"""
R3 Phase-3 diagnostic baseline: VEV pure z-score mean-reversion scalp.

NOT a production trader. Built solely as a comparison probe against
trader-r3-v1-vev-meanrev.py. The MM template implicitly captures MR via
its skewed-quote layer; this scalp captures MR explicitly via a z-score
gate. We backtest both side-by-side and decompose the MM PnL to figure
out whether the MM template is leaking PnL to a pure-scalp formulation.

Strategy:
  - EMA of mid, window=50 (matches MM template for apples-to-apples).
  - Rolling stdev of (mid - EMA) over a 200-tick window.
  - z = (mid - EMA) / rolling_stdev.
  - Entry: when |z| > 2.0, take 30 in the mean-reverting direction
    (z > 2.0 means mid is too high -> sell; z < -2.0 means mid is too
    low -> buy). Stack up to 3 entries deep (max position +-90).
  - Exit each entry when z reaches the OPPOSITE-SIDE threshold of -0.3
    relative to entry sign (long entry exits at z < -0.3, short entry
    exits at z > 0.3) OR after 500 ticks held (whichever first). The
    overshoot threshold gives reversion room to overshoot zero before
    we exit, since N1's half-life of 248 ticks means the OU process
    naturally crosses zero before settling.
  - Robust tick counter persisted in traderData; resets across days
    because the rust backtester instantiates a fresh Trader per day,
    so timestamp resets to 0 - we treat each day as independent.
  - No drift kill. No passive quotes. No skew. This is a probe, not
    a production trader.

All parameters tied to N1 numbers or to "matches MM template for
apples-to-apples comparison".
"""

from datamodel import OrderDepth, TradingState, Order  # type: ignore
from typing import Dict, List
import json
import math

PRODUCT = "VELVETFRUIT_EXTRACT"

# N1: VEV demeaned-level half-life is 248 ticks. EMA50 (alpha~0.039,
# half-life ~33 ticks) tracks the slow drift well within the MR cycle.
# Same as MM template - apples-to-apples.
EMA_WINDOW = 50
# Rolling stdev window. 200 ticks is ~80% of one MR half-life - long
# enough to estimate the deviation distribution stably, short enough
# that within-day drift doesn't pollute it (KPSS rejects level
# stationarity around a constant per N1 cell 14).
STDEV_WINDOW = 200
# Z entry threshold: widened from 1.5 (Stage-1 default) to 2.0 to filter
# out shallower deviations that bled out at the 5-wide spread cost. |z|>2
# is ~5% of ticks in a normal distribution.
Z_OPEN = 2.0
# Exit threshold (opposite-sign overshoot). Long exits when z drops below
# -Z_EXIT, short exits when z rises above +Z_EXIT. Allows reversion to
# overshoot fair before we close - matches the OU half-life mechanic in
# N1's findings (mid mean-reverts past the EMA before settling).
Z_EXIT = 0.3
# Cap hold at 500 ticks (~2x the N1 half-life of 248) to bound drawdowns
# when reversion fails to materialize.
MAX_HOLD_TICKS = 500
# Per-entry take size. Matches MM template's aggressive_take_size_cap=30
# for apples-to-apples. Stacking up to 3 deep gives max |pos|=90, well
# inside the +-200 limit.
ENTRY_SIZE = 30
MAX_ENTRIES = 3
POSITION_LIMIT = 200


