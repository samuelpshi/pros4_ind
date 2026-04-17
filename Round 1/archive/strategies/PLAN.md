# Round 1 Strategy Plan

**Version:** Pass 3 — Code-Ready Strategy Plan
**Date:** 2026-04-16
**Author:** Prep Pass 3 (Strategy Synthesizer)
**Status:** Final — ready for Pass 4 implementation

---

## Sources

| # | File | Role |
|---|------|------|
| 1 | `Round 1/docs/ipr_mm_synthesis.md` | BINDING IPR design constraint — asymmetric quoting, long-only floor, MM as entry/skim refinement |
| 2 | `Round 1/analysis/r1_eda_summary.md` | Pass 2 findings: archetypes, p-values, half-lives, 7 still-open questions |
| 3 | `Round 1/analysis/r1_eda.ipynb` | Numeric source of record for EDA outputs (12 cells, 12 plots) |
| 4 | `Round 1/docs/r1_product_mechanics.md` | Position limits, tick size, engine rules, 11 open questions |
| 5 | `Round 1/docs/imc3_r1_playbook.md` | KELP entry parameters, strategy-family citation source |
| 6 | `Round 1/analysis/pepper_root_findings.md` | Drift, slippage, Config A commitment, Note 1 (deep bid dead code), Note 2 (reversal risk) |
| 7 | `Round 1/traders/trader-v8-173159.py` | Active trader — Trader.run() signature, Config A parameters, helper methods, traderData encoding |
| 8 | `Round 1/analysis/backtest.py` | PnL marking convention, scenario setup, reversal event tracking |

---

## ACO — New Strategy (KELP-Analog Market Making)

### (a) Thesis

ASH_COATED_OSMIUM is a mean-reverting product with two confirmed and statistically distinct timescales:

**Fast timescale (primary):** ADF stationarity confirmed within each day (p=0.0048, 0.0000, 0.0147 for days -2, -1, 0; all < 0.05). OU half-life = **8.4 timesteps** estimated from AR(1) regression (beta = -0.0790). Return autocorrelation at lag-1 = **-0.494** (95% CI ±0.0118). This is not noise — the magnitude exactly matches the range that bid-ask bounce market making exploits. Each tick, approximately half the displacement reverts within 8 ticks. Variance ratio VR(2)=0.506, VR(4)=0.272, VR(8)=0.149, VR(16)=0.089 — all far below 1 at every horizon, confirming mean reversion persists across scales.

**Slow timescale (secondary):** Level autocorrelation turns negative at lag ~1000 timesteps (r=-0.123) and is most negative at lag ~2000 timesteps (r=-0.340). This is a bounded oscillation with half-period approximately 1000-2000 timesteps — the "hidden pattern" referenced in the Trading-groundwork lore hint (r1_product_mechanics.md §ACO Fair-Value Anchors). The ACO intraday range is 27-36 XIRECS; the oscillation is contained within this range. No consistent intraday drift direction across the 3 days (-6.5, +10, +4 XIRECS total drift per day), confirming there is no trend — only the oscillation.

Trade-sign flow has no predictive value for next-tick returns (r=-0.002, p=0.906) — safe to make passively without adverse-selection concern. No named counterparties (Olivia signal absent). Order book is effectively 1-2 levels deep (L1=100%, L2=68%, L3=2.6% — negligible).

**ACO archetype:** KELP-analog mean-reverting market maker. Cite: imc3_r1_playbook.md §2 KELP, "Mean-reverting microstructure-driven market-making."

### (b) Strategy Family

**KELP** strategy family from imc3_r1_playbook.md: filtered mmbot mid + mean-reversion fair-value adjustment + standard take/clear/make execution stack. This is the directly named playbook entry for this archetype.

The core formula (imc3_r1_playbook.md §2 Fair Value Formula Summary):
```
mmbot_mid   = (min(filtered_asks) + max(filtered_bids)) / 2
               where filtered = orders with |volume| >= adverse_volume
last_return = (mmbot_mid - prev_mmbot_mid) / prev_mmbot_mid
fair_value  = mmbot_mid + mmbot_mid * last_return * reversion_beta
```

The execution stack (imc3_r1_playbook.md §4B Standard Execution Stack):
1. **Take**: hit ask if ask <= fv - take_width; hit bid if bid >= fv + take_width
2. **Clear**: reduce inventory when price returns to fair (zero-EV or near-zero-EV trades)
3. **Make**: post passive quotes around fair value with inventory skew

The existing ACO code in `trader-v8-173159.py` uses EMA-based fair value (`alpha=0.12`, `quote_offset=2`, `take_edge=3`) — this is a simpler approximation of the same concept. The new strategy replaces the EMA fair value with the KELP-style mmbot mid + reversion-beta formula, which has more empirical grounding for ACO specifically.

### (c) Timescale Decision

**Decision: Trade the fast timescale only (8.4-tick OU mean reversion). Use the slow timescale (1000-2000 ts oscillation) as a passive sizing bias — not a separate signal stream.**

Justification:

The fast signal is the primary edge. An OU half-life of 8.4 timesteps means that after any 1-tick displacement, the expected reversal happens within seconds of wall time. This is the same microstructure mechanism that makes KELP market making profitable — capturing the bid-ask bounce repeatedly throughout the day. The lag-1 return autocorrelation of -0.494 gives a per-fill edge of roughly 0.5 ticks per trade (captured as spread income).

