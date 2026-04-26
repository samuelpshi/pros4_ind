# trader-r3-v1-hydrogel.py — interface audit vs R1 references

Reviewer: agent (no code modified)
Target file: `R3/traders/trader-r3-v1-hydrogel.py` (171 lines)
References:
- `R1/archive/traders/trader-v9-r1-aco-only.py` (v9 ACO mean-reverting MM, IMC-submitted)
- `R1/traders/trader-v8-173159.py` (v8 ACO MM, IMC-submitted)
- `R1/traders/trader1.py` (R1 baseline ACO MM)
- Canonical `datamodel.py` extracted from `~/prosperity_rust_backtester/src/pytrader.rs:225–345`
  (single source of truth — embedded by the rust runner and matches the IMC sandbox class
  layout)

---

## Executive summary

**Six interface checks: 5 PASS, 1 PARTIAL.** No outright contract bugs; the trader
constructs `Order`, returns the 3-tuple, parses sell-volume signs, persists `traderData`,
and reads `state.position` correctly.

The PARTIAL is **Check 6** (position-limit enforcement): the trader sizes the passive
make leg against a *projected* post-take position rather than start-of-tick position. When
near the limit on one side AND the take layer fires on the opposite side, the engine
will see a per-side order sum that exceeds `limit ∓ pos` and may reject the make leg.
This pattern is *also present* in R1 v9 / v8 ACO so it is not novel to r3-v1; but
HYDROGEL's fill profile (5.8× IMC vs local) makes it more likely to surface here than it
ever did in R1.

Beyond the six checks, two **strategic gaps** stand out as more likely root causes for
the observed ±200 pinning on IMC than any interface bug:

- **B1 (HIGH).** No "clear layer" and no asymmetric take threshold. Both R1 references
  unwind aggressively at exactly `fv` when pinned (v8 via asymmetric-threshold take,
  v9 via a dedicated `aco_clear` layer at `fv ± 0`). r3-v1 has neither. Once pinned,
  the only unwind mechanism is the modest 1-tick make-side skew.
- **B2 (HIGH).** Skew strength of 1.0 against a quote_offset of 3 is geometrically too
  weak to escape the limit: at full long, the ask shifts only from `fv+3` to `fv+2`.
  Combined with B1, position pinning is structurally self-reinforcing.

Total findings: **1 contract issue (Check 6, low–medium severity)** + **2 strategic
gaps** (more likely culprits for the IMC pinning). Detail below.

---

## Per-check findings

### Check 1 — `Trader.run` signature and return — **PASS**

(a) Reference (datamodel + R1 v9): returns `(orders_dict, conversions_int, traderData_str)`.
(b) r3-v1 line 170: `return result, 0, json.dumps(saved)` — 3-tuple, dict, int, str. ✓
(c) Match.
(d) n/a.

The rust backtester's `_normalize_run_output` (`pytrader.rs:174`) accepts 1-, 2-, or
3-tuples and coerces traderData to `str(...)`, so the rust local would tolerate
mistakes here. The IMC sandbox is stricter; r3-v1 already returns the canonical
3-tuple of correct types.

### Check 2 — `Order` construction and sign convention — **PASS**

(a) `Order(symbol, price: int, quantity: int)`; positive quantity = buy, negative =
    sell. Confirmed in `datamodel.py:277-281` and uniformly across R1 references
    (v9 line 105 `Order(symbol, ap, qty)` for buys, line 116 `Order(symbol, bp, -qty)`
    for sells).
(b) r3-v1:
    - take-buy at line 123: `orders.append(Order(PRODUCT, ap, qty))`, qty > 0. ✓
    - take-sell at line 138: `orders.append(Order(PRODUCT, bp, -qty))`, qty > 0 then
      negated. ✓
    - make-bid at line 164: `Order(PRODUCT, bid_px, bid_size)`, bid_size > 0. ✓
    - make-ask at line 166: `Order(PRODUCT, ask_px, -ask_size)`, ask_size > 0 negated. ✓
(c) All four order constructions use the correct sign.
(d) n/a.

### Check 3 — Position read — **PASS**

(a) `state.position.get(SYMBOL, 0)` returns start-of-tick position (after the previous
    tick's fills, before this tick's submitted orders). R1 v9 line ≈ uses the same
    pattern.
(b) r3-v1 line 109: `pos = state.position.get(PRODUCT, 0)`. Read once. ✓
(c) Match.
(d) n/a — the trader does not maintain a parallel position counter that could drift.

Note: r3-v1 computes `proj_pos = pos + take_buy_used - take_sell_used` (line 146),
but uses `proj_pos` only for sizing/skew of the make leg, not as a substitute for
`state.position`. That use of projected position is the subject of Check 6 below.

