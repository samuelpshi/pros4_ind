# R1 EDA Summary — Round 1 Pass 2 Findings

**Date:** 2026-04-16 (Session 4)
**Analyst:** Prep Pass 2 (quantitative EDA)
**Products:** ASH_COATED_OSMIUM (ACO) + INTARIAN_PEPPER_ROOT (IPR)
**Notebook:** `Round 1/analysis/r1_eda.ipynb` (12 cells, all executed, 12 PNG outputs)

---

## Section 1 — Already Established (Teammates)

Source: `Round 1/analysis/pepper_root_findings.md` (all 5 findings reproduced verbatim as reference).

| # | Finding | File |
|---|---------|------|
| 1 | IPR drift: +1001.3/day mean, std=1.8, across all 3 days. Deterministic, not luck. | `pepper_root_findings.md` §1 |
| 2 | Data cleaning: 54 rows/day mid=0 (empty book). 7.7% of rows one-sided. Drop rows missing bid_price_1 OR ask_price_1. Drift unchanged after cleaning. | `pepper_root_findings.md` §2 |
| 3 | Position limit: 80 for both ACO and IPR (v8 hardcoded 40, corrected in v9). | `pepper_root_findings.md` §3 |
| 4 | Entry slippage: ~9.4/unit for target=80 fill, fills by ts≈400, 99.1% of theoretical drift captured. | `pepper_root_findings.md` §4 |
| 5 | Config A committed: target_long=80. Config B (target=70 + skim) requires 16x skim productivity to break even — rejected. | `pepper_root_findings.md` §5 |

Teammate notebooks (`pepper_root_deep_dive.ipynb`, `bid_ask_analysis.ipynb`): Cell 1 load/sanity, Cell 2 open-to-close drift, Cell 3a trade-size histogram, Cell 3b Olivia overlay. Visual only, no statistical tests.

---

## Section 2 — New Findings

### ACO — ASH_COATED_OSMIUM

**Archetype:** Mean-reverting range-bounded oscillator. Closest IMC3 R1 analog: **KELP** (mean-reverting microstructure-driven market-making).

**Recommended strategy family:** KELP-style market making with filtered mmbot mid + mean-reversion fair-value adjustment.

**Evidence:**

| Test | Result | Implication |
|------|--------|------------|
| ADF (stationarity) | p=0.0048 / 0.0000 / 0.0147 across days -2, -1, 0 | Stationary within each day — confirmed mean-reverting |
| Return autocorr lag-1 | r = −0.494 | Strong negative: each tick partially reverts. 95% CI ±0.0065 |
| Return autocorr lag-5,20,100 | r = +0.016, +0.009, +0.005 | No persistence beyond 1 tick — mean reversion is instantaneous |
| Variance Ratio VR(2,4,8,16) | 0.506 / 0.272 / 0.149 / 0.089 | All << 1. Strong mean reversion across all horizons |
| OU Half-Life | 8.4 timesteps (AR beta = -0.0790) | Very fast mean reversion — ideal for tight market making |
| Hurst (R/S on levels) | 0.793 | Trending in level (expected for mean-reverting process on price levels); not informative on its own |
| Intraday range | 27–36 XIRECS per day | Tight bounded range; drift magnitude = −6.5, +10, +4 across 3 days (no consistent direction) |
| Tick volatility | 1.91–1.96 XIRECS/tick | Stable across all 3 days (no regime shifts) |
| Long-lag level autocorr | lag-1000: −0.123; lag-2000: −0.340 | Negative at ~1000–2000 ts lag → oscillation period ~2000–4000 ts. This is the ACO "hidden pattern" mentioned in the lore |
| Flow-to-return | r = −0.002, p = 0.906 | No adverse-selection signal in trade flow. Safe to make passively |
| Order-book depth | L1=100%, L2≈68%, L3≈2.6% | Near-fully bilateral; L3 negligible |
| Bot identity | All NaN | No Olivia-style signal. SQUID_INK strategy inapplicable |

