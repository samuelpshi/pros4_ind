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