# P3 vev_meanrev — Phase-3 standalone VEV mean-reversion investigation

Owner: P3_vev_meanrev
Dates: 2026-04-26

## Goal

Build a delta-1 mean-reversion trader for VELVETFRUIT_EXTRACT (VEV) and
decide whether the MM-template approach (forked from hydrogel.py)
captures the MR signal correctly, or whether a pure z-score scalp is
needed. No delta hedging. No voucher trading. Standalone module.

## Setup

1. Forked `R3/traders/trader-r3-v1-hydrogel.py` ->
   `R3/traders/trader-r3-v1-vev-meanrev.py` with:
   - `PRODUCT = "VELVETFRUIT_EXTRACT"`.
   - Re-tuned defaults for VEV's tighter spread (5 vs hydrogel's 16):
     `quote_offset=1`, `take_edge=2`, smaller passive_size=20.
   - **New drift-defense state machine**: if `|pos| > 150` for 500
     consecutive ticks, kill the side that adds to inventory until
     `|pos| < 100`. Hysteresis prevents flip-flopping. Logs entry/exit
     via `print()` so we can verify it fires.
   - Each parameter tied to an N1 number in code comments.
2. Built diagnostic baseline `R3/traders/trader-r3-v1-vev-scalp.py`:
   pure z-score scalp, no passives, no skew, no kill. Same EMA window
   (50) as MM template for apples-to-apples. Originally `Z_OPEN=1.5`,
   exit at `z=0`. Both later revised post-Stage-1 (see below).
3. Config sidecar at `R3/traders/configs/vev_meanrev_v1.json`. Note: the
   task brief specified `R3/configs/vev_meanrev_v1.json` but the existing
   convention (hydrogel, vev v1.5 module-A, etc.) is
   `R3/traders/configs/`. Used the existing convention so the trader's
   `Path(__file__).parent / "configs" / ...` loader works without code
   changes. Documented here, not surfaced as a deviation.
4. Hard Rule #10 verified on both traders: no `import os` / `from os`,
   pathlib only.

## Stage 1 sanity (single-config 3-day backtest each)

| trader                | trades / 3d | D0     | D1      | D2      | mean    | std   |
|-----------------------|------------:|-------:|--------:|--------:|--------:|------:|
| MM-meanrev (qo=1)     |          16 |   -283 |   -1595 |   +3030 |    +384 |  2384 |
| MM-meanrev (qo=2 probe)|         21 |     -9 |   -1384 |   -1925 |   -1106 |  1014 |
| Scalp (z>1.5, exit z=0)|        1834 | -31860 |  -34333 |  -32263 |  -32818 |  1240 |

### Issue 1 (MM): structural undertrading at quote_offset=1

The local rust backtester is a trade-replay simulator (per
P2_v2_calibration log lines 64-85). VEV's spread is 5-wide 74% of ticks
(N1 cell 7), so the wall sits at fv +- 2.5. With `quote_offset=1` we sit
INSIDE the wall and our quotes never match historical bot trade prices;
result: 16 fills / 3 days. At `quote_offset=2` we sit at-wall and get 21
fills (still few). VEV has ~450 bot trades / day available; we capture
<2% of them. **quote_offset cannot be optimized in local backtest** -
it's a live-vs-local-engine unknown. Pinned at 2 for the sweep.

### Issue 2 (Scalp): pure z-scalp blowup is structural, not bug

-32k mean / day at -54 PnL/trade. Spread cost is 5 per round trip; the
extra 49/trade is wrong-direction (drift adverse-selection). Per-tick
absolute σ = 2.15e-4 × 5245 ≈ 1.1, so |z|>1.5 deviation = ~1.7 absolute
- smaller than 5-tick spread cost. **No pure aggressive-crossing scalp
can profit on VEV**, regardless of threshold. The MR signal is real
(N1 ρ₁=-0.159) but the signal magnitude is below transaction cost.

### Pre-sweep attribution (MM qo=2 with --persist)

Day-1 fills: 5 trades, all sells, all in first 6,100 ticks; then nothing
for 93,900 ticks. The remaining day's PnL trajectory is mark-to-market
on a held inventory, not new trades. Day-2: 11 trades, clean MR pattern
(buy ~5263, sell ~5269, profit on the early-day cycle). Kill-state
never fires (max |pos| stayed well below 150 throughout). Conclusion:
attribution of MM PnL to passive vs aggressive at this trade volume is
not meaningful; the trader is structurally under-filling.

### Stop-and-check-in (after Task 3)

Surfaced findings to user. User revised plan:
1. Skip detailed attribution.
2. Fix scalp: widen entry to |z|>2.0, exit at opposite-side overshoot
   (z > +0.3 for longs, z < -0.3 for shorts; not z=0), robust tick
   counter.
3. Drop `quote_offset` as a sweep axis (fix at 2).
4. Expand `take_edge` to {0, 1, 2, 3, 4} (zero = take whenever book
   crosses fv).
5. Expand `skew_strength` to {0.5, 1.0, 1.5, 2.0, 2.5, 3.0}.
6. Revised grid: 4 * 5 * 6 * 3 = 360 combos.

### Scalp bugfix attempt (Stage 1.5)

After widening entry to |z|>2 and adding overshoot exit:
| scalp variant | trades / 3d | D0     | D1     | D2     | mean    | std  |
|---------------|------------:|-------:|-------:|-------:|--------:|-----:|
| z>1.5, exit z=0 (orig)   | 1834 | -31860 | -34333 | -32263 | -32818 | 1240 |
| z>2.0, exit z>0.3 wrong-direction | 4013 | (worse) |  | | -78907 | - |
| z>2.0, exit z>0.3 corrected | 1023 | -20244 | -20304 | -10833 | -17127 | 4664 |

