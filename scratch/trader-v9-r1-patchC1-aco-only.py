"""
Round 1 Trader — v9-r1-aco-only
=================================

ACO-only variant of trader-v9-r1.py.
ACTIVE_PRODUCTS = {"ASH_COATED_OSMIUM"} — IPR is gated out.
All IPR constants and code remain in this file; only the set constant changes.

See trader-v9-r1.py for full strategy notes.
"""

from datamodel import OrderDepth, TradingState, Order  # type: ignore
from typing import Dict, List, Tuple
import collections
import jsonpickle  # type: ignore
import math

# ---------------------------------------------------------------------------
# Active products — single gating constant used by all single-product variants.
# Only products in this set are processed; all others are skipped.
# ---------------------------------------------------------------------------
ACTIVE_PRODUCTS = {"ASH_COATED_OSMIUM"}

# ---------------------------------------------------------------------------
# Engine constants
# ---------------------------------------------------------------------------
TIMESTAMP_MAX = 999_900
EOD_START     = 950_000

POSITION_LIMITS: Dict[str, int] = {
    "ASH_COATED_OSMIUM":     80,   # r1_product_mechanics.md §ACO Position Limit
    "INTARIAN_PEPPER_ROOT":  80,   # r1_product_mechanics.md §IPR Position Limit
}

# ===========================================================================
# ACO PARAMETERS — KELP-analog market making
# Source: PLAN.md §ACO (b)/(d)/(e)/(f)/(g) and r1_eda_summary.md §Section 3
# ===========================================================================

# Adverse-volume filter for mmbot-mid computation.
# KELP playbook default (imc3_r1_playbook.md §2 PARAMS). ACO L1 is 100% quoted.
ACO_ADVERSE_VOLUME      = 15

# Mean-reversion beta applied to last log-return of mmbot mid.
# Midpoint of EDA-recommended range -0.40 to -0.50 (lag-1 autocorr = -0.494).
# PLAN.md §ACO (d) committed parameters.
ACO_REVERSION_BETA      = -0.45

# Take layer: take if ask <= fv - take_width or bid >= fv + take_width.
# KELP playbook default 1.5; ACO tick vol = 1.9. PLAN.md §ACO (e) ACO_CFG_V2.
ACO_TAKE_WIDTH          = 3.0

# Clear layer: zero-EV inventory clearing at fv ± clear_width.
# KELP default 0; with clear_width=0 we only clear at exactly fv. PLAN.md §ACO (e).
ACO_CLEAR_WIDTH         = 0.0

# Make layer: passive quote offset from (inventory-skewed) fair value.
# KELP default_edge=1. PLAN.md §ACO (e) ACO_CFG_V2 "default_edge".
ACO_DEFAULT_EDGE        = 1

# Inventory skew per unit of position: shift fair value to encourage unwinding.
# KELP retreat_per_lot=0.012 scaled up for ACO. PLAN.md §ACO (e) ACO_CFG_V2.
ACO_INVENTORY_PENALTY   = 0.025

# Deflection kill switch threshold: suppress quoting on side that moved sharply.
# PLAN.md §ACO (g) — ACO intraday range 27-36; 2.0 is a ~7% move of daily range.
ACO_DEFLECTION_THR      = 2.0

# Slow-oscillation range bias window (timesteps stored as rolling deque).
# PLAN.md §ACO (d) "trailing_range_window = 500 timesteps".
ACO_RANGE_WINDOW        = 500

# Top/bottom fraction of the range that triggers the bias.
# PLAN.md §ACO (d) "range_bias_threshold = 0.20".
ACO_RANGE_BIAS_THRESHOLD = 0.20

# Multiplier applied to passive size on the biased side (halve it).
# PLAN.md §ACO (d) "range_bias_factor = 0.50".
ACO_RANGE_BIAS_FACTOR   = 0.50

