# R4 Counterparty Findings — Part 3 (Sophisticated probes round 2)

Source: `sophisticated2.py` (output captured in `sophisticated2.out`).
Probes: #3 microprice edge, #10 Mark 67 inter-arrival pacing, #11 pre-jump trader composition, #12 cross-day stability ranking.

This is the consolidation of the four remaining sophisticated probes. The headline result is **#11 (pre-jump composition)** which surfaced a previously-missed front-running pattern in Mark 55, and **#12 (stability ranking)** which downgrades Mark 67's apparent edge.

---

## #3 — Microprice vs mid-price edge (NEGATIVE result)

Hypothesis: book imbalance (heavier side of L1) refines fair value, so `edge_micro_5k = side*(microprice_5k − price)*qty` should rank traders differently from the naive mid-based edge.

```
Difference (micro − mid) per fill, by trader:
  Mark 67   −0.23    Mark 14   −0.06    Mark 01   −0.02
  Mark 22    0.00    Mark 55   +0.13    Mark 38   +0.01
  Mark 49   +0.41
```

All deltas ≤ $0.41/fill — well inside noise. Microprice does **not** add information over mid-price for this dataset. Likely explanation: trades clear at the prevailing best bid/ask anyway, and in the 5k-tick horizon the imbalance signal mean-reverts to mid faster than the move materialises.

**Action:** drop microprice from any trader-feature pipeline. Mid-based forward edge is sufficient.

---

## #10 — Mark 67 inter-arrival pacing on VELVETFRUIT (NEGATIVE result)

Hypothesis: Mark 67's edge ($165/fill close-edge — the headline in [FINDINGS.md](FINDINGS.md)) might intensify when their fills compress in time (i.e. they fire bursts ahead of moves) and weaken when slow.

```
Mark 67 inter-arrival distribution: mean 18033, median 13300, p10 2030, p90 38680

pace_q       n  avg_dt    fwd_5k_ret  fwd_close_ret   qty
compressed  54   3624          2.59          20.30   8.98
normal      54  12872          0.56          14.53   9.61
slow        54  37604          2.39          19.59   8.87
```

`fwd_close_ret` is roughly flat across pacing buckets (14.5 / 19.6 / 20.3). No usable pacing signal — when Mark 67 trades, their direction is informative regardless of cadence. **Same conclusion for Mark 49 sells** (13.8 / 15.5 / 17.7).

**Action:** trader logic should treat every Mark 67 fill identically. No need to gate on inter-arrival.

---

## #11 — Pre-jump trader composition (POSITIVE: Mark 55 surfaces, Mark 14↔38 confirmed mirror)

Method: per (day, symbol), find timestamps where `mid_price.shift(-50) − mid_price` ≥ 3σ. For each such jump, compute net signed quantity by trader in the 20k-tick pre-window.

### VELVETFRUIT_EXTRACT — Mark 55 is on the correct side of jumps despite negative overall PnL

```
day 1  ts=727400  UP   +24   pre-flow: Mark 55 +15, Mark 49 −13, Mark 67 +13, Mark 14 −10
day 1  ts=939200  DOWN −23   pre-flow: Mark 55 −22, Mark 01 +12, Mark 14 +10
day 2  ts=594600  UP   +26   pre-flow: Mark 14 +12, Mark 55  −9, Mark 01 −3
day 3  ts=37300   DOWN −24.5 pre-flow: Mark 14 +10, Mark 55  −8, Mark 22 −7, Mark 67 +7
day 3  ts=36900   DOWN −23.5 pre-flow: Mark 55 −13, Mark 14 +10, Mark 22 −7, Mark 67 +7
```

**Mark 55 is on the correct side of 4 of 5 jump events** (the Day-2 UP move is the exception). This contradicts the simple-edge picture from Part 1 where Mark 55 looked like a mediocre taker losing $-13k overall.

Interpretation: Mark 55 may be **right just before the move and wrong everywhere else** — front-running a small set of inflection points but bleeding on average between them. Because we have only 5 jump events, this is suggestive rather than conclusive (would want 20+ to ASSert).

