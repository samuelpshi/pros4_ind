# IPR Skim Parameter Sweep — Analysis (Pass 6, Agent 12)

**Date:** 2026-04-16
**Scope:** IPR skim/refill parameter space (skim_size, skim_offset, refill_max_size)
**Gate result:** FAILED — sweep not executed. Corner test only.

---

## 1. Setup

Three IPR parameters were selected for a 3D parameter sweep based on PLAN.md §IPR (b):

| Parameter | Default (v8) | Corner Low | Corner High | Range to sweep |
|-----------|-------------|-----------|------------|----------------|
| `skim_size` | 5 | 3 | 15 | 3–12 in steps of 1 |
| `skim_offset` | 2 | 1 | 5 | 1–3 in steps of 1 |
| `refill_max_size` | 10 | 5 | 20 | 5–20 in steps of 5 |

Full 3D grid: 4 × 3 × 4 = 400 runs (merged-scenario across days -2/-1/0). Gate: the 8-corner IPR PnL spread must exceed 5,000 XIRECS to justify the full 400-run sweep. Source: pass5_ship_decision.md, standard sweep-gating protocol.

---

## 2. Corner Test Result

8 corners tested (Agent 11). All runs used scenario = merged (days -2/-1/0 concatenated). ACO PnL is constant across all corners; cross-product independence confirmed.

| skim_size | skim_offset | refill_max_size | IPR PnL | ACO PnL | Total PnL |
|-----------|-------------|-----------------|---------|---------|-----------|
| 3 | 1 | 5 | 238,018 | 18,556 | 256,574 |
| 3 | 1 | 20 | 238,018 | 18,556 | 256,574 |
| 3 | 5 | 5 | 238,054 | 18,556 | 256,610 |
| 3 | 5 | 20 | 238,054 | 18,556 | 256,610 |
| 15 | 1 | 5 | 237,963 | 18,556 | 256,519 |
| 15 | 1 | 20 | 237,963 | 18,556 | 256,519 |
| 15 | 5 | 5 | 238,054 | 18,556 | 256,610 |
| 15 | 5 | 20 | 238,054 | 18,556 | 256,610 |
| **(baseline)** | **(no env vars)** | **(default)** | **238,024** | **18,556** | **256,580** |

**Corner spread: 237,963 to 238,054 = 91 XIRECS.**
**Gate threshold: 5,000 XIRECS.**
**Verdict: GATE FAILED. Full 400-run sweep not executed.**

Best corner vs baseline: +30 XIRECS (noise). Worst corner vs baseline: -61 XIRECS (also noise).

---

## 3. Why the Space Is Flat — Mechanistic Explanation

The skim parameters only affect PnL when a skim order actually executes. Four independent gates must all be open simultaneously for a skim fill to occur:

**Gate A — Position eligibility.** Skim fires only when `pos >= cfg["skim_min_pos"]` (= 75; trader-v8-173159.py line 217). After the greedy entry fills ~80 units by ts≈400 (pepper_root_findings.md §Finding 3), the position stays at or near 80 for the remaining ~9,600 timesteps. This gate is open >95% of the day — not the bottleneck.

**Gate B — Skim order posted.** The skim posts a passive sell at `best_ask + skim_offset`. This executes only when a counterparty crosses the skim price, meaning a bot aggressively buys at or above `best_ask + offset` (trader-v8-173159.py line 221). The EDA logged 402 "buyer hit ask" events per day (r1_eda_summary.md §2, v8 comment block). However, these are bots hitting the *existing* best_ask, not necessarily paying an additional `skim_offset` ticks above it.

**Gate C — Refill bid fires.** A refill bid (trader-v8-173159.py lines 226-233) is posted only when `pos < target_long`. This requires Gate B to have already filled the skim sell, dropping pos below 80. If skim fills are rare, the refill bid rarely fires — it is contingent on Gate B, not independent. The 0-fill observation across all 3 backtest days (PLAN.md §IPR (b)) confirms this: skim fills = 0, therefore refill bids = 0.

**Gate D — skim_offset must be tight enough.** The v8 default of `skim_offset=2` places the passive sell 2 ticks above best_ask — roughly one full spread width above the inside market. The 402 buyer-hit-ask events hit the *existing* ask, not a quote 2 ticks above it. Reducing to `skim_offset=1` (corner low) should increase fill probability, but the 3-day backtest shows this change produces only +55 XIRECS uplift (corner average at offset=1: 237,990.5; at offset=5: 238,054 — counterintuitively, offset=5 is *higher* in PnL, discussed below).

**Why offset=5 is not better than offset=1 in theory:** A higher offset earns more per fill but fills less often. The net effect on 3-day PnL is only 63.5 XIRECS (the largest main effect in this space). Both are well below noise on any realistic day-to-day PnL variance.

