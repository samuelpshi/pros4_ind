# R4 Counterparty Analysis — Findings

**Goal:** Find the Olivia-equivalent in R4. Use the newly-revealed trader IDs in `trades_round_4_day_{1,2,3}.csv` to identify (a) informed traders we should follow, (b) "patsy" traders we should fade or replace, and (c) market-makers we compete with.

**Data:** 4,281 trades across 12 products × 3 days. Cash flows zero-sum-check passes (max abs imbalance = 0.0).

**Trader universe:** 7 bots — Mark 01, 14, 22, 38, 49, 55, 67.

**Methodology:** for each fill, compute `edge_close = side · (day_close_mid − price) · qty` (mark-to-EoD PnL contribution) plus forward edges at +5k and +50k ticks. Aggregate per (trader, product, day). Bootstrap 2000-sample one-sided p-values on per-fill mean edge.

---

## 1. PnL Leaderboard (sum across all 3 days, all products)

| Trader   | n_fills | gross_qty | edge_close (∑ MTM-EoD) | edge_close per fill | win-rate close | win-rate +5k | bootstrap p (mean ≠ 0) |
|----------|--------:|----------:|-----------------------:|---------------------:|---------------:|-------------:|----------------------:|
| **Mark 14** | 2,172 | 8,718 | **+42,206** | +19.4 | 0.56 | **0.72** | <0.001 |
| **Mark 67** |   165 | 1,510 | **+27,261** | **+165.2** | **0.78** | 0.53 | <0.001 |
| Mark 01 | 1,843 | 7,428 | +10,101 | +5.5 | **0.72** | **0.81** | 0.006 |
| Mark 55 | 1,198 | 6,551 | −13,204 | −11.0 | 0.49 | 0.38 | 0.016 |
| Mark 49 |   122 | 1,186 | −15,346 | **−125.8** | 0.34 | 0.44 | <0.001 |
| Mark 22 | 1,584 | 5,889 | −17,395 | −11.0 | **0.21** | **0.15** | <0.001 |
| Mark 38 | 1,478 | 5,000 | **−33,622** | −22.7 | 0.41 | **0.20** | <0.001 |

Numbers reproducible from `trader_summary.csv` and `trader_bootstrap.csv`.

**Headline:** four traders are statistically distinguishable winners or losers at p<0.01.

---

## 2. Per-product attribution — who makes money on what

`edge_close` summed across 3 days, by trader × product (see `trader_product_day.csv`):

| Symbol            | M01  | M14   | M22    | M38    | M49     | M55     | M67    |
|-------------------|-----:|------:|-------:|-------:|--------:|--------:|-------:|
| HYDROGEL_PACK     |    0 | **+24,415** |    −23 | **−24,392** |       0 |       0 |      0 |
| VELVETFRUIT_EXTRACT | +4,366 | +6,906 | −9,984 |     0 | **−15,346** | **−13,204** | **+27,261** |
| VEV_4000          |    0 | **+9,241** |     −0 |  **−9,240** |       0 |       0 |      0 |
| VEV_4500–5100     |    0 |     0 |   ~0   |    ~0  |       0 |       0 |      0 |
| VEV_5200          |   +155 |   +974 | −1,123 |     −6 |       0 |       0 |      0 |
| VEV_5300          |   +1,755 |  +742 | −2,514 |    +17 |       0 |       0 |      0 |
| VEV_5400          |   +1,882 |   −84 | −1,798 |     0 |       0 |       0 |      0 |
| VEV_5500          |     +837 |   +12 |   −849 |     0 |       0 |       0 |      0 |
| VEV_6000          |     +552 |     0 |   −552 |     0 |       0 |       0 |      0 |
| VEV_6500          |     +552 |     0 |   −552 |     0 |       0 |       0 |      0 |

**Three closed loops emerge:**

