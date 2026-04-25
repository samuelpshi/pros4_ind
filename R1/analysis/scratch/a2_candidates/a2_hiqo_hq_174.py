"""
Round 1 Trader — v8
====================

Data-backed iteration based on actual log analysis from v7 backtest.

WHAT THE LOG SHOWED:
- v7 IPR PnL for one day = 3660 (just drift on +40 from start)
- We bought 40 units in 2 ticks at start, NEVER traded IPR again
- 402 "buyer hit ask" events + 137 "seller hit bid" events per day
- Bot-to-bot trades happen at ASK (~+6 above mid) or BID (~-6 below mid)
- Each round-trip (sell at ask, buy at bid) = ~13 ticks per unit captured

V8 STRATEGY: "Skim and Refill" on top of buy-and-hold
- Phase 1: Aggressive entry to +40 at day start (same as v7 — already optimal)
- Phase 2: Always maintain a small SELL quote at ask + 2 (size 5)
  → Only fills on sharp UP spikes when bots aggressively buy
  → When filled: position drops from 40 to 35, we earned (ask+2 - mid) ≈ 8 ticks/unit
- Phase 3: When pos < 40, post AGGRESSIVE bid at bid_top + 1 (size = 40-pos)
  → Refills our position as drift continues OR when bots sell at the bid
  → Round-trip net: (ask+2) - (bid+1) ≈ 8-10 ticks per cycle = ~40-50 PnL per 5-unit cycle
  
Expected: 8-12 round trips per day = +400-600 PnL per day on top of drift
Across 3 days: +1200-1800 extra IPR PnL

ASH_COATED_OSMIUM: UNCHANGED from teammate's original.
"""

from datamodel import OrderDepth, TradingState, Order  # type: ignore
from typing import Dict, List, Tuple
import jsonpickle  # type: ignore
import math

# ---------------------------------------------------------------------------
# IPR parameters — defaults match v8's IPR_CFG.
# ---------------------------------------------------------------------------
_IPR_SKIM_SIZE        = 5
_IPR_SKIM_OFFSET      = 2
_IPR_REFILL_MAX_SIZE  = 10

# ---------------------------------------------------------------------------
POSITION_LIMITS: Dict[str, int] = {
    "ASH_COATED_OSMIUM":     80,
    "INTARIAN_PEPPER_ROOT":  80,
}

TIMESTAMP_MAX = 999_900
EOD_START     = 950_000

# ACO - A7 recommended params: quote_offset=5, max_skew=8, take_edge=3
# Justified by A7 LOO-CV (worst_LOO=2034 CSV, vs v8 worst_LOO=892.5 CSV)
# GT validation required before shipping (A8 step 1)
ACO_CFG = {
    "ema_alpha":       0.1025,
    "quote_offset":    6,
    "take_edge":       3.1581,
    "max_skew":        9,
    "panic_threshold": 0.75,
}

# IPR v8 config
IPR_CFG = {
    # Trend reversal detection (defensive)
    "ema_fast":              0.05,
    "ema_slow":              0.005,
    "reversal_threshold":    -8.0,
    "strong_reversal_thr":   -15.0,
    
    # Entry
    "target_long":           80,      # = position limit; max drift capture
    "entry_take_cap":        80,      # fill entire target greedily at open

    # SKIM ASK (the new income source)
    # Values read from env vars at import time; defaults match original v8.
    "skim_offset":           _IPR_SKIM_OFFSET,    # post sell at ask_top + skim_offset
    "skim_size":             _IPR_SKIM_SIZE,       # units per skim quote
    "skim_min_pos":          75,                   # skim only when within 5 of target

    # REFILL BID (when below target)
    "refill_offset":         1,                    # post buy at bid_top + 1 (not swept)
    "refill_max_size":       _IPR_REFILL_MAX_SIZE, # max units per tick to refill
    
    # Defensive deep bids (catch flash crashes)
    "deep_bid_offsets":      [3, 5],
    "deep_bid_sizes":        [3, 2],
}


def best_bid_ask(depth: OrderDepth) -> Tuple[int, int]:
    return max(depth.buy_orders), min(depth.sell_orders)


def vwap_mid(depth: OrderDepth) -> float:
    bid_val = sum(p * q for p, q in depth.buy_orders.items())
    bid_vol = sum(depth.buy_orders.values())
    ask_val = sum(p * abs(q) for p, q in depth.sell_orders.items())
    ask_vol = sum(abs(q) for q in depth.sell_orders.values())
    if bid_vol == 0 or ask_vol == 0:
        bb, ba = best_bid_ask(depth)
        return (bb + ba) / 2.0
    return (bid_val / bid_vol + ask_val / ask_vol) / 2.0


