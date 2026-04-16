# Round 1 Product Mechanics Reference

**Version:** 2026-04-16 (rev 2 — adds Round 1 objective, Exchange Auction, product lore now that Trading-groundwork HTML is readable)
**Scope:** Rules-derived mechanics only. No empirical numbers from backtests or data analysis appear here.
**Audience:** Strategy team — assumes familiarity with order-book trading concepts but not with IMC-specific rules.

---

## Sources

| File | Used for |
|------|----------|
| `Writing an Algorithm in Python.html` | Engine mechanics: position limits, order execution, conversion API, iteration structure |
| `R1_Trading groundwork.html` | Round-specific rules: profit objective, two algorithmic products + lore hints, Exchange Auction mechanics (DRYLAND_FLAX, EMBER_MUSHROOM). Originally blocked by Unicode curly-quote filename; renamed with ASCII quotes to enable reading. |
| `images/osmium.png` | Visual order-book regime for ASH_COATED_OSMIUM |
| `images/pepper_root.png` | Visual order-book regime for INTARIAN_PEPPER_ROOT |
| `images/bid_ask_round1.png` | Best bid/ask overlay across all three days, both products |
| `images/bid_ask_round1_zoomed.png` | Per-day bid/ask detail, both products |
| `images/ipr_mid_price_by_day.png` | IPR mid-price per day with empty-book events visible |
| `Round 1/r1_data_capsule/prices_round_1_day_-2.csv` | Price/volume format inspection for tick-size and depth confirmation |
| `Round 1/analysis/pepper_root_findings.md` | Context only — empirical numbers deliberately excluded from this document |

---

## Conventions

- **Prices** are denominated in **XIRECS** (the in-game currency).
- **Position** is a signed integer: positive = long (holding units), negative = short (owed units). Zero = flat.
- **Position limit L** means position must remain in the closed interval **[−L, +L]**.
- **Tick size** = minimum price increment. Observed from price data: all quoted prices are whole integers, so tick size = 1 XIREC.
- **Timestamp** advances in steps of 100 per iteration; one full day spans roughly 0 to 999,900 (10,000 iterations).
- **ACO** = ASH_COATED_OSMIUM. **IPR** = INTARIAN_PEPPER_ROOT.
- **Order book depth** in the `OrderDepth` object: unbounded Python dict (no structural cap). The historical CSV export shows up to 3 price levels per side, but the live engine may expose more or fewer.
- **"Iteration"** = one call to `Trader.run()`. All orders from a single iteration are processed atomically before the next iteration begins.

---

## Round 1 Objective (Rules-Stated)

- **Cumulative profit target:** at least **200,000 XIRECs** before the start of the third trading day. This is the round's pass/fail threshold as stated in the Trading-groundwork page.
- Lore framing: each Intarian trading day lasts 72 hours (in simulation, one day = ~10,000 iterations, timestamp 0 to ~999,900).
- Round 1 contains two components:
  1. **Algorithmic trading challenge ("First Intarian Goods")** — Python algo trading `ASH_COATED_OSMIUM` and `INTARIAN_PEPPER_ROOT` in continuous book-based markets.
  2. **Manual trading challenge ("An Intarian Welcome")** — a one-off Exchange Auction on two separate products (`DRYLAND_FLAX`, `EMBER_MUSHROOM`) that are **not** traded in continuous markets. See dedicated section below.
- The rules do not specify whether algorithmic PnL and auction PnL are pooled toward the 200k threshold or tracked separately — flagged in the Exchange Auction Open Questions below.

---

## Engine-Level Rules (apply to both products)

### Order Submission

- Each iteration, `run()` returns a dict mapping product names to lists of `Order` objects.
- An `Order` has three fields: `symbol` (str), `price` (int), `quantity` (int).
- Positive `quantity` = buy order. Negative `quantity` = sell order.
- `price` on a buy order is the maximum price the algorithm is willing to pay; on a sell order it is the minimum price the algorithm will accept.

### Order Matching and Execution

- Orders that cross with existing bot quotes execute immediately at the bot's quoted price, not at the algorithm's limit price. The engine processes all levels greedily from best price inward.
- Any unmatched remainder of the algorithm's order sits as a passive resting quote visible to bots for the remainder of that iteration.
- If no bot fills the resting quote during that iteration, it is cancelled automatically before the next `TradingState` arrives.
- Bots may also trade with each other after the algorithm's orders are processed and before the next iteration.

### Position Limit Enforcement

