# Pepper Root Findings

## Finding 1: Daily Drift

| Day | First Mid | Last Mid | Drift   |
|-----|-----------|----------|---------|
| -2  | 9998.5    | 11001.5  | +1003.0 |
| -1  | 10998.5   | 11998.0  | +999.5  |
| 0   | 11998.5   | 13000.0  | +1001.5 |

- Mean drift: +1001.3/day
- Std drift: 1.8
- Verdict: **deterministic upward trend, not luck**. v8's directional thesis is correct.

## Finding 2: Flash Crashes (mid_price = 0)

- 54 rows across 3 days where entire order book is empty (all 6 levels NaN). IMC reports mid=0.0.
- 1,162 rows with bid missing only (mid defaults to ask_price_1).
- 1,096 rows with ask missing only (mid defaults to bid_price_1).
- Cleaning strategy: drop rows where either bid_price_1 or ask_price_1 is NaN. Removes 2,312 rows (7.7%).
- **Drift is unchanged after cleaning**: +1003.0, +999.5, +1001.5.
- These are not real flash crashes. They are timesteps where one or both sides of the book are empty (no market makers quoting). The trader already guards against this (line 274: `if not depth.buy_orders or not depth.sell_orders: continue`).

## Finding 3: Position Limit

- True limit: **80** for both IPR and ACO (confirmed from IMC documentation).
- Limits are absolute: position must stay in [-80, +80].
- v8 hardcoded 40 — capturing at most 50% of available drift PnL.
- The `room_long_buy = limit - pos` / `room_long_sell = limit + pos` logic in v8 is structurally correct for absolute limits.

## Finding 4: Entry Slippage (multi-timestep greedy buy)

Order book refills fast. Greedy taking fills the full target within 2-4 timesteps (200-400 out of 999,900).

### Target = 80

| Day | Filled | Fill ts | VWAP     | Slippage/unit | Realistic PnL | Theoretical PnL | Capture |
|-----|--------|---------|----------|---------------|---------------|------------------|---------|
| -2  | 80     | 400     | 10007.2  | +8.7          | +79,543       | +80,240          | 99.1%   |
| -1  | 80     | 400     | 11008.1  | +9.6          | +79,192       | +79,960          | 99.0%   |
| 0   | 80     | 200     | 12008.5  | +10.0         | +79,319       | +80,120          | 99.0%   |
| **Mean** | | **333** | | **+9.4** | **+79,351** | **+80,107** | **99.1%** |

### Target = 70

| Day | Filled | Fill ts | VWAP     | Slippage/unit | Realistic PnL | Theoretical PnL | Capture |
|-----|--------|---------|----------|---------------|---------------|------------------|---------|
| -2  | 70     | 200     | 10007.3  | +8.8          | +69,594       | +70,210          | 99.1%   |
| -1  | 70     | 200     | 11008.2  | +9.7          | +69,287       | +69,965          | 99.0%   |
| 0   | 70     | 200     | 12008.4  | +9.9          | +69,413       | +70,105          | 99.0%   |
| **Mean** | | **200** | | **+9.5** | **+69,431** | **+70,093** | **99.1%** |

## Strategy Call: Config A (target_long = 80)

### Rationale

Config A (target=80) vs Config B (target=70) comparison:

| Metric | Config A (80) | Config B (70) | Delta |
|--------|---------------|---------------|-------|
| Drift PnL/day | +79,351 | +69,431 | -9,920 |
| Skim room (units) | 5 | 10 | +5 |
| Break-even skim RT/day | n/a | ~130 | -- |
| v8 estimated skim RT/day | 8-12 | 8-12 | -- |

Config B requires skim/refill to be 16x more productive than v8 estimated to break even with Config A. With <24h until Round 1 deadline, maximizing the certain PnL source (drift) over the speculative one (skim) is the correct call.

### Changes applied (v8 -> v9)

```
POSITION_LIMITS: ACO 40->80, IPR 40->80
IPR_CFG.target_long: 40->80
IPR_CFG.entry_take_cap: 40->80
IPR_CFG.skim_min_pos: 35->75
```

All other IPR_CFG values unchanged. Audited and confirmed appropriate:
- `skim_size: 5` — absolute size matters more than % of position; keeps drift-exposure sacrifice small
- `refill_max_size: 10` — exceeds skim_size, so refill is never the bottleneck
- `deep_bid_offsets/sizes` — see Note 1 below

## Note 1: Deep Bid Feature Retired in Config A

With `target_long = limit = 80`, `room_long_buy` is always 0 except briefly after a skim fill (pos drops to 75, room = 5). In that case, the refill bid (Step 3) claims all 5 units of available room, leaving `remaining_room = 0` for deep bids. The `deep_bid_sizes: [3, 2]` code is therefore dead — it never posts.

This is acceptable for now. The deep bids were speculative "free money on flash crashes" and contribute negligible expected PnL compared to drift.

**Future improvement to consider:** re-enable flash-crash protection via a different mechanism — e.g., temporarily lowering target after an adverse return spike to free room for deep bids. This would let the trader buy dips without permanently sacrificing drift exposure.

## Note 2: Reversal Thresholds Need Scrutiny

The reversal detection uses:
- `reversal_threshold = -8.0` (fast EMA - slow EMA): target flips to 0
- `strong_reversal_thr = -15.0`: target flips to -80 (full short)

With drift std = 1.8 across 3 verified days, these thresholds were designed for a much noisier price assumption. At position 80, a false reversal signal causes a **160-unit forced unwind** (from +80 to -80 at strong reversal), which is catastrophic if drift actually continues upward.

**Backtest must explicitly track:**
1. Did the EMA crossover ever fire a reversal signal during the 3 days?
2. If yes, at what timestamp(s) and what was the actual price behavior in the 100 timesteps after?
3. Would the trader have been better off ignoring the signal?

If the reversal signal never fires in 3 days of data, consider removing it entirely or raising thresholds significantly to avoid the tail risk of a false trigger in live trading.
