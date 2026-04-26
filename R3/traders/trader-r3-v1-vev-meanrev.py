"""
R3 Phase-3 standalone trader: VELVETFRUIT_EXTRACT (VEV) only.

SHIP STATUS (2026-04-26): SHIPPED at rank-3 sweep config as a
**bounded-downside variance contribution**, NOT as an edge strategy.

Honest read: the 3-day backtest (mean=+2058, score=+661) is a
close-direction-favorable sample. Two independent diagnostics show the
underlying per-fill edge is ~zero or negative:
  1. Pre-sweep attribution: forward-50-tick mid edge per fill is
     -10 to -110 across BOTH passive (wall) and aggressive (te=1) zones.
     Passive zone PnL = +12 over 125 fills (vs +500 expected from naive
     spread capture); aggressive zone = -772 over 55 fills.
  2. Force-flatten test (Option C): replacing the closing-MTM with
     last-500-tick realized close drops 3-day mean from +2058 to +698,
     a 1360 PnL gap that's 6.8x the half-spread cost. The closing-mid
     gift was favorable on all 3 sample days.
See R3/analysis/vev_meanrev_comparison.md for the full writeup.

What this strategy actually does:
  - Posts passive two-sided quotes at the wall (fv +/- quote_offset),
    skewed by inventory.
  - Takes aggressively when book has crossed by take_edge or more.
  - Saturates to |pos| ~ 90 within ~1k ticks and lives there for the
    rest of the day. Final PnL = MTM at closing mid on the held book.
  - Drift kill (threshold=150) is dormant: max|pos| never reaches it.

The shipping rationale: under the local trade-replay engine, fills are
capped at 25-80/day across all sensible configs, which structurally
prevents per-fill edge from being captured even if it exists. On the
live IMC engine (richer fills against snapshot books) the picture
could differ in either direction. We submit this module as a
bounded-downside variance contribution to the GOAT-phase basket
(positions liquidate at hidden fair at end-of-round), not as an alpha
strategy. Single-day downside is bounded by the saturation level
(|pos| <= 100 across all 96 swept configs).

Strategy mechanics (three layers stacked on a single fair-value EMA):
  1. Fair value = EMA(mid). Window=120 ticks (rank-3 winner).
  2. Aggressive take inside fair_value +/- take_edge (te=2 selected).
  3. Passive two-sided quote at fair_value +/- quote_offset, shifted by
     an inventory skew. Skew is the implicit MR mechanism: when long,
     both quotes shift down so we sell more easily and lean toward
     flat. Empirically inactive at the operating |pos|~90 level.

Drift defense (kept dormant; do not tighten without overhaul):
  If |position| > kill_threshold for kill_dwell_ticks consecutive ticks,
  we collapse the quote to one-sided. (B1) tested kill_threshold=80
  and the strategy paid spread cost on every saturate/drain cycle:
  3-day mean dropped from +2058 to -12723. Tightening the kill is
  contraindicated until the per-fill bleed is fixed at the architecture
  level.

Defaults are justified against N1 (R3/analysis/agent_logs/N1_log.md):
  - VEV spread is a near-fixed 5 wide (N1 cell 7).
  - Lag-1 return ACF = -0.159, 15 sigma negative (N1 cell 16) - the
    statistical MR signal exists but its magnitude (~1.1 abs/sigma per
    tick) is below the 5-tick spread cost, so it cannot be captured by
    aggressive crossing alone.
  - Demeaned-level AR(1) rho = 0.9972 -> half-life ~248 ticks (N1 cell 19).
  - Independent of HYDROGEL_PACK (lag-0 corr ~0.012, N1 cell 27) so
    this module is fully standalone.

All parameters live in configs/vev_meanrev_v1.json (loaded once, cached).
"""

from datamodel import OrderDepth, TradingState, Order  # type: ignore
from typing import Dict, List
import json

PRODUCT = "VELVETFRUIT_EXTRACT"