The slow oscillation is real (lag-2000 autocorr = -0.340, statistically significant) but is too slow to trade as a primary signal for three reasons: (1) We have only 3 days of data — the oscillation period of 1000-2000 timestamps might shift between days, making a dedicated signal generator overfit. (2) A position held for 1000+ timesteps to ride the oscillation ties up the entire 80-unit position limit, eliminating the fast MM edge during that holding period. (3) The slow oscillation's amplitude (roughly the 27-36 XIREC intraday range) cannot be captured without going to the position limit at both extremes, which requires a directional flip — a riskier operation than symmetric MM.

The correct incorporation of the slow signal is as a **sizing bias on the make layer**: when the rolling 500-tick mid is in the top 20% of its range, reduce passive bid size (don't add to a likely-to-fall position) and optionally post a slightly tighter ask; when in the bottom 20%, reduce passive ask size (don't short a likely-to-rise position). This costs nothing to implement, adds no latency, and doesn't require holding a directional position for 1000 timesteps. If the slow signal misfires on the live submission day, the impact is reduced fill rate on one side — not a position unwind.

This avoids the "two separate signal streams" approach (complexity risk, conflicting signals, requires more calibration data than 3 days) and the "slow bias on fast sizing" version is strictly better than ignoring the slow signal entirely.

### (d) Fair Value Formula — Committed Window

**Formula:**
```
mmbot_mid(t) = (min(filtered_asks(t)) + max(filtered_bids(t))) / 2
               filtered: keep only orders where |volume| >= adverse_volume (= 15)
               fallback: if no filtered orders on either side, use prev_mmbot_mid

last_mmlog_ret = log(mmbot_mid(t)) - log(mmbot_mid(t-1))
                  (log-return of mmbot mid, not raw mid)

fair_value(t) = mmbot_mid(t) * exp(last_mmlog_ret * reversion_beta)
              = mmbot_mid(t) + mmbot_mid(t) * last_mmlog_ret * reversion_beta
                (linearized; difference is negligible at these price scales)
```

**Committed parameters:**
- `adverse_volume = 15` — KELP playbook default (imc3_r1_playbook.md §2 PARAMS line 2207). ACO L1 is always quoted (100% coverage), so this filter will find large orders in every timestep under normal conditions.
- `reversion_beta = -0.45` — midpoint of the EDA-recommended range (-0.40 to -0.50). The empirical lag-1 return autocorrelation of -0.494 implies that the optimal reversion adjustment absorbs roughly 45% of the last tick's displacement. Sweep range: -0.25 to -0.55 in steps of 0.05.
- **No explicit window length** is needed: unlike an EMA or SMA, this formula uses only the current timestep's mmbot mid and the previous timestep's mmbot mid. The "window" is 1 lag, stored in `traderData` as a single float. This is consistent with the KELP playbook formula and with how the existing trader persists EMA state via `jsonpickle.encode(saved)`.

**Slow-timescale bias (make-layer only):**
```
trailing_range_window = 500 timesteps  (stored as a deque of 500 mmbot mids in traderData)
pos_in_range = (mmbot_mid(t) - min(trailing_500)) / (max(trailing_500) - min(trailing_500))
               (clamped to [0, 1])
range_bias   = 0           if 0.2 <= pos_in_range <= 0.8  (neutral zone)
             = +1          if pos_in_range > 0.8           (near top of range: expect down)
             = -1          if pos_in_range < 0.2           (near bottom: expect up)
```
When `range_bias = +1`: multiply passive bid size by 0.5 (fewer longs near top). When `range_bias = -1`: multiply passive ask size by 0.5 (fewer shorts near bottom). This is the only place the slow signal enters.

**traderData size check:** Storing 500 floats for ACO (each 8 bytes) + 500 floats for IPR (drift tracking) + EMA state = ~12 KB, well within the 50,000-character jsonpickle limit (r1_product_mechanics.md §State Persistence).

### (e) Pseudocode

Compatible with `Trader.run(state: TradingState)` as implemented in `trader-v8-173159.py`. The trader returns `(result, conversions, traderData)` where `result` is `Dict[str, List[Order]]`, `conversions = 0` (no conversion used), and `traderData = jsonpickle.encode(saved)`.

