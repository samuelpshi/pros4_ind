# Pass 2.6 Progress — 2026-04-17 (FINAL)

All 4 agents (A0, A1, A2, A3_refine, A4_finalize) completed. Total agent wall time ≈ 60 min (well under the 4h budget).

## ACTION REQUIRED FROM USER

Pass 2.6 surfaced a **genuine tension between gates** that the dispatch rules cannot auto-resolve. A4 deferred the ship decision to you.

**Default (per strict dispatch rules): ship v9-qo5 unchanged.**
**Override candidate: `qo=7, ms=4, te=2.33, alpha=0.147`** — beats v9-qo5 merged 37,922 vs 29,007 (+30.7%), worst-of-3 12,145 vs 9,013 (+34.7%), walk-forward 3/3.

Read `Round 1/analysis/aco_pass2_6_summary.md` Section 8 before deciding. Summary of the conflict:

| Gate | Result | Meaning |
|---|---|---|
| Adjacency | PASS (ratio 0.82-0.97) | Winner is not an isolated peak; top-5 are clustered |
| Sensitivity | FAIL (-17% at qo+10%) | Going from qo=7 to qo=8 collapses fills (structural liquidity cliff) |
| Walk-forward | PASS 3/3 | On every chronologically-held-out day, qo=7 ms=4 beats v9-qo5 by +25% to +36% |

The dispatch's strict rule: any ±10% perturbation dropping PnL >15% = reject. The dispatch's own note: walk-forward is "the only test that mimics live submission."

The sensitivity failure is a **known structural cliff at qo=8** (quotes sit too far from fair value), not fragility at qo=7. Adjacency already characterizes this. Whether that structural feature should veto a 3/3 walk-forward win is your call.

## Completed work

### A0 — champion_baseline_anchoring (sonnet) — PASS
v9-qo5 per-day ACO: -2=9,201 / -1=10,793 / 0=9,013 (merged 29,007). Worst-of-6 = 4,139 (half-2 day -2). A3 decomp: 96.4% passive, **0 aggressive fills at te=3** (the knob is vestigial). Reproduced `baselines.json` exactly. A3 tagging module at `a3_tagging.py`.

### A1 — parameter_space_designer (opus) — PASS
4-param search space in `search_space.json`: qo int[2,8], ms int[4,12], te float[1.5,5.0], alpha float[0.05,0.25]. Seed=42, n=300. Excluded `panic_threshold` (no empirical basis) and `quote_size_bid/ask` (mechanical no-op: P2.5 fill model caps at 1 unit/event).

