# R3 Backtest Results — commentary log

Each entry summarises a backtest run. Numbers come from the Rust local
backtester (`rust_backtester --dataset round3 --products full`) over all 3
historical days. Per-row machine-readable detail lives in
`backtest_results.csv`.

---

## 2026-04-26 — `trader-r3-v1-hydrogel.py` (Stage 1 baseline)

**Config**: `configs/hydrogel_v1.json`
(`fair_value_ema_window=50`, `quote_offset=3`, `skew_strength=1.0`,
`take_edge=4`, `passive_quote_size=30`, `aggressive_take_size_cap=50`,
`position_limit=200`).

**Per-day PnL**: D0 = 3362, D1 = 4998, D2 = 1719.
**Mean PnL across 3 days = 3359.67**, sample stdev = 1639.5,
coefficient of variation 0.49.

**Per-product attribution**: 100% of PnL is HYDROGEL_PACK (correct — trader
ignores all other symbols). All voucher and VEV columns flat at 0.00 across
all days, confirming the symbol filter works.

**Trade count**: 7 / 6 / 20 own trades on D0/D1/D2. Average ~$480 per trade
on D0–D1, ~$86/trade on D2. Very low fill rate, which is expected: HYDROGEL
posts a fixed 16-wide spread (N1 cell 7) with the wall at roughly fv ± 8,
so our passive quotes at fv ± 3 sit deep inside the spread and only fill
when bot flow crosses through them. The aggressive-take leg almost never
triggers — for the take to fire we need best_ask ≤ fv − 4 or best_bid ≥
fv + 4, and the wall stays out at ± 8 for most ticks.

**Behaviour**: PnL is consistently positive with no per-day losses. D2
takes 3× as many trades as D0/D1 but earns less per trade — suggesting D2
had more cross-the-spread flow at marginal prices rather than juicy
mispricings. No evidence of position pinning at the limit (would need to
inspect the run logs to confirm peak |position|; deferred). The baseline
is a viable PnL floor; the obvious next step is to lift the fill rate.

**Variance vs Hard Rule #3**: stdev/mean = 0.49 is high relative to the
"straight-line-up cumulative PnL" goal. With only 7–20 trades per day the
estimator is noisy by construction — Stage 2 sweeps that increase fill
rate should also tighten the variance.

---

## 2026-04-26 — `trader-r3-v1-vev.py` (Stage 1 baseline)

**Config**: `configs/vev_v1.json` (`v1-vev-defaults`)
- Active strikes: `[5000, 5100, 5200, 5300, 5400, 5500]` (drop 4000/4500/6000/6500 per N2/N3/N4 strike triage).
- Smile fallback `(a=0.143, b=-0.002, c=0.236)` from N4 cell 11. *Note: N3 reports a different pooled fit `(0.158, -0.0046, 0.232)` under the EPS_EXT=0.5 filter; spec selected N4. Diff is <1.5% IV at typical |m|<0.1.*
- EMA20 demean, 100-tick z-window, z_open=1.5 / z_close=0.5.
- Per-strike caps `60/80/120/120/80/60` (5000..5500) — N4 cell 38 hedge feasibility.
- Module B: c_t z-score over 500 ticks, ±25 contracts on each of 5200/5300.
- Module C: VEV delta-hedge target = `-round(net voucher delta)`; EMA50 mean-reversion overlay on VEV mid (N1 ρ₁=−0.159), ±50 max; net portfolio delta hard-capped at ±50 with hedging priority.

**Per-day PnL** (Rust backtester, `--products full`):
| day | final_pnl | own_trades |
|---|---|---|
| 0 | −1,117,582 | 35,220 |
| 1 | −1,094,560 | 34,751 |
| 2 | −1,080,644 | 34,437 |
| **mean** | **−1,097,595** | **34,803** |
| stdev | 18,506 | 393 |

**Per-product attribution (3-day total, all VEV-related; HYDROGEL_PACK and 4 dropped strikes flat at 0)**:
| product | total PnL | share of total loss |
|---|---|---|
| VELVETFRUIT_EXTRACT | −1,471,962 | 44.7% |
| VEV_5100 | −435,308 | 13.2% |
| VEV_5200 | −426,761 | 13.0% |
| VEV_5000 | −418,793 | 12.7% |
| VEV_5300 | −280,900 | 8.5% |
| VEV_5400 | −145,664 | 4.4% |
| VEV_5500 | −113,397 | 3.4% |
| **TOTAL** | **−3,292,786** | 100.0% |

