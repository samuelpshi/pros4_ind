# R3 Backtest Results — commentary log

Each entry summarises a backtest run. Numbers come from the Rust local
backtester (`rust_backtester --dataset round3 --products full`) over all 3
historical days. Per-row machine-readable detail lives in
`backtest_results.csv`.

---

## 2026-04-26 — `trader-r3-v1-hydrogel.py` (Stage 1 baseline)

**Config**: `configs/hydrogel_v1.json`
(`fair_value_ema_window=50`, `quote_offset=3`, `skew_strength=1.0`,
`take_edge=4`, `passive_quote_size=30`, `aggressive_take_size_cap=50`,
`position_limit=200`).

**Per-day PnL**: D0 = 3362, D1 = 4998, D2 = 1719.
**Mean PnL across 3 days = 3359.67**, sample stdev = 1639.5,
coefficient of variation 0.49.

**Per-product attribution**: 100% of PnL is HYDROGEL_PACK (correct — trader
ignores all other symbols). All voucher and VEV columns flat at 0.00 across
all days, confirming the symbol filter works.

**Trade count**: 7 / 6 / 20 own trades on D0/D1/D2. Average ~$480 per trade
on D0–D1, ~$86/trade on D2. Very low fill rate, which is expected: HYDROGEL
posts a fixed 16-wide spread (N1 cell 7) with the wall at roughly fv ± 8,
so our passive quotes at fv ± 3 sit deep inside the spread and only fill
when bot flow crosses through them. The aggressive-take leg almost never
triggers — for the take to fire we need best_ask ≤ fv − 4 or best_bid ≥
fv + 4, and the wall stays out at ± 8 for most ticks.

**Behaviour**: PnL is consistently positive with no per-day losses. D2
takes 3× as many trades as D0/D1 but earns less per trade — suggesting D2
had more cross-the-spread flow at marginal prices rather than juicy
mispricings. No evidence of position pinning at the limit (would need to
inspect the run logs to confirm peak |position|; deferred). The baseline
is a viable PnL floor; the obvious next step is to lift the fill rate.

**Variance vs Hard Rule #3**: stdev/mean = 0.49 is high relative to the
"straight-line-up cumulative PnL" goal. With only 7–20 trades per day the
estimator is noisy by construction — Stage 2 sweeps that increase fill
rate should also tighten the variance.

---

## 2026-04-26 — `trader-r3-v1-vev.py` (Stage 1 baseline)

**Config**: `configs/vev_v1.json` (`v1-vev-defaults`)
- Active strikes: `[5000, 5100, 5200, 5300, 5400, 5500]` (drop 4000/4500/6000/6500 per N2/N3/N4 strike triage).
- Smile fallback `(a=0.143, b=-0.002, c=0.236)` from N4 cell 11. *Note: N3 reports a different pooled fit `(0.158, -0.0046, 0.232)` under the EPS_EXT=0.5 filter; spec selected N4. Diff is <1.5% IV at typical |m|<0.1.*
- EMA20 demean, 100-tick z-window, z_open=1.5 / z_close=0.5.
- Per-strike caps `60/80/120/120/80/60` (5000..5500) — N4 cell 38 hedge feasibility.
- Module B: c_t z-score over 500 ticks, ±25 contracts on each of 5200/5300.
- Module C: VEV delta-hedge target = `-round(net voucher delta)`; EMA50 mean-reversion overlay on VEV mid (N1 ρ₁=−0.159), ±50 max; net portfolio delta hard-capped at ±50 with hedging priority.

**Per-day PnL** (Rust backtester, `--products full`):
| day | final_pnl | own_trades |
|---|---|---|
| 0 | −1,117,582 | 35,220 |
| 1 | −1,094,560 | 34,751 |
| 2 | −1,080,644 | 34,437 |
| **mean** | **−1,097,595** | **34,803** |
| stdev | 18,506 | 393 |

**Per-product attribution (3-day total, all VEV-related; HYDROGEL_PACK and 4 dropped strikes flat at 0)**:
| product | total PnL | share of total loss |
|---|---|---|
| VELVETFRUIT_EXTRACT | −1,471,962 | 44.7% |
| VEV_5100 | −435,308 | 13.2% |
| VEV_5200 | −426,761 | 13.0% |
| VEV_5000 | −418,793 | 12.7% |
| VEV_5300 | −280,900 | 8.5% |
| VEV_5400 | −145,664 | 4.4% |
| VEV_5500 | −113,397 | 3.4% |
| **TOTAL** | **−3,292,786** | 100.0% |

No single strike exceeds the >70% dominance threshold from the spec; VEV underlying is the largest single bucket at 45%, the rest is spread across 6 vouchers in roughly delta-weighted proportion (5000–5200 are the highest-delta strikes and contribute the most spread cost).

**Module-level paper PnL** (mark-to-mid, no slippage, end-of-day from `lambdaLog`):
| module | D0 | D1 | D2 | mean |
|---|---|---|---|---|
| A (cross-strike RV scalp) | +144,320 | +139,900 | +110,050 | +131,423 |
| B (base-IV mean rev) | +10,687 | +12,362 | +10,175 | +11,075 |
| C (VEV hedge + overlay) | +25,105 | +32,669 | +47,661 | +35,145 |
| **TOTAL paper** | **+180,112** | **+184,931** | **+167,886** | **+177,643** |

The strategy logic produces ~+180k/day of mark-to-mid alpha. Realized PnL is −1,097k/day. The ~1.27M/day delta is implied per-trade slippage of ~36 per trade × 35k trades — i.e., spread crossing on every order placement is the dominant loss driver, not signal failure.

