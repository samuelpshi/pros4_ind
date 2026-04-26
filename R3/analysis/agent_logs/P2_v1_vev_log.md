# P2_v1_vev — VEV Stage-1 baseline trader log

Trader: `R3/traders/trader-r3-v1-vev.py`
Config: `R3/traders/configs/vev_v1.json`

## What we did

Built a single-file three-module trader for the VEV ecosystem
(VELVETFRUIT_EXTRACT delta-1 + 6 voucher strikes 5000–5500). HYDROGEL_PACK
is fully ignored; it is handled in the separate `trader-r3-v1-hydrogel.py`.

**Module A — voucher IV scalper.** Per tick: take the order-book mid for each
of the 6 active strikes; invert IV via Newton-Raphson with bisection fallback
on `[0.01, 2.0]`; compute moneyness `m = log(K/S)/sqrt(T)`; least-squares
fit a quadratic smile `v(m)=am²+bm+c` across the strikes that produced an IV.
Compute price residual = `mid − BS(S, K, T, smile_iv(m))`, demean with EMA20,
z-score over a 100-tick rolling buffer, open at `|z|>1.5`, close at `|z|<0.5`.

**Module B — base-IV mean reversion.** Track `c_t` = smile intercept over
500 ticks; z-score; if `|z(c_t)|>1.5` go long/short ATM (split equally
across VEV_5200 and VEV_5300 at ±25 each).

**Module C — VEV underlying.** Two roles sharing the ±200 limit:
1. Delta hedge using BS deltas at fitted-smile IV; target VEV =
   `−round(net_voucher_delta)`.
2. EMA50 mean-reversion overlay on VEV mid (z-scored over 200 deviation
   samples), up to ±50 contracts.
The hard rule (net portfolio delta within ±50) is enforced after combining
hedge + overlay; if breached, the overlay is dropped (hedge wins).

**EDA → parameter mapping** (each is also commented in the trader source):

| Parameter | Default | Source |
|---|---|---|
| `active_strikes` | `[5000..5500]` | N2 cell 18 + N3 cell 16 + N4 cell 32: drop 4000/4500 (intrinsic-only) and 6000/6500 (floor-pegged $0.5). |
| `smile_hardcoded_fallback` | `(0.143, −0.002, 0.236)` | N4 cell 11 pooled fit (n=251,785, R²=0.9836). **Discrepancy flagged**: N3 reports `(0.158, −0.0046, 0.232)` under EPS_EXT=0.5 filter; spec selected N4. Diff is <1.5% IV at \|m\|<0.1 so smile-implied prices are within ~0.05 at the typical strike spacing. |
| `ema_demean_window` | 20 | N4 cell 29: EMA20 demean flips ATM lag-1 autocorr from +0.81 to ≈0/slightly negative — load-bearing for the IV scalp to be tradeable. |
| `zscore_stdev_window` | 100 | Halved from N4 cell 22's 200-tick test for faster reaction. Will be swept Stage 2. |
| `z_open / z_close` | 1.5 / 0.5 | N4 cell 22 standard. |
| `strike_position_caps` | 60/80/120/120/80/60 | N4 cell 38: joint cap ≈109 for top-3 ATM portfolio against VEV ±200. Tuned so ATM strikes carry the most size, wings less. |
| `base_iv_zscore_window` | 500 | N4 cell 26 (z-window for c_t scalp that delivered +2,490 paper PnL). |
| `base_iv_position_size` | 25 | Spec; small additive overlay (combined ±50 split). |
| `vev_hedge_target_band` | 50 | Spec hard rule; net portfolio delta cap. |
| `vev_overlay_ema_window` | 50 | N1 cell 19: VEV demeaned half-life 248 ticks ⇒ EMA50 (alpha~0.039) sits well inside that. |
| `vev_overlay_max_size` | 50 | Spec; light overlay leaving room for hedge swings. |
| `vev_overlay_threshold` | 1.0 z | Spec. |
| `current_day` | 0 | **Stage-1 limitation** — see Open questions. |