```python
# ---- ACO constants (replace ACO_CFG in trader-v8-173159.py) ----
ACO_CFG_V2 = {
    "adverse_volume":      15,       # mmbot mid filter threshold (KELP default)
    "reversion_beta":     -0.45,     # mean-reversion adjustment (empirical lag-1 autocorr)
    "take_width":          1.5,      # take if ask <= fv - 1.5 or bid >= fv + 1.5 (KELP default)
    "clear_width":         0.0,      # no separate clearing band (KELP default)
    "deflection_thr":      2.0,      # halt quoting on side where fv moved > 2.0 ticks (tunable)
    "default_edge":        1,        # passive quote offset from fair value (KELP default_edge)
    "inv_skew_per_unit":   0.025,    # shift fair value by this per unit of inventory (KELP retreat_per_lot=0.012 → scale to ACO)
    "range_window":        500,      # timesteps for slow-oscillation range bias
    "range_bias_threshold": 0.20,    # top/bottom 20% of range triggers bias
    "range_bias_factor":   0.50,     # halve passive size on biased side
    "position_limit":      80,       # r1_product_mechanics.md §ACO Position Limit
}

# ---- ACO fair value computation ----
def aco_mmbot_mid(depth, adverse_vol, prev_mmbot_mid):
    """
    Filter order book for large-volume orders and compute midpoint.
    Fallback to prev_mmbot_mid if filtered book is empty on either side.
    """
    filtered_bids = [p for p, q in depth.buy_orders.items()  if q  >=  adverse_vol]
    filtered_asks = [p for p, q in depth.sell_orders.items() if abs(q) >= adverse_vol]
    if not filtered_bids or not filtered_asks:
        return prev_mmbot_mid  # fallback: previous value
    return (max(filtered_bids) + min(filtered_asks)) / 2.0

def aco_fair_value(mmbot_mid, prev_mmbot_mid, reversion_beta):
    """
    Apply mean-reversion adjustment: fv = mmbot_mid + mmbot_mid * last_return * beta.
    beta is negative, so a positive last_return (price rose) pulls fv down.
    """
    if prev_mmbot_mid <= 0:
        return mmbot_mid
    last_return = (mmbot_mid - prev_mmbot_mid) / prev_mmbot_mid
    return mmbot_mid + mmbot_mid * last_return * reversion_beta

# ---- Slow-oscillation range bias (compute once per tick) ----
def aco_range_bias(mmbot_mid, trailing_mids, cfg):
    """
    Returns +1 (near top → reduce bids), -1 (near bottom → reduce asks), 0 (neutral).
    trailing_mids: deque of up to range_window recent mmbot mids.
    """
    if len(trailing_mids) < 50:  # need minimum history
        return 0
    lo, hi = min(trailing_mids), max(trailing_mids)
    if hi == lo:
        return 0
    pos_in_range = (mmbot_mid - lo) / (hi - lo)
    thr = cfg["range_bias_threshold"]
    if pos_in_range > (1 - thr): return +1
    if pos_in_range < thr:       return -1
    return 0

# ---- ACO take layer ----
def aco_take_v2(symbol, depth, fv, pos, limit, take_width):
    """
    Take orders where: ask <= fv - take_width (buy) or bid >= fv + take_width (sell).
    Returns (orders, updated_pos).
    """
    orders = []
    for ap in sorted(depth.sell_orders):
        if ap > fv - take_width: break
        room = limit - pos
        if room <= 0: break
        qty = min(-depth.sell_orders[ap], room)
        orders.append(Order(symbol, ap, qty)); pos += qty
    for bp in sorted(depth.buy_orders, reverse=True):
        if bp < fv + take_width: break
        room = limit + pos
        if room <= 0: break
        qty = min(depth.buy_orders[bp], room)
        orders.append(Order(symbol, bp, -qty)); pos -= qty
    return orders, pos

# ---- ACO clear layer ----
def aco_clear_v2(symbol, depth, fv, pos, limit, clear_width):
    """
    Zero-EV inventory clearing: sell near fv if long, buy near fv if short.
    With clear_width=0, only executes at exactly fv.
    """
    orders = []
    if pos > 0:  # long: look for bids at fv - clear_width or better
        for bp in sorted(depth.buy_orders, reverse=True):
            if bp < fv - clear_width: break
            qty = min(depth.buy_orders[bp], pos)
            if qty > 0:
                orders.append(Order(symbol, bp, -qty)); pos -= qty
    elif pos < 0:  # short: look for asks at fv + clear_width or below
        for ap in sorted(depth.sell_orders):
            if ap > fv + clear_width: break
            qty = min(-depth.sell_orders[ap], -pos)
            if qty > 0:
                orders.append(Order(symbol, ap, qty)); pos += qty
    return orders, pos

# ---- ACO make layer ----
def aco_make_v2(symbol, fv, pos, limit, cfg, range_bias, deflected_side, urgency):
    """
    Post passive quotes around inventory-skewed fair value.
    deflected_side: 'bid', 'ask', or None — side that had a sharp move; don't quote it.
    range_bias: +1 reduce bids, -1 reduce asks, 0 neutral.
    """
    # Inventory skew: shift fair value to encourage unwinding
    skew = pos * cfg["inv_skew_per_unit"]
    skewed_fv = fv - skew  # long position → pull fv down → bid lower, ask lower

    edge = cfg["default_edge"]
    bid_px = math.floor(skewed_fv) - edge
    ask_px = math.ceil(skewed_fv) + edge

    # Ensure quotes don't cross
    if ask_px <= bid_px: ask_px = bid_px + 1

    # Compute base sizes
    buy_qty  = limit - pos   # remaining long capacity
    sell_qty = limit + pos   # remaining short capacity

    # Apply slow-oscillation range bias (halve size on biased side)
    if range_bias == +1:   # near top of range: likely to fall → reduce bids
        buy_qty = int(buy_qty * cfg["range_bias_factor"])
    elif range_bias == -1:  # near bottom: likely to rise → reduce asks
        sell_qty = int(sell_qty * cfg["range_bias_factor"])

    # Deflection: don't quote on deflected side
    orders = []
    if deflected_side != 'bid' and buy_qty > 0 and bid_px > 0:
        orders.append(Order(symbol, bid_px, buy_qty))
    if deflected_side != 'ask' and sell_qty > 0 and ask_px > 0:
        orders.append(Order(symbol, ask_px, -sell_qty))
    return orders

# ---- ACO kill switch ----
def aco_kill_switch(pos, limit, fv_change, deflection_thr):
    """
    Returns ('bid', 'ask', or None) indicating which make side to suppress.
    A sharp up-move → don't post more bids (avoid filling into a rising market).
    A sharp down-move → don't post more asks.
    fv_change = fv(t) - fv(t-1).
    """
    if fv_change > deflection_thr:
        return 'ask'   # price moved up sharply: don't add asks (price may keep rising)
    if fv_change < -deflection_thr:
        return 'bid'   # price moved down sharply: don't add bids
    return None

# ---- Integration into Trader.run() for ACO ----
# Inside the existing for-loop over state.order_depths:
# Replace the current "if symbol == 'ASH_COATED_OSMIUM'" block:

# Load state (from saved dict via jsonpickle):
prev_mmbot = saved.get("aco_mmbot", {}).get(symbol, None)
prev_fv    = saved.get("aco_fv", {}).get(symbol, None)
trailing_mids_list = saved.get("aco_trailing", {}).get(symbol, [])
trailing_mids = collections.deque(trailing_mids_list, maxlen=ACO_CFG_V2["range_window"])

# Compute mmbot mid
mmb = aco_mmbot_mid(depth, ACO_CFG_V2["adverse_volume"], prev_mmbot or vwap_mid(depth))

# Compute fair value (needs at least 1 prior mmbot_mid)
if prev_mmbot is None:
    fv = mmb  # first tick: no reversion adjustment yet
else:
    fv = aco_fair_value(mmb, prev_mmbot, ACO_CFG_V2["reversion_beta"])

# Deflection
fv_change = fv - (prev_fv or fv)
deflected_side = aco_kill_switch(pos, limit, fv_change, ACO_CFG_V2["deflection_thr"])

# Range bias
trailing_mids.append(mmb)
range_bias = aco_range_bias(mmb, trailing_mids, ACO_CFG_V2)

# Execute stack: take → clear → make
take_ords, pos2 = aco_take_v2(symbol, depth, fv, pos, limit, ACO_CFG_V2["take_width"])
clear_ords, pos3 = aco_clear_v2(symbol, depth, fv, pos2, limit, ACO_CFG_V2["clear_width"])
make_ords = aco_make_v2(symbol, fv, pos3, limit, ACO_CFG_V2, range_bias, deflected_side, urgency)
result[symbol] = take_ords + clear_ords + make_ords

# Save state
saved.setdefault("aco_mmbot", {})[symbol] = mmb
saved.setdefault("aco_fv", {})[symbol] = fv
saved.setdefault("aco_trailing", {})[symbol] = list(trailing_mids)
```

