"""
R3 Stage-2a-extended v1.5-scalp-only trader: 6-voucher RV scalp + base-IV
mean reversion. NO VEV underlying trading (Module C stripped).

Diff vs v1.4:
  - Module C (VEV delta hedge + EMA50 mean-reversion overlay) removed.
    No orders are emitted for VELVETFRUIT_EXTRACT.
  - net_voucher_delta is still computed and logged (visibility) but not
    acted on. Hedge will be re-introduced as a separate trader at the
    integration step.
  - Hedge-related config keys removed from configs/vev_v1.5-scalp-only.json
    (vev_hedge_target_band, vev_overlay_*, vev_position_limit,
    hedge_passive_wait_ticks).
  - Trader prefers configs/vev_v1.5-scalp-only.json; falls back to
    configs/vev_v1.json; finally to inlined CONFIG. All via pathlib only
    (Hard Rule #10: NEVER use `import os` or `from os import ...`).
  - Lambda-log instrumented with full smile coefs (a,b,c) and per-strike
    passive/aggressive routing flags so Stage-2a-extended diagnostics
    can attribute fills without re-running.

Inherits from v1.1-v1.4: min_hold/cooldown gating, passive-first
execution, max_step_size cap, per-day current_day routing.
"""

from datamodel import OrderDepth, TradingState, Order  # type: ignore
from typing import Dict, List, Optional, Tuple
import json
import math
from statistics import NormalDist

# ---- Symbol set --------------------------------------------------------------
PRODUCT_VEV = "VELVETFRUIT_EXTRACT"
HYDROGEL = "HYDROGEL_PACK"  # explicitly ignored (separate trader)

ALL_VOUCHER_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
def voucher_symbol(K: int) -> str:
    return f"VEV_{K}"

# ---- Config -----------------------------------------------------------------
# Inlined for IMC submission. Mirror of configs/vev_v1.5-scalp-only.json.
CONFIG = {
    "active_strikes": [5000, 5100, 5200, 5300, 5400, 5500],
    "smile_fit_min_strikes": 4,
    "smile_hardcoded_fallback": {"a": 0.143, "b": -0.002, "c": 0.236},
    "ema_demean_window": 20,
    "zscore_stdev_window": 100,
    "z_open_threshold": 1.5,
    "z_close_threshold": 0.5,
    "strike_position_caps": {
        "5000": 60, "5100": 80, "5200": 120, "5300": 120, "5400": 80, "5500": 60,
    },
    "base_iv_zscore_window": 500,
    "base_iv_z_open": 1.5,
    "base_iv_z_close": 0.5,
    "base_iv_position_size": 25,
    "voucher_position_limit": 300,
    "round_day_to_tte_days": {"0": 8, "1": 7, "2": 6, "3": 5, "4": 4, "5": 3},
    "current_day": 0,
    "min_hold_ticks": 5,
    "cooldown_ticks": 10,
    "passive_wait_ticks": 3,
    "aggressive_z_threshold": 2.5,
    "max_step_size": 10,
}

# Local-dev override: prefer the v1.5-only config file, fall back to v1.0
# config (so older scripts that overwrite vev_v1.json keep working), then
# fall back to inlined CONFIG. pathlib only -- Hard Rule #10.
try:
    from pathlib import Path as _Path
    _here = _Path(__file__).parent / "configs"
    for _name in ("vev_v1.5-scalp-only.json", "vev_v1.json"):
        _p = _here / _name
        if _p.is_file():
            with open(_p, "r") as _f:
                CONFIG = json.load(_f)
            break
    # Per-day current_day override (written by backtest wrapper).
    _day_path = _here / "_current_day.txt"
    if _day_path.is_file():
        with open(_day_path, "r") as _f:
            _d = _f.read().strip()
            if _d:
                CONFIG["current_day"] = int(_d)
except (NameError, FileNotFoundError, OSError, ValueError):
    pass


# ---- Black-Scholes (r=0, no divs) -------------------------------------------
_N = NormalDist()

def bs_call(S: float, K: float, T: float, sigma: float) -> Tuple[float, float, float]:
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0:
        intrinsic = max(0.0, S - K)
        return intrinsic, (1.0 if S > K else 0.0), 0.0
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    Nd1 = _N.cdf(d1)
    Nd2 = _N.cdf(d2)
    pdfd1 = _N.pdf(d1)
    price = S * Nd1 - K * Nd2
    delta = Nd1
    vega = S * pdfd1 * sqrtT
    return price, delta, vega


