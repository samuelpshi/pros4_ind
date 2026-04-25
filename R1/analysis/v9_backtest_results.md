# v9 Backtest Results

**Author:** Agent 8 (Backtest Evaluator), Pass 4 — post-Agent-7b-fix re-run
**Date:** 2026-04-16
**Verdict:** ITERATE

**Note:** This file supersedes the previous BLOCKED evaluation. Agent 7b patched the IPR order aggregation bug that caused 5,209+ "exceeded limit" rejections on IPR. This is a fresh evaluation from scratch on re-run logs.

---

## 1. Setup

**Marking convention:** Mark-to-mid at end of day. Source: `Round 1/analysis/backtester_marking_verified.md` §5 Verdict — both ACO and IPR verified to match PnL_mid formula exactly (ACO: 10007.0−10013=−6.0 matches reported; IPR: 13000.0−12006=994.0 matches reported). No transaction fees confirmed for Round 1.

**Backtester:** `prosperity4btest`. Agent 6 verified correct operation and marking convention.

**Backtester invocation pattern:**
```
prosperity4btest "<trader-file>" <round>-<day> [--merge-pnl] [--match-trades worse] --out <log>
```
Omitting `--merge-pnl` runs a single day. With `--merge-pnl`, runs all available days in the round. Position does NOT reset between days in merged mode.

**All 11 runs:**

| # | Scenario | Command | Log Path |
|---|----------|---------|---------|
| 1 | v8 day -2 | `prosperity4btest "Round 1/traders/trader-v8-173159.py" 1--2 --out runs/v8_day-2.log` | `runs/v8_day-2.log` |
| 2 | v8 day -1 | `prosperity4btest "Round 1/traders/trader-v8-173159.py" 1--1 --out runs/v8_day-1.log` | `runs/v8_day-1.log` |
| 3 | v8 day 0 | `prosperity4btest "Round 1/traders/trader-v8-173159.py" 1-0 --out runs/v8_day0.log` | `runs/v8_day0.log` |
| 4 | v9 day -2 | `prosperity4btest "Round 1/traders/trader-v9-r1.py" 1--2 --out runs/v9_day-2.log` | `runs/v9_day-2.log` |
| 5 | v9 day -1 | `prosperity4btest "Round 1/traders/trader-v9-r1.py" 1--1 --out runs/v9_day-1.log` | `runs/v9_day-1.log` |
| 6 | v9 day 0 | `prosperity4btest "Round 1/traders/trader-v9-r1.py" 1-0 --out runs/v9_day0.log` | `runs/v9_day0.log` |
| 7 | v8 merged | `prosperity4btest "Round 1/traders/trader-v8-173159.py" 1 --merge-pnl --out runs/v8_merged.log` | `runs/v8_merged.log` |
| 8 | v9 merged | `prosperity4btest "Round 1/traders/trader-v9-r1.py" 1 --merge-pnl --out runs/v9_merged.log` | `runs/v9_merged.log` |
| 9 | v9 merged worse | `prosperity4btest "Round 1/traders/trader-v9-r1.py" 1 --merge-pnl --match-trades worse --out runs/v9_merged_worse.log` | `runs/v9_merged_worse.log` |
| 10 | v9 ACO-only merged | `prosperity4btest "Round 1/traders/trader-v9-r1-aco-only.py" 1 --merge-pnl --out runs/v9_aco_only_merged.log` | `runs/v9_aco_only_merged.log` |
| 11 | v9 IPR-only merged | `prosperity4btest "Round 1/traders/trader-v9-r1-ipr-only.py" 1 --merge-pnl --out runs/v9_ipr_only_merged.log` | `runs/v9_ipr_only_merged.log` |

All 11 runs completed with exit code 0. Logs were overwritten from the previous BLOCKED run.

**Parsing scripts:** `scratch/parse_logs.py` (updated with exceeded-limit counting), `scratch/parsed_results.json`

---

## 2. Per-Day Results Table

All PnL values in XIRECS. Source: Activities log `profit_and_loss` column, final row per product per day (ts=999900). The "max drawdown" values in the raw parsed output (~879K–1.37M) are artifacts of mid_price=0 rows (54/day, per CLAUDE.md §Verified Findings) and are not reported here.