# Inlined config. Source of truth for IMC submissions, where only this
# .py is uploaded. Must stay in sync with configs/vev_meanrev_v1.json.
CONFIG = {
    # SHIP CONFIG: rank-3 winner from the 96-combo Stage-2 sweep
    # (vmr-ema120-te2-sk2.0-tc30, mean=+2058, std=1397, score=+661).
    # See R3/analysis/vev_meanrev_comparison.md for the honest read on
    # what this strategy does and does not capture.
    "fair_value_ema_window": 120,
    # quote_offset fixed at 2: trade-replay backtester only matches at
    # historical bot trade prices, which sit at the wall (fv +- 2.5).
    # Lower offsets undertrade catastrophically (qo=1 gives 16 fills/3d).
    "quote_offset": 2,
    # Highest skew tested. At |pos|=90 (the operating saturation level)
    # this only shifts quotes by 1 tick; the axis is roughly neutral in
    # this regime per Stage-2 break-out.
    "skew_strength": 2.0,
    # te=2 wins the take-edge break-out (mean +214, 22/32 positive).
    # te=1 fires into continuation per attribution; te=0 strictly worst.
    "take_edge": 2,
    "passive_quote_size": 20,
    "aggressive_take_size_cap": 30,
    # IMC-confirmed absolute position limit for VELVETFRUIT_EXTRACT.
    "position_limit": 200,
    # Drift kill kept loose (threshold 150) and effectively dormant.
    # Stage-2 trajectory shows max|pos| = 95 / 98% pinned, so this never
    # fires in practice. Tightening it to 80 was tested as (B1) and
    # collapsed PnL by churning into negative-edge fills - see WORKLOG.
    "kill_threshold": 150,
    "kill_dwell_ticks": 500,
    "kill_release": 100,
}

# Local-dev override: same pattern as hydrogel.py. JSON sidecar at
# configs/vev_meanrev_v1.json overrides the inlined CONFIG when present;
# falls back silently on the IMC sandbox where the JSON file isn't uploaded.
try:
    from pathlib import Path as _Path
    _cfg_path = _Path(__file__).parent / "configs" / "vev_meanrev_v1.json"
    if _cfg_path.is_file():
        with open(_cfg_path, "r") as _f:
            CONFIG = json.load(_f)
except (NameError, FileNotFoundError, OSError):
    pass


