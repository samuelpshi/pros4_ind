# Round 1 — Archive

Superseded artifacts from the Round 1 workflow. Nothing in here is active; the live trader and governing analyses live under `Round 1/traders/` and `Round 1/analysis/`.

**Date archived:** 2026-04-17 (end of Round 1 cleanup pass).

---

## Why these were archived

Work on Round 1 proceeded in several passes. The passes preserved here as reference, but not on the active path, are:

- **Passes 3 and 4 — KELP-analog rewrite (`trader-v9-r1*`)**: a full rewrite of ACO around a KELP-style mmbot-mid fair value with a reversion-beta framework. 3-day local backtest showed it underperformed the v8 baseline by 7,844 XIRECS (v9 merged 248,735.5 vs v8 256,580.0). Superseded by Pass 2.5.
- **Pass 5 — ACO inventory-penalty corner test**: the 2-corner sweep produced a spread of +270 XIRECS against a 2,000-XIREC gate. Gate failed; the full sweep was never run. See `Round 1/analysis/pass5_corner_test_verdict.md` and `pass5_ship_decision.md` (both kept in `analysis/`; the supporting trader-side scripts and logs moved here).
- **Pass 6 — IPR skim parameter sweep corner test**: 8-corner test produced a spread of 91 XIRECS against a 5,000-XIREC gate. Gate failed, full 400-run sweep not executed. See `Round 1/analysis/pass_ipr_sweep_analysis.md` (kept; its log path references point into this archive).
- **Patch C1 — ACO_TAKE_WIDTH 1.5 → 3.0**: hypothesis falsified (−259 XIRECS). See `Round 1/analysis/patchC1_test_results.md` (kept).
- **Misc scratch**: one-off parsing scripts, cached sweep scripts, and scratch trader copies used during the above passes.

What remains on the active path:

- `Round 1/traders/trader-v8-173159.py` — shipped v8 baseline (ACO `qo=2, ms=5, te=3`; IPR Config A drift capture).
- `Round 1/traders/trader-v9-aco-qo5-ms8-te3.py` — **Pass 2.5 ACO ship candidate (`qo=5, ms=8, te=3`), pending R1 live verification.** Local 3-day backtest: +45% / +55% / +72% over v8 on days −2/−1/0. Promotion to the submission slot deferred until the R1 live log confirms the local ranking transfers.
- `Round 1/traders/trader-v8-173159-jmerle.py` — visualizer-instrumented variant of v8. No jmerle-instrumented variant of the Pass 2.5 ship candidate was produced.
- `Round 1/analysis/aco_deep_eda_summary.md` plus Pass 2.5 plots (`plots/aco_decomp_day-*.png`, `plots/aco_deep/*`) — the source of truth for the ship decision.

---

## `trader-v9-cb.py` clarification

The Pass 2.5 A1 dispatch block referenced a file named `trader-v9-cb.py` as the "v8 baseline for decomposition." **That file does not and never did exist on disk** — a repo-wide search at archive time (`**/trader-v9-cb*`) returns zero hits.

The actual baseline used by A3 was `trader-v8-173159.py`. Verified at archive time that this file contains:

- `ACO_CFG` (line 53) with `ema_alpha=0.12`, `quote_offset=2`, `take_edge=3`, `max_skew=5`, `panic_threshold=0.75` (lines 54–58).
- `aco_take` (line 114) and `aco_make` (line 133).

These are the exact fields and functions A3 decomposed against, and the accounting identity (spread_capture + reversion_capture + inventory_carry + eod_flatten == total PnL, zero residual) held on all three days.

**Note for future readers:** `trader-v9-cb.py` was a local working-copy name for the same content as `trader-v8-173159.py`; A3 validated against the latter and the accounting identity held.

---

## Layout

```
Round 1/archive/
├── README.md                    (this file)
├── traders/                     ← superseded v9-r1 KELP rewrite (4 files)
│   ├── trader-v9-r1.py
│   ├── trader-v9-r1-jmerle.py
│   ├── trader-v9-r1-aco-only.py
│   └── trader-v9-r1-ipr-only.py
├── strategies/                  ← Pass 3/4 planning docs for the archived v9-r1
│   ├── PLAN.md
│   └── IMPLEMENTATION_NOTES.md
├── scratch/                     ← one-off scripts and scratch trader copies
│   ├── parse_logs.py
│   ├── parsed_results.json
│   ├── sweep_aco_0_025.py
│   ├── sweep_aco_0_050.py
│   ├── sweep_aco_inventory_penalty.py
│   ├── trader-v9-r1-patchC1.py
│   └── trader-v9-r1-patchC1-aco-only.py
├── runs/                        ← superseded backtest logs
│   ├── v9_day-{-2,-1,0}.log, v9_merged.log, v9_merged_worse.log
│   ├── v9_aco_only_merged.log, v9_ipr_only_merged.log
│   ├── mark_test_aco.log, mark_test_ipr.log
│   ├── ipr_sweep/               (9 logs — Pass 6 corner test)
│   ├── pass5/                   (2 logs — Pass 5 ACO inv-penalty corners)
│   └── patchC1/                 (5 logs — Patch C1 test)
└── analysis/plots/              ← 8 Pass 2 plots not referenced by Pass 2.5
    ├── aco_flow_vs_ret.png, aco_return_autocorr.png, aco_rolling_mean.png
    ├── cross_product_corr.png, cross_product_spread.png
    ├── ipr_flow_vs_ret.png, ipr_return_autocorr.png
    └── mid_price_all_days.png
```

---

## Cross-reference paths from kept analyses

Two kept `.md` files reference paths under this archive:

- `Round 1/analysis/pass_ipr_sweep_analysis.md` §7 + `Round 1/analysis/sweep_log_index_ipr.md` — 9 log paths repointed to `Round 1/archive/runs/ipr_sweep/*`.
- `Round 1/analysis/aco_slow_ema_calibration.md` §1 — one reference to `trader-v9-r1-aco-only.py` repointed to `Round 1/archive/traders/trader-v9-r1-aco-only.py`.

Both updates are applied in the commit that follows the filesystem-move commit.
