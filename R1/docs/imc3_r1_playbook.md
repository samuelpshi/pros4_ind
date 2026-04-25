# IMC Prosperity 3 — Round 1 Strategy Playbook

Synthesized from `/Users/samuelshi/IMC-Prosperity-2026-personal/IMC3_r1.md` (6,838 lines).

## How to Navigate the Source

The source file has five logical regions (in order of appearance):

1. **Lines 1–295** — High-level narrative summary of all three products and cross-product themes. Read this first for orientation.
2. **Lines 296–905** — Cleaned editorial analysis: recommended combinations, architecture critique, improvement proposals. Contains the key parameter-comparison tables.
3. **Lines 906–1060** — Second pass of the same editorial analysis (slightly different phrasing, same numbers). Use as cross-check.
4. **Lines 1063–1930** — Detailed per-product deep dives with pseudocode, signal math, and improvement suggestions.
5. **Lines 1931–6838** — Raw code from multiple codebases (five or more distinct `Trader` class implementations). Parameters are embedded in `PARAMS` dicts and `__init__` constructors. Use Grep for specific constants.

Key grep targets:
- `PARAMS` — the canonical parameter dictionary (lines ~2194–2226)
- `reversion_beta` — all beta occurrences
- `zscore_period`, `smoothing_period`, `threshold` — Squid Ink signal params
- `adverse_volume` — volume filter threshold
- `deflection_threshold` — Kelp deflection param
- `KelpStrategy`, `SquidInkStrategy`, `RainforestResinStrategy` — class implementations

---

## 1. RAINFOREST_RESIN

### Behavior Archetype

**Stable market-making.** Fair value is fixed and does not drift. The only trading decisions are whether currently visible prices are favorable relative to the known fair value.

### Product Character

- Fair value: hardcoded **10,000** (universally agreed across all codebases)
- Price only deviates meaningfully when the market moves outside approximately **±5** of fair value
- No forecasting required; no directional signal needed
- The largest and most reliable PnL contributor of the three products

### Winning Strategies

The most effective approach combined three layers:

1. **Take** any ask below 10,000 or bid above 10,000 aggressively (immediate fill at market)
2. **Zero-EV clearing**: if long and 10,000 is available in the book, sell there; if short, buy there. Individual trade is breakeven but restores capacity for future profitable trades.
3. **Market make** passively at **9,999 / 10,001** (one tick inside fair on each side)

Additional refinement used in one codebase (StaticTrader): "overbid/underbid" — quote one tick inside the best away-from-mid order to gain queue priority. This improves fill rate but adds complexity.

### Specific Parameters (verbatim from PARAMS dict, lines 2194–2199)

```python
Product.RAINFOREST_RESIN: {
    "fair_value": 10000,
    "take_width": 1,       # take if ask <= fair - 1 or bid >= fair + 1
    "clear_width": 0.5,    # zero-EV clear band
    "volume_limit": 0      # no volume filter on this product
}
```