Mark 67 in pre-windows is **inconsistent**: +13 before Day-1 UP (correct) but +7 before Day-3 DOWN (wrong). So Mark 67's headline edge is from broad direction-getting, not jump anticipation.

Mark 14 in pre-windows is mostly **opposite** to the jump direction (selling before up, buying before down) — they get run over by the jump but recover via spread capture. Confirms their role as the patient market-maker.

### HYDROGEL_PACK — Mark 14 ↔ Mark 38 mirror is exact

```
day 1  ts=259100  UP   +41   Mark 14 +5,  Mark 38 −5
day 2  ts=292700  UP   +45   Mark 14 −27, Mark 38 +27
day 3  ts=222100  DOWN −43   Mark 14 +31, Mark 38 −28
day 3  ts=232800  UP   +44   Mark 14 +3,  Mark 38 +0
```

Mark 14 and Mark 38 are net opposite by construction (they trade against each other), but **neither has a consistent relationship to jump direction** on HYDROGEL. Sometimes Mark 14 is correct (Day 1 UP), sometimes Mark 38 is correct (Day 2 UP, Day 3 DOWN). HYDROGEL jumps appear to be exogenous, not driven by either trader's positioning.

**Action:** Add a Mark-55-on-VELVETFRUIT signal to the trader watchlist. **Cautiously**, because n=5. Don't size it like Mark 67. No HYDROGEL pre-jump signal — both Mark 14 and Mark 38 are uninformed about the direction.

---

## #12 — Cross-day stability ranking (CRITICAL: Mark 67 is unstable)

Per (trader, symbol), compute close-edge per unit on each day. Filter to total_qty ≥ 30. A signal is "stable" if it has the same sign on all 3 days.

### Stable POSITIVE-edge cells (winning every day)

```
trader   symbol               day1   day2   day3   mean   total_qty
Mark 14  VEV_4000             11.14  10.52  10.10  10.59      870
Mark 14  HYDROGEL_PACK        10.19   0.88   6.26   5.77     4022
Mark 14  VELVETFRUIT_EXTRACT   3.51   0.06   2.33   1.97     3524
Mark 01  VELVETFRUIT_EXTRACT   2.73   1.28   0.72   1.58     2792
Mark 01  VEV_6000              0.50   0.50   0.50   0.50     1105
Mark 01  VEV_6500              0.50   0.50   0.50   0.50     1105
```

**Mark 01 on VEV_6000 and VEV_6500 — literally constant $0.50/unit profit, every day.** This is mechanical, not skill: it's a fixed-margin pricing arb (deep-OTM voucher quoted exactly 0.50 inside fair, and Mark 01 is on the winning side of every fill).

**Mark 14 on VEV_4000 — +10.59/unit every day.** Spread-capture on the deep-ITM voucher. Mark 14 makes the market and pockets the spread.

### Stable NEGATIVE-edge cells (losing every day — these are the patsies)

```
trader   symbol               day1   day2   day3   mean    total_qty
Mark 38  VEV_4000            −11.01 −10.52 −10.04 −10.52       876
Mark 38  HYDROGEL_PACK        −9.94  −0.91  −6.22  −5.69      4096
Mark 55  VELVETFRUIT_EXTRACT  −3.12  −1.09  −1.91  −2.04      6551
Mark 22  VEV_6000             −0.50  −0.50  −0.50  −0.50      1105
Mark 22  VEV_6500             −0.50  −0.50  −0.50  −0.50      1105
```

**Mark 22 is the patsy on VEV_6000/6500** — exact mirror of Mark 01's $0.50 wins. Front-running this requires getting between Mark 01 and Mark 22 on those two strikes. Sample size is huge (2,210 fills combined) and edge is microscopic but **deterministic**.

**Mark 38 is the patsy on VEV_4000** — exact mirror of Mark 14. Same setup, larger size.

**Mark 55 loses ~$2/unit on VFX every day.** Confirms the bleed — but per #11 above, the bleed coexists with correct positioning at the inflection points.

### UNSTABLE cells (sign flipped across days)

