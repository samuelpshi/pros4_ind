# VEV Mean-Reversion Comparison: MM Template vs Pure Scalp

Owner: P3_vev_meanrev
Date: 2026-04-26
Status: closed (1-page summary; original 5-section template collapsed
because the data we collected makes the long form unjustified — both
architectures showed no real per-fill edge).

## TL;DR

Both architectures fail to capture a per-fill edge on VEV. The MM
template's positive 3-day backtest mean is close-direction noise on a
favourable sample, not spread capture. The pure scalp loses outright
because it pays the 5-tick spread on every entry without a signal
strong enough to overcome it. We ship the MM template at rank-3 sweep
config as a bounded-downside variance contribution to the GOAT-phase
basket, and we do not iterate further on either approach.

## Headline numbers

| metric (3-day, all 3 sample days)     | MM template (rank-3 winner) | Pure scalp (corrected)  |
|---------------------------------------|----------------------------:|------------------------:|
| config                                | ema=120, te=2, sk=2.0, tc=30 | Z_OPEN=2.0, Z_EXIT=0.3 |
| D0 PnL                                |                       +491  |                 -20244  |
| D1 PnL                                |                      +2511  |                 -20304  |
| D2 PnL                                |                      +3173  |                 -10833  |
| mean across 3 days                    |                      +2058  |                 -17127  |
| stdev across 3 days                   |                       1397  |                   4664  |
| score (mean - stdev)                  |                       +661  |                 -21791  |
| trades / 3d                           |                         77  |                   1023  |
| max \|pos\| reached (3-day)             |                         95  |                     90  |
| time pinned at \|pos\|>80                |                  29208 ticks (97%)  |        n/a (smaller)  |
| drift-kill activations (MM only)      |                          0  |                    n/a  |

Source: `R3/analysis/sweep_vev_meanrev_results.json` (rank-3 row),
`R3/analysis/agent_logs/P3_vev_meanrev_log.md` Stage 1.5 table.

## Why the MM template's positive mean is not edge

Two independent diagnostics converge on the same answer.

**Diagnostic 1 — pre-sweep attribution at the pilot D2 winner.** Each
own_trade tagged `aggressive_zone` if `|price - fv| <= 1.5`, else
`passive_zone`. Forward-50-tick mid edge per fill:

| zone        | fills (3d) | total PnL | avg fwd edge |
|-------------|-----------:|----------:|-------------:|
| aggressive  |         55 |      -772 |       -75/fill on D0, -110 on D1, -61 on D2 |
| passive     |        125 |       +12 |       -57/fill on D0, -40 on D1, -11 on D2 |

Passive zone delivers ~zero PnL despite 125 fills (a clean spread-
capture story would predict ~+500). Aggressive zone is strictly
negative. Forward-edge sums (3-day): aggressive = -3879, passive =
-4511. The mid moves AGAINST our fill on average, in both zones.

**Diagnostic 2 — Option C force-flatten test.** Same rank-3 config,
plus a "drain to flat in last 500 ticks" rule that aggressively closes
the held book. End-of-day position goes from saturated to exactly 0
on all 3 days; mechanical change works as intended. PnL impact:

| day | baseline (held) | force-flatten | delta |
|----:|----------------:|--------------:|------:|
|   0 |            +491 |          -122 |  -613 |
|   1 |           +2511 |         +1238 | -1273 |
|   2 |           +3173 |          +978 | -2195 |
|     |                 |          mean |  -1360 / day |

If the strategy were capturing real spread or MR edge, force-flatten
would only cost the half-spread per close: 0.5 * 5 ticks * ~80 lots =
~200 per day. We lost 1360/day — **6.8× the half-spread cost**. The
excess delta is the closing-mid MTM gift on a held inventory that
happened to drift favourably on all 3 days. The "+2058 mean" was
substantially a 3-of-3 lucky-direction run.

## Why the scalp loses

Per-tick absolute sigma on VEV is ~1.1 (= 2.15e-4 * 5245), and the
spread cost on every aggressive round trip is 5 ticks. A |z|>2 entry
captures ~2.2 abs of deviation in the best case — less than half the
spread it pays. Even with the corrected `Z_EXIT=0.3` opposite-side
overshoot exit, mean PnL = -17127 / 3d. The MR signal that N1
identified (lag-1 ACF = -0.159, half-life 248 ticks) is real but its
magnitude is structurally below transaction cost. No threshold tuning
fixes this; it's an architecture-level constraint of the product.

## Decision table (now resolved)

| condition                                                            | implies                                                          |
|----------------------------------------------------------------------|------------------------------------------------------------------|
| Scalp PnL ≈ MM's passive PnL                                         | MM captures MR correctly, drop scalp, ship MM                    |
| Scalp PnL >> MM's passive PnL                                        | MM bleeding to adverse selection on passives, tighten or ship scalp |
| MM wins both mean & var                                              | spread capture is the real edge, MR incidental, widen quotes     |
| **Scalp negative, MM positive only via close-direction MTM** ✓       | **Neither captures edge. Ship MM as variance contribution; do not pursue scalp.** |

## What we ship

`R3/traders/trader-r3-v1-vev-meanrev.py` at config
`R3/traders/configs/vev_meanrev_v1.json` (rank-3: ema=120, te=2,
sk=2.0, tc=30, kill=150). Single-day max-loss bound is set by the
saturation level (|pos| ≤ 100 across all 96 swept configs) times the
worst sample-day intraday move (~30 ticks) ≈ -3000. Acceptable as a
bounded-variance contribution alongside the voucher modules.

## Caveats

1. **Trade-replay limitation, again.** Local backtester only matches
   our orders against historical bot trade prices, capping fills at
   ~25-80/d for any sensible MM config. The IMC live engine fills
   against snapshot books and may produce a materially different
   distribution of outcomes. We documented this conclusion under the
   local engine; we did not validate it on live.
2. **3-day sample.** Stdev with N=3 is barely an estimate. The
   close-direction-favourable read is consistent with attribution and
   force-flatten but a different 3-day sample could shift the picture.
3. **Within-day drift not modeled in scalp's signal.** N1 KPSS
   rejects level stationarity; faster drift than EMA-50 causes
   systematic wrong-direction entries. Did not retune the scalp on
   this axis because the spread-cost arithmetic alone rules it out.