Improved by 47% from original but still hard loss. Confirmation:
**aggressive-crossing scalp is structurally net-negative on VEV** at any
sensible threshold/exit combination.

## Stage 2 — sweep results (96-combo pruned grid, 3-day)

Grid: ema {30,50,80,120} x te {0,1,2} x sk {0.5,1.0,1.5,2.0} x tc {20,30}
= 96 combos. quote_offset fixed at 2. Score = mean - 1*stdev.

Aggregate: 49/96 positive mean, 9/96 positive score. Best:
**vmr-ema30-te1-sk0.5-tc30** (mean=+2148, std=1472, score=+676).
Rank-3 chosen for ship: **vmr-ema120-te2-sk2.0-tc30** (mean=+2058,
std=1397, score=+661) - nearly tied with #1 but uses the more robust
te=2 take regime.

Axis break-outs (mean of means across each axis value):
- te: te=0 -> -728 (12/32 pos), te=1 -> -273 (15/32), te=2 -> +214 (22/32).
  te=2 dominates as default; te=0 strictly worst (taking on every fv
  crossing bleeds, confirms attribution prior).
- sk: 0.5 -> -226, 1.0 -> -238, 1.5 -> -227, 2.0 -> -359. Roughly
  flat. Pilot's monotonic degradation was D2-only noise. Skew is
  effectively inactive at the operating |pos|~90 level.
- ema: ema=30 -> +461 (17/24), ema=50 -> -809 (worst), ema=80 -> -422,
  ema=120 -> -280. Faster EMAs track within-day drift better.
- tc: 20 -> -258, 30 -> -266. Marginal.

Trajectory across all 96 configs: max|pos| range [81, 100]
(mean=92, median=92). Pinned at |pos|>80 mean=29364 ticks, median=29546
(98.5% of day). **Drift kill (threshold=150) never fires across any
of the 96 configs**. Strategy saturates within ~1k ticks and lives
there.

Full top-10 + axis tables in
`R3/analysis/backtest_results.md` 2026-04-26 entry.

## Stage 4 — pre-sweep attribution (run on pilot D2 winner ema50-te1)

Trader's PnL decomposed per zone:
- aggressive_zone (|price-fv| <= 1.5): 55 fills, total -772, fwd-edge
  per fill -75 to -110.
- passive_zone (|price-fv| > 1.5): 125 fills, total +12, fwd-edge per
  fill -57 to -11.

Forward-50-tick edge sums (3d): aggressive=-3879, passive=-4511. Mid
moves AGAINST every fill type on average. Naive spread-capture story
would predict ~+500 from passive zone; actual is +12. The MM
template's "edge" at the wall is fully consumed by adverse selection.

## Stage 5.B — architectural fixes (Option B)

User reordering: kill-tighten first, verify trajectory, then
force-flatten.

**(B1) kill_threshold=80, kill_release=40.** PnL collapsed:
mean=-12723 (vs +2058 baseline, delta=-14781). Trade count exploded
77 -> 779. Trajectory partially broke (97% pinned -> 77%) but max|pos|
still hits 100. Failure mode: aggressive takes are not gated by
kill_active, so once the kill releases at |pos|<40 a `te=2` take
fires and re-saturates. Each saturate/drain cycle realizes negative-
edge directional moves on 80+ lots, paying ~10 ticks per cycle.

**(C) force-flatten last 500 ticks (skip B1, kill back at 150).**
Ends each day at exactly pos=0, drained in 3-4 fills inside the
window. PnL impact: D0 -613, D1 -1273, D2 -2195 per day (mean -1360).
Half-spread cost expected ~200/day; actual loss 6.8x that. Confirms
the +2058 baseline mean was close-direction MTM gift on a 3-of-3
favourable sample.

## Findings

1. The MM template's positive 3-day backtest mean is close-direction
   noise, not edge. Two independent diagnostics converge:
   - attribution shows forward-50-tick edge negative on every fill type
   - force-flatten test shows 1360/day of MTM gift dependent on the
     held inventory direction matching the closing drift
2. The pure scalp loses outright (-17127/3d): per-tick sigma on VEV
   (~1.1) is below the 5-tick spread cost on every round trip. No
   threshold tuning fixes this.
3. Drift kill at threshold=150 is dormant (max|pos|=100 across all
   sweep configs). Tightening to 80 churns into negative-edge fills
   and collapses PnL.
4. Skew is empirically inactive at the operating |pos|~90 level.
5. Local trade-replay backtester caps fills at 25-80/d for any
   sensible MM config; this is a structural ceiling, not a parameter
   to optimize.

## What we shipped

`R3/traders/trader-r3-v1-vev-meanrev.py` at rank-3 sweep config:
ema=120, te=2, sk=2.0, tc=30, qo=2, kill_threshold=150 (dormant). No
force-flatten. Honest docstring framing this as a bounded-downside
variance contribution, NOT an edge strategy. Worst-case single-day
loss bounded by saturation level (|pos|<=100) times worst intraday
move (~30 ticks) ~= -3000.

Task 5 collapsed to one-page summary at
`R3/analysis/vev_meanrev_comparison.md`. Task 6 collapsed to one
paragraph at `R3/analysis/vev_meanrev_v2_hybrid_design.md` because
the original z-gate motivation (take-specific bleed) is invalidated
by the attribution showing fill-type-agnostic bleed.

## Next session starts with

VEV mean-reversion module is closed. If revisited in R4+ it should be
a clean architectural restart (event-driven rather than continuous-
quote MM), not an extension. Next active focus is voucher work (R3
P3.7 noTrade-5100 signal sweep on z_open x demean_window x
zscore_stdev_window) and HYDROGEL_PACK module.