**Design notes for implementer:**
- `collections.deque` with `maxlen=500` handles the sliding window automatically; convert to `list` before jsonpickle encoding, back to `deque` after decoding.
- The existing `eod_urgency()` helper is retained; pass `urgency` to `aco_make_v2` and use it to tighten quotes near EOD (same logic as existing `aco_make`).
- The existing `vwap_mid()` helper is retained as the fallback for the first timestep before mmbot_mid history exists.
- `traderData` state keys are namespaced (`aco_mmbot`, `aco_fv`, `aco_trailing`) to avoid collision with existing IPR state keys (`ema_fast`, `ema_slow`).

### (f) Parameter Sweep Ranges

All starting values are derived from EDA findings or playbook entries. Sweep order is priority-ranked; sweep one parameter at a time, holding others at starting value.

| Parameter | Starting Value | Sweep Range | Step | Priority | Source |
|-----------|---------------|-------------|------|----------|--------|
| `reversion_beta` | -0.45 | -0.25 to -0.55 | 0.05 | 1st | EDA lag-1 autocorr = -0.494 |
| `take_width` | 1.5 | 1.0 to 3.0 | 0.5 | 2nd | KELP default 1.5; ACO tick vol = 1.9 |
| `adverse_volume` | 15 | 10 to 25 | 5 | 3rd | KELP default 15; test 20 as alt |
| `deflection_thr` | 2.0 | 0.5 to 4.0 | 0.5 | 4th | KELP used 0.5 (flagged as needing tuning); ACO range is 27-36 so 2.0 is a reasonable first cut |
| `inv_skew_per_unit` | 0.025 | 0.005 to 0.050 | 0.005 | 5th | KELP retreat_per_lot=0.012; scaled to ACO |
| `range_bias_threshold` | 0.20 | 0.10 to 0.30 | 0.05 | 6th | Exploratory — no strong prior |
| `range_bias_factor` | 0.50 | 0.25 to 0.75 | 0.25 | 7th | Exploratory — only if range bias shows value |

**Sweep stopping criterion:** accept a parameter value if mean PnL across all 3 days improves and standard deviation does not increase by more than 20% of the improvement in mean. Do not optimize against a single day.

### (g) Risk Controls

