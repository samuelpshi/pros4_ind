# Agent 7b Fix Summary — IPR Order Aggregation Bug

**Author:** Agent 7b (IPR Order Aggregation Fix), Pass 4 patch
**Date:** 2026-04-16
**Files modified:** `Round 1/traders/trader-v9-r1.py`, `trader-v9-r1-jmerle.py`, `trader-v9-r1-aco-only.py`, `trader-v9-r1-ipr-only.py`, `Round 1/strategies/IMPLEMENTATION_NOTES.md`

---

## Bug Description and Fix Mechanism

Agent 7's implementation of `ipr_orders()` submitted multiple buy orders in a single tick whose combined quantity exceeded the per-tick buy budget (`limit - current_position`). Specifically: STEP 1 posted a passive bid for the full remaining room (`limit - pos`, up to 80 units when starting from 0), and STEP 3 unconditionally appended a refill bid for up to `IPR_REFILL_MAX_SIZE = 10` additional units. When both fired together, the combined submission was up to 90 units against an 80-unit budget, causing the engine to reject the entire IPR order set for that tick with "exceeded limit of 80 set." This rejection happened on every tick until the market price happened to move down to the passive bid level on its own — a delay of 350,900–86,300 ms across days -2/−1/0 respectively, forfeiting 27,701/11,376/6,564 XIRECS of drift income per day (total: −45,641 XIRECS vs v8 over 3 days). The delay magnitude matched the drift-missed formula to within 0.5% on all 3 days, confirming pure delayed-entry causation.

The fix introduces two helpers, `_capped_buy()` and `_capped_sell()`, that compute the remaining per-tick budget (accounting for all orders already in the list for that tick) before appending. Every `orders.append(Order(...))` call in the IPR order-placement path was replaced with the appropriate capped helper. This makes per-tick budget overrun structurally impossible: no code path in `ipr_orders()` can reach a raw `append(Order(...))` for a buy or sell without going through a helper that enforces the budget.

---

## ACO Audit Finding

**ACO is CLEAN — no capped helpers needed.**

The ACO take→clear→make pipeline threads `pos` sequentially through each layer: `aco_take()` returns `pos2`, `aco_clear()` takes `pos2` and returns `pos3`, `aco_make()` uses `pos3` to compute `buy_qty = limit - pos3` (remaining buy capacity after take+clear) and `sell_qty = limit + pos3`. By construction: total submitted buys = `(pos3 - pos) + (limit - pos3) = limit - pos` — exactly the per-tick buy budget. Same argument for sells. No overrun is structurally possible. Citations: `aco_take()` line 251, `aco_clear()` line 279, `aco_make()` line 306, integration pipeline at lines 596–599 of `trader-v9-r1.py`.

Note: ACO does hit ±80 on all 3 days (Agent 8 Diagnostic 3), but this is due to insufficient inventory penalty (`ACO_INVENTORY_PENALTY = 0.025`), not an order-aggregation bug. That is a Pass 5 parameter-sweep issue, not a structural fix.

---

## Append-Sites Replaced with Capped Helpers

All 4 trader variant files received identical changes. Line numbers below refer to `trader-v9-r1.py` after the patch.

| Original raw append | Replaced with | Location in patched file |
|---|---|---|
| `orders.append(Order(symbol, passive_bid_px, room))` (passive entry bid, STEP 1) | `_capped_buy(orders, symbol, passive_bid_px, room, pos, limit)` | `ipr_orders()` line 465 |
| `greedy_orders.append(Order(symbol, ap, qty))` (greedy fallback loop, STEP 1) | `_capped_buy(greedy_orders, symbol, ap, qty_available, pos, limit)` | `ipr_orders()` line 482 |
| `orders.append(Order(symbol, skim_px, -skim_size))` (skim ask, STEP 2) | `_capped_sell(orders, symbol, skim_px, skim_size, pos, limit)` | `ipr_orders()` line 509 |
| `orders.append(Order(symbol, refill_px, refill_size))` (refill bid, STEP 3) | `_capped_buy(orders, symbol, refill_px, refill_size, pos, limit)` | `ipr_orders()` line 517 |

Total: **4 raw append-sites replaced** across the IPR path. Zero raw `append(Order(...))` calls remain in `ipr_orders()`.

---

## Structural Invariant Confirmations

- **Long-only guard** (`if skim_size > 0 and (pos - skim_size) >= IPR_LONG_ONLY_FLOOR:` at line 507) is **NOT modified**. `_capped_sell` runs only when the guard passes — the guard decides whether to sell at all; `_capped_sell` enforces the per-tick budget if a sell is allowed. Guard logic and ordering preserved exactly.
- **Circuit breaker logic** (`ipr_circuit_triggered()` at line 387, `circuit_frozen = ipr_circuit_triggered(...)` at line 652) is **NOT modified**. Parameters `IPR_CIRCUIT_W=500`, `IPR_CIRCUIT_K=5.0`, `IPR_CIRCUIT_ABS_FLOOR=50.0` unchanged.
- **ACTIVE_PRODUCTS gating** (`ACTIVE_PRODUCTS = {...}` at line 27, enforcement at line 555) is **NOT modified** in any of the 4 files. Only ACTIVE_PRODUCTS value differs between variants, as before.
- **No parameter values changed.** `ACO_REVERSION_BETA=-0.45`, `ACO_INVENTORY_PENALTY=0.025`, and all IPR parameters are byte-identical to pre-patch values.