def solve_iv(market_price: float, S: float, K: float, T: float,
             initial: float = 0.23) -> Optional[float]:
    intrinsic = max(0.0, S - K)
    if market_price <= intrinsic + 1e-6 or market_price >= S:
        return None
    sigma = max(initial, 0.05)
    for _ in range(20):
        price, _, vega = bs_call(S, K, T, sigma)
        diff = price - market_price
        if abs(diff) < 1e-5:
            return sigma
        if vega < 1e-6:
            break
        step = diff / vega
        sigma_new = sigma - step
        if sigma_new <= 0.0 or sigma_new > 5.0:
            break
        if abs(sigma_new - sigma) < 1e-7:
            return sigma_new
        sigma = sigma_new
    lo, hi = 0.01, 2.0
    p_lo, _, _ = bs_call(S, K, T, lo)
    p_hi, _, _ = bs_call(S, K, T, hi)
    if (p_lo - market_price) * (p_hi - market_price) > 0.0:
        return None
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        p_mid, _, _ = bs_call(S, K, T, mid)
        if abs(p_mid - market_price) < 1e-5:
            return mid
        if (p_lo - market_price) * (p_mid - market_price) <= 0.0:
            hi = mid
            p_hi = p_mid
        else:
            lo = mid
            p_lo = p_mid
    return 0.5 * (lo + hi)


def fit_quadratic_smile(ms: List[float], ivs: List[float]) -> Optional[Tuple[float, float, float]]:
    n = len(ms)
    if n < 3 or n != len(ivs):
        return None
    s0 = float(n)
    s1 = sum(ms)
    s2 = sum(x * x for x in ms)
    s3 = sum(x * x * x for x in ms)
    s4 = sum(x * x * x * x for x in ms)
    t0 = sum(ivs)
    t1 = sum(x * y for x, y in zip(ms, ivs))
    t2 = sum(x * x * y for x, y in zip(ms, ivs))
    M = [[s4, s3, s2, t2],
         [s3, s2, s1, t1],
         [s2, s1, s0, t0]]
    for i in range(3):
        piv = i
        for k in range(i + 1, 3):
            if abs(M[k][i]) > abs(M[piv][i]):
                piv = k
        if piv != i:
            M[i], M[piv] = M[piv], M[i]
        if abs(M[i][i]) < 1e-12:
            return None
        for k in range(i + 1, 3):
            f = M[k][i] / M[i][i]
            for j in range(i, 4):
                M[k][j] -= f * M[i][j]
    c = M[2][3] / M[2][2]
    b = (M[1][3] - M[1][2] * c) / M[1][1]
    a = (M[0][3] - M[0][1] * b - M[0][2] * c) / M[0][0]
    return a, b, c


def smile_iv(coefs: Tuple[float, float, float], m: float) -> float:
    a, b, c = coefs
    return a * m * m + b * m + c