**Position limit:** 80 (absolute, both sides). Source: r1_product_mechanics.md §ASH_COATED_OSMIUM Position Limit. Engine enforces at submission time — if total buy orders would push position past +80, the entire buy side is rejected (r1_product_mechanics.md §Position Limit Enforcement). The make-layer correctly computes `buy_qty = limit - pos` and `sell_qty = limit + pos` to avoid crossing the limit.

**Inventory penalty formula:** Encoded in the inventory skew on `skewed_fv`. With `inv_skew_per_unit = 0.025`, a position of +80 shifts fair value down by 2.0 XIRECS, making the passive bid 2 XIRECS less attractive and the passive ask 2 XIRECS more aggressive. This is a soft penalty (changes quote aggressiveness) rather than a hard stop.

**Deflection kill switch:** When `|fv_change| > deflection_thr (=2.0)`, suppress passive quoting on the side in the direction of the move. This prevents adding to a position that has just moved sharply against us — the primary adverse-selection protection for ACO. Suppression lasts exactly one timestep (kill switch is recomputed each tick). Source: KELP playbook deflection mechanism (imc3_r1_playbook.md §2 Edge Cases).

**Hard inventory stop (not in current v8):** If position reaches ±80 (the limit), the make layer's `buy_qty` or `sell_qty` naturally reaches 0, preventing further accumulation. No separate kill switch needed for the make layer. The take layer will still take profitable opportunities on the unwinding side.

**Position limit saturation recovery:** The clear layer with `clear_width=0` handles zero-EV unwinds at fair value when stuck near the limit. With inventory skew, quotes naturally shift to encourage unwinding before saturation.

### (h) PnL Marking Convention

**Convention chosen: mark-to-mid at end of day.** This resolves open question ACO-5.

**What backtest.py currently does:** Inspecting `backtest.py` lines 239-247:
```python
# End of day: mark to market
# Get last valid mid for each product
last_ts_rows = grouped.get_group(timestamps[-1])
for _, row in last_ts_rows.iterrows():
    product = row['product']
    last_mid = row['mid_price']
    pos = position.get(product, 0)
    mtm = cash.get(product, 0) + pos * last_mid
```
The docstring at the top of `backtest.py` also states explicitly: "At end of day, mark to mid-price (last valid mid)." The convention is **mark-to-mid**. Cash is accumulated from fills (exact execution prices) and the residual position is marked at the last available mid-price column from the CSV.

**Keeping or changing:** Keep as-is. Mark-to-mid is the standard convention for backtesting intraday strategies when the true fair value is unknown. The `profit_and_loss` column in the prices CSV is not used in the backtester — it records IMC's internal PnL tracking, which may use a different formula (open question ACO-5). The conservative approach is to use mid-price marking in local backtest and accept that there may be a small discrepancy vs IMC's website score. This discrepancy is acceptable given that the website backtest is explicitly deprioritized in CLAUDE.md Hard Rule 4.

**No backtest changes required** for this convention. The mark-to-mid convention is already implemented and documented in `backtest.py`.

---

## IPR — Refinement of Config A

Config A (target_long=80, entry fills in 2-4 timesteps by ts≈400, mean PnL +79,351/day) is committed. This section proposes five targeted deltas on top of Config A. No delta below replaces Config A; each is a marginal improvement or risk control.

**Pre-check: ipr_mm_synthesis.md re-read confirmed before writing this section.**

The synthesis document is the binding constraint for all IPR design. Its conclusions, paraphrased:
- MM is compatible with IPR's microstructure (same lag-1 bounce structure as ACO) but only works as entry refinement and skim enhancement on top of the drift thesis — not as a standalone strategy.
- Inventory risk is asymmetric: going long is free (drift works for you), going short is bleeding (drift works against you). A symmetric MM would be catastrophic.
- Long-only floor must be hard-coded at the code level.
- The drift-dependence of MM entry and skim is identical to Config A's drift-dependence — not an independent source of edge.

### (a) Entry Refinement via Asymmetric MM

**Current behavior (v9):** Aggressive greedy take of 80 units at day start. All 80 units filled by ts≈400 at VWAP ~9.4/unit above mid. Mean slippage cost: 80 × 9.4 = 752 XIRECS/day.

**Delta:** Post passive bids at `fv(t) - spread/2` during accumulation phase instead of crossing the spread. This captures the bid-ask bounce on the entry itself — buying at the bid instead of the ask saves 1 spread width (~2-4 XIRECS per unit) per fill.

**fv(t) formula for passive entry bids:**
```
drift_per_tick = 1001.3 / 10000 = 0.10013 XIRECS/tick
fv(t)          = price_at_day_start + drift_per_tick * (t / 100)
                (t is the timestamp; divide by 100 because timestamps step in increments of 100)
```
Source: drift = +1001.3/day (pepper_root_findings.md §Finding 1), uniform across all 4 intraday quartiles (r1_eda_summary.md §IPR, intraday quartile drift Q1=0.1096, Q2=0.1088, Q3=0.1077, Q4=0.1092 XIRECS/tick for day -2 — uniformly ~0.109/tick).

