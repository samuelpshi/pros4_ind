# P2_v2 — local backtester calibration & inventory module fix

Live log. Each step appended in chronological order.

## Phase 1 — calibrate local fill model against IMC

### Step 1.1 — qp sweep on D2

Ran local backtester at `--queue-penetration ∈ {0.0, 0.2, 0.4, 0.6, 0.8, 1.0}`
on D2 with `--persist`. Other matching settings at defaults
(`trade-match-mode=all`, `price-slippage-bps=0`). Trader unchanged.
Run dirs (timestamp = run start):

| qp  | run_dir                        |
|-----|--------------------------------|
| 0.0 | runs/backtest-1777165292181    |
| 0.2 | runs/backtest-1777165293553    |
| 0.4 | runs/backtest-1777165295071    |
| 0.6 | runs/backtest-1777165296622    |
| 0.8 | runs/backtest-1777165298189    |
| 1.0 | runs/backtest-1777165299609    |

### Step 1.2 — IMC ground truth (D2 window ts 0..99,900)

From `R3/logs/trader-r3-v1-hydrogel.log`:
- `trades = 115`
- `max_abs_position = 200`
- `final_pnl = -7,105.88`
- `position_limit_rejections = 19` (informational, dropped from distance
  score — local trader self-bounds, so this metric is constant 0 on local)

### Step 1.3 — distance table

Per-metric percent deviation: `|local − imc| / max(|imc|, 1)`. Sum across
the three retained metrics.

| qp  | trades | max\|p\| |  pnl_window | %dev_trd | %dev_pos | %dev_pnl | sum_dev |
|-----|-------:|--------:|------------:|---------:|---------:|---------:|--------:|
| 0.0 |     18 |      82 |   −2,459.00 |    0.843 |    0.590 |    0.654 |   2.087 |
| 0.2 |     20 |      80 |   −2,333.00 |    0.826 |    0.600 |    0.672 |   2.098 |
| 0.4 |     20 |      79 |   −2,270.00 |    0.826 |    0.605 |    0.681 |   2.112 |
| 0.6 |     20 |      79 |   −2,270.00 |    0.826 |    0.605 |    0.681 |   2.112 |
| 0.8 |     20 |      77 |   −2,144.00 |    0.826 |    0.615 |    0.698 |   2.139 |
| 1.0 |     20 |      76 |   −2,081.00 |    0.826 |    0.620 |    0.707 |   2.153 |

Best by `sum_dev`: **qp = 0.0** (boundary).
Best by `max_dev`: qp = 0.2 (essentially indistinguishable from 0.4–1.0).

### Step 1.4 — STOP condition triggered

Two simultaneous failures of the user-specified STOP rules:

1. **Optimal value at boundary (qp = 0.0).** User rule: "If the optimal
   value is at a boundary (0.0 or 1.0) → the fill model needs more than
   just queue_penetration tuning. STOP and report."
2. **No qp value gets within 15% of IMC on any of the three metrics.**
   User rule: "If a single value only matches one or two days within
   ~15% on each metric → calibration succeeded." Best-case here misses
   IMC by **~83% on trade count**, **~59% on max position**, and **~65%
   on PnL**. Calibration has not even succeeded on the single day we
   were fitting on, let alone generalized.

### Why qp doesn't move the needle — root cause

Counted historical bot-to-bot HYDROGEL_PACK trades in `r3_datacap/`:

| day | total bot trades | bot trades in window [0, 99,900] |
|-----|-----------------:|---------------------------------:|
| D0  |              324 |                               24 |
| D1  |              375 |                               39 |
| D2  |              311 |                               20 |

Local backtester reports 18–20 own trades on D2 in the same window
across all qp values — **almost 100% participation in the 20 historical
bot trades available**. There is no headroom for qp tuning to extract
more fills, because **the local rust backtester is a trade-replay
simulator**: our orders are matched against historical bot trades that
actually happened, not against the snapshot order book with synthesized
flow. `queue_penetration` controls our share of historical-trade volume;
it cannot synthesize volume that wasn't in the data.

IMC's 115 fills in the same window means **IMC is not a trade-replay
simulator** — it interacts our quotes with the snapshot books somehow
(probably synthesizes additional flow, or treats incoming ticks as
crossable against any resting order ≤ touch). This is a fundamentally
richer fill model than what `rust_backtester` can express, regardless
of parameter value.

`--trade-match-mode=book` was probed (CLI accepts the value silently
without a closed enum check) and produced an identical 20-trade /
+1,719 PnL result to the default `all` mode. So no other knob in the
existing rust backtester closes the gap either.

### Recommendation

Phase 1 cannot be completed with the current local backtester. Three
paths forward, ordered by my preference:

1. **Switch local backtester to one with order-book-flow synthesis.**
   Most plausibly the `jmerle/IMC-Prosperity-3-backtester` (Python,
   community-maintained, used widely in P3) or another community fork
   that does touch-fill against snapshot books. Risk: any backtester is
   a model, and we'd need to re-validate it against IMC ground truth
   the same way before trusting it. Effort: a few hours to install,
   adapt the dataset symlinks, and re-run the divergence comparison.

2. **Pivot to using IMC submissions as the primary tuning loop.** Limit
   the per-tweak burn by batching changes (instead of one change per
   submission, ship a config bundle and read which params produced
   which behaviour from the log). The Phase 2 inventory work would be
   designed against the IMC fill model directly. Risk: slower
   iteration cadence, harder to do parameter sweeps. Effort: a
   workflow/process change, no new code.

3. **Build a custom mini-backtester that does touch-fill against the
   snapshot book**. Read each tick's `bid_price_1/ask_price_1`; if our
   ask ≤ bid_1, we sell into bid_1 with some volume model; if our bid
   ≥ ask_1, we buy into ask_1. This is what IMC appears to do. Risk:
   own-built, will have its own quirks; need to validate against IMC
   anyway. Effort: a day, plus validation.

Stopping here per user instruction. **Phase 2 is not started.**

### Receipts

- Sweep runner: `/tmp/qp_sweep.sh`
- Sweep parser: `/tmp/qp_parse.py`
- Persisted local runs: `~/prosperity_rust_backtester/runs/backtest-1777165{292181,293553,295071,296622,298189,299609}/`
- IMC log: `R3/logs/trader-r3-v1-hydrogel.log`
- Historical bot-trade source: `R3/r3_datacap/trades_round_3_day_{0,1,2}.csv`