- Position limits are **enforced on submitted order aggregates, not on fills.** If the sum of all buy (sell) orders submitted in one iteration would, if fully filled, push the position past the long (short) limit, the **entire set of buy (sell) orders for that product is rejected** — even if only some orders would have crossed the limit.
- This means sending orders totaling more than `limit − current_position` on the buy side causes all buys to be dropped, not just the excess.
- Limit is absolute and symmetric: the same numeric limit applies to both long and short sides.

### Conversion Mechanism

- The engine supports an optional `conversions` integer returned from `run()`. A positive conversion request reduces a short position; a negative request reduces a long position.
- Conversion requires a prior non-zero position in the product.
- Conversion amount cannot exceed the absolute position size (e.g., from position −10, only 1 through 10 is valid; requesting 11 or more causes the entire conversion to be ignored).
- Conversion costs are applied: transport fees plus an import or export tariff, depending on direction. These costs are product-specific and are provided each iteration via the `ConversionObservation` fields: `bidPrice`, `askPrice`, `transportFees`, `exportTariff`, `importTariff`.
- **Ambiguity:** Whether any Round 1 product (ACO or IPR) has a `ConversionObservation` populated in practice is unconfirmed from the rules page alone — see Open Questions under each product.

### State Persistence

- Global and class variables are not guaranteed to persist between iterations (AWS Lambda stateless model).
- The string field `traderData` (returned from `run()` and passed back in the next `TradingState`) is the only guaranteed persistence mechanism.
- `traderData` is truncated to 50,000 characters by the engine; exceeding this limit corrupts the state.

### Timing

- Hard timeout per iteration: 900 ms. Expected average budget: ≤ 100 ms.
- Submissions that time out lose that iteration's orders entirely.

---

## ASH_COATED_OSMIUM (ACO)

### Position Limit

- **80** (absolute, both sides). Confirmed from IMC documentation per the team's cross-check against the rules wiki. Rule basis: position limits are listed per-round per-product on the Prosperity wiki "Rounds" section.

### Tick Size

- **1 XIREC** (integer prices only). Confirmed by inspection of the prices CSV: all bid, ask, and mid values are whole numbers.

### Order-Book Depth

- The prices CSV exposes up to **3 levels per side** (`bid_price_1/2/3`, `ask_price_1/2/3`). The `OrderDepth` object delivered at runtime is a dict and may contain more levels; the 3-level cap is a property of the historical data export format, not necessarily a guarantee of live book depth.
- Visually (from `osmium.png` and `bid_ask_round1.png`): the spread is consistently narrow and bid/ask move together, suggesting a liquid, closely quoted book.

### Fee / Tariff / Conversion Mechanics

- No conversion mechanism has been identified for ACO from the available rules sources.
- Currency for all trades is XIRECS; buyer/seller identity is anonymized in the trade log.
- No explicit transaction fee or per-trade tariff is described for ACO in the algo-trading primer.

### Fair-Value Anchors (Rules-Derived)

- The rules do not specify an explicit fair-value formula or reference price for ACO.
- **Lore hint (Trading-groundwork page):** ACO is described as relatively volatile, but its apparent unpredictability is suggested to possibly follow a hidden pattern. This is a narrative hint, not a stated formula — but it signals that the design intent is for a discoverable signal (regime, cycle, cross-product relationship, or observation-driven driver) to exist. Treat as a strategy prompt, not a proof.
- The price charts (`osmium.png`, `bid_ask_round1.png`) show ACO oscillating within a bounded range across all three days, consistent with a mean-reverting or range-bounded product. This is a chart-level observation, not a rules statement.
- No fundamental anchor (e.g., a peg to an external index or observable) is described in the available rules text.

### Asymmetric-Information / Insider Mechanic

- None explicitly named for ACO in the Trading-groundwork page.
- The "hidden pattern" phrasing in the lore hint (see Fair-Value Anchors) is the closest thing to an asymmetric-information hint — it implies an exploitable regularity rather than a privileged-counterparty signal.
- The general IMC framework notes that some products may have observable signals (via `plainValueObservations` or `ConversionObservation` in the `Observation` object), but no such signal is confirmed for ACO from the Round 1 rules page.

### Open Questions — ACO