## Findings

### Backtest summary (`v1-vev-defaults`, all 3 historical days)

Per-day final PnL (Rust local backtester, `--products full`):
| day | PnL | own_trades |
|---|---|---|
| 0 | −1,117,582 | 35,220 |
| 1 | −1,094,560 | 34,751 |
| 2 | −1,080,644 | 34,437 |
| **mean** | **−1,097,595** | **34,803** |
| stdev | 18,506 | 393 |

cv = stdev/|mean| = 0.017 — consistently bad, not random.

### Per-product attribution (3-day total)

| product | PnL | share |
|---|---|---|
| VELVETFRUIT_EXTRACT | −1,471,962 | 44.7% |
| VEV_5100 | −435,308 | 13.2% |
| VEV_5200 | −426,761 | 13.0% |
| VEV_5000 | −418,793 | 12.7% |
| VEV_5300 | −280,900 | 8.5% |
| VEV_5400 | −145,664 | 4.4% |
| VEV_5500 | −113,397 | 3.4% |
| HYDROGEL_PACK | 0 | 0% (correctly ignored) |
| VEV_4000/4500/6000/6500 | 0 | 0% (correctly dropped) |

VEV is the largest single bucket at ~45%. No single voucher exceeds the
spec's >70% imbalance threshold; losses spread roughly in proportion to
each strike's notional vega/delta exposure (5000–5200 highest, 5500
lowest).

### Module-level paper PnL (mark-to-mid, per-tick `lambdaLog`)

End-of-day cumulative paper PnL by module:
| module | D0 | D1 | D2 | mean |
|---|---|---|---|---|
| A (cross-strike RV scalp) | 144,320 | 139,900 | 110,050 | 131,423 |
| B (base-IV mean rev) | 10,687 | 12,362 | 10,175 | 11,075 |
| C (VEV hedge + overlay) | 25,105 | 32,669 | 47,661 | 35,145 |
| **total paper** | **180,112** | **184,931** | **167,886** | **177,643** |

Implied per-trade slippage:
`(paper_pnl − realized_pnl) / own_trades = (177,643 + 1,097,595) / 34,803
≈ 36.6 per trade`. Median spreads from N2 cell 5 are 1–6 ticks across the
active strikes and 5 ticks on VEV — consistent with paying near-full bid-ask
on every fill.

### Behavioural observations

- **Smile fit fallback never fired.** With 6 active strikes and 100% IV
  survival (N3 cell 16), `len(ivs) ≥ 4` always held. The hardcoded
  coefficients are present as a safety net but not used in this run.
- **Delta hedging holds the band.** Per-tick `net_d` (printed each tick)
  stayed within ±0.5 across all 30k ticks of all 3 days — well inside the
  ±50 spec band. The hedge-priority logic was never triggered to drop the
  overlay (because the unconstrained hedge always landed within band on
  its own).
- **Overlay rarely opens.** `vev_t` is dominated by the hedge component;
  the EMA50 fade overlay rarely contributes because by the time `z_v>1.0`
  the hedge has already bumped VEV to one limit anyway. Overlay's
  marginal contribution is hard to read in the tick log.
- **Trade frequency is the killer.** 3.5 trades per tick on average; the
  bang-bang signal (jump to ±cap on `|z|>1.5`, jump to 0 on `|z|<0.5`)
  thrashes through threshold crossings. Each thrash crosses spread.
- **No strike pinned to its position cap for long stretches.** Spot
  `nv_d` swings between roughly ±60 across the day, which means the
  combined voucher target keeps flipping. Caps are not the constraint.
- **Position limits never blocked.** Net VEV target stayed within ±100
  most ticks (max observed |vev_t| ≈ 80). Voucher caps similarly under-
  used.

## Open questions / known limits

### Stage-1 limitations to flag for Sam / consolidator

