# How FH Followed Olivia — and how we adapt it to Mark 67

Reference: [FH_trader.py](../../../FH_trader.py) lines 51, 225–265, 335–405, 409–545.
Do not edit FH_trader.py — it's read-only reference material.

## 1. The core "check_for_informed" mechanism (FH lines 225–265)

FH's entire Olivia layer is just one method on the `ProductTrader` base class. Every per-product trader calls it at construction time:

```python
def check_for_informed(self):
    informed_bought_ts, informed_sold_ts = self.last_traderData.get(self.name, [None, None])
    trades = self.state.market_trades.get(self.name, []) + self.state.own_trades.get(self.name, [])
    for trade in trades:
        if trade.buyer  == 'Olivia': informed_bought_ts = trade.timestamp
        if trade.seller == 'Olivia': informed_sold_ts   = trade.timestamp
    self.new_trader_data[self.name] = [informed_bought_ts, informed_sold_ts]

    if informed_bought_ts is None and informed_sold_ts is None:    direction = NEUTRAL
    elif informed_bought_ts is None:                               direction = SHORT
    elif informed_sold_ts is None:                                 direction = LONG
    elif informed_sold_ts > informed_bought_ts:                    direction = SHORT
    elif informed_sold_ts < informed_bought_ts:                    direction = LONG
    else:                                                          direction = NEUTRAL
    return direction, informed_bought_ts, informed_sold_ts
```

Three things to copy verbatim:

1. **Persistence via `traderData`.** They JSON-encode `[bought_ts, sold_ts]` per symbol into `state.traderData` so the bias survives across timesteps. Without this you'd lose Olivia the moment the trade scrolls out of `market_trades`.
2. **Read both `market_trades` AND `own_trades`.** If WE happened to be the counterparty to Olivia's fill, the trade lives in `own_trades`, not `market_trades`. Missing this halves your detection rate.
3. **Direction = "most recent" wins.** When both have been seen, the later timestamp dictates direction. So Olivia flipping from buy → sell mid-day flips your bias.

## 2. Three downstream "how to act on it" patterns

FH applies the same `check_for_informed` output three different ways, depending on the product's character:

### Pattern A — KELP / `DynamicTrader` (lines 335–377): bias-quoting + reactive lift

Two layers stacked:

- **Reactive (recent ≤ 500 ts):** `if informed_bought_ts + 500 >= state.timestamp:` — Olivia just bought; immediately lift the *whole* ask wall (`bid_price = ask_wall`, `bid_volume = 40 - position`). Translation: "she's buying right now, we have ~5 ticks before the move; aggress."
- **Persistent skew (any time after seen):** outside the reactive window, just *bias* the regular MM logic. When SHORT bias, post a *more aggressive bid* (cheaper bid → less likely to get filled long); when LONG bias, post a *more aggressive ask*. Equivalent to "we're willing to be net long 40 if the world will sell to us."

This is the right pattern for **products you market-make**. We're not abandoning quoting — we're skewing it asymmetrically.

### Pattern B — SQUID_INK / `InkTrader` (lines 382–405): pure follow-to-limit

```python
expected_position = +position_limit if LONG else -position_limit if SHORT else 0
remaining = expected_position - current_position
if remaining > 0:  bid(ask_wall, remaining)   # walk the offer up to limit
elif remaining < 0: ask(bid_wall, -remaining) # walk the bid down to limit
```

No quoting at all — once Olivia's seen, slam to the position limit by *taking* the book. This is the "Olivia signal dominates everything" stance the writeup describes.

This is the right pattern for **products where we don't think we have edge ourselves, but Olivia clearly does**.

### Pattern C — Croissants / `EtfTrader` (lines 409–545): amplify through related products

