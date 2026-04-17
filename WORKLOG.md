# Pepper Root Work Log

## 2026-04-16 (Session 1) — Setup & data orientation

**What we did:**
- Cloned repo, installed Claude Code in VS Code
- Confirmed data structure: 3 days of prices + trades, semicolon-separated
- Read Ethan's existing analysis notebook — purely visual, no statistical tests
- Reviewed our_trader/173159.py (v8) — built on assumed upward drift, validated on 1 day only

**Key open questions:**
- Does pepper root actually drift up consistently across all 3 days, or is the v7 PnL of 3660 a one-day fluke?
- Are there hidden bot signals (Olivia-style trades at extrema)?

**Next session starts with:**
- Build analysis/pepper_root_deep_dive.ipynb
- Cell 1: load + sanity-check data
- Goal of next session: get through Phase 1 (cells 1-5)

---

## 2026-04-16 (Session 2) — Drift validation, Config A committed

**What we did:**
- Created `analysis/pepper_root_deep_dive.ipynb` (Cells 1-2 run)
- Investigated flash crashes to mid=0 (empty order books, not real crashes)
- Confirmed position limit is 80 (v8 hardcoded 40)
- Simulated multi-timestep greedy entry for targets 80 and 70
- Committed Config A: target_long=80, entry_take_cap=80, skim_min_pos=75
- Built `analysis/backtest.py` (minimal matching engine from CSV data)
- Ran backtest on all 3 days

**Findings:**
- IPR drift: +1001.3/day, std=1.8 across 3 days — deterministic, not luck
- Flash crashes: 54 empty-book rows (mid=0), 7.7% one-sided rows. Drift unchanged after cleaning
- Entry slippage: ~9.4/unit, fills target=80 by ts=400 (0.04% of day), 99.1% theoretical capture
- Backtest PnL (v9 Config A): IPR +79,351/day avg, ACO +2,206/day avg, total +244,673 across 3 days
- v8 baseline was +3,660/day IPR only — Config A is 21.7x improvement
- Zero reversal signals fired across all 3 days
- Zero skim fills — skim overlay is irrelevant to PnL on this data
- Deep bid feature is dead code at target=limit (no room)

**Next session starts with:**
- Cell 3: trade size histogram + Olivia signal hunt
- Consider simplifying trader (remove dead reversal/deep-bid code paths)
- Consider raising or removing reversal thresholds to avoid catastrophic false trigger on unseen data

---

## 2026-04-16 (Session 3) — Prep Pass 1: mechanics, historical playbook, repo audit

**What we did:**
- Ran Prep Pass 1 as three parallel agents (Product Mechanics Analyst, Historical Strategy Archivist, Repository Steward)
- Created `Round 1/docs/` with two new reference docs
- Updated `CLAUDE.md` Repo Layout, backtester invocation, jmerle variant description, strategy-naming convention, data-day convention

**Outputs:**
- `Round 1/docs/r1_product_mechanics.md` — R1 rules spec for osmium + pepper root (~1,350 words; 5 open questions for osmium, 6 for pepper root)
- `Round 1/docs/imc3_r1_playbook.md` — IMC3 R1 historical playbook for RAINFOREST_RESIN, KELP, SQUID_INK (~3,235 words; ~55 preserved numeric parameters) with bidirectional archetype↔product mapping matrix
- `CLAUDE.md` — minimal-churn updates to Repo Layout only; Hard Rules / Verified Findings / Position-Limit Rules / Vocabulary left intact

**Findings / flags:**
- Mechanics doc blocker: `Round 1 - "Trading groundwork".html` filename contains Unicode curly quotes that prevented Read/Grep from opening it. Round-specific product lore, fundamental anchors, and any insider mechanic stated in that HTML are currently unconfirmed — flagged as open questions in the mechanics doc. Needs a follow-up pass (rename the file or read via an alternate method).
- Playbook preserves specific numerics (e.g. RAINFOREST_RESIN fair_value=10,000, passive quotes at 9,999/10,001; KELP reversion_beta=-0.229, adverse_volume=15; SQUID_INK zscore_period=150, entry_z=1.25, exit_z=0.3).
- Prior-round archetypes identified: stable MM (Resin), mean-reverting / adverse-selection-aware (Kelp), trending / momentum-driven (Squid Ink). Pass 2 will match current R1 products to these archetypes.

**Next session starts with:**
- Resolve the Trading groundwork HTML read blocker (rename file with ASCII quotes, or read via a tool that handles Unicode path bytes) and fill in the mechanics doc's open questions
- Prep Pass 2: synthesize mechanics + playbook + current findings into concrete strategy deltas for `trader-v8-173159.py` (pepper root first)
- Revisit deferred Session 2 follow-ups: Cell 3 Olivia hunt, dead-code cleanup, reversal-threshold review