# Position limit — must match POSITION_LIMITS dict.
ACO_POSITION_LIMIT      = 80   # r1_product_mechanics.md §ACO Position Limit

# Minimum trailing-mids history before range bias activates (stability guard).
ACO_RANGE_MIN_HISTORY   = 50

# ===========================================================================
# IPR PARAMETERS — Config A drift capture + circuit breaker
# Source: PLAN.md §IPR (a)/(b)/(c)/(d)/(f) and pepper_root_findings.md
# ===========================================================================

# Deterministic drift per tick (XIRECS/tick), hardcoded from empirical mean.
# pepper_root_findings.md §Finding 1: +1001.3/day ÷ 10000 ticks/day.
# PLAN.md §IPR (a) "drift_per_tick = 1001.3 / 10000".
IPR_DRIFT_PER_TICK      = 0.10013

# Config A target position: buy to the position limit for maximum drift capture.
# Config A committed in PLAN.md §IPR intro; pepper_root_findings.md §Finding 5.
IPR_TARGET_POSITION     = 80

# Skim ask: size of sell order posted above market when pinned at limit.
# PLAN.md §IPR (b): increased from 5 to 8 once position pinned at 80.
IPR_SKIM_SIZE           = 8

# Skim trigger: minimum position before skim ask is posted.
# PLAN.md §IPR (b): unchanged at 75 (pepper_root_findings.md §Note 1).
IPR_SKIM_TRIGGER        = 75

# Skim offset: ticks above best_ask for the skim sell order.
# PLAN.md §IPR (b): tightened from 2 to 1 to improve fill rate.
IPR_SKIM_OFFSET         = 1

# Refill bid offset: ticks above best_bid for the refill buy order.
# PLAN.md §IPR (b): unchanged at 1.
IPR_REFILL_OFFSET       = 1

# Refill max size per tick when below target.
# PLAN.md §IPR (b): unchanged at 10 (always >= skim_size to prevent bottleneck).
IPR_REFILL_MAX_SIZE     = 10

# Long-only hard floor: position must never go below this value.
# ipr_mm_synthesis.md §long-only floor: "Never quote an ask that could take position net short."
# PLAN.md §IPR (c): floor = 0 (never net short).
IPR_LONG_ONLY_FLOOR     = 0

# Passive bid entry: how many ticks BELOW fv(t) to post the passive entry bid.
# PLAN.md §IPR (a): "passive bids at fv(t) - spread/2"; spread ~2 ticks → offset=1.
IPR_ENTRY_OFFSET        = 1

# Passive bid fallback: after this many timesteps without reaching target, switch to greedy.
# PLAN.md §IPR (f) sweep table: starting value N=20.
IPR_PASSIVE_BID_FALLBACK_N = 20

# Circuit breaker rolling window (timesteps of mid-price history stored).
# PLAN.md §IPR (d): W=500 timesteps (5% of a day).
IPR_CIRCUIT_W           = 500

# Circuit breaker sensitivity (standard deviations below prior drift mean).
# PLAN.md §IPR (d): k=5.0 → fires only on a full reversal, not noise.
IPR_CIRCUIT_K           = 5.0

# Absolute safety floor on realized drift (XIRECS/day) below prior mean.
# PLAN.md §IPR (d): abs_floor=50 absorbs 3.5 XIREC day-to-day variation.
IPR_CIRCUIT_ABS_FLOOR   = 50.0

# Per-day tick-volatility std used in the circuit breaker formula.
# pepper_root_findings.md §Finding 1: per-day drift std = 1.8 XIRECS/day.
# Used in PLAN.md §IPR (d) formula for W=500 noise bound.
IPR_CIRCUIT_STD_DRIFT   = 1.8

# Position limit — must match POSITION_LIMITS dict.
IPR_POSITION_LIMIT      = 80   # r1_product_mechanics.md §IPR Position Limit


# ===========================================================================
# Shared helpers
# ===========================================================================