| Scenario | v8 Total | v8 ACO | v8 IPR | v9 Total | v9 ACO | v9 IPR | Δ Total | Δ ACO | Δ IPR |
|----------|----------|--------|--------|----------|--------|--------|---------|-------|-------|
| Day -2 | 85,878.0 | 6,335.0 | 79,543.0 | 83,462.5 | 4,278.5 | 79,184.0 | −2,415.5 | −2,056.5 | −359.0 |
| Day -1 | 86,134.0 | 6,972.0 | 79,162.0 | 83,406.0 | 4,736.0 | 78,670.0 | −2,728.0 | −2,236.0 | −492.0 |
| Day 0  | 84,568.0 | 5,249.0 | 79,319.0 | 81,867.0 | 3,433.0 | 78,434.0 | −2,701.0 | −1,816.0 | −885.0 |

Source: `runs/v8_day-2.log`, `runs/v8_day-1.log`, `runs/v8_day0.log`, `runs/v9_day-2.log`, `runs/v9_day-1.log`, `runs/v9_day0.log` — Activities log `profit_and_loss` column, last row per product (ts=999900).

**v9 inventory paths (from Trade History per-day logs):**

| Day | IPR path | ACO path |
|-----|----------|----------|
| -2 | 0 → +80 by ts=7,400 (7 ticks); 1 skim fill at ts=205,000 (7 units), refilled ts=205,100; final pos=+80 | Oscillated [−80, +80]; hit −80 at ts≈51,400; final pos=+67 |
| -1 | 0 → +80 early; 1 skim fill at ts=865,600 (8 units), refilled; final pos=+80 | Oscillated [−80, +74]; hit −80 at ts≈89,700; final pos=+73 |
|  0 | 0 → +80 early; 0 skim fills; final pos=+80 | Oscillated [−80, +39]; hit −80 at ts≈809,300; final pos=−52 |

Source: Trade History sections of `runs/v9_day-2.log`, `runs/v9_day-1.log`, `runs/v9_day0.log`.

---

## 3. Concatenated (Merged) Results

PnL is cumulative across all 3 days. Per-day sum of individual runs matches merged totals exactly (verified: ACO sum 4,278.5+4,736.0+3,433.0=12,447.5; IPR sum 79,184.0+78,670.0+78,434.0=236,288.0).

| Metric | v8 merged | v9 merged | Δ | Δ% |
|--------|-----------|-----------|---|-----|
| Total 3-day PnL | 256,580.0 | 248,735.5 | −7,844.5 | −3.06% |
| ACO 3-day PnL | 18,556.0 | 12,447.5 | −6,108.5 | −32.9% |
| IPR 3-day PnL | 238,024.0 | 236,288.0 | −1,736.0 | −0.73% |

Source: `runs/v8_merged.log`, `runs/v9_merged.log` — Activities log, last row per product.

---

## 4. Sensitivity Table

| Metric | v9 merged (default) | v9 merged (worse) | Δ | Δ% |
|--------|---------------------|-------------------|---|-----|
| Total PnL | 248,735.5 | 248,768.5 | +33.0 | +0.013% |
| ACO PnL | 12,447.5 | 12,445.5 | −2.0 | −0.016% |
| IPR PnL | 236,288.0 | 236,323.0 | +35.0 | +0.015% |

Note: the "worse" scenario produces marginally higher total PnL (+33.0), indicating the fill-matching convention has essentially zero impact on this strategy. Both ACO and IPR are near-insensitive to fill order; IPR holds the long position passively and ACO's symmetric market-making is not directionally dependent on fill timing.

Source: `runs/v9_merged.log`, `runs/v9_merged_worse.log` — Activities log, final rows.

---

## 5. Single-Product Attribution

| Scenario | ACO PnL | IPR PnL | Total |
|----------|---------|---------|-------|
| v9 ACO-only merged | 12,447.5 | 0.0 | 12,447.5 |
| v9 IPR-only merged | 0.0 | 236,288.0 | 236,288.0 |
| v9 merged (both) | 12,447.5 | 236,288.0 | 248,735.5 |

**ACO attribution:** v9_aco_only_merged ACO = 12,447.5; v9_merged ACO = 12,447.5. Difference = 0.0 (0.0%). No cross-product interaction.

**IPR attribution:** v9_ipr_only_merged IPR = 236,288.0; v9_merged IPR = 236,288.0. Difference = 0.0 (0.0%). No cross-product interaction.