The EtfTrader holds an `informed_constituent` (CROISSANTS) and `hedging_constituents` (JAMS, DJEMBES). When Olivia's CROISSANTS direction is LONG:
1. Push CROISSANTS to position limit using Pattern B.
2. *Shift the basket-spread thresholds* by `ETF_THR_INFORMED_ADJS = 90` so the ETF-arb logic biases toward also going long the baskets — this multiplies CROISSANTS exposure ~4× through basket constituent exposure.
3. Half-hedge the residual basket exposure with JAMS/DJEMBES (`ETF_HEDGE_FACTOR = 0.5`) — keep enough naked CROISSANTS exposure to capture the signal, hedge the rest.

This is the most ambitious pattern: **use Olivia's signal as a multiplier on a structural arb you were already running.**

## 3. Adapting to Mark 67 / R4

Critical differences from Olivia:

| Aspect              | Olivia (P3)                              | Mark 67 (R4)                                          |
|---------------------|-------------------------------------------|-------------------------------------------------------|
| Direction           | Both sides (buys lows, sells highs)       | **Only ever buys** (165 fills, 0 sells)               |
| Reliability         | Near-perfect timing                       | Wins 2/3 days, loses 1                                |
| Aggressor role      | Mostly active (per FH writeup)            | 99% taker (pays the spread)                          |
| Edge per fill       | Very high (writeup describes 40+ SeaShells) | +$166/fill                                          |
| Counter-signal      | None mentioned                            | Mark 49 (only-sells, mirror)                         |
| Size signal         | Not mentioned                             | His 10+ lot fills carry +$22/unit edge vs +$16 small |

So our adaptations:

### A. Modify `check_for_informed` to handle one-sided + counter-signal

```python
INFORMED_BUYER  = 'Mark 67'
COUNTER_SELLER  = 'Mark 49'

def check_for_informed(self):
    state_blob = self.last_traderData.get(self.name, [None, 0, None, 0])
    buyer_ts, buyer_qty_window, seller_ts, seller_qty_window = state_blob

    BIG_FILL = 10  # qty threshold for "high conviction"

    trades = (self.state.market_trades.get(self.name, [])
              + self.state.own_trades.get(self.name, []))
    for tr in trades:
        if tr.buyer  == INFORMED_BUYER:
            buyer_ts = tr.timestamp
            buyer_qty_window = max(buyer_qty_window, tr.quantity)
        if tr.seller == COUNTER_SELLER:
            seller_ts = tr.timestamp
            seller_qty_window = max(seller_qty_window, tr.quantity)

    self.new_trader_data[self.name] = [buyer_ts, buyer_qty_window, seller_ts, seller_qty_window]

    # Only-LONG bias possible; size scales conviction.
    if buyer_ts is not None:
        conviction = 2 if buyer_qty_window >= BIG_FILL else 1
        return LONG, conviction, buyer_ts, seller_ts
    if seller_ts is not None:
        # No M67 yet; M49 dumping = weak short bias
        return SHORT, 1, buyer_ts, seller_ts
    return NEUTRAL, 0, buyer_ts, seller_ts
```