def best_bid_ask(depth: OrderDepth) -> Tuple[int, int]:
    return max(depth.buy_orders), min(depth.sell_orders)


def vwap_mid(depth: OrderDepth) -> float:
    """Volume-weighted average of best bid and best ask; fallback to simple mid."""
    bid_val = sum(p * q for p, q in depth.buy_orders.items())
    bid_vol = sum(depth.buy_orders.values())
    ask_val = sum(p * abs(q) for p, q in depth.sell_orders.items())
    ask_vol = sum(abs(q) for q in depth.sell_orders.values())
    if bid_vol == 0 or ask_vol == 0:
        bb, ba = best_bid_ask(depth)
        return (bb + ba) / 2.0
    return (bid_val / bid_vol + ask_val / ask_vol) / 2.0


def eod_urgency(timestamp: int) -> float:
    """Returns 0.0 before EOD_START, rises to 1.0 at TIMESTAMP_MAX."""
    if timestamp < EOD_START:
        return 0.0
    return min(1.0, (timestamp - EOD_START) / (TIMESTAMP_MAX - EOD_START))


# ===========================================================================
# ACO helpers — KELP-analog market making
# ===========================================================================

def aco_mmbot_mid(depth: OrderDepth, adverse_vol: int, prev_mmbot_mid: float) -> float:
    """
    Filter order book for large-volume orders and compute midpoint.
    Fallback to prev_mmbot_mid if filtered book is empty on either side.
    PLAN.md §ACO (d) formula for mmbot_mid(t).
    """
    filtered_bids = [p for p, q in depth.buy_orders.items()  if q  >= adverse_vol]
    filtered_asks = [p for p, q in depth.sell_orders.items() if abs(q) >= adverse_vol]
    if not filtered_bids or not filtered_asks:
        return prev_mmbot_mid
    return (max(filtered_bids) + min(filtered_asks)) / 2.0


def aco_fair_value(mmbot_mid: float, prev_mmbot_mid: float, reversion_beta: float) -> float:
    """
    Apply mean-reversion adjustment to mmbot mid.
    fv = mmbot_mid + mmbot_mid * last_return * beta.
    beta is negative, so a positive last_return (price rose) pulls fv down.
    PLAN.md §ACO (d) linearized formula.
    """
    if prev_mmbot_mid <= 0:
        return mmbot_mid
    last_return = (mmbot_mid - prev_mmbot_mid) / prev_mmbot_mid
    return mmbot_mid + mmbot_mid * last_return * reversion_beta


def aco_range_bias(mmbot_mid: float, trailing_mids: collections.deque, min_history: int,
                   thr: float) -> int:
    """
    Slow-oscillation range bias for make-layer sizing.
    Returns +1 (near top → reduce passive bids), -1 (near bottom → reduce passive asks), 0 (neutral).
    PLAN.md §ACO (d) range_bias formula.
    """
    if len(trailing_mids) < min_history:
        return 0
    lo, hi = min(trailing_mids), max(trailing_mids)
    if hi == lo:
        return 0
    pos_in_range = (mmbot_mid - lo) / (hi - lo)
    if pos_in_range > (1 - thr):
        return +1
    if pos_in_range < thr:
        return -1
    return 0


def aco_deflection_side(fv_change: float, deflection_thr: float):
    """
    Kill-switch: returns 'ask' (suppress asks), 'bid' (suppress bids), or None.
    A sharp up-move → don't post more asks (price may keep rising).
    A sharp down-move → don't post more bids.
    PLAN.md §ACO (g) deflection kill switch.
    """
    if fv_change > deflection_thr:
        return 'ask'
    if fv_change < -deflection_thr:
        return 'bid'
    return None