1. **Day inference is hard-coded to `current_day=0`.** The Rust backtester
   runs each historical day as a separate process with `state.timestamp`
   resetting to 0; the trader cannot self-detect day. Backtest TTE is
   computed as if every day were day 0 (TTE 8d → 7d during the day) when
   in truth historical day 1 is 7d → 6d and day 2 is 6d → 5d. Vega
   ratio sqrt(6/8) = 0.866 ⇒ up to ~13% delta error on day 2 vs day 0.
   Hedge band is ±50 so the absolute error stays small in our regime,
   but Stage-2 backtest accuracy can be improved by either (a) running
   each day with its own config override or (b) wiring the day in via
   environment variable in a backtester wrapper script. For live R3, set
   `current_day=3`.

2. **Per-module PnL is paper-only (mark-to-mid).** True per-fill
   attribution requires tagging each Order with a module ID, which the
   IMC `Order` interface doesn't support. The `lambdaLog` numbers above
   are the prior-tick shadow position marked to current mid. For a true
   attribution test, run with each module disabled in turn (Stage 2).

3. **Spread crossing on every order is the dominant loss driver.** The
   strategy logic appears correct: paper PnL is +177k/day, smoothly
   positive, hedge band held, attribution sane. Stage 2 must address
   execution before sweeping signal parameters — sweeping z-thresholds
   on top of marketable orders will explore a different surface than the
   one that matters once orders go passive.

### Stage-2 priorities (data-driven from this baseline)

In rough order of expected impact:

1. **Reduce trade frequency.** Hysteresis bands (open at z=1.5 but require
   z to cross 0 before flipping, not just drop below 0.5); per-tick max
   step size on position changes; rebalance bands on the hedge so VEV
   doesn't re-trade every tick. This is the single highest-impact knob.
2. **Passive quoting.** Replace `emit_to_target` (which always lifts/hits
   the opposite side) with limit orders at the smile-implied fair value
   ± a small offset. Converts spread cost into spread capture. Bigger
   refactor; should be tested as a separate variant.
3. **Z-window length sweep.** N4's variation list ranks EMA window first
   for the IV scalp; the 100-tick z-window I used is shorter than N4's
   200-tick test. Sweep `{50, 100, 200, 500}`.
4. **Overlay disambiguation.** Separately test Module A only, then A+B,
   then A+B+C, to read true attribution rather than paper-PnL approx.
5. **Hedge frequency.** Currently hedges every tick. Try every-N-tick
   hedging and ±X delta band before adjusting (per CLAUDE.md "explicit
   VEV delta hedge rebalance bands {20, 50, 100}" sweep idea).
6. **Smile fit method.** Per-tick refit was deferred (N3 finds per-tick
   coefs are noisy on `a` and `b`); try vega-weighted pooled vs unweighted
   pooled vs per-tick.

### Latent items

- **Smile coefficient discrepancy** between N3 (0.158, −0.0046, 0.232)
  and N4 (0.143, −0.002, 0.236) is unresolved. Spec used N4; if Stage 2
  shows the smile-implied fair value is biased on either wing or near
  ATM, switching to N3 is cheap to test (one config edit).
- **Module B and Module A can fight on 5200/5300.** When Module A wants
  short on 5200 but Module B wants long, the combined target can be near
  zero, producing per-tick churn. Worth tracking the count of opposing
  signals on those two strikes.
- **`vev_overlay_threshold=1.0` is small.** Combined with the hedge
  taking priority on band breach, the overlay often gets immediately
  killed. Consider raising threshold or lowering hedge band so overlay
  has space to act.
- **No protection against the IV solver returning ill-posed results.**
  The solver returns `None` cleanly when market price is below intrinsic
  or above S, but if the smile fit produces negative IVs at extreme `m`
  (none observed in this run), the BS pricer returns the intrinsic. Not
  a current bug, but a future risk if active strikes ever extend.