1. **HYDROGEL_PACK + VEV_4000:** essentially a 2-player game. Mark 14 takes ~$33k off Mark 38, almost exactly the gross size of those two product PnLs combined. Other Marks barely participate.
2. **VELVETFRUIT_EXTRACT:** 6-trader product, but the one-sided structural flow (M67 buys only, M49 sells only, M55 mostly sells) drives most of the PnL.
3. **High-strike VEV vouchers (5300–6500):** Mark 22 sells, Mark 01 buys. M22 loses ~$6.3k cumulatively across these; M01 collects almost exactly the mirror.

---

## 3. Counterparty matrix — who pays whom

`edge_close` row-wise (positive = row trader makes money against column trader), sum across all products & days; from `counterparty_matrix.csv`:

| trader → cp | M01 | M14 | M22 | M38 | M49 | M55 | M67 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Mark 01 |  · |  0 | **+5,734** |  0 |  0 | **+4,366** |  0 |
| Mark 14 |  0 |  · | +1,644 | **+33,656** |  0 | +6,906 |  0 |
| Mark 22 | −5,734 | −1,644 | · | −34 | +377 | +1,020 | **−11,380** |
| Mark 38 |  0 | **−33,656** | +34 |  · |  0 |  0 |  0 |
| Mark 49 |  0 |  0 | −377 |  0 |  · | +921 | **−15,890** |
| Mark 55 | −4,366 | −6,906 | −1,020 |  0 | −921 |  · | −9 |
| Mark 67 |  0 |  0 | **+11,380** |  0 | **+15,890** | +9 |  · |

The dominant edge transfers:
- **Mark 14 ↔ Mark 38: −$33,656** (all on HYDROGEL + VEV_4000)
- **Mark 67 ↔ Mark 49: −$15,890** (all on VELVETFRUIT)
- **Mark 67 ↔ Mark 22: −$11,380** (all on VELVETFRUIT)
- **Mark 14 ↔ Mark 55: −$6,906** (mostly VELVETFRUIT)
- **Mark 01 ↔ Mark 22: −$5,734** (high-strike vouchers)

---

## 4. Trader profiles

### Mark 14 — TOP MARKET-MAKER on HYDROGEL_PACK and VEV_4000
- 2,172 fills (largest of any trader). Roughly balanced (1,127 buys / 1,045 sells).
- Inventory mean-reverts around 0 (bounded ±50 on HYDROGEL, see `figures/focus_Mark14_HYDROGEL_day1.png`).
- Buys cluster *below* mid, sells cluster *above* mid → he's spread-capturing, not directional.
- Win rate jumps from 56% close → **72% +5k**, meaning his alpha is short-horizon micro-structural (he picks the right side at the right tick), not "knows where price closes".
- **He's not Olivia. He's the rival market-maker we compete with.**
- Per-day edge_close: +23k / +5.7k / +13.5k → consistent across all 3 days.

### Mark 67 — DIRECTIONAL ONE-WAY BUYER on VELVETFRUIT (the Olivia candidate)
- 165 fills, **all buys, zero sells**. Avg fill qty 9.2.
- Per day: +9k / +21.8k / **−3.6k** → wins 2 of 3 days, but day 3 loses.
- Trades broadly throughout the day (first ts ~10k–30k, last ts ~990k), monotonically accumulating long position to ~+500.
- Edge realises long-horizon: edge_5k = +1.7k vs edge_close = +27k → his individual fills don't move price; the day moves with him.
- **Not a perfect bottom-picker** like Olivia. More like a structural bull who's correct ⅔ of the time.
- Suggestive cross-day signal: total day-1 buy qty **519, 567, 424** correlates with day open→close move **+20, +28, −63**. The day-3 lower volume hinted at lower conviction.