def aco_take(symbol: str, depth: OrderDepth, fv: float, pos: int,
             limit: int, take_width: float):
    """
    Take layer: hit asks at fv - take_width or better; hit bids at fv + take_width or better.
    PLAN.md §ACO (e) aco_take_v2.
    """
    orders = []
    for ap in sorted(depth.sell_orders):
        if ap > fv - take_width:
            break
        room = limit - pos
        if room <= 0:
            break
        qty = min(-depth.sell_orders[ap], room)
        orders.append(Order(symbol, ap, qty))
        pos += qty
    for bp in sorted(depth.buy_orders, reverse=True):
        if bp < fv + take_width:
            break
        room = limit + pos
        if room <= 0:
            break
        qty = min(depth.buy_orders[bp], room)
        orders.append(Order(symbol, bp, -qty))
        pos -= qty
    return orders, pos


def aco_clear(symbol: str, depth: OrderDepth, fv: float, pos: int,
              limit: int, clear_width: float):
    """
    Clear layer: zero-EV inventory reduction at fv ± clear_width.
    With clear_width=0 only executes at exactly fv.
    PLAN.md §ACO (e) aco_clear_v2.
    """
    orders = []
    if pos > 0:
        for bp in sorted(depth.buy_orders, reverse=True):
            if bp < fv - clear_width:
                break
            qty = min(depth.buy_orders[bp], pos)
            if qty > 0:
                orders.append(Order(symbol, bp, -qty))
                pos -= qty
    elif pos < 0:
        for ap in sorted(depth.sell_orders):
            if ap > fv + clear_width:
                break
            qty = min(-depth.sell_orders[ap], -pos)
            if qty > 0:
                orders.append(Order(symbol, ap, qty))
                pos += qty
    return orders, pos


def aco_make(symbol: str, fv: float, pos: int, limit: int,
             range_bias: int, deflected_side, urgency: float) -> List[Order]:
    """
    Make layer: post passive quotes around inventory-skewed fair value.
    deflected_side: 'bid', 'ask', or None — suppress quoting on that side.
    range_bias: +1 reduce bids (near top), -1 reduce asks (near bottom), 0 neutral.
    PLAN.md §ACO (e) aco_make_v2 + eod_urgency from trader-v8 pattern.
    """
    # Inventory skew: shift fv to encourage unwinding
    skew = pos * ACO_INVENTORY_PENALTY
    skewed_fv = fv - skew  # long → pull fv down → bid lower, ask lower

    edge = ACO_DEFAULT_EDGE
    # EOD urgency: tighten quotes (match trader-v8 urgency pattern)
    if urgency > 0 and abs(pos) > 0:
        edge = max(0, edge - round(urgency * edge))

    bid_px = math.floor(skewed_fv) - edge
    ask_px = math.ceil(skewed_fv) + edge

    # Ensure quotes don't cross
    if ask_px <= bid_px:
        ask_px = bid_px + 1

    # Base sizes: remaining capacity on each side
    buy_qty  = limit - pos
    sell_qty = limit + pos

    # Apply slow-oscillation range bias (halve size on biased side)
    if range_bias == +1:
        buy_qty  = int(buy_qty  * ACO_RANGE_BIAS_FACTOR)
    elif range_bias == -1:
        sell_qty = int(sell_qty * ACO_RANGE_BIAS_FACTOR)

    orders: List[Order] = []
    if deflected_side != 'bid' and buy_qty > 0 and bid_px > 0:
        orders.append(Order(symbol, bid_px, buy_qty))
    if deflected_side != 'ask' and sell_qty > 0 and ask_px > 0:
        orders.append(Order(symbol, ask_px, -sell_qty))
    return orders


# ===========================================================================
# Per-tick budget helpers — enforce engine position-limit invariant
# ===========================================================================