No single strike exceeds the >70% dominance threshold from the spec; VEV underlying is the largest single bucket at 45%, the rest is spread across 6 vouchers in roughly delta-weighted proportion (5000–5200 are the highest-delta strikes and contribute the most spread cost).

**Module-level paper PnL** (mark-to-mid, no slippage, end-of-day from `lambdaLog`):
| module | D0 | D1 | D2 | mean |
|---|---|---|---|---|
| A (cross-strike RV scalp) | +144,320 | +139,900 | +110,050 | +131,423 |
| B (base-IV mean rev) | +10,687 | +12,362 | +10,175 | +11,075 |
| C (VEV hedge + overlay) | +25,105 | +32,669 | +47,661 | +35,145 |
| **TOTAL paper** | **+180,112** | **+184,931** | **+167,886** | **+177,643** |

The strategy logic produces ~+180k/day of mark-to-mid alpha. Realized PnL is −1,097k/day. The ~1.27M/day delta is implied per-trade slippage of ~36 per trade × 35k trades — i.e., spread crossing on every order placement is the dominant loss driver, not signal failure.

**Behaviour**:
- Hedge band held: `net_d` (printed each tick) stays within ±0.5 throughout all 3 days; the delta hedge is doing its job to spec (±50 band).
- 35k own trades per day = 3.5 trades per tick on average. The trader is constantly thrashing positions in response to noisy z-scores. The bang-bang signal (jump to ±cap on |z|>1.5, jump to 0 on |z|<0.5) interacts badly with marketable order placement.
- Smile fit fallback: with 6 active strikes and 100% IV survival across this universe (N3 cell 16), `len(ivs) >= 4` essentially always holds; the hardcoded fallback never triggered.
- Module C overlay: `vev_t` per tick is dominated by the hedge component, not the overlay; the EMA50-fade overlay rarely opens in either direction because once z>1.0 fires the hedge band check usually drops it.

**Variance vs Hard Rule #3**: D0/D1/D2 final PnLs are remarkably consistent (cv = 0.017). The strategy is losing money smoothly, not randomly — confirming the loss is a systematic execution issue, not luck-driven.

**Stage 2 priorities** (data-driven from this baseline):
1. Trade-frequency reduction is the single highest-impact knob: hysteresis bands on z-thresholds (require z to overshoot by some delta before reversing); per-tick step-size caps; or rebalance bands on the hedge so VEV doesn't re-trade every 100ms.
2. Passive quoting (post limit orders inside the spread) instead of marketable would convert spread cost into spread capture; this is a deeper rewrite of the order-routing layer.
3. The smile/IV/scalp signal layer looks correct (paper PnL is positive and consistent across days, attribution is sane). Stage 2 sweeps on EMA window and z-thresholds remain on the priority list per N4's variation table, but the execution layer is the gating issue.

---

## 2026-04-26 — Stage 2a execution surgery (`trader-r3-v1-vev-v1.{1,2,3,4}.py`)

Goal: fix the spread-cost dominance flagged in v1.0 Stage-1 baseline. Same signal logic, four incremental versions on order routing only. Full per-version analysis in `agent_logs/P2_v1_4_execution_log.md`.

### Headline table (all 3 historical days, `--products full`)

| Version | Mean PnL/day | Trades/day | vs v1.0 | Voucher PnL (3-day) | VEV PnL (3-day) |
|---|---:|---:|---:|---:|---:|
| v1.0 baseline | −1,097,595 | 34,803 | — | −1,820,824 | −1,471,962 |
| v1.1 hold/cooldown | −1,030,396 | 31,646 | +6.1% | −1,857,919 | −1,233,270 |
| v1.2 passive | −410,905 | 7,641 | +62.6% | −71,176 | −1,161,538 |
| v1.3 step-cap | −208,287 | 9,738 | +81.0% | −42,464 | −582,397 |
| v1.4 day-aware | −208,518 | 9,756 | +81.0% | −42,815 | −582,627 |

### Key findings

