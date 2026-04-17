# Pass 5 — Ship Decision

**Date:** 2026-04-16  
**Author:** Agent 10 (Ship Decision Analyst)  
**Sources:** `pass5_corner_test_verdict.md`, `v9_backtest_results.md`, `trader-v8-173159.py`, `trader-v9-r1.py`

---

### 1. Summary Table

| Option | ACO | IPR | Total | vs v8 | Risk |
|--------|-----|-----|-------|-------|------|
| A. SHIP_V9_UNTUNED | 12,448 | 236,288 | 248,736 | −3.06% (−7,844) | low |
| B. SHIP_V8 | 18,556 | 238,024 | 256,580 | 0% (baseline) | medium — reverts IPR limit fix and circuit breaker |
| C. SHIP_V9_PATCHED | est. 14,000–17,000 | ~236,288 | est. 250,000–253,000 | ~−1.4% to +−0.1% | medium |

v8 IPR = 238,024 (merged 3-day). Source: `v9_backtest_results.md` §3.

---

### 2. Root Cause of ACO Gap

**v8 fair value** (`trader-v8-173159.py` lines 280–283): simple EMA on VWAP mid with `alpha=0.12`.
```
fv = 0.12 * vwap_mid + 0.88 * prev_fv
```
This is slow-smoothing: fv tracks a 8-tick-lag weighted average. The take layer fires at `fv ± 3` (take_edge=3, line 44/107). Any ask ≤ fv−3 is hit; any bid ≥ fv+3 is hit. **Effective take threshold is 3 ticks.**

**v9 fair value** (`trader-v9-r1.py` lines 191–214): mmbot-mid filtered by adverse_vol=15, then reversion-adjusted by beta=−0.45. Take layer fires at `fv ± 1.5` (ACO_TAKE_WIDTH=1.5, line 56/259). **Effective take threshold is 1.5 ticks.**

The structural gap has two sources:

1. **Take width halved** (line 56 in v9 vs line 44/107 in v8): v8 takes at ±3, v9 takes at ±1.5. With ACO's typical spread of 10–20 ticks, v9 takes far fewer resting orders that are truly mispriced — it misses profitable takes that v8 captures. This is the dominant cause.

2. **Adverse-volume filter fallback** (v9 line 199–200): when no orders exceed volume threshold 15 on either side, `aco_mmbot_mid` returns `prev_mmbot_mid` (stale). During sparse book conditions, fv stalls while the market moves, making the take layer dormant. v8 has no such filter — it always quotes on live VWAP mid.

The reversion beta (−0.45) is directionally appropriate (lag-1 autocorrelation = −0.494) but adds complexity without compensating for the take-width and filter issues above.

---

### 3. Option C: Candidate 1-Line Patches

**Patch C1 — Widen ACO take width: `ACO_TAKE_WIDTH` from `1.5` → `3.0`**  
(v9 line 56)  
Matches v8's effective take threshold exactly. Take layer fires at ±3 ticks from fv, identical to v8's `take_edge=3`. Expected to recover the largest share of the 6,108 gap since v8's take layer is the primary fill driver. Risk to IPR: **zero** (products independent, confirmed Diagnostic §5 in `v9_backtest_results.md`).

**Patch C2 — Reduce adverse-volume filter: `ACO_ADVERSE_VOLUME` from `15` → `5`**  
(v9 line 47)  
Lowers the bar for "mmbot order" classification; far fewer ticks will fall back to stale `prev_mmbot_mid`. The mmbot mid will track live prices more closely, keeping the take layer active through thin book periods. Risk to IPR: **zero**. Secondary benefit only — should be paired with C1 rather than applied alone.

**Patch C3 — Add EMA fallback when mmbot_mid falls back: replace the fallback `return prev_mmbot_mid` with `return vwap_mid(depth)` in `aco_mmbot_mid`**  
(v9 line 200)  
When both sides of the filtered book are empty, fv currently freezes. Using live VWAP mid as fallback (exactly what v8 does) prevents stale fv and keeps both take and make layers reactive. Risk to IPR: **zero**.

---

### 4. Recommendation

**Top pick: Option C — SHIP_V9_PATCHED, applying Patch C1 only (ACO_TAKE_WIDTH: 1.5 → 3.0).**

C1 is a single constant change on one line (v9 line 56) with a clean, mechanistic justification: v8's dominance in ACO comes directly from a take threshold twice as wide. C1 restores that threshold without touching the mmbot-mid formula, the reversion beta, or any IPR logic. IPR is structurally independent (zero cross-product interaction, verified). The gap is 6,108 XIRECS (2.4% of total); if C1 recovers even half, v9 crosses the 3-day combined threshold with margin. Shipping v8 (Option B) would silently revert the IPR position-limit fix (40→80) and circuit breaker — a regression on the product that matters most. Shipping v9 untuned (Option A) leaves a recoverable 6,108 gap on the table with one day of competition remaining.
