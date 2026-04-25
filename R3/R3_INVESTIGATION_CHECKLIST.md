# Round 3 — Options Strategy Investigation Checklist

Synthesis of two Prosperity 3 voucher-round writeups (the unnamed-team hybrid strategy + Frankfurt Hedgehogs). Use as a checklist of analyses to run on R3 historical data **before** writing trader code.

---

## 1. Mathematical framework

### Black-Scholes setup
- European calls on `VELVETFRUIT_EXTRACT` (VEV)
- Risk-free rate `r = 0`, no dividends
- Per voucher: strike `K`, time to expiry `T` (in days, or fraction of year — be explicit)
- Vouchers expire at end of R5
  - Historical day 0 → TTE = 8d
  - Historical day 1 → TTE = 7d
  - Historical day 2 → TTE = 6d
  - **R3 simulation start → TTE = 5d**
  - R4 → 4d, R5 → 3d, expiry 2d after R5 starts (verify exact rule)

### IV inversion
- Solve $C_\text{market} = \text{BS}(S, K, T, \sigma, r=0)$ for $\sigma$
- Use Newton-Raphson on vega; bisection fallback when vega is tiny
- Skip strikes where extrinsic value is too small to invert reliably (deep ITM/OTM or near expiry)

### Moneyness convention
- Use $m_t = \log(K / S_t) / \sqrt{T}$ for the smile x-axis
- This is what both writeups used; it makes smile shape stable as TTE decays
- Alternatives to test: $\log(K/S)$, $K/S - 1$, $(K - S)/(S\sqrt{T})$

### Smile fit
- **Quadratic in moneyness**: $\hat v(m) = a m^2 + b m + c$
- Fit per-tick via weighted least squares
- Weight ATM strikes higher (cleaner IV); drop strikes with no quote or extreme spread
- Frankfurt explicitly disregarded "outliers at the bottom-left" — points where extrinsic was too low to give meaningful IV
- The intercept $c$ ≈ ATM base IV → track separately as a level signal

---

## 2. Underlying analysis (`HYDROGEL_PACK` and `VELVETFRUIT_EXTRACT`)

Both are delta-1 products, limit 200. Need to characterize independently before treating VEV as "the underlying" for vouchers.

### Stationarity & process tests
- ADF test on price levels (likely non-stationary) and returns (should be stationary)
- KPSS for confirmation
- Ljung-Box on returns

### Mean reversion tests
- Autocorrelation function (ACF) of returns at lags 1-50
- **Frankfurt's randomization test**: generate ~1000 random Gaussian return series with same length and variance; compute rolling autocorrelation for each; plot real series against the band of randoms; if real falls outside the random envelope, the autocorrelation is statistically real (Figure 8 in their writeup)
- OU half-life from AR(1) coefficient: $\tau_{1/2} = -\log 2 / \log(\rho_1)$

### Distributional checks
- QQ plot of returns vs normal
- Detect jumps and fat tails — Frankfurt warned that jumps complicate mean-reversion strategies even when autocorrelation looks favorable

### What this informs
- Whether market-making, mean-reversion, or trend-following is right per product
- Whether VEV itself supports an underlying-mean-reversion overlay (the unnamed team and Frankfurt both used one, with mixed results)

---

## 3. Voucher market structure

10 strikes: 4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500. Limit 300 each.

### Per-strike data quality
- Fraction of timestamps with a two-sided market
- Median and tail bid-ask spread
- Median quoted depth at top of book
- Mid-price availability

### ATM identification over time
- Track distance `|K - S_t|` per voucher per tick
- Identify the most ATM strike at each timestamp
- Frankfurt's strategy was to focus scalping on the most ATM strike and rotate as VEV moved

### Strike triage
- Liquid + ATM-ish: primary scalping candidates (likely 5100-5400 if VEV trades around there)
- Liquid + OTM/ITM: usable for smile fit but lower scalping priority
- Illiquid: drop from fit and don't trade

### Vega per strike
- Compute BS vega across all timestamps
- Vega is highest at ATM → same IV deviation = larger price deviation at ATM → most $ scalping edge lives there
- Frankfurt's Figure 6c (price residuals over time) showed dramatically larger price moves at the ATM 10000 strike vs OTM strikes

---

## 4. IV smile analysis

### Per-tick smile
- For each timestamp, compute IV per liquid strike
- Plot IV vs moneyness scatter, color by strike — replicate Frankfurt's Figure 6a
- Fit quadratic, plot fitted curve
- Save fitted parameters $(a, b, c)$ to a time series

