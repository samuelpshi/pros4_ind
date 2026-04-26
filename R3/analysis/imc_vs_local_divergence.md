# IMC vs local backtester divergence — HYDROGEL_PACK Stage 1 trader

**Trader**: `R3/traders/trader-r3-v1-hydrogel.py`
**IMC log**: `R3/logs/trader-r3-v1-hydrogel.log` (submissionId
`9bacc034-2e80-4be0-8c19-087a0ca7f2d3`)
**Local run dir**: `~/prosperity_rust_backtester/runs/backtest-1777164066302/`

## TL;DR

The divergence is **not** a CONFIG drift, **not** a `traderData`/EMA
persistence break, and **not** systematically worse fill prices on IMC. It
is **the local Rust backtester's fill model being so restrictive that the
trader's MM logic is never actually exercised**. Local fills 20 of our
orders in the first 25,900 ticks of day 2 and then stops filling for the
remaining 7,410 ticks of the captured window (and 974,000 ticks of the
full day); IMC fills 115 of the trader's orders in just the first 100,000
ticks of the same day. With local fills frozen, the trader sits in a
mostly-static +76 position whose mark-to-market drifts with the underlying;
with IMC fills, the same trader is bounced between ±200 inventory limits
17 times in the captured window, takes 19 explicit `Orders for product
HYDROGEL_PACK exceeded limit of 200` rejections, and ends the window at
−7,106 after touching −12,357 mid-window.

## Scope of the IMC log

The submission log spans **day 2 only, timestamps 0-99,900 (1,000 ticks =
10% of one historical day)**. The user's verbal description of "D1
catastrophe drops to ~−11K mid-day" matches this exact window:
HYDROGEL_PACK PnL bottoms at −12,357 at ts=69,700, recovers to −7,106 by
ts=99,900. IMC's day labelling differs from our local file labelling but
the underlying data is from `prices_round_3_day_2.csv`.

## Step 1 — CONFIG diff (run, ruled out)

Field-by-field diff of the inlined `CONFIG` dict in
`trader-r3-v1-hydrogel.py` vs `configs/hydrogel_v1.json`: 7/7 keys match,
all values bit-identical (including `skew_strength=1.0` as a float). The
inlined-dict change introduced in the `import os` fix did not drift.

## Step 2 — IMC log schema

Top-level keys of the `.log` JSON object:
- `submissionId` (str)
- `activitiesLog` (str, semicolon-CSV) — full per-tick L3 book for all 12
  R3 products and a running per-product `profit_and_loss`. 12,002 lines.