def _capped_buy(orders_list: List[Order], symbol: str, price: int, qty: int,
                current_pos: int, limit: int) -> int:
    """
    Append a buy order, capped by remaining per-tick buy budget.
    Budget = limit - current_pos - sum(existing buy-order quantities in orders_list).
    Returns actual quantity appended (may be 0 if budget exhausted).
    """
    existing_buy_vol = sum(o.quantity for o in orders_list if o.quantity > 0)
    remaining_budget = limit - current_pos - existing_buy_vol
    actual_qty = min(qty, remaining_budget)
    if actual_qty > 0:
        orders_list.append(Order(symbol, price, actual_qty))
    return actual_qty


def _capped_sell(orders_list: List[Order], symbol: str, price: int, qty: int,
                 current_pos: int, limit: int) -> int:
    """
    Append a sell order, capped by remaining per-tick sell budget.
    qty is positive (the magnitude of the sell). The appended Order has -qty.
    Budget = limit + current_pos - abs(sum(existing sell-order quantities)).
    Returns actual quantity appended as a positive number (may be 0).
    """
    existing_sell_vol = sum(-o.quantity for o in orders_list if o.quantity < 0)
    remaining_budget = limit + current_pos - existing_sell_vol
    actual_qty = min(qty, remaining_budget)
    if actual_qty > 0:
        orders_list.append(Order(symbol, price, -actual_qty))
    return actual_qty


# ===========================================================================
# IPR helpers — Config A drift capture + circuit breaker
# ===========================================================================

def ipr_circuit_triggered(mid_history: collections.deque) -> bool:
    """
    Realized-drift circuit breaker (PLAN.md §IPR (d)).
    Returns True (TRIGGERED) when realized drift over W ticks deviates from
    prior drift mean by more than k standard deviations + absolute floor.

    Formula:
      realized_drift_W = (mid[-1] - mid[-W]) / W * 10000   (XIRECS/day)
      trigger if realized_drift_W < IPR_DRIFT_MEAN_DAY - k*sigma - abs_floor
    where:
      IPR_DRIFT_MEAN_DAY = 1001.3 XIRECS/day (pepper_root_findings.md §Finding 1)
      sigma = tick_vol * sqrt(W) / W * 10000  (PLAN.md §IPR (d) W and k justification)
      k = IPR_CIRCUIT_K = 5.0
      abs_floor = IPR_CIRCUIT_ABS_FLOOR = 50.0
    """
    if len(mid_history) < IPR_CIRCUIT_W:
        return False  # not enough history — stay NORMAL
    mid_now  = mid_history[-1]
    mid_past = mid_history[-IPR_CIRCUIT_W]
    realized = (mid_now - mid_past) / IPR_CIRCUIT_W * 10000.0

    drift_mean   = 1001.3  # XIRECS/day — pepper_root_findings.md §Finding 1
    # sigma of the W-tick realized drift estimate (PLAN.md §IPR (d) formula)
    sigma_w      = IPR_CIRCUIT_STD_DRIFT * math.sqrt(IPR_CIRCUIT_W) / IPR_CIRCUIT_W * 10000.0
    threshold    = drift_mean - IPR_CIRCUIT_K * sigma_w - IPR_CIRCUIT_ABS_FLOOR
    return realized < threshold


