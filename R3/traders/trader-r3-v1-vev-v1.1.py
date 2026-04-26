"""
R3 Stage-2a v1.1 trader: VEV ecosystem (VELVETFRUIT_EXTRACT + 6 vouchers).

Diff vs v1.0: Module A per-strike targets are gated by min_hold_ticks and
cooldown_ticks. Same signal logic, same execution (still marketable).
Goal: cut trade-frequency thrash (35k/day -> target ~10-15k/day) by
forbidding direction flips/closes within min_hold_ticks of an open and
re-opens within cooldown_ticks of a close. Hedge churn drops as a
side-effect because voucher targets stop flipping every tick.

Original v1.0 docstring follows.

R3 Stage-1 baseline trader: VEV ecosystem (VELVETFRUIT_EXTRACT + 6 vouchers).

HYDROGEL_PACK is handled in a separate trader file and is fully ignored here.

Three modules in one Trader class:

  A. Voucher IV scalper across 6 active strikes (5000, 5100, 5200, 5300, 5400, 5500).
     Per tick: solve IV from market mid, fit a quadratic smile in
     m = log(K/S)/sqrt(T), compute price residual, EMA20-demean, z-score over
     100 ticks, open at |z|>1.5, close at |z|<0.5.

  B. Base-IV mean reversion overlay on smile intercept c_t over a 500-tick
     z-score, trades ATM vouchers (5200/5300) when |z|>1.5. Adds onto Module A.

  C. VEV underlying. Two roles sharing the +/-200 limit:
       1. Delta hedge (priority): target VEV = -round(net voucher delta) using
          BS deltas under the fitted-smile IV.
       2. EMA50 mean-reversion overlay on VEV mid (N1 lag-1 ACF = -0.159).
     Hard rule: |net portfolio delta (vouchers + VEV)| <= 50; hedging wins ties.

All parameters live in configs/vev_v1.json. Each parameter has a code comment
citing the EDA finding that justified the default.
"""

from datamodel import OrderDepth, TradingState, Order  # type: ignore
from typing import Dict, List, Optional, Tuple
import json
import math
from statistics import NormalDist

# ---- Symbol set --------------------------------------------------------------
PRODUCT_VEV = "VELVETFRUIT_EXTRACT"
HYDROGEL = "HYDROGEL_PACK"  # explicitly ignored (separate trader)

# active_strikes: N2 cell 18 + N3 cell 16 + N4 cell 32 all converge on dropping
# {4000, 4500} (intrinsic-only) and {6000, 6500} (pinned at 0.5 floor).
ALL_VOUCHER_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
def voucher_symbol(K: int) -> str:
    return f"VEV_{K}"

# ---- Config -----------------------------------------------------------------
# Inlined for IMC submission (only this single .py file is uploaded). Values
# below MUST stay in sync with R3/traders/configs/vev_v1.json, which the
# local-dev override block immediately below reads when present.
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
    "vev_hedge_target_band": 50,
    "vev_overlay_max_size": 50,
    "vev_overlay_ema_window": 50,
    "vev_overlay_threshold": 1.0,
    "voucher_position_limit": 300,
    "vev_position_limit": 200,
    "tte_days_per_round_day": 1.0,
    "round_day_to_tte_days": {"0": 8, "1": 7, "2": 6, "3": 5, "4": 4, "5": 3},
    "current_day": 0,
}

# Local-dev override: if configs/vev_v1.json sits next to this file, reload
# CONFIG from it so JSON edits take effect without touching the .py. On the
# IMC sandbox the JSON is not uploaded and __file__ resolution may differ;
# fall back to the inlined CONFIG above. Documented exception per Hard Rule #7.
try:
    from pathlib import Path as _Path
    _cfg_path = _Path(__file__).parent / "configs" / "vev_v1.json"
    if _cfg_path.is_file():
        with open(_cfg_path, "r") as _f:
            CONFIG = json.load(_f)
except (NameError, FileNotFoundError, OSError):
    pass


# ---- Black-Scholes (r=0, no divs) -------------------------------------------
_N = NormalDist()  # statistics.NormalDist gives cdf+pdf without scipy.