class Trader:
    def run(self, state: TradingState):
        try:
            saved = json.loads(state.traderData) if state.traderData else {}
        except Exception as e:
            saved = {"_traderData_error": repr(e)}

        ema = saved.get("ema_fv")
        # Rolling buffer of (mid - EMA) deviations for stdev.
        dev_buf: List[float] = saved.get("dev_buf", [])
        # Open entries: list of {"sign": +1/-1, "tick": int}.
        # +1 = long (we bought), -1 = short (we sold).
        entries: List[Dict] = saved.get("entries", [])
        # Robust tick counter persisted in traderData. Increments once per
        # call; survives within-day. The rust backtester instantiates a
        # fresh Trader per day, so traderData starts empty and tick=0 on
        # day 0 of each day's run - which is what we want for "held"
        # measurements (no cross-day leak).
        tick = int(saved.get("tick", 0))
        tick += 1
        saved["tick"] = tick

        result: Dict[str, List[Order]] = {}

        depth = state.order_depths.get(PRODUCT)
        if depth is None or not depth.buy_orders or not depth.sell_orders:
            saved["ema_fv"] = ema
            saved["dev_buf"] = dev_buf
            saved["entries"] = entries
            return result, 0, json.dumps(saved)

        best_bid = max(depth.buy_orders)
        best_ask = min(depth.sell_orders)
        mid = 0.5 * (best_bid + best_ask)

        alpha = 2.0 / (EMA_WINDOW + 1.0)
        ema = mid if ema is None else alpha * mid + (1.0 - alpha) * ema

        dev = mid - ema
        dev_buf.append(dev)
        if len(dev_buf) > STDEV_WINDOW:
            dev_buf = dev_buf[-STDEV_WINDOW:]

        pos = state.position.get(PRODUCT, 0)
        orders: List[Order] = []

        # Need enough samples to estimate stdev meaningfully.
        if len(dev_buf) < STDEV_WINDOW // 2:
            saved["ema_fv"] = ema
            saved["dev_buf"] = dev_buf
            saved["entries"] = entries
            return result, 0, json.dumps(saved)

        mu = sum(dev_buf) / len(dev_buf)
        var = sum((x - mu) ** 2 for x in dev_buf) / max(len(dev_buf) - 1, 1)
        sd = math.sqrt(var) if var > 0 else 0.0
        z = (dev - mu) / sd if sd > 1e-9 else 0.0

        # ---- Exits first ---------------------------------------------------
        # An entry exits when z crosses zero (relative to its sign) or
        # when held >= MAX_HOLD_TICKS.
        remaining: List[Dict] = []
        for e in entries:
            sign = e["sign"]
            held = tick - e["tick"]
            # Exit when z reaches opposite-side overshoot threshold, or
            # hold limit hit. Long entered at z<<0 -> exit when z has
            # reverted ABOVE 0 by Z_EXIT (overshoot up). Short entered
            # at z>>0 -> exit when z has reverted BELOW 0 by Z_EXIT.
            crossed = (sign == +1 and z > Z_EXIT) or (sign == -1 and z < -Z_EXIT)
            timed_out = held >= MAX_HOLD_TICKS
            if crossed or timed_out:
                # Close this entry: if we were long (+1), sell back; short, buy back.
                if sign == +1:
                    # Sell at best_bid up to ENTRY_SIZE.
                    qty = min(ENTRY_SIZE, depth.buy_orders.get(best_bid, 0))
                    if qty > 0:
                        orders.append(Order(PRODUCT, best_bid, -qty))
                else:
                    qty = min(ENTRY_SIZE, -depth.sell_orders.get(best_ask, 0))
                    if qty > 0:
                        orders.append(Order(PRODUCT, best_ask, qty))
                # Whether or not we got volume, mark this entry closed -
                # we'll rely on the next tick's residual position to
                # generate any unfilled portion's continuation. (For the
                # diagnostic comparison this is acceptable; production
                # would track unfilled fragments.)
            else:
                remaining.append(e)
        entries = remaining

        # ---- Entries -------------------------------------------------------
        # Open a new entry only if we have room (< MAX_ENTRIES open) AND
        # |z| > Z_OPEN. Sign of new entry = -sign(z) (mean-reverting).
        if len(entries) < MAX_ENTRIES and abs(z) > Z_OPEN:
            if z > Z_OPEN:
                # Mid above fair -> sell.
                room = POSITION_LIMIT + pos
                qty = min(ENTRY_SIZE, room, depth.buy_orders.get(best_bid, 0))
                if qty > 0:
                    orders.append(Order(PRODUCT, best_bid, -qty))
                    entries.append({"sign": -1, "tick": tick})
            elif z < -Z_OPEN:
                # Mid below fair -> buy.
                room = POSITION_LIMIT - pos
                qty = min(ENTRY_SIZE, room, -depth.sell_orders.get(best_ask, 0))
                if qty > 0:
                    orders.append(Order(PRODUCT, best_ask, qty))
                    entries.append({"sign": +1, "tick": tick})

        result[PRODUCT] = orders
        saved["ema_fv"] = ema
        saved["dev_buf"] = dev_buf
        saved["entries"] = entries
        return result, 0, json.dumps(saved)
