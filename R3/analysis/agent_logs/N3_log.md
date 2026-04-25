# N3 — IV & Smile Analysis log

Notebook: `R3/analysis/03_iv_smile_analysis.ipynb`

## What we did

Built a from-scratch Black-Scholes call pricer (r=0, no divs) and Newton-with-
bisection-fallback IV solver, validated by a synthetic round-trip
(max abs error 4.38e-11). Loaded the 3-day voucher panel (300,000 voucher
rows), computed `best_mid`, `wall_mid`, S, T, and moneyness m=log(K/S)/√T per
tick. Filtered to extrinsic ≥ 0.5 and inverted IV per voucher per tick (60.9%
survival = 182,696 rows). Fitted the pooled quadratic smile v̂(m)=am²+bm+c in
unweighted, 1/|m| (ATM-up), and vega-weighted forms. Ran a per-tick smile
refit (>=4 strikes per tick, success rate 100% / 30,000 ticks). Computed IV-
space and price-space residuals under both pooled and per-tick fits and
tabulated their stdev and lag-1 autocorrelation per strike. Cached:
`cache/smile_params.json`, `cache/iv_panel.pkl` (32 MB),
`cache/per_tick_smile.pkl`, `cache/iv_per_tick.pkl` (40 MB). Figures:
`fig_n3_pooled_smile.png`, `fig_n3_pooled_fit.png`, `fig_n3_per_tick_coefs.png`,
`fig_n3_iv_resids.png`, `fig_n3_price_resids.png`, `fig_n3_resid_compare.png`.

## Findings

- **Pooled unweighted smile fit (cell 23):** **a = 0.15778, b = −0.00464,
  c = 0.23221**, residual stdev 0.01447 in IV space, R² = 0.9476 over
  182,696 obs.
- **Pooled vega-weighted (cell 35):** a = 0.13789, b = −0.00485, c = 0.23532
  (R² = 0.9329).
- **Pooled 1/|m| ATM-up (cell 35):** a = 0.13885, b = −0.00458, c = 0.23801
  (R² = 0.9306).
- **ATM IV ≈ 23%** vs FH P3 reference c = 0.14877. Mild negative skew (b<0).
- **Per-day mean of per-tick coefficients (cell 28):**
  | day | a | b | c |
  |---|---|---|---|
  | 0 | 0.0465 | −0.0067 | **0.2380** |
  | 1 | 0.0179 | +0.0014 | **0.2408** |
  | 2 | 0.0344 | +0.0018 | **0.2398** |
  Per-day intercept c is very stable (range 0.238–0.241); the pooled c is
  unbiased by day mix. Per-day curvature `a` wanders 0.018–0.046.
- **Per-tick coef variability (cell 26):** mean a=0.0329 (std 0.0383), mean
  b=−0.00116 (std 0.0188), mean c=0.2396 (std 0.00231). Per-tick fits are
  noisy on `a` and `b` but tight on `c`.
- **IV-coverage filter survival (cell 16):** 100% on K=5100–5500,
  29,940/30,000 on K=5000, only **1,378 (4.6%) on K=4000 and K=4500** because
  most of the time their voucher mid is at or below intrinsic. **K=6000 and
  K=6500: zero survivors** under the EPS_EXT=0.5 filter (entirely below
  threshold across all 30k ticks).
- **Median IV by strike** (cell 17, best_mid): 4000=0.890, 4500=0.533,
  5000=0.242, 5100=0.239, 5200=0.243, 5300=0.246, 5400=0.230, 5500=0.249.
- **IV-space residuals (cell 31):** stdev pool / per-tick / lag-1 ac
  (pool / per-tick) per strike:
  | K | std_pool | std_pt | ac1_pool | ac1_pt |
  |---|---|---|---|---|
  | 5000 | 0.0081 | 0.0065 | 0.364 | **0.068** |
  | 5100 | 0.0060 | 0.0059 | 0.818 | 0.444 |
  | 5200 | 0.0034 | 0.0027 | 0.820 | 0.520 |
  | 5300 | 0.0044 | 0.0031 | 0.940 | 0.873 |
  | 5400 | 0.0038 | 0.0043 | 0.945 | 0.722 |
  | 5500 | 0.0043 | 0.0036 | 0.932 | 0.257 |
  **All lag-1 autocorrs are positive** → naive z-scalp on pooled residuals
  will fail without de-trending. Per-tick refit reduces the autocorr but
  does not flip its sign on most strikes.
- **Price-space residuals (cell 40):** stdev_pool per strike: 5000=0.567,
  5100=1.072, 5200=0.908, 5300=1.079, 5400=0.716, 5500=0.450. ATM strikes
  carry the largest price residuals (vega × IV-resid), so PnL potential is
  concentrated at the money. Median vega per strike: 5000=99.5, 5100=185.0,
  5200=267.6, 5300=267.6, 5400=193.4, 5500=109.2.

## Open questions / known limits

- **(P0)** Whether per-tick refit + simple z-scalp gives negative ac1 *and*
  positive cumulative PnL — left for N4.
- **(P0)** Whether EMA-demeaning a pooled residual (FH-style) produces
  negative ac1 — left for N4.
- **(P1)** Does using `wall_mid` as the market-price reference reduce
  residual noise? `iv_wall` column was inverted but ac1/std comparison
  versus `iv_best` not run inside N3 (left for N4 cell 28).
- **(P1)** Is `c_t` stationary? ADF/half-life for the base-IV-mean-reversion
  overlay was deferred to N4.
- **(P2)** Lowering EPS_EXT to 0.1 to recover some K=4000/4500 inversions —
  not run; flagged as cheap experiment.
- **K=6000 / K=6500 contradiction with N4 to flag.** N3's EPS_EXT=0.5 filter
  produces zero IV survivors on these strikes; N4 reports 100% IV coverage on
  the same strikes. The two notebooks use different filters; both agree the
  strikes are non-tradeable.
