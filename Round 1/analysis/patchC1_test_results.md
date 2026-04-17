# Patch C1 Test Results

**Author:** Agent 10 Validation Run (Patch C1 Test)
**Date:** 2026-04-16
**Verdict:** WORSE

---

## 1. Setup

**What was changed:** `ACO_TAKE_WIDTH` from `1.5` to `3.0`.

**Hypothesis tested (Agent 10 Pass 5):** v9's `ACO_TAKE_WIDTH = 1.5` causes v9 to take inside v8's profitable spread, missing 10–20 tick captures. Raising to `3.0` (matching v8's effective behavior) should recover half or more of the 6,108 ACO gap.

**Files modified (scratch copies only; Round 1/traders/ untouched):**
- `scratch/trader-v9-r1-patchC1-aco-only.py` — ACO-only variant (IPR gated out)
- `scratch/trader-v9-r1-patchC1.py` — Full trader (both products)

Source files copied from:
- `Round 1/traders/trader-v9-r1-aco-only.py`
- `Round 1/traders/trader-v9-r1.py`

Patch applied via Python `str.replace` (sed failed silently due to RTK proxy; Python confirmed single occurrence, applied cleanly).

---

## 2. Diff Verification

### aco-only trader

```
51c51
< ACO_TAKE_WIDTH          = 1.5
---
> ACO_TAKE_WIDTH          = 3.0
```

**Result: exactly 1 line changed.** No other modifications.

### Full trader

```
56c56
< ACO_TAKE_WIDTH          = 1.5
---
> ACO_TAKE_WIDTH          = 3.0
```

**Result: exactly 1 line changed.** No other modifications.

---

## 3. Per-Day ACO PnL Table

Source: `runs/patchC1/aco_only_day-*.log` Activities log, final row (ts=999900). v9 baselines from `Round 1/analysis/v9_backtest_results.md` §2.

| Day | v9 baseline ACO | patchC1 ACO | Δ |
|-----|-----------------|-------------|---|
| -2  | 4,278.5         | 4,085.5     | −193.0 |
| -1  | 4,736.0         | 5,071.0     | +335.0 |
|  0  | 3,433.0         | 3,032.0     | −401.0 |

Mixed signal: one day improves (+335), two days regress (−193, −401). Net across 3 days: **−259.0**.

---

## 4. Merged Results Table

Source: `runs/patchC1/aco_only_merged.log` (ACO-only), `runs/patchC1/full_merged.log` (full trader). v8/v9 baselines from `v9_backtest_results.md` §3.

| Metric | v8 | v9 | patchC1 | (C1 − v9) | (C1 − v8) |
|--------|----|----|---------|-----------|-----------|
| Total 3-day PnL | 256,580.0 | 248,735.5 | 248,476.5 | −259.0 | −8,103.5 |
| ACO 3-day PnL | 18,556.0 | 12,447.5 | 12,188.5 | **−259.0** | −6,367.5 |
| IPR 3-day PnL | 238,024.0 | 236,288.0 | 236,288.0 | **0.0** | −1,736.0 |

All values in XIRECS.

---

## 5. Max ACO Position Comparison

Source: parse_logs.py Trade History position tracking.

| Day | v9 max |ACO pos| | v9 min ACO pos | patchC1 max ACO pos | patchC1 min ACO pos |
|-----|--------|--------|-----------|-----|
| -2  | +80    | −80    | +80       | −80 |
| -1  | +74    | −80    | +45       | −80 |
|  0  | +39    | −80    | 0         | −80 |

**Observation:** patchC1 hits the lower boundary (−80) on all 3 days — identical to v9. The higher `ACO_TAKE_WIDTH = 3.0` does not change the inventory boundary behavior; ACO still drives to −80 on all three days. Max positive position is lower on days -1 and 0 (45 vs 74, 0 vs 39), consistent with the wider take width triggering fewer long-side takes.

Merged aco_only max/min: +118/−80 (cross-day cumulative; not a real single-timestep position).

---

## 6. IPR Zero-Impact Check

| Metric | v9 merged IPR | patchC1 merged IPR | Δ | Δ% |
|--------|---------------|--------------------|---|-----|
| IPR 3-day PnL | 236,288.0 | 236,288.0 | **0.0** | **0.000%** |

Source: `runs/patchC1/full_merged.log` Activities log final IPR row.

IPR PnL is **exactly identical** to v9 — zero impact from the ACO_TAKE_WIDTH change. Confirms complete independence between ACO and IPR execution. Zero-impact check: PASS (well within ±0.1%).

---

## 7. Runtime Health

All 5 runs completed with exit code 0. No Python tracebacks, no exceptions, no NaN values.

| Log | IPR exceeded limit | ACO exceeded limit | Circuit triggers | Errors |
|-----|-------------------|--------------------|-----------------|--------|
| aco_only_day-2 | 0 | 98 | 0 | 0 |
| aco_only_day-1 | 0 | 96 | 0 | 0 |
| aco_only_day0  | 0 | 140 | 0 | 0 |
| aco_only_merged | 0 | 334 | 0 | 0 |
| full_merged    | 0 | 334 | 0 | 0 |

ACO exceeded limit counts (98–140/day, 334 merged) are **lower** than v9 (171–222/day, 566 merged). Wider take width reduces the number of make-layer orders that breach limits (take consumes more budget, leaving less for the make layer to overshoot). This is expected behavior, not a bug.

---

## 8. Verdict

**WORSE**

patchC1 (`ACO_TAKE_WIDTH = 3.0`) produces a merged ACO PnL of **12,188.5**, which is **−259.0** below v9's 12,447.5. The hypothesis is falsified: widening the take width does not recover the ACO gap — it marginally worsens ACO PnL.

**Why the hypothesis failed:**

Agent 10's diagnosis assumed that v9's narrow take width (`1.5`) was causing missed profitable captures that v8 was taking. The evidence does not support this:
- Day-by-day results are mixed (+335, −193, −401), not systematically positive
- The wider width (`3.0`) reduces make-layer fill opportunity (confirmed by fewer exceeded-limit messages: 98–140 vs 171–222), which hurts more than the additional take captures help
- The root cause of the v9-vs-v8 ACO gap is more likely structural: v9's KELP-style mmbot-mid fair value + reversion-beta framework produces different fill patterns than v8's simpler EMA approach, not just a take-width calibration problem

**Recommendation:** Do NOT ship `ACO_TAKE_WIDTH = 3.0`. Ship v9 untuned for R1. Treat the ACO gap as a R2 problem. The existing PLAN.md §ACO (f) inventory penalty sweep (`ACO_INVENTORY_PENALTY` from 0.025 → 0.035–0.050) remains the highest-priority ACO parameter, and the ACO-5 PnL shortfall is not blocking given v9 still clears the 3,000/day ship threshold (v9 ACO mean: 4,149.2/day).

---

## 9. Log File Index

| Scenario | Log File | Exit Code |
|----------|----------|-----------|
| patchC1 ACO-only day -2 | `runs/patchC1/aco_only_day-2.log` | 0 |
| patchC1 ACO-only day -1 | `runs/patchC1/aco_only_day-1.log` | 0 |
| patchC1 ACO-only day 0  | `runs/patchC1/aco_only_day0.log`  | 0 |
| patchC1 ACO-only merged | `runs/patchC1/aco_only_merged.log` | 0 |
| patchC1 full merged     | `runs/patchC1/full_merged.log`     | 0 |

Scratch trader files (evidence, do not delete):
- `scratch/trader-v9-r1-patchC1-aco-only.py`
- `scratch/trader-v9-r1-patchC1.py`

---

*patchC1_test_results.md ends.*