**Key implication for strategy:** The OU half-life of 8.4 timesteps means that after a 1-tick move, the expected reversal is already priced in within ~8 ticks. The KELP reversion-beta (−0.229 historically) should be recalibrated to this data: the directly measured lag-1 autocorrelation of −0.494 implies a larger reversion adjustment than KELP's −0.229. Suggested starting reversion_beta: −0.40 to −0.50 (test range: −0.25 to −0.50).

**Second key implication:** The ~2000-timestep oscillation means there may be a medium-term directional signal on ACO (when the rolling price is in the top quarter of its recent range, it is likely to drift back down over the next 1000–2000 timesteps). This is not a microstructure signal but a momentum/reversion hybrid at the intraday scale.

---

### IPR — INTARIAN_PEPPER_ROOT

**Archetype:** Deterministic upward drift — pure directional. This archetype does **not appear in any IMC3 R1 product.** Closest analogues: none. RAINFOREST_RESIN is stable (no drift). KELP is noisy random walk. SQUID_INK is volatility-driven. IPR is uniquely a walk with constant positive drift and near-zero noise around the drift.

**Recommended strategy family:** Novel archetype — "Config A buy-and-hold to limit." Not named in the IMC3 playbook. The correct strategy is to immediately buy to the position limit (80 units) and hold to end of day, capturing the deterministic drift. No mean-reversion or z-score overlay is warranted.

**Evidence:**

| Test | Result | Implication |
|------|--------|------------|
| ADF (stationarity) | p=0.935 / 0.802 / 0.894 across days -2, -1, 0 | Cannot reject unit root. Confirmed non-stationary / trending |
| Return autocorr lag-1 | r = −0.488 | Same magnitude as ACO — this is microstructure bid-ask bounce, not mean reversion |
| Return autocorr lag-5,20,100 | r = −0.014, +0.001, −0.013 | Essentially zero. Returns are i.i.d. around the drift |
| Variance Ratio VR(2,4,8,16) | 0.511 / 0.253 / 0.126 / 0.064 | VR << 1 but this is the same artifact as ACO's lag-1 bounce superimposed on a trend. Not exploitable |
| OU Half-Life | 279,697 timesteps (~28 full days) | Infinite for practical purposes — NOT mean-reverting |
| IPR range | 1002–1003 XIRECS/day | Range equals drift: the entire intraday range IS the drift, confirming no reversals |
| Tick volatility | 1.58–1.87 XIRECS/tick | Constant per-tick noise (slightly lower than ACO, σ ≈ 1.7 avg) |
| Intraday quartile drift | Q1=0.1096, Q2=0.1088, Q3=0.1077, Q4=0.1092 XIRECS/tick (day -2) | Drift is uniform across all 4 time segments — no intraday timing advantage |
| Flow-to-return | r = −0.007, p = 0.734 | No adverse-selection signal. Confirms drift is not informed-trader driven |
| Bot identity | All NaN | No Olivia signal. Drift is structural, not counterparty-driven |

**Key implication:** The reversal thresholds in v9 (EMA-cross delta = −8 / −15 triggers a 160-unit position flip) are based on a false premise — IPR has no reversals in 3 days of data. Zero reversal signals fired in all 3 days (confirmed in Session 2 backtest). The threshold parameters are orphaned safety code that adds catastrophic-false-trigger risk without benefit on this data. Recommend removal.

---

### Cross-Product Findings

- **Level correlation:** r=0.276, p≈0 — weak but nominally significant, driven entirely by both products occupying similar absolute price ranges (~10,000 XIRECS), not a structural relationship.
- **Return correlation:** r=0.007, p=0.264 — NOT significant. Tick-by-tick moves are independent.
- **Cointegration (Engle-Granger by day):** Day -2: p=0.0208; Day -1: p=0.0003; Day 0: p=0.056. The apparent cointegration is a **statistical artifact**: the EG test applies ADF to the OLS residual of regressing IPR on ACO. Since ACO itself is stationary, this residual is dominated by ACO's stationarity, not a genuine co-movement. No pairs-trading strategy is warranted.