### Mark 49 — DIRECTIONAL ONE-WAY SELLER on VELVETFRUIT (the loser-mirror of M67)
- 122 fills, ~85% sells (105 vs 17 buys). Avg fill qty 9.7.
- Per day: −4.7k / −14k / +3.4k → mirrors Mark 67 inverted.
- Per-fill edge **−$126 average** — the most negative per-fill edge of any trader.
- Very-short-horizon edge_5k is small (−$1.2k) but EoD edge huge (−$15k). Same long-horizon directional pattern as Mark 67.
- **Likely the natural counterparty to Mark 67's flow.** Net imbalance (M67 buys − M49 sells) = +177 / +167 / +95 across days 1/2/3, monotonically aligned with the day's direction.

### Mark 22 — ALWAYS-SELLS HIGH-STRIKE VOUCHERS (and VELVETFRUIT)
- 1,584 fills, **97% sells** (1,542 vs 42 buys overall).
- On VEV_5400/5500/6000/6500: **literally never buys** (0 buys across all 3 days). Pure short-call writer.
- Win rate **21% close, 15% +5k** — by far the worst short-horizon trader.
- His sell-prices average at price_pct_of_day = 0.30–0.45 (i.e. **below the day's midpoint**) — selling cheap, getting picked off.
- **He's our best source of cheap calls.** Whenever Mark 22 is on the offer side of a high-strike voucher, the mid will probably drift higher.

### Mark 01 — ALWAYS-BUYS HIGH-STRIKE VOUCHERS (Mark 22's mirror)
- 1,843 fills, 87% buys overall (1,599 vs 244 sells); on VEV_5400/5500/6000/6500: **only buys**.
- Win rate **72% close, 81% +5k** — the most consistently right per-fill of all traders.
- VEV_6000 and VEV_6500 trades are typically at price 0.5 vs settle 1, so the +0.5 unit edge is cheap optionality bought at intrinsic ≈ 0.
- Per day on big strikes (5300–5500): wins on days 1+2, slightly loses on day 3.
- **Probably a structural call buyer / hedger, but with some price discrimination.** When Mark 01 is bidding, it's often a fair-value bid we can join.

### Mark 38 — THE PATSY on HYDROGEL_PACK and VEV_4000 (Mark 14's mirror)
- 1,478 fills, balanced direction (733 buys / 745 sells), but inventory drifts countertrend.
- BUYS cluster *above* mid, SELLS cluster *below* mid (`focus_Mark38_HYDROGEL_day1.png`).
- Win rate **41% close, 20% +5k** — gets picked off in the very next ticks.
- His total edge_close ≈ Mark 14's negated. They mostly trade with each other.
- **Useful as a contrarian micro signal: when Mark 38 buys, fade.**

### Mark 55 — VELVETFRUIT-only, balanced but losing
- 1,198 fills, 50/50 buys/sells, but loses −$13k on the day's close.
- Win rate ~49% close, 38% +5k — slightly worse than coinflip.
- Less informative than the one-sided traders; more of a low-quality MM.

---

## 5. Strategic recommendations for our R4 trader

### A. VELVETFRUIT_EXTRACT — exploit the M67/M49 imbalance
1. **Tally Mark 67 buy volume vs Mark 49 sell volume in a rolling window** (the trades show up in `state.market_trades`, addressable by `Trade.buyer`/`seller`). When net imbalance accumulates beyond a threshold (e.g. >40 over the last 100k ticks), tilt our position long. Day 1/2 had +177/+167 net buys at close → both upside days.
2. **Mark 67's first-buy-of-day timestamp** is a coarse early signal: <15k = strong (days 1/2), >30k = weak (day 3). On day 1 of round live, simply waiting for M67's first buy and going long for the day worked twice out of three.
3. **Don't hedge against Mark 67's flow.** If we accumulate VELVETFRUIT long alongside M67, we ride the EoD drift. Conversely, if we see Mark 49 sells outpacing Mark 67 buys, fade by going short.
4. Caveat: only 3 days of data — the 2/3 hit-rate could easily go 1/3 in live; size accordingly.

### B. HYDROGEL_PACK and VEV_4000 — be Mark 14, not Mark 38
1. Mark 14's behaviour matches a **pure spread-capturing market maker** with bounded inventory. Reproducing his style: post both sides at ±1 around mid; flatten to 0 by EoD.
2. When Mark 38 lifts our offer, that's a *good* fill (he's the patsy). When Mark 14 lifts our offer, more of a *bad* fill — we may have been picked off.
3. Specifically on HYDROGEL_PACK: Mark 14 alone made +24k. The product is **not informed-flow driven**; it's a market-maker scalp game. A clean inventory-bounded spread-quoter will share the pie with him.
4. VEV_4000 is identical structure; treat as ATM-call-MM with delta-hedging.