**Drift estimate source:** Hardcode `drift_per_tick = 0.10013` (= 1001.3 / 10000). The three observed day-drifts span only 3.5 XIRECS total (1003.0, 999.5, 1001.5), introducing a maximum per-tick error of ~0.00015 — negligible relative to spread width. No per-day calibration needed.

**Refresh cadence:** Recompute `fv(t)` every timestep (O(1), no history). Store `price_at_day_start` in `traderData` (set on first timestep with a two-sided book; frozen until the next day).

**Implementation:** Replace Step 1 aggressive take with passive bids at `fv(t) - spread/2` during accumulation. Add greedy-take fallback after N=20 timesteps without a fill. Once pos=80, bid side is dead — consistent with synthesis doc and existing `if pos < target_long` guard in v9.

**Expected improvement:** ~160 XIRECS/day (80 units × ~2 XIRECS/unit spread saving). Small (~0.2% of drift PnL) but strictly positive. Greedy fallback ensures full position is reached even on spike-down days.

### (b) Skim Refinement

**Current behavior (v9):** `skim_size=5`, `skim_min_pos=75`, `skim_offset=2` (post sell at best_ask + 2). Estimated 8-12 round-trips/day, 0 actually observed in 3-day backtest (pepper_root_findings.md §Session 2). Reason: skim_offset=2 may be too far above market for bots to hit.

**Delta:** Tighten skim offset from +2 to +1 (post at best_ask + 1 instead of best_ask + 2). Increase skim_size from 5 to 8 once position is pinned at 80. Keep `skim_min_pos=75` (unchanged — already correct per pepper_root_findings.md §Note 1).

**New skim parameters:**
```
skim_offset   = 1      (tighter: 1 tick above best_ask vs. 2 ticks)
skim_size     = 8      (larger: 8 units vs. 5)
skim_min_pos  = 75     (unchanged)
refill_offset = 1      (unchanged: buy at best_bid + 1 to refill)
refill_max_size = 10   (unchanged: exceeds new skim_size, so refill is never the bottleneck)
```

**Justification — tighter offset:** Synthesis doc: post at `fv(t) + spread/2`. With spread ~2 ticks, offset=1 places the skim quote at fv + 1 tick, which is inside a natural spike range. Offset=2 was one full spread-width above ask — too far for bots to sweep. Offset=1 gives bots a reason to hit.

**Justification — larger size:** Synthesis doc: "make [skim] more aggressive: larger skim size, tighter triggers, as long as you can refill before EOD." At drift +1001.3/day, an 8-unit skim refills within ~80 timesteps via drift alone. refill_max_size=10 is already larger, so refill is never the bottleneck.

**Risk:** More fills on microstructure moves rather than genuine spikes. Net cost per premature fill ≈ 0 (sell ask+1, rebuy bid+1 = break-even at the spread). Acceptable — worst case is a wash, upside is skim income on genuine bot sweeps.

### (c) Long-Only Floor (Hard Code-Level Constraint)

**Requirement from ipr_mm_synthesis.md:** "Never quote an ask that could take position net short." This is a hard code-level constraint, not a soft parameter.

**Implementation:** Add a guard in `ipr_orders()` before appending any sell order:
```python
# HARD CONSTRAINT: Never quote an ask that could result in net short position.
# This is non-negotiable per ipr_mm_synthesis.md.
# Sell orders (skim) are only posted when they would reduce from a long to flat or smaller long,
# never from flat to short.
if skim_size > 0 and pos - skim_size >= 0:
    orders.append(Order(symbol, skim_px, -skim_size))
# If pos - skim_size < 0, do not post the skim.
```

v9 already partially implements this via `skim_size = min(cfg["skim_size"], room_long_sell)`. The additional action: **remove** the symmetric short-skim block (trader-v8-173159.py lines 243-249). That block posts buy orders when `target < 0`, which can never fire in Config A and is confusing dead code. Deleting it makes the long-only policy unambiguous.

Code comment to add:
```python
# IPR LONG-ONLY POLICY (per ipr_mm_synthesis.md):
# Drift works against short positions every tick. All sells reduce an existing long — never cross zero.
```

### (d) Drift-Reversal Circuit Breaker

**Risk addressed (IPR-5):** Zero reversals in 3 days, but absence of evidence is not evidence of absence. The current EMA-gap thresholds (< -8 / < -15) can false-trigger on normal drift noise given α_fast=0.05, α_slow=0.005, causing a catastrophic 160-unit unwind (pepper_root_findings.md §Note 2). Replace entirely with a realized-drift test.

**Circuit breaker specification:**

Trigger: realized drift over a trailing window W deviates from +1001.3/day by more than k standard deviations.

```
Observed drift formula:
  realized_drift_W(t) = (mid(t) - mid(t - W)) / W * 10000
                       (units: XIRECS per 10000-tick day, normalized to compare with prior)

Trigger condition:
  if realized_drift_W(t) < +1001.3 - k * std_drift - abs_floor:
      circuit_breaker = TRIGGERED
  else:
      circuit_breaker = NORMAL

Parameters:
  W = 500 timesteps  (5% of a day; large enough to distinguish noise from trend change)
  k = 5.0            (5 standard deviations below prior drift mean)
  std_drift = 1.8 XIRECS/day (from pepper_root_findings.md §Finding 1; per-day std)
  abs_floor = 50 XIRECS/day  (absolute safety margin; see cost analysis below)
```