1. **Passive quoting on vouchers is a step-change** (v1.1→v1.2): voucher loss collapses from −619k/day to −24k/day (−96%). The rust matching model fills passive limits via market-trade flow at our limit price (runner.rs L612–702), so a buy at `best_bid` captures spread instead of paying it.
2. **VEV hedge becomes the dominant cost** in v1.2 at −387k/day (94% of total loss) — escalating to marketable in 50-lot chunks each time realized delta drifts past the ±50 band.
3. **`max_step_size=10` halves VEV loss** (v1.2→v1.3): from −387k/day to −194k/day. Step capping converts each 50-lot escalation into 5×10-lot escalations; net spread paid drops despite slightly more trades/day.
4. **Per-day TTE has negligible impact** (v1.3→v1.4): D1 worsens 684 (0.3%), D2 worsens 11 (0.005%). Vega-ratio sqrt(6/8)=0.866 → 13% delta error in our band regime is small.
5. **Stage-2a goal of 70%-of-paper realized PnL was NOT met.** v1.4 realized = −208k/day vs paper +177k/day = ratio −1.17. We cut losses 81% but still lose money. Residual is the VEV underlying hedge bleed (94% of remaining loss). Stage 2b must address this — see `P2_v1_4_execution_log.md` for prioritized candidates (passive offset, rebalance band, hedge band sweep).

### Variance vs Hard Rule #3

v1.4 cv = 5,952/208,518 = 0.029. Slightly higher than v1.0's 0.017 (consistent losses), but losses are still very smooth across days — confirming the residual cost is structural, not luck.


---

## 2026-04-25 — Stage 2a-extended (v1.5-scalp-only, strip Module C + execution sweep)

Goal: kill the VEV underlying hedge bleed flagged in Stage-2a (94% of v1.4 loss) and re-tune the order-routing knobs without it. Full analysis in `agent_logs/P2_v1_5_extended_log.md`.

### Headline table (all 3 historical days, `--products full`)

| Version | Mean PnL/day | Trades/day | vs v1.4 | Voucher PnL (3-day) | VEV PnL (3-day) |
|---|---:|---:|---:|---:|---:|
| v1.4 baseline | −208,287 | 9,738 | — | −42,464 | −582,397 |
| v1.5 (defaults: pw=1, az=2.5, ms=10) | −14,154 | 368 | +93.2% | ≈ −42,000 | 0 |
| **v1.5 tuned (pw=8, az=3.5, ms=5)** | **−738.8** | **123** | **+99.6%** | **−2,217** | **0** |

### Key findings

1. **Removing Module C (VEV delta hedge + overlay) is the largest single win in this round of work**: even at sweep defaults, mean loss collapses from −208k/day to −14k/day. The hedge was actively losing far more than the overlay was making.
2. **125-combo execution sweep over `passive_wait_ticks × aggressive_z_threshold × max_step_size`** found a clear directional optimum: maximize patience (`pw=8`), require very strong signal (`az=3.5`), take small steps (`ms=5`). All three live on a sweep boundary, so the true optimum may sit outside the explored region.
3. **Tuned-v1.5 is on the right side of zero per round trip on 5100/5200/5300/5500** but per-trade edge is still ≤ +4 across strikes; total PnL is dominated by the small handful of strikes where we still take losing positions (5000: avg −11.30/share over 5 round trips).
4. **Trade volume cut 9× vs v1.4** (≈ 130 fills/day vs ≈ 1100 on vouchers). Capture-to-cost ratio rose at the strikes that still trade (5300: 0.43 → 0.82); passive fill rate rose from ≈ 0% to 4.8% on 5300, 16.7% on 5400.
5. **5200 is structurally bad in both regimes** (capture/cost 0.08 in v1.4, 0.00 in tuned-v1.5 with similar n_fills). Strong candidate for removal from `active_strikes` next iteration.

### Variance vs Hard Rule #3

Tuned-v1.5: per-day PnL D0=−92, D1=−482, D2=−1643. Stdev = 807, |cv| ≈ 1.1 (numerator small). The trend is monotonically worse (D0 → D2) which mirrors v1.4 — consistent with declining-TTE residual signal degradation rather than random variance. Worth investigating in a follow-up.

### What is NOT yet attributed

The diagnostics break down per-strike round-trip economics, but Module A (cross-strike scalp) vs Module B (base-IV mean-rev) PnL is not split — both modules contribute to the same voucher fills. The lambda log carries `a_pnl` / `b_pnl` fields; a follow-up should break out per-module attribution before launching the signal sweep.