---

## 2026-04-16 (Session 4) — Prep Pass 2: Statistical EDA, ACO analysis, bot identity

**What we did:**
- Installed scipy + statsmodels
- Wrote and executed `Round 1/analysis/r1_eda_script.py` (all computations, saves JSON + PNGs)
- Created `Round 1/analysis/r1_eda.ipynb` (12 cells, all executed end-to-end, 12 PNG plots in `plots/`)
- Created `Round 1/analysis/r1_eda_summary.md` with findings, strategy recommendations, and 11-question triage

**Findings (specific numbers):**
- ACO ADF: stationary within each day (p=0.0048, 0.0000, 0.0147 for days -2, -1, 0). OU half-life = 8.4 timesteps. Archetype = KELP.
- ACO return autocorr: lag-1 = −0.494 (strong mean reversion), lags 5/20/100 ≈ 0 (no persistence). Variance ratio VR(2)=0.506, VR(16)=0.089.
- ACO "hidden pattern": level autocorr at lag-1000 = −0.123, lag-2000 = −0.340. Bounded oscillation with half-period ~1000–2000 timesteps. This IS the lore-hinted pattern.
- ACO suggested reversion_beta: −0.40 to −0.50 (vs KELP's −0.229; ACO reverts harder).
- IPR ADF: unit root on all 3 days (p=0.935, 0.802, 0.894). OU half-life = 279,697 timesteps (infinite). Archetype = novel deterministic drift, no IMC3 analog.
- IPR intraday quartile mean return: uniformly 0.107–0.110 XIRECS/tick across all 4 quartiles and all 3 days. No timing advantage.
- IPR cross-product return correlation: r=0.007, p=0.264 (not significant). ACO and IPR are independent.
- Cointegration: statistical artifact — apparent cointegration is driven by ACO's own stationarity, not co-movement.
- Trade-sign flow → next-tick return: ACO r=−0.002 (p=0.906), IPR r=−0.007 (p=0.734). No adverse-selection signal in either product.
- Order-book depth: L1=100%, L2≈68%, L3≈1.6–2.6% — effectively 1–2 levels. L3 is negligible.
- Bot identity: all buyer/seller values are NaN (anonymized). No Olivia-style signal exists in Round 1.
- Open questions triage: 4 resolved by EDA, 0 by HTML re-read, 7 still open.

**Next session starts with:**
- Pass 3: synthesize EDA findings into concrete strategy code changes for `traders/trader-v8-173159.py`
  - IPR: remove reversal thresholds (zero reversals in 3 days; false trigger is catastrophic; raise guard to EMA delta < −50 minimum if keeping at all)
  - ACO: evaluate switching from current EMA fair value to KELP-style filtered mmbot mid + reversion_beta = −0.40 to −0.50
  - ACO: prototype the medium-term oscillation regime filter (position in trailing-500-tick range → directional bias)
  - Backtest all changes across all 3 days; accept only if mean PnL increases without large variance increase

---

## 2026-04-16 (Session 5) — Prep Pass 3: Code-Ready Strategy Plan

**What we did:**
- Read all 8 required source docs in order: ipr_mm_synthesis.md (BINDING), r1_eda_summary.md, r1_eda.ipynb, r1_product_mechanics.md, imc3_r1_playbook.md, pepper_root_findings.md, trader-v8-173159.py, backtest.py
- Wrote `Round 1/strategies/PLAN.md` — full code-ready plan for Pass 4 implementation

**Findings / decisions:**

ACO (new strategy):
- Strategy family committed: KELP (imc3_r1_playbook.md §2) — filtered mmbot mid + reversion-beta fair value, take/clear/make stack
- Timescale decision: trade fast timescale only (OU half-life 8.4 ts); incorporate slow timescale (1000–2000 ts oscillation, lag-2000 autocorr −0.340) as passive sizing bias on make layer — not a separate signal stream
- Fair value: mmbot_mid (adverse_volume=15, KELP default) + reversion_beta=−0.45 (midpoint of empirical −0.40 to −0.50 range)
- Window: 1 lag (no rolling window needed; only prev_mmbot_mid required, stored in traderData)
- Slow-oscillation bias: trailing 500-tick deque; top/bottom 20% of range halves passive size on that side
- PnL marking: mark-to-mid (matches backtest.py, no backtest changes required; resolves ACO-5)
- Success threshold: mean ACO PnL >= +3,000/day vs. current baseline +2,206/day

IPR (targeted deltas only — Config A untouched):
- Delta (a): passive entry bids at fv(t)−spread/2 during accumulation; fv(t) = price_at_day_start + 0.10013/tick × t; fallback to greedy take after N=20 ts
- Delta (b): skim_offset 2→1, skim_size 5→8; keeps skim_min_pos=75 and refill_max_size=10
- Delta (c): long-only floor hard-coded; remove symmetric short-skim block from ipr_orders()
- Delta (d): drift-reversal circuit breaker — W=500 ts, k=5.0, replaces EMA gap logic entirely; action = freeze target at 0 (no active dump)
- Circuit breaker cost of false alarm at midday: ~40,052 XIRECS (acceptable given W=500+k=5 gives effectively-zero false-trigger rate on training data)
- Open question triage: 2 Answered (ACO-5, IPR-6), 2 Validate live (ACO-1, IPR-3), 3 Unresolvable/assumption (ACO-3, IPR-2, IPR-5)

**Next session starts with:**
- Pass 4: Implement PLAN.md directly into `Round 1/traders/trader-v8-173159.py`
  - Step 1: ACO — replace ACO_CFG + aco_take/aco_make with ACO_CFG_V2 + aco_mmbot_mid + aco_fair_value + aco_take_v2 + aco_clear_v2 + aco_make_v2 + kill switch
  - Step 2: IPR deltas — (c) long-only floor + remove dead short-skim block; (d) circuit breaker replacing EMA gap logic; (a) passive entry bid with greedy fallback; (b) skim_offset=1, skim_size=8
  - Step 3: run backtest.py, confirm ACO PnL >= +3,000/day and IPR PnL >= +79,350/day; compare full 3-day totals
  - Step 4: parameter sweep ACO reversion_beta (−0.25 to −0.55, step 0.05) and IPR skim_offset (1 to 3)
  - Step 5: run drift-reversal stress test (ts 25/50/75% reversal) on IPR circuit breaker
  - Commit passing version as v10
---

## 2026-04-17 — Round 1 directory cleanup (post-Pass 2.5 archive)

**What we did:**
- Built KEEP/ARCHIVE/DELETE classification over all Round 1/, runs/, scratch/ artifacts
- Created Round 1/archive/ preserving subdir structure and moved 38 files (v9-r1 KELP rewrite + jmerle/aco-only/ipr-only variants, Pass 3/4 strategies/ planning MDs, Pass 5/6 sweep logs, patchC1 logs, mark_test logs, 7 scratch scripts/JSON, 8 Pass 2 plots not referenced by Pass 2.5)
- Deleted tracked clutter: 4 .DS_Store files, 3 __pycache__ directories (19 .pyc files)
- Wrote Round 1/archive/README.md with layout, reasoning, and the trader-v9-cb.py clarification note
- Verified trader-v8-173159.py carries the expected ACO_CFG (ema_alpha=0.12, quote_offset=2, take_edge=3, max_skew=5, panic_threshold=0.75) and aco_take/aco_make functions — A3's accounting identity is consistent
- Updated CLAUDE.md: Active Context broadened to both products; added Pass 2.5 ship candidate to Repo Layout; added both ACO param sets with "pending R1 live verification" note; updated Decisions Made So Far
- Repointed 9 log paths in pass_ipr_sweep_analysis.md + sweep_log_index_ipr.md to Round 1/archive/runs/ipr_sweep/
- Repointed 1 trader reference in aco_slow_ema_calibration.md to Round 1/archive/traders/trader-v9-r1-aco-only.py
- Committed in two logical commits: (1) filesystem moves + archive README, (2) MD text updates + this WORKLOG entry

**Findings:**
- trader-v9-cb.py (referenced in the Pass 2.5 A1 dispatch as "v8 baseline for decomposition") does NOT exist on disk — repo-wide glob for `**/trader-v9-cb*` returns zero hits. A3's actual baseline was trader-v8-173159.py; the v9-cb name was a working-copy label for the same content.
- Active Round 1/traders/ after cleanup: 4 trader files (v8 + v8-jmerle + Pass 2.5 ship candidate + Ethan's trader1.py) + 2 _mark_test scripts. Was 8 before (4 archived).
- Active runs/ after cleanup: 7 log files (v8_day-{-2,-1,0}.log + v8_merged.log as A3 ground truth; qo5_ms8_te3_day-{-2,-1,0}.log as A8 ship-candidate verification). Was 29 before (22 archived).

**Next session starts with:**
- Confirm R1 live submission: which trader is going in — v8 baseline (trader-v8-173159.py) or Pass 2.5 ship candidate (trader-v9-aco-qo5-ms8-te3.py)?
- If Pass 2.5 candidate ships: capture the live log, compare live ACO PnL vs local backtest, update CLAUDE.md "Decisions Made So Far" with the verified outcome, and promote (or revert) accordingly.
- If v8 ships: keep ship candidate on the bench, treat Pass 2.5 as deferred for R2.