### C. High-strike vouchers (VEV_5300+) — buy from Mark 22
1. Mark 22 dumps high-strike vouchers persistently. His 5400/5500/6000/6500 fills total ~$5.6k of edge given up to Mark 01.
2. **Whenever Mark 22 is the best offer on these strikes, lift it.** Even VEV_6500 at 0.5 (intrinsic ~0) settled at 1.0 every day — risk-free 0.5/unit *if we can confirm Mark 22 is the source*.
3. Track this in code: when our `state.order_depths[<voucher>].sell_orders` shows a level whose volume matches Mark 22's typical sell pattern (1–6 lots), aggress.
4. Since Mark 01 is already harvesting this systematically, expect competition — race him to the bid.

### D. Cross-product hedge consideration (per the writeup we read)
- Total expected daily edge from informed signals (rough order of magnitude):
  - VELVETFRUIT directional follow-Mark-67: ~$3–10k/day expected (need sizing rules, position limit 200 caps us)
  - HYDROGEL/VEV_4000 MM: aim for ~$5k/day (Mark 14 makes ~$14k/day at ~10x our likely capacity)
  - High-strike voucher harvesting: ~$1–2k/day from M22's flow
- These are independent edges — combine them, don't trade them off.
- **Position-limit interaction:** Mark 67 follow signal pushes us long VELVETFRUIT (limit 200). VEV_4000 MM is delta-hedged, so doesn't conflict. High-strike voucher harvest is small-size enough (lot sizes 1–6) to ignore.

---

## 6. What we still don't know / next-step probes

1. **Day-3 reversal:** every "smart" trader (M14, M67, M01) had reduced edges on day 3, and Mark 49 even turned positive. Was day 3 an inflection day, or do the smart traders generally underperform when the market reverses? We'd need >3 days to tell.
2. **Order-book footprints:** we haven't yet checked whether Mark 67 is the *resting* bid or the *aggressing* bid. Useful to know — if he passively quotes, his quote width may be a signal too.
3. **Quote-deletion tracking:** the `prices_round_4_*.csv` show top-3 levels but not who placed them. We can't currently tie order-book quotes to trader IDs without IMC-revealed ID attribution per quote (only trades are attributed).
4. **Test the M67 first-buy signal in a live submission.** Cheap to add — wrap a "follow M67" rule into the VELVETFRUIT trader and backtest.
5. **Test "fade Mark 38"** explicitly: when `state.market_trades[HYDROGEL_PACK]` contains a buy where buyer == "Mark 38", short for the next ~5k ticks. His +5k win rate is 0.20, so contrarian win rate ≈ 0.80.

---

## Files produced (`R4/analysis/counterparty/`)

- `build_dataset.py`, `edge_pnl.py`, `timing_analysis.py`, `plots.py`, `focused_plots.py` — analysis scripts
- `trades_enriched.pkl`, `mid_panel.pkl` — cached enriched datasets
- `trader_summary.csv`, `trader_product_day.csv`, `trader_product_breakdown.csv`, `counterparty_matrix.csv`, `trader_symbol_day_timing.csv`, `trader_bootstrap.csv` — tabulated results
- `figures/` — 36 per-(product,day) overlay plots + 21 per-trader focus plots with cumulative inventory
