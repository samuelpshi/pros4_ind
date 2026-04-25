# IMC Prosperity 4 — Project Instructions

## Active Context

- Round 1 of the competition (April 14–17, 2026)
- Active focus: both products have been worked on. IPR was Phase 1 (drift capture, Config A committed); ACO Pass 2.5 produced a ship candidate pending R1 live verification. Default to not modifying either product's logic unless explicitly asked.
- Working in a shared GitHub repo with at least one teammate (Ethan)
- Goal: analyze data thoroughly, understand whether the current trader is sound, then improve the pepper-root strategy

## Session Workflow

At the start of every session:
1. Read CLAUDE.md (this file) for project rules and structure
2. Read WORKLOG.md and find the most recent session entry
3. Read the "Next session starts with" line from the most recent entry
4. Summarize in 2-3 sentences: "Last session we [X]. We're picking up at [Y]." Wait for user confirmation before proceeding.

At the end of every session, when the user signals we're wrapping up:
1. Append a new dated entry to WORKLOG.md with three sections:
   - What we did
   - Findings (specific numbers, p-values, plot references — not vague prose)
   - Next session starts with
2. If any structural change happened (new file location, new tool installed, new product focus), update CLAUDE.md to reflect it
3. Suggest a git commit message summarizing the session

## Repo Layout
IMC-Prosperity-2026-personal/
├── CLAUDE.md                                     ← project instructions (this file)
├── WORKLOG.md                                    ← running dev log; read at session start
├── IMC3_r1.md                                    ← R1 reference notes
├── "Round 1 - Trading groundwork".html           ← IMC tutorial HTML
├── "Writing an Algorithm in Python.html"         ← IMC tutorial HTML
├── images/                                       ← chart exports (PNGs)
└── Round 1/
    ├── r1_data_capsule/              ← raw data from IMC (CSVs); days -2/-1/0 are historical samples leading up to the live round
    │   ├── prices_round_1_day_-2.csv
    │   ├── prices_round_1_day_-1.csv
    │   ├── prices_round_1_day_0.csv
    │   ├── trades_round_1_day_-2.csv
    │   ├── trades_round_1_day_-1.csv
    │   └── trades_round_1_day_0.csv
    ├── analysis/
    │   ├── backtest.py                  ← local backtester; run as `python backtest.py` from `Round 1/analysis/`; hard-coded data paths via os.path relative to __file__; adjacent `traders/` dir inserted into sys.path; no argparse
    │   ├── pepper_root_deep_dive.ipynb  ← main analysis notebook
    │   ├── pepper_root_findings.md      ← verified findings with numbers
    │   └── bid_ask_analysis.ipynb       ← Ethan's basic EDA (visual only, no stats)
    ├── docs/
    │   ├── r1_product_mechanics.md      ← R1 rules spec
    │   └── imc3_r1_playbook.md          ← distilled IMC3 R1 historical playbook
    ├── traders/                         ← naming convention: trader-v<N>-<suffix>.py (version + optional variant suffix)
    │   ├── trader-v8-173159.py          ← base submission trader (v9, Config A) — THIS is what we improve
    │   ├── trader-v8-173159-jmerle.py   ← identical strategy + Logger class (~+86 lines) for jmerle visualizer compatibility; -jmerle suffix = visualizer-instrumented variant
    │   ├── trader-v9-aco-qo5-ms8-te3.py ← Pass 2.5 ACO ship candidate (qo=5, ms=8, te=3); PENDING R1 live verification
    │   └── trader1.py                   ← Ethan's separate trader (REFERENCE ONLY, do not edit)
    ├── archive/                         ← superseded artifacts (v9-r1 KELP attempt, Pass 3–6 runs/plots); see archive/README.md
    └── logs/
        └── 173159.log                   ← submission log
## Data Format Reference

**Prices file** (`prices_round_1_day_X.csv`, semicolon-separated):
- Columns: `day, timestamp, product, bid_price_1, bid_volume_1, bid_price_2, bid_volume_2, bid_price_3, bid_volume_3, ask_price_1, ask_volume_1, ask_price_2, ask_volume_2, ask_price_3, ask_volume_3, mid_price, profit_and_loss`
- Each row = one timestep snapshot of the order book for one product
- ~10,000 timesteps per day (timestamp goes 0 to ~1,000,000 in steps of 100)
- 3 levels of order book depth on each side

**Trades file** (`trades_round_1_day_X.csv`, semicolon-separated):
- Columns: `timestamp, buyer, seller, symbol, currency, price, quantity`
- `buyer`/`seller` are empty in early rounds (anonymized)
- Currency is XIRECS (in-game money)

## Hard Rules

