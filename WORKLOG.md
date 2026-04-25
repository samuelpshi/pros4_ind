# R3 WORKLOG

## 2026-04-25 — Phase 1 EDA complete (N1-N4, parallel notebooks)

### What we did

Ran four EDA notebooks in parallel under `R3/analysis/`. **N1**
(`01_underlying_eda.ipynb`) characterized the two delta-1 products
(HYDROGEL_PACK and VELVETFRUIT_EXTRACT) — return moments, ADF/KPSS
stationarity, ACF/AR(1), FH-style randomization band, jump scan, and
HYDROGEL↔VEV cross-correlation. **N2** (`02_voucher_market_structure.ipynb`)
mapped the 10 voucher strikes for liquidity, spread, depth, ATM dynamics,
wall-mid vs best-mid agreement, strike triage, BS-Greek hedge feasibility
(σ=0.15 reference), and realized trade volume. **N3**
(`03_iv_smile_analysis.ipynb`) built a from-scratch BS pricer + Newton/
bisection IV solver (round-trip max abs err 4.4e-11), inverted IV per
voucher per tick (182,696 obs after EPS_EXT=0.5 filter), fitted pooled and
per-tick quadratic smiles, and persisted the IV/residual panel. **N4**
(`04_signal_validation_and_fh_features.ipynb`) tested whether the residuals
are scalpable (lag-1 ACF, FH randomization, in-sample z-scalp PnL),
replicated FH's full feature stack (wall-mid anchor, EMA demeaning, switch
gate, low-vega adjustment), tested base-IV mean reversion, ran hedge
feasibility under fitted-IV deltas, and produced the ranked Phase-2
variation list. Per-agent detail in `R3/analysis/agent_logs/N{1..4}_log.md`.

### Findings (cross-notebook synthesis)

1. **N3+N4: lag-1 autocorrelation on raw price residuals is +0.81 / +0.83 /
   +0.93 / +0.95 / +0.93 on K=5100/5200/5300/5400/5500** — strongly positive
   on every ATM-band strike, contradicting FH's P3 negative-autocorrelation
   finding. FH randomization test: real ρ₁ at the 100th percentile of the
   1,000-sim Gaussian band on every strike. **No strike passes the FH
   "significantly negative" filter on raw residuals** (N4 cells 16–17).
2. **N4: EMA20 demeaning flips the sign.** Demeaned residual ρ₁ at the ATM
   strikes: 5100 +0.82→**−0.04**, 5200 +0.86→**−0.02**, 5300 +0.95→+0.01,
   5400 +0.95→+0.09. EMA demeaning is **load-bearing for any IV scalp
   strategy on R3** (N4 cell 29). This is the single highest-priority knob
   in the Phase-2 variation list.
3. **N3: pooled hardcoded smile coefficients to bake into trader v1:**
   unweighted (a, b, c) = (**0.1578, −0.00464, 0.2322**), R² = 0.9476,
   IV residual stdev 0.0145 over 182,696 obs. Vega-weighted alternative:
   (0.1379, −0.00485, 0.2353). ATM IV ≈ 23%, well above FH's P3 reference
   c = 0.149. Cached at `R3/analysis/cache/smile_params.json`.
4. **N4 vs N3 smile-fit contradiction (flagged, not papered over).** N4's
   pooled fit (a=0.143, b=−0.0020, c=0.236, n=251,785) differs from N3's
   above. N4 does not apply the EPS_EXT=0.5 filter and includes K=6000/6500
   numerically tiny IVs (N4 reports 100% IV coverage on those strikes; N3
   reports 0%). Both notebooks agree the strikes are non-tradeable; trader
   v1 should use the **N3 fit** as the headline baseline (it's what the
   `smile_params.json` artifact points to).
5. **N2+N4: hedge cap binds before voucher position cap.** Single full-size
   long on K=5200 is +213 delta at flat-IV reference (N2) or +187 at fitted
   IV (N4) — already at/over the VEV ±200 cap. Long 300 each on
   {5100,5200,5300} = **+549 fitted delta** (N4 cell 37), not hedgeable.
   **Joint cap for the top-3 ATM portfolio: 109.4 contracts per leg** before
   |Σdelta| > 200 (N4 cell 38). VEV is the binding constraint, not the
   voucher 300-limit.
6. **N2+N3+N4: drop K=4000, 4500, 6000, 6500 from the trader.** N2
   classifies 4000/4500 as intrinsic-only and 6000/6500 as floor-pegged at
   $0.5 (cell 18). N3 finds K=4000/4500 only have 4.6% IV survival under
   EPS_EXT=0.5 and K=6000/6500 zero. N4 confirms vega ≈ 0 on the wings
   (medians 6.9 / 8.7 / 8.6 / 11.9). All three converge on a 6-strike
   active universe.
7. **N2+N4: only K=5200 and K=5300 ever play ATM.** ATM split 51.8% / 48.2%
   over 30,000 ticks; only 1.74% of ticks have an ATM-strike switch (N2
   cell 15). The trader can treat ATM as a 2-state variable flipped at
   S=5250 — primary scalp targets are 5200/5300, secondary 5100/5400.
