# R4 Backtest Results

Append-only log of trader variants and 3-day backtest results.
All runs use `rust_backtester --dataset round4` from `~/prosperity_rust_backtester`.

---

## v1 — trader-r4-v1-velvetfruit-follow67.py (baseline)

**Logic:** Mark 67 follower on VELVETFRUIT_EXTRACT (down-weighted to ±50 / ±100 target per [FH_OLIVIA_BLUEPRINT.md](counterparty/FH_OLIVIA_BLUEPRINT.md) §8.1) + Mark 55 jump overlay (§8.2) + passive 0-bid strip on VEV_6000/6500 (§8.3). 2000 ts reactive window for M67 lifts, 3000 ts for M55.

**Results:**

| Day | Final PnL | Own trades |
|-----|-----------|------------|
| 1   | +2,230    | 8          |
| 2   | +3,759    | 27         |
| 3   | −2,505    | 22         |
| **Total** | **+3,484** | 57 |

Mean = $1,161/day, std = $3,135/day. All PnL came from VELVETFRUIT_EXTRACT; strip legs captured $0 (Mark 01's queue priority on VEV_6000/6500 blocked any fills, as predicted by §8.3).

**Notes:**
- Day 3 loss matches the §8.1 prediction — Mark 67 was −$8/unit per [FINDINGS_PART3.md](counterparty/FINDINGS_PART3.md) #12 cross-day stability ranking, and we mirrored that.
- Mean PnL is positive but std is comparable in magnitude → mean/std = 0.37, well below "straight-line-up" hard rule #3 standard.
- Total own_trades = 57 over 30k ticks is very low; the strategy is almost dormant most of the time (M67 only fires ~165× across 3 days; reactive window 2000 ts means most ticks have no signal).

**Next iterations to try:**
- v1.1: add realised-edge gate (§8.1).
- v1.2: widen reactive window from 2000 → 5000 ts.
- v1.3: bigger target sizing (±100/±200 ≡ full FH-style follow).
- v1.4: smaller target sizing (±30/±60).
- v1.5: drop persistent-MM legs (reactive-only).

---

## Sweep summary — v1 family (target/window/MM tuning)

| Variant | Logic delta vs v1            | D1     | D2     | D3      | Total   | Notes |
|---------|------------------------------|--------|--------|---------|---------|-------|
| v1      | baseline                      | +2230  | +3759  | −2505   | **+3484** | Reference |
| v1.1    | + realised-edge gate          | +2230  | +3714  | −2669   | +3275   | Gate fires too late within a day; state resets per-day |
| v1.2    | reactive window 2000→5000     | +2246  | +3561  | −2669   | +3138   | Marginal D1 gain, D2/D3 worse |
| v1.3    | target ±100/±200 (FH-full)    | +2119  | +3231  | −3018   | +2332   | Bigger target HURTS — adverse fills at higher prices when chasing |
| **v1.4**| target ±30/±60 (tighter)      | +2246  | +3550  | −2237   | **+3559** | Best — tighter target reduces D3 damage |
| v1.5    | drop persistent MM legs        | +1290  | +1941  | −1890   | +1341   | MM legs were net positive ~$2k contribution |

**Conclusion:** v1.4 is the winner ($3559 total, $1186 mean, std ~3000). Mean/std = 0.40, still well below "straight-line-up" standard but the best of the family. Marginal gains plateau here — further parameter tuning unlikely to move the needle materially. Time to add product diversification (HYDROGEL_PACK + VEV_4000 spread-capture) to dilute the M67-day-3 risk via uncorrelated edges.

---

## Variants archived in `R4/traders/`

- `trader-r4-v1-velvetfruit-follow67.py` — baseline
- `trader-r4-v1.1-edge-gated.py` — + realised-edge gate
- `trader-r4-v1.2-wider-window.py` — wider reactive window
- `trader-r4-v1.3-bigger-target.py` — full ±100/±200 target
- `trader-r4-v1.4-tighter-target.py` — **WINNER** ±30/±60
- `trader-r4-v1.5-no-mm.py` — reactive-only (no MM)

Next: v2 adds HYDROGEL_PACK strategy (port from R3) + delta-1 quoting + retains v1.4's tuning for the M67 leg.

---

## v2 — trader-r4-v2-combined.py (M67 follower + HYDROGEL_PACK MM + strip)

**Logic:** v1.4's M67 follower verbatim (target ±30/±60, reactive window 2000 ts, MM legs at ±1 inside spread when spread ≥ 2) + R3's `trader-r3-v1-hydrogel.py` ported verbatim (EMA-50 fair value, take_edge 4, quote_offset 3, passive_size 30, take_cap 50, skew_strength 1.0) + passive 0-bid strip on VEV_6000/6500. VEV_4000 intentionally NOT traded (Mark 14 makes +$10.59/u every day, defensive avoidance per FINDINGS_PART3.md §8).

**Results:**

| Day | Final PnL | Own trades | HYDROGEL | VELVETFRUIT |
|-----|-----------|------------|----------|-------------|
| 1   | +7,244    | 21         | +4,998   | +2,246      |
| 2   | +5,269    | 100        | +1,719   | +3,550      |
| 3   | −2,358    | 40         | −121     | −2,237      |
| **Total** | **+10,155** | 161 | +6,596 | +3,559 |

Mean = $3,385/day, std = $5,071, **mean/std = 0.67** (vs v1.4's 0.40 — significant improvement). HYDROGEL is the new top earner, contributing 65% of total PnL across 3 days. Strip legs still $0 (Mark 01 queue priority unchanged).

**Why HYDROGEL works so well on R4 data:** the R3 EDA findings (lag-1 ACF = −0.13, demeaned-level half-life ~300 ticks, fixed ~16-wide spread) clearly transfer to R4 — the product behaviour is the same. EMA-anchored MM with inventory skew is well-matched to a wide-spread mean-reverting product.

**Day 3 risk now diluted:** HYDROGEL essentially flat on D3 (−121), so the M67 D3 loss is no longer the dominant story. v2 is the production candidate.

**Open questions / next iterations:**
- v2.1: should we cautiously add VEV_4000 quoting? Mark 14 dominates but maybe we can opportunistically take fills inside Mark 14's spread without crossing him. Risk of being the patsy if we miscalibrate.
- v2.2: the 9 voucher strikes we're not trading (VEV_4500/5000/5100/5200/5300/5400/5500/6000/6500) may have edge from BS-pricing residuals — much bigger build, defer to v3+.
- Strip (v2 leg 3) producing $0 across 30k ticks confirms §8.3 hypothesis. Not worth iterating on.
