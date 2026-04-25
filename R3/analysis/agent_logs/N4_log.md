# N4 — Signal Validation & FH-Feature Replication log

Notebook: `R3/analysis/04_signal_validation_and_fh_features.ipynb`
Builder: `R3/analysis/_build_n4.py`

## What we did

Self-contained notebook that re-implements BS pricer, IV solver, and pooled
+ per-tick quadratic smile fits (consistent with N3) so it runs independently.
Computed price residuals (market − BS-from-smile) under both hardcoded and
per-tick smile, against both `best_mid` and `wall_mid` market anchors.
Validated whether residuals are scalpable: (A) lag-1 autocorr per strike;
FH 1,000-sim Gaussian randomization band; multi-lag ACF; in-sample |z|>1.5
open / |z|<0.5 close scalp PnL with 200-tick rolling window. (B) Tested the
base-IV intercept c_t for stationarity (ADF, AR(1)/half-life) and ran a
z-score scalp of c_t on the ATM voucher. (C) Replicated FH's signal
architecture piece by piece — wall-mid vs best-mid anchor, EMA20 demeaning,
EMA100 |residual − EMA| switch gate at threshold 0.7, low-vega
(vega ≤ 1) threshold adjustment. (D) Strike segmentation diagnostic —
median vega and voucher-vs-VEV return correlation. (E) Hedge-feasibility
under fitted-IV deltas with the VEV ±200 cap. (F) Wrote a ranked Phase-2
A/B variation list. Cached: `cache/n4_iv_best.pkl`, `cache/n4_iv_wall.pkl`,
`cache/n4_pertick_smile.pkl`, `cache/n4_variations_to_backtest.csv`.

## Findings

- **Pooled smile fit on N4's IV set (cell 11):** a=0.142503, b=−0.002020,
  c=0.235694, R²=0.9836, σ_res=0.01747, n=251,785. Note: differs from N3's
  (0.158, −0.0046, 0.232) because N4 does not apply the EPS_EXT=0.5 filter
  before fitting — see "open questions" for the contradiction.
- **Per-tick smile mean coefs (cell 12):** a=0.13485 (std 0.01186),
  b=0.01045 (std 0.01755), c=0.23518 (std 0.00353). Success rate 100% across
  30,000 ticks.
- **Raw price residual lag-1 autocorr (cell 16, hardcoded smile, best_mid):**
  | K | ρ₁ raw | ρ₁ per-tick |
  |---|---|---|
  | 5000 | 0.196 | 0.228 |
  | 5100 | **0.810** | 0.462 |
  | 5200 | **0.831** | 0.409 |
  | 5300 | **0.934** | 0.669 |
  | 5400 | **0.948** | 0.750 |
  | 5500 | **0.928** | 0.542 |
  | 6000 | 1.000 | 0.705 |
  | 6500 | 1.000 | 0.404 |
  All strongly positive — raw residuals trend, do not revert.
- **FH randomization test (cell 17).** All strikes' real ρ₁ at the 100th
  percentile of the 1000-sim Gaussian band (band roughly ±0.011). **Zero
  strikes pass the FH "significantly negative" filter on raw residuals.**
  Contradicts the FH P3 finding.
- **In-sample |z|>1.5 / |z|<0.5 scalp on raw residuals (cell 22).** Cumulative
  PnL still positive on every strike with IV coverage, but PnL-per-round-trip
  is below median spread on every strike → zero-cost upper bound only:
  | K | cum PnL | n trades | PnL/trade | med spread |
  |---|---|---|---|---|
  | 4000 | 4665 | 1807 | 2.58 | 21 |
  | 4500 | 3888 | 1756 | 2.21 | 16 |
  | 5000 | 3146 | 2272 | 1.39 | 6 |
  | 5100 | 2700 | 2387 | 1.13 | 4 |
  | 5200 | 2208 | 2565 | 0.86 | 3 |
  | 5300 | 1669 | 2685 | 0.62 | 2 |
  | 5400 | 968 | 2586 | 0.37 | 1 |
  | 5500 | 527 | 1319 | 0.40 | 1 |
- **Base IV c_t mean reversion (cell 25).** c_t: n=30000, mean 0.23518,
  std 0.00353, range [0.22439, 0.25829]. ADF stat=−8.247, p=4e-13
  → stationary. AR(1) φ=0.17023, OU half-life ≈ 0.4 ticks (essentially noise
  around a slowly drifting mean).
- **c_t mean-reversion overlay PnL (cell 26).** Z-score of c_t over 500-tick
  window, trade ATM voucher in direction of reversion: cumulative PnL =
  **+2,490** over ~2,326 trades — small but consistent additive overlay.
