# Pass 5 — ACO Inventory Penalty Corner Test Verdict

**Date:** 2026-04-16  
**Agent:** Agent 9 (ACO Inventory Penalty Sweep Runner)  
**Gate:** ACO_pnl(0.050) − ACO_pnl(0.025) ≥ 2,000 to proceed to full sweep

---

## Verdict: NO_MEANINGFUL_SIGNAL — sweep not worth running

**Recommend: SHIP_V9_UNTUNED** (or investigate root cause of ACO gap vs v8 differently)

---

## Corner Test Numbers

| penalty | total_pnl   | aco_pnl  | ipr_pnl   | aco_max_abs_pos/day | rejections_aco |
|---------|-------------|----------|-----------|---------------------|----------------|
| 0.025   | 248,735.5   | 12,447.5 | 236,288.0 | 80                  | 566            |
| 0.050   | 249,005.0   | 12,717.0 | 236,288.0 | 80                  | 574            |

**ACO PnL delta (0.050 − 0.025): +269.5**  
Gate threshold: 2,000  
Gate status: **FAILED** (delta = 269.5 << 2,000)

---

## Interpretation

Doubling the inventory penalty (0.025 → 0.050) produces only a +270 improvement in ACO PnL
across the merged 3-day backtest. The full sweep range [0.025, 0.050] with 5 additional
intermediate values would yield at most ~270 XIRECS improvement, with a monotone or
near-monotone response (no reason to expect a non-monotone peak in between when both
endpoints are close).

The ACO position still pins at ±80 with either penalty (566 vs 574 rejections). This means
the inventory skew is doing some work, but the dominant force on ACO position is the
order-book signal (take layer), not the make-layer skew. The 6,108 ACO gap vs v8 appears
to come from a structural difference in how v9's KELP-analog fair value is computed versus
v8's simpler EMA approach — not from insufficient inventory skew.

---

## Backtester Used

`prosperity4btest` v1.0.1 — marks to mid-price (verified in prior passes).  
Both runs used `--merge-pnl` mode (3-day concatenated, position carries across days).  
`--match-trades` not specified (defaults to `all` mode).

---

## Log Paths

| scenario | log |
|----------|-----|
| penalty=0.025 merged | `runs/pass5/corner_0_025_merged.log` |
| penalty=0.050 merged | `runs/pass5/corner_0_050_merged.log` |

---

## Scratch Files (preserved per task spec)

- `/scratch/sweep_aco_0_025.py` — copy of trader-v9-r1.py with ACO_INVENTORY_PENALTY = 0.025
- `/scratch/sweep_aco_0_050.py` — copy of trader-v9-r1.py with ACO_INVENTORY_PENALTY = 0.050

---

## What To Do Instead (for Agent 10 or next session)

The ACO gap (−6,108 vs v8) persists because:
1. v9's take layer is more conservative than v8 (ACO_TAKE_WIDTH=1.5 vs v8's tighter spread)
2. v9 ACO positions pin at ±80 regularly — inventory skew at 0.025 OR 0.050 is too weak to
   prevent this, and increasing it further would make quotes too wide to fill
3. Root cause is the make-layer passive quote size is capped at `limit ∓ pos`, which when pos=0
   means 80-lot passive quotes that are rarely filled vs v8's more active trading

Recommended next actions:
- Compare v9 vs v8 ACO fill count and position oscillation pattern (Trade History)
- Investigate ACO_TAKE_WIDTH sensitivity (maybe widen from 1.5 to 2.0 or 2.5)
- Investigate ACO_DEFAULT_EDGE sensitivity (1 → 0 for tighter passive quotes)
- Do NOT run full inventory-penalty sweep — the signal is absent