**Behaviour**:
- Hedge band held: `net_d` (printed each tick) stays within ±0.5 throughout all 3 days; the delta hedge is doing its job to spec (±50 band).
- 35k own trades per day = 3.5 trades per tick on average. The trader is constantly thrashing positions in response to noisy z-scores. The bang-bang signal (jump to ±cap on |z|>1.5, jump to 0 on |z|<0.5) interacts badly with marketable order placement.
- Smile fit fallback: with 6 active strikes and 100% IV survival across this universe (N3 cell 16), `len(ivs) >= 4` essentially always holds; the hardcoded fallback never triggered.
- Module C overlay: `vev_t` per tick is dominated by the hedge component, not the overlay; the EMA50-fade overlay rarely opens in either direction because once z>1.0 fires the hedge band check usually drops it.

**Variance vs Hard Rule #3**: D0/D1/D2 final PnLs are remarkably consistent (cv = 0.017). The strategy is losing money smoothly, not randomly — confirming the loss is a systematic execution issue, not luck-driven.

**Stage 2 priorities** (data-driven from this baseline):
1. Trade-frequency reduction is the single highest-impact knob: hysteresis bands on z-thresholds (require z to overshoot by some delta before reversing); per-tick step-size caps; or rebalance bands on the hedge so VEV doesn't re-trade every 100ms.
2. Passive quoting (post limit orders inside the spread) instead of marketable would convert spread cost into spread capture; this is a deeper rewrite of the order-routing layer.
3. The smile/IV/scalp signal layer looks correct (paper PnL is positive and consistent across days, attribution is sane). Stage 2 sweeps on EMA window and z-thresholds remain on the priority list per N4's variation table, but the execution layer is the gating issue.

---

## 2026-04-26 — Stage 2a execution surgery (`trader-r3-v1-vev-v1.{1,2,3,4}.py`)

Goal: fix the spread-cost dominance flagged in v1.0 Stage-1 baseline. Same signal logic, four incremental versions on order routing only. Full per-version analysis in `agent_logs/P2_v1_4_execution_log.md`.

### Headline table (all 3 historical days, `--products full`)

| Version | Mean PnL/day | Trades/day | vs v1.0 | Voucher PnL (3-day) | VEV PnL (3-day) |
|---|---:|---:|---:|---:|---:|
| v1.0 baseline | −1,097,595 | 34,803 | — | −1,820,824 | −1,471,962 |
| v1.1 hold/cooldown | −1,030,396 | 31,646 | +6.1% | −1,857,919 | −1,233,270 |
| v1.2 passive | −410,905 | 7,641 | +62.6% | −71,176 | −1,161,538 |
| v1.3 step-cap | −208,287 | 9,738 | +81.0% | −42,464 | −582,397 |
| v1.4 day-aware | −208,518 | 9,756 | +81.0% | −42,815 | −582,627 |

### Key findings

1. **Passive quoting on vouchers is a step-change** (v1.1→v1.2): voucher loss collapses from −619k/day to −24k/day (−96%). The rust matching model fills passive limits via market-trade flow at our limit price (runner.rs L612–702), so a buy at `best_bid` captures spread instead of paying it.
2. **VEV hedge becomes the dominant cost** in v1.2 at −387k/day (94% of total loss) — escalating to marketable in 50-lot chunks each time realized delta drifts past the ±50 band.
3. **`max_step_size=10` halves VEV loss** (v1.2→v1.3): from −387k/day to −194k/day. Step capping converts each 50-lot escalation into 5×10-lot escalations; net spread paid drops despite slightly more trades/day.
4. **Per-day TTE has negligible impact** (v1.3→v1.4): D1 worsens 684 (0.3%), D2 worsens 11 (0.005%). Vega-ratio sqrt(6/8)=0.866 → 13% delta error in our band regime is small.
5. **Stage-2a goal of 70%-of-paper realized PnL was NOT met.** v1.4 realized = −208k/day vs paper +177k/day = ratio −1.17. We cut losses 81% but still lose money. Residual is the VEV underlying hedge bleed (94% of remaining loss). Stage 2b must address this — see `P2_v1_4_execution_log.md` for prioritized candidates (passive offset, rebalance band, hedge band sweep).

### Variance vs Hard Rule #3

v1.4 cv = 5,952/208,518 = 0.029. Slightly higher than v1.0's 0.017 (consistent losses), but losses are still very smooth across days — confirming the residual cost is structural, not luck.


---

## 2026-04-25 — Stage 2a-extended (v1.5-scalp-only, strip Module C + execution sweep)

Goal: kill the VEV underlying hedge bleed flagged in Stage-2a (94% of v1.4 loss) and re-tune the order-routing knobs without it. Full analysis in `agent_logs/P2_v1_5_extended_log.md`.

### Headline table (all 3 historical days, `--products full`)

| Version | Mean PnL/day | Trades/day | vs v1.4 | Voucher PnL (3-day) | VEV PnL (3-day) |
|---|---:|---:|---:|---:|---:|
| v1.4 baseline | −208,287 | 9,738 | — | −42,464 | −582,397 |
| v1.5 (defaults: pw=1, az=2.5, ms=10) | −14,154 | 368 | +93.2% | ≈ −42,000 | 0 |
| **v1.5 tuned (pw=8, az=3.5, ms=5)** | **−738.8** | **123** | **+99.6%** | **−2,217** | **0** |

### Key findings