def eod_urgency(timestamp: int) -> float:
    if timestamp < EOD_START:
        return 0.0
    return min(1.0, (timestamp - EOD_START) / (TIMESTAMP_MAX - EOD_START))


# ===========================================================================
# ACO — UNCHANGED
# ===========================================================================

def aco_take(symbol, depth, fv, pos, limit, edge):
    orders = []
    for ap in sorted(depth.sell_orders):
        threshold = fv - edge if pos >= 0 else fv
        if ap > threshold: break
        room = limit - pos
        if room <= 0: break
        qty = min(-depth.sell_orders[ap], room)
        orders.append(Order(symbol, ap, qty)); pos += qty
    for bp in sorted(depth.buy_orders, reverse=True):
        threshold = fv + edge if pos <= 0 else fv
        if bp < threshold: break
        room = limit + pos
        if room <= 0: break
        qty = min(depth.buy_orders[bp], room)
        orders.append(Order(symbol, bp, -qty)); pos -= qty
    return orders, pos


def aco_make(symbol, fv, pos, limit, cfg, urgency):
    offset = cfg["quote_offset"]
    max_skew = cfg["max_skew"]
    panic_thr = cfg["panic_threshold"]
    inv_ratio = pos / limit
    skew = round(inv_ratio * max_skew)
    panic_extra = 0
    if abs(inv_ratio) >= panic_thr:
        panic_extra = round((abs(inv_ratio) - panic_thr) / (1.0 - panic_thr) * 3)
    if urgency > 0 and abs(pos) > 0:
        offset = max(0, offset - round(urgency * offset))
        skew = round(inv_ratio * (max_skew + urgency * 4))
    bid_px = math.floor(fv) - offset - skew
    ask_px = math.ceil(fv) + offset - skew
    if pos > 0 and panic_extra > 0: ask_px -= panic_extra
    elif pos < 0 and panic_extra > 0: bid_px += panic_extra
    if urgency > 0.5 or abs(inv_ratio) >= panic_thr:
        bid_px = min(bid_px, math.floor(fv))
        ask_px = max(ask_px, math.ceil(fv))
    else:
        bid_px = min(bid_px, math.floor(fv) - 1)
        ask_px = max(ask_px, math.ceil(fv) + 1)
    if ask_px <= bid_px: ask_px = bid_px + 1
    orders = []
    buy_qty, sell_qty = limit - pos, limit + pos
    if buy_qty > 0 and bid_px > 0: orders.append(Order(symbol, bid_px, buy_qty))
    if sell_qty > 0 and ask_px > 0: orders.append(Order(symbol, ask_px, -sell_qty))
    return orders


# ===========================================================================
# IPR v8 — Buy-and-hold + skim/refill MM
# ===========================================================================

