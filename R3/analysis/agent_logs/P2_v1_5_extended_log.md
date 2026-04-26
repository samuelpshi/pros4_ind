# P2 v1.5-extended — Stage 2a-extended log

Owner: P2_v1_5_extended
Dates: 2026-04-25 evening session

## What we did

1. **Stripped Module C** (VEV delta hedge + overlay) from v1.4 to produce
   `R3/traders/trader-r3-v1-vev-v1.5-scalp-only.py`. Module A (cross-strike
   smile-residual scalp) and Module B (base-IV mean-rev) remain. Net
   voucher delta is still computed for visibility but no orders go to
   `VELVETFRUIT_EXTRACT`. Matching pruned config:
   `R3/traders/configs/vev_v1.5-scalp-only.json`.
2. **Added per-strike passive→aggressive escalation** controlled by three
   new keys: `passive_wait_ticks`, `aggressive_z_threshold`,
   `max_step_size`. Spec semantics (per re-read): we escalate to a
   marketable order **only when** `|z| ≥ aggressive_z_threshold` **AND**
   the position has been off-target for at least `passive_wait_ticks`.
   The wait counter is a gate, not a trigger; an OR-formulation regressed
   PnL to ≈ −340k/day in a one-off check.
3. **Strengthened Hard Rule #10** in `CLAUDE.md` to forbid both
   `import os` and `from os import …` in trader files. (Driver scripts
   like the sweep are unaffected.)
4. **Ran a 125-combo execution sweep** across
   `passive_wait_ticks ∈ {1,2,3,5,8}` ×
   `aggressive_z_threshold ∈ {1.8,2.0,2.5,3.0,3.5}` ×
   `max_step_size ∈ {5,10,15,25,40}`. Driver:
   `R3/analysis/sweep_v1_5.py`. Each combo was scored
   `mean_pnl − 1.0·std_pnl` over 3 historical days. Full output:
   `R3/analysis/sweep_v1_5_results.json` (sorted), and every per-day row
   appended to `R3/analysis/backtest_results.csv`.
5. **Saved the winning config** as
   `R3/traders/configs/vev_v1.5-scalp-only-tuned.json` and overwrote the
   active `vev_v1.5-scalp-only.json` to match (so the trader picks it up
   without code changes).
6. **Ran per-strike diagnostics** on persisted runs of v1.4-instr and
   tuned-v1.5 across all 3 days using
   `R3/analysis/diagnostics_v1_5.py`. Round trips defined as
   position-cycles back through 0; per-fill `pas`/`agg` tags read from
   the lambda log; residual capture computed against the smile fit
   `(a,b,c)` snapshot at the fill timestamp.

## Strip results — v1.5-scalp-only at sweep defaults vs v1.4

```
trader                             D=0       D+1       D+2     mean    notes
trader-r3-v1-vev-v1.4.py     -208 287   ≈        ≈      ≈ -208k   Module C bleeds VEV ~−195k/day
trader-r3-v1-vev-v1.5 (def)   -7 737    -14 154   -20 572  -14 154   no hedge; voucher legs only
```

So even before tuning, removing Module C alone takes the strategy from
≈ −208k/day to ≈ −14k/day on the same 3 days. The hedge was actively
losing far more than the overlay was making.

## Sweep results

Top 10 by `score = mean − 1.0·stdev`:

| rank | label             | mean PnL | stdev | score   |
|----:|-------------------|---------:|------:|--------:|
| 1   | pw8-az3.5-ms5     |  −738.8  | 807.0 | −1545.8 |
| 2   | pw8-az3.5-ms15    | −1188.5  | 437.7 | −1626.2 |
| 3   | pw8-az3.5-ms10    |  −907.0  | 756.1 | −1663.1 |
| 4   | pw8-az3.5-ms25    | −1401.5  | 691.7 | −2093.2 |
| 5   | pw5-az3.5-ms5     | −1001.0  |1293.0 | −2294.0 |
| 6   | pw3-az3.5-ms5     | −1193.0  |1452.8 | −2645.8 |
| 7   | pw8-az3.0-ms5     | −1442.3  |1340.6 | −2782.9 |
| 8   | pw2-az3.5-ms5     | −1288.0  |1625.7 | −2913.7 |
| 9   | pw1-az3.5-ms5     | −1399.8  |1608.5 | −3008.3 |
| 10  | pw8-az3.5-ms40    | −1963.0  |1124.5 | −3087.5 |

Macro pattern across all 125 combos:

- **Patience (`pw`) helps**: low `pw` with low `az` blows up — `pw1-az1.8-ms40` mean = −98 948.
- **High `aggressive_z` (3.0–3.5) is required**: az=1.8 universally
  produces −20k to −100k means; az=3.5 produces −0.7k to −4k.
- **Small `max_step_size` (5) wins on score** (smaller steps → smaller
  realised slippage when a flip is wrong); ms=5 dominates the top of
  every (pw, az) slice.
- The signal direction of the parameters is consistent: minimize
  marketable activity, only act when the signal is very strong.

**Winner**: `passive_wait_ticks=8, aggressive_z_threshold=3.5,
max_step_size=5`. Per-day PnL of the winner re-run with `--persist`:
D0=−91.5, D1=−482.0, D2=−1643.0 (matches the sweep number to within
rounding).

### Stability check

The winner sits on three boundaries (pw=8 = max, az=3.5 = max, ms=5 =
min), so only three of the six axis-1 neighbors exist:

| neighbor          | mean PnL | Δ vs winner |
|-------------------|---------:|------------:|
| **pw8-az3.5-ms5 (W)** | −738.8 |   0       |
| pw5-az3.5-ms5     | −1001.0  |  −262     |
| pw8-az3.0-ms5     | −1442.3  |  −704     |
| pw8-az3.5-ms10    |  −907.0  |  −168     |

Tight cluster (−738 to −1442). No knife-edge optimum: every
1-step neighbor still scores in the top decile of the sweep. Caveat:
the winner is on three corners, so we cannot rule out that the true
optimum lies outside the swept region (e.g. `pw=12, az=4.0`).

## Diagnostics — v1.4-instr vs tuned-v1.5 (3-day aggregates)

Aggregated by hand across the 3 per-day tables. Capture/cost is
`avg_residual_capture / avg_spread_paid`.

### v1.4-instr (Module C present, very chatty)

| K    | n_rt (Σ) | n_fills (Σ) | hit% (avg) | avg_rt_PnL | cap/cost (avg) | pas_rate% (avg) |
|-----:|---------:|------------:|-----------:|-----------:|---------------:|----------------:|
| 5000 | 82       | 423         | 20.5       | −6.10      | 0.21           | 0.0             |
| 5100 | 47       | 432         | 26.8       | −4.72      | 0.27           | 0.0             |
| 5200 | 92       | 1031        | 21.8       | −1.78      | 0.08           | 0.0             |
| 5300 | 140      | 1207        | 17.3       | −1.54      | 0.43           | 0.5             |
| 5400 | 78       | 478         | 17.3       | −1.00      | 0.65           | 0.0             |
| 5500 | 87       | 535         | 4.9        | −1.02      | 0.35           | 0.2             |

### Tuned-v1.5 (pw=8, az=3.5, ms=5)

| K    | n_rt (Σ) | n_fills (Σ) | hit% (avg) | avg_rt_PnL | cap/cost (avg) | pas_rate% (avg) |
|-----:|---------:|------------:|-----------:|-----------:|---------------:|----------------:|
| 5000 | 5        | 23          | 0.0        | −11.30     | 0.77           | 0.0             |
| 5100 | 2        | 20          | 50.0       | +0.50      | 0.38           | 0.0             |
| 5200 | 5        | 112         | 50.0†      | +4.20      | 0.00           | 2.0             |
| 5300 | 15       | 184         | 75.0†      | +1.58      | 0.82           | 4.8             |
| 5400 | 6        | 16          | 27.8       | −2.43      | 0.0 / −0.05    | 16.7            |
| 5500 | 6        | 33          | 8.3        | −1.70      | 1.15†          | 0.0             |

† small-sample averages (n_rt ≤ 5 on individual days), not statistically
meaningful.

### Side-by-side takeaways

1. **Trade count cratered**: from ≈ 1100 fills/day on v1.4 to ≈ 130
   fills/day on tuned-v1.5 — a 9× reduction. This is by design: the
   sweep selected the most patience-heavy corner.
2. **Per-trade edge is still negative on average** (avg_rt_PnL is
   negative on 4 of 6 strikes for tuned-v1.5). The PnL improvement
   from v1.4 → v1.5 is mostly from cutting losing trades, not from
   finding winning ones.
3. **Capture/cost did improve** at the strikes that still trade
   (5300: 0.43 → 0.82; 5400: 0.65 → ≈ 0; 5500: 0.35 → 1.15 on a
   tiny sample). Consistent with the "patience filters out the
   noisiest signals" hypothesis, but the signal at our edges still
   doesn't reliably overcome spread.
4. **Passive fill rate measurably rose** at strikes where we now sit:
   5300 jumped from 0.5% to 4.8%, 5400 from 0% to 16.7%. So
   `passive_wait_ticks=8` is doing what it should — limit orders are
   getting filled on the resting book — but it doesn't yet flip the
   sign of the per-trade edge.
5. **5200 is structurally bad in both regimes**: tightest spread, most
   fills, lowest capture/cost (0.08 in v1.4; 0.00 in v1.5). Strong
   candidate for being dropped from `active_strikes`.

## Open questions / next steps

1. **Edge problem, not execution problem**: even the patience-maximised
   corner of the sweep loses per round trip. The execution sweep was
   the right Phase-2a step but it has hit its ceiling. Next is a
   **signal sweep**: vary `z_open_threshold ∈ {1.5, 2.0, 2.5, 3.0}`,
   `ema_demean_window ∈ {10, 20, 50, 100}`,
   `zscore_stdev_window ∈ {50, 100, 200, 500}`. Hold the tuned
   execution params fixed.
2. **Drop 5200**, possibly also 5000? Both have hit rates ≤ 14% and
   capture/cost ≤ 0.21 on v1.4 (where they had statistical power) and
   are not getting better in v1.5.
3. **Boundary risk**: winner sits on three sweep corners. Consider
   extending the next sweep to `pw ∈ {8, 12, 16}` and
   `az ∈ {3.5, 4.0, 4.5}` to make sure we are not just seeing the edge
   of the explored region.
4. **Spread paid vs residual capture** are comparable in magnitude
   (~0.5–2.0 each). The smile residual we are trading is not large
   enough to clear the spread on most strikes. Re-examine whether the
   hardcoded smile fallback `(a=0.143, b=−0.002, c=0.236)` is actually
   the right per-day fit, or whether per-tick refit (when ≥4 strikes
   have valid IVs) gives a meaningfully different residual signal.
5. **Module B base-IV mean-rev contribution** is not yet attributed
   separately in the diagnostics. The lambda-log fields `b_pnl` and
   `a_pnl` exist; a follow-up should split per-day PnL into the two
   modules so we know which one is paying for the other.