1. **Verify everything empirically.** Don't trust docstrings, comments, or claims — write a small script to confirm on actual data.
2. **No magic numbers.** Every parameter in `trader.py` needs a comment pointing to where in the analysis it was justified.
3. **Straight-line-up cumulative PnL is the goal.** Jumpy PnL means hidden directional exposure or luck.
4. **Don't optimize against the IMC website backtest score.** It's only 20% of a day and overfits trivially. Use a local backtester (Jasper's `prosperity-bt` or equivalent) as primary.
5. **Explain math in plain language.** When using a statistical concept (autocorrelation, Z-score, ADF test, EMA, mean reversion, fair value, edge, slippage, market making, penny jumping, position limit, etc.), define it in context the first time per document. Assume the reader has a solid undergrad math background but is new to trading terminology.
6. **No ML for price prediction.** Compute budget is 100ms per timestep; small neural nets and big regressions overfit.
7. **No silent error handling.** Wrap try/except only with documented reason.

## What the Current Trader Does (v9 — Config A)

`traders/trader-v8-173159.py` handles two products:

**ASH_COATED_OSMIUM (ACO):** Standard market making with EMA-tracked fair value, take orders inside fair value +/- edge, post passive bids/asks around fair value with inventory skew. Logic unchanged from v8; only position limit updated (40->80).

Two parameter sets exist:
- **v8 baseline (shipped):** `quote_offset=2, max_skew=5, take_edge=3` — `traders/trader-v8-173159.py`.
- **Pass 2.5 ship candidate (pending R1 live verification):** `quote_offset=5, max_skew=8, take_edge=3` — `traders/trader-v9-aco-qo5-ms8-te3.py`. Local backtest showed +45%/+55%/+72% over v8 on days -2/-1/0. Not yet promoted to submission; final choice deferred until the R1 live log confirms the local ranking.

**INTARIAN_PEPPER_ROOT (IPR):** Full directional + small skim overlay:
- Aggressively buy **80** units at day start (max drift capture at position limit)
- Post tiny "skim" sell at `best_ask + 2` (size 5) when pos >= 75
- Post "refill" bid at `best_bid + 1` to rebuy after skim fills
- Deep defensive bids are structurally dead (no room when target = limit) — see Note 1 in findings
- Reversal protection: if fast EMA falls 8+ below slow EMA, target flips to 0 or short (needs scrutiny — see Note 2 in findings)

**Open concerns:**
- Reversal thresholds (-8, -15) are magic numbers; false trigger causes 160-unit forced unwind
- Deep bid feature is dead code at target=limit; flash-crash protection not available

## Analysis Plan (Phase 1 of Project)

Build `analysis/pepper_root_deep_dive.ipynb` with these cells:

**Phase 1 — Quantify the data:**
1. Load price + trade data, sanity check
2. Derive best bid, best ask, mid, spread per timestep
3. Compute returns (absolute and percentage)
4. Plot price + spread together
5. Distribution plots: spread histogram, return histogram

**Phase 2 — Test v8's directional thesis:**
6. Compute "buy 40 at start, hold to EOD" PnL for each of the 3 days. Mean, std. Is 3660 typical?
7. ADF test on price (mean reverting vs random walk)
8. Autocorrelation of returns at lags 1, 5, 20, 100

**Phase 3 — Search for hidden signals:**
9. Trade size histogram — find any suspicious repeating sizes
10. Plot trades of each repeating size on price chart — do any cluster at daily highs/lows? (Olivia signal detection)
11. Bot quote analysis — at what distances from mid do MM bots quote consistently?

**Phase 4 — Verify the engine:**
12. Use `profit_and_loss` column to back out IMC's true fair value formula
13. Empirical fill probability at different distances from mid

## Vocabulary to Define Inline When Used

bid, ask, order book, mid-price, spread, fair value (true price), edge, alpha, market making, taking liquidity, making liquidity, position, position limit, slippage, mean reversion, EMA (with formula), Z-score, ADF test, autocorrelation, penny jumping.

## Position-Limit Rules (confirmed from IMC docs)

- Position limits are **absolute**: position must stay in `[-limit, +limit]`.
- For IPR and ACO, the true limit is **80** (not the 40 hardcoded in v8).
- Allowed range is −80 to +80 (total range 160 units).
- Orders that would push position outside this range are auto-rejected by the engine.
- The existing `room_long_buy = limit - pos` and `room_long_sell = limit + pos` logic in v8 is structurally correct; only the numeric constants need updating.
- Full flips are legal in a single timestep: e.g., if pos = −5 and limit = 80, a buy of 85 is valid (brings position to +80).

## Verified Findings (do not re-litigate)

1. **Drift**: IPR drifts +1001.3/day (std=1.8) across all 3 days. Deterministic, not luck.
2. **Data cleaning**: 54 rows/day have fully empty order books (mid=0). 7.7% of rows have one side missing. Drop rows missing bid_price_1 or ask_price_1 for analysis. Drift unchanged after cleaning.
3. **Entry execution**: Greedy buy fills target=80 in 2-4 timesteps (ts 200-400). Slippage ~9.4/unit. 99.1% of theoretical drift captured.
4. **Position limit**: True limit is 80 (absolute, both sides). v8 hardcoded 40.

## Decisions Made So Far

- ACO: v8 logic remains the shipped default (limit 40->80). Pass 2.5 produced a tuned-parameter ship candidate (qo=5, ms=8, te=3) pending R1 live verification before promotion.
- IPR is the active battleground
- Working from `traders/trader-v8-173159.py` (v9, Config A), not Ethan's `traders/trader1.py`
- **Strategy call: Config A committed** — target_long=80 for max drift capture
- Config B (target=70) rejected: skim would need 16x v8's estimated productivity to break even

## Workflow Expectations

When starting a session:
1. Read this file
2. Read `analysis/pepper_root_deep_dive.ipynb` if it exists
3. Read `traders/trader-v8-173159.py`
4. Summarize current state in 2 sentences before doing anything else

When proposing strategy changes:
1. Show the diff before applying
2. Run the local backtester after every meaningful change
3. Compare new PnL to old PnL across all 3 days, not just one
4. Reject changes that improve mean PnL but increase variance significantly without justification

When committing to git:
- Use descriptive messages: "add ADF test to pepper root analysis" not "update"
- Coordinate with Ethan before pushing changes that affect shared files