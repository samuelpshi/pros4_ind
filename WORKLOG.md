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