### Check 4 — `traderData` round-trip — **PASS**

(a) Reference: serialize/deserialize via the same library, store all stateful values
    inside the persisted blob (R1 uses jsonpickle; standard json works equally well
    on the IMC sandbox for primitives).
(b) r3-v1:
    - Line 83: `saved = json.loads(state.traderData) if state.traderData else {}`.
    - Line 88: on parse failure, `saved = {"_traderData_error": repr(e)}` (then
      proceeds with empty state — the documented intent under Hard Rule #7).
    - Line 89: `ema = saved.get("ema_fv")`.
    - Line 169 / 97: `saved["ema_fv"] = ema; return ..., json.dumps(saved)`.
    - All persisted state is in `saved`, not in `self.*`. ✓ — important because IMC
      may instantiate a fresh `Trader()` between ticks; `self.*` would not survive.
(c) Match.
(d) n/a.

Minor observation (not a bug): `_traderData_error` once set on a parse failure will
persist forever in subsequent `saved` blobs. Harmless but noisy if it ever fires.

### Check 5 — Order-book access and sign — **PASS**

(a) Reference + datamodel + rust runner: `buy_orders` values are POSITIVE volumes;
    `sell_orders` values are NEGATIVE volumes (rust runner explicitly negates ask
    volumes at `pytrader.rs:517`). Best bid = `max(buy_orders)`, best ask =
    `min(sell_orders)`.
(b) r3-v1:
    - Line 100: `best_bid = max(depth.buy_orders)`. ✓
    - Line 101: `best_ask = min(depth.sell_orders)`. ✓
    - Line 102: `mid = 0.5 * (best_bid + best_ask)`. ✓
    - Line 119: `available = -depth.sell_orders[ap]  # sell_orders volumes are negative`. ✓
    - Line 134: `available = depth.buy_orders[bp]` (already positive). ✓
(c) Match. The trader correctly handles the bid-positive / ask-negative convention
    at every read site.
(d) n/a.

### Check 6 — Position-limit enforcement — **PARTIAL** *(top suspect per the task brief)*

(a) Reference invariant from `R1/archive/traders/trader-v9-r1-aco-only.py:347–375`
    (`_capped_buy` / `_capped_sell` helpers): the per-tick budget for each side is
    measured against **start-of-tick** `current_pos` plus the **already-submitted
    same-side volume in the orders list**:

    ```python
    remaining_budget = limit - current_pos - existing_buy_vol   # buy side
    remaining_budget = limit + current_pos - existing_sell_vol  # sell side
    ```

    NB: the v9 ACO branch itself does NOT actually call these helpers (lines
    591–593 use the projected-position pattern); the helpers are only wired into
    the IPR branch. So R1 ACO and r3-v1 share the same shortcut.

(b) r3-v1 sizes the make leg against PROJECTED post-take position
    (lines 146–148):

    ```python
    proj_pos          = pos + take_buy_used - take_sell_used
    room_buy_passive  = limit - proj_pos
    room_sell_passive = limit + proj_pos
    ...
    bid_size = min(passive_size, room_buy_passive)
    ask_size = min(passive_size, room_sell_passive)
    ```

    Algebraically:

    ```
    sum(buys submitted)  = take_buy_used + bid_size
                         ≤ take_buy_used + (limit - pos - take_buy_used + take_sell_used)
                         = limit - pos + take_sell_used

    sum(sells submitted) ≤ limit + pos + take_buy_used
    ```

    So when **start-of-tick `pos` is near +limit AND `take_sell_used > 0`**, the
    submitted **buy** total can exceed the engine's `limit - pos` budget. Symmetrically
    on the short side.

(c) Mismatch *under the specific co-fire condition*. Same-side-only ticks (the common
    case for HYDROGEL with its 16-wide spread and `take_edge = 4`) are not affected —
    if `take_sell_used = 0` then sum(buys) ≤ `limit - pos` exactly.

(d) Failure mode at runtime: when pinned at e.g. `pos = +195` and bids exist at
    `≥ fv + 4`, the take_sell loop can fire (up to `take_cap = 50`), then the make
    leg posts a 30-unit bid at `fv − 4` (because `room_buy_passive = take_sell_used`).
    The IMC engine sees `pos + sum(buys) = 195 + 30 = 225 > 200` and either rejects
    the bid order or trims it. This is consistent with the IMC log's reported
    `position_limit_rejections = 19` over the D2 window where local reports 0 (the
    local rust backtester does not enforce per-side rejection in this manner; see
    `imc_vs_local_divergence.md`).

    Severity: **low–medium**. 19 rejections over 10000 ticks is small; it explains
    the *existence* of rejections in the IMC log but not the *bulk* of the divergence
    or the pinning behavior. The strategic gaps below are more likely.

---

## Step 3 — broader scan beyond the six checks

### B1 (HIGH severity, strategic) — No clear layer and no asymmetric take threshold

R1 v8 (`trader-v8-173159.py:117, 124`) uses **asymmetric take thresholds** that relax
to `fv` (no edge) when on the unwind side:

```python
threshold = fv - edge if pos >= 0 else fv   # relax buy-threshold when short
threshold = fv + edge if pos <= 0 else fv   # relax sell-threshold when long
```

R1 v9 (`trader-v9-r1-aco-only.py:274–298`) instead uses a **dedicated `aco_clear`
layer** that fires at exactly `fv ± clear_width` (with `clear_width = 0`) whenever
`pos != 0`. This sits between take and make, and is invoked at line 592.

r3-v1 has **neither**. The take loop in r3-v1 (lines 116–141) uses a fixed symmetric
`fv ± take_edge` threshold regardless of inventory. Once `pos` is pinned at +limit,
the only sell-side action available is:

1. take_sell, only if `bid ≥ fv + 4` (rare on HYDROGEL_PACK)
2. the make ask at `fv + 2` (after 1-tick skew on the +1.0 max-skew strength)

Neither is sufficient to escape the limit promptly.

Failure mode: positions accumulate to ±limit and stay there for long stretches —
which is exactly the IMC behavior described in the task brief. R1 wouldn't have
exhibited the same because either the asymmetric take or the clear layer was
forcing intra-tick unwind.

### B2 (HIGH severity, strategic) — Skew strength geometrically dominated by quote_offset

Default config:
```
quote_offset  = 3
skew_strength = 1.0
```

At full long (`proj_pos = +limit`), `skew = +1.0`. The make-leg prices are:
- `bid_px = round(fv − 3 − 1) = fv − 4`
- `ask_px = round(fv + 3 − 1) = fv + 2`

So the ask, even at full inventory pinning, is still **2 ticks above fair value** —
deeply passive. With HYDROGEL_PACK's 16-wide spread, the wall sits at roughly
`fv ± 8`, so `fv + 2` is just 2 ticks inside the wall. There is no aggressive
"dump-the-inventory" quote.

Compare R1 v8 (line 138) which uses `max_skew = 5` (against `quote_offset = 2`),
*plus* a panic_extra term that adds another 0–3 ticks beyond the 75% threshold,
*plus* an "ignore-fv-side-guard" bypass at panic. Net effect: under pinning, v8
can quote at or even below `fv`. r3-v1 cannot.

Failure mode: same as B1 — inability to unwind a pinned position. B1 and B2
compound: the take won't sell at the unwind threshold, and the make ask is too
passive to attract a fill on the bid side.

### Other items examined — no findings

- **All trading-logic params come from CONFIG**, no magic numbers. ✓
- **EMA cold-start**: line 89 `ema = saved.get("ema_fv")` returns None on first tick
  → line 106 `ema = mid if ema is None else ...` → first-tick fv = mid. With
  `take_edge = 4` and 16-wide spread, no spurious takes fire. Sensible. ✓
- **Bid/ask cross guard** at line 158: `if ask_px <= bid_px: ask_px = bid_px + 1`.
  Only nudges ask. With current params (`quote_offset = 3`, `skew_strength = 1.0`)
  this guard cannot trigger; if `skew_strength` were tuned ≥ 6 it could. Minor and
  irrelevant at current defaults.
- **`saved` dict accumulates extra keys forever** (e.g. `_traderData_error`).
  Harmless but worth noting if you ever add many transient keys.
- **Try/except on `json.loads`** at line 84 catches `Exception`, which is broad but
  documented (Hard Rule #7) and bounded — only swallows `traderData` parse errors.
- **Iteration ordering**: `sorted(depth.sell_orders)` and `sorted(depth.buy_orders,
  reverse=True)` correctly walk the books from best to worst. ✓
- **`take_buy_used >= take_cap or take_buy_used >= room_buy` exit guards**: redundant
  with the next iteration's `qty <= 0` check, but defensive and free. No bug.
- **`state.own_trades` is not consulted**. Reference traders also ignore it for MM
  logic. Not a bug, just an observation.

---

## Ranked bug list (by likelihood of causing the IMC ±200 pinning + divergence)

| Rank | Tag | Location | Severity | Likelihood |
|------|-----|----------|----------|-----------|
| 1 | **B1**: no clear-layer / no asymmetric take threshold | lines 116–141 (take), missing intermediate layer | HIGH (strategic) | HIGH — directly explains pinning |
| 2 | **B2**: skew_strength too weak vs quote_offset | CONFIG defaults `skew_strength=1.0`, `quote_offset=3` (lines 32–33) | HIGH (strategic) | HIGH — compounds B1 |
| 3 | **Check 6**: per-side budget against projected pos, not start-of-tick pos | lines 144–166 (make sizing) | LOW–MEDIUM (interface) | LOW–MEDIUM — explains the 19 rejections in the IMC log but not the bulk of divergence |
| — | Checks 1, 2, 3, 4, 5 | — | n/a | PASS — no findings |

---

## Proposed fixes (NOT IMPLEMENTED)

### Fix for #1 (B1) — add a clear layer between take and make

Mirror v9's pattern. After the take loop and before the make sizing:

```python
# Clear layer: at exactly fv (clear_width = 0), unwind any open inventory.
# Mirrors R1 v9 aco_clear (trader-v9-r1-aco-only.py lines 274-298).
clear_width = 0
running_pos = pos + take_buy_used - take_sell_used
clear_buy_used = 0
clear_sell_used = 0
if running_pos > 0:
    for bp in sorted(depth.buy_orders, reverse=True):
        if bp < fv - clear_width:
            break
        qty = min(depth.buy_orders[bp], running_pos,
                  limit + pos - take_sell_used - clear_sell_used)
        if qty <= 0:
            break
        orders.append(Order(PRODUCT, bp, -qty))
        clear_sell_used += qty
        running_pos -= qty
elif running_pos < 0:
    for ap in sorted(depth.sell_orders):
        if ap > fv + clear_width:
            break
        qty = min(-depth.sell_orders[ap], -running_pos,
                  limit - pos - take_buy_used - clear_buy_used)
        if qty <= 0:
            break
        orders.append(Order(PRODUCT, ap, qty))
        clear_buy_used += qty
        running_pos += qty
```

Add `clear_width` (default 0) to CONFIG. Then update `proj_pos` for the make sizing
to include `clear_buy_used` and `clear_sell_used`.

Alternative (simpler, v8-style): keep the take loop but make `take_edge` asymmetric
on `pos`:

```python
buy_threshold  = fv - take_edge if pos >= 0 else fv
sell_threshold = fv + take_edge if pos <= 0 else fv
```

The clear-layer approach is closer to v9, more explicit, and easier to reason about
for sizing — recommended.

### Fix for #2 (B2) — increase skew_strength and/or decouple from quote_offset

Two options:

(a) Raise `skew_strength` to ≥ `quote_offset + 1` (so at full inventory the ask can
    cross to the wrong side of `fv` and the cross-guard at line 158 actually does
    work). Concretely: `skew_strength = 4`, `quote_offset = 3` → at +200, ask shifts
    to `fv − 1`, well below `fv` — aggressive unwind.

(b) Adopt v8's panic_extra term: when `|inv_ratio| ≥ panic_threshold` (e.g. 0.75),
    add an extra `panic_extra = round((|inv_ratio| − thr) / (1 − thr) * 3)` ticks
    of one-sided pressure on the unwind side.

Recommend (a) first — single-knob change, easy to sweep.

### Fix for #3 (Check 6) — cap make-leg budget against start-of-tick `pos`, not `proj_pos`

Replace the make-leg sizing (lines 161–162) with:

```python
sum_buys_so_far  = take_buy_used        # plus clear_buy_used  if Fix-1 applied
sum_sells_so_far = take_sell_used       # plus clear_sell_used if Fix-1 applied
bid_size = min(passive_size, max(0, limit - pos - sum_buys_so_far))
ask_size = min(passive_size, max(0, limit + pos - sum_sells_so_far))
```

This is the same invariant as v9's `_capped_buy / _capped_sell` helpers. Note that
`pos` here is start-of-tick; the projection is only used for skew and quote pricing,
not for budget. (Skew can continue to use `proj_pos` for its directional tilt — that
isn't a budget question.)

---

## Notes on what was NOT modified

- `R3/traders/trader-r3-v1-hydrogel.py` — untouched.
- No backtests were run.
- `~/prosperity_rust_backtester/` — not modified.
- `R3/traders/configs/hydrogel_v1.json` — not modified.

The audit's reference list:
- `R1/traders/trader-v8-173159.py`
- `R1/traders/trader1.py`
- `R1/archive/traders/trader-v9-r1-aco-only.py`
- canonical `datamodel.py` from `~/prosperity_rust_backtester/src/pytrader.rs:225–345`
