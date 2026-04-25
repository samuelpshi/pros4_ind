"""
Round 1 Trader
==============

ASH_COATED_OSMIUM    : Mean-reverting price that oscillates ~±100 around a
                       stable mean (~10,000).
                       Strategy: slow-EMA fair-value + aggressive takes on
                       deviations + passive market-making with inventory skew.

INTARIAN_PEPPER_ROOT : Linearly trending price (~10,000 → 11,500 over 3 days).
                       Strategy: dual-EMA momentum — stay at max-long while
                       fast EMA > slow EMA, exit/flip short if trend reverses.
                       EOD position flattening each day.
"""

from datamodel import OrderDepth, TradingState, Order  # type: ignore
from typing import Dict, List, Tuple
import jsonpickle  # type: ignore
import math

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POSITION_LIMITS: Dict[str, int] = {
    "ASH_COATED_OSMIUM":     80,
    "INTARIAN_PEPPER_ROOT":  80,
}

# Timestamps run 0 → 999_900 (step 100) each day.
# EOD flattening kicks in at EOD_START.
TIMESTAMP_MAX = 999_900
EOD_START     = 950_000


# ---------------------------------------------------------------------------
# Per-product configs
# ---------------------------------------------------------------------------

# ASH_COATED_OSMIUM — mean reversion
ACO_CFG = {
    "ema_alpha":       0.12,   # slow EMA → stable estimate of the true mean
    "quote_offset":    2,      # passive spread each side of FV
    "take_edge":       3,      # take resting orders this many ticks from FV
    "max_skew":        5,      # max ticks of inventory skew on quotes
    "panic_threshold": 0.75,   # fraction of limit that triggers panic mode
}