1. **Is a `ConversionObservation` populated for ACO?** ~~The primer describes conversion mechanics generically. If ACO has a populated `ConversionObservation`, there may be a cross-venue arbitrage or hedging mechanism not captured here.~~ **RESOLVED BY HTML re-read (2026-04-16):** `R1_Trading groundwork.html` contains zero mentions of the word "conversion". The Python primer also says "we expect you won't really need to work much with [the Observation] class (feel free to skip)." Round 1 has no conversion mechanic for ACO. Confirm defensively in live TradingState by checking `state.observations.conversionObservations.get("ASH_COATED_OSMIUM")` is `None`.
2. **What is the structure of ACO's "hidden pattern"?** The Trading-groundwork page now confirms a pattern is hinted at but does not describe its shape. Candidate hypotheses worth testing against data: (a) time-of-day cycle within a single 10k-iteration day; (b) day-of-round drift (similar to how IPR's growth varies); (c) cross-product relationship with IPR; (d) dependence on a field inside `Observation` (plain-value observation or conversion-style input). **RESOLVED BY EDA (r1_eda.ipynb Cell 11):** bounded oscillation with half-period ~1000–2000 timesteps (lag-2000 autocorr = −0.340).
3. **Are there any bot-specific quoting rules for ACO?** ~~The engine primer says bots quote in `order_depths` but does not describe how individual bots behave or whether their quoting is tied to observable market conditions.~~ **RESOLVED by user (2026-04-16):** no product in any round has explicit bot-specific quoting rules published. The provided price/trade data is the training set from which to infer patterns; live submission runs against analogous but unseen bot behavior. Strategy correctly relies on the adverse-volume filter (≥15 units) as its bot-identification proxy.
4. **Is the 3-level order-book depth in the CSV a hard cap or an artifact of the data export?** If bots can quote beyond 3 levels, strategies that assume only 3 levels of depth may miss liquidity. **RESOLVED BY EDA (r1_eda.ipynb Cell 5):** L3 quoted only ~2.6% of the time; effectively 1–2 levels in practice.
5. **Is PnL marked to IMC's internal fair value or to mid-price?** The `profit_and_loss` column exists in the prices CSV but its marking convention (mid, last trade, IMC's own formula) is not stated in the algo-trading primer. **RESOLVED BY PLAN.md Pass 3:** local backtester uses mark-to-mid (backtest.py lines 239-247); accept any discrepancy vs IMC's internal marking as acceptable per CLAUDE.md Hard Rule 4.

---

## INTARIAN_PEPPER_ROOT (IPR)

### Position Limit

- **80** (absolute, both sides). Same rule basis as ACO: position limits listed per-round per-product on the Prosperity wiki. Team has separately cross-checked this against the IMC docs.

### Tick Size

- **1 XIREC** (integer prices only). Confirmed from the prices CSV: all IPR bid and ask prices are whole integers.

### Order-Book Depth

- Same structural observation as ACO: the prices CSV shows up to **3 levels per side**. Whether this is a hard engine constraint or a data-export artifact is unconfirmed.
- Visually (from `pepper_root.png`, `bid_ask_round1.png`, `bid_ask_round1_zoomed.png`): the bid and ask lines track extremely closely, nearly parallel to the trend line, suggesting the spread is consistently narrow even while the price drifts substantially upward. One-sided book events (either bid or ask completely absent) are visible as discrete spikes in `ipr_mid_price_by_day.png`.

### Fee / Tariff / Conversion Mechanics

- No conversion mechanism has been identified for IPR from the available rules sources. The `ConversionObservation` fields (bidPrice, askPrice, transportFees, exportTariff, importTariff) do not appear in any IPR-specific rules text in the available HTML.
- Currency for all trades: XIRECS. Buyer/seller identity is anonymized.
- No per-trade transaction fee is described for IPR.

### Fair-Value Anchors (Rules-Derived)

- The rules do not specify a numeric formula or external reference anchoring IPR's price.
- **Lore hint (Trading-groundwork page):** IPR is described as steady in value but also as a hardy, slow-growing root, and is cross-referenced to the tutorial round's EMERALDS product as a comparable "steady" archetype. The narrative pairing of "steady" with "slow-growing" is best read as **low-volatility persistent growth** — a deterministic upward drift with tight noise rather than a flat price. This is the rules-level basis for the observed directional drift.
- **Contradiction to flag:** A naive reading of "steady" alone could suggest a flat mean-reverting product (like Rainforest Resin from IMC3 R1). The chart data rules this out — IPR drifts strongly upward on every sample day. The reconciliation ("steady" = low-volatility, "slow-growing root" = directional drift) depends on reading both adjectives together. A strategy that treats IPR as purely mean-reverting because of the word "steady" would be wrong.
- The price charts show IPR with a persistent upward trend across all three sample days, starting from a different absolute level on each day (the product carries over between days rather than resetting). This is a visual observation from the charts, consistent with the "slow-growing" lore framing.
- No numeric fundamental driver (e.g., a harvest index or external peg) is provided in the rules text — only the biological / narrative framing.