- **Anchor comparison (cell 28).** Wall-mid vs best-mid residuals: wall-mid
  has slightly lower stdev (e.g., 5200: 0.893 vs 0.908) but slightly *higher*
  raw lag-1 autocorr (0.860 vs 0.831) on ATM strikes — neither dominates;
  wall-mid stale-quote effect cancels its noise reduction.
- **EMA20 demeaning is critical (cell 29).** Lag-1 autocorr raw → demeaned:
  | K | raw (wall_mid) | EMA20-demeaned |
  |---|---|---|
  | 5100 | 0.822 | **−0.037** |
  | 5200 | 0.860 | **−0.015** |
  | 5300 | 0.952 | +0.009 |
  | 5400 | 0.949 | +0.087 |
  | 5500 | 0.930 | +0.535 |
  Demeaning flips the sign of ATM-band autocorr from +0.8/0.9 to ≈0/slightly
  negative — converts the slow-drifting residual into a tradeable signal.
- **FH switch gate is dead on R3 (cell 30).** Switch_means = EMA100 of
  |residual − EMA20|. At threshold 0.7, gate is OPEN on **0.0%** of ticks on
  every strike. FH's threshold was calibrated on P3 voucher price scale; on
  R3 typical |resid − EMA| is much smaller. Gate must be either dropped or
  rescaled (variations_to_test: 0.05 / 0.10 / 0.20 / off).
- **Low-vega regime is empty on R3 (cell 32).** Vega ≤ 1 holds on **0.0%** of
  ticks on every strike. Median vega per strike: 4000=11.9, 4500=6.9,
  5000=99.9, 5100=186.4, 5200=268.0, 5300=268.0, 5400=195.3, 5500=111.3,
  6000=8.7, 6500=8.6. FH's `LOW_VEGA_THR_ADJ=0.5` at vega ≤ 1 catches no R3
  strikes — needs rescaling (e.g., adj when vega < 2 or scale linearly with
  1/vega).
- **Voucher-VEV return correlation (cell 35):** 5500=0.348, 5400=0.540,
  4000=0.595, 4500=0.598, 5300=0.622, 5200=0.717, 5000=0.754, 5100=0.765;
  6000/6500=NaN. Lower-vega ATM-band strikes ride the underlying more.
- **Median fitted-IV BS deltas (cell 37):** 4000=0.994, 4500=0.997,
  5000=0.926, 5100=0.818, 5200=**0.623**, 5300=0.387, 5400=0.198, 5500=0.088,
  6000/6500=0.004.
- **Hedge feasibility (cells 37-38).** Long 300 of K=5200 alone = 187 of
  delta (just under VEV 200 cap). Long 300 each of {5100,5200,5300} =
  **548.7 net delta — not hedgeable**. Per-strike max alone before VEV cap:
  K=4000/4500: 201, K=5000: 216, K=5100: 244, K=5200..6500: 300. **Joint cap
  for {5100,5200,5300} simultaneous long: 109.4 contracts each before
  |sum delta| > 200** — VEV is the binding constraint.
- **Phase-2 variation list ranked (cache `n4_variations_to_backtest.csv`):**
  rank 1 EMA demeaning (CRITICAL); 2 switch-gate threshold; 3 open/close
  thresholds; 4 smile fit method; 5 market-price anchor; 6 strike triage;
  7 explicit delta hedge; 8 base-IV MR overlay; 9 underlying VEV MR overlay;
  10 low-vega threshold adjustment.

## Open questions / known limits

- In-sample PnL has **zero slippage and assumes mid-fills**. Real PnL will be
  a fraction of these numbers; Rust backtester is the next gate.
- N4's pooled smile fit (a=0.143, b=−0.002, c=0.236, n=251,785) differs from
  N3's (a=0.158, b=−0.0046, c=0.232, n=182,696). N4 does not apply
  EPS_EXT=0.5 before fitting; this affects whether 6000/6500 contribute
  numerically tiny IV "successes" (per N4, coverage 100%) versus being
  excluded entirely (per N3). Trader v1 should use the N3 fit per N3's
  own recommendation.
- TTE-driven step in c_t at day boundaries is small but real; trader should
  reset/widen the EMA windows around boundaries.
- No deep-dive on whether the *demeaned* residual passes the FH
  randomization test (only raw was tested at cell 17). Demeaned ρ₁ near zero
  is good but variance/significance not separately bounded.
- Per-tick smile success rate 100%, but `c_t` only varies in [0.224, 0.258]
  — tight. Hardcoded smile is likely a fine starting point; per-tick may add
  noise without benefit.