def bs_call(S: float, K: float, T: float, sigma: float) -> Tuple[float, float, float]:
    """Black-Scholes European call (r=0). Returns (price, delta, vega)."""
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
    """Newton-Raphson on vega; bisection fallback on [0.01, 2.0].
    Returns IV or None if both fail / problem is ill-posed.
    Initial guess 0.23 = N3 pooled c_t intercept (cell 23)."""
    intrinsic = max(0.0, S - K)
    if market_price <= intrinsic + 1e-6 or market_price >= S:
        # Below intrinsic or above the no-arbitrage upper bound (call <= S).
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
    # Bisection fallback
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
    """Least-squares fit v(m) = a*m^2 + b*m + c. Returns (a, b, c) or None.
    Solves the 3x3 normal-equations system via Gaussian elimination -- fast
    enough for n<=10 strikes and avoids a numpy dependency."""
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
    # Normal equations: [s4 s3 s2; s3 s2 s1; s2 s1 s0] [a;b;c] = [t2; t1; t0]
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


def emit_to_target(symbol: str, depth: OrderDepth, current_pos: int,
                   target_pos: int) -> List[Order]:
    """Generate marketable order(s) to move current_pos toward target_pos by
    walking the opposite-side book. Returns at most one Order at a single price
    level (the best opposite price), bounded by available volume."""
    diff = target_pos - current_pos
    if diff == 0:
        return []
    if diff > 0:
        # Buy: lift best ask
        if not depth.sell_orders:
            return []
        best_ask = min(depth.sell_orders)
        avail = -depth.sell_orders[best_ask]  # sell volumes are negative
        qty = min(diff, avail)
        if qty <= 0:
            return []
        return [Order(symbol, best_ask, qty)]
    else:
        if not depth.buy_orders:
            return []
        best_bid = max(depth.buy_orders)
        avail = depth.buy_orders[best_bid]
        qty = min(-diff, avail)
        if qty <= 0:
            return []
        return [Order(symbol, best_bid, -qty)]