8. **N2 vs N4: wall-mid is a wash.** N2 finds median |best_mid − wall_mid|
   = 0 with p95 ≤ 0.5 across all strikes (cell 11). N4 confirms wall-mid
   gives slightly lower residual stdev but slightly *higher* lag-1 autocorr
   on ATM strikes — the stale-quote effect cancels the noise reduction
   (cell 28). Keep wall-mid as default per FH but A/B test best-mid.
9. **N4: FH switch gate at threshold 0.7 is dead on R3.** Open 0.0% of
   ticks on every strike (cell 30). FH calibrated on P3 voucher price scale
   where typical |resid − EMA| is much larger. Either drop the gate or
   rescale (variations to test: 0.05 / 0.10 / 0.20 / off).
10. **N4: FH's low-vega regime (vega ≤ 1) is empty on R3.** 0.0% of ticks on
    every strike (cell 32). Median vega on the 6-strike active universe
    ranges 99–268. The `LOW_VEGA_THR_ADJ=0.5` adjustment must be rescaled
    (e.g., adj when vega<2 or scale linearly with 1/vega).
11. **N4: base-IV mean-reversion overlay is a real but small additive
    signal.** c_t (smile intercept ≈ ATM IV) is stationary (ADF stat=−8.25,
    p=4e-13; AR(1) φ=0.17; OU half-life ≈ 0.4 ticks). z-score scalp on
    c_t over a 500-tick window applied to the ATM voucher gave **+2,490
    cumulative in-sample PnL over ~2,326 trades** (cell 26). Implement as
    a separate module on top of cross-strike RV scalp.
12. **N1: HYDROGEL_PACK and VEV are independent microstructure mean-
    reverters.** Lag-1 return ACF = −0.129 (HYDROGEL_PACK) / −0.159 (VEV),
    both 12–15σ negative against the IID null. Level half-lives 300 / 248
    ticks (~30s / 25s). Lag-0 contemporaneous correlation by day:
    0.011 / 0.012 / −0.005 — within noise. **HYDROGEL_PACK gets its own
    standalone MM module; it is not a hedge or signal for VEV.**

### Next session starts with

Phase 2 trader implementation. Architecture decisions are anchored to the
Phase-1 numbers above; the ranked A/B sweep list is in
`R3/analysis/cache/n4_variations_to_backtest.csv`.

- **Module split.** Three independent strategy modules: (a) cross-strike RV
  scalp on vouchers (per-strike residual + EMA demean), (b) base-IV
  mean-reversion overlay on the current ATM voucher (uses c_t z-score),
  (c) HYDROGEL_PACK standalone market-maker. VEV-as-delta-hedge is its own
  routing layer, not a strategy.
- **Drop strikes 4000, 4500, 6000, 6500.** Active universe = 6 strikes:
  primary scalp 5200, 5300; secondary 5100, 5400; thin 5000, 5500.
- **Pooled smile baseline** = N3 unweighted (a, b, c) = (0.1578, −0.00464,
  0.2322) from `cache/smile_params.json`. Per-tick refit deferred to a
  later sweep.
- **EMA-demeaned pooled residual** is the v1 signal (raw residuals do not
  scalp). Open at |z|>1.5, close at |z|<0.5 as a starting point; sweep.
- **Net delta hard-capped at ±200.** Joint per-leg cap ≈ 109 when running
  3 ATM-band legs simultaneously. Trader must compute net portfolio delta
  every tick using fitted-IV deltas (not σ=0.15 flat) and clamp orders.
  Explicit VEV hedge band is one of the variations to sweep.
- **Optimization sweeps planned (in priority order from
  `n4_variations_to_backtest.csv`):**
  1. EMA demean window: no-demean / EMA5 / EMA20 / EMA50 / EMA100 /
     tuned-α EWMA.
  2. Switch gate threshold: 0.05 / 0.10 / 0.20 / off (FH's 0.7 is dead).
  3. Open/close z-thresholds: open ∈ {0.2, 0.3, 0.5, 1.0}, close ∈ {0.0,
     0.1, 0.2}.
  4. Smile fit: hardcoded pooled vs per-tick vs vega-weighted vs rolling-
     window pooled.
  5. Market anchor: wall-mid vs best-mid vs microprice.
  6. Strike triage edges: confirm 4000/4500/6000/6500 are unprofitable in
     backtest; test deep-OTM as cheap-vega-buy if vol expands.
  7. Explicit VEV delta hedge: rebalance bands {20, 50, 100} or every-100-
     ticks vs no-hedge.
  8. Base-IV MR overlay on/off.
  9. VEV underlying MR overlay on/off (uses N1's ρ₁=−0.16 finding).
  10. Low-vega threshold adjustment (FH's vega≤1 cutoff is empty; rescale).
- **Hard rules in force.** Local Rust backtester is the primary metric;
  every variant runs across all 3 historical days; mean+std PnL reported;
  no variants ship that improve mean but inflate variance without
  justification. Results to `R3/analysis/backtest_results.csv` /
  `backtest_results.md`.