**W and k justification:**

Tick volatility σ_tick ≈ 1.8 XIRECS (r1_eda_summary.md §IPR Regime Table). Over W=500 ticks, the standard deviation of the realized-drift estimate is σ_tick × √500 / 500 × 10000 ≈ 806 XIRECS/day. With k=5, the trigger fires when realized drift falls 5 × 806 = 4030 XIRECS/day below the prior mean of +1001.3 — i.e., approximately -3029 XIRECS/day. That is a full reversal, not a slowdown. The abs_floor=50 XIRECS/day absorbs the 3.5-XIREC day-to-day variation in observed drift (days -2/-1/0: 1003.0, 999.5, 1001.5) without triggering.

**Cost of false alarm (worst case):** Circuit breaker at ts=500,000 with pos=80 stops further accumulation; drift continues. Cost = 80 units × 0.5 remaining day × 1001.3 ≈ 40,052 XIRECS foregone. However, a false trigger at W=500, k=5 requires the price to have fallen ~3029 XIRECS below the expected path, which itself causes ~240,000 XIREC mark-to-mid loss on the long. Freezing in that scenario is correct regardless.

**Circuit breaker action sequence:**
```
NORMAL:    target = cfg["target_long"] = 80  (unchanged Config A)
TRIGGERED: freeze target at 0 (stop adding, hold existing)
           do NOT flip to short (-80) — the 160-unit unwind is the failure mode we are eliminating
           re-evaluate every timestep; if realized_drift_W recovers above threshold, reset to NORMAL
```

**Replace existing EMA reversal detection entirely** (fast_ema - slow_ema gap < -8 / < -15). The EMA gap is uninformative for a drifting price — the EMA always lags and the gap widens on any noisy tick. Realized drift over W directly measures what matters: is the drift still positive?

**traderData:** Store a deque of 500 recent mid-prices in `saved["ipr_mid_history"]`. Realized drift = `(mid[-1] - mid[-500]) * 10000 / 500` when len >= 500; else use NORMAL.

### (e) Drift Thesis Dependency Note

All three deltas inherit the drift thesis — they are a better implementation of the same thesis, not an independent edge source (ipr_mm_synthesis.md §Bottom Line). Conditional on drift continuing: +160/day (entry) + ~150/day (skim) + 0 (circuit breaker). Conditional on reversal: only the circuit breaker matters.

### (f) Parameters to Sweep on Top of Config A

| Parameter | Current (v9) | New Starting Value | Sweep Range | Step | Priority |
|-----------|-------------|-------------------|-------------|------|----------|
| `skim_offset` | 2 | 1 | 1 to 3 | 1 | 1st |
| `skim_size` | 5 | 8 | 3 to 12 | 1 | 2nd |
| Circuit breaker W | N/A (EMA) | 500 | 200 to 1000 | 100 | 3rd |
| Circuit breaker k | N/A (EMA) | 5.0 | 3.0 to 8.0 | 0.5 | 4th |
| `passive_bid_fallback_N` | N/A (always greedy) | 20 | 5 to 50 | 5 | 5th |

---

## Shared Evaluation Plan

### Metrics (in priority order)

1. **Mean PnL across days -2, -1, 0** — primary metric. Report separately for ACO and IPR and combined.
2. **PnL standard deviation across days** — secondary. An improvement that increases PnL variance by more than 20% of the mean PnL gain is rejected without further justification.
3. **Max intraday drawdown** (largest peak-to-trough PnL drop within a day) — report per product per day.
4. **Fill rate** — for ACO: total fills per day; for IPR: skim fills per day (expected: 0 in v9 backtest; should increase with tighter skim_offset).
5. **Inventory path** — plot position vs. timestamp for each day. A healthy IPR path: goes from 0 to 80 in ts 0-400, then stays at 80 with small oscillations from skim/refill cycles. A healthy ACO path: oscillates symmetrically around 0 with occasional excursions, no sustained saturation at ±80.

### Scenarios

Run backtest.py across all three scenarios:

1. **Day -2 only** — baseline day
2. **Day -1 only** — confirms day -2 is not a lucky outlier
3. **Day 0 only** — confirms strategy holds on the most recent data
4. **Days -2/-1/0 concatenated** — treated as a single 30,000-timestep day (position does NOT reset between days; this matches the assumption that position resets to 0 at day start as implemented in backtest.py). Report concatenated total PnL.

**IPR additional scenario — drift-reversal stress test:**

Synthesize three simulated reversal scenarios by modifying the prices CSV mid-prices starting from the reversal point. For each of ts=25% / 50% / 75% of the day (timestamps 250,000 / 500,000 / 750,000):
- At the reversal point, flatten the mid-price drift to 0 (price stays constant at the level reached at the reversal timestamp).
- Run backtest with the circuit breaker active. Measure:
  - Does the circuit breaker trigger within W=500 timesteps of the reversal?
  - What is the final PnL vs. Config A without circuit breaker?
  - What is the position path after the reversal?
- Expected result: circuit breaker triggers ~500 timesteps after reversal, freezing position at whatever level it was at. Skim orders continue to run off the long position slowly if bots happen to sweep the ask. Net position at EOD should be < 80 units, reducing the mark-to-mid loss.