class Trader:
    def run(self, state: TradingState):
        cfg = CONFIG

        ema_window: int = cfg["fair_value_ema_window"]
        quote_offset: int = cfg["quote_offset"]
        skew_strength: float = cfg["skew_strength"]
        take_edge: int = cfg["take_edge"]
        passive_size: int = cfg["passive_quote_size"]
        take_cap: int = cfg["aggressive_take_size_cap"]
        limit: int = cfg["position_limit"]
        kill_thr: int = cfg["kill_threshold"]
        kill_dwell: int = cfg["kill_dwell_ticks"]
        kill_release: int = cfg["kill_release"]

        try:
            saved = json.loads(state.traderData) if state.traderData else {}
        except Exception as e:
            # Hard Rule #7: bad traderData on startup is the only realistic
            # case. Surface the cause in the persisted blob for next tick.
            saved = {"_traderData_error": repr(e)}
        ema = saved.get("ema_fv")
        kill_counter: int = int(saved.get("kill_counter", 0))
        kill_active: bool = bool(saved.get("kill_active", False))
        kill_side: str = saved.get("kill_side", "")  # "long" or "short" or ""

        result: Dict[str, List[Order]] = {}

        depth = state.order_depths.get(PRODUCT)
        if depth is None or not depth.buy_orders or not depth.sell_orders:
            saved["ema_fv"] = ema
            saved["kill_counter"] = kill_counter
            saved["kill_active"] = kill_active
            saved["kill_side"] = kill_side
            return result, 0, json.dumps(saved)

        best_bid = max(depth.buy_orders)
        best_ask = min(depth.sell_orders)
        mid = 0.5 * (best_bid + best_ask)

        alpha = 2.0 / (ema_window + 1.0)
        ema = mid if ema is None else alpha * mid + (1.0 - alpha) * ema
        fv = ema

        pos = state.position.get(PRODUCT, 0)

        # ---- Drift defense state machine -----------------------------------
        # kill_counter ticks up while |pos| > kill_thr; resets when |pos|
        # falls below kill_thr. Once the counter exceeds kill_dwell, kill
        # the side that holds the inventory (long pos -> kill bid, so we
        # only post the ask). Release when |pos| drops below kill_release.
        if abs(pos) > kill_thr:
            kill_counter += 1
        else:
            kill_counter = 0
            if kill_active:
                # Position is back inside the threshold band but we never
                # reached the release. Treat that as an early exit of the
                # kill state - hysteresis is for the deeper kill_release
                # band. Keeping symmetric: always exit when pos returns to
                # kill_thr band.
                pass
        if (not kill_active) and kill_counter >= kill_dwell:
            kill_active = True
            kill_side = "long" if pos > 0 else "short"
            print(f"[VEV-MR] KILL ENTER: pos={pos} side={kill_side} after {kill_counter} ticks above |{kill_thr}|")
        if kill_active and abs(pos) < kill_release:
            print(f"[VEV-MR] KILL EXIT: pos={pos} (released below |{kill_release}|)")
            kill_active = False
            kill_side = ""
            kill_counter = 0

        orders: List[Order] = []

        # --- Step 1: aggressive takes inside fair_value +/- take_edge -------
        # Buy any ask priced <= fv - take_edge. Walk asks bottom-up.
        room_buy = limit - pos
        take_buy_used = 0
        for ap in sorted(depth.sell_orders):
            if ap > fv - take_edge:
                break
            available = -depth.sell_orders[ap]  # sell_orders volumes are negative
            qty = min(available, room_buy - take_buy_used, take_cap - take_buy_used)
            if qty <= 0:
                break
            orders.append(Order(PRODUCT, ap, qty))
            take_buy_used += qty
            if take_buy_used >= take_cap or take_buy_used >= room_buy:
                break

        # Sell any bid priced >= fv + take_edge. Walk bids top-down.
        room_sell = limit + pos
        take_sell_used = 0
        for bp in sorted(depth.buy_orders, reverse=True):
            if bp < fv + take_edge:
                break
            available = depth.buy_orders[bp]
            qty = min(available, room_sell - take_sell_used, take_cap - take_sell_used)
            if qty <= 0:
                break
            orders.append(Order(PRODUCT, bp, -qty))
            take_sell_used += qty
            if take_sell_used >= take_cap or take_sell_used >= room_sell:
                break

        # --- Step 2: passive two-sided quote with inventory skew ------------
        # Project position assuming the takes above fill, so we don't
        # overshoot the limit when both take and quote fill same tick.
        proj_pos = pos + take_buy_used - take_sell_used
        room_buy_passive = limit - proj_pos
        room_sell_passive = limit + proj_pos

        # Skew shifts both quotes in the same direction. Long inventory ->
        # bias both bid and ask down, ask fills more easily, bid fills less
        # easily, pulling inventory back toward zero.
        inv_ratio = proj_pos / limit  # in [-1, 1]
        skew = inv_ratio * skew_strength  # in [-skew_strength, +skew_strength]

        bid_px = int(round(fv - quote_offset - skew))
        ask_px = int(round(fv + quote_offset - skew))
        # Cross-guard: load-bearing because VEV's 5-wide spread + skew can
        # produce ask <= bid at full position. Force a 1-tick spread.
        if ask_px <= bid_px:
            ask_px = bid_px + 1

        bid_size = min(passive_size, room_buy_passive)
        ask_size = min(passive_size, room_sell_passive)

        # Drift kill: drop the side that adds to held inventory.
        if kill_active and kill_side == "long":
            bid_size = 0  # no more buys; only post ask to bleed off long
        elif kill_active and kill_side == "short":
            ask_size = 0  # no more sells; only post bid to bleed off short

        if bid_size > 0:
            orders.append(Order(PRODUCT, bid_px, bid_size))
        if ask_size > 0:
            orders.append(Order(PRODUCT, ask_px, -ask_size))

        result[PRODUCT] = orders
        saved["ema_fv"] = ema
        saved["kill_counter"] = kill_counter
        saved["kill_active"] = kill_active
        saved["kill_side"] = kill_side
        return result, 0, json.dumps(saved)