# INTARIAN_PEPPER_ROOT — directional / trend following
IPR_CFG = {
    "ema_fast":          0.25,  # fast EMA tracks recent price
    "ema_slow":          0.04,  # slow EMA tracks the longer trend
    "trend_threshold":   4.0,   # minimum fast-slow gap to confirm a trend
    "quote_offset":      1,     # tight spread when posting in trend direction
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def best_bid_ask(depth: OrderDepth) -> Tuple[int, int]:
    return max(depth.buy_orders), min(depth.sell_orders)


def vwap_mid(depth: OrderDepth) -> float:
    """Volume-weighted mid across the full book."""
    bid_val = sum(p * q          for p, q in depth.buy_orders.items())
    bid_vol = sum(depth.buy_orders.values())
    ask_val = sum(p * abs(q)     for p, q in depth.sell_orders.items())
    ask_vol = sum(abs(q)         for q in depth.sell_orders.values())
    if bid_vol == 0 or ask_vol == 0:
        bb, ba = best_bid_ask(depth)
        return (bb + ba) / 2.0
    return (bid_val / bid_vol + ask_val / ask_vol) / 2.0


def eod_urgency(timestamp: int) -> float:
    """0.0 → normal trading;  1.0 → last tick of the day."""
    if timestamp < EOD_START:
        return 0.0
    return min(1.0, (timestamp - EOD_START) / (TIMESTAMP_MAX - EOD_START))


# ---------------------------------------------------------------------------
# ASH_COATED_OSMIUM — mean-reversion helpers
# ---------------------------------------------------------------------------

def aco_take(symbol: str, depth: OrderDepth, fv: float,
             pos: int, limit: int, edge: int) -> Tuple[List[Order], int]:
    """
    Take resting orders that are `edge` ticks away from fair value.
    Also takes AT fair value when inventory favours the direction.
    """
    orders: List[Order] = []

    for ap in sorted(depth.sell_orders):
        threshold = fv - edge if pos >= 0 else fv   # relax when short
        if ap > threshold:
            break
        room = limit - pos
        if room <= 0:
            break
        qty = min(-depth.sell_orders[ap], room)
        orders.append(Order(symbol, ap, qty))
        pos += qty

    for bp in sorted(depth.buy_orders, reverse=True):
        threshold = fv + edge if pos <= 0 else fv   # relax when long
        if bp < threshold:
            break
        room = limit + pos
        if room <= 0:
            break
        qty = min(depth.buy_orders[bp], room)
        orders.append(Order(symbol, bp, -qty))
        pos -= qty

    return orders, pos


def aco_make(symbol: str, fv: float, pos: int, limit: int,
             cfg: dict, urgency: float) -> List[Order]:
    """
    Post passive bid/ask around FV with inventory skew + EOD flattening.
    """
    offset = cfg["quote_offset"]
    max_skew = cfg["max_skew"]
    panic_thr = cfg["panic_threshold"]
    inv_ratio = pos / limit

    skew = round(inv_ratio * max_skew)

    # Panic: aggressively unwind when near limits
    panic_extra = 0
    if abs(inv_ratio) >= panic_thr:
        panic_extra = round(
            (abs(inv_ratio) - panic_thr) / (1.0 - panic_thr) * 3
        )

    # EOD: collapse spread and push skew hard
    if urgency > 0 and abs(pos) > 0:
        offset = max(0, offset - round(urgency * offset))
        skew   = round(inv_ratio * (max_skew + urgency * 4))

    bid_px = math.floor(fv) - offset - skew
    ask_px = math.ceil(fv)  + offset - skew

    if pos > 0 and panic_extra > 0:
        ask_px -= panic_extra   # lower ask to dump longs
    elif pos < 0 and panic_extra > 0:
        bid_px += panic_extra   # raise bid to cover shorts

    # Safety: never quote on the wrong side of FV (except during EOD/panic)
    if urgency > 0.5 or abs(inv_ratio) >= panic_thr:
        bid_px = min(bid_px, math.floor(fv))
        ask_px = max(ask_px, math.ceil(fv))
    else:
        bid_px = min(bid_px, math.floor(fv) - 1)
        ask_px = max(ask_px, math.ceil(fv) + 1)

    if ask_px <= bid_px:
        ask_px = bid_px + 1

    orders: List[Order] = []
    buy_qty  = limit - pos
    sell_qty = limit + pos
    if buy_qty  > 0 and bid_px > 0:
        orders.append(Order(symbol, bid_px,  buy_qty))
    if sell_qty > 0 and ask_px > 0:
        orders.append(Order(symbol, ask_px, -sell_qty))
    return orders


# ---------------------------------------------------------------------------
# INTARIAN_PEPPER_ROOT — directional / trend-following helpers
# ---------------------------------------------------------------------------

def ipr_orders(symbol: str, depth: OrderDepth, fast_ema: float,
               slow_ema: float, pos: int, limit: int,
               cfg: dict, urgency: float) -> List[Order]:
    """
    Trend-following logic:
    - fast_ema > slow_ema + threshold  → uptrend  → target +limit
    - fast_ema < slow_ema - threshold  → downtrend → target -limit
    - EOD: flatten toward 0
    """
    orders:   List[Order] = []
    bb, ba    = best_bid_ask(depth)
    threshold = cfg["trend_threshold"]
    offset    = cfg["quote_offset"]
    gap       = fast_ema - slow_ema

    # ── Determine target position ─────────────────────────────────────────
    if urgency > 0.5:
        # Late EOD: hard-flatten regardless of trend
        target = 0
    elif gap > threshold:
        target = +limit    # confirmed uptrend
    elif gap < -threshold:
        target = -limit    # confirmed downtrend
    else:
        target = pos       # no clear signal — hold current

    delta = target - pos   # how many units we still need to trade

    # ── Aggressive takes in trend direction ───────────────────────────────
    if delta > 0:
        # Need to buy — sweep the ask side
        for ap in sorted(depth.sell_orders):
            if delta <= 0:
                break
            qty = min(-depth.sell_orders[ap], delta, limit - pos)
            if qty <= 0:
                break
            orders.append(Order(symbol, ap, qty))
            pos   += qty
            delta -= qty

    elif delta < 0:
        # Need to sell — sweep the bid side
        for bp in sorted(depth.buy_orders, reverse=True):
            if delta >= 0:
                break
            qty = min(depth.buy_orders[bp], -delta, limit + pos)
            if qty <= 0:
                break
            orders.append(Order(symbol, bp, -qty))
            pos   -= qty
            delta += qty

    # ── Passive resting order for any remaining delta ─────────────────────
    remaining = target - pos
    if remaining > 0 and (limit - pos) > 0:
        # Post bid just above current best bid to get filled quickly
        bid_px = bb + offset
        orders.append(Order(symbol, bid_px, min(remaining, limit - pos)))
    elif remaining < 0 and (limit + pos) > 0:
        ask_px = ba - offset
        orders.append(Order(symbol, ask_px, -min(-remaining, limit + pos)))

    return orders


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------

class Trader:
    def run(self, state: TradingState):
        # ── Restore persisted state ──────────────────────────────────────
        saved: dict = {}
        if state.traderData:
            try:
                saved = jsonpickle.decode(state.traderData)
            except Exception:
                pass

        ema:      Dict[str, float] = saved.get("ema",      {})
        ema_fast: Dict[str, float] = saved.get("ema_fast", {})
        ema_slow: Dict[str, float] = saved.get("ema_slow", {})

        result: Dict[str, List[Order]] = {}
        t       = state.timestamp
        urgency = eod_urgency(t)

        for symbol, depth in state.order_depths.items():
            if not depth.buy_orders or not depth.sell_orders:
                continue

            pos   = state.position.get(symbol, 0)
            limit = POSITION_LIMITS.get(symbol, 20)
            mid   = vwap_mid(depth)

            # ================================================================
            # ASH_COATED_OSMIUM — mean reversion
            # ================================================================
            if symbol == "ASH_COATED_OSMIUM":
                alpha = ACO_CFG["ema_alpha"]
                prev  = ema.get(symbol, mid)
                fv    = alpha * mid + (1.0 - alpha) * prev
                ema[symbol] = fv

                take_ords, pos2 = aco_take(
                    symbol, depth, fv, pos, limit, ACO_CFG["take_edge"]
                )
                make_ords = aco_make(
                    symbol, fv, pos2, limit, ACO_CFG, urgency
                )
                result[symbol] = take_ords + make_ords

            # ================================================================
            # INTARIAN_PEPPER_ROOT — directional / trend following
            # ================================================================
            elif symbol == "INTARIAN_PEPPER_ROOT":
                alpha_f = IPR_CFG["ema_fast"]
                alpha_s = IPR_CFG["ema_slow"]

                prev_f = ema_fast.get(symbol, mid)
                prev_s = ema_slow.get(symbol, mid)

                fast = alpha_f * mid + (1.0 - alpha_f) * prev_f
                slow = alpha_s * mid + (1.0 - alpha_s) * prev_s

                ema_fast[symbol] = fast
                ema_slow[symbol] = slow

                result[symbol] = ipr_orders(
                    symbol, depth, fast, slow, pos, limit, IPR_CFG, urgency
                )

        # ── Persist state ────────────────────────────────────────────────
        saved["ema"]      = ema
        saved["ema_fast"] = ema_fast
        saved["ema_slow"] = ema_slow
        trader_data = jsonpickle.encode(saved)

        return result, 0, trader_data
