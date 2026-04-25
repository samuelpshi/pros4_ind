# Pass 5 — ACO Inventory Penalty Sweep Log Index

**Status:** Corner test only (gate failed — full sweep not run).  
See `pass5_corner_test_verdict.md` for rationale.

| penalty | scenario | log_path |
|---------|----------|----------|
| 0.025 | merged | `runs/pass5/corner_0_025_merged.log` |
| 0.050 | merged | `runs/pass5/corner_0_050_merged.log` |

## Scratch trader files

| penalty | file |
|---------|------|
| 0.025 | `scratch/sweep_aco_0_025.py` |
| 0.050 | `scratch/sweep_aco_0_050.py` |

## Notes

- `--match-trades worse` scenario (merged_worse) was NOT run — gate failed before reaching Step 2.
- `prosperity4btest` v1.0.1 supports `--match-trades worse` (confirmed via `--help`), so it would have been available if the gate had passed.
- Full sweep runner: `scratch/sweep_aco_inventory_penalty.py` (idempotent, can be re-run with `SKIP_GATE = True` to force full sweep)