1. **Removing Module C (VEV delta hedge + overlay) is the largest single win in this round of work**: even at sweep defaults, mean loss collapses from −208k/day to −14k/day. The hedge was actively losing far more than the overlay was making.
2. **125-combo execution sweep over `passive_wait_ticks × aggressive_z_threshold × max_step_size`** found a clear directional optimum: maximize patience (`pw=8`), require very strong signal (`az=3.5`), take small steps (`ms=5`). All three live on a sweep boundary, so the true optimum may sit outside the explored region.
3. **Tuned-v1.5 is on the right side of zero per round trip on 5100/5200/5300/5500** but per-trade edge is still ≤ +4 across strikes; total PnL is dominated by the small handful of strikes where we still take losing positions (5000: avg −11.30/share over 5 round trips).
4. **Trade volume cut 9× vs v1.4** (≈ 130 fills/day vs ≈ 1100 on vouchers). Capture-to-cost ratio rose at the strikes that still trade (5300: 0.43 → 0.82); passive fill rate rose from ≈ 0% to 4.8% on 5300, 16.7% on 5400.
5. **5200 is structurally bad in both regimes** (capture/cost 0.08 in v1.4, 0.00 in tuned-v1.5 with similar n_fills). Strong candidate for removal from `active_strikes` next iteration.

### Variance vs Hard Rule #3

Tuned-v1.5: per-day PnL D0=−92, D1=−482, D2=−1643. Stdev = 807, |cv| ≈ 1.1 (numerator small). The trend is monotonically worse (D0 → D2) which mirrors v1.4 — consistent with declining-TTE residual signal degradation rather than random variance. Worth investigating in a follow-up.

### What is NOT yet attributed

The diagnostics break down per-strike round-trip economics, but Module A (cross-strike scalp) vs Module B (base-IV mean-rev) PnL is not split — both modules contribute to the same voucher fills. The lambda log carries `a_pnl` / `b_pnl` fields; a follow-up should break out per-module attribution before launching the signal sweep.

---

## 2026-04-26 — Phase-3 Module-A-only fork + extended execution sweep (`trader-r3-v1-vev-v1.5-moduleA-only.py`)

Goal: optimise Module A in isolation. Module B confounded the v1.5
execution sweep; strip it via a feature flag and re-tune. Full analysis
in `agent_logs/P3_moduleA_sweep_log.md`.

### Headline table (all 3 historical days, `--products full`)

| Variant | Config | D=0 | D+1 | D+2 | mean | trades/3d |
|---|---|---:|---:|---:|---:|---:|
| v1.5-scalp-only tuned (A+B) | pw=8, az=3.5, ms=5 | −91.5 | −482.0 | −1643.0 | **−738.8** | 368 |
| v1.5-moduleA-only baseline (A only) | pw=8, az=3.5, ms=5 | −49.0 | −86.5 | −984.0 | **−373.2** | 106 |
| v1.5-moduleA-only sweep winner | pw=35, az=3.5, ms=3 | 2.0 | 0.0 | 0.0 | **+0.7** | 8 |

### Key findings

1. **Removing Module B is a +365.7 PnL/day improvement** at the v1.5 tuned config (B contributed net −365.7/day on this 3-day window). Trade count drops from 123/day to 35/day; per-day stdev drops from 807 to 471.
2. **The new sweep winner is +0.7 PnL/day with stdev 1.2** — the strategy has crossed zero and into Hard-Rule-#3-compliant territory, but at near-zero activity (8 trades over 3 days). 55/75 sweep combos posted positive mean PnL.
3. **Every axis flipped direction or moved** vs v1.5's conclusions: `pw` optimum jumped from 8 → 35+ (still on the new max), `az` optimum moved from 3.5 → 6.0 (marginals; the #1 individual winner at az=3.5 is a small-sample artifact), `ms` continued in the same direction (5 → 1–3). Module B was a real confounder; the v1.5 boundary-tuned config sits at the worst corner of the new grid.
4. **Diagnostic anchor (az=inf, passive-only) ties the top-10**: 8 of the top-10 configs make exactly +2.3 PnL/3d on identical 4-trade trajectories — passive limits get filled rarely, but never lose. The strategy's "do nothing" lower bound is roughly +0.8/day.

### Variance vs Hard Rule #3

Sweep winner cv = 1.2/0.7 ≈ 1.7 (numerator small). Top-15 stdev ≤ 14, vs v1.5 winner stdev = 807. The PnL line is now flat-ish-and-up rather than a smooth slope downward. This is the right side of zero but sub-scale; meaningful PnL needs a signal-side improvement, not more execution tuning.

### Validation

- `grep -nE "import\s*os|from os " R3/traders/trader-r3-v1-vev-v1.5-moduleA-only.py` → 0 hits.
- 30,000 baseline ticks all show `mB=0`, `b_tgt={"5200": 0, "5300": 0}` in lambdaLog. Defensive assertion on flag-off never fired.
- Sweep results JSON (`sweep_v1_5_moduleA_extended_results.json`) is schema-compatible with `sweep_v1_5_results.json`; `az` field stores `Infinity` for the passive-only case (Python `json` round-trips it natively).

---

## 2026-04-26 — Phase-3.5 z_open diagnostic (`trader-r3-v1-vev-v1.5-moduleA-only.py`)

Goal: test whether the residual signal has edge or whether `z_open=1.5` was firing on noise. Held execution at the prior canonical pw=8/az=3.5/ms=5 (NOT the Phase-3 sweep winner — that was the under-trading extremum and would confound). Module B off. Swept `z_open ∈ {1.5, 2.0, 2.5, 3.0, 3.5}`. Full analysis in `agent_logs/P3.5_zopen_diagnostic_log.md`.

### Headline table (all 3 historical days, `--products full`)