Source: `runs/v9_aco_only_merged.log`, `runs/v9_ipr_only_merged.log`, `runs/v9_merged.log` — Activities log, final rows.

---

## 6. Success Criteria Check

From `Round 1/strategies/PLAN.md` §Shared Evaluation Plan §Success Criteria (numeric):

### ACO

| Criterion | Threshold | v9 Value | Result |
|-----------|-----------|---------|--------|
| Mean ACO PnL/day | ≥ 3,000/day | 4,149.2/day | PASS |
| ACO PnL std/day | < 2,000/day | 661.1/day | PASS |
| Negative ACO PnL any single day | Disqualifies | Min = 3,433 (day 0) | PASS |

v9 ACO mean: (4,278.5 + 4,736.0 + 3,433.0) / 3 = 4,149.2/day. Clears the 3,000/day ship threshold despite v8 ACO mean being 6,185.3/day. The v9 ACO shortfall vs v8 is attributable to the new KELP-style strategy's less aggressive quoting (narrower effective fill rate) and the ITERATE-class inventory penalty issue (see Diagnostic 3).

Source: `runs/v9_day-2.log`, `runs/v9_day-1.log`, `runs/v9_day0.log`.

### IPR

| Criterion | Threshold | v9 Value | Result |
|-----------|-----------|---------|--------|
| Mean IPR PnL/day (ship) | ≥ 79,350/day | 78,762.7/day | FAIL (−587.3/day below) |
| Mean IPR PnL/day (iterate) | < 79,000/day | 78,762.7/day | ITERATE (below iterate threshold) |
| Circuit breaker: no trigger on training data | Never fires | Never fired | PASS |

v9 IPR mean: (79,184.0 + 78,670.0 + 78,434.0) / 3 = 78,762.7/day.

**Important calibration note:** The PLAN.md ship threshold of 79,350/day is 8.7/day above the v8 mean of 79,341.3/day. This means the threshold commits to a small improvement over baseline — neither v8 nor v9 meets it. v9 misses the threshold by 587.3/day (0.74%). This is a real but small shortfall.

The v9 vs v8 regression of −578.7/day (−0.73%) is consistent with the 2% noise-band test in Diagnostic 4. The regression is likely attributable to the new passive entry bid strategy: PLAN.md §IPR (a) expected +160/day saving from better entry prices, but the actual result shows a small net negative, suggesting slippage on the passive entry is slightly worse than the greedy fallback in practice.

Source: `runs/v9_day-2.log`, `runs/v9_day-1.log`, `runs/v9_day0.log`.

### Combined

| Criterion | Threshold | v9 Value | Result |
|-----------|-----------|---------|--------|
| 3-day combined total | ≥ 248,000 | 248,735.5 | PASS (by 735.5) |

v9 3-day total is 248,735.5 vs threshold of 248,000. Passes by 735.5 XIRECS.

Source: `runs/v9_merged.log`.

---

## 7. Stress Test Status

**Deferred.** Rationale: `prosperity4btest` does not support clean drift injection without data modification. Simulating reversal scenarios requires modifying CSV price data, which introduces invented data and violates evaluation constraints. Stress tests can be conducted after Pass 5 parameter tuning, using the approach described in PLAN.md §IPR Additional Scenario.

---

## 8. Diagnostics

### Diagnostic 1: IPR LONG-ONLY FLOOR

**Check:** Scan all v9 logs for any timestamp where IPR position < 0.

**Evidence:** Parsed Trade History for all 5 v9 logs (script: `scratch/parse_logs.py`, Trade History cumulative position tracking). IPR minimum position observed:
- `runs/v9_day-2.log`: min IPR position = 0
- `runs/v9_day-1.log`: min IPR position = 0
- `runs/v9_day0.log`: min IPR position = 0
- `runs/v9_merged.log`: min IPR position = 0
- `runs/v9_ipr_only_merged.log`: min IPR position = 0

**Result: PASS.** IPR long-only floor holds in every run. The guard clause at IMPLEMENTATION_NOTES.md line 507 (`if skim_size > 0 and (pos - skim_size) >= IPR_LONG_ONLY_FLOOR:`) is functional. IPR position never crosses zero in any run. This satisfies ipr_mm_synthesis.md §Long-Only Floor hard requirement.

---

### Diagnostic 2: CIRCUIT BREAKER BEHAVIOR