def ipr_orders(symbol: str, depth: OrderDepth, pos: int, limit: int,
               day_start_price: float, timestamp: int,
               last_fill_ts,
               mid_history: collections.deque,
               circuit_frozen: bool) -> List[Order]:
    """
    IPR v9-r1 order generation.

    Steps:
    1. Circuit breaker check — if triggered, freeze new entry orders (hold existing).
       PLAN.md §IPR (d) action: FREEZE, not liquidate. Never flip to short.
    2. If not at target and circuit NOT triggered:
       a. Post passive bid at fv(t) - IPR_ENTRY_OFFSET.
       b. After IPR_PASSIVE_BID_FALLBACK_N timesteps without reaching target,
          fall back to greedy take (same as v8 aggressive entry).
    3. If position >= IPR_SKIM_TRIGGER and circuit NOT triggered:
       Post skim ask at best_ask + IPR_SKIM_OFFSET.
       HARD GUARD: only if pos - skim_size >= IPR_LONG_ONLY_FLOOR.
    4. If pos < target and not circuit frozen:
       Post refill bid at best_bid + IPR_REFILL_OFFSET (capped at best_ask - 1).

    Returns (orders, updated_last_fill_ts).
    """
    orders: List[Order] = []
    bb, ba = best_bid_ask(depth)
    current_mid = (bb + ba) / 2.0

    # ---- Circuit breaker check ----------------------------------------
    # Action: if triggered, set effective target to current position (freeze).
    # Do NOT set target to 0 in the sense of selling down — just stop buying.
    # PLAN.md §IPR (d): "freeze target at 0 (stop adding, hold existing)".
    # Hard invariant #3: freeze means target = pos (no new buys, no sells).
    if circuit_frozen:
        effective_target = pos  # don't accumulate further
    else:
        effective_target = IPR_TARGET_POSITION

    # ---- STEP 1: Entry (passive or greedy) ---------------------------------
    if pos < effective_target and not circuit_frozen:
        # Compute drift-adjusted fair value for passive entry bid placement.
        # PLAN.md §IPR (a): fv(t) = price_at_day_start + drift_per_tick * (t / 100)
        # timestamps step in increments of 100; t/100 = tick index within day.
        tick_idx = timestamp / 100.0
        fv_entry = day_start_price + IPR_DRIFT_PER_TICK * tick_idx
        passive_bid_px = int(math.floor(fv_entry - IPR_ENTRY_OFFSET))

        # Only post passive bid if it's below the current ask (don't cross spread)
        if passive_bid_px < ba and passive_bid_px > 0:
            room = limit - pos
            if room > 0:
                _capped_buy(orders, symbol, passive_bid_px, room, pos, limit)
                # Track fill progress: we'll detect actual fills via position delta
                # last_fill_ts is updated externally in Trader.run() after comparing positions

        # Greedy fallback: if we haven't reached target for IPR_PASSIVE_BID_FALLBACK_N ticks
        # (last_fill_ts is None or stale), sweep the ask side aggressively.
        # last_fill_ts == None means we've never filled (first tick of the day).
        if last_fill_ts is not None:
            ticks_since_fill = (timestamp - last_fill_ts) / 100.0
            if ticks_since_fill >= IPR_PASSIVE_BID_FALLBACK_N:
                # Greedy: sweep all available ask levels
                greedy_orders: List[Order] = []
                need = effective_target - pos
                for ap in sorted(depth.sell_orders):
                    if need <= 0:
                        break
                    qty_available = min(-depth.sell_orders[ap], need)
                    appended = _capped_buy(greedy_orders, symbol, ap, qty_available, pos, limit)
                    pos += appended
                    need -= appended
                    if appended == 0:
                        break
                if greedy_orders:
                    # Replace passive bid with greedy orders
                    orders = greedy_orders

    # ---- Recompute room after possible entry orders --------------------------
    # Note: pos here reflects greedy fills in the fallback path only.
    # For passive bids, pos is unchanged (fills happen next tick).
    # For skim/refill sizing we use the pre-order pos for conservatism.
    room_long_sell = limit + pos  # how many we can sell from our long

    # ---- STEP 2: Skim ask (only when near limit) ----------------------------
    # IPR LONG-ONLY POLICY (per ipr_mm_synthesis.md):
    # Drift works against short positions every tick. All sells reduce an existing long
    # — never cross zero. The guard clause below is the HARD INVARIANT (Hard invariant #1).
    if pos >= IPR_SKIM_TRIGGER:
        skim_size = min(IPR_SKIM_SIZE, room_long_sell)
        # HARD GUARD: never post a sell that would drop position below the long-only floor.
        # This is the explicit, unbypassable guard required by Hard invariant #1.
        # _capped_sell runs AFTER this guard — the guard determines whether a sell is allowed
        # at all; _capped_sell caps the quantity if a sell is allowed.
        if skim_size > 0 and (pos - skim_size) >= IPR_LONG_ONLY_FLOOR:
            skim_px = ba + IPR_SKIM_OFFSET
            _capped_sell(orders, symbol, skim_px, skim_size, pos, limit)

    # ---- STEP 3: Refill bid (when below target, circuit not frozen) ----------
    if pos < IPR_TARGET_POSITION and not circuit_frozen:
        refill_size = min(IPR_REFILL_MAX_SIZE, limit - pos)
        if refill_size > 0:
            refill_px = bb + IPR_REFILL_OFFSET
            if refill_px < ba:  # don't cross the ask
                _capped_buy(orders, symbol, refill_px, refill_size, pos, limit)

    return orders