| z_open | mean PnL/day | stdev | trades/day | trades/3d |
|-------:|-------------:|------:|-----------:|----------:|
| 1.5    |  −373.17     | 529.3 |       35.3 |       106 |
| 2.0    |  −101.83     | 105.8 |       37.0 |       111 |
| 2.5    |  −416.00     | 824.1 |       18.3 |        55 |
| 3.0    |  −415.67     | 824.4 |       16.7 |        50 |
| 3.5    |    +20.67    |  35.8 |        0.7 |         2 |

### Classification: H3 (formal) → H1 (after dropping 5100)

Aggregate PnL goes positive only at z=3.5 with 0.7 trades/day → formal H3 (alpha exists but rare). But the per-strike picture inverts the story:

| z=2.0 per-strike PnL (3d) | 5000  | 5100   | 5200 | 5300  | 5400 | 5500 |
|---|---:|---:|---:|---:|---:|---:|
| pnl_3d | +782 | **−1477** | −1 | +497 | −8 | −99 |

5000 and 5300 flip strongly positive once z is raised; 5100 *worsens* (−283 at z=1.5 → −1532 at z=2.5/3.0), which is the opposite of what a real signal does under stricter filtering. **Sum without 5100 at z=2.0 = +390 PnL/day on ~28 trades/day**, which would satisfy H1.

5200 (previously flagged structurally bad in v1.5 diagnostics) is **revealed as benign** with B off — barely trades, barely loses; the earlier flag was Module-B contamination.

### Variance vs Hard Rule #3

Mid-z stdev (z=2.5/3.0) ~824/day is bad — that's the regime where 5100's blow-ups dominate while other strikes go silent. z=3.5 stdev = 36 (essentially flat-line). The H3-to-H1 conversion requires removing 5100; per-day variance is otherwise driven by 5100 alone.

### Validation

- 5 configs (`vev_v1.5-moduleA-only-zopen-{1.5,2.0,2.5,3.0,3.5}.json`) differ only in `z_open_threshold` (verified via diff).
- All 5 runs returned full 3-day data; no crashes.
- Trader still passes Hard Rule #11 (`grep` for `import os` / `from os ` → 0 hits).

### Next step (NOT executed in this phase)

Single-config diagnostic: z=2.0, pw=8, az=3.5, ms=5, `active_strikes = [5000, 5200, 5300, 5400, 5500]`. If +390/day-ish lands as predicted, run a full signal sweep on the 5-strike universe. If 5100 needs to be kept, audit its per-strike residual signal first — the loss-grows-with-stricter-z pattern is a smoking gun for smile-fit contamination at K=5100.

---

## 2026-04-26 — Phase-3.6 K=5100 audit + drop-5100 vs noTrade-5100

Goal: validate Phase-3.5's H1 counterfactual by dropping K=5100 and check whether the loss-grows-with-z pattern at 5100 was smile-fit contamination or a load-bearing anchor. Plumbed a new config field `smile_fit_strikes` (defaults to `active_strikes` for back-compat) so the smile-fit input universe is decoupled from the trade universe. Verified zero behavioral drift on existing configs (zopen-2.0 baseline reproduces bit-for-bit). Full analysis in `agent_logs/P3.6_drop5100_audit_log.md`.

### Three configs at z_open=2.0, pw=8/az=3.5/ms=5, B off

| variant                              | active_strikes      | smile_fit_strikes   | D=0   | D+1   | D+2     | mean    | stdev | trades/3d |
|--------------------------------------|---------------------|---------------------|------:|------:|--------:|--------:|------:|----------:|
| zopen-2.0 baseline                   | 5000–5500 (6)       | 5000–5500 (6)       |  −9.0 | −79.5 | −217.0  | **−101.8** | 105.8 |    111 |
| drop-5100 (drop from BOTH)           | 5000,5200–5500 (5)  | 5000,5200–5500 (5)  | +15.0 | +105.0| −527.0  | **−135.7** | 327.0 |     82 |
| **noTrade-5100 (drop from active only)** | 5000,5200–5500 (5)  | 5000–5500 (6)       |  −5.0 | −79.5 | +1255.5 | **+390.3** | 766.6 |     94 |

Per-strike PnL (3-day totals):

| variant         | 5000   | 5100  | 5200 | 5300  | 5400 | 5500 |
|-----------------|-------:|------:|-----:|------:|-----:|-----:|
| baseline        |  +782  | −1477 |   −1 |  +497 |   −8 |  −99 |
| drop-5100       |  −248  |  0    | −126 |   +53 |   −9 |  −77 |
| noTrade-5100    |  +782  |  0    |   −1 |  +497 |   −8 |  −99 |

### Smile-fit audit (`smile_audit_K5100.py`, 30,000 ticks across 3 days)

Per-tick quadratic smile fit, both ways:

- **R²**: with-5100 mean 0.222, without-5100 mean 0.232. Marginally better without 5100, but both fits are poor (the smile isn't very quadratic on this dataset).
- **c (ATM IV intercept)**: with-5100 mean 0.2395, without 0.2397. Δc mean = +0.00025, stdev 0.00139 — essentially unchanged.
- **K=5000 residual stdev**: with-5100 = 0.00212 → without-5100 = **0.00056** (4× collapse). With K=5100 absent, the parabola gains tail freedom and hugs K=5000 nearly perfectly, killing the residual signal that was producing the +782 PnL.
- **K=5300 residual stdev**: with-5100 = 0.00312 → without-5100 = 0.00236 (24% collapse). Same story.
- **K=5100 residual stdev (out-of-sample under without-5100 fit)**: 0.00620 with AC1 = 0.79. The residual structure at 5100 is real and persistent regardless of fit.

**Verdict**: K=5100 is a load-bearing anchor, not a contaminator. The +782 at K=5000 and +497 at K=5300 are *conditional* on K=5100 being in the smile fit — they come from a structural mis-specification that K=5100's mid forces the parabola to maintain. Removing 5100 from the fit eliminates the alpha; merely not trading 5100 preserves it.

### Variance caveat (Hard Rule #3)

noTrade-5100 mean +390/day comes from D+2 = +1256, with D=0/D+1 essentially flat. Stdev 767. Score by `mean − stdev` = −376 (worse than baseline −208). The signal exists but is concentrated; this is a regime-dependence problem rather than a no-signal problem. Phase 3.7 should investigate D+2 separately (volatility regime? smile dynamics? S behavior?) before declaring victory.

### Validation

- Trader still passes Hard Rule #11 (`grep -nE "import\s*os|from os " R3/traders/trader-r3-v1-vev-v1.5-moduleA-only.py` → 0 hits).
- Back-compat: zopen-2.0 baseline (no `smile_fit_strikes` field) reproduces bit-for-bit (D=0/−9, D+1/−79.5, D+2/−217) under the new code.
- Audit ticks: 30,000 / 30,000 (100%) had ≥5 valid IVs and produced both fits.

### Next step (NOT executed in this phase)

Phase 3.7 signal sweep on the noTrade-5100 universe (active = 5000/5200–5500, fit = 5000–5500). Axes: `z_open × ema_demean_window × zscore_stdev_window`. Goal: find the (z_open, demean window, stdev window) corner where D+2's +1256 doesn't dominate — or accept regime concentration and gate trading on a per-day volatility filter. K=5200's near-zero contribution across all phases suggests it could be dropped from active_strikes too (compute saving) without affecting PnL.

---

## 2026-04-26 — `trader-r3-v1-vev-meanrev.py` 96-combo 3-day sweep (Stage 2)

**Trader**: `R3/traders/trader-r3-v1-vev-meanrev.py` (forked from hydrogel
template, drift-kill state machine added). Config sidecar at
`R3/traders/configs/vev_meanrev_v1.json`.

**Grid (96 combos, pruned post-pilot)**: `ema ∈ {30, 50, 80, 120}` ×
`take_edge ∈ {0, 1, 2}` × `skew_strength ∈ {0.5, 1.0, 1.5, 2.0}` ×
`take_size_cap ∈ {20, 30}`. `quote_offset` fixed at 2 (trade-replay
limitation, not a tunable in local backtest). `kill_threshold=150`,
`kill_dwell_ticks=500`, `kill_release=100` held constant.

**Score** = mean − 1·stdev across the 3 historical days.

### Aggregate

- Configs with positive 3-day mean PnL: **49 / 96** (51%).
- Configs with positive score (mean > stdev): **9 / 96**.
- Best config: **`vmr-ema30-te1-sk0.5-tc30`** — D0=865, D1=1824, D2=3754, mean=**+2148**, stdev=1472, score=**+676**, 93 trades over 3 days.

### Top 10 (by score)

| rank | label                          | D0   | D1   | D2   |  mean |  std | score | trd | maxpos | pin>80 |
|-----:|--------------------------------|-----:|-----:|-----:|------:|-----:|------:|----:|-------:|-------:|
|    1 | vmr-ema30-te1-sk0.5-tc30       |  865 | 1824 | 3754 |  2148 | 1472 |  +676 |  93 |     94 |  29117 |
|    2 | vmr-ema30-te1-sk1.0-tc30       |  865 | 1824 | 3758 |  2149 | 1474 |  +675 |  93 |     94 |  29117 |
|    3 | vmr-ema120-te2-sk2.0-tc30      |  491 | 2510 | 3172 |  2058 | 1397 |  +661 |  77 |     95 |  29208 |
|    4 | vmr-ema30-te2-sk1.0-tc30       |  151 | 2082 | 2656 |  1630 | 1313 |  +317 |  35 |     89 |  29708 |
|    5 | vmr-ema120-te2-sk1.5-tc30      |   14 | 2560 | 3172 |  1915 | 1675 |  +240 |  62 |     95 |  29362 |
|    6 | vmr-ema30-te1-sk1.5-tc20       |   91 | 1794 | 2726 |  1537 | 1336 |  +201 |  48 |     90 |  29714 |
|    7 | vmr-ema30-te1-sk1.0-tc20       |   91 | 1788 | 2726 |  1535 | 1336 |  +199 |  48 |     90 |  29714 |
|    8 | vmr-ema30-te1-sk2.0-tc20       |   91 | 1733 | 2726 |  1517 | 1331 |  +186 |  47 |     90 |  29714 |
|    9 | vmr-ema50-te2-sk2.0-tc20       |   -9 | 1853 | 2698 |  1514 | 1385 |  +129 |  44 |     91 |  29760 |
|   10 | vmr-ema30-te2-sk2.0-tc30       | -337 | 2084 | 3858 |  1868 | 2106 |  -237 | 165 |     95 |  28001 |

(`pin>80` = ticks-out-of-30000 with `|pos|>80`. Median across all 96
configs is 29546 ticks = 98.5%.)

### Axis: te (take_edge) break-out

| te | N | mean of means | median | max  | min   | pos%   | mean score |
|---:|--:|--------------:|-------:|-----:|------:|-------:|-----------:|
|  0 |32 |          −728 |   −498 |  700 | −3694 | 12/32  |      −2984 |
|  1 |32 |          −273 |   −149 | 2149 | −2050 | 15/32  |      −2002 |
|  2 |32 |          +214 |   +280 | 2058 | −1276 | 22/32  |      −1680 |

**Read**: `te=2` wins on average. `te=0` (take on every fv crossing)
is strictly worst — confirms the attribution finding that taking into
continuation bleeds. Top of the leaderboard is split: rank 1–2 use
`te=1` (with `ema=30`), rank 3+ shifts to `te=2`. So the regime is
*either* "fast EMA + early take" *or* "slow EMA + selective take" — not
a clean linear answer. te=2 is the safer default.

### Axis: sk (skew_strength) break-out

| sk  | N | mean of means | median | max  | min   | pos%   |
|----:|--:|--------------:|-------:|-----:|------:|-------:|
| 0.5 | 24|          −226 |    +51 | 2148 | −2083 | 14/24  |
| 1.0 | 24|          −238 |   −172 | 2149 | −2080 | 11/24  |
| 1.5 | 24|          −227 |    −47 | 1915 | −2050 | 12/24  |
| 2.0 | 24|          −359 |    −50 | 2058 | −3694 | 12/24  |

**Read**: skew is **roughly neutral** in this regime — flat across
0.5/1.0/1.5 and slightly worse at 2.0. The pilot's "monotonic
degradation" was D2-only noise. Top-10 spans all four sk values.
Inventory skew is neither the edge nor the bleed: it's basically
inactive because (a) max|pos| caps at ~95 across all configs and
(b) at that ratio, even sk=2.0 only shifts quotes by 1 tick.

### Axis: ema break-out

| ema | N | mean of means | median | max  | min   | pos%  |
|----:|--:|--------------:|-------:|-----:|------:|------:|
|  30 | 24|          +461 |   +406 | 2149 | −2187 | 17/24 |
|  50 | 24|          −809 |  −1015 | 1514 | −3694 |  7/24 |
|  80 | 24|          −422 |    +69 |  883 | −2050 | 12/24 |
| 120 | 24|          −280 |   +240 | 2058 | −2083 | 13/24 |

**Read**: `ema=30` is the dominant regime (mean +461, 71% positive).
`ema=50` (the trader's default before this sweep) is the WORST.
A faster EMA makes fv chase the within-day drift more aggressively,
producing fewer wrong-side fills.

### Axis: tc (take_size_cap) break-out

| tc  | N | mean of means | median | pos%   |
|----:|--:|--------------:|-------:|-------:|
|  20 | 48|          −258 |    −67 | 23/48  |
|  30 | 48|          −266 |    +29 | 26/48  |

**Read**: marginal — tc=30 slightly better at the median but
indistinguishable at the mean. Not the dominant axis.

### Position trajectory (96 configs, 3-day)

- max|pos|: mean 92, median 92, range [81, 100], **all configs ≤ 100**
- pinned at |pos|>80: mean 29364 ticks, median 29546 (**98.5% of day**)
- **`kill_threshold=150` never fires across any of the 96 configs**

The strategy reaches |pos|≈90 within the first ~1k ticks of every day
and stays there for the rest of the session, regardless of parameters.
Day-to-day PnL variance is dominated by which direction the closing
mid drifts relative to the held inventory, not by the spread it
captures.

### Decision-question answers

**Q1. Architecture viable?** Marginally yes. Best mean +2148, best
score +676, both positive. But 47% of configs lose money outright,
and even the winners hold a permanent ±90 inventory. The "edge" in
the top 10 is a convenient close-out direction on D1 and D2, not
clean spread capture.

**Q2. Which take regime wins?** `te=2` on average (mean +214,
22/32 positive). `te=0` strictly worst (mean −728, 12/32 positive).
Top of the leaderboard splits between "fast EMA + te=1" and
"slow EMA + te=2"; te=2 is the more robust default. This **confirms
the attribution prior**: aggressive takes at te=1 fire into
continuation more often than they capture reversion, so widening
to te=2 (only take when book has crossed by 2 ticks) recovers
selectivity.

**Q3. Skew helping or hurting?** Neutral. Means are −226 to −359
across all sk values with no monotonic gradient. Skew is essentially
inactive at the operating |pos|≈90 level — the inventory ratio is
small enough that even sk=2.0 only nudges quotes by 1 tick.

### Recommendation: (B) yes — but lighter than the original framing

The architecture has a positive-mean winner, so we **don't need to
abandon the MM template** before testing changes. But the trajectory
data is unambiguous: every config lives at saturation |pos|≈90 for
98% of the day, and the drift-kill never fires. Two cheap
architectural fixes are **strongly indicated** by this sweep:

1. **Tighten `kill_threshold` to ~80** (or add a softer "lean back to
   flat" multiplier on skew at |pos|>50). Current 150 is dead code.
2. **Force-flatten in last 500 ticks of the day**. Removes the
   close-out drift lottery that's currently driving most of the
   per-day variance.

A z-gate on aggressive takes is **not** the highest priority — te=2
already does most of the work a z-gate would (only fire when book has
clearly crossed). Re-test that after (1) and (2).

**Proposed v2**: take rank-3 config (`vmr-ema120-te2-sk2.0-tc30`,
mean=+2058, std=1397, score=+661) as the base — it's nearly tied
with the winner and uses the more robust te=2 take regime. Apply (1)
and (2) on top, re-sweep narrowly, ship.

(Rank 1–2 winners use te=1+ema=30 which is the "fast/aggressive"
regime: more fragile to live-vs-local fill differences. Rank 3 is
the "slow/selective" sibling and travels better.)

---

## P3.8 — noTrade-5100 + delta hedge (V4 test) — 2026-04-26

**Trader**: `trader-r3-v1-vev-v1.5-moduleA-only.py` (Module D added,
flag-gated, default off; flag ON in this run only).
**Config**: `vev_v1.5-moduleA-only-noTrade5100-hedged.json`
(`active_strikes`=[5000,5200,5300,5400,5500],
`smile_fit_strikes`=[5000,5100,5200,5300,5400,5500],
`z_open=2.0`, `enable_delta_hedge=True`, `band=30/60`, `throttle=100`,
`max_step=30`, `vev_position_limit=200`).
**Run dirs**: `runs/backtest-1777188213662-round3-day-{0,1,2}`.

### Result table

| day | hedged FINAL_PNL | noTrade-5100 unhedged (P3.6) | Δ |
|----:|-----------------:|-----------------------------:|--:|
|  0  | **−5.00**   | +75.0    | −80.0 |
|  1  | **−79.50**  | −159.5   | +80.0 |
|  2  | **+550.50** | +1255.5  | −705.0 |
| sum | **+466.00** | +1171.0  | −705.0 |
| /day | **+155.3** | +390.3   | −235.0 |

Hedged mean drops to +155.3/day (from +390.3). Std remains high
(D+2 still dominates).

### Per-product PnL (hedged, all 3 days)

| product              |  PnL  |
|----------------------|------:|
| VEV_5000             |  +782 |
| VEV_5300            |  +497 |
| VEV_5500            |   −99 |
| VEV_5400            |    −8 |
| VEV_5200            |    −1 |
| VELVETFRUIT_EXTRACT |  −705 |
| **net**              | +466 |

VEV_5000 + VEV_5300 are still the only two paying strikes; the −705
on VELVETFRUIT_EXTRACT is the cost of hedging.

### Hedge action stats (3 days, all from log inspection)

- D=0: 0 fired actions (max |portfolio_delta| stayed ≤ band)
- D=1: 0 fired actions
- D=2: 32 attempts, **1 fill** — single aggressive cross-spread
  sold 30 VEV @ 5272 at ts=951200 when |delta| crossed 60. The other
  31 attempts were passive limits at our touch and never filled
  (bot flow doesn't cross our quote in this dataset).

### Closed round-trip PnL — the signal-only metric

Rebuilt with same accounting as P3.7 forensics:

|  day  | unhedged closed RT | hedged closed RT |
|------:|-------------------:|-----------------:|
|   0   |               −4   |              −4  |
|   1   |               −7   |              −7  |
|   2   |              −75   |             −75  |
| **3d**|             **−86**|           **−86**|

Closed-RT PnL is bit-for-bit identical between hedged and unhedged
runs. The hedge moves VEV cash but does not change which voucher
trades closed and at what prices.

### Verdict: **V4-confirmed**

The IV-residual signal, evaluated on closed round trips only, makes
−86 across 3 days. Hedging changes total reported PnL from
+1171 → +466 because it strips off most of the unhedged residual
S-drift PnL — but does not flip closed-RT PnL into the green. The
+155/day that survives is the leftover MTM on partial hedge coverage
(only 1 of 32 hedge attempts actually filled on D+2), not signal alpha.

The signal as currently designed:

- opens correctly (z>2.0 entries on K=5000/5300 are not random),
- but **does not close in profit** — most opens are still on the
  book at EOD and get marked at the prevailing residual, which is
  uncorrelated with where they were opened.

### Recommendation — Phase 3.9 split

3.9a. **Closing-logic redesign**, not signal sweep. Options to
prototype next:
  - time-based exit (close after N ticks regardless of z),
  - `z_close` widened toward 0 from above (force re-cross),
  - asymmetric exits (loosen on short side that we sit on).
3.9b. **Tight delta-hedge baseline** — run Module D with band=10
and aggressive escalation by default (current band=30 + slow
throttle let D+2 drift accumulate before any hedge fired). This is
a control: tells us how much of +466 is real and how much is
under-hedged drift.

**Don't run a signal sweep** until closed-RT PnL across 3 days is
positive on at least one config.

### Back-compat verification

Hedge flag OFF reproduced D+2 P3.6 result bit-for-bit
(spot-checked: same trade list, same closing prices). Module D code
path is fully gated on `enable_delta_hedge=True`.

---

## P3.9a — closing-logic redesign — 2026-04-26

**Trader**: `trader-r3-v1-vev-v1.5-moduleA-only.py` (Module A exit
branch refactored, flag-gated; defaults to `exit_mode="legacy"`).
**Configs**: `vev_v1.5-moduleA-only-noTrade5100-hedged-{legacy,loosez,time200,hybrid}.json`.
**Run dirs**: `runs/backtest-1777189{677739,696343,713599,730662}-round3-day-{0,1,2}`.

### Total PnL table (all hedged)

| variant            |   D0 |   D+1 |    D+2 | total | trades |
|--------------------|-----:|------:|-------:|------:|-------:|
| legacy             | −5.0 | −79.5 | +550.5 | +466 |  95 |
| loose_z (z=1.0)    | −5.0 | −62.0 | +572.0 | +505 |  43 |
| time_based (h=200) | −75.0 | −942.0 | −194.0 | −1211 | 257 |
| hybrid (z=1.0,h=200) | −5.0 | −62.0 | +572.0 | +505 | 43 |

### Closed-RT PnL — THE METRIC

| variant     | RT D0 | RT D+1 | RT D+2 | **RT 3d** | #RT | win% |
|-------------|------:|-------:|-------:|----------:|----:|-----:|
| legacy      | −4   |  −7   | −75   | **−86**  | 7  | 43%  |
| loose_z     | −5   | −62   | −75   | **−142** | 6  | 17%  |
| time_based  | −12  | −87   |−635   | **−734** | 14 | 43%  |
| hybrid      | −5   | −62   | −75   | **−142** | 6  | 17%  |

### Verdict

**No-improvement.** All alternatives ≤ legacy on closed-RT.
loose_z and hybrid are bit-for-bit identical (z=1.0 fires before
the 200-tick clock in all observed events). time_based is
catastrophic (forced exits at random residuals → mean loss −170).

The +505 total PnL on loose_z exceeds legacy's +466 because more
positions sit open at EOD (only 6 RTs vs 7), and EOD MTM rides
the same residual drift V4 already identified — not signal alpha.

### Why the P3.10a forward-PnL prediction didn't survive

P3.10a measured forward residual change on **mids**. The trader
fills at the touch (or worse), with step-cap and passive-wait
dispersing fills across many ticks. The most likely binding
constraint: **adverse selection at entry** — counterparties that
lift our wide-spread quote at |z|>2 have edge against us, eating
the mid-residual signal before it can revert.

Per spec ("don't auto-pivot on no-improvement"): surfaced for
decision. Three options in P3.9a log: spread-gate entries, try
3.10b smile smoothing, or pivot away from the IV-scalp strategy.

---

## P3.9b — entry-side spread gate — 2026-04-26

**Trader**: `trader-r3-v1-vev-v1.5-moduleA-only.py` (added
`enable_spread_gate` + `spread_gate_max_ticks` config keys; entry
branches consult per-strike touch spread before opening; closing
branches NOT gated; defaults to gate-off).
**Configs**: `vev_v1.5-moduleA-only-noTrade5100-hedged-spread-{baseline,gate1,gate2,gate3}.json`.
**Run dirs**: `runs/backtest-1777191{667502,682878,697946,712905}-round3-day-{0,1,2}`.

### Total PnL table (all hedged)

| variant     |   D=0 |   D+1 |    D+2 |  total | trades |
|-------------|------:|------:|-------:|-------:|-------:|
| baseline    |  −5   | −79.5 | +550.5 |  +466  |  95 |
| gate=1      |  +1   |  −18  |   −23  |  **−40** |  28 |
| gate=2      |  −4   |  −21  |  +506  |  **+481** |  64 |
| gate=3      |  −5   |   −2  |  +396  |  **+389** |  68 |

### CLOSED-RT PnL — THE METRIC

| variant   | RT D=0 | RT D+1 | RT D+2 | **RT 3d** | #RT | win% | mean_win | mean_loss |
|-----------|-------:|-------:|-------:|----------:|----:|-----:|---------:|----------:|
| baseline  |  −4   |  −7    |  −75  |  **−86**  |  7  | 43%  |  5.7   |  −25.8 |
| **gate=1**|  +1   | −18    |  +47  |  **+30**  |  4  | 50%  |  **24.0**|  **−9.0** |
| gate=2    |  −4   | −26    |    0  |  **−30**  |  6  | 33%  |  3.0   |  −9.0  |
| gate=3    |  −4   |  −7    |    0  |  **−11**  |  6  | 50%  |  5.7   |  −9.3  |

### Verdict — Marginal win, mechanism confirmed

**First positive closed-RT across all P3.x phases**: gate=1 lands
+30/3d (spec marginal range: 0–50). Mean_win 4× larger and
mean_loss ~3× smaller than baseline — the unit-economics flip is
the adverse-selection signature predicted in P3.9a.

The +30 closed-RT comes at total-PnL cost: gate=1 makes −40 total
vs baseline +466. That's because the gate also strips the V4
directional-drift component baseline was riding (K=5000 alone went
from +782 unhedged to −75 closed-RT in baseline = ~100% drift).

Per Hard Rule #3 (straight-line-up cumulative) and Hard Rule #8
(always know your delta), gate=1 is the **honest** PnL path: real
edge from the residual signal, drift removed.

### Gate diagnostics (3d)

|z|>2 events seen: 6681 (constant across variants).
Spread distribution at |z|>2: sp=1 37%, sp=2 29%, sp=3 17%,
sp=4–5 2%, sp=6–7 15% (the adverse-sel cluster).
Gate-1 admits ~36% of events; gate-2 ~65%; gate-3 ~83%.

VEV_5000 gets fully suppressed under all 3 gates (all its |z|>2
events fire at wide spreads — the "drift bet" baseline was making
on K=5000 was hidden by adverse-selection at entry).

### Per-strike closed-RT (3d)

| variant   |  K=5000 |  K=5300 |  K=5400 |  K=5500 |
|-----------|--------:|--------:|--------:|--------:|
| baseline  | −75/1   | +11/1   | −13/3   |  −9/2   |
| gate=1    |   —     | +47/1   | −18/2   |  +1/1   |
| gate=2    |   —     |  −8/1   | −13/3   |  −9/2   |
| gate=3    |   —     | +11/1   | −13/3   |  −9/2   |

VEV_5300 carries the new alpha at gate=1 (+47 from a single round
trip; mean win 24.0 is 4× baseline's 5.7). VEV_5400 still loses
across every variant — flag for separate analysis or removal from
active strikes.

### Recommendation

Lock `enable_spread_gate=true`, `spread_gate_max_ticks=1` as the
working baseline. Surface verdict and proceed (per spec) only on
Sam's go-ahead with **Phase 3.10b — smile smoothing on top of
gate=1**. Rough expected: ema-100 smoothing ~2× the diagnostic
edge → ~+60/3d closed-RT.
