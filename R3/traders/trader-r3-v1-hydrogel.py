"""
R3 Stage-1 baseline trader: HYDROGEL_PACK only.

Strategy: textbook market-maker for a wide-spread mean-reverting product.
  1. Fair value = EMA of mid-price.
  2. Aggressive take inside fair_value +/- take_edge.
  3. Passive two-sided quote at fair_value +/- quote_offset, shifted by an
     inventory skew that gets stronger as |position| approaches the limit.

All parameters live in configs/hydrogel_v1.json (loaded once, cached).
Defaults are justified against N1 (R3/analysis/agent_logs/N1_log.md):
  - Spread is a near-fixed 16 wide on HYDROGEL_PACK (N1 cell 7).
  - Lag-1 return ACF = -0.129, 12 sigma negative (N1 cell 16).
  - Demeaned-level AR(1) rho = 0.9977 -> half-life ~300 ticks (N1 cell 19).
  - 18% zero-return ticks (N1 cell 12) -> EMA on mid is the natural anchor.
  - HYDROGEL_PACK is independent of VEV (lag-0 corr ~0.01, N1 cell 27) so
    this module is fully standalone.
"""

from datamodel import OrderDepth, TradingState, Order  # type: ignore
from typing import Dict, List
import json

PRODUCT = "HYDROGEL_PACK"

# Inlined config. This is the source of truth for IMC submissions, where
# only this single .py file is uploaded. The values below MUST stay in
# sync with R3/traders/configs/hydrogel_v1.json (which the local override
# block immediately below reads when it sits next to this file).
CONFIG = {
    "fair_value_ema_window": 50,
    "quote_offset": 3,
    "skew_strength": 1.0,
    "take_edge": 4,
    "passive_quote_size": 30,
    "aggressive_take_size_cap": 50,
    "position_limit": 200,
}

# Local-dev override: if configs/hydrogel_v1.json is present alongside this
# file (i.e. the local backtester run, not the IMC upload), reload CONFIG
# from it so JSON edits take effect without touching the .py. Wrapped in
# try/except for the documented reason that on the IMC submission sandbox
# the JSON file is not uploaded and __file__ resolution may differ;
# falling back to the inlined CONFIG is the intended behaviour.
try:
    from pathlib import Path as _Path
    _cfg_path = _Path(__file__).parent / "configs" / "hydrogel_v1.json"
    if _cfg_path.is_file():
        with open(_cfg_path, "r") as _f:
            CONFIG = json.load(_f)
except (NameError, FileNotFoundError, OSError):
    pass


class Trader:
    def run(self, state: TradingState):
        cfg = CONFIG

        # N1: half-life ~300 ticks -> EMA window 50-100 is responsive but not noisy.
        # Window 50 is the Stage-1 starting point; will be swept in Stage 2.
        ema_window: int = cfg["fair_value_ema_window"]
        # N1: spread is fixed ~16, wall sits at fair +/- 8. Quoting at fair +/- 3
        # gives 6-wide quote inside 16-wide market: real edge with room to spare.
        quote_offset: int = cfg["quote_offset"]
        # Standard MM convention: full skew at full position.
        skew_strength: float = cfg["skew_strength"]
        # N1: take when market mispricing exceeds ~half the quote offset, so we
        # capture clearly mispriced fills before our passive quotes reach them.
        take_edge: int = cfg["take_edge"]
        # ~15% of the 200-unit limit per quote; lets us quote both sides without
        # immediately exhausting room from one fill.
        passive_size: int = cfg["passive_quote_size"]
        # ~25% of the 200-unit limit per aggressive trade; leaves room for
        # consecutive mispricings on subsequent ticks.
        take_cap: int = cfg["aggressive_take_size_cap"]
        # IMC-confirmed absolute position limit for HYDROGEL_PACK (CLAUDE.md).
        limit: int = cfg["position_limit"]

        # Restore EMA from traderData. We only persist a single float, so
        # the standard json module is sufficient.
        try:
            saved = json.loads(state.traderData) if state.traderData else {}
        except Exception as e:
            # No silent error handling (Hard Rule #7): bad traderData on startup
            # is the only realistic case, so fall back to empty state and surface
            # the cause in the persisted blob for the next tick.
            saved = {"_traderData_error": repr(e)}
        ema = saved.get("ema_fv")

        result: Dict[str, List[Order]] = {}

        depth = state.order_depths.get(PRODUCT)
        if depth is None or not depth.buy_orders or not depth.sell_orders:
            # No book on at least one side -> skip this tick. Persist EMA
            # unchanged so we resume cleanly when the book returns.
            saved["ema_fv"] = ema
            return result, 0, json.dumps(saved)

        best_bid = max(depth.buy_orders)
        best_ask = min(depth.sell_orders)
        mid = 0.5 * (best_bid + best_ask)

        # Standard EMA: alpha = 2 / (N+1) for a window of N.
        alpha = 2.0 / (ema_window + 1.0)
        ema = mid if ema is None else alpha * mid + (1.0 - alpha) * ema
        fv = ema

        pos = state.position.get(PRODUCT, 0)
        orders: List[Order] = []

        # --- Step 1: aggressive takes inside fair_value +/- take_edge -----------
        # Walk the ask book bottom-up; buy any level priced at or below fv - take_edge.
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

        # Walk the bid book top-down; sell into any level priced at or above fv + take_edge.
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

        # --- Step 2: passive two-sided quote with inventory skew -----------------
        # Project position assuming the takes above will fill, so we don't
        # overshoot the position limit when both take and quote fill same tick.
        proj_pos = pos + take_buy_used - take_sell_used
        room_buy_passive = limit - proj_pos
        room_sell_passive = limit + proj_pos

        # Skew shifts both quotes in the same direction. When long, we bias
        # both bid and ask downward -> ask fills more easily, bid fills less
        # easily, pulling inventory back toward zero.
        inv_ratio = proj_pos / limit  # in [-1, 1]
        skew = inv_ratio * skew_strength  # in [-skew_strength, +skew_strength]

        bid_px = int(round(fv - quote_offset - skew))
        ask_px = int(round(fv + quote_offset - skew))
        if ask_px <= bid_px:
            ask_px = bid_px + 1

        bid_size = min(passive_size, room_buy_passive)
        ask_size = min(passive_size, room_sell_passive)
        if bid_size > 0:
            orders.append(Order(PRODUCT, bid_px, bid_size))
        if ask_size > 0:
            orders.append(Order(PRODUCT, ask_px, -ask_size))

        result[PRODUCT] = orders
        saved["ema_fv"] = ema
        return result, 0, json.dumps(saved)