### A2 — lhs_joint_search (opus) — PASS, surfaced key methodology finding
- **Critical methodology finding:** tagging-layer replay is **INVERTED** across qo changes (Spearman ρ=-0.74). Cached fill streams are qo-specific; candidates with qo≠cached-qo simulate with ~0 fills. Agent correctly fell back to full prosperity4btest GT on 250/300 combos (~17 min wall time).
- Null-baseline: median worst3 = 9,116 (already above v9-qo5's 9,013); 95th pct = 11,442; meaningful-improvement threshold = 11,340; 17 combos above.
- **v9-qo5 was on the rising slope of quote_offset, not the optimum. Pass 2.5 hit its own grid wall at qo=5.**
- Top 3 candidates all clustered at **qo=7**, ms∈{4,5}; worst3 ≈ 12,000 (+33% over v9-qo5).

### A3_refine — local_grid_refinement (opus) — MIXED (see "Action required")
- 312-combo local grid (L1≤3 around top-3 centers), all GT-evaluated, 9.9 min wall.
- **Bug fixed:** half-2 timestamp extraction on merged multi-day logs (days -1/0 used wrong ts boundary in earlier code paths).
- **Adjacency: PASS** (top-5 neighbor ratios 0.82-0.97).
- **Sensitivity: FAIL** (qo+10% → qo=8 drops worst-of-6 -17%, exceeding 15% threshold).
- **Walk-forward: PASS 3/3.** qo=7 ms=4 beats v9-qo5 on every held-out day (+27% to +36%).
- Decision per strict rules: `ship_qo5_unchanged`.

### A4_finalize — ship_decision_and_writeup (opus) — PASS
Wrote `Round 1/analysis/aco_pass2_6_summary.md` (13.1 KB, 10 sections). Section 8 documents the tension verbatim and defers the call to user. No trader file created per strict rule; spec is in Section 6 for user to promote manually if overriding.

## All artifacts

### Notebook
- `Round 1/analysis/aco_deep_eda_v2.ipynb` — Pass 2.6 (A0, A1, A2, A3, A4 cells)

### Code / modules
- `Round 1/analysis/a3_tagging.py` — reusable; **does NOT transfer to cross-qo searches** (A2 finding)

### Data
- `Round 1/analysis/search_space.json`
- `Round 1/analysis/baselines.json` (verified + qo5 A3 decomp added)
- `Round 1/analysis/scratch/a2_lhs_samples.json`
- `Round 1/analysis/scratch/a2_eval_results.json` (300 combos, tagging — informational only, unreliable)
- `Round 1/analysis/scratch/a2_eval_gt_all.json` (250 combos, GT)
- `Round 1/analysis/scratch/a2_top10_gt.json`
- `Round 1/analysis/scratch/a2_top3_candidates.json`
- `Round 1/analysis/scratch/a2_candidates/` (temp trader files)
- `Round 1/analysis/scratch/a3_local_grid.json` (312 combos)
- `Round 1/analysis/scratch/a3_local_grid_gt_corrected.json`
- `Round 1/analysis/scratch/a3_ship_decision.json`
- `Round 1/analysis/scratch/a3_candidates/` (temp trader files)
- `Round 1/analysis/scratch/a1_aco_make_patch.py` (reference only, do NOT apply)

### Plots
- `Round 1/analysis/plots/aco_pass2_6/a2_worst_of_6_dist.png`
- `Round 1/analysis/plots/aco_pass2_6/a3_heatmap_qo_ms.png`
- `Round 1/analysis/plots/aco_pass2_6/a3_heatmap_te_alpha.png`
- `Round 1/analysis/plots/aco_pass2_6/a3_heatmap_qo_te.png`

### Runs
- `Round 1/runs/pass2_6/` — A0's fresh baseline logs (v8 + qo5 × 3 days)

### Report
- `Round 1/analysis/aco_pass2_6_summary.md` (PRIMARY deliverable, 13.1 KB)

### NOT created
- **No new trader file in `Round 1/traders/`.** Per A3's strict-rule decision. If user overrides, the spec is in summary Section 6:
  - path: `Round 1/traders/trader-v9-aco-p2.6-qo7-ms4-te2.33-alpha0.147.py`
  - ACO_CFG: `quote_offset=7, max_skew=4, take_edge=2.33, ema_alpha=0.147, panic_threshold=0.75`

## Proposed commit messages

**Default path (ship qo5 unchanged):**
```
Pass 2.6: search expanded, ship v9-qo5 unchanged (sensitivity gate FAIL on qo=8 cliff; walk-forward 3/3 FAV qo=7)
```

**Override path (ship qo=7 ms=4):**
```
Pass 2.6: ship qo=7 ms=4 te=2.33 alpha=0.147 (walk-forward 3/3 +25-36% over v9-qo5; sensitivity gate overridden — qo=8 structural cliff, not winner fragility)
```

## Key recommendations for R2

1. **A3 tagging layer does not transfer** to any search where quote_offset varies. Pure GT prosperity4btest from the start.
2. **Walk-forward is the primary validator**, not a tiebreaker. Day-LOO and within-day halves both leak information.
3. **Search boundaries must expand past the prior-round champion.** Pass 2.5 hit its own grid wall at qo=5 because it capped there. Pass 2.6 found qo=7 by extending.
4. **Null-baseline thresholding is strong machinery.** Reuse it.

## Outstanding (optional)

- Passive fill counts for the qo=7 ms=4 candidate (A4 flagged as "not extracted"). Requires a single GT run with fill-count logging. Only needed if user overrides to ship.
- Session close per CLAUDE.md: append dated entry to `WORKLOG.md` and update `CLAUDE.md` "Decisions Made So Far" with whichever ship decision is made.