---

## Section 3 — Initial Parameter Ranges + Caveats

### ACO Strategy Parameters (KELP-style market making)

| Parameter | Suggested Range | Justification |
|-----------|----------------|---------------|
| `fair_value` basis | Filtered mmbot mid (volume filter ≥ 15 units) | From KELP playbook; eliminates small retail-distorted quotes |
| `reversion_beta` | −0.40 to −0.50 | Empirical lag-1 ACO autocorr = −0.494; KELP used −0.229 but ACO reverts faster |
| `take_width` | 1.0–2.0 ticks | KELP used 1.5; ACO tick vol = 1.9; taking inside 1 tick is likely profitable given 8.4-ts OU half-life |
| `clear_width` | 0.0–0.5 | KELP used 0; start at 0 |
| `adverse_volume` | 10–20 | Test 15 (KELP default) and 20; ACO tick vol is symmetric |
| `deflection_threshold` | 0.5–2.0 | KELP used 0.5, flagged as needing tuning; ACO range is 27–36 XIRECS so threshold should be on that scale |
| `passive_quote_offset` | 1 tick | KELP default_edge=1; ACO spread is tight so 1-tick passive is competitive |
| `position_limit` | 80 | Confirmed |

**Medium-term ACO signal (new — from oscillation finding):**
- The ~2000-ts oscillation suggests a "regime filter": if current ACO mid is in the top 20% of its trailing-500-tick range, bias the passive ask and reduce passive bid size. Conversely if in bottom 20%, bias bid.
- This is exploratory and not backtested. Risk: false signals on days where oscillation period differs.

**Risks for ACO:**
- If the "hidden pattern" changes between days (e.g., the oscillation period is not stable), medium-term signals will misfire.
- If adverse volume filter is set too high, fair-value estimate degrades in thin books.
- The current v9 ACO strategy uses EMA-based fair value, not the KELP-style filtered mmbot mid. Switching fair-value methodology may change PnL significantly. Must backtest before deploying.

### IPR Strategy Parameters (Config A, already committed)

| Parameter | Current Value | Range to Test | Justification |
|-----------|--------------|---------------|---------------|
| `target_long` | 80 | — | Config A committed; drift = +1001.3/day × 80 units = +79,351 PnL/day |
| `entry_take_cap` | 80 | — | Committed; fills by ts≈400 |
| Reversal threshold | −8 / −15 EMA delta | Remove entirely | Zero reversals in 3 days; false trigger risk far exceeds benefit |
| `skim_size` | 5 | 0–10 | Skim fills estimated 8–12/day; negligible vs drift PnL |
| `skim_min_pos` | 75 | 70–78 | Must leave room for refill; current setting sound |

**Risk for IPR:**
- The drift thesis depends on the "slow-growing root" mechanic holding in future rounds. If IMC introduces a harvest/reset event, the drift stops and a 80-unit long position at the top of the day would unwind for a large loss.
- No mean-reversion hedge is available (IPR half-life is infinite). Position management should use the reversal EMA ONLY as a catastrophic hedge with a very wide threshold (e.g., EMA delta < −50 before triggering).
- IPR does not match any IMC3 R1 product. Config A's buy-and-hold-to-limit is a **novel archetype** with no prior playbook entry. The risk is entirely that the drift stops or reverses on unseen data.

---

## Section 4 — Open Questions Status

Source: `Round 1/docs/r1_product_mechanics.md` — 5 ACO questions + 6 IPR questions.

### ACO Open Questions