**Check:** Parse for circuit breaker trigger events in all v9 logs.

**Evidence:** Searched sandboxLog fields in all v9 runs for "circuit" (case-insensitive). Zero matches in all 5 v9 logs. IPR reached position +80 in every day run, consistent with the breaker never firing and allowing full accumulation. The circuit breaker (PLAN.md §IPR (d), IMPLEMENTATION_NOTES.md line 387) requires realized drift over W=500 ticks to fall below 1001.3 − 5.0×806 − 50 ≈ −3,029 XIRECS/day. On training data with drift +1001.3/day, no W=500 window approaches this.

**Result: PASS.** Circuit breaker never fires. Consistent with PLAN.md §IPR (d): "on training data (no reversal), circuit breaker must NOT trigger."

Source: `runs/v9_day-2.log`, `runs/v9_day-1.log`, `runs/v9_day0.log`, `runs/v9_merged.log`, `runs/v9_ipr_only_merged.log`.

---

### Diagnostic 3: ACO POSITION LIMIT

**Check:** Max |ACO position| across all v9 runs. Pass: < 50. Soft flag: 50–70. Fail: hits or grazes 80.

**Evidence:**

| Run | ACO max | ACO min | |max ACO|| Assessment |
|-----|---------|---------|---------|------------|
| v9 day −2 | +80 | −80 | 80 | FAIL |
| v9 day −1 | +74 | −80 | 80 | FAIL |
| v9 day 0  | +39 | −80 | 80 | FAIL |