### Asymmetric-Information / Insider Mechanic

- None explicitly named for IPR in the Trading-groundwork page.
- The "hardy, slow-growing" framing is a lore-level description, not a privileged-information mechanic. The page does not reference an insider, counterparty tell, or observation-based signal for IPR specifically.

### Open Questions — IPR

1. **Is the growth rate constant, or does it vary by day / round / hidden state?** The Trading-groundwork page provides the narrative explanation for the drift ("hardy, slow-growing") but no rate formula. Whether the per-iteration growth is fixed, seasonal, dependent on an observation field, or tied to day number is unspecified. **RESOLVED BY EDA (r1_eda.ipynb Cells 9 + 10):** mean drift 0.1077–0.1096 XIRECS/tick uniform across all 4 intraday quartiles and all 3 days; per-day totals 1003.0 / 999.5 / 1001.5 XIRECS (std 1.8). Rate is constant within and nearly constant across observed days.
2. **Does IPR carry its position and price across days, or does the engine reset position to zero at day boundaries?** ~~The price charts show each day starting at a different price level (not at a common baseline), which suggests price carries over. Whether position also carries over is not stated in the algo-trading primer.~~ **RESOLVED by user (2026-04-16):** the three days are effectively continuous — treat as a single connected data set for strategy design and backtesting purposes. Price carries (confirmed: day -2 ends at 11001.5, day -1 starts at 10998.5). Position-reset behavior at engine boundary remains the v9 trader's implicit assumption (re-buys 80 at each day start) and is consistent with IMC's standard per-day submission model.
3. **Is a `ConversionObservation` populated for IPR?** ~~If so, there may be a conversion or hedging mechanism (possibly into another product or venue) that the current strategy ignores.~~ **RESOLVED BY HTML re-read (2026-04-16):** same as ACO-1 — `R1_Trading groundwork.html` has zero mentions of "conversion". Round 1 has no conversion mechanic for IPR.
4. **Do one-sided book events (empty bid or ask side) represent a rules-defined state or a transient artifact?** The primer says bot orders are cancelled at end of iteration if unmatched, so empty-book moments may be genuine market-maker absences. The rules do not describe any guaranteed minimum liquidity. **RESOLVED BY EDA (r1_eda.ipynb Cell 5):** L1 = 100% after cleaning; one-sided events are genuine market-maker absences. v9 trader guards via `if not depth.buy_orders or not depth.sell_orders: continue`.
5. **Does the "slow-growing" framing imply the trend never reverses, or is there a harvest / maturity event that resets or inverts it?** The lore language is unidirectional ("growing"), but no explicit rule forbids a regime change — e.g., a mid-round event or cross-round reset. The current rules text does not settle this. **Still open — HIGH RISK** (user confirmed 2026-04-16: only 3 days of data available; no additional context. Primary strategy can assume drift continues; defensive infrastructure required in case of change). Primary mitigation: drift-reversal circuit breaker in PLAN.md §IPR (d) (W=500, k=5.0, freeze target at 0).
6. **Can an algorithm go short IPR, and if so, is there any borrowing cost?** ~~The engine permits short positions generically (down to −80), but whether a persistent short in a trending-up product incurs any additional cost or mechanic is unspecified.~~ **RESOLVED BY HTML re-read (2026-04-16):** neither HTML contains the words "borrow", "short sell", "shorting", "funding", "margin", "interest", or "carry". No explicit shorting cost exists by rule; only engine constraint is `position ∈ [−80, +80]`. The long-only floor in PLAN.md §IPR (c) is a strategic choice under the drift thesis, not a compliance requirement.

---

## Cross-Product Notes

- Both products share the same simulation infrastructure: same iteration cadence (timestamp step 100), same timeout budget, same position-limit enforcement rules.
- The engine processes both products within a single `run()` call; there is no guaranteed ordering between how ACO and IPR orders are matched.
- There is no cross-product margin, netting, or correlation mechanic described in the available sources.
- The `plainValueObservations` field of the `Observation` object could carry round-specific signals for either product; its content for Round 1 is not described in the available docs.