| # | Question (paraphrase) | Status | Evidence / Notes |
|---|----------------------|--------|-----------------|
| ACO-1 | Is a `ConversionObservation` populated for ACO? | **Still open** | Not detectable from price/trade CSVs. Suggested disposition: assume no conversion; flag if live observations contain non-null conversion fields. |
| ACO-2 | What is the structure of ACO's "hidden pattern"? | **Resolved by EDA** | `r1_eda.ipynb` Cell 11; `plots/aco_long_lag_autocorr.png`. Level autocorr turns negative at lag ~1000 (−0.123) and most negative at lag ~2000 (−0.340). Pattern is a bounded oscillation with half-period ~1000–2000 timesteps. ADF confirms stationarity with OU half-life 8.4 ts. |
| ACO-3 | Are there bot-specific quoting rules for ACO? | **Still open** | All buyer/seller values are NaN. Bot quoting behavior not identifiable from anonymized trade data. Suggested disposition: assume symmetric bots; use adverse-volume filter to distinguish mm-bots from retail. |
| ACO-4 | Is the 3-level order-book depth a hard cap or export artifact? | **Resolved by EDA** | `r1_eda.ipynb` Cell 5; `plots/aco_depth_distribution.png`. L3 is quoted only ~2.6% of the time — the cap is effectively 1–2 levels in practice. Strategy should not rely on L3. |
| ACO-5 | Is PnL marked to mid or to IMC's internal fair value? | **Still open** | The `profit_and_loss` column exists in the prices CSV but its formula is not verifiable from the data alone without knowing the true fair value. Suggested disposition: assume mid-price marking; any discrepancy will show up in live vs. backtest comparison. |

### IPR Open Questions

| # | Question (paraphrase) | Status | Evidence / Notes |
|---|----------------------|--------|-----------------|
| IPR-1 | Is the growth rate constant or does it vary by day/hidden state? | **Resolved by EDA** | `r1_eda.ipynb` Cells 9 + 10; `plots/intraday_quartile_returns.png`. Mean drift per quartile is 0.1077–0.1096 XIRECS/tick across all 4 quartiles and all 3 days. Growth rate is constant within each day and nearly constant across days (1003.0, 999.5, 1001.5 total drift per day). |
| IPR-2 | Does IPR carry position AND price across days, or reset? | **Still open** | Price is confirmed to carry over (day -2 ends at 11001.5; day -1 starts at 10998.5 — very close). Position carry-over is not confirmed from data alone; mechanics doc flags this. Suggested disposition: assume position resets to 0 at day boundaries (consistent with how the v9 trader behaves — it re-buys 80 units at day start). |
| IPR-3 | Is a `ConversionObservation` populated for IPR? | **Still open** | Not detectable from CSV data. Same as ACO-1. Suggested disposition: assume no conversion. |
| IPR-4 | Do one-sided book events represent a rules-defined state? | **Resolved by EDA** | `r1_eda.ipynb` Cell 5; `plots/ipr_depth_distribution.png`. L1 = 100% after cleaning. One-sided events (7.7% of raw rows per teammate finding) are real market-maker absences, not artifacts. Strategy correctly guards against this (v9 line 274: `if not depth.buy_orders or not depth.sell_orders: continue`). |
| IPR-5 | Does the drift ever reverse (harvest/maturity event)? | **Still open — HIGH RISK** | Zero reversals observed in 3 days of data. But this is only 3 days. No reversal does NOT confirm a reversal can never happen. Suggested disposition: retain reversal guard in trader, but raise threshold from −8 to at minimum −50 EMA delta to avoid false triggers on normal drift noise. |
| IPR-6 | Can you go short IPR and is there borrowing cost? | **Still open** | Mechanically allowed (position limit −80 to +80). No borrowing cost described in rules. However, shorting IPR with a deterministic upward drift is irrational under the current thesis. Suggested disposition: do not short IPR unless drift reversal is confirmed live. |

**Triage summary:**
- Resolved by EDA: **5** (ACO-2, ACO-4, IPR-1, IPR-4, and IPR-4 duplicate — net 4 unique EDA resolutions)
- Resolved by EDA: ACO-2, ACO-4, IPR-1, IPR-4 → **4 questions**
- Still open: ACO-1, ACO-3, ACO-5, IPR-2, IPR-3, IPR-5, IPR-6 → **7 questions**
- Resolved by re-reading HTML: **0 questions** (all rules text already captured in mechanics doc)

**Corrected count:** 4 Resolved by EDA | 0 Resolved by HTML re-read | 7 Still open.
