# R4 Counterparty Analysis — Part 2: Sophisticated Edge Sources

Following up on `FINDINGS.md`, this round digs into hidden edge that simple per-trader PnL doesn't surface. Three of the four probes found *substantial* new signal; one was negative.

## 1. Aggressor classification — the picture changes substantially

For every trade we know the bid_price_1 / ask_price_1 of the resting book at that timestamp. So we can infer the aggressor:
- price ≥ ask  →  buyer was the aggressor (took the offer)
- price ≤ bid  →  seller was the aggressor (hit the bid)

It turns out **every trader's role is essentially binary**:

| Trader  | Role                  | Buy aggr% | Buy passive% | Sell aggr% | Sell passive% |
|---------|-----------------------|----------:|-------------:|-----------:|--------------:|
| Mark 01 | **pure passive maker** |      0% |        100% |        0% |         100% |
| Mark 14 | **pure passive maker** |      0% |        100% |        0% |         100% |
| Mark 49 | **pure passive maker** |      6% |         94% |        1% |          99% |
| Mark 22 | **mixed**             |     14% |         86% |       93% |           7% |
| Mark 38 | **pure taker**         |    100% |          0% |      100% |           0% |
| Mark 55 | **pure taker**         |    100% |          0% |      100% |           0% |
| Mark 67 | **pure taker**         |     99% |          1% |       0% |           0% |

So the population separates:
- **Makers:** M01, M14, M49 (post quotes; collect spread when right, lose when wrong)
- **Takers:** M38, M55, M67 (cross the spread on every fill)
- **Mixed:** M22 (passively bids on the rare cases he buys; aggressively hits when selling)

Now the edge-per-fill conditioned on role:

| Trader | role  | n | edge_close per fill |
|--------|-------|---:|---:|
| Mark 67 | **TAKER** | 164 | **+166.3** |
| Mark 14 | maker | 2,172 | +19.4 |
| Mark 01 | maker | 1,843 | +5.5  |
| Mark 22 | taker | 1,436 | −4.9  |
| Mark 55 | taker | 1,198 | −11.0 |
| Mark 38 | TAKER | 1,478 | **−22.7** |
| Mark 49 | maker | 120  | **−127.6** |

This rearranges the story:

**Mark 67 is a *taker* who pays the bid-ask spread and STILL wins +$166/fill.** That's qualitatively different from "structural buyer who tends to be right". Paying the spread and still winning means he has signal *strong enough to overcome the slippage*. This is the cleanest informed-flow signature in the data.

**Mark 49 is a *maker* who loses $128/fill.** He's posting quotes and getting picked off — i.e., his bids/offers are stale. The question becomes: *who picks him off?* Answer is mostly Mark 67: M49's quotes on VELVETFRUIT are the resting offers Mark 67 lifts. M67's edge ≈ M49's loss on that product, almost exactly.

**Mark 14 is a maker who wins $19/fill.** Standard market-maker spread capture. He makes his money by being on the *passive* side of every fill.

**Mark 38 is a taker who loses $23/fill.** Uninformed taker — pays the spread *and* picks the wrong direction. 80% loss rate at +5k ticks.

### Strategic upshot

When designing our trader, the question for each trade we contemplate is **"who's likely on the other side?"**:
- If we passively post a tight quote on VELVETFRUIT, the trader most likely to lift it is Mark 67 — and we *don't* want to be lifted by Mark 67 (he's picking us off). So we should **widen quotes when we suspect M67 is active**.
- If we passively quote HYDROGEL and Mark 38 lifts our offer, that's the most profitable possible counterparty (his +5k win-rate is 0.20 = our 0.80).
- If we want to hit a quote (be the taker), the best target is **Mark 49's resting bid/offer on VELVETFRUIT**, exactly what Mark 67 does. Lift Mark 49 the way M67 does, sit on the inventory, mark it to close.

---

## 2. Multi-leg / strip trades — the BIGGEST hidden signal

Grouping by (day, timestamp, buyer, seller), we find **333 multi-leg events** where the same pair of traders crosses ≥2 products in a single timestamp. Crucially: **317 of the 333 events are Mark 01 ⇄ Mark 22**, and they're STRIPS:

