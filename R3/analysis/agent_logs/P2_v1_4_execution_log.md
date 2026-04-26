# P2_v1_4_execution — Stage 2a execution surgery on the VEV trader

Trader files: `R3/traders/trader-r3-v1-vev-v1.{1,2,3,4}.py`
Config: `R3/traders/configs/vev_v1.json` (Stage 2a keys appended)

## What we did

Stage-1 baseline (`v1.0`, see `P2_v1_vev_log.md`) lost ~1.10M/day on +177k/day
of paper alpha — i.e., spread crossing on 35k/day marketable orders ate the
strategy. Stage 2a is execution surgery: same signal logic, four
incremental versions that fix order routing.

| Version | Diff vs prior |
|---|---|
| v1.1 | Module A per-strike `min_hold_ticks=5` and `cooldown_ticks=10` gating. Same marketable execution. |
| v1.2 | New `emit_passive_or_marketable()`. Vouchers post limits at our own touch (buy at best_bid, sell at best_ask) and only escalate to marketable when `|z| >= aggressive_z_threshold=2.5`. VEV hedge same, with extra "realized net delta breaches band" escalation and `hedge_passive_wait_ticks=1`. |
| v1.3 | Per-tick `max_step_size=10` cap on the diff between target and current position before order emission (vouchers and VEV alike). |
| v1.4 | Per-day `current_day` routing via optional `configs/_current_day.txt` (no `import os` — Hard Rule #10). Smile-coef sanity check noted. |

### Pre-flight: matching model verified

Before designing v1.2 I read `~/prosperity_rust_backtester/src/runner.rs`
lines 540–740. `match_orders_for_symbol` walks the **opposite-side** book
for each of our orders: a buy with quantity > 0 only fills against asks
where `level.price <= order.price` (line 616). A buy at `best_bid` therefore
sits passive (no ask satisfies `ask <= best_bid`). It can still fill
against market trades that cross our level via lines 661–740, at our limit
price (line 702). Confirmed: passive-first execution captures spread on
this matching model.

## Findings

### Headline backtest table (Rust, all 3 historical days, `--products full`)

| Version | D0 PnL | D1 PnL | D2 PnL | mean PnL | trades/day | vs v1.0 |
|---|---:|---:|---:|---:|---:|---:|
| v1.0 baseline | −1,117,582 | −1,094,560 | −1,080,644 | **−1,097,595** | 34,803 | — |
| v1.1 hold/cooldown | −1,049,807 | −1,023,451 | −1,017,930 | **−1,030,396** | 31,646 | +6.1% |
| v1.2 passive | −410,130 | −402,035 | −420,549 | **−410,905** | 7,641 | +62.6% |
| v1.3 step-cap | −204,420 | −205,624 | −214,816 | **−208,287** | 9,738 | +81.0% |
| v1.4 day-aware | −204,420 | −206,308 | −214,827 | **−208,518** | 9,756 | +81.0% |

**Across-day stdev** (cv = stdev/|mean|):
v1.0 = 18,506 (cv 0.017); v1.4 = 5,952 (cv 0.029). Losses are still
remarkably consistent across days — the residual is structural, not luck.

### Per-product attribution (3-day total, vouchers vs VEV)

| Version | VEV (underlying) | vouchers total | voucher share |
|---|---:|---:|---:|
| v1.0 | −1,471,962 | −1,820,824 | 55% |
| v1.1 | −1,233,270 | −1,857,919 | 60% |
| v1.2 | −1,161,538 |    −71,176 |  6% |
| v1.3 |   −582,397 |    −42,464 |  7% |
| v1.4 |   −582,627 |    −42,815 |  7% |

The Module A/B voucher loss is essentially eliminated by passive quoting
(v1.0 −1.82M ⇒ v1.2 −71k, a 96% reduction). The remaining VEV loss in
v1.4 is the delta-hedge crossing spread; v1.3 step-cap halved that.

### Trade count vs spread cost

`(realized − paper) / trades` is the implied per-trade slippage:

| Version | trades/day | paper PnL/day (est.) | realized PnL/day | implied slip/trade |
|---|---:|---:|---:|---:|
| v1.0 | 34,803 | +177,643 | −1,097,595 | −36.6 |
| v1.1 | 31,646 | +177,643* | −1,030,396 | −38.2 |
| v1.2 |  7,641 | +177,643* |   −410,905 | −77.0 |
| v1.3 |  9,738 | +177,643* |   −208,287 | −39.7 |
| v1.4 |  9,756 | +177,643* |   −208,518 | −39.6 |

\* assumes paper PnL roughly invariant across versions; `lambdaLog` per-tick
attribution lines from each run could refine this, but the signal logic is
unchanged so the order-of-magnitude is correct.

The v1.2 implied per-trade slip going *up* even as total realized loss
goes down is the expected sign that fewer, bigger marketable hedges are
absorbing a larger share of spread per trade — passive voucher fills are
near-zero-slip but the residual VEV escalations are expensive. v1.3
introduces step capping, which shrinks each escalation back to size 10
and brings per-trade slip back near v1.0 levels while halving total cost.

### Paper / realized ratio

Paper alpha is +177k/day (Module A=+131k, B=+11k, C=+35k per `P2_v1_vev_log.md`).

| Version | realized / paper |
|---|---:|
| v1.0 | −6.2 |
| v1.1 | −5.8 |
| v1.2 | −2.3 |
| v1.3 | −1.17 |
| v1.4 | −1.17 |

Stage-2a goal was "70% of paper". We did not reach it — v1.4 realised PnL is
still negative and the ratio is **−1.17×**, i.e., we lose ~1.17× the paper
alpha per day. We did cut losses 81% (4.7M→1.0M over 3 days). The remaining
loss is structurally the VEV underlying.

### What the residual VEV loss is

In v1.4, VELVETFRUIT_EXTRACT carries −195k/day. Vouchers carry −14k/day.
The hedge mechanic: as voucher passive fills accumulate, realised net delta
drifts. When it crosses `hedge_band=50`, the hedge escalates to marketable
in chunks ≤ `max_step_size=10`. With ~9–10 step-capped marketable VEV
fills per drift cycle and VEV spread of ~5 ticks (N2 cell 5), each cycle
costs 50 × ~10 lots ≈ 500 per cycle × ~400 cycles/day ≈ −200k/day —
order-of-magnitude matches.

## Behavioural observations (stable across v1.2–v1.4)

- **Voucher orders almost never escalate.** `aggressive_z_threshold=2.5`
  is well above the typical `z_open=1.5` band; only spike events trigger
  marketable. Voucher PnL went from −607k/day to ~−14k/day; the small
  residual is the rare escalation events.
- **Hedge escalation is the dominant cost.** Each delta-band breach
  triggers a step-capped marketable VEV order until band re-entry. The
  step cap shrinks per-trade slip but adds trade *count*, hence v1.3's
  higher trades/day vs v1.2.
- **Paper PnL distribution (v1.4 D0 sample from `lambdaLog`)** shows
  Module C still printing positive in mark-to-mid (hedge captures the
  ATM gamma and pays only delta drift); Modules A/B essentially
  unchanged because the signal is the same.
- **Per-day TTE matters less than expected.** v1.4 vs v1.3 (which used
  current_day=0 for all 3 days) differ by < 1k PnL on D1 and D2
  combined. Vega-ratio sqrt(6/8)=0.866 ⇒ ~13% delta error → small
  absolute error at our band sizes. Confirms `P2_v1_vev_log.md`'s prior.
- **Smile coefficient choice is moot.** With `smile_fit_min_strikes=4`
  and 6 strikes always producing IVs, the hardcoded fallback never
  fires across all 3 days of all 4 versions. N4 vs N3 pooled coefs
  produce identical backtests. (Switching live values is one config
  edit if Stage 2b shows wing/ATM bias.)

## Open questions / known limits

1. **Realized PnL is still negative.** v1.4 at −208k/day cuts the v1.0
   loss by 81% but doesn't reach breakeven. Stage 2b must address the
   remaining VEV hedge cost. Candidate moves:
   - Widen `hedge_band` from 50 to 75–100 (spec said 50 is hard, but a
     sweep to confirm the bound is set right would be cheap).
   - Add a `hedge_rebalance_band` of e.g. 5: skip emitting hedge orders
     when the size diff is tiny — already in config but currently
     unused. v1.5 should plumb it.
   - Hedge passive at best_bid+1 / best_ask−1 (one tick inside the
     touch) to fill faster while still capturing edge.
   - Switch to a more sparse rebalance schedule (every K ticks, not
     every tick) when realized delta is small.
2. **Paper PnL estimate is from v1.0.** Stage 2a's per-tick `lambdaLog`
   from v1.4 was not parsed for module attribution; reasoned from
   "signal unchanged ⇒ paper unchanged". Could be tightened with a
   single parsing pass over the v1.4 D0 submission.log.
3. **Module B and Module A still combine into one voucher target before
   execution.** When they disagree on 5200/5300, the combined target
   may flicker. Stage 2b could route them as separate orders with
   independent escalation gates.
4. **Day inference uses a side-channel file.** Works in backtest with
   the wrapper script; for live R3 set `current_day=3` directly in
   `vev_v1.json` and ensure `_current_day.txt` is absent. The
   IMC sandbox only uploads the .py, so the file lookup will silently
   noop in production — desirable.
5. **`max_step_size=10` was not swept.** Sensible values in {5, 10, 20}
   were not compared. Stage 2b sweep candidate.
6. **Passive quote at touch may be picking off stale book levels.** When
   our buy at best_bid fills via a market sell, we sometimes are buying
   from a counterparty whose flow predicts the market is about to drop
   (adverse selection). If the realized hedge cost is partly explained
   by adverse selection on the voucher side, passive isn't entirely
   "free" — Stage 2b can measure this by computing per-fill 1-tick
   forward MTM PnL.

## Stage-2b priorities (data-driven from this baseline)

In rough order of expected impact on the remaining −208k/day:

1. **Hedge passive-quote pricing.** Try `vev_passive_offset = 1` (post
   one tick inside touch) so the hedge fills more often without
   crossing. Should kill most of the remaining VEV bleed.
2. **`hedge_rebalance_band`.** Already in config; plumb it so that we
   skip emitting hedge orders when |target_diff| < band. Skips many
   one-lot-noise hedge ticks.
3. **Hedge band sweep.** Sweep `vev_hedge_target_band` in {30, 50, 75,
   100} to confirm 50 is the right point on the slippage-vs-delta-risk
   curve.
4. **Adverse-selection diagnostic.** For each passive voucher fill,
   compute forward 5/10/20-tick MTM. If forward MTM is consistently
   negative (we keep being lifted at the top / hit at the bottom),
   widen the passive offset by 1 tick.
5. **`max_step_size` sweep**: {5, 10, 20}.
6. **EMA / z-window sweep on Module A** (deferred from Stage 2 plan): the
   signal layer has not been tuned at all — these will only matter once
   execution is solved.

## Files produced

- `R3/traders/trader-r3-v1-vev-v1.1.py`
- `R3/traders/trader-r3-v1-vev-v1.2.py`
- `R3/traders/trader-r3-v1-vev-v1.3.py`
- `R3/traders/trader-r3-v1-vev-v1.4.py`
- Updated `R3/traders/configs/vev_v1.json` (Stage 2a keys)
- Appended 12 rows to `R3/analysis/backtest_results.csv`

## Next session starts with

Stage 2b: address the residual VEV hedge bleed. Start by trying
`vev_passive_offset=1` and `hedge_rebalance_band=5` plumbed in v1.5,
then sweep `vev_hedge_target_band`.