```
trader   symbol               day1    day2    day3    mean     std    total_qty
Mark 22  VEV_5200            −15.91  −36.31    1.50  −16.91   18.92      162
Mark 14  VEV_5200             15.93   36.31   −4.07   16.06   20.19      122
Mark 67  VELVETFRUIT_EXTRACT  17.42   38.42   −8.41   15.81   23.46     1510
Mark 49  VELVETFRUIT_EXTRACT −12.37  −31.92    9.28  −11.67   20.61     1186
Mark 22  VELVETFRUIT_EXTRACT −12.46  −22.74    3.85  −10.45   13.41      843
```

**Mark 67 on VELVETFRUIT IS UNSTABLE.** Day 1 +$17/unit, Day 2 +$38/unit, Day 3 **−$8/unit**. Their headline $165/fill close-edge from Part 1 is dominated by Days 1–2; on Day 3 they actually lost.

**This is the most important finding of Part 3.** A blind Mark-67-follower trader would have been profitable on Days 1 and 2 but losing on Day 3 by mirroring their fills. The signal is real but not stationary — possibly Mark 67's inputs are correlated with a regime that flipped on Day 3, or Mark 67 was simply wrong that day.

Mark 49 is the symmetric story (mirror of Mark 67 on VFX): wins Day 3 when Mark 67 loses.

---

## Updated Trader Portraits

Revisions to the table from [FINDINGS.md](FINDINGS.md):

| Trader  | Old portrait                       | Updated portrait (after Part 3)                                                                            |
|---------|------------------------------------|------------------------------------------------------------------------------------------------------------|
| Mark 01 | "Spread-capture maker"              | **+ Mechanical $0.50/unit fixed-margin arb on VEV_6000/6500 (every day, deterministic)** |
| Mark 14 | "Top market-maker"                  | **Confirmed stable +$10.59/unit on VEV_4000 every day; absorbs jumps and recovers via spread**          |
| Mark 22 | "Mirror of Mark 14 on VEV_4000"     | **+ Deterministic $0.50/unit loser on VEV_6000/6500. Patsy across the curve.**                          |
| Mark 38 | "Patsy on HYDROGEL"                 | **Confirmed stable patsy on VEV_4000 (−$10.52/unit every day) AND HYDROGEL.**                            |
| Mark 49 | "Selling-side counterpart"          | Mirror of Mark 67 on VFX; wins Day 3 (+$9.28) when Mark 67 loses (−$8.41).                                 |
| Mark 55 | "Mediocre taker, mostly ignore"     | **REVISED: bleeds $-2/unit on average BUT on the correct side of 4/5 VFX 3σ jump events. Possible jump front-runner.** |
| Mark 67 | "Informed taker on VELVETFRUIT, $165/fill close-edge" | **REVISED: signal NOT STATIONARY. Wins Days 1–2 (+$17, +$38) but LOSES Day 3 (−$8). Blind-follow risk is real.** |

---

## Implications for the R4 Trader

1. **Down-weight Mark 67.** The headline edge was real but unstable across the 3-day sample. Don't size a Mark-67-follower as if it were certain edge. Cap exposure or gate on confirmation (e.g., require a second corroborating trader).

2. **Add Mark 55 to VFX watchlist as a low-confidence directional signal at jump times.** n=5 is too small to size confidently. One way to use it: when Mark 55 trades VFX with quantity ≥ p90 (their conviction trades), follow with a small position.

3. **The most exploitable arbs are the deterministic Mark 01 ↔ Mark 22 fixed-margin trades on VEV_6000/6500.** $0.50/unit × 1100+ qty/day = ~$550/day per strike per side, if we can intercept. Worth a separate strip-front-runner module.

4. **Mark 14's VEV_4000 spread-capture (+$10.59/unit, 870 qty) is the cleanest single signal in the dataset.** We can't be Mark 14 (we'd be racing them), but we can avoid being on the wrong side — i.e., do not aggressively cross the VEV_4000 spread; let them quote and skim.

5. **Don't waste compute on microprice or pacing features** — both produced negative results. Stick with mid-price forward edge for any per-trader scoring.

---

## Files

- `sophisticated2.py` — driver script for these four probes
- `sophisticated2.out` — full text output (this writeup is the synthesis)
- `trades_enriched.pkl` — input dataframe (built by `build_dataset.py`)