Differences from FH:
- We never set bias from buyer/seller-recency comparison — Mark 67 never sells, so there's no flip.
- We track the *max* recent fill quantity as a conviction multiplier (FH didn't need this; Olivia was always all-in).
- Mark 49 sells contribute a **weaker** counter-bias; only fire SHORT when M67 hasn't been seen yet that day.

### B. Pattern selection for VELVETFRUIT_EXTRACT

Use **Pattern A (bias-quote + reactive)** rather than Pattern B (pure follow). Reasoning:
- M67's signal isn't perfect (1/3 days he's wrong), so going to position-limit on him is too aggressive.
- We have edge ourselves on VELVETFRUIT MM, since Mark 49's quotes leak edge — there's a market-making business worth keeping.

```python
class VelvetfruitTrader(ProductTrader):
    # ... base class setup ...
    LONG_TARGET_FRACTION = 0.5  # cap follow at ±100 of ±200 limit (vs FH's full 40/40 on KELP)

    def get_orders(self):
        direction, conviction, buyer_ts, seller_ts = self.check_for_informed()
        target_pos = direction * conviction * int(self.position_limit * self.LONG_TARGET_FRACTION / 2)
        # conviction 1 => target ±50, conviction 2 (big M67 fill) => target ±100

        # === Reactive lift (within 2000 ts of last M67 buy — wider than FH's 500 because R4 ticks every 100) ===
        if buyer_ts is not None and self.state.timestamp - buyer_ts <= 2000:
            shortfall = target_pos - self.initial_position
            if shortfall > 0 and self.ask_wall is not None:
                self.bid(self.ask_wall, shortfall)   # take the offer aggressively

        # === Persistent skewed quoting (always) ===
        # Standard MM around wall_mid, but bias quote prices toward the target side.
        bid_price = int(self.wall_mid - 1)
        ask_price = int(self.wall_mid + 1)
        if direction == LONG and self.initial_position < target_pos:
            ask_price = int(self.ask_wall)        # widen ask, prefer not to go shorter
            bid_price = int(self.wall_mid)        # tighten bid, willing to fill long
        elif direction == SHORT and self.initial_position > target_pos:
            bid_price = int(self.bid_wall)        # widen bid
            ask_price = int(self.wall_mid)

        self.bid(bid_price, self.max_allowed_buy_volume)
        self.ask(ask_price, self.max_allowed_sell_volume)

        return {self.name: self.orders}
```

### C. Pattern C analog — the strip-trade front-runner

Mark 01 ⇄ Mark 22 strip events (317 across 3 days, ~$3+/event base edge) are the closest R4 thing to the Croissants amplification trade. They aren't driven by an informed-trader signal at all — they're driven by detecting Mark 22's strip-quote in the order book. That's a **separate, parallel module**, not a downstream of `check_for_informed`.

```python
class StripFrontRunner:
    HIGH_STRIKES = ['VEV_5200', 'VEV_5300', 'VEV_5400', 'VEV_5500', 'VEV_6000', 'VEV_6500']
    STRIP_QUOTE_PRICES = {'VEV_6000': 0.5, 'VEV_6500': 0.5}  # Mark 22's signature pinned-OTM prices

    def detect_strip(self, state):
        # Heuristic: count strikes where Mark 22's signature appears (very low ask, small lot, multiple strikes)
        strip_strikes = []
        for sym in self.HIGH_STRIKES:
            depth = state.order_depths.get(sym)
            if not depth: continue
            for price, vol in depth.sell_orders.items():
                # Empirical M22 signature: ask is at his typical small-lot range
                if (1 <= abs(vol) <= 8) and (price <= self.fair_value_for(sym) * 0.9):
                    strip_strikes.append((sym, price, abs(vol)))
                    break
        return strip_strikes if len(strip_strikes) >= 4 else []

    def lift_strip(self, state, strip):
        out = {}
        for sym, price, vol in strip:
            out[sym] = [Order(sym, int(price), vol)]
        return out
```

Run this *before* the per-product traders each tick, since strip-lift orders take precedence (we want to beat Mark 01 to the bid).

## 4. Implementation tricks worth stealing from FH

These aren't about Olivia per se, but they're the load-bearing scaffolding:

1. **`max_allowed_buy_volume / max_allowed_sell_volume` decremented on every order** (lines 200–211). Prevents accidentally placing orders that would breach position limits when stacking multiple per-tick orders. We've already had `vev` traders mis-sized in R3; this pattern fixes it.
2. **Wall-mid as the reference price**, not best-bid/ask mid (lines 153–166). FH defines `bid_wall = min(buy_orders)` and `ask_wall = max(sell_orders)` — i.e., the *deepest* visible book level. Wall-mid filters out flickery 1-lot quotes from market makers; the FH writeup specifically says best-bid mid was noisy, wall-mid is the right reference. Already incorporated in our R3 EDA findings; reapply here.
3. **`expected_position` separate from `initial_position`** (line 118). Update `expected_position` when you pre-commit to a fill so the next decision in the same tick already accounts for the in-flight order. Critical for hedge legs.
4. **All-symbol JSON `traderData`** persists across timesteps. Use it for: M67 last-seen ts, M49 last-seen ts, M22 strip-quote prior detections, IV smile fits, anything else stateful.

## 5. Suggested first version (what to actually code next)

A. **`trader-r4-v1-velvetfruit-follow67.py`** — VELVETFRUIT-only, just the Mark 67 follower with the bias-quote + reactive-lift logic above. No options, no strip detector. Backtest across days 1/2/3.
   - Expected behaviour: ~$3-5k/day on days 1+2, possibly ~$0-(-2k) on day 3. So mean ~$2-3k/day, std ~$2k.
   - Sanity benchmark: Mark 67 himself made +9k / +22k / -3.5k. We won't capture all of his edge (we won't hit every fill), but ~30% capture would be ~$3-7k mean.

B. **`trader-r4-v1-strip-frontrun.py`** — high-strike VEV vouchers, strip-lift only. No correlation with A; can run side-by-side.
   - Expected behaviour: ~$1k-$3k / round (depending on how many strip events we beat M01 to).

C. **`trader-r4-v2-combined.py`** — A + B + the existing R3 HYDROGEL/VEV_4000 MM logic + standard delta-1 quoting on VELVETFRUIT (when M67 is silent).

Three independent edges; combine linearly.

## 6. Things FH did NOT have that we do

- **Counter-signal trader (Mark 49):** their detection was Olivia-only. We can fade Mark 49's stale quotes the way Mark 67 does — copy his playbook by hitting Mark 49's resting offers proactively, even before Mark 67 arrives.
- **Aggressor classification:** we know Mark 67 is a taker. So when our quote sits at the ask in `state.order_depths` and the next tick's `state.market_trades` shows Mark 67 lifted us, we have a clean signal that *we* were the one picked off — we should immediately *widen* further, not refresh at the same price.
- **Trade-size conviction:** FH's ±40 KELP target was static. Ours can be `target = base_target * (1 + 0.5 * sign(qty - 10))` — bigger M67 fills push us harder.

## 7. Things to verify before submitting

- `state.market_trades` in R4 actually populates `Trade.buyer` / `Trade.seller` with the "Mark XX" strings (we've confirmed this in `r4_datacap/trades_round_4_day_*.csv`; verifying it's the same on the live exchange is the first thing to check on round day).
- `traderData` survives between calls for our trader — sanity-print at session start.
- The `import os` ban from CLAUDE.md still applies; FH uses none either, so we're safe.

## 8. Amendments from Part 3 sophisticated probes

Source: [FINDINGS_PART3.md](FINDINGS_PART3.md). Three updates that change the implementation plan above.

### 8.1 Down-weight Mark 67 — the signal is NOT stationary

Cross-day stability ranking (`sophisticated2.py` #12) shows Mark 67's per-unit close-edge on VELVETFRUIT is **+$17 (day 1), +$38 (day 2), −$8 (day 3)**. The headline +$165/fill from Part 1 was day-1+2 dominated. A blind follower would have lost on day 3.

**Implication for the v1 follower (§5.A):**
- Drop `LONG_TARGET_FRACTION` from 0.5 to **0.25** (cap follow at ±50, not ±100).
- Add a **realised-edge gate**: track `cumulative_pnl_attributed_to_m67_signal` in `traderData`; if it goes negative by more than ~$2k, halve the target fraction further.
- Revised expected behaviour: $1-3k/day across 3 days, std ~$1.5k. (Worse than the original projection but more honest given day-3 risk.)

### 8.2 Add Mark 55 as a low-confidence VFX jump signal

Pre-jump trader composition (#11) shows Mark 55 was on the **correct side of 4 of 5** 3σ jump events on VELVETFRUIT, despite their overall bleed of −$2/unit on the same product. n=5 is small, but the pattern is striking.

**New addition to §3.A `check_for_informed`:**

```python
JUMP_FRONTRUNNER = 'Mark 55'
JUMP_QTY_THRESHOLD = 10  # M55's "conviction" trades

# Inside check_for_informed loop:
for tr in trades:
    # ... existing M67/M49 logic ...
    if (tr.buyer == JUMP_FRONTRUNNER and tr.quantity >= JUMP_QTY_THRESHOLD):
        m55_long_ts, m55_long_qty = tr.timestamp, tr.quantity
    if (tr.seller == JUMP_FRONTRUNNER and tr.quantity >= JUMP_QTY_THRESHOLD):
        m55_short_ts, m55_short_qty = tr.timestamp, tr.quantity

# After M67/M49 logic resolves direction, only OVERLAY M55 if NEUTRAL:
# (don't let M55 contradict a fresh M67 signal)
if direction == NEUTRAL:
    if m55_long_ts is not None and (state.timestamp - m55_long_ts) < 3000:
        return LONG, conviction=1, ...
    if m55_short_ts is not None and (state.timestamp - m55_short_ts) < 3000:
        return SHORT, conviction=1, ...
```

Tiny target (conviction 1, ±25 position), short reactive window (3000 ts), big-fill gate. This is opportunistic rather than strategic.

### 8.3 Strip-front-runner — DOWNGRADED after looking at the actual book

Original §3.C / §5.B implementation plan assumed Mark 22 was posting **asks** below fair value that we could lift before Mark 01. Verified against the price snapshots: the actual mechanic is:

- VEV_6000 / VEV_6500 book consistently shows **bid at price 0** (volume ~14-30) and **ask at price 1** (volume ~18-30); mid is 0.5
- Every strip trade prints at price = **0** (n=634 across 3 days, all of them)
- Mark 22 is the aggressor (hits Mark 01's resting bid); Mark 01 is the resting maker at 0
- Position end-of-round liquidation value appears to be ~0.5 (matches `day_close`), so buying at 0 = +0.5/unit

This means the play is NOT to lift an ask — it's to be the **resting bid at price 0** before Mark 22 dumps. But Mark 01's 14-30 lots sit in front of us in the price-time queue, and Mark 22 only dumps 2-5 lots per trade. We almost never get past Mark 01.

**Revised strip module — "passive 0-bid":**
- Post bid at price 0 with full position-limit size (300) on both VEV_6000 and VEV_6500
- Risk-free: a fill at 0 is +0.5/unit at liquidation; cost of resting is zero
- Expected fills: rare; bounded by residual flow after Mark 01. Probably 0-20 lots/day total. Capped upside ~$10/day across both strikes
- Still worth coding because it's literally 6 lines of code and decoupled from everything else

**Strip-frontrun is not actually the cleanest play after this verification.** It stays in v1 (because it's free) but is no longer the priority module.

### 8.4 Drop microprice and pacing from feature pipeline

Probes #3 (microprice edge) and #10 (Mark 67 inter-arrival pacing) both produced negative results (≤$0.4/fill differences and flat across pacing buckets). **Don't add either as features.** Mid-based forward edge is sufficient for any per-trader signal scoring.

### 8.5 Updated v1 trader priority order

Was (§5): A=follow67 → B=strip → C=combined. Pre-verification I'd promoted B to first; post-verification (§8.3) the strip is mostly cosmetic.

**Final order:**
1. **A: trader-r4-v1-velvetfruit-follow67.py** — Mark 67 follower with §8.1 down-weighting and §8.2 Mark 55 overlay. Primary edge.
2. **B: passive 0-bid module** — fold into A as a side-leg (bid 0 size 300 on VEV_6000/6500). 6 lines. No separate file.
3. **C: combined trader** — adds HYDROGEL/VEV_4000 MM logic from R3 work + delta-1 quoting on VFX when M67 silent.