This stress test is run once before submission (not part of the parameter sweep). It validates the circuit breaker's activation timing and action.

### Success Criteria (numeric)

**ACO:**
- Baseline: current v9 ACO mean PnL = +2,206/day (from Session 2 backtest, WORKLOG.md §2026-04-16 Session 2).
- "Ship" threshold: mean ACO PnL >= +3,000/day across all 3 days with std < 2,000/day.
- "Iterate" threshold: mean ACO PnL < +3,000/day OR std >= 2,000/day.
- Note: a negative ACO PnL in any single day is a strong signal to re-examine the fair-value formula.

**IPR:**
- Baseline: Config A mean PnL = +79,351/day across 3 days (pepper_root_findings.md §Finding 4, Target=80 table).
- "Ship" threshold for refinements: mean IPR PnL >= +79,350/day (refinements must not regress the baseline). Any improvement above baseline is a bonus.
- "Iterate" threshold: mean IPR PnL < +79,000/day (more than 351/day regression means a refinement delta has hurt the core).
- For the circuit breaker specifically: on training data (no reversal), circuit breaker must NOT trigger on any of the 3 days. If it does, increase k or W.

**Combined:**
- "Ship" combined: total PnL across all 3 days >= 248,000 XIRECS (vs. current ~244,673; a ~1.4% improvement driven by ACO).
- The Round 1 pass/fail threshold is 200,000 XIRECS before day 3 (r1_product_mechanics.md §Round 1 Objective). Config A alone achieves ~238,000 from IPR over 3 days, already clearing this bar. The ACO and refinement work is upside, not the survival threshold.

---

## Open Questions Remaining

Source: r1_eda_summary.md §Section 4 Open Questions Status. Updated 2026-04-16 post-HTML re-read and user confirmation: **5 additional questions closed (ACO-1, ACO-3, IPR-2, IPR-3, IPR-6)**. Only **IPR-5** remains truly open.

| # | Question | Bucket | Resolution / Assumption |
|---|----------|--------|------------------------|
| ACO-1 | Is a ConversionObservation populated for ACO? | **Resolved by HTML re-read + user (2026-04-16)** | `R1_Trading groundwork.html` has zero mentions of "conversion"; user confirmed conversion is not a Round 1 mechanic (may appear in later rounds). Defensive runtime check: `state.observations.conversionObservations.get("ASH_COATED_OSMIUM") is None` expected. |
| ACO-3 | Are there bot-specific quoting rules for ACO? | **Resolved by user (2026-04-16)** | No product in any round has explicit bot-specific quoting rules published. Price/trade data = training set; live submission runs against analogous unseen bot behavior. Strategy correctly relies on the adverse-volume filter (volume ≥ 15) as its bot-identification proxy. No further action needed. |
| ACO-5 | Is PnL marked to mid or to IMC's internal fair value? | **Answered by this plan + user (2026-04-16)** | Mark-to-mid. Backtest.py uses mid-price marking explicitly; user concurs. IMC's internal marking may differ but this is not controllable from our side. Accept the potential discrepancy and use local backtest as primary. |
| IPR-2 | Does IPR carry position across days, or reset? | **Resolved by user (2026-04-16)** | Days are effectively continuous — treat as single connected data set for strategy design and backtesting. Price carries (empirical: day -2 ends at 11001.5, day -1 starts at 10998.5). Position-reset behavior consistent with v9 trader's implicit assumption (re-buys 80 at each day start) and IMC's standard per-day submission model. |
| IPR-3 | Is a ConversionObservation populated for IPR? | **Resolved by HTML re-read + user (2026-04-16)** | Same evidence as ACO-1. No conversion for IPR at this time. |
| IPR-5 | Does the drift ever reverse (harvest/maturity event)? | **Still open — HIGH RISK** | User confirmed: only 3 days of data, no additional context. Assume drift continues as the primary thesis; **build defensive infrastructure in case anything changes.** The drift-reversal circuit breaker (§IPR (d), W=500, k=5.0, freeze target at 0) is the primary risk mitigation and directly implements this requirement. If the circuit breaker triggers on live submission day, it is a strong signal that the drift thesis has failed. |
| IPR-6 | Can you go short IPR, and is there borrowing cost? | **Resolved by HTML re-read + user (2026-04-16) + this plan** | Neither HTML contains "borrow", "short sell", "shorting", "funding", "margin", "interest", or "carry"; user confirmed no known borrowing cost. Only engine constraint is `position ∈ [−80, +80]`. Strategically still avoided — long-only floor (§IPR (c)) hard-codes the policy under the drift thesis. Revisit only if IPR-5 confirms reversal. |

**Triage summary (post-user-confirmation 2026-04-16):**
- **Resolved by HTML re-read (3):** ACO-1, IPR-3, IPR-6
- **Answered by this plan (1):** ACO-5
- **Resolved by user (2):** ACO-3, IPR-2
- **Still open (1):** IPR-5 (drift reversal) — HIGH RISK, defensive infrastructure (circuit breaker §IPR (d)) is the committed mitigation.

---

*PLAN.md ends. Pass 4 begins with implementation of ACO (§e pseudocode → production code) followed by IPR deltas (§a–d), then full backtest sweep.*