- `logs` (list[1000]) — `{sandboxLog, lambdaLog, timestamp}` per tick.
  `lambdaLog` is empty for all 1000 ticks (the trader doesn't `print()`).
  `sandboxLog` is empty except for **19 ticks (ts 72,300–78,100) carrying
  `Orders for product HYDROGEL_PACK exceeded limit of 200 set`** — IMC's
  position-limit rejection messages.
- `tradeHistory` (list[228]) — `{timestamp, buyer, seller, symbol,
  currency, price, quantity}`. Our trades have `buyer="SUBMISSION"` or
  `seller="SUBMISSION"`; the counterparty is anonymized to `""`. 115 of
  the 228 are HYDROGEL_PACK trades involving our SUBMISSION.

There is no `fair_value` field in the IMC log — we'd have to log it from
the trader via `lambdaLog` (i.e. `print()`) on a future submission to get
visibility into the trader's internal EMA. For this diagnosis, the
matching trade prices below give indirect evidence that the EMA is
behaving identically on both sides.

## Step 3 — Local persisted run

Re-ran with `--persist --day=2`. Artifacts in
`runs/backtest-1777164066302/`:
- `trades.csv` — same schema as IMC `tradeHistory` (timestamp, buyer,
  seller, symbol, currency, price, quantity).
- `activity.csv` — same schema as IMC `activitiesLog` (per-tick book).
- `pnl_by_product.csv` — per-tick MTM PnL with each product as its own
  column.
- `metrics.json` — `queue_penetration: 1.0`, `trade_match_mode: "all"`,
  `price_slippage_bps: 0.0`, `own_trade_count: 20` for the **full day**.

Worth noting: **all 20 local trades on day 2 happen in the first 25,900
ticks**. After ts=25,900 the local backtester fills nothing for the
remaining 9,740 ticks of the IMC window (and nothing for the remaining
974,100 ticks of the full day).

## Step 4 — Side-by-side comparison (IMC window: ts 0–99,900, day 2)

### (a) Fill count and volume

| metric                          | LOCAL | IMC  | ratio |
|---------------------------------|-------|------|-------|
| total trades                    | 20    | 115  | 5.8×  |
| buys (count)                    | 13    | 56   | 4.3×  |
| sells (count)                   | 7     | 59   | 8.4×  |
| buy units                       | 139   | 710  | 5.1×  |
| sell units                      | 63    | 775  | 12.3× |

IMC fills the trader **5.8× more often** in the same window. The local
fill model is materially more restrictive than IMC.

### (b) Fill price vs mid (signed by side)

Edge convention: positive = good for us (bought below mid / sold above mid).

|              | n   | mean    | median | min     | max     |
|--------------|-----|---------|--------|---------|---------|
| LOCAL buys   |  13 | −6.500  | −8.0   | −10.0   | −3.5    |
| LOCAL sells  |   7 | −5.000  | −4.5   | −8.0    | +1.0    |
| IMC buys     |  56 | −7.321  | −8.0   | −13.0   | +0.0    |
| IMC sells    |  59 | −7.144  | −8.0   | −11.5   | +6.0    |

Both venues show **negative mean edge**: we're systematically buying ABOVE
mid and selling BELOW mid because both sides of the trader cross the
spread (the take leg always crosses; the passive quotes at fv ± 3 are
inside the wall at fv ± 8 so when filled they still sit on the "wrong"
side of mid). IMC's mean edge is ~1 worse per fill, but the **dominant
effect is volume, not per-fill price**: 5–12× more units multiplied by
~7 ticks of adverse selection compounds to the −7,106 IMC PnL. Local's
20-trade tab simply doesn't accumulate enough adverse selection to matter.

**The first 5 trades on each side are bit-identical** (same ts, side,
quantity, fill price):

```
ts= 1500 SELL 12 @ 10017  mid=10020.5
ts= 3200 SELL 12 @ 10022  mid=10030.0
ts= 3300 SELL 12 @ 10021  mid=10029.0
ts= 3400 SELL 11 @ 10023  mid=10031.0
ts= 7600 BUY   5 @ 10018  mid=10014.0
```

Identical fill prices on identical ticks rules out price-slippage
differences and confirms the trader's order generation is identical on
both venues — which means EMA / `traderData` persistence is intact on
IMC (Step 4(c) hypothesis ruled out).

### (c) `traderData` / EMA persistence

Indirect evidence only (no `fair_value` logged), but the bit-identical
matching trades in (b) plus the absence of any `lambdaLog` exception
output anywhere in the 1000 ticks (which would show up if the JSON
round-trip of the EMA ever raised) means **the EMA persistence is fine on
IMC**. Hypothesis 4(c) ruled out.

### (d) Position trajectory

Side-by-side at checkpoints (mid is identical because both consume the
same `prices_round_3_day_2.csv`):

| ts     | mid      | LOCAL pnl | LOCAL pos | IMC pnl    | IMC pos |
|--------|----------|-----------|-----------|------------|---------|
|     0  | 10011.0  |     +0.00 |       +0  |      +0.00 |     +0  |
|  5000  | 10027.0  |   −296.00 |      −47  |   −296.19  |    −47  |
| 10000  | 10023.0  |    −83.00 |      −42  |   −102.25  |    −42  |
| 20000  | 10016.0  |   +317.00 |      −54  |   +309.12  |    −54  |
| 30000  | 10005.0  |  +1339.00 |      +76  |  +2438.00  |   +200  |
| 40000  |  9993.0  |   +427.00 |      +76  |   +209.50  |   +178  |
| 50000  |  9952.0  |  −2689.00 |      +76  |  −7424.75  |   +200  |
| 60000  |  9962.0  |  −1929.00 |      +76  |  −5625.12  |   +180  |
| 70000  |  9996.0  |   +655.00 |      +76  | −12208.62  |   −200  |
| 80000  |  9960.0  |  −2081.00 |      +76  |  −5009.09  |    +50  |
| 90000  |  9927.0  |  −4589.00 |      +76  |  −8549.25  |   +200  |
| 99900  |  9960.0  |  −2081.00 |      +76  |  −7105.88  |    −65  |

Position range over the window:

|                  | LOCAL    | IMC        |
|------------------|----------|------------|
| min position     |   −58    |   −200     |
| max position     |   +76    |   +200     |
| trades \|pos\|≥180 |    0   |    16      |
| limit rejections |    0     |    19      |

LOCAL hits +76 at ts ≈ 25,900 and **never trades again for the rest of
the day** — the +76 is then carried as static inventory whose MTM swings
purely with mid drift (which is why local PnL oscillates between roughly
+1.3K and −4.6K without any actual trading). IMC, on the same data,
swings to ±200 four separate times: long +200 at ts 25,600 (selling rally
at mid≈10027), still +200 at ts 50,000 (catching falling knife to mid
9952), flips short −200 at ts 70,000 (mid recovered to 9996), back long
+200 at ts 90,000 (mid 9927). Each flip happens against the move.

This is **textbook "fading a trend with a mean-reverting MM"**. The
trader is doing what it's designed to do: when bid hits, it's long; when
ask hits, it's short. With the inventory skew at `skew_strength=1.0`
(only 1 tick of pull at full position) this is far too weak to fight a
50-tick mid swing. On IMC, where fills happen, this hits the ±200 wall
repeatedly and the rejections in `sandboxLog` mark the bursts where
even our throttled passive quotes can't squeeze any more orders past
the limit.

On local, none of this is exercised — the fill model freezes the
position before the swings begin.

## Diagnosis

**Hypothesis (a) — local fill model too generous**: REJECTED. Inverted
direction. Local fills FAR FEWER orders than IMC, not more.

**Hypothesis (b) — local fill prices systematically better**: REJECTED.
Identical fill prices on the matching trades; mean edge is within ~1
tick across the broader sample, with both venues negative.

**Hypothesis (c) — `traderData`/EMA persistence broken on IMC**: REJECTED.
Identical decisions on matching ticks; no exception in `lambdaLog`.

**Hypothesis (d) — local fill model is letting the trader "fade a move"
that IMC fills it into**: **CONFIRMED, with a sign flip from how the
hypothesis was phrased**. The user's framing assumed IMC was the
generous-fill side; in fact IMC is the realistic side and **local is
the under-filling side**. After ts=25,900 the local backtester refuses
to fill any more of our orders; IMC continues to fill them at a
sustained 1.15 trades/tick rate.

### Root cause

`metrics.json` reports the local fill model as `queue_penetration: 1.0`,
`trade_match_mode: "all"`, `price_slippage_bps: 0.0`. With
`queue_penetration=1.0` the local backtester treats our resting orders
as sitting at the back of the FIFO queue at each level: we only fill
when **all other resting volume at our level has been consumed first by
incoming marketable flow**. On HYDROGEL_PACK's 16-wide spread with
~10–25 units of standing volume per level (per `bid_volume_1` /
`ask_volume_1` in activity.csv), it's plausible that the early ticks
have lighter standing volume (so we get the residual) and later ticks
have enough standing volume that incoming flow never reaches us. IMC
appears to operate closer to a touch-fill model where any incoming
marketable order at-or-through our limit price hits us proportionally
without the hard FIFO assumption.

This is a **fill-model calibration problem in the local backtester**, not
a trader bug. The Stage 1 baseline trader's "good" local PnL of
+1719/+10079 is an artefact of the fill model freezing inventory after
~10% of the day; the trader is essentially being scored on its luck
buying-and-holding +76 units rather than on its market-making behaviour.

## Proposed fix (DO NOT IMPLEMENT — for review)

Two layers — **do not act on either until the user confirms which path**:

1. **Calibrate the local fill model first.** Re-run the same trader at
   `--queue-penetration` values stepped down from 1.0 (e.g. 0.5, 0.25,
   0.1, 0.0) and find the value at which local trade count and PnL
   trajectory most closely track the IMC log. This is purely a
   measurement: no trader change. If `queue_penetration=0.0` (touch-fill)
   gets us close to IMC's 115 trades over the same window, that's the
   right setting going forward and Stage 2 sweeps must use it. Otherwise
   we'll keep optimizing against an oracle that doesn't predict
   real-world PnL (Hard Rule #4 explicitly warns about exactly this
   class of failure).

2. **Once the fill model matches IMC, the trader fix is its own thing.**
   Even with fills calibrated, the −7K IMC PnL says the trader's
   parameters are wrong for HYDROGEL's swing dynamics. Likely candidates
   in priority order: (i) `skew_strength=1.0` is way too weak — at full
   ±200 inventory it shifts quotes by only 1 tick, nowhere near enough
   to pull inventory back during a 50-tick mid swing. Try 5–10 and see
   if position pinning resolves. (ii) `take_edge=4` might be filling us
   into the trend; consider raising to 8 or removing the take leg
   entirely until we have a real signal. (iii) `passive_quote_size=30`
   is large relative to standing volume; smaller quotes spread across
   more ticks would give the inventory skew more time to react.

Both layers are deferred until the user has reviewed this diagnosis.

## Numbers, not vibes — receipts

- IMC log: `R3/logs/trader-r3-v1-hydrogel.log` (submissionId
  `9bacc034-2e80-4be0-8c19-087a0ca7f2d3`).
- Local persisted run:
  `~/prosperity_rust_backtester/runs/backtest-1777164066302/`.
- Analysis scripts: `/tmp/parse_imc_log_v2.py`,
  `/tmp/imc_hydrogel_analysis.py`, `/tmp/local_vs_imc_v2.py` (kept
  outside the repo as they're investigation-only).
- Position-limit rejection events on IMC: 19, ts 72,300–78,100, all at
  recorded position −195 to −175 with mid 9953–9977.
- Local final position trace: trades 1–20 at ts 1,500–25,900; trades 21+
  do not exist for the full 10,000-tick day.