def ipr_orders(symbol, depth, fast_ema, slow_ema, pos, limit, cfg):
    """
    v8 — Hold +40 with skim/refill MM cycle.
    
    Logic:
    1. If pos < target_long (and no reversal): aggressively BUY to target
    2. If pos == target_long: post small skim ASK above market (catches up-spikes)
    3. If pos < target_long: post REFILL BID inside spread (active rebuy)
    4. ALWAYS: defensive deep bids to catch flash crashes for free
    5. Reversal protection: if drift reverses, gradually flatten (no panic dump)
    """
    orders: List[Order] = []
    bb, ba = best_bid_ask(depth)
    
    # Determine base target
    target = cfg["target_long"]
    gap = fast_ema - slow_ema
    if gap < cfg["strong_reversal_thr"]:
        target = -limit
    elif gap < cfg["reversal_threshold"]:
        target = 0
    
    delta = target - pos
    
    # === STEP 1: AGGRESSIVE TAKE TOWARD TARGET ===
    cap = cfg["entry_take_cap"]
    if delta > 0:
        need = min(delta, cap)
        for ap in sorted(depth.sell_orders):
            if need <= 0: break
            qty = min(-depth.sell_orders[ap], need, limit - pos)
            if qty <= 0: break
            orders.append(Order(symbol, ap, qty))
            pos += qty; need -= qty
    elif delta < 0:
        need = min(-delta, cap)
        for bp in sorted(depth.buy_orders, reverse=True):
            if need <= 0: break
            qty = min(depth.buy_orders[bp], need, limit + pos)
            if qty <= 0: break
            orders.append(Order(symbol, bp, -qty))
            pos -= qty; need -= qty
    
    # Recompute room for passive orders
    room_long_buy = limit - pos       # how many more we can buy
    room_long_sell = limit + pos      # how many we can sell (long side)
    
    # === STEP 2: SKIM ASK (only when target is long and pos near limit) ===
    # Post small sell quote ABOVE market — catches occasional up-spikes
    # Don't skim if we're already trying to flatten (target <= 0)
    if target > 0 and pos >= cfg["skim_min_pos"]:
        skim_size = min(cfg["skim_size"], room_long_sell)
        if skim_size > 0:
            skim_px = ba + cfg["skim_offset"]
            orders.append(Order(symbol, skim_px, -skim_size))
    
    # === STEP 3: REFILL BID ===
    # When below target_long, post tight bid inside spread to refill
    # This earns the spread when bots sell at the bid OR drift refills us
    if target > 0 and pos < cfg["target_long"]:
        refill_size = min(cfg["refill_max_size"], room_long_buy)
        if refill_size > 0:
            refill_px = bb + cfg["refill_offset"]
            # Don't cross the ask
            if refill_px < ba:
                orders.append(Order(symbol, refill_px, refill_size))
    
    # === STEP 4: DEEP DEFENSIVE BIDS (free dip-catching) ===
    # These almost never fill but catch flash crashes for cheap
    if target > 0 and room_long_buy > 0:
        remaining_room = room_long_buy
        # Subtract refill bid size if we just posted it
        if pos < cfg["target_long"]:
            remaining_room -= min(cfg["refill_max_size"], room_long_buy)
        for off, sz in zip(cfg["deep_bid_offsets"], cfg["deep_bid_sizes"]):
            if remaining_room <= 0: break
            deep_px = bb - off
            if deep_px <= 0: continue
            qty = min(remaining_room, sz)
            orders.append(Order(symbol, deep_px, qty))
            remaining_room -= qty
    
    # === SHORT SIDE (mirror logic when target is negative — defensive only) ===
    if target < 0 and pos > target:
        # Need to sell more to reach target (handled above)
        pass
    if target < 0 and pos <= -cfg["skim_min_pos"]:
        # Symmetric skim: post buy below market
        skim_size = min(cfg["skim_size"], room_long_buy)
        if skim_size > 0:
            skim_px = bb - cfg["skim_offset"]
            if skim_px > 0:
                orders.append(Order(symbol, skim_px, skim_size))
    
    return orders


# ===========================================================================
# Trader
# ===========================================================================

class Trader:
    def run(self, state: TradingState):
        saved: dict = {}
        if state.traderData:
            try: saved = jsonpickle.decode(state.traderData)
            except Exception: pass

        ema:         Dict[str, float] = saved.get("ema", {})
        ema_fast:    Dict[str, float] = saved.get("ema_fast", {})
        ema_slow:    Dict[str, float] = saved.get("ema_slow", {})

        result: Dict[str, List[Order]] = {}
        t = state.timestamp
        urgency = eod_urgency(t)

        for symbol, depth in state.order_depths.items():
            if not depth.buy_orders or not depth.sell_orders: continue
            pos = state.position.get(symbol, 0)
            limit = POSITION_LIMITS.get(symbol, 20)
            mid = vwap_mid(depth)

            if symbol == "ASH_COATED_OSMIUM":
                alpha = ACO_CFG["ema_alpha"]
                prev  = ema.get(symbol, mid)
                fv    = alpha * mid + (1 - alpha) * prev
                ema[symbol] = fv
                take_ords, pos2 = aco_take(symbol, depth, fv, pos, limit, ACO_CFG["take_edge"])
                make_ords = aco_make(symbol, fv, pos2, limit, ACO_CFG, urgency)
                result[symbol] = take_ords + make_ords

            elif symbol == "INTARIAN_PEPPER_ROOT":
                af = IPR_CFG["ema_fast"]
                as_ = IPR_CFG["ema_slow"]
                prev_f = ema_fast.get(symbol, mid)
                prev_s = ema_slow.get(symbol, mid)
                fast = af  * mid + (1 - af ) * prev_f
                slow = as_ * mid + (1 - as_) * prev_s
                ema_fast[symbol] = fast
                ema_slow[symbol] = slow
                
                orders = ipr_orders(symbol, depth, fast, slow, pos, limit, IPR_CFG)
                result[symbol] = orders

        saved["ema"] = ema
        saved["ema_fast"] = ema_fast
        saved["ema_slow"] = ema_slow
        return result, 0, jsonpickle.encode(saved)