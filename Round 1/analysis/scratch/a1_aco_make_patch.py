"""
a1_aco_make_patch.py — A1 scratch: what aco_make() would look like if
quote_size_bid and quote_size_ask were added as searchable parameters.

STATUS: REJECTED — see bottom of file for rationale.

DO NOT copy this to traders/. This is a spec-only scratch file.

Current aco_make() (from trader-v9-aco-qo5-ms8-te3.py):
    buy_qty  = limit - pos   # fill remaining room on bid side
    sell_qty = limit + pos   # fill remaining room on ask side

Proposed change: cap quote sizes at cfg["quote_size_bid"] / cfg["quote_size_ask"].
If the cap is higher than the room, room still takes priority (no position violation).
"""

import math


def aco_make_patched(symbol, fv, pos, limit, cfg, urgency):
    """
    Patched aco_make with optional quote size caps.

    New keys in cfg (optional, default=None means unlimited = current behavior):
        "quote_size_bid": int or None  — max units posted on bid side per tick
        "quote_size_ask": int or None  — max units posted on ask side per tick

    All other logic is identical to the original aco_make().
    """
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
    if pos > 0 and panic_extra > 0:
        ask_px -= panic_extra
    elif pos < 0 and panic_extra > 0:
        bid_px += panic_extra
    if urgency > 0.5 or abs(inv_ratio) >= panic_thr:
        bid_px = min(bid_px, math.floor(fv))
        ask_px = max(ask_px, math.ceil(fv))
    else:
        bid_px = min(bid_px, math.floor(fv) - 1)
        ask_px = max(ask_px, math.ceil(fv) + 1)
    if ask_px <= bid_px:
        ask_px = bid_px + 1

    orders = []
    buy_room  = limit - pos   # hard physical cap (position constraint)
    sell_room = limit + pos

    # --- PATCH: apply optional size caps ---
    qs_bid = cfg.get("quote_size_bid", None)
    qs_ask = cfg.get("quote_size_ask", None)

    buy_qty  = min(buy_room,  qs_bid) if qs_bid is not None else buy_room
    sell_qty = min(sell_room, qs_ask) if qs_ask is not None else sell_room
    # --- END PATCH (6 lines total, no new branching on the price side) ---

    if buy_qty > 0 and bid_px > 0:
        orders.append(("Order", symbol, bid_px, buy_qty))
    if sell_qty > 0 and ask_px > 0:
        orders.append(("Order", symbol, ask_px, -sell_qty))
    return orders


# ============================================================================
# A1 DECISION: REJECT quote_size_bid and quote_size_ask from Pass 2.6 search
# ============================================================================
#
# Patch assessment:
#   Lines changed: 6 (vs ~20-line function, ~30% change)
#   New branching: 0 (only min() calls, no new if/else)
#   Risk of bug: LOW — the cap is applied after all price logic, before Order construction.
#     Worst case: if qs_bid/qs_ask > buy_room/sell_room, min() safely clips to room.
#     No position limit violation possible (room is always the true upper bound).
#   Patch is trustworthy.
#
# Reason to EXCLUDE despite trustworthy patch:
#
#   1. MECHANISM MISMATCH: A0's decomposition shows qo5 is 96.4% spread_capture.
#      Passive fill count: 362-383 per day. Each fill fills 1 unit at a time (verified in
#      aco_param_search.py line ~337: `record_fill(j, bid_px, 1, 'passive')` — fills
#      are one unit at a time, not the full quoted size). The "fill remaining room" behavior
#      means we post a large quote but only get filled 1 unit per incoming trade event.
#      The quoted SIZE does not change how many units get filled per tick; it only controls
#      whether we can accumulate to large |pos| over many ticks.
#
#   2. ACTUAL EFFECT OF CAPPING: A cap of quote_size_bid=30 (vs unlimited=80) would
#      ONLY matter when pos is already near +50 (room < 30). In that case, both behaviors
#      are equivalent (room < cap => min(room, cap) = room). The cap only bites when
#      room is large AND we would otherwise quote the full 80 units — but since fills are
#      1 unit/event anyway, the quoted size above 1 is never the binding constraint.
#      The parameter has near-zero marginal effect on actual fill outcomes.
#
#   3. PARAMETER BUDGET: With 6-parameter cap, including two near-zero-effect parameters
#      burns 2 slots from the budget at the cost of legitimate free parameters (take_edge,
#      ema_alpha) that have genuine upside (see A1 justifications).
#
#   4. SEARCH EFFICIENCY: 300 LHS samples across 6 dimensions already gives ~2.9 samples
#      per dim per std dev. Adding quote_size_bid and quote_size_ask together in the same
#      sweep (total 7 or 8 params) would drop effective coverage per important dimension
#      below the LHS efficiency floor.
#
# Conclusion: The patch is mechanically sound (~6 lines, no new branching), but the
# parameter is excluded because the current "fill remaining room" behavior is not
# worth disturbing: fills are already bounded to 1 unit/event by the engine's
# order-matching model, making the cap a no-op in practice.