# ===========================================================================
# Trader
# ===========================================================================

class Trader:
    def run(self, state: TradingState):
        # ---- Load persisted state -------------------------------------------
        saved: dict = {}
        if state.traderData:
            try:
                saved = jsonpickle.decode(state.traderData)
            except Exception:
                pass

        # ACO state
        aco_mmbot:    Dict[str, float] = saved.get("aco_mmbot", {})
        aco_fv:       Dict[str, float] = saved.get("aco_fv", {})
        aco_trailing_raw: Dict[str, list] = saved.get("aco_trailing", {})

        # IPR state
        ipr_day_start_price: Dict[str, float] = saved.get("ipr_day_start_price", {})
        ipr_last_fill_ts:    Dict[str, object] = saved.get("ipr_last_fill_ts", {})
        ipr_mid_history_raw: Dict[str, list]   = saved.get("ipr_mid_history", {})
        ipr_prev_pos:        Dict[str, int]    = saved.get("ipr_prev_pos", {})
        ipr_prev_ts:         Dict[str, int]    = saved.get("ipr_prev_ts", {})

        result: Dict[str, List[Order]] = {}
        t = state.timestamp
        urgency = eod_urgency(t)

        for symbol, depth in state.order_depths.items():
            # ACTIVE_PRODUCTS gating — skip anything not in the set.
            # Hard invariant #5: this is the sole product gate; no other branching.
            if symbol not in ACTIVE_PRODUCTS:
                continue
            if not depth.buy_orders or not depth.sell_orders:
                continue

            pos   = state.position.get(symbol, 0)
            limit = POSITION_LIMITS.get(symbol, 80)

            # ================================================================
            # ACO — KELP-analog market making
            # ================================================================
            if symbol == "ASH_COATED_OSMIUM":
                # Reconstruct deque from saved list
                trailing_list = aco_trailing_raw.get(symbol, [])
                trailing_mids: collections.deque = collections.deque(
                    trailing_list, maxlen=ACO_RANGE_WINDOW
                )

                # Compute mmbot mid with adverse-volume filter
                prev_mmb = aco_mmbot.get(symbol)
                if prev_mmb is None:
                    prev_mmb = vwap_mid(depth)  # first tick fallback
                mmb = aco_mmbot_mid(depth, ACO_ADVERSE_VOLUME, prev_mmb)

                # Compute fair value with reversion beta
                prev_fv = aco_fv.get(symbol)
                if prev_fv is None:
                    fv = mmb  # first tick: no reversion adjustment yet
                else:
                    fv = aco_fair_value(mmb, prev_mmb, ACO_REVERSION_BETA)

                # Deflection kill switch
                fv_change = fv - (prev_fv if prev_fv is not None else fv)
                deflected = aco_deflection_side(fv_change, ACO_DEFLECTION_THR)

                # Append current mmb and compute range bias
                trailing_mids.append(mmb)
                bias = aco_range_bias(mmb, trailing_mids, ACO_RANGE_MIN_HISTORY,
                                      ACO_RANGE_BIAS_THRESHOLD)

                # Execute: take → clear → make
                take_ords, pos2 = aco_take(symbol, depth, fv, pos, limit, ACO_TAKE_WIDTH)
                clear_ords, pos3 = aco_clear(symbol, depth, fv, pos2, limit, ACO_CLEAR_WIDTH)
                make_ords = aco_make(symbol, fv, pos3, limit, bias, deflected, urgency)
                result[symbol] = take_ords + clear_ords + make_ords

                # Save ACO state
                aco_mmbot[symbol]   = mmb
                aco_fv[symbol]      = fv
                aco_trailing_raw[symbol] = list(trailing_mids)

            # ================================================================
            # IPR — Config A drift capture + refinements + circuit breaker
            # ================================================================
            elif symbol == "INTARIAN_PEPPER_ROOT":
                bb, ba = best_bid_ask(depth)
                current_mid = (bb + ba) / 2.0

                # ---- Reconstruct mid history deque --------------------------
                mid_hist_list = ipr_mid_history_raw.get(symbol, [])
                mid_history: collections.deque = collections.deque(
                    mid_hist_list, maxlen=IPR_CIRCUIT_W
                )

                # ---- Day-boundary detection + state reset -------------------
                # PLAN.md §IPR (d): the circuit breaker's rolling window must NOT
                # carry state across day boundaries. Detect new day via timestamp
                # wrapping from near TIMESTAMP_MAX back to near 0.
                # Hard invariant #2: reset mid_history and day_start_price on new day.
                prev_ts = ipr_prev_ts.get(symbol, t)
                if prev_ts > EOD_START and t < EOD_START:
                    # Timestamp wrapped — new day started
                    mid_history.clear()
                    ipr_day_start_price.pop(symbol, None)
                    ipr_last_fill_ts[symbol] = None

                # ---- Set day-start price on first tick with a two-sided book -
                if symbol not in ipr_day_start_price:
                    ipr_day_start_price[symbol] = current_mid
                    ipr_last_fill_ts[symbol]    = None  # haven't filled yet this day

                day_start_price = ipr_day_start_price[symbol]

                # ---- Detect fills from previous tick -----------------------
                # If pos increased vs prev_pos, a fill happened; update last_fill_ts.
                prev_pos = ipr_prev_pos.get(symbol, 0)
                if pos > prev_pos:
                    ipr_last_fill_ts[symbol] = t

                last_fill_ts = ipr_last_fill_ts.get(symbol)

                # ---- Append mid to history ----------------------------------
                mid_history.append(current_mid)

                # ---- Circuit breaker evaluation ----------------------------
                # PLAN.md §IPR (d): check realized drift over W ticks.
                # Hard invariant #3: FREEZE means stop buying, hold existing — NOT liquidate.
                circuit_frozen = ipr_circuit_triggered(mid_history)

                # ---- Generate IPR orders ------------------------------------
                orders = ipr_orders(
                    symbol, depth, pos, limit,
                    day_start_price, t,
                    last_fill_ts,
                    mid_history,
                    circuit_frozen
                )
                result[symbol] = orders

                # ---- Save IPR state -----------------------------------------
                ipr_mid_history_raw[symbol]  = list(mid_history)
                ipr_prev_pos[symbol]         = pos
                ipr_prev_ts[symbol]          = t

        # ---- Persist all state ---------------------------------------------
        saved["aco_mmbot"]          = aco_mmbot
        saved["aco_fv"]             = aco_fv
        saved["aco_trailing"]       = aco_trailing_raw
        saved["ipr_day_start_price"] = ipr_day_start_price
        saved["ipr_last_fill_ts"]   = ipr_last_fill_ts
        saved["ipr_mid_history"]    = ipr_mid_history_raw
        saved["ipr_prev_pos"]       = ipr_prev_pos
        saved["ipr_prev_ts"]        = ipr_prev_ts

        return result, 0, jsonpickle.encode(saved)
