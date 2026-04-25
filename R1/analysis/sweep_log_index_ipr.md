# IPR Skim Sweep — Log File Index

Corner test only (gate FAILED: spread=91 < threshold=5,000).

| skim_size | skim_offset | refill_max_size | scenario | ipr_pnl | total_pnl | log_path |
|-----------|-------------|-----------------|----------|---------|-----------|----------|
| 3 | 1 | 5 | merged | 238018 | 256574 | `Round 1/archive/runs/ipr_sweep/sz3_off1_rfl5_merged.log` |
| 3 | 1 | 20 | merged | 238018 | 256574 | `Round 1/archive/runs/ipr_sweep/sz3_off1_rfl20_merged.log` |
| 3 | 5 | 5 | merged | 238054 | 256610 | `Round 1/archive/runs/ipr_sweep/sz3_off5_rfl5_merged.log` |
| 3 | 5 | 20 | merged | 238054 | 256610 | `Round 1/archive/runs/ipr_sweep/sz3_off5_rfl20_merged.log` |
| 15 | 1 | 5 | merged | 237963 | 256519 | `Round 1/archive/runs/ipr_sweep/sz15_off1_rfl5_merged.log` |
| 15 | 1 | 20 | merged | 237963 | 256519 | `Round 1/archive/runs/ipr_sweep/sz15_off1_rfl20_merged.log` |
| 15 | 5 | 5 | merged | 238054 | 256610 | `Round 1/archive/runs/ipr_sweep/sz15_off5_rfl5_merged.log` |
| 15 | 5 | 20 | merged | 238054 | 256610 | `Round 1/archive/runs/ipr_sweep/sz15_off5_rfl20_merged.log` |
| (baseline) | (no env vars) | (default) | merged | 238024 | 256580 | `Round 1/archive/runs/ipr_sweep/baseline_no_envvars_merged.log` |

## Gate Verdict

- IPR PnL range: 237,963 to 238,054
- Spread: **91 XIRECS**
- Gate threshold: 5,000 XIRECS
- Result: **GATE FAILED — space too flat**
- Action: Full 400-run sweep NOT executed. Recommend keeping v8 defaults.

## ACO Sanity Check

ACO PnL = 18,556 across all 8 corners (spread = 0). Sanity check PASSED.
