# P3 moduleA sweep — Phase-3 Module-A-only execution sweep

Owner: P3_moduleA_sweep
Dates: 2026-04-26

## Setup

1. **Forked** `R3/traders/trader-r3-v1-vev-v1.5-scalp-only.py` →
   `R3/traders/trader-r3-v1-vev-v1.5-moduleA-only.py`. Added a config
   key `enable_module_b` (default `False`). Wrapped the entire Module-B
   signal block (c_t buffering, z_c computation, target setting) in
   `if enable_b:`. When the flag is off, `module_b_targets` defaults to
   `{5200: 0, 5300: 0}` and a defensive assertion fires if a non-zero
   value ever leaks in via `traderData`.
2. **Lambda log** gained two diagnostic fields, `mB` (flag value) and
   `b_tgt` (the per-tick Module-B target dict). Both are < 50 bytes
   per tick — kept permanently rather than removed; they are the
   cleanest signal that the flag is honored at runtime.
3. **`aggressive_z_threshold` = inf** is now legal config. The trader
   accepts the JSON literal `Infinity` (Python's default `allow_nan`
   round-trip) or the string `"inf"`. With `aggressive_z = inf`, the
   `if abs(z) >= aggressive_z` escalation branch is unreachable and
   the trader is passive-only.
4. **Config files**:
   - `configs/vev_v1.5-moduleA-only-baseline.json` — saved snapshot of
     the v1.5-tuned config (pw=8, az=3.5, ms=5) with
     `enable_module_b=False`.
   - `configs/vev_v1.5-moduleA-only.json` — canonical slot the trader
     reads first; overwritten by the sweep driver each combo, copied
     from the baseline file to run a baseline.
5. **Hard Rules #10/#11 verified**: `grep -nE "import\\s*os|from os "` on the
   trader file returns zero hits (only `pathlib.Path` + `open()` for I/O).
   Day inference reads `_current_day.txt` via `pathlib`, never an env var.

## Baseline result + Module-B attribution

Run config: `pw=8, az=3.5, ms=5, enable_module_b=False`.

| variant                           | D=0    | D+1    | D+2     | mean    | trades/3d |
|-----------------------------------|-------:|-------:|--------:|--------:|----------:|
| v1.5-scalp-only tuned (B on)      |  −91.5 | −482.0 | −1643.0 | **−738.8** | 368  |
| v1.5-moduleA-only baseline (B off) |  −49.0 |  −86.5 |  −984.0 | **−373.2** | 106  |
| Δ (B off vs B on)                 |  +42.5 | +395.5 |  +659.0 | **+365.7** | −262 |

Module B's net contribution at this exact config was **−365.7 PnL/day**
(positive number = improvement when B is removed). Trade count drops
from 123/day to ~35/day. Module B was strictly hurting at the v1.5
boundary-tuned execution params; either the c_t signal is bad on this
3-day window, or the execution layer that worked for A was wrong for B.

**Validation**: across all 30,000 ticks of the 3-day baseline run, the
lambda log showed `mB=0` and `b_tgt={"5200": 0, "5300": 0}` uniformly
(via `grep -oE '\\"mB\\": [01]' combined.log | sort -u`). The defensive
assertion never fired.

## Sweep grid + rationale