### Smile evolution
- Plot $a_t$, $b_t$, $c_t$ over the 3 historical days
- Look for: structural breaks at day boundaries (TTE drop), drift, regime shifts
- Pooled fit (all timestamps together) vs per-tick fit — compare residual variance

### IV residuals
- $\epsilon_t^K = v_t^K - \hat v(m_t^K)$ for each strike, each timestamp
- Plot residual time series per strike (Frankfurt's Figure 6b)
- Look for: stationarity, clustering, mean-reversion

### Base IV mean reversion
- The intercept $c_t$ is the ATM-fair IV at each tick
- Test for mean reversion: ADF, OU half-life, ACF
- Earlier writeup emphasized this — the Coconut Coupon trade was largely IV-level mean reversion around ~16%
- If $c_t$ mean-reverts, this is an additive signal on top of cross-strike RV

---

## 5. Signal generation & validation

### Cross-strike relative value (the core scalping trade)
- Per strike per tick: theoretical price = BS($S$, $K$, $T$, $\hat v(m_t^K)$)
- Price deviation $= P_\text{market} - P_\text{theoretical}$
- Z-score the deviation using rolling stdev per strike
- Trade on |z| > threshold

### Critical: price space, not IV space
- Frankfurt's key insight (Figure 6b vs 6c): IV residuals look similar across strikes, but **price deviations are dominated by the ATM strike** because of vega
- Threshold trades on price deviations, not IV deviations
- Or, threshold on IV deviations but size positions proportional to vega

### 1-lag autocorrelation test (Frankfurt's filter)
- For each strike, compute Cor($\epsilon_t$, $\epsilon_{t-1}$) on the price-residual series
- Significantly negative → residuals revert → scalping has positive expectation on that strike
- Flat or positive → just noise, don't scalp
- Compare to randomized baseline as in Section 2

### Profit threshold
- Trade only when expected mean-reversion profit > round-trip transaction cost (spread)
- Frankfurt tracked this in real time to decide which strikes to "activate" scalping on

---

## 6. Position sizing & delta hedging

### The hard limit math
- VEV underlying limit: 200
- Each voucher limit: 300
- 10 vouchers, so theoretical max delta from voucher book is huge — cannot hedge with 200 VEV alone in general

### Hedge feasibility analysis
- Compute delta per strike at typical IV (use ATM IV as estimate)
- For each scenario (e.g., long 300 of 5200 + long 300 of 5300): what is total delta?
- Identify which combinations are fully hedgeable
- The unnamed-team writeup got burned in the Coconut round by going beyond hedge capacity

### Sizing rule (the safe approach)
- Cap voucher positions so net portfolio delta ≤ 200 at all times
- Voucher Coupon team: capped voucher positions so they could always fully hedge — sacrificed upside for clean execution
- This is the right default unless your backtest shows the unhedged-delta version dominating

### Hedge instrument
- Use VEV (the underlying) for delta hedging
- Compute delta using BS at the fitted-smile IV for each voucher
- Rebalance threshold: don't rehedge every tick (transaction costs); rehedge when |delta drift| > some band

---

## 7. Auxiliary strategies

### Gamma scalping
- Buy underpriced vouchers (per smile model), set up perfect delta hedge, rehedge frequently
- Profit if realized vol > implied vol you paid
- Both writeups: "stable but small contributor" — don't prioritize over IV scalping
- Add only if time permits and limits allow

### Underlying mean-reversion overlay
- Light EMA-based mean reversion on VEV itself
- The unnamed team and Frankfurt both ran this as a separate, smaller engine
- Frankfurt's R4: this overlay lost ~50k. R5: lost ~10k. Variance was high.
- Frankfurt's framing: kept it as a "regret hedge" against teams going all-in on mean reversion, not as standalone alpha
- Decision rule: only activate if Section 2 tests show statistically significant negative autocorrelation in VEV

### Theta / time decay
- As TTE drops to 1-2 days, theta dominates
- Long-vol positions (gamma scalping, long vouchers) get punished harder near expiry
- Plan to scale down or close voucher book by R5 unless edge is strong

---

## 8. Strategic / meta considerations

### What other teams will likely do
- Top teams will all build the IV-scalping core
- Differentiation comes from execution quality, sizing, hedge management
- Teams that overweight directional bets (unhedged vouchers, large mean-rev positions) get high variance — sometimes winners, sometimes blow-ups

### Regret minimization framing
- Frankfurt's hybrid wasn't max-EV; it was max-min across plausible market regimes
- For GOAT (R3 reset), variance matters because tail outcomes determine ranking
- Don't optimize for absolute PnL; optimize for top-K finish probability

### When the market hands you a clean signal vs noise
- Frankfurt's autocorrelation-vs-random plot is the right discipline
- "I see a pattern" is not enough — verify that the pattern exceeds what random data would produce

---

## 9. R3-specific considerations

### 10 strikes = more data, more discipline
- More data points → smile fit is more robust per tick
- But: only 4-5 strikes (likely 5100, 5200, 5300, 5400, maybe 5000/5500) will be liquid + near ATM
- Don't try to scalp all 10 — concentrate on the 1-2 most ATM at any moment

### TTE schedule
- R3 starts at TTE=5d, ends at ~3d
- R4 covers TTE 3d→2d
- R5 covers TTE 2d→1d (or 1d→0d depending on exact rule — verify)
- Smile shape and signal quality degrade as TTE shrinks; plan an end-of-R5 wind-down

### Pin risk near expiry
- If VEV ends very close to a strike at expiry, that voucher's payoff is highly sensitive to small moves
- Reduce or close positions in the most ATM voucher in the final hours

### Hidden fair value at round end
- "Open positions are automatically liquidated against a hidden fair value at the end of the round"
- Don't end the round with positions that are far from theoretical fair value — IMC will haircut you

---

## 10. EDA checklist (concrete to-do)

Order roughly by dependency. Notebook assignments in brackets correspond to the agent prompt.

### A. Data loading & sanity
1. Load all 3 historical days of price/trade data for HYDROGEL_PACK, VELVETFRUIT_EXTRACT, all 10 vouchers [N1, N2]
2. Check timestamp alignment, missing data, fraction of NaN mids per product [N2]
3. Plot raw price series end-to-end across days [N1, N2]

### B. Underlying characterization [N1]
4. ADF, KPSS, Ljung-Box on HYDROGEL_PACK and VEV
5. ACF plots, returns histograms, QQ plots
6. AR(1) coefficient and OU half-life
7. Frankfurt-style randomization: random Gaussian return series envelope vs real
8. Jump detection (large absolute returns, count and characterize)

### C. Voucher market structure [N2]
9. Per-strike: % ticks with two-sided market, median spread, median depth
10. ATM strike identification per tick (smallest |K - S_t|)
11. Time-series of ATM strike (does it switch? how often?)
12. Strike triage table (liquid/ATM-ish/scalp candidate)

### D. IV inversion & smile [N3]
13. Implement BS pricer + IV solver
14. Compute IV per strike per tick (handle TTE schedule by historical day)
15. Compute moneyness $m_t^K = \log(K/S_t)/\sqrt{T}$
16. Scatter plot IV vs moneyness, color by strike (replicate Frankfurt Figure 6a)
17. Fit quadratic per tick; save $(a_t, b_t, c_t)$
18. Plot fitted parameters over time
19. Plot IV residuals per strike (Frankfurt Figure 6b)
20. Convert residuals to price-space deviations via BS
21. Plot price deviations per strike (Frankfurt Figure 6c)

### E. Signal validation [N4]
22. 1-lag autocorrelation of price residuals per strike; randomization test for significance
23. ADF + OU half-life on base IV $c_t$
24. ACF of base IV
25. Vega per strike; relate vega rank to price-residual magnitude rank
26. Per-strike "expected scalping PnL per round-trip" (residual scale × autocorr) vs typical spread → which strikes pass the profit threshold
27. Per-strike: cumulative PnL of a simple z-score scalping rule (in-sample backtest, no execution costs) — sanity check the strategy works on the data

### F. Hedge feasibility [N4]
28. Delta per strike at fitted-smile IV
29. Worst-case net delta from various plausible voucher position combinations
30. Maximum scalable voucher position before hedge capacity (200 VEV) is exceeded

---

## Quick-reference: findings to write into trader code

Once EDA is done, the trader needs to know (per strike):
- Is this strike liquid enough to trade? (yes/no)
- What's the typical residual stdev for z-scoring?
- What's the autocorrelation — is scalping justified?
- What's the BS delta and vega at fitted IV?
- Position size cap given hedge constraints

And globally:
- Current ATM strike
- Current base IV $c_t$, and where it sits relative to historical mean (for level signal)
- Current net portfolio delta
- VEV available for hedging

---

## What NOT to do (anti-patterns from the writeups)

- ❌ Take voucher positions you can't hedge ("we knowingly chose a higher-variance version")
- ❌ Fit smile through illiquid deep ITM/OTM points that pull the curve off
- ❌ Threshold on IV deviation alone — bigger price moves live at ATM
- ❌ Treat all 10 strikes equally — concentrate on the 1-2 most ATM
- ❌ Run mean-reversion overlay as standalone alpha if the autocorrelation evidence is marginal
- ❌ Forget that hidden fair value liquidates positions at round end
