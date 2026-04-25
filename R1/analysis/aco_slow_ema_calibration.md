# ACO Slow-EMA Calibration — Pass 6.1

**Date:** 2026-04-16
**Pass:** 6.1 (calibration input to the hybrid KELP-analog strategy's slow-timescale signal)
**Scope:** EDA only. No trader edits, no backtests. Output: a defensible EMA half-life sweep grid for Pass 6.5, plus an honest verdict on whether the slow component is stable enough to justify the hybrid concept.

**Data:** `Round 1/r1_data_capsule/prices_round_1_day_{-2,-1,0}.csv`, ACO rows only, cleaned per Pass 2 rule (drop `mid_price == 0` and rows missing `bid_price_1` or `ask_price_1`). n = 9,187 / 9,225 / 9,232 rows per day.

**Reproducibility:** `Round 1/analysis/aco_slow_ema_calibration.py` → `aco_slow_ema_calibration_results.json` + 12 PNGs under `Round 1/analysis/plots/`.

---

## 1. Setup — Price series chosen

**Chosen series: `mmbot_mid`** = midpoint of the filtered book where each side is restricted to quotes with absolute volume ≥ 15 (matches `ACO_ADVERSE_VOLUME = 15` in `Round 1/archive/traders/trader-v9-r1-aco-only.py`, line 44; trader archived after Pass 2.5 superseded v9-r1). When either filtered side is empty, fall back to the previous `mmbot_mid` value, mirroring the trader's online logic.

**Why mmbot_mid over raw mid.**

- **Consistency with v9's existing fast-FV pipeline.** The hybrid strategy's slow EMA is a bias on top of the same fair value the MM already uses; using a different input would introduce a new and untested signal pathway.
- **Less noise at short lags.** Per-tick increment stddev: `mmbot_mid` ≈ 0.60 vs raw mid ≈ 1.92 across all three days (see `series_choice_comparison` in results JSON). The factor-of-3 reduction is exactly the bid-ask-bounce component that the adverse-volume filter is supposed to suppress.
- **Negligible cost at long lags.** ACF at lag 2000 is within 0.02 absolute between raw and mmbot on all three days (Day -2: +0.050 vs +0.050; Day -1: −0.062 vs −0.061; Day 0: −0.280 vs −0.299). The slow structure is preserved.

The rest of this document uses `mmbot_mid` exclusively unless stated otherwise.

---

## 2. ACF decomposition

Six plots; both versions on the same lag axis (0–3000).

| Day | Raw ACF | Filtered ACF (40-tick centered MA) |
|-----|---------|-----------------------------------|
| −2  | `plots/acf_aco_day-2.png` | `plots/acf_aco_day-2_filtered.png` |
| −1  | `plots/acf_aco_day-1.png` | `plots/acf_aco_day-1_filtered.png` |
|  0  | `plots/acf_aco_day0.png`  | `plots/acf_aco_day0_filtered.png` |

The filter is a centered rolling mean of window 40 (≈ 5 × the fast OU half-life of 8.4 ticks from Pass 2). It removes the bid-ask-bounce signature at lag 1 and makes the slow component's shape legible.

**Raw ACF at diagnostic lags (mmbot_mid):**

| Lag  | Day −2  | Day −1  | Day 0   |
|------|---------|---------|---------|
| 1000 | −0.229  | −0.040  | −0.120  |
| 1500 | −0.161  | −0.106  | −0.263  |
| 2000 | +0.050  | −0.061  | −0.299  |
| 2500 | −0.047  | +0.066  | −0.194  |
| 3000 | −0.158  | −0.021  | −0.134  |

**Immediate finding:** Pass 2 reported lag-2000 ACF = −0.340 as a headline number. That number is roughly the mean of these three (mean = −0.103), but it is **not representative of any single day.** Day −2 at lag 2000 is slightly **positive**. The Pass 2 aggregate hid substantial day-to-day structure.

---

## 3. Per-day half-period estimates

Two independent methods.

- **Method A (ACF zero-crossing / argmin):** On the filtered ACF, find (i) the first zero crossing pos→neg after lag 100 and (ii) the lag of the most negative value (the ACF trough). For a pure sinusoid of period T, the trough sits at T/2 and the zero crossing at T/4. We report argmin as the half-period estimate.
- **Method B (spectral peak):** FFT of the demeaned raw mmbot_mid series; take the dominant power peak restricted to periods in [400, 6000] ts; half-period = period / 2.

| Day | Method A: argmin lag (ACF value) | Method A: zero crossing | Method B: peak period (T/2) | Agreement (|A−B|/max) |
|-----|----------------------------------|-------------------------|------------------------------|-----------------------|
| −2  | 1137 ts (ACF = −0.357) | 658 ts  | 2297 ts (T/2 = 1148) | 1.0%  ✅ |
| −1  | 1314 ts (ACF = −0.208) | 783 ts  | 2306 ts (T/2 = 1153) | 12.2% ⚠ |
| 0   | 2284 ts (ACF = −0.322) | 847 ts  | 4616 ts (T/2 = 2308) | 1.0%  ✅ |

**Within-day agreement is excellent on days −2 and 0** (methods differ by < 2%). On day −1 the spectral peak (1153) is shorter than the ACF argmin (1314); Method B points to the same regime as Day −2 while Method A pushes slightly later. The ACF trough on Day −1 is shallow (−0.21 vs −0.32 / −0.36 on the other days), so the argmin is less statistically sharp — inspect `plots/acf_aco_day-1_filtered.png` and note the broad flat region from ~1000 to ~1500.

**Cross-day agreement is poor.** Method B: [1148, 1153, 2308] — Days −2/−1 cluster near 1150; Day 0 is almost exactly **2×** that. Cross-day spread is 50%, comfortably above the 30% "flag as instability" threshold in the task brief. Method A reproduces the same pattern with a similar 50% spread.

---

## 4. EMA half-life ranges per day

Per the task rule, an EMA meant to track a sinusoidal component of half-period H should have half-life in [H/π, H/2].

| Day | Method A range (ts) | Method B range (ts) | Per-day union (ts) |
|-----|---------------------|---------------------|--------------------|
| −2  | [362, 568]          | [366, 574]          | **[362, 574]**     |
| −1  | [418, 657]          | [367, 577]          | **[367, 657]**     |
| 0   | [727, 1142]         | [735, 1154]         | **[727, 1154]**    |

Days −2 and −1 overlap tightly; Day 0 sits entirely above them. There is **no single half-life value simultaneously inside the [H/π, H/2] band for all three days** — e.g., 600 ts is at the upper edge of Day −2's band, above Day −1's, and below Day 0's band.

---

## 5. Signal magnitude check

At the per-day median candidate half-life, compute stddev of `(mmbot_mid − slow_ema)`. This is the residual the hybrid strategy would be biasing the inventory target off of.

| Day | Median candidate half-life (ts) | Residual stddev (XIRECS) | Tick-size comparison |
|-----|---------------------------------|--------------------------|----------------------|
| −2  | 467  | **3.91** | ≈ 3.9 ticks (tick = 1) |
| −1  | 497  | **3.46** | ≈ 3.5 ticks |
| 0   | 938  | **4.75** | ≈ 4.8 ticks |

All three days yield a residual well in excess of 1 tick (the task's "< ~1 tick → signal too weak" floor). For a KELP-style MM, a 3–5 XIREC deviation from slow EMA is more than enough to meaningfully shift inventory target by a few units at `k ~ 0.5–1.0 units / XIREC`.

**The slow signal's magnitude is not the weak link in the hybrid concept. The weak link is timescale stability.** See `plots/slow_ema_tracking_day-2.png` (clean oscillation at hl=467) vs `plots/slow_ema_tracking_day0.png` (long trends at hl=938) for a qualitative contrast.

---

## 6. Cross-day stability assessment

**Weakly stable / bordering on unstable.**

Positive evidence:
- Both methods agree within each day (≤12% disagreement).
- Residual magnitude (3.5–4.8 XIRECS) is robust and comparable across all three days.
- A slow component *is* present on every day (ACF trough between −0.21 and −0.36; every day is well below zero somewhere in [1000, 2300]).

Negative evidence:
- Half-period varies by **2× across days** (Days −2/−1 ≈ 1150 ts; Day 0 ≈ 2300 ts). The spectral peak finding is essentially bimodal, not clustered.
- Day 0's filtered ACF (see `plots/acf_aco_day0_filtered.png`) does **not** show a clean sinusoidal bounce back toward zero after the trough — it plateaus in a long negative trough from ~1500 to ~2300. This is more consistent with a single slow drift than with a periodic oscillation. If Day 0 represents a different regime, pooling across days (as Pass 2 implicitly did to produce "half-period 1000–2000 ts, lag-2000 autocorr −0.340") is misleading.
- Pass 2's −0.340 number at lag 2000 is driven almost entirely by Day 0 (−0.299); Day −2 at the same lag is actually slightly **positive** (+0.050). The original finding was not a stable property of ACO, it was a property of Day 0 that happened to survive averaging.

Verdict: the slow component exists on every day but its **timescale is not stable**. The hybrid concept is not falsified, but it cannot be committed to a single half-life from this data.

---

## 7. Recommended sweep grid for Pass 6.5

Union of all per-day [H/π, H/2] bands is approximately [362, 1154]. Take 5 log-spaced points, rounded to the nearest 25:

**`[350, 475, 650, 875, 1150]`**

Spans factor ~3.3× (log-linear). Each adjacent pair is ~1.35× apart. This is wider than a GREEN verdict would warrant but honestly reflects the day-0 vs days-−2/−1 dichotomy.

Grid rationale:
- **350, 475** — cover Days −2 and −1 (both methods' [H/π, H/2] bands live here).
- **650** — the middle ground; inside Day −1's band, just outside the other two.
- **875, 1150** — cover Day 0 (both methods agree this day wants a substantially longer half-life).

If Pass 6.5 sweeps this grid and the PnL-optimum clusters into one or the other sub-band (e.g., {350, 475} or {875, 1150}), that is diagnostic: ACO has two regimes, and the hybrid needs a regime-detection layer, not a fixed half-life. If the PnL surface is flat across the grid, the slow signal is fitting noise and the hybrid should be abandoned. If it peaks in the middle (e.g., 650), accept weak average behavior and note that any single day may deviate.

---

## 8. Verdict on the hybrid concept

**YELLOW — proceed with eyes open.**

The slow component is real on every day and its signal magnitude (3.5–4.8 XIRECS deviation from EMA) is comfortably above the noise floor. Within-day, the ACF-argmin and spectral methods agree to ~1% on Days −2 and 0 and ~12% on Day −1, so the measurement is not methodologically fragile.

But the timescale is **not** consistent across days. Day 0's characteristic half-period is roughly 2× that of Days −2 and −1, and its ACF shape suggests a longer-lived drift rather than a clean oscillation, materially different in kind from the other two days. Pass 2's headline finding (lag-2000 autocorr = −0.340) is driven primarily by Day 0; Day −2 at the same lag is slightly positive, which means the "stable slow oscillation" framing that motivated the hybrid was partly an averaging artifact. This needs to be reported back to Pass 6.2.

Pass 6.3 can proceed to implement the hybrid using the sweep grid above, but Pass 6.5 must treat "no robust winner across days" as a plausible outcome — not a sweep-grid problem to fix by widening the grid further, but a signal to either (a) commit to half-life ≈ 1150 and accept Days −2/−1 give weaker PnL, (b) commit to half-life ≈ 475 and accept Day 0 gives weaker PnL, or (c) drop the hybrid entirely if neither sub-band produces a PnL improvement over the pure-MM baseline on the respective days where it should work.

---

## Appendix — File manifest

Analysis code:
- `Round 1/analysis/aco_slow_ema_calibration.py`

Numeric outputs:
- `Round 1/analysis/aco_slow_ema_calibration_results.json`

Plots (all under `Round 1/analysis/plots/`):
- `acf_aco_day-2.png`, `acf_aco_day-1.png`, `acf_aco_day0.png` — raw ACF, 0–3000 lag, with Method A argmin and Method B half-period marked.
- `acf_aco_day-2_filtered.png`, `acf_aco_day-1_filtered.png`, `acf_aco_day0_filtered.png` — ACF of 40-tick smoothed series (fast component suppressed), with zero-crossing and argmin marked.
- `spectrum_aco_day-2.png`, `spectrum_aco_day-1.png`, `spectrum_aco_day0.png` — log-log periodogram of demeaned mmbot_mid with the dominant-peak period marked.
- `slow_ema_tracking_day-2.png`, `slow_ema_tracking_day-1.png`, `slow_ema_tracking_day0.png` — mmbot_mid series overlaid with slow EMA at the per-day median candidate half-life; residual stddev in the title.