# ---- Trader ------------------------------------------------------------------
class Trader:
    def run(self, state: TradingState):
        cfg = CONFIG

        # ---- Restore persisted state ---------------------------------------
        # No silent error handling (Hard Rule #7): a corrupt traderData would
        # only happen at process boot, so reset and surface it once.
        try:
            saved = json.loads(state.traderData) if state.traderData else {}
        except Exception as e:
            saved = {"_traderData_error": repr(e)}

        # ---- TTE -----------------------------------------------------------
        # current_day: each rust-backtester run is a single historical day with
        # a fresh trader process and timestamp resetting to 0; the trader cannot
        # self-detect day. Stage 1 default = 0 (TTE start = 8d). For the live
        # R3 round set this to 3 -> TTE = 5d. Per-day backtest precision is
        # acknowledged as a Stage-1 limitation; max delta error across days
        # is ~13% (vega ratio sqrt(6/8) = 0.866).
        current_day = int(cfg.get("current_day", 0))
        # round_day_to_tte_days: spec, derived from TTE schedule (CLAUDE.md).
        tte_days_at_start = cfg["round_day_to_tte_days"][str(current_day)]
        # FH formula simplifies to (tte_days_at_start - tf)/365 with tf in [0,1).
        tf = state.timestamp / 1_000_000.0
        T = max((tte_days_at_start - tf) / 365.0, 1e-6)

        # ---- VEV mid -------------------------------------------------------
        vev_depth = state.order_depths.get(PRODUCT_VEV)
        vev_mid = book_mid(vev_depth) if vev_depth is not None else None
        if vev_mid is None:
            # Cannot compute IVs / hedge without an underlying mid -> persist
            # state and skip this tick.
            return {}, 0, json.dumps(saved)
        S = float(vev_mid)

        # ---- Per-strike inputs --------------------------------------------
        # active_strikes: N2/N3/N4 strike triage (see header comment).
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

        # smile_fit_min_strikes=4: spec; below this, fall back to last fit or
        # the hardcoded N4-pooled coefficients.
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
                # smile_hardcoded_fallback: N4 cell 11 pooled fit
                # (a=0.143, b=-0.002, c=0.236; n=251,785; R^2=0.9836).
                # Note: N3 pooled fit is (0.158, -0.0046, 0.232) under EPS_EXT=0.5;
                # spec selected the N4 version. Difference is <1.5% IV at |m|<0.1.
                hc = cfg["smile_hardcoded_fallback"]
                smile_coefs = (hc["a"], hc["b"], hc["c"])
        # Persist last_smile only if this tick actually produced a fresh fit.
        # (Falling back to previous shouldn't overwrite the stored "last".)
        if len(ivs_per_strike) >= min_strikes:
            saved["last_smile"] = {"a": smile_coefs[0], "b": smile_coefs[1], "c": smile_coefs[2]}

        # ---- Per-strike residuals + EMA demean + Z-score ------------------
        # ema_demean_window=20: N4 cell 29 -- EMA20 demean flips ATM lag-1
        # autocorr from +0.81 to -0.04/-0.02 (load-bearing for IV scalp).
        ema_window = int(cfg["ema_demean_window"])
        ema_alpha = 2.0 / (ema_window + 1.0)
        # zscore_stdev_window=100: starting point for rolling stdev; will be
        # swept Stage 2 (N4 cell 22 used 200-tick rolling window).
        z_window = int(cfg["zscore_stdev_window"])

        vouchers_state: dict = saved.get("vouchers", {})
        z_scores: Dict[int, float] = {}
        deltas_per_strike: Dict[int, float] = {}
        for K, mid in voucher_mids.items():
            m = moneyness_per_strike[K]
            iv_smile = smile_iv(smile_coefs, m)
            theo, delta, _ = bs_call(S, K, T, iv_smile)
            deltas_per_strike[K] = delta
            resid = mid - theo

            st = vouchers_state.get(str(K), {})
            ema = st.get("resid_ema")
            ema = resid if ema is None else ema_alpha * resid + (1.0 - ema_alpha) * ema
            demeaned = resid - ema
            buf = st.get("dem_buf", [])
            buf.append(demeaned)
            if len(buf) > z_window:
                buf = buf[-z_window:]
            # Z-score: only meaningful once the buffer has filled enough to
            # estimate stdev (>= 20 samples).
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

        # ---- Module A: per-strike scalp targets ---------------------------
        # z_open=1.5, z_close=0.5, per-strike caps from N4 cell 38 hedge math.
        z_open = float(cfg["z_open_threshold"])
        z_close = float(cfg["z_close_threshold"])
        strike_caps: Dict[str, int] = cfg["strike_position_caps"]

        # v1.1 additions: per-strike min_hold/cooldown gating to cut churn.
        # min_hold_ticks: once a position is opened (dir != 0), forbid any
        #   direction change (including close) for this many ticks. Captures
        #   that the IV scalp signal half-life is longer than the noise-driven
        #   z-crossings producing 35k trades/day in v1.0.
        # cooldown_ticks: once a position is closed back to flat, forbid
        #   re-opening for this many ticks. Damps the open-close-open thrash.
        # Tick counter is incremented per call; resilient to non-uniform
        # timestamp spacing (timestamps go up by 100/tick in IMC, but using
        # an explicit counter avoids coupling to that constant).
        tick_count = int(saved.get("tick_count", 0))
        saved["tick_count"] = tick_count + 1
        min_hold = int(cfg.get("min_hold_ticks", 0))
        cooldown = int(cfg.get("cooldown_ticks", 0))
        # a_meta[str(K)] = last_change_tick (when dir last changed; default -inf
        # equivalent so initial entries never blocked).
        a_meta: Dict[str, int] = saved.get("module_a_meta", {})

        module_a_targets: Dict[int, int] = {}
        prev_a = saved.get("module_a_pos", {})
        for K in active_strikes:
            cap = int(strike_caps.get(str(K), 0))
            prev = int(prev_a.get(str(K), 0))
            prev_dir = 1 if prev > 0 else (-1 if prev < 0 else 0)
            z = z_scores.get(K, 0.0)

            # Raw signal target (same as v1.0).
            if z < -z_open:
                desired = cap
            elif z > z_open:
                desired = -cap
            elif abs(z) < z_close:
                desired = 0
            else:
                desired = prev  # hold band

            desired_dir = 1 if desired > 0 else (-1 if desired < 0 else 0)
            last_change = int(a_meta.get(str(K), -10**9))
            ticks_since = tick_count - last_change

            # Gate: any direction change must respect hold (if currently
            # holding) or cooldown (if currently flat).
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

        # ---- Module B: base-IV mean reversion (separate, additive) -------
        # base_iv_zscore_window=500: N4 cell 26 -- z-scalp on c_t over 500
        # ticks gave +2,490 in-sample PnL.
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
        if len(c_buf) >= 50:
            mu = sum(c_buf) / len(c_buf)
            var = sum((x - mu) ** 2 for x in c_buf) / max(len(c_buf) - 1, 1)
            sd = math.sqrt(var) if var > 0 else 0.0
            z_c = (c_t - mu) / sd if sd > 1e-9 else 0.0
            # Elevated base IV -> options expensive -> short ATM. Depressed -> long.
            if z_c > base_iv_z_open:
                module_b_targets = {5200: -base_iv_size, 5300: -base_iv_size}
            elif z_c < -base_iv_z_open:
                module_b_targets = {5200: base_iv_size, 5300: base_iv_size}
            elif abs(z_c) < base_iv_z_close:
                module_b_targets = {5200: 0, 5300: 0}
            else:
                module_b_targets = {5200: int(prev_b.get("5200", 0)),
                                    5300: int(prev_b.get("5300", 0))}
        saved["module_b_pos"] = {str(K): v for K, v in module_b_targets.items()}

        # ---- Combined voucher targets, per-strike clamped ----------------
        voucher_limit = int(cfg["voucher_position_limit"])
        combined_voucher_targets: Dict[int, int] = {}
        for K in active_strikes:
            cap_k = int(strike_caps.get(str(K), 0))
            a = module_a_targets.get(K, 0)
            b = module_b_targets.get(K, 0)
            tgt = max(-cap_k, min(cap_k, a + b))
            tgt = max(-voucher_limit, min(voucher_limit, tgt))
            combined_voucher_targets[K] = tgt

        # ---- Module C part 1: delta hedge ---------------------------------
        # Net voucher delta from combined targets * BS delta(fitted IV).
        net_voucher_delta = 0.0
        for K, tgt in combined_voucher_targets.items():
            net_voucher_delta += tgt * deltas_per_strike.get(K, 0.0)
        # Hedge target for VEV: short the voucher delta so net portfolio
        # delta lies within +/- vev_hedge_target_band (=50 per spec).
        vev_pos_limit = int(cfg["vev_position_limit"])
        hedge_band = int(cfg["vev_hedge_target_band"])
        # Unconstrained hedge: VEV = -round(net_voucher_delta).
        hedge_unc = -int(round(net_voucher_delta))
        # Bound to VEV position limit; if even maxed-out hedge can't bring net
        # delta into +/- band, hedging still wins (no overlay added on top).
        hedge_target = max(-vev_pos_limit, min(vev_pos_limit, hedge_unc))

        # ---- Module C part 2: VEV EMA-fade overlay -----------------------
        # vev_overlay_ema_window=50: N1 cell 19 reports VEV demeaned half-life
        # 248 ticks; an EMA50 (alpha~0.039) sits well inside that. Overlay
        # leans against deviation in the direction of mean-reversion.
        ovl_window = int(cfg["vev_overlay_ema_window"])
        ovl_alpha = 2.0 / (ovl_window + 1.0)
        ovl_thr = float(cfg["vev_overlay_threshold"])
        ovl_max = int(cfg["vev_overlay_max_size"])
        vev_ema = saved.get("vev_ema")
        vev_ema = S if vev_ema is None else ovl_alpha * S + (1.0 - ovl_alpha) * vev_ema
        saved["vev_ema"] = vev_ema
        # Rolling stdev of (S - vev_ema) for z-scaling. Keep last 200 dev samples.
        vev_dev_buf: List[float] = saved.get("vev_dev_buf", [])
        dev = S - vev_ema
        vev_dev_buf.append(dev)
        if len(vev_dev_buf) > 200:
            vev_dev_buf = vev_dev_buf[-200:]
        saved["vev_dev_buf"] = vev_dev_buf

        overlay_target = 0
        if len(vev_dev_buf) >= 50:
            mu = sum(vev_dev_buf) / len(vev_dev_buf)
            var = sum((x - mu) ** 2 for x in vev_dev_buf) / max(len(vev_dev_buf) - 1, 1)
            sd = math.sqrt(var) if var > 0 else 0.0
            z_v = (dev - mu) / sd if sd > 1e-9 else 0.0
            # Mean-revert: if VEV above its EMA, fade short (and vice versa).
            if z_v > ovl_thr:
                overlay_target = -ovl_max
            elif z_v < -ovl_thr:
                overlay_target = ovl_max

        # Combine hedge + overlay, clamp to VEV limit.
        vev_combined_target = hedge_target + overlay_target
        vev_combined_target = max(-vev_pos_limit, min(vev_pos_limit, vev_combined_target))

        # Hard rule: net portfolio delta within +/- hedge_band. If the combined
        # VEV target would push net delta outside the band, drop the overlay.
        net_delta_with_combined = net_voucher_delta + vev_combined_target
        if abs(net_delta_with_combined) > hedge_band:
            # Hedging wins -- drop the overlay component.
            vev_combined_target = max(-vev_pos_limit, min(vev_pos_limit, hedge_target))
            net_delta_with_combined = net_voucher_delta + vev_combined_target

        # ---- Build orders -------------------------------------------------
        result: Dict[str, List[Order]] = {}

        for K, tgt in combined_voucher_targets.items():
            sym = voucher_symbol(K)
            depth = voucher_depths.get(K)
            if depth is None:
                continue
            cur = state.position.get(sym, 0)
            orders = emit_to_target(sym, depth, cur, tgt)
            if orders:
                result[sym] = orders

        cur_vev = state.position.get(PRODUCT_VEV, 0)
        vev_orders = emit_to_target(PRODUCT_VEV, vev_depth, cur_vev, vev_combined_target)
        if vev_orders:
            result[PRODUCT_VEV] = vev_orders

        # ---- Paper PnL attribution (Stage 1 best-effort) ------------------
        # True per-module PnL requires per-fill tagging which the IMC interface
        # doesn't support. Approximation: mark each module's prior-tick shadow
        # position to current mid.
        last_mids: dict = saved.get("last_mids", {})
        prev_a_pos = saved.get("prev_module_a_pos", {})
        prev_b_pos = saved.get("prev_module_b_pos", {"5200": 0, "5300": 0})
        prev_c_pos = int(saved.get("prev_module_c_pos", 0))
        pnl_a = float(saved.get("module_a_pnl_paper", 0.0))
        pnl_b = float(saved.get("module_b_pnl_paper", 0.0))
        pnl_c = float(saved.get("module_c_pnl_paper", 0.0))
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
        last_vev_mid = last_mids.get(PRODUCT_VEV)
        if last_vev_mid is not None:
            pnl_c += prev_c_pos * (S - last_vev_mid)
        last_mids[PRODUCT_VEV] = S
        saved["last_mids"] = last_mids
        saved["prev_module_a_pos"] = saved["module_a_pos"]
        saved["prev_module_b_pos"] = saved["module_b_pos"]
        saved["prev_module_c_pos"] = vev_combined_target
        saved["module_a_pnl_paper"] = pnl_a
        saved["module_b_pnl_paper"] = pnl_b
        saved["module_c_pnl_paper"] = pnl_c
        saved["net_delta_last"] = net_delta_with_combined

        # ---- Lightweight tick log (visible in run output) -----------------
        # One JSON line per tick; the rust backtester captures stdout. Stage 2
        # sweeps will parse this for module attribution if --persist is used.
        try:
            print(json.dumps({
                "ts": state.timestamp,
                "S": round(S, 2),
                "c": round(smile_coefs[2], 4),
                "nv_d": round(net_voucher_delta, 2),
                "vev_t": vev_combined_target,
                "net_d": round(net_delta_with_combined, 2),
                "a_pnl": round(pnl_a, 1),
                "b_pnl": round(pnl_b, 1),
                "c_pnl": round(pnl_c, 1),
            }))
        except Exception:
            pass  # logging is best-effort; do not fail the tick

        return result, 0, json.dumps(saved)