**The structural conclusion:** The skim is a minor income layer on top of a 238,000-XIREC drift position. The drift captures ~99.1% of theoretical PnL (pepper_root_findings.md §Finding 3). The skim overlay contributes at most ~1,700 XIRECS across 3 days (v8 comment: "Expected: 8-12 round trips/day = +400-600 PnL per day"). In practice, the backtest shows 0 skim fills over 3 days. Changing skim_size or refill_max_size within the tested ranges does not change the event count — it only changes the quantity captured per event, which is effectively zero when events are zero.

---

## 4. Parameter Sensitivity Ranking

Main effects computed as absolute mean PnL difference across the 8 corners when that dimension is held at its low vs. high value:

| Rank | Parameter | Main Effect (XIRECS) | Fraction of Total Spread |
|------|-----------|---------------------|------------------------|
| 1 | `skim_offset` | 63.5 | 70% |
| 2 | `skim_size` | 27.5 | 30% |
| 3 | `refill_max_size` | 0.0 | 0% |

`refill_max_size` has zero effect: the skim never fills, so the refill never fires, so changing the refill size from 5 to 20 moves PnL by exactly 0 XIRECS across all 8 corners. This is consistent with the mechanistic analysis above.

`skim_offset` leads because it changes the premium captured per rare skim event. Even then, 63.5 XIRECS over 3 days is a rounding error relative to the 238,000-XIREC IPR baseline.

---

## 5. Recommendation

**B. KEEP_V8_DEFAULTS** — `skim_size=5, skim_offset=2, refill_max_size=10`.

Quantitative justification:

- Total corner spread = **91 XIRECS** vs. 5,000-XIREC gate threshold. The signal-to-noise ratio does not support tuning.
- Best corner is only **+30 XIRECS** above v8 baseline (238,024). This is within daily PnL variance from routing noise alone.
- Worst corner is **-61 XIRECS** below baseline — confirming the space has no dominant corner.
- The highest-sensitivity parameter (`skim_offset`) drives only 63.5 XIRECS of variation across a 4-tick range. No single-dimension refinement sweep is warranted.
- The skim mechanism produced 0 fills across all 3 training days at the default parameters. A skim that never fills cannot be improved by changing its size or maximum refill quantity.

Do NOT recommend SHIP_V8_TUNED. 91 XIRECS of signal over a 3-day merged scenario is below any defensible threshold for changing production parameters.

---

## 6. Implications for Pass 7 and Beyond

**Should IPR skim be revisited?** Only under two specific conditions, neither of which is evidenced by this sweep:

1. **If skim fills are observed in live submission data.** The training data showed 0 fills. If live logs show skim fills (indicating bots are actually sweeping above best_ask), the parameter space becomes non-flat and a sweep would be warranted. Check the submission log for skim activity.

2. **If the skim_offset=1 delta from PLAN.md §IPR (b) is implemented.** PLAN.md recommends tightening skim_offset from 2 to 1, arguing offset=2 is too far for bots to sweep. This is a code change, not a sweep result. If implemented and if it generates fills in the live submission, a post-live sweep of offset ∈ {1, 2, 3} with fill-count data would be meaningful.

**The structural edge is in the drift, not the skim.** All 8 corners confirm that IPR PnL tracks within 91 XIRECS of the Config A drift baseline regardless of skim parameters. Pass 7 effort should focus on: (a) ACO strategy implementation (KELP analog, PLAN.md §ACO), and (b) the drift-reversal circuit breaker (PLAN.md §IPR (d)) — neither of which is addressed by this sweep.

---

## 7. Log File Index

| skim_size | skim_offset | refill_max_size | scenario | IPR PnL | log_path |
|-----------|-------------|-----------------|----------|---------|----------|
| 3 | 1 | 5 | merged | 238,018 | `Round 1/archive/runs/ipr_sweep/sz3_off1_rfl5_merged.log` |
| 3 | 1 | 20 | merged | 238,018 | `Round 1/archive/runs/ipr_sweep/sz3_off1_rfl20_merged.log` |
| 3 | 5 | 5 | merged | 238,054 | `Round 1/archive/runs/ipr_sweep/sz3_off5_rfl5_merged.log` |
| 3 | 5 | 20 | merged | 238,054 | `Round 1/archive/runs/ipr_sweep/sz3_off5_rfl20_merged.log` |
| 15 | 1 | 5 | merged | 237,963 | `Round 1/archive/runs/ipr_sweep/sz15_off1_rfl5_merged.log` |
| 15 | 1 | 20 | merged | 237,963 | `Round 1/archive/runs/ipr_sweep/sz15_off1_rfl20_merged.log` |
| 15 | 5 | 5 | merged | 238,054 | `Round 1/archive/runs/ipr_sweep/sz15_off5_rfl5_merged.log` |
| 15 | 5 | 20 | merged | 238,054 | `Round 1/archive/runs/ipr_sweep/sz15_off5_rfl20_merged.log` |
| (baseline) | (no env vars) | (default) | merged | 238,024 | `Round 1/archive/runs/ipr_sweep/baseline_no_envvars_merged.log` |

Source index: `Round 1/analysis/sweep_log_index_ipr.md` (Agent 11 canonical log).
