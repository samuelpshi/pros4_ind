# N2 — Voucher Market Structure log

Notebook: `R3/analysis/02_voucher_market_structure.ipynb`

## What we did

Characterized the 10 VEV vouchers across the 3 historical days
(30,000 ticks per voucher). Loaded prices, computed per-strike data quality
(two-sidedness, spread quantiles, top/total depth) and a wall-mid vs best-mid
comparison; identified ATM strikes per tick and counted ATM switches; built
a strike-triage classification (primary/secondary/drop) using two-sidedness,
ATM-rank distance, extrinsic value, and floor-pegging; computed Black-Scholes
(σ=0.15 flat) deltas and vegas at TTE 8d→3d and worked out hedge feasibility
for several long-300 scenarios; tabulated realized trade volume per strike;
and plotted strike-vs-spot distance histograms. Cached summaries in
`cache/n2_quality.csv`, `cache/n2_wall_summary.csv`, `cache/n2_triage.csv`,
`cache/n2_trade_summary.csv`. Figures saved to
`R3/analysis/figures_n1-4/atm_tracking.png`,
`figures_n1-4/dist_from_spot.png`, `figures_n1-4/voucher_mids.png`.

## Findings

- **Two-sidedness universal (cell 5).** All 10 strikes show 100% two-sided
  market on every tick across all 3 days; spreads narrow monotonically from
  21 ticks at K=4000 to 1 tick at K=5400+.
- **VEV trades a 102-pt band [5198, 5300]** (cell 8) — under 2% of price;
  median 5249.5; stdev 15.63 across 30k ticks.
- **Only K=5200 and K=5300 ever play ATM** (cell 15): 51.8% / 48.2% split.
  ATM strike switches 523/30,000 = **1.74%** of ticks. ATM is effectively a
  2-state variable flipped at S=5250.
- **Wall-mid ≈ best-mid (cell 11).** Wall-mid available 100% of ticks on every
  strike. Wall-mid equals best-mid on 43.5% (K=4000) up to 100% (K=6000/6500)
  of ticks. Median absolute difference 0.0 across all strikes; p95 ≤ 0.5;
  max disagreement 6.0 (single outlier on K=4000).
- **Strike triage (cell 18).** Liquidity is universal; *time value* is the
  discriminator.
  - **Drop**: K=4000, 4500 (median extrinsic 0.0, intrinsic-only); K=6000,
    6500 (mid pinned at 0.5 floor across all 30,000 ticks).
  - **Primary scalp**: K=5000, 5100, 5200, 5300, 5400 (within 2 strike-rank
    steps of ATM 51.8–100% of the time; median extrinsic 4.5–47.0).
  - **Secondary**: K=5500 (within 2 strikes 48.2% of ticks; extrinsic 6.5).
- **BS Greeks at TTE=5d, σ=0.15, S=5249.5** (cell 21):
  | K | Δ | ν | Δ×300 |
  |---|---|---|---|
  | 5000 | 0.997 | 5.1 | 299.2 |
  | 5100 | 0.951 | 62.4 | 285.3 |
  | 5200 | 0.708 | 210.9 | **212.5** |
  | 5300 | 0.296 | 212.3 | 88.7 |
  | 5400 | 0.055 | 68.0 | 16.4 |
  | 5500 | 0.004 | 7.4 | 1.2 |
- **Hedge cap binds early (cell 23-24).** Single full-size long on K=5200
  alone is **+213 of delta — already over the VEV-200 cap**. Long 300 on
  both 5200 and 5300 = +301 delta; primary scalp set (5100..5400) = +603;
  full active universe (5000..5500) = +903. Per-strike max long for full
  hedge: 200 (K=4000–5000), 210 (5100), **282 (5200)**, 300 (5300+).
- **Realized trade volume thin but books quoted (cell 27).** Tradeable
  strikes 5200/5300/5400/5500 see 18 / 121 / 225 / 267 trades over 3 days
  (1-90/day). Mean trade size ~3.5 contracts. K=4000 = 464 trades but at
  intrinsic (~$1250). K=6000/6500 = 284 trades each at price $0 (dust).
- **Distance from spot (cell 30).** Only K=5200 straddles money (99.96% ITM,
  0.03% OTM, 0.01% exact ATM). K=5300 is 99.997% OTM. All other strikes are
  100% on one side of S throughout the sample.

## Open questions / known limits

- Whether 2-strike concentration (rotate between 5200/5300 at S=5250) gives
  more PnL than spreading across the 4 primary strikes is unresolved. Hedge
  math says concentration is more capital-efficient; per-strike scalp edge
  must be confirmed in N3/N4.
- Hedge feasibility numbers use σ=0.15 flat (FH writeup reference). Actual
  smile-fitted IV is ~0.23 (per N3); N4 recomputes deltas under fitted IV
  and gets slightly different numbers (e.g., median Δ at K=5200 ≈ 0.62
  rather than 0.71).
- Exact per-strike voucher caps under net-portfolio-delta ≤ 200 left to N4
  (which produced 109.4 per leg for the 3-strike top-ATM portfolio).