Position limit used in all codebases: **50** (note: IMC4 confirmed this is actually 80 for IPR/ACO — verify for each round's products).

Make quotes (explicit in RainforestResinStrategy, lines 5197–5198):
```python
zero_ev_bid, zero_ev_ask = 10000, 10000   # clear price
pos_ev_bid, pos_ev_ask   = 9999,  10001  # passive quote price
```

One simple-bot codebase used fixed quotes at **9,998 bid / 10,002 ask** with volume **35** per side (lines 5827–5845). This wider spread generates less fill frequency but captures more per fill.

### Edge Cases and How They Were Handled

- **Position limit saturation**: When stuck at +50 or -50, profitable opportunities on the opposite side cannot be taken. The zero-EV clearing mechanic (selling/buying exactly at 10,000 when inventory crosses zero) is the primary mitigation. Clearing at fair value is breakeven per trade but restores future optionality.
- **Adaptive quoting**: If the best ask is at or below `fair_value + 2`, push quoted ask to `fair_value + 3` to avoid posting inside own fair value. Same logic applies on the bid side (lines 2754–2762).
- **No directional risk**: Because fair value is fixed, there is no position-flip risk. Only inventory management matters.

### PnL Attribution

Narrative: "For many strong teams, Rainforest Resin was one of the largest and most stable contributors to round PnL." No specific dollar figures given in the source.

---

## 2. KELP

### Behavior Archetype

**Mean-reverting microstructure-driven market-making.** Fair value is not fixed but moves slowly (mild random walk). The core insight is that the visible mid-price is too noisy — the real fair value must be estimated from large-volume orders ("market-maker quotes") rather than top-of-book prices.

### Product Character

- Fair value moves slowly; not wildly directional
- Spread typically tighter than Resin, so each trade earns less
- Small retail orders distort the visible best bid/ask
- Strong residual autocorrelation: last return predicts next return via a negative beta (mean reversion)
- No reliably exploitable directional trend over longer horizons

### Winning Strategies

1. **Filter order book for large quotes**: ignore orders with volume below **15 units** on the bid side and **21 units** on the ask side in one implementation (lines 3643–3644). Use the resulting "mmbot mid" as fair value rather than raw mid.
2. **Apply mean-reversion adjustment**: fair value = mmbot_mid + mmbot_mid * (last_return * reversion_beta)
3. **Market make around the adjusted fair value**: take orders inside fair±take_width, then post passive quotes.
4. **Deflection mechanism**: after a sharp price move in one direction, temporarily stop quoting on that side to avoid adverse selection.

### Specific Parameters (verbatim from PARAMS dict, lines 2201–2210)

```python
Product.KELP: {
    "take_width": 1.5,          # take if ask <= fair - 1.5 or bid >= fair + 1.5
    "clear_width": 0,           # no separate clear band
    "prevent_adverse": True,    # enable adverse volume filter
    "adverse_volume": 15,       # ignore orders with |volume| < 15 (tested also: 20)
    "reversion_beta": -0.229,   # tested range: -0.0229 to -0.25
    "disregard_edge": 1,        # ignore book levels within 1 tick of fair
    "join_edge": 0,             # join existing quotes at same level (not step ahead)
    "default_edge": 1,          # default passive quote offset from fair
}
```

**Mean-reversion beta consistency**: measured across three different codebases as **-0.229**, **-0.293** (PCA-based), and approximately **-0.23** (reported in recommendation table). The PCA-based third codebase predicted future mmbot log-return with `beta = -0.2933` (line 3392).

**Volume filter thresholds across codebases**:
- Codebase 2 (main PARAMS): `adverse_volume = 15`
- Codebase 3 (kelp_orders function, line 3643): bid filter `>= 15`, ask filter `>= 21`
- Codebase 4 (product_orders, line 4101): `>= 10`
- Recommendation: test both 15 and 20; 15 is the most common

**KelpStrategy deflection threshold** (line 5708):
```python
KelpStrategy(deflection_threshold=0.5, ...)
```
This value was flagged as "likely needs tuning."

**Position limit** used in all codebases: **50**.

**Kelp (codebase 3, PCA-based) fair value model** (lines 3366–3393):
```python
ask_pca = (
    -0.67802679 * ask_volume_1
    + 0.73468115 * ask_volume_2
    + 0.02287503 * ask_volume_3
)
bid_pca = (
    -0.69827525 * bid_volume_1
    + 0.71532596 * bid_volume_2
    + 0.02684134 * bid_volume_3
)
future_log_return_prediction = (
    -0.0000035249
    + 0.0000070160 * ask_pca
    + -0.0000069054 * bid_pca
    + -0.2087831028 * current_log_return
    + -0.0064021782 * lag_1_askvol_return_interaction
    + -0.0049996728 * lag_1_bidvol_return_interaction
)
# Simplified version (recommended):
future_mmbot_log_return_prediction = -0.2933 * current_mmbot_log_return
future_price_prediction = current_mmbot_midprice * exp(future_mmbot_log_return_prediction)
```

**Kelp inventory retreat** (line 3397):
```python
theo = future_price_prediction - kelp_position * self.retreat_per_lot
```
with `retreat_per_lot = 0.012` and `edge_per_lot = 0.015`, `edge0 = 0.02`.

**Kelp order sizing formula** (lines 3416–3417):
```python
bid_volume = floor((bid_edge - edge0) / edge_per_lot)  if bid_edge > edge0 else 0
ask_volume = floor((ask_edge - edge0) / edge_per_lot)  if ask_edge > edge0 else 0
```

**One simple-strategy kelp timespan parameter** (line 3872): `timespan = 10`

### Fair Value Formula Summary

```python
# Step 1: filter book for large-volume orders
filtered_ask = [p for p in sell_orders if |volume| >= adverse_volume]  # default: 15
filtered_bid = [p for p in buy_orders  if |volume| >= adverse_volume]  # default: 15
mmmid_price  = (min(filtered_ask) + max(filtered_bid)) / 2
# fallback to last price or raw mid if no large orders found

# Step 2: apply mean reversion
last_returns = (mmmid_price - last_mmmid) / last_mmmid
pred_returns = last_returns * reversion_beta   # reversion_beta ≈ -0.229
fair_value   = mmmid_price + mmmid_price * pred_returns
```

### Edge Cases and How They Were Handled

- **Missing large-volume orders**: fallback to `kelp_last_price` from previous timestep, or to raw mid if no history exists.
- **Sharp price moves (adverse selection)**: deflection mechanism stops quoting on one side when `change_in_fair > deflection_threshold` (= 0.5). Side that dropped 100 ticks in quoted price is effectively disabled.
- **Unbounded history growth bug**: PCA-based codebase stores the full DataFrame history without truncation — this causes memory growth and was explicitly flagged as a bug. Fix: cap history length.
- **Position limit saturation**: `clear_width = 0` means no separate clearing step; inventory management is entirely through the mean-reversion fair value adjustment.

### PnL Attribution

Not stated explicitly. Described as "smaller total PnL opportunity" than Resin due to tighter spreads.

---

## 3. SQUID_INK

### Behavior Archetype

**Insider-driven directional + mean-reverting hybrid.** The strongest edge did not come from price modelling but from detecting a specific participant (Olivia) who systematically buys at daily lows and sells at daily highs. When Olivia is absent, a smoothed z-score mean-reversion strategy serves as fallback.

### Product Character

- Much higher volatility than Resin or Kelp
- Frequent sharp jumps and reversals
- Passive market making is dangerous due to large post-fill moves
- Olivia: anonymous trader (later identified) who buys **15 lots** at the daily low and sells **15 lots** at the daily high
- In the absence of Olivia's signal, mean-reversion approaches produced inconsistent results

### Winning Strategies

**Primary: Follow Olivia (highest priority)**

When Olivia trades, immediately go to the position limit at market:
- Olivia buy detected → buy to position limit
- Olivia sell detected → sell to position limit

Implementation (`SignalSnoopers.get_olivia_signal`, lines 4913–4920):
```python
def get_olivia_signal(self, product, state) -> int:
    buy_bots  = [t.buyer  for t in state.own_trades.get(product, [])
                           + state.market_trades.get(product, [])]
    sell_bots = [t.seller for t in state.own_trades.get(product, [])
                           + state.market_trades.get(product, [])]
    if "Olivia" in buy_bots:  return 1
    if "Olivia" in sell_bots: return -1
    return 0
```

When Olivia signal is +1: `market_taking_strategy(..., fair_buying_price=99999, fair_selling_price=99999, ...)` — effectively a market buy for the full limit.
When Olivia signal is -1: `market_taking_strategy(..., fair_buying_price=1, fair_selling_price=1, ...)` — effectively a market sell for the full limit.

`SquidInkStrategy` then calls `mean_reversion_taker` with parameters:
```python
self.b.mean_reversion_taker(state, self, self.symbol, self.limit,
    self.price_array, self.fair_price,
    period=100, z_score_threshold=0, fixed_threshold=30)
```

**Secondary: Smoothed Z-Score (when Olivia absent)**

From first codebase (`SquidInkStrategy.get_signal`, lines 2107–2129):
```python
zscore_period    = 150   # rolling window for z-score computation
smoothing_period = 100   # rolling window for smoothing the z-score
threshold        = 1     # entry/exit signal threshold

required_history = zscore_period + smoothing_period  # = 250 timesteps

score = (
    ((hist - hist.rolling(zscore_period).mean())
     / hist.rolling(zscore_period).std())
    .rolling(smoothing_period)
    .mean()
    .iloc[-1]
)

if score < -threshold:   return Signal.LONG
if score > +threshold:   return Signal.SHORT
```

**Alternative z-score parameters from other codebases:**
- Codebase 3 (third Trader, lines 3433–3444): `rolling_window = 150`, `edge_0 = 2`. Target position sizing: `target_position = min(int((|z_score| - edge_0) * 10), 30)` — scales position linearly with z-score above threshold, capped at **30**.
- Codebase 2 (PARAMS, line 2225): `z_trigger = 3.75` — editorial consensus is this is "too conservative" and produces very few trades.
- Recommendation table (line 358): "Mean reversion threshold ≈ 1.5–2"

**Tertiary: Regime-switching SMA (volatility-based)**

From second Trader codebase (`sma` function, lines 2504–2595):
```python
PARAMS[SQUID_INK] = {
    "averaging_length"     : 350,   # SMA period
    "trigger_price"        : 10,    # price deviation from SMA to enter
    "take_width"           : 5,     # aggressive order offset from best bid/ask
    "clear_width"          : 1,
    "adverse_volume"       : 18,    # volume filter for MM mode
    "reversion_beta"       : -0.3,  # used in MM fair-value computation
    "disregard_edge"       : 1,
    "join_edge"            : 1,
    "default_edge"         : 1,
    "max_order_quantity"   : 35,
    "volatility_threshold" : 3,     # switch from MM to SMA mean-reversion
    "z_trigger"            : 3.75,  # z-score entry threshold (flagged as too conservative)
}
```

Regime logic:
- `if volatility > 3`: use SMA mean-reversion (if price deviates ≥ 10 from 350-period SMA, enter aggressively)
- `else`: use market-making with dynamic fair value (filtered mmbot mid + dynamic slope)

**Dynamic reversion beta for Squid Ink** (lines 2476–2483):
```python
slope_sign      = 1 if slope > 0 else -1
slope_magnitude = abs(slope)
# Normalized to range [0.02, 0.3]:
normalized_magnitude = min(0.3, max(0.02, 0.1 * (slope_magnitude / 100)))
norm_slope = slope_sign * normalized_magnitude
```
Slope is computed via linear regression over the last **3–4** mmbot mid-prices.

**Spread-based market-making filter** (lines 2795–2796):
```python
if current_max_spread > avg_max_spread + 2:
    return []   # skip market making entirely
```
Spread history window: **4** ticks (lines 2446–2454).

**Pressure signal** (fourth codebase, lines 3697–3760):
- Tracks mmbot bid and ask level changes over **50 ticks**
- `running_pressure = sum(pressure_history[-50:])`
- Signals: if `0 < running_pressure < 30` → buy; if `running_pressure < -30` → sell
- Editorial verdict: "fragile" — a single large order disappearing registers as strong negative pressure even if price hasn't moved.

**EMA-based Squid Ink** (fifth codebase, lines 6142–6174):
```python
squid_ink_short_window = 600   # EMA short period
squid_ink_long_window  = 1400  # EMA long period
alpha = 2 / (long_window + 1)
# EMA cross signals directional trades
entry_z  = 1.25  # z-score entry threshold
exit_z   = 0.3   # z-score exit threshold
```

**Simpler EMA-momentum approach** (lines 5853–5960):
```python
window             = 30
std_threshold      = 1.4   # rolling std must exceed this to trade
momentum_threshold = 0.5   # EMA(5) - EMA(15) must exceed this
slope_threshold    = 0.01  # linear regression slope must exceed this
max_hold_time      = 50_000  # force-exit position after this many ms
```
EMA formula (line 5869–5873):
```python
alpha = 2 / (span + 1)
ema   = alpha * price + (1 - alpha) * prev_ema
```
EMA spans used: short = **5**, long = **15** (lines 5898–5900).

**Position sizing formula** in z-score adaptive approach (lines 6412–6416):
```python
aggression = min(25, abs(z) * max_pos)   # dynamic size, capped at 25
# Dynamic quantity (from squid_ink_orders, line 2937):
scale       = min(abs(zscore), 3)
dynamic_qty = max(min(int(scale * min(base_quantity, adjusted_limit)), max_quantity), min_quantity)
```

### Edge Cases and How They Were Handled

- **High-volatility market making**: disabled when `current_max_spread > avg_max_spread + 2`. In spread-stable but trending markets, use slope sign to skew bid/ask quotes directionally.
- **Position time limit**: one codebase exits positions after `max_hold_time = 50,000` ms (line 5867) regardless of signal.
- **Insufficient history**: different codebases handle this differently. Best practice: emit no orders until `len(history) >= required_history`.
- **Proximity to anchor price**: one codebase (squid_ink_orders) adjusts effective position limit by distance from `fair_value = 2000`: `anchor_proximity = max(0, 1 - (distance_from_anchor / 100))`, `adjusted_limit = max(10, position_limit * anchor_proximity)` (lines 2919–2922). This is adaptive position sizing near a price anchor.

### PnL Attribution

"Squid Ink was the most difficult product to trade well and often the least uniform across teams." No specific dollar figure given. The Olivia-following approach was described as "far more robust" than statistical approaches.

---

## 4. Cross-Product Patterns and Themes

### A. Fair Value Hierarchy

| Product | Fair Value Method | Key Formula |
|---|---|---|
| RAINFOREST_RESIN | Hardcoded constant | `fair = 10000` |
| KELP | Filtered mmbot mid + mean reversion | `fair = mmmid + mmmid * last_return * beta` |
| SQUID_INK | Smoothed z-score anchor / Olivia / regime | Various (see above) |

### B. Standard Execution Stack

Every product uses the same three-layer execution pattern:
1. **Take**: hit orders at `best_ask <= fair - take_width` or `best_bid >= fair + take_width`
2. **Clear**: reduce inventory when price returns to fair (zero-EV or near-zero-EV trades)
3. **Make**: post passive quotes around fair

### C. Inventory Management

Position limits were **50** per product in IMC3 Round 1 (confirmed across all codebases). The standard inventory formulas:
```python
to_buy  = limit - position          # remaining long capacity
to_sell = limit + position          # remaining short capacity
```
Both are used identically in all codebases.

### D. Signal Architecture (Recommended Upgrade)

The recommended unified framework from the editorial analysis:
```python
signal           = w1 * zscore + w2 * imbalance + w3 * trend
target_inventory = clip(signal * scale, -limit, limit)
# Execution: buy if target > position, sell if target < position
```

### E. Key Microstructure Formulas

**Micro-price** (volume-weighted fair value):
```
P_micro = (V_bid * P_ask + V_ask * P_bid) / (V_bid + V_ask)
```

**Order book imbalance**:
```
I = (V_bid - V_ask) / (V_bid + V_ask)
```
When `I > 0.4`, price likely to move up; use to confirm z-score signals.

**Inventory skew** (for price adjustment):
```
P_skewed = P_fair - (inventory * inventory_skew)
```

---

## 5. Architecture Notes

### Recommended Class Structure (from "first codebase")

```
Strategy           → base execution class (symbol, limit, act(), run())
StatefulStrategy   → adds save()/load() via traderData
SignalStrategy     → LONG/SHORT/NEUTRAL signals, goes to limit at market
MarketMakingStrategy → get_true_value() → take/clear/make loop
```

Per-product instantiation (all positions limits 50, from lines 2141–2154):
```python
limits = {"RAINFOREST_RESIN": 50, "KELP": 50, "SQUID_INK": 50}
```

### State Persistence Pattern

Save/load per symbol:
```python
new_trader_data[symbol] = strategy.save()   # serialized each tick
strategy.load(old_trader_data[symbol])      # restored next tick
```
Prevents cross-product state pollution and handles missing keys gracefully.

---

## 6. Mapping Matrix

### 6A. Prior Product → Archetype + Key Parameters

| Product | Archetype | Top Numeric Parameters |
|---|---|---|
| **RAINFOREST_RESIN** | Stable market-making | fair_value=10000; take_width=1; clear_width=0.5; make at 9999/10001; position_limit=50 |
| **KELP** | Mean-reverting microstructure | adverse_volume=15 (filter); reversion_beta=-0.229; take_width=1.5; clear_width=0; deflection_threshold=0.5; position_limit=50 |
| **SQUID_INK** | Insider-driven + mean-reverting hybrid | Olivia signal: go to limit at market; z-score: zscore_period=150, smoothing_period=100, threshold=1; SMA fallback: averaging_length=350, volatility_threshold=3, trigger_price=10; z_trigger alt values: 1.0 (codebase 1), 2.0 (codebase 3), 3.75 (codebase 2, too conservative); position_limit=50 |

### 6B. Archetype → Strategy Family + Starting Parameters

| Archetype | Strategy Family | Starting Parameters |
|---|---|---|
| **Stable market-making** | Fixed fair value; take ±1 tick; zero-EV clear at fair; make 1 tick inside fair | fair_value=hardcoded; take_width=1; clear_width=0.5; passive_bid=fair-1; passive_ask=fair+1 |
| **Mean-reverting microstructure** | Filtered mmbot mid + negative beta adjustment; standard take/clear/make stack | adverse_volume=15; reversion_beta=-0.229 to -0.293; take_width=1.5; deflection on sharp move (threshold=0.5) |
| **Insider-driven directional** | Detect named trader in market_trades/own_trades; go to limit at market immediately | signal: +1/-1/0; action: full-limit market order; fallback to z-score when signal=0 |
| **Mean-reverting statistical** | Rolling z-score, smoothed, threshold entry | zscore_period=150; smoothing_period=100; threshold=1 (conservative: 2.0; too tight: 3.75) |
| **Regime-switching hybrid** | Volatility gate selects between mean reversion (SMA) and market making | volatility_threshold=3; SMA period=350; trigger_price=10; take_width=5 (higher for aggressive mean reversion) |
| **EMA momentum** | EMA crossover + std gate | short_span=5; long_span=15; std_threshold=1.4; momentum_threshold=0.5; max_hold_time=50000ms |

### 6C. Recommended Combination Table (from source, line 356–358)

| Product | Fair Value | Take | Clear | Make | Signal |
|---|---|---|---|---|---|
| RAINFOREST_RESIN | Hardcoded 10,000 | Aggressively at 9,999/10,001 | Zero-EV at 10,000 | 9,999/10,001 | None needed |
| KELP | Market-maker mid + reversion_beta ≈ -0.23 | ±1.5 ticks | Near fair | Inside best away-from-mid order | Deflection on sharp moves |
| SQUID_INK | Smoothed z-score (periods 150/100) | Follow Olivia immediately when active | Mean reversion threshold ≈ 1.5–2 | Avoid making during high volatility | Olivia first, z-score second |

---

## 7. Parameters Not Specified in Source

The following are flagged explicitly as unspecified or flagged as needing tuning:
- Optimal edge size for Resin market making (sources say test via backtest/grid search; 9,999/10,001 is the consensus starting point)
- Optimal `adverse_volume` for Kelp (source says "both 15 and 20 are worth testing")
- `deflection_threshold = 0.5` — explicitly flagged as "likely needs tuning"
- Olivia trade size at which she acts (source says 15 lots, inferred from behavioral observation)
- z-score threshold for Squid Ink (source gives a range: 1.0, 2.0, 3.75 — 3.75 is flagged as too conservative)

---

*Playbook synthesized 2026-04-16. Source: IMC Prosperity 3 Round 1 writeup (6,838 lines). For IMC Prosperity 4, verify position limits per product before reusing numeric constants.*
