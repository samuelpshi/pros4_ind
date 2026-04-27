# R3 + R4 WORKLOG

## 2026-04-26 — R4 Part 3 probes + v1 M67 sweep + v2 combined trader (HYDROGEL added)

### What we did

Wrapped up the R4 counterparty-analysis "sophisticated probes" series and shipped
the first follower trader. Ran `R4/analysis/counterparty/sophisticated2.py`
covering four probes (#3 microprice edge, #10 M67 inter-arrival pacing,
#11 pre-jump trader composition, #12 cross-day stability ranking). Wrote up
results in `R4/analysis/counterparty/FINDINGS_PART3.md` and amended the
implementation playbook in `R4/analysis/counterparty/FH_OLIVIA_BLUEPRINT.md`
(new §8 with five subsections updating the trader plan).

Verified strip-trade mechanics empirically by hand against `prices_round_4_day_1.csv`:
the original blueprint's "lift Mark 22's ask" plan was based on a misread —
actual mechanic is Mark 22 *hits* Mark 01's resting bid at price 0 on
VEV_6000/6500, so we'd queue behind Mark 01 and rarely fill. Updated §8.3 of
the blueprint to reflect this and demoted strip from priority #1 to a free
side-leg (passive 0-bid).

Coded `trader-r4-v1-velvetfruit-follow67.py` (Mark 67 follower with reactive
lift + persistent skewed MM + Mark 55 jump overlay + Mark 49 weak counter +
passive 0-bid strip leg). Backtested on full round4 dataset (3 days). Ran
five tuning variants v1.1–v1.5 sweeping target size, reactive window,
realised-edge gate, and MM on/off. Recorded all six runs in
`R4/analysis/backtest_results.md`.

### Findings

**Part 3 sophisticated probes (`FINDINGS_PART3.md`):**

- **Mark 67's per-unit close-edge on VFX is NOT stationary**: +$17/u (D1),
  +$38/u (D2), **−$8/u (D3)**. Cross-day stability ranking puts him in the
  unstable bucket. Headline +$165/fill from FINDINGS.md was D1+D2 dominated.
  → forced down-weighting in trader implementation.
- **Mark 01 ↔ Mark 22 strip is mechanical, not exploitable as front-runner**:
  all 634 fills (317 each on VEV_6000 and VEV_6500) print at price exactly
  $0.00 with day_close $0.50 → +$0.50/u for Mark 01 every time. But the
  L1 book has bid=0 (vol 14-30) and ask=1 (vol 18-30); Mark 22's small
  dumps (2-5 lots) hit Mark 01's resting bid. We can't beat M01's queue
  position by joining the bid at 0, so this is at best a passive freebie.
- **Mark 55 surfaced as low-confidence VFX jump front-runner**: correct side
  of 4 of 5 3σ jump events on VFX, despite overall bleed of −$2/u. n=5 is
  too small to size aggressively; added as overlay only when M67 silent.
- **Microprice edge probe (#3) negative**: |micro − mid| ≤ $0.41/fill across
  all traders. Drop microprice from feature pipeline.
- **M67 inter-arrival pacing probe (#10) negative**: forward edge flat across
  compressed/normal/slow buckets (~14-20 SeaShells in all three). No pacing
  signal.

**Trader v1 sweep (6 variants, all from `R4/traders/`):**

| Variant | Total PnL (3 days) | D1 / D2 / D3 | Note |
|---------|---------------------|---------------|------|
| v1 baseline | +3,484 | +2230 / +3759 / −2505 | Reference |
| v1.1 + edge gate | +3,275 | +2230 / +3714 / −2669 | Gate too late within a day |
| v1.2 wider window 5000 | +3,138 | +2246 / +3561 / −2669 | Marginal |
| v1.3 bigger target ±100/200 | +2,332 | +2119 / +3231 / −3018 | Counter-intuitive: HURTS |
| **v1.4 tighter target ±30/60** | **+3,559** | +2246 / +3550 / −2237 | **WINNER** |
| v1.5 no MM legs | +1,341 | +1290 / +1941 / −1890 | MM contributed ~$2k |

Mean PnL v1.4 = $1,186/day, std ≈ $3,000, mean/std = 0.40. Still well below
"straight-line-up" hard rule #3 standard — the D3 loss is structural to the
M67 signal, not a tuning bug. Further parameter optimization plateaus here.

**v2 combined trader (M67 + HYDROGEL_PACK + strip):**

| Day | Total | HYDROGEL | VFX | Own trades |
|-----|-------|----------|-----|------------|
| 1   | +7,244 | +4,998 | +2,246 | 21 |
| 2   | +5,269 | +1,719 | +3,550 | 100 |
| 3   | −2,358 | −121 | −2,237 | 40 |
| **Total** | **+10,155** | +6,596 | +3,559 | 161 |

v2 = v1.4's M67 leg verbatim + R3's `trader-r3-v1-hydrogel.py` ported verbatim
(EMA-50 fair value, take_edge 4, quote_offset 3, passive_size 30, skew 1.0).
VEV_4000 intentionally NOT traded (Mark 14 captures spread there, defensive
avoidance per FH_OLIVIA_BLUEPRINT §8). Strip leg still $0 (Mark 01 queue
priority blocks fills, as predicted).

Mean = $3,385/day, std = $5,071, **mean/std = 0.67** (1.7× v1.4's 0.40).
HYDROGEL contributed 65% of total PnL across 3 days. Critically, HYDROGEL was
near-zero on D3 (−$121), diluting the M67 D3 risk. v2 is the production
candidate.

### Files touched

New / authored this session:

- `R4/analysis/counterparty/FINDINGS_PART3.md`
- `R4/analysis/counterparty/sophisticated2.out` (captured stdout)
- `R4/traders/trader-r4-v1-velvetfruit-follow67.py`
- `R4/traders/trader-r4-v1.1-edge-gated.py`
- `R4/traders/trader-r4-v1.2-wider-window.py`
- `R4/traders/trader-r4-v1.3-bigger-target.py`
- `R4/traders/trader-r4-v1.4-tighter-target.py`
- `R4/traders/trader-r4-v1.5-no-mm.py`
- `R4/traders/trader-r4-v2-combined.py` (M67 + HYDROGEL + strip)
- `R4/analysis/backtest_results.md` (new file for R4)

Modified:

- `R4/analysis/counterparty/FH_OLIVIA_BLUEPRINT.md` (added §8 amendments
  reflecting Part 3 results: §8.1 down-weight M67, §8.2 add M55 overlay,
  §8.3 verify strip mechanics + downgrade, §8.4 drop microprice/pacing,
  §8.5 revised priority order).

### Next session starts with

**v2 is the production candidate** ($10,155 total / 3 days, mean $3,385,
mean/std 0.67). Two directions to consider:

1. **v2.1 — cautious VEV_4000 participation**: currently avoided defensively.
   Could try posting passive quotes inside Mark 14's spread on VEV_4000 (no
   crossing). Risk: we become Mark 38 (the patsy losing $-10.52/u every day)
   if we miscalibrate. Test would be a quick join-the-spread-only quoter,
   reverted if mean PnL drops on any day.
2. **v3 — voucher BS pricing**: bigger build. The 9 VEV strikes (4500,
   5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500) we don't trade actively
   may have edge from BS-pricing residuals. Requires a smile fit + delta
   hedging — significant work. Best done as a separate side trader rather
   than bolted onto v2.

Recommendation: ship v2 as-is, mark it as the R4 baseline, and decide v2.1
vs v3 based on remaining time before R4 close.

### Suggested commit message

```
R4 v2 combined trader: M67 follower + HYDROGEL_PACK MM = $10,155 / 3 days

Three-part progress:

1. Sophisticated probes round 2 (FINDINGS_PART3.md). Mark 67's
   per-unit edge on VELVETFRUIT is NOT stationary across days
   (+$17/+$38/-$8), forcing target down-weighting. Mark 01/22 strip
   cannot be front-run (Mark 01 queue priority on the price-0 bid).
   Mark 55 surfaced as low-confidence VFX jump front-runner (4/5
   correct on 3-sigma jumps).

2. v1 family sweep (6 variants of the M67 follower). Best is v1.4
   (tighter target +/-30/+/-60) at +3,559 across 3 days, mean/std
   0.40. Bigger target HURTS, MM legs contribute net positive, gate
   too late within a day.

3. v2 combined trader (M67 verbatim + HYDROGEL_PACK from R3 ported
   verbatim + strip). +10,155 across 3 days, mean $3,385, std
   $5,071, mean/std 0.67. HYDROGEL_PACK contributes 65% of PnL and
   critically dilutes M67 D3 risk (HG flat on D3 at -$121).
   VEV_4000 intentionally not traded (Mark 14 dominates). Strip
   captures $0 as predicted.

v2 is the R4 production candidate.

Adds FINDINGS_PART3.md, FH_OLIVIA_BLUEPRINT.md §8 amendments,
R4/analysis/backtest_results.md, 7 trader files in R4/traders/.
```

---

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

---

## 2026-04-26 — VEV mean-reversion module: full Phase-3 investigation, shipped honestly

### What we did

Standalone delta-1 mean-reversion module for VELVETFRUIT_EXTRACT.
No vouchers, no delta hedging. Owner: P3_vev_meanrev. Full per-step
detail in `R3/analysis/agent_logs/P3_vev_meanrev_log.md`.

1. Built MM-template trader `R3/traders/trader-r3-v1-vev-meanrev.py`
   (forked from hydrogel.py) with a drift-kill state machine and
   diagnostic baseline `R3/traders/trader-r3-v1-vev-scalp.py` (pure
   z-score scalp).
2. Stage-1 sanity. MM at qo=1: 16 fills/3d (wall is at fv±2.5,
   we sat inside it); pinned qo=2 going forward as a live-vs-local
   unknown rather than a sweep axis. Scalp blew up: -32k/3d at
   |z|>1.5 entry, -17k/3d after corrected |z|>2 + opposite-side
   overshoot exit. Per-tick σ on VEV (~1.1) is below the 5-tick
   spread, so no aggressive-crossing scalp can profit on this product.
3. Pre-sweep attribution at the pilot D2 winner config.
   Forward-50-tick mid edge per fill: aggressive zone (|p-fv|≤1.5)
   avg -75 to -110/fill; passive zone avg -57 to -11/fill. Passive
   zone delivered total +12 PnL across 125 fills vs ~+500 expected
   from naive spread capture. Mid moves AGAINST every fill type.
4. Stage-2 96-combo 3-day sweep
   (`R3/analysis/sweep_vev_meanrev.py`). 49/96 positive mean,
   9/96 positive score. Best by score: vmr-ema30-te1-sk0.5-tc30
   (mean=+2148, std=1472, score=+676). Selected for ship: rank-3
   vmr-ema120-te2-sk2.0-tc30 (mean=+2058, std=1397, score=+661);
   tied with #1 on score but uses the more robust te=2 take regime.
   Axis break-outs: te=2 dominates (mean +214, 22/32 positive),
   te=0 strictly worst (-728); skew flat across {0.5..2.0};
   ema=30 best regime, ema=50 worst.
5. Trajectory measurement on all 96 configs: max|pos| range [81, 100],
   median 92; pinned at |pos|>80 median = 29546 / 30000 ticks (98.5%).
   **Drift kill (threshold=150) never fires on any of the 96 configs.**
6. Architectural fix attempts (Option B, after stop-and-check):
   - **(B1) kill_threshold=80, kill_release=40** at rank-3 base. PnL
     collapsed from +2058 to -12723 mean, trade count 77 → 779.
     Failure mode: aggressive takes are not gated by kill_active, so
     the strategy churns into a saturate→drain→saturate cycle that
     pays spread cost on every leg.
   - **(C) force-flatten last 500 ticks** at rank-3 base, kill back at
     150. End-of-day pos = 0 on all 3 days (mechanism works). PnL:
     mean dropped 2058 → 698, delta -1360/day. Half-spread cost
     would explain ~200/day; actual loss was 6.8× that. Confirms the
     +2058 baseline was a 3-of-3 close-direction MTM gift on the
     held inventory.
7. Decision rule: ship rank-3 baseline as a bounded-downside variance
   contribution (NOT an edge strategy). Stripped the force-flatten
   code, finalized rank-3 config, rewrote the trader's docstring with
   honest framing referencing the attribution and force-flatten
   diagnostics. Verified `kill_threshold=150`, no `flatten_window`
   code, no `os` import. Reproduced the +2058 mean.
8. Tasks 5 and 6 collapsed to short writeups since the long form
   isn't justified by the data:
   - `R3/analysis/vev_meanrev_comparison.md` — one-page MM vs scalp
     summary with the resolved decision row.
   - `R3/analysis/vev_meanrev_v2_hybrid_design.md` — single paragraph
     on why a z-gated hybrid does not address the actual problem
     (passive-zone bleed > aggressive-zone bleed; z-gate addresses
     only ~30% of the loss).

### Findings (numbers, not vibes)

- **MM template, rank-3 ship config (ema=120, te=2, sk=2.0, tc=30,
  qo=2, kill=150)**: D0=+491, D1=+2511, D2=+3173 → mean=+2058,
  std=1397, score=+661. 77 trades / 3d. max|pos| = 95.
- **Pure scalp (corrected |z|>2 + Z_EXIT=0.3)**: D0=-20244, D1=-20304,
  D2=-10833 → mean=-17127, std=4664. 1023 trades / 3d.
- **Attribution (rank-3 family at pilot D2 winner)**: 3-day forward-
  50-tick edge sums = aggressive -3879, passive -4511. Both negative
  on every sample day.
- **(B1) tightened kill (threshold=80)**: mean=-12723, std=6231,
  trade count 779 (vs 77 baseline). Saturate/drain churn.
- **(C) force-flatten last 500 ticks**: mean=+698, std=722,
  end_pos=0/0/0 ✓. Delta vs baseline = -1360/day = 6.8× the
  half-spread cost; remaining +698 is a small mix of passive
  spread that didn't get realized adversely.
- Drift kill never fired across any of 96 sweep configs at
  threshold=150 (max|pos| ≤ 100 universally). At threshold=80 it
  fires immediately and creates the cycle above.
- Hard Rule #10 verified: no `import os` / `from os` in either trader
  file (`grep -cE "^(import|from)\s+os" → 0`).

### Files touched

New / authored this session:
- `R3/traders/trader-r3-v1-vev-meanrev.py`
- `R3/traders/trader-r3-v1-vev-scalp.py`
- `R3/traders/configs/vev_meanrev_v1.json`
- `R3/analysis/sweep_vev_meanrev.py`
- `R3/analysis/sweep_vev_meanrev.log`
- `R3/analysis/sweep_vev_meanrev_pilot.json`
- `R3/analysis/sweep_vev_meanrev_results.json`
- `R3/analysis/attribution_vev_meanrev.py`
- `R3/analysis/vev_meanrev_comparison.md`
- `R3/analysis/vev_meanrev_v2_hybrid_design.md`
- `R3/analysis/agent_logs/P3_vev_meanrev_log.md`

Modified:
- `R3/analysis/backtest_results.csv` (appended sweep + Stage 1 rows)
- `R3/analysis/backtest_results.md` (appended VEV meanrev sweep
  writeup with top 10 + axis tables + decision-question answers)

### Next session starts with

VEV mean-reversion module is **closed**. The MM-template trader is
shipped as-is at the rank-3 config; if R4 requires VEV revisited it
should be a clean architectural restart (event-driven rather than
continuous-quote MM), not an extension of this module.

Next active focus: voucher work (R3 P3.7 noTrade-5100 signal sweep on
`z_open × demean_window × zscore_stdev_window`) per the prior
WORKLOG entry, plus the HYDROGEL_PACK module which already has a
working positive-PnL strategy.

### Suggested commit message

```
Ship VEV mean-reversion module (rank-3 baseline) as honest variance contribution

96-combo Stage-2 sweep + pre-sweep attribution + force-flatten
diagnostic together show no captureable per-fill edge on VEV under
the local trade-replay engine. The rank-3 winner's positive 3-day
mean (+2058, score=+661) is a 3-of-3 close-direction MTM gift on
held inventory, not spread capture. Pure z-scalp loses outright due
to per-tick σ ~1.1 << 5-tick spread cost.

Ships trader-r3-v1-vev-meanrev.py at ema=120/te=2/sk=2.0/tc=30/
kill=150 with an honest docstring. Tasks 5 (comparison writeup) and
6 (hybrid sketch) collapsed to one-page and one-paragraph forms
respectively. Full investigation arc in P3_vev_meanrev_log.md and
WORKLOG.md.
```
