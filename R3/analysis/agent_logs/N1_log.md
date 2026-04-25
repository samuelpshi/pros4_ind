# N1 — Underlying EDA log (HYDROGEL_PACK and VELVETFRUIT_EXTRACT)

Notebook: `R3/analysis/01_underlying_eda.ipynb`

## What we did

Characterized the two delta-1 products in R3 across 3 historical days (30,000
ticks per product). Loaded prices into a continuous global-tick frame, sanity-
checked the book (rows, NaN mids, one-sided books, recomputed mid match),
computed within-day tick log-returns, fitted return moments and tail
diagnostics, ran ADF and KPSS stationarity tests on both levels and returns,
computed return ACF at lags {1,2,5,10,20,50,100} and AR(1) coefficients/OU
half-lives on demeaned levels, replicated FH's Figure-8 randomization
envelope (1,000 IID Gaussian sims of rolling-100 lag-1 ACF), ran a |z|>4
single-tick jump scan, and computed lag-0 to ±10 cross-correlation between
HYDROGEL_PACK and VEV. FH-style randomization band is cached at
`cache/n1_fh_random_band.npz`.

## Findings

- **Data is clean.** All 6 (product × day) pairs = 10,000 rows; zero NaN mids,
  zero one-sided books; file `mid_price` matches recomputed `0.5*(bid+ask)` to
  float precision (cell 6).
- **Spread structure (cell 7).** HYDROGEL_PACK posts a near-fixed 16-wide
  spread (IQR 16-16, range 7-17). VEV posts a near-fixed 5-wide spread (IQR
  5-5, range 1-6). Both look MM-quoted at fixed width.
- **Return moments (cell 12).** Per-tick log-return std ≈ 2.15e-4 for both.
  Excess kurtosis 0.62 (HYDROGEL_PACK) / 0.35 (VEV) — mild. |r|>5σ rate:
  0.013% (HYDROGEL_PACK) / 0% (VEV). Zero-return rate: 18% / 25%.
- **Stationarity (cell 14).** ADF p<5e-5 on both mid levels and p≪0.001 on
  both returns. KPSS rejects stationarity-around-a-constant on both levels
  (p<0.01) — verdict: stationary around a slowly drifting mean.
- **Return ACF (cell 16).** Lag-1 ACF = **−0.129 (HYDROGEL_PACK)**,
  **−0.159 (VEV)**. With N≈30k, IID 95% CI is ±0.011, so both are 12-15σ
  negative. Lags ≥2 within noise (|ρ|<0.01). Microstructure mean-reverter
  signature.
- **Level half-life (cell 19).** Within-day demeaned mid AR(1) ρ=0.9977
  (HYDROGEL_PACK) → half-life ≈ 300 ticks (~30 s); ρ=0.9972 (VEV) → ~248
  ticks (~25 s).
- **FH randomization band (cell 22).** HYDROGEL_PACK rolling lag-1 ACF below
  random IID 5th pct on **35.1%** of ticks (above 95th pct: 0.76%). VEV below
  5th pct **46.8%**, above 95th: 0%. Real-series median rolling ACF: −0.128
  (HYDROGEL_PACK), −0.164 (VEV). Cache: `cache/n1_fh_random_band.npz`.
- **Jumps (cell 24).** HYDROGEL_PACK: 20 |z|>4 single-tick returns
  (rate 0.067%, max |z|=5.86). VEV: 16 (0.053%, max |z|=5.37). Scattered, not
  clustered — no jump-detection guardrail required.
- **HYDROGEL_PACK ⊥ VEV (cells 27-28).** Lag-0 contemporaneous correlation
  per day: 0.011 / 0.012 / −0.005, all within ±0.020 noise. All ±10 lag
  cross-correlations |ρ|<0.012, none significant. **The two delta-1 products
  are effectively independent** — separate trading modules.

## Open questions / known limits

- VEV's mean-reversion may partially come from voucher market-makers hedging.
  Worth checking VEV residual conditional on voucher trade ticks (deferred to
  N4, not actually executed there).
- KPSS rejects level stationarity around a constant — within-day mean drifts.
  Whether the drift is predictable from voucher signals (aggregate moneyness)
  was not tested.
- HYDROGEL_PACK has no co-movement with anything else — its only PnL source
  is its own microstructure. Robustness of mean PnL across days is unknown
  until backtested.
- 18-25% zero-return ticks: confirm trader handles them without spurious
  quote churn (deferred to Phase 2).