Driver: `R3/analysis/sweep_v1_5_moduleA_extended.py`.
Schema-compatible with `sweep_v1_5_results.json` (key `az` is numeric;
`float('inf')` round-trips through JSON via Python's `Infinity` literal).

| axis              | values                       | reason |
|-------------------|------------------------------|--------|
| passive_wait_ticks | {8, 12, 18, 25, 35}          | v1.5 winner sat at pw=8 (max). Push past it; if pw=8 stays best, the boundary is interior of this grid. |
| aggressive_z_threshold | {3.5, 4.5, 6.0, 8.0, inf} | v1.5 winner sat at az=3.5 (max). Push past — and include `inf` (passive-only) as a diagnostic anchor. |
| max_step_size      | {1, 3, 5}                   | v1.5 winner sat at ms=5 (min). Push smaller — ms=1 trades 1 contract per tick, the smallest possible step. |

Score = `mean − 1.0·stdev` over 3 days, same as v1.5 sweep.

## Top-10 configs

Source: `R3/analysis/sweep_v1_5_moduleA_extended_results.json` (sorted
by `score = mean − 1.0·stdev`).

| rank | label                       | mean | stdev | score | trades_total |
|----:|-----------------------------|-----:|------:|------:|------------:|
| 1   | v1.5mA-pw35-az3.5-ms3       |  0.7 |   1.2 |  −0.5 |          8  |
| 2   | v1.5mA-pw35-az3.5-ms5       |  0.7 |   1.2 |  −0.5 |          8  |
| 3   | v1.5mA-pw8-azinf-ms1        |  2.3 |   5.1 |  −2.8 |          4  |
| 4   | v1.5mA-pw12-az8.0-ms1       |  2.3 |   5.1 |  −2.8 |          4  |
| 5   | v1.5mA-pw12-azinf-ms1       |  2.3 |   5.1 |  −2.8 |          4  |
| 6   | v1.5mA-pw18-az8.0-ms1       |  2.3 |   5.1 |  −2.8 |          4  |
| 7   | v1.5mA-pw18-azinf-ms1       |  2.3 |   5.1 |  −2.8 |          4  |
| 8   | v1.5mA-pw25-az8.0-ms1       |  2.3 |   5.1 |  −2.8 |          4  |
| 9   | v1.5mA-pw25-azinf-ms1       |  2.3 |   5.1 |  −2.8 |          4  |
| 10  | v1.5mA-pw35-az8.0-ms1       |  2.3 |   5.1 |  −2.8 |          4  |

Saved as `configs/vev_v1.5-moduleA-only-sweepwinner.json`
(pw=35, az=3.5, ms=3, enable_module_b=False).

### Marginal mean-PnL by axis (averaged across the other two axes)

| axis | value | mean of means | n |
|------|------:|--------------:|--:|
| pw   |  8    | −25.7  | 15 |
| pw   | 12    | −23.2  | 15 |
| pw   | 18    | −27.3  | 15 |
| pw   | 25    |   0.2  | 15 |
| pw   | 35    |   8.6  | 15 |
| az   | 3.5   | −79.7  | 15 |
| az   | 4.5   | −13.8  | 15 |
| az   | 6.0   |  13.1  | 15 |
| az   | 8.0   |   6.7  | 15 |
| az   | inf   |   6.3  | 15 |
| ms   |  1    |   1.3  | 25 |
| ms   |  3    |  −4.3  | 25 |
| ms   |  5    | −37.6  | 25 |

55/75 combos have **mean PnL > 0**. Even the worst combo of the new
sweep (pw=8, az=3.5, ms=5 — the *baseline*) is the only combo that
loses more than ≈ −250/day; the next-worst combo loses −243.

## Boundary check

| axis | v1.5 winner | new-sweep winner | new-sweep marginal best | grid-edge? |
|------|-------------|------------------|-------------------------|------------|
| pw   | 8 (max)     | 35               | 35 (max)                | edge — push higher next |
| az   | 3.5 (max)   | 3.5              | 6.0                     | interior on marginals; #1 winner is at low end of new grid (small-sample artifact) |
| ms   | 5 (min)     | 3                | 1                       | interior, but `ms=1` ties #1 on score and dominates the top-15 |

`pw` is still pinned to its max — needs another extension. `az` and
`ms` are interior on marginals. The exact #1 (pw=35, az=3.5, ms=3) is
inside an 8-trade-total regime where statistical power is essentially
zero; the marginal best (high pw, az≈6, ms=1) is the more defensible
read.

## Observations + recommendations

1. **Removing Module B re-shaped the entire execution surface.** v1.5's
   sweep concluded "max patience, max aggressive_z, min step" was
   uniquely optimal (winners on three corners); the new sweep
   concludes the same *direction* on `ms` (smaller still wins) but
   the opposite direction on `az` (higher wins) and a much higher
   optimum on `pw` (35+ vs 8). Module B was contaminating the
   measurement. Confounders matter.
2. **Module B was net −365.7 PnL/day** at the v1.5 boundary config.
   Either the c_t mean-reversion signal is bad on this 3-day window,
   or the execution params that worked for A were wrong for B. To
   re-evaluate B fairly we would have to sweep B's own thresholds with
   A held fixed, not bolt B onto A's tuned routing.
3. **The "do nothing" bound is roughly +2/day per voucher pair.** Many
   high-az/high-pw configs converge to identical behavior (the
   passive-only diagnostic anchor at `az=inf` matches `az=8.0` exactly
   for several of the top-10 configs). With the current signal at the
   current spread, the strategy is *barely* profitable when it is
   nearly inert. This is consistent with the v1.5 finding that per-trade
   edge ≤ spread paid: when we trade rarely, we don't pay the spread.
4. **Per-day variance is now tiny.** Top-15 configs all have stdev
   ≤ 14 (versus v1.5 winner's 807). The strategy is now well within
   Hard Rule #3 ("straight-line-up cumulative PnL"), but the line is
   essentially flat.
5. **Recommendation A — extend pw and tighten az.** Next sweep:
   `pw ∈ {35, 50, 75, 100}` × `az ∈ {5.0, 6.0, 7.0, 8.0}` × `ms ∈ {1, 3}`.
   The interior optimum (high pw, az≈6) suggests the patience-axis
   has more room to run.
6. **Recommendation B — pursue signal, not execution.** The execution
   sweep has bottomed out at "do nothing earns +0.7/day"; further
   refinement of pw/az/ms is rearranging deck chairs. The next
   high-impact lever is the *signal*: `z_open_threshold`,
   `ema_demean_window`, `zscore_stdev_window`, plus dropping the
   structurally-bad strikes (5000 lost the most in v1.5 diagnostics;
   re-test 5200 now that Module B isn't trading it).
7. **Recommendation C — re-evaluate Module B in isolation.** Hold
   Module A at its new winner config (pw=35, az=3.5 or marginal-best
   az=6, ms=1 or 3). Sweep Module B's own thresholds
   (`base_iv_z_open`, `base_iv_z_close`, `base_iv_position_size`,
   `base_iv_zscore_window`). Decide whether B is salvageable on its
   merits or should be deleted.