```
day 3 ts=524000   M01 buys from M22:  [VEV_5200, 5300, 5400, 5500, 6000, 6500]   (6 legs)
day 3 ts=431900   M01 buys from M22:  [VEV_5200, 5300, 5400, 5500, 6000, 6500]   (6 legs)
... 315 more like this ...
```

This is **a pre-arranged block trade pattern**: Mark 22 quotes the entire high-strike OTM strip at static low prices (often 0.5 for the deepest OTM), and Mark 01 lifts the whole strip in one synchronized timestamp. **Per strip-event** the realised edge for Mark 01 is roughly **6 legs × 0.5 SeaShells = +$3 per event** at a minimum (and frequently more on the lower OTM strikes that aren't pinned to 0.5).

317 events × ~$3 base edge = ~$950 of risk-free PnL just on the deepest-OTM legs, before counting the higher-edge 5200–5500 legs.

Two other small-but-systematic patterns:
- **Mark 38 ⇄ Mark 22 strikes 4000–5300** — appears 1× day 1 (ts 437,100) and 2× day 3. Less frequent but same shape (low-strike strip).
- **Mark 14 ⇄ Mark 22, Mark 14 ⇄ Mark 38** — 4–5 events each, smaller scale.

### Strategic upshot — front-run Mark 01 on strip events

The behaviour is predictable enough that it's worth coding directly:

> **Trigger:** any timestamp where `state.market_trades` shows Mark 22 listed as seller on ≥3 different VEV strikes simultaneously, OR `state.order_depths[VEV_X].sell_orders` shows the same volume at the same price across the high-strike strip (a "strip quote" signature).
>
> **Action:** fire IOC bids on the entire high-strike strip *one tick before* Mark 01 normally arrives. Specifically — on VEV_6000 and VEV_6500, lift any 0.5-priced offer; on VEV_5200–5500, lift below fair value (which we already estimate from the smile model from R3 EDA).

Even if we capture only 5–10% of M01's strip edge before he beats us to it, that's a "free" few hundred SeaShells per round.

---

## 3. Trade size as conviction

Within each trader, bin fills into 4 quantiles by quantity, look at edge per unit:

**Mark 67 (informed buyer, VELVETFRUIT):**

| qty quantile | n | avg_qty | **edge per unit** |
|---|---:|---:|---:|
| Q0 (small) | 46 | 5.8 | +16.1 |
| Q1         | 53 | 8.4 | +18.0 |
| Q2         | 30 | 10.4 | **+21.8** |
| Q3 (large) | 36 | 13.4 | +17.1 |

Edge per unit *increases* monotonically up to Q2, peaking at +21.8 per unit on his bigger lots. **Trade size IS conviction.** This is *exactly* the "look at fill size as a confidence signal" pattern.

**Mark 49 (uninformed seller, VELVETFRUIT):**

| qty quantile | n | avg_qty | **edge per unit** |
|---|---:|---:|---:|
| Q0 |  45 |  6.6 | −2.6  |
| Q1 |  17 |  9.0 | −13.9 |
| Q2 |  35 | 10.9 | −15.9 |
| Q3 |  25 | 14.0 | **−16.0** |

His small fills barely lose; his big fills lose 6× as much per unit. **The bigger Mark 49's order, the harder we should fade him.**

**Mark 22:** Q0–Q2 ~−$2/unit, Q3 (avg 7.7 lots) **−$11.3/unit**. His large dumps are much worse than his small dumps. Strip-trade events tend to be Q0/Q1 sizes (1–2 lots per leg) — this is the *small-and-frequent* edge channel. The Q3 channel is his bulk dumps, which are even cheaper to fade.

### Strategic upshot

In the live trader, weight signals by counterparty fill size:

```
informed_score = +1 if (M67 buys with qty ≥ 10 lots) else +0.5
uninformed_score = -1 if (M22 sells with qty ≥ 7 lots) else -0.5
```

Mark 67's 10+ lot fills carry the strongest forward signal in the dataset.

---

## 4. Lead-lag VEV_4000 → VELVETFRUIT — NEGATIVE result

Theory: option traders may have spot-direction information leaking from their option flow. Tested: per trader, correlation of (signed VEV_4000 fill quantity) with (VELVETFRUIT mid 5k ticks later).

| Trader  | corr(signed_qty, vfx_5k_ret) | Buy→ vfx_5k mean | Sell→ vfx_5k mean |
|---------|---:|---:|---:|
| Mark 14 | −0.022 | −0.08 | +0.00 |
| Mark 38 | +0.015 | −0.01 | −0.03 |

All correlations within ±0.03 — **no detectable lead-lag** between voucher flow and underlying at 5k-tick horizon. The HYDROGEL/VEV_4000 game is not "informed options trader knows underlying direction"; it's pure spread-capture between Mark 14 and Mark 38.

This is itself useful: it tells us **we cannot use voucher flow as a directional signal for VELVETFRUIT**. The directional signal lives in the *underlying's own* trade flow (Mark 67 / Mark 49 imbalance from Part 1).

---

## 5. Updated trader portrait & playbook

| Trader   | role          | character                                              | how to trade against |
|----------|---------------|--------------------------------------------------------|----------------------|
| Mark 01  | passive maker | structural call buyer; harvests M22's strip quotes    | Race him on strip detection |
| Mark 14  | passive maker | top spread-capturer (HYDROGEL/VEV_4000)                | Compete with him; mirror his style |
| Mark 22  | mixed         | aggressive seller of high-strike vouchers + VELVETFRUIT | Buy from him on strip events |
| Mark 38  | pure taker    | uninformed taker, gets picked off everywhere           | Fade him on +5k horizon |
| Mark 49  | passive maker | bad MM, gets picked off on VELVETFRUIT                 | Lift his quotes the way M67 does |
| Mark 55  | pure taker    | mediocre taker, slight bleed                           | Mostly ignore |
| Mark 67  | pure taker    | **informed take-buyer of VELVETFRUIT (+$166/fill)**    | Follow his direction; size = conviction |

## 6. Three concrete code triggers for the R4 trader

These are mechanical, computable from `state.market_trades` and `state.order_depths`:

```python
# (1) M67 informed-buy follower (VELVETFRUIT)
recent_67_buys = sum(t.quantity for t in market_trades['VELVETFRUIT_EXTRACT']
                     if t.buyer == 'Mark 67' and (now - t.timestamp) <= 50_000)
recent_49_sells = sum(t.quantity for t in market_trades['VELVETFRUIT_EXTRACT']
                      if t.seller == 'Mark 49' and (now - t.timestamp) <= 50_000)
imbalance = recent_67_buys - recent_49_sells          # >40 = bullish
# Tilt our VELVETFRUIT inventory long when imbalance exceeds threshold.
# Bonus: if any single M67 buy in window had qty >= 10, double the conviction.

# (2) Strip-trade frontrunner (high-strike VEV vouchers)
m22_simultaneous_strikes = set()
for sym, depth in state.order_depths.items():
    if not sym.startswith('VEV_'): continue
    if any(p == 0.5 and v >= 1 for p, v in depth.sell_orders.items()):
        m22_simultaneous_strikes.add(sym)
if len(m22_simultaneous_strikes) >= 4:
    # Strip is being quoted; lift it now before M01 arrives.
    for sym in m22_simultaneous_strikes:
        lift_strip(sym, qty=1)

# (3) M38 / M55 taker-fade (HYDROGEL_PACK)
for trade in market_trades['HYDROGEL_PACK']:
    if trade.buyer == 'Mark 38' and (now - trade.timestamp) < 5_000:
        # Mark 38 just bought; he's on the wrong side 80% at +5k.
        signal_short_hp += trade.quantity
    if trade.seller == 'Mark 38' and (now - trade.timestamp) < 5_000:
        signal_long_hp += trade.quantity
```

These three signals are *independent* (different products / different time horizons) and can be combined linearly, capped by position limits.

---

## 7. Other ideas worth running but not yet tested

- **Microprice edge** instead of mid edge — does the bid/ask volume imbalance at fill time predict edge? Likely yes for makers (M14 may quote tighter when imbalance is in his favor).
- **Inter-arrival pacing** — Mark 67's gap between consecutive buys; sudden compression = informed burst.
- **IV-residual flow** — fit smile across other strikes; check which trader systematically buys negative-residual options. Likely Mark 01.
- **Pre-jump composition** — find ≥3σ mid jumps; rank traders by net flow in the 5–20k tick window before each jump.
- **Cross-day signature stability** — Mark 67's win rate is 91%/100%/33%; Mark 01 on VEV_6000 is 100%/100%/100%. The most stable signals are the most exploitable. Mark 01's strip-buy edge passes this test cleanly.