# ---- Order book helpers ------------------------------------------------------
def best_bid_ask(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
    bid = max(depth.buy_orders) if depth.buy_orders else None
    ask = min(depth.sell_orders) if depth.sell_orders else None
    return bid, ask


def book_mid(depth: OrderDepth) -> Optional[float]:
    bb, ba = best_bid_ask(depth)
    if bb is None or ba is None:
        return None
    return 0.5 * (bb + ba)


def emit_passive_or_marketable(symbol: str, depth: OrderDepth, current_pos: int,
                               target_pos: int, escalate: bool) -> List[Order]:
    """Passive-first: post limit at our touch by default. Escalate to
    marketable (cross spread) when caller flags. Rust matching model
    (runner.rs L612-658) confirms a buy at best_bid will not cross any
    ask; it only fills via market-trade flow at our limit price."""
    diff = target_pos - current_pos
    if diff == 0:
        return []
    bb, ba = best_bid_ask(depth)
    if bb is None or ba is None:
        return []
    if escalate:
        if diff > 0:
            avail = -depth.sell_orders.get(ba, 0)
            qty = min(diff, avail)
            return [Order(symbol, ba, qty)] if qty > 0 else []
        else:
            avail = depth.buy_orders.get(bb, 0)
            qty = min(-diff, avail)
            return [Order(symbol, bb, -qty)] if qty > 0 else []
    else:
        if diff > 0:
            return [Order(symbol, bb, diff)]
        else:
            return [Order(symbol, ba, diff)]


# ---- Trader ------------------------------------------------------------------
class Trader:
    def run(self, state: TradingState):
        cfg = CONFIG

        try:
            saved = json.loads(state.traderData) if state.traderData else {}
        except Exception as e:
            saved = {"_traderData_error": repr(e)}

        # ---- TTE -----------------------------------------------------------
        current_day = int(cfg.get("current_day", 0))
        tte_days_at_start = cfg["round_day_to_tte_days"][str(current_day)]
        tf = state.timestamp / 1_000_000.0
        T = max((tte_days_at_start - tf) / 365.0, 1e-6)

        # ---- VEV mid (used as S only; no VEV trading) ----------------------
        vev_depth = state.order_depths.get(PRODUCT_VEV)
        vev_mid = book_mid(vev_depth) if vev_depth is not None else None
        if vev_mid is None:
            return {}, 0, json.dumps(saved)
        S = float(vev_mid)

        # ---- Per-strike inputs --------------------------------------------
        active_strikes: List[int] = cfg["active_strikes"]
        voucher_depths: Dict[int, OrderDepth] = {}
        voucher_mids: Dict[int, float] = {}
        for K in active_strikes:
            sym = voucher_symbol(K)
            d = state.order_depths.get(sym)
            if d is None:
                continue
            mid = book_mid(d)
            if mid is None:
                continue
            voucher_depths[K] = d
            voucher_mids[K] = mid

        # ---- IV inversion + smile fit -------------------------------------
        ivs_per_strike: Dict[int, float] = {}
        moneyness_per_strike: Dict[int, float] = {}
        for K, mid in voucher_mids.items():
            m = math.log(K / S) / math.sqrt(T)
            iv = solve_iv(mid, S, K, T)
            moneyness_per_strike[K] = m
            if iv is not None:
                ivs_per_strike[K] = iv

        min_strikes = int(cfg["smile_fit_min_strikes"])
        smile_coefs: Optional[Tuple[float, float, float]] = None
        if len(ivs_per_strike) >= min_strikes:
            ms = [moneyness_per_strike[K] for K in ivs_per_strike]
            ivs = [ivs_per_strike[K] for K in ivs_per_strike]
            smile_coefs = fit_quadratic_smile(ms, ivs)
        if smile_coefs is None:
            last = saved.get("last_smile")
            if last is not None:
                smile_coefs = (last["a"], last["b"], last["c"])
            else:
                hc = cfg["smile_hardcoded_fallback"]
                smile_coefs = (hc["a"], hc["b"], hc["c"])
        if len(ivs_per_strike) >= min_strikes:
            saved["last_smile"] = {"a": smile_coefs[0], "b": smile_coefs[1], "c": smile_coefs[2]}

        # ---- Per-strike residuals + EMA demean + Z-score ------------------
        ema_window = int(cfg["ema_demean_window"])
        ema_alpha = 2.0 / (ema_window + 1.0)
        z_window = int(cfg["zscore_stdev_window"])

        vouchers_state: dict = saved.get("vouchers", {})
        z_scores: Dict[int, float] = {}
        deltas_per_strike: Dict[int, float] = {}
        residuals_per_strike: Dict[int, float] = {}
        for K, mid in voucher_mids.items():
            m = moneyness_per_strike[K]
            iv_smile = smile_iv(smile_coefs, m)
            theo, delta, _ = bs_call(S, K, T, iv_smile)
            deltas_per_strike[K] = delta
            resid = mid - theo
            residuals_per_strike[K] = resid

            st = vouchers_state.get(str(K), {})
            ema = st.get("resid_ema")
            ema = resid if ema is None else ema_alpha * resid + (1.0 - ema_alpha) * ema
            demeaned = resid - ema
            buf = st.get("dem_buf", [])
            buf.append(demeaned)
            if len(buf) > z_window:
                buf = buf[-z_window:]
            z = 0.0
            if len(buf) >= 20:
                mu = sum(buf) / len(buf)
                var = sum((x - mu) ** 2 for x in buf) / max(len(buf) - 1, 1)
                sd = math.sqrt(var) if var > 0 else 0.0
                if sd > 1e-9:
                    z = (demeaned - mu) / sd
            z_scores[K] = z
            vouchers_state[str(K)] = {"resid_ema": ema, "dem_buf": buf}
        saved["vouchers"] = vouchers_state

        # ---- Module A: per-strike scalp targets (with v1.1 hold/cooldown) -
        z_open = float(cfg["z_open_threshold"])
        z_close = float(cfg["z_close_threshold"])
        strike_caps: Dict[str, int] = cfg["strike_position_caps"]

        tick_count = int(saved.get("tick_count", 0))
        saved["tick_count"] = tick_count + 1
        min_hold = int(cfg.get("min_hold_ticks", 0))
        cooldown = int(cfg.get("cooldown_ticks", 0))
        a_meta: Dict[str, int] = saved.get("module_a_meta", {})

        module_a_targets: Dict[int, int] = {}
        prev_a = saved.get("module_a_pos", {})
        for K in active_strikes:
            cap = int(strike_caps.get(str(K), 0))
            prev = int(prev_a.get(str(K), 0))
            prev_dir = 1 if prev > 0 else (-1 if prev < 0 else 0)
            z = z_scores.get(K, 0.0)
            if z < -z_open:
                desired = cap
            elif z > z_open:
                desired = -cap
            elif abs(z) < z_close:
                desired = 0
            else:
                desired = prev
            desired_dir = 1 if desired > 0 else (-1 if desired < 0 else 0)
            last_change = int(a_meta.get(str(K), -10**9))
            ticks_since = tick_count - last_change
            if desired_dir != prev_dir:
                if prev_dir == 0:
                    if ticks_since < cooldown:
                        desired = prev
                        desired_dir = prev_dir
                else:
                    if ticks_since < min_hold:
                        desired = prev
                        desired_dir = prev_dir
            if desired_dir != prev_dir:
                a_meta[str(K)] = tick_count
            module_a_targets[K] = desired
        saved["module_a_meta"] = a_meta
        saved["module_a_pos"] = {str(K): v for K, v in module_a_targets.items()}

        # ---- Module B: base-IV mean reversion -----------------------------
        base_iv_window = int(cfg["base_iv_zscore_window"])
        base_iv_z_open = float(cfg["base_iv_z_open"])
        base_iv_z_close = float(cfg["base_iv_z_close"])
        base_iv_size = int(cfg["base_iv_position_size"])

        c_t = smile_coefs[2]
        c_buf: List[float] = saved.get("base_iv_buf", [])
        c_buf.append(c_t)
        if len(c_buf) > base_iv_window:
            c_buf = c_buf[-base_iv_window:]
        saved["base_iv_buf"] = c_buf

        module_b_targets: Dict[int, int] = {5200: 0, 5300: 0}
        prev_b = saved.get("module_b_pos", {"5200": 0, "5300": 0})
        z_c_val = 0.0
        if len(c_buf) >= 50:
            mu = sum(c_buf) / len(c_buf)
            var = sum((x - mu) ** 2 for x in c_buf) / max(len(c_buf) - 1, 1)
            sd = math.sqrt(var) if var > 0 else 0.0
            z_c_val = (c_t - mu) / sd if sd > 1e-9 else 0.0
            if z_c_val > base_iv_z_open:
                module_b_targets = {5200: -base_iv_size, 5300: -base_iv_size}
            elif z_c_val < -base_iv_z_open:
                module_b_targets = {5200: base_iv_size, 5300: base_iv_size}
            elif abs(z_c_val) < base_iv_z_close:
                module_b_targets = {5200: 0, 5300: 0}
            else:
                module_b_targets = {5200: int(prev_b.get("5200", 0)),
                                    5300: int(prev_b.get("5300", 0))}
        saved["module_b_pos"] = {str(K): v for K, v in module_b_targets.items()}

        # ---- Combined voucher targets, per-strike clamped -----------------
        voucher_limit = int(cfg["voucher_position_limit"])
        combined_voucher_targets: Dict[int, int] = {}
        for K in active_strikes:
            cap_k = int(strike_caps.get(str(K), 0))
            a = module_a_targets.get(K, 0)
            b = module_b_targets.get(K, 0)
            tgt = max(-cap_k, min(cap_k, a + b))
            tgt = max(-voucher_limit, min(voucher_limit, tgt))
            combined_voucher_targets[K] = tgt

        # ---- Net voucher delta (logging only; no hedge) -------------------
        net_voucher_delta = 0.0
        for K, tgt in combined_voucher_targets.items():
            net_voucher_delta += tgt * deltas_per_strike.get(K, 0.0)

        # ---- Build orders (passive-first, max_step capped) ----------------
        aggressive_z = float(cfg.get("aggressive_z_threshold", 2.5))
        max_step = int(cfg.get("max_step_size", 10))
        result: Dict[str, List[Order]] = {}

        def _clip_step(cur: int, tgt: int) -> int:
            d = tgt - cur
            if d > max_step:
                return cur + max_step
            if d < -max_step:
                return cur - max_step
            return tgt

        # Diagnostics: per-tick passive vs aggressive routing decision per K.
        pas_strikes: List[int] = []
        agg_strikes: List[int] = []

        # Per-strike pending-tick counter: counts ticks since the (clipped)
        # step target first differed from current position. Used for the
        # passive_wait_ticks escalation path. Reset to 0 once filled.
        pending_wait: Dict[str, int] = saved.get("pending_wait", {})
        passive_wait_ticks = int(cfg.get("passive_wait_ticks", 3))

        for K, tgt in combined_voucher_targets.items():
            sym = voucher_symbol(K)
            depth = voucher_depths.get(K)
            if depth is None:
                continue
            cur = state.position.get(sym, 0)
            tgt_step = _clip_step(cur, tgt)
            # Update pending counter against the *step* target (what we
            # actually try to reach this tick).
            if cur == tgt_step:
                pending_wait[sym] = 0
            else:
                pending_wait[sym] = int(pending_wait.get(sym, 0)) + 1
            waited = int(pending_wait.get(sym, 0))

            z_strong = abs(z_scores.get(K, 0.0)) >= aggressive_z
            if K in (5200, 5300):
                z_strong = z_strong or (abs(z_c_val) >= aggressive_z)
            # Spec semantics: escalate only when signal is strong AND we've
            # already waited passively for at least passive_wait_ticks.
            # Smaller wait => more eager to take liquidity once signal fires.
            # Larger wait => stay patient even on strong signal.
            escalate = z_strong and (waited >= passive_wait_ticks)

            orders = emit_passive_or_marketable(sym, depth, cur, tgt_step, escalate=escalate)
            if orders:
                result[sym] = orders
                if escalate:
                    agg_strikes.append(K)
                else:
                    pas_strikes.append(K)
        saved["pending_wait"] = pending_wait

        # NOTE: no orders for VELVETFRUIT_EXTRACT (Module C stripped).

        # ---- Paper PnL attribution (Modules A and B only) -----------------
        last_mids: dict = saved.get("last_mids", {})
        prev_a_pos = saved.get("prev_module_a_pos", {})
        prev_b_pos = saved.get("prev_module_b_pos", {"5200": 0, "5300": 0})
        pnl_a = float(saved.get("module_a_pnl_paper", 0.0))
        pnl_b = float(saved.get("module_b_pnl_paper", 0.0))
        for K in active_strikes:
            sym = voucher_symbol(K)
            mid = voucher_mids.get(K)
            if mid is None:
                continue
            last_mid = last_mids.get(sym)
            if last_mid is not None:
                dprice = mid - last_mid
                pnl_a += int(prev_a_pos.get(str(K), 0)) * dprice
                if str(K) in prev_b_pos:
                    pnl_b += int(prev_b_pos.get(str(K), 0)) * dprice
            last_mids[sym] = mid
        last_mids[PRODUCT_VEV] = S
        saved["last_mids"] = last_mids
        saved["prev_module_a_pos"] = saved["module_a_pos"]
        saved["prev_module_b_pos"] = saved["module_b_pos"]
        saved["module_a_pnl_paper"] = pnl_a
        saved["module_b_pnl_paper"] = pnl_b

        # ---- Lambda log (per-tick) ----------------------------------------
        # Includes full smile coefs (a,b) and per-strike passive/aggressive
        # routing flags for Stage-2a-extended diagnostics.
        try:
            print(json.dumps({
                "ts": state.timestamp,
                "S": round(S, 2),
                "a": round(smile_coefs[0], 5),
                "b": round(smile_coefs[1], 5),
                "c": round(smile_coefs[2], 5),
                "nv_d": round(net_voucher_delta, 2),
                "z_c": round(z_c_val, 3),
                "pas": pas_strikes,
                "agg": agg_strikes,
                "z": {str(K): round(z_scores.get(K, 0.0), 2) for K in active_strikes},
                "tgt": {str(K): combined_voucher_targets[K] for K in active_strikes},
                "a_pnl": round(pnl_a, 1),
                "b_pnl": round(pnl_b, 1),
            }))
        except Exception:
            pass

        return result, 0, json.dumps(saved)