ACO hits −80 on all 3 days (min position = −80 every day). On day −2, it also hits +80 near EOD. The pattern is symmetric oscillation: ACO spends brief time exactly at the limit, not sustained pile-up in one direction (consistent with Agent 7b's diagnosis in agent7b_fix_summary.md §ACO Audit Finding: "ACO does hit ±80 on all 3 days... due to insufficient inventory penalty").

ACO "exceeded limit" sandboxLog counts: 171 (day −2), 173 (day −1), 222 (day 0), 566 (merged). These are higher than v8 (118/127/151/396), reflecting the more aggressive KELP-style full-capacity make orders. This increase is expected from the strategy change (v9 ACO quotes full remaining capacity at every tick), not a bug introduced by Agent 7b. The ACO order-budget structure is structurally sound per IMPLEMENTATION_NOTES.md §ACO Audit — the exceeded-limit messages occur when the engine rejects orders that would collectively exceed the limit; the make layer uses `buy_qty = limit − pos` which can only produce violations when the take or clear layer has already consumed part of the budget in the same tick. This is the same ITERATE-class penalty issue noted by Agent 7b.

**Result: FAIL → ITERATE.** ACO grazes ±80 boundary. Character: symmetric oscillation, not sustained directional pile-up. Root cause: `ACO_INVENTORY_PENALTY = inv_skew_per_unit = 0.025` (IMPLEMENTATION_NOTES.md line 68) is too weak. This is not a structural bug — the ACO take→clear→make budget pipeline is correct — it is a parameter calibration issue (PLAN.md §ACO (f) already lists this as the priority-5 sweep parameter).

**Candidate parameter:** `inv_skew_per_unit` from 0.025 → sweep [0.035, 0.040, 0.045, 0.050] per PLAN.md §ACO (f). At 0.025, a ±80 position shifts the quoted fv by only ±2.0 XIRECS, insufficient deterrent in a market with 10–20 XIREC typical spread. At 0.040, the shift is ±3.2 XIRECS. The sweep stopping criterion (PLAN.md §ACO (f)): accept the value where mean PnL improves AND std does not increase by more than 20% of the mean improvement, tested across all 3 days.

Source: `runs/v9_day-2.log`, `runs/v9_day-1.log`, `runs/v9_day0.log` — Trade History cumulative position; sandbox logs exceeded-limit counts.

---

### Diagnostic 4: V9 vs V8 IPR REGRESSION CHECK

**Check:** Per-day IPR PnL, v9 vs v8. Pass: v9 ≥ v8, or within 2% noise band. Fail: materially worse consistently (>2%). Previous BLOCKED run failed this check due to 5,209 IPR engine rejections. This re-run verifies Agent 7b's fix.

**Evidence:**

| Day | v8 IPR | v9 IPR | Δ | Δ% | Within 2%? |
|-----|--------|--------|---|-----|-----------|
| −2 | 79,543.0 | 79,184.0 | −359.0 | −0.45% | YES |
| −1 | 79,162.0 | 78,670.0 | −492.0 | −0.62% | YES |
|  0 | 79,319.0 | 78,434.0 | −885.0 | −1.12% | YES |
| merged | 238,024.0 | 236,288.0 | −1,736.0 | −0.73% | YES |

All three days and merged are within the 2% noise band. The worst single-day regression is −1.12% on day 0.

**Agent 7b fix verification (explicit):** IPR "exceeded limit" sandboxLog messages in all v9 logs:
- `runs/v9_day-2.log`: IPR exceeded limit = **0** (v8: 0; previous Agent 8 run: 1,759)
- `runs/v9_day-1.log`: IPR exceeded limit = **0** (previous: 1,278)
- `runs/v9_day0.log`: IPR exceeded limit = **0** (previous: 757)
- `runs/v9_merged.log`: IPR exceeded limit = **0**
- `runs/v9_ipr_only_merged.log`: IPR exceeded limit = **0**

Agent 7b's fix is confirmed: zero IPR engine rejections across all v9 logs. The previous 5,209 total IPR rejections (causing the BLOCKED verdict) are fully resolved.

The remaining −0.73% mean regression is a small, consistent shortfall. Source is likely: passive entry bids at `fv(t) − spread/2` (PLAN.md §IPR (a)) sometimes getting passed by on ticks where the ask moves away before the fill, while the v8 greedy approach always fills within 2-4 timestamps. The delta is below the 2% threshold and is within measurement noise for a 3-day dataset.

**Result: PASS.** All three days within 2% noise band. Agent 7b fix confirmed: 0 IPR "exceeded limit" messages in all v9 logs.

Source: `runs/v9_day-2.log`, `runs/v9_day-1.log`, `runs/v9_day0.log` — Activities log final rows; sandbox log exceeded-limit scan.

---

### Diagnostic 5: RUNTIME HEALTH

**Check:** Scan for "Error", "Exception", "Traceback", "Warning", "NaN", "exceeded limit" (IPR-specific Agent 7b gate).

**Evidence (all v9 logs):**
- Python Traceback count: 0
- Python Exception count: 0
- NaN in any field: 0
- lambdaLog messages: all empty strings (`""`) in every sandbox log entry
- Suspicious "None" values: 0

**"exceeded limit" breakdown (Agent 7b fix gate):**

| Log | IPR exceeded limit | ACO exceeded limit |
|-----|-------------------|-------------------|
| v9_day-2 | **0** | 171 |
| v9_day-1 | **0** | 173 |
| v9_day0 | **0** | 222 |
| v9_merged | **0** | 566 |
| v9_ipr_only_merged | **0** | 0 |

IPR exceeded limit count is **zero in every v9 log**. Agent 7b fix is verified at the raw sandboxLog level. ACO exceeded limit counts (171–566) are a pre-existing ITERATE-class issue (present in v8 at 118–396) and increase with the more aggressive KELP-style strategy. These are not new structural bugs — they are the symptom of the inventory penalty being too weak (Diagnostic 3).

**Result: PASS.** Runtime clean. No Python exceptions, no NaN, no IPR engine rejections. ACO engine rejections are pre-existing parameter-tuning issue.

Source: `runs/v9_day-2.log`, `runs/v9_day-1.log`, `runs/v9_day0.log`, `runs/v9_merged.log` — sandbox log section.

---

### Diagnostic 6: SENSITIVITY UNDER --match-trades worse

**Check:** Compare v9_merged vs v9_merged_worse. Pass: degradation < 30%, no sign flip.

**Evidence:**

| Metric | v9 merged (default) | v9 merged (worse) | Δ | Δ% |
|--------|---------------------|-------------------|---|-----|
| Total PnL | 248,735.5 | 248,768.5 | +33.0 | +0.013% |
| ACO PnL | 12,447.5 | 12,445.5 | −2.0 | −0.016% |
| IPR PnL | 236,288.0 | 236,323.0 | +35.0 | +0.015% |

The "worse" fill convention produces a marginally higher total (+0.013%), not lower. This indicates the strategy is not fill-sensitive: IPR holds a long position and is agnostic to fill order within any given timestep; ACO's symmetric quoting is likewise insensitive to minor fill-ordering changes.

**Result: PASS.** Near-zero impact (well below 30% threshold). No sign flip. No IPR collapse.

Source: `runs/v9_merged.log`, `runs/v9_merged_worse.log` — Activities log, final rows.

---

### Cross-Product Attribution (Context)

v9_aco_only_merged ACO PnL = 12,447.5; v9_merged ACO = 12,447.5. Difference = 0.0 (0.0%). No cross-product interaction.

v9_ipr_only_merged IPR PnL = 236,288.0; v9_merged IPR = 236,288.0. Difference = 0.0 (0.0%). No cross-product interaction.

Both products execute independently. Source: `runs/v9_aco_only_merged.log`, `runs/v9_ipr_only_merged.log`, `runs/v9_merged.log`.

---

## 9. VERDICT

**ITERATE**

No structural bugs. Agent 7b fix confirmed across all 5 v9 logs (IPR exceeded limit = 0 everywhere). One diagnostic Fail (Diagnostic 3: ACO inventory penalty), which is ITERATE-class, not BLOCKED.

**Summary of diagnostic outcomes:**

| # | Diagnostic | Result | Notes |
|---|-----------|--------|-------|
| 1 | IPR Long-Only Floor | PASS | Min IPR pos = 0 in all runs |
| 2 | Circuit Breaker | PASS | Never fires on training data |
| 3 | ACO Position Limit | FAIL → ITERATE | Symmetric ±80 oscillation; penalty too weak |
| 4 | V9 vs V8 IPR Regression | PASS | All days within 2% noise band; 0 IPR limit rejections |
| 5 | Runtime Health | PASS | No exceptions; IPR limit count = 0 (Agent 7b fix verified) |
| 6 | Sensitivity | PASS | 0.013% degradation (well below 30%) |

**Why not SHIP:** Two criteria missed — (a) ACO hits ±80 (Diagnostic 3 Fail); (b) IPR mean of 78,762.7/day is below the 79,350/day ship threshold (misses by 587.3/day).

**Why not BLOCKED:** No structural bugs. Diagnostic 3 fails the "< 50" pass criterion but is explicitly classified as ITERATE in the diagnostic spec: "symmetric oscillation — penalty too weak" (agent7b_fix_summary.md §ACO Audit Finding). Diagnostic 4 is now PASS; the IPR regression is within noise.

**Parameter candidates (ITERATE action):**

**Candidate 1 — ACO inv_skew_per_unit (Priority 1, addresses Diagnostic 3):**
Sweep [0.035, 0.040, 0.045, 0.050] per PLAN.md §ACO (f). Starting value 0.025 shifts fv by ±2.0 XIRECS at ±80 position — insufficient relative to the 10–20 XIREC spread. At 0.040, shift = ±3.2 XIRECS. At 0.050, shift = ±4.0 XIRECS. Sweep stopping criterion: mean ACO PnL improves across all 3 days AND std does not increase by more than 20% of the mean improvement. Evidence: v9_day-2.log ACO min position = −80 (multiple timestamps), first hit at ts≈51,400. Log: `runs/v9_day-2.log` Trade History.

**Candidate 2 — IPR skim interaction (context, addresses IPR ship threshold gap):**
Skim produced 2 fills across 3 days (1 on day −2 at ts=205,000 with qty=7; 1 on day −1 at ts=865,600 with qty=8) vs 0 fills observed with v8. The skim is working as designed (filled then immediately refilled). At 2 fills across 3 days vs expected 8-12 fills/day (PLAN.md §IPR (b)), fill rate is below expectation. Each skim round-trip (sell 8 at ask+1, rebuy at bid+1) yields approximately 8×2 = 16 XIRECS. 2 fills over 3 days contributes ≈ 11 XIRECS/day — insufficient to close the 587/day gap to the ship threshold. Increasing skim frequency (lower skim_trigger or larger skim_size) could narrow the gap but the 587/day shortfall is larger than skim can realistically provide. The primary driver of the IPR shortfall vs ship threshold is the baseline drift PnL being slightly below the threshold — the threshold was set 8.7/day above v8's observed mean, requiring a net positive improvement over v8, which the passive entry did not deliver. Log evidence: `runs/v9_merged.log` Trade History — 2 SUBMISSION seller IPR trades confirmed.

---

## 10. Log File Index

| Claim | Log File | Location in Log |
|-------|----------|----------------|
| v8 day −2: ACO=6,335.0, IPR=79,543.0 | `runs/v8_day-2.log` | Activities log, rows at ts=999900 |
| v8 day −1: ACO=6,972.0, IPR=79,162.0 | `runs/v8_day-1.log` | Activities log, rows at ts=999900 |
| v8 day 0: ACO=5,249.0, IPR=79,319.0 | `runs/v8_day0.log` | Activities log, rows at ts=999900 |
| v9 day −2: ACO=4,278.5, IPR=79,184.0 | `runs/v9_day-2.log` | Activities log, rows at ts=999900 |
| v9 day −1: ACO=4,736.0, IPR=78,670.0 | `runs/v9_day-1.log` | Activities log, rows at ts=999900 |
| v9 day 0: ACO=3,433.0, IPR=78,434.0 | `runs/v9_day0.log` | Activities log, rows at ts=999900 |
| v8 merged: ACO=18,556.0, IPR=238,024.0 | `runs/v8_merged.log` | Activities log, final rows |
| v9 merged: ACO=12,447.5, IPR=236,288.0 | `runs/v9_merged.log` | Activities log, final rows |
| v9 merged worse: ACO=12,445.5, IPR=236,323.0 | `runs/v9_merged_worse.log` | Activities log, final rows |
| v9 aco-only: ACO=12,447.5 | `runs/v9_aco_only_merged.log` | Activities log, ACO final row |
| v9 ipr-only: IPR=236,288.0 | `runs/v9_ipr_only_merged.log` | Activities log, IPR final row |
| IPR exceeded limit = 0 in v9_day-2 | `runs/v9_day-2.log` | Sandbox logs, IPR-related sandboxLog fields |
| IPR exceeded limit = 0 in v9_day-1 | `runs/v9_day-1.log` | Sandbox logs, IPR-related sandboxLog fields |
| IPR exceeded limit = 0 in v9_day0 | `runs/v9_day0.log` | Sandbox logs, IPR-related sandboxLog fields |
| IPR exceeded limit = 0 in v9_merged | `runs/v9_merged.log` | Sandbox logs, IPR-related sandboxLog fields |
| IPR exceeded limit = 0 in v9_ipr_only | `runs/v9_ipr_only_merged.log` | Sandbox logs, all sandboxLog fields |
| ACO exceeded limit = 171 in v9_day-2 | `runs/v9_day-2.log` | Sandbox logs, ASH_COATED_OSMIUM sandboxLog fields |
| ACO exceeded limit = 566 in v9_merged | `runs/v9_merged.log` | Sandbox logs, ASH_COATED_OSMIUM sandboxLog fields |
| ACO min position = −80 day −2 | `runs/v9_day-2.log` | Trade History, cumulative position tracking |
| ACO max position = +80 day −2 | `runs/v9_day-2.log` | Trade History, cumulative position tracking |
| IPR min position = 0 in all v9 logs | All 5 v9 logs | Trade History, cumulative position tracking |
| IPR position reached +80 all days | `runs/v9_day-2.log`, `runs/v9_day-1.log`, `runs/v9_day0.log` | Trade History, buyer=SUBMISSION IPR entries |
| Sensitivity delta: +33.0 total | `runs/v9_merged.log`, `runs/v9_merged_worse.log` | Activities log, final rows |
| No lambdaLog messages in v9 runs | All v9 logs | Sandbox logs, all lambdaLog fields |
| v9 merged total: 248,735.5 ≥ 248,000 threshold | `runs/v9_merged.log` | Activities log, final rows (sum: 12,447.5 + 236,288.0) |
| IPR skim fill day −2: ts=205,000, qty=7, price=10208 | `runs/v9_day-2.log` | Trade History, seller=SUBMISSION IPR entry |
| IPR skim fill day −1: ts=865,600, qty=8, price=11868 | `runs/v9_day-1.log` | Trade History, seller=SUBMISSION IPR entry |
| IPR 0 skim fills day 0 | `runs/v9_day0.log` | Trade History, no seller=SUBMISSION IPR entries |
| IPR reached +80 by ts=7,400 on day −2 | `runs/v9_day-2.log` | Trade History, cumulative position=80 at ts=7,400 |

---

*v9_backtest_results.md ends. Post-Agent-7b re-run. All 11 log files in `runs/`. Parsing script at `scratch/parse_logs.py`.*
