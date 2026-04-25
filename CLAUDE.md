# IMC Prosperity 4 — Project Instructions

## Active Context

- **Round 3 ("Gloves Off")** of the competition — start of **GOAT phase**, leaderboard reset to 0
- Active focus: build from-scratch options strategy for VEV vouchers, plus delta-1 strategies for HYDROGEL_PACK and VELVETFRUIT_EXTRACT
- Goal: thorough EDA → simple FH-style trading logic → backtest variations → ship before R3 live close

## Round 3 Products

**Delta-1 (limit 200 each):**
- `HYDROGEL_PACK` — new product, behavior unknown
- `VELVETFRUIT_EXTRACT` (VEV) — underlying for the 10 vouchers

**Options — European call vouchers (limit 300 each, 10 strikes):**
- `VEV_4000`, `VEV_4500`, `VEV_5000`, `VEV_5100`, `VEV_5200`, `VEV_5300`, `VEV_5400`, `VEV_5500`, `VEV_6000`, `VEV_6500`

**TTE schedule:**
- Vouchers expire at end of R5 (or after — verify exact rule from R3_wiki.html)
- Historical day 0 → TTE = 8d
- Historical day 1 → TTE = 7d
- Historical day 2 → TTE = 6d
- **R3 simulation start → TTE = 5d**
- R4 → 4d, R5 → 3d
- Positions liquidated at hidden fair value at end of each round; inventory does NOT carry over

## R3 Reference Documents

- `Round 3/R3_wiki.html` — IMC's official R3 round brief
- `Round 3/FH_trader.py` — Frankfurt Hedgehogs Prosperity 3 voucher trader (REFERENCE ONLY, do not edit)
- `Round 3/R3_INVESTIGATION_CHECKLIST.md` — synthesis of two P3 voucher-round writeups (FH + the unnamed-team hybrid strategy)
- `Round 3/r3_datacap/` — historical price/trade CSVs (same format as R1)

## Session Workflow

NOTE: WORKLOG.md was reset for R3.

### When working solo (one Claude Code session at a time)

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
4. Do not commit — Sam handles git

### When multiple agents work in parallel (Phase 1 EDA, Phase 2 sweeps, etc.)

Multiple agents writing to a single WORKLOG.md causes merge conflicts. Instead:

1. Each agent owns its own log file at `Round 3/analysis/agent_logs/<agent_id>_log.md`
2. Agent IDs follow conventions: N1-N4 for EDA notebooks; P2_<short-name> for Phase 2 work (e.g., P2_v1_baseline, P2_smile_sweep, P2_ema_sweep)
3. Each agent log uses the same three-section format (What we did / Findings / Next session starts with)
4. Numbers, not vibes — every claim is backed by a specific cell output, file path, or backtest run ID
5. Agents do not edit other agents' logs
6. Agents do not append to WORKLOG.md directly while working in parallel

After all parallel agents finish, a separate consolidation pass (run by Sam or a dedicated consolidator agent):
1. Reads all the agent_logs/*_log.md files for that phase
2. Writes one dated WORKLOG.md entry summarizing the full phase
3. Suggests a single git commit message
4. Sam commits manually

### Numbers, not vibes — examples

Bad: "Showed clear mean reversion."
Good: "Lag-1 ACF = -0.13 on HYDROGEL_PACK returns, 12σ negative, see notebook 01 cell 18."

Bad: "Backtest looked promising."
Good: "v1-baseline mean PnL across 3 days = 14,200 (std 3,100); per-product breakdown in backtest_results.md row 4."

## Repo Layout

```
IMC-Prosperity-2026-personal/
├── CLAUDE.md                                     ← project instructions (this file)
├── WORKLOG.md                                    ← running dev log; read at session start
├── Writing an Algorithm in Python.html           ← Trading Logic structure/syntax for competition
├── images/                                       ← chart exports (PNGs)
├── R1/                                           ← R1 archive (complete, inactive)
├── R2/                                           ← R2 archive (complete, inactive)
│   └── [structure mirrors R1 where applicable]
└── Round 3/                                      ← ACTIVE
    ├── R3_wiki.html                              ← IMC R3 round brief
    ├── FH_trader.py                              ← Frankfurt Hedgehogs reference (DO NOT EDIT)
    ├── R3_INVESTIGATION_CHECKLIST.md             ← synthesis of P3 voucher writeups
    ├── r3_datacap/                               ← historical data (3 days)
    │   ├── prices_round_3_day_0.csv              ← TTE = 8d (verify)
    │   ├── prices_round_3_day_1.csv              ← TTE = 7d (verify)
    │   ├── prices_round_3_day_2.csv              ← TTE = 6d (verify)
    │   ├── trades_round_3_day_0.csv
    │   ├── trades_round_3_day_1.csv
    │   └── trades_round_3_day_2.csv
    ├── analysis/                                 ← EDA notebooks (created by agents)
    │   ├── 01_underlying_eda.ipynb
    │   ├── 02_voucher_market_structure.ipynb
    │   ├── 03_iv_smile_analysis.ipynb
    │   ├── 04_signal_validation_and_fh_features.ipynb
    │   ├── agent_logs/                           ← per-agent work logs
    │   ├── backtest_results.csv                  ← machine-readable backtest log (append-only)
    │   └── backtest_results.md                   ← human-readable backtest commentary
    ├── traders/                                  ← naming: trader-r3-v<N>-<suffix>.py
    │   └── (created after EDA)
    ├── docs/
    │   └── r3_product_mechanics.md               ← extracted from R3_wiki.html
    └── logs/
```

## Data Format Reference

**Prices file** (`prices_round_3_day_X.csv`, semicolon-separated):
- Columns: `day, timestamp, product, bid_price_1, bid_volume_1, bid_price_2, bid_volume_2, bid_price_3, bid_volume_3, ask_price_1, ask_volume_1, ask_price_2, ask_volume_2, ask_price_3, ask_volume_3, mid_price, profit_and_loss`
- Each row = one timestep snapshot of the order book for one product
- ~10,000 timesteps per day (timestamp goes 0 to ~1,000,000 in steps of 100)
- 3 levels of order book depth on each side
- 12 products per timestamp in R3: HYDROGEL_PACK, VELVETFRUIT_EXTRACT, plus 10 vouchers

**Trades file** (`trades_round_3_day_X.csv`, semicolon-separated):
- Columns: `timestamp, buyer, seller, symbol, currency, price, quantity`
- `buyer`/`seller` are empty in early rounds (anonymized)
- Currency is XIRECS (in-game money)

## Hard Rules

1. **Verify everything empirically.** Don't trust docstrings, comments, or claims — write a small script to confirm on actual data.
2. **No magic numbers.** Every parameter in the trader needs a comment pointing to where in the analysis it was justified.
3. **Straight-line-up cumulative PnL is the goal.** Jumpy PnL means hidden directional exposure or luck.
4. **Don't optimize against the IMC website backtest score.** It's only 20% of a day and overfits trivially. Use the local Rust backtester (`prosperity_rust_backtester`) as primary; see the "Local Backtester" section for the standard invocation. All trader variants must be backtested across all 3 historical days before any comparison conclusions are drawn.
5. **Explain math in plain language.** When using a statistical or finance concept (autocorrelation, Z-score, ADF test, EMA, mean reversion, fair value, edge, slippage, market making, position limit, implied volatility, vol smile, moneyness, delta hedging, vega, gamma, theta, etc.), define it in context the first time per document. Assume the reader has a solid undergrad math background but is new to specific trading terminology.
6. **No ML for price prediction.** Compute budget is 100ms per timestep; small neural nets and big regressions overfit.
7. **No silent error handling.** Wrap try/except only with documented reason.
8. **R3-specific — always know your net delta.** Even if not hedging every tick, compute and log net portfolio delta from voucher positions. FH skipped explicit hedging because their TTE=3d positions had small delta; our TTE=5d positions will be larger.
9. **R3-specific — replicate before improving.** For each FH feature (hardcoded smile, wall mid signal, EMA demeaning, switch gate, strike segmentation), backtest the FH version first as a baseline, then test variations.

## Position-Limit Rules (confirmed from IMC docs)

- Position limits are **absolute**: position must stay in `[-limit, +limit]`.
- HYDROGEL_PACK: limit 200
- VELVETFRUIT_EXTRACT: limit 200
- Each voucher (10 strikes): limit 300
- Orders that would push position outside this range are auto-rejected.
- Full flips are legal in a single timestep.

## Local Backtester

We use [GeyzsoN/prosperity_rust_backtester](https://github.com/GeyzsoN/prosperity_rust_backtester) as the primary local backtester.

### Setup (one-time, already done)

- Backtester repo lives at `~/prosperity_rust_backtester/` (outside this repo)
- Round data is symlinked into the backtester's `datasets/` folder:
~/prosperity_rust_backtester/datasets/round3 → IMC-Prosperity-2026-personal/Round 3/r3_datacap
- CLI installed via `make install` and accessible as `rust_backtester` from anywhere

### Standard agent invocation

Agents should call the backtester via bash from this repo's root using full paths to keep things explicit. Standard command:

```bash
rust_backtester \
  --trader "$(pwd)/Round 3/traders/<trader_filename>.py" \
  --dataset round3
```

Single-day run:

```bash
rust_backtester \
  --trader "$(pwd)/Round 3/traders/<trader_filename>.py" \
  --dataset round3 \
  --day -2
```

Persisted run (writes `runs/<backtest-id>/submission.log` for jmerle visualizer):

```bash
rust_backtester \
  --trader "$(pwd)/Round 3/traders/<trader_filename>.py" \
  --dataset round3 \
  --persist
```

### Output parsing

The CLI prints a table to stdout, one row per day:
SET    DAY    TICKS  OWN_TRADES    FINAL_PNL  RUN_DIR
D-2     -2    10000          39       118.10  runs/backtest-...
D-1     -1    10000          42       123.45  runs/backtest-...
D0       0    10000          37        95.20  runs/backtest-...

Plus a per-product PnL breakdown (`--products full` for all products, `summary` default). Parse `FINAL_PNL` per day; compute mean and std across days. Use `--products full` when comparing variant attribution.

### Multi-variant comparison workflow

For comparing trader variants (which we do a lot in Phase 2):

1. Each variant lives in `Round 3/traders/trader-r3-v<N>-<suffix>.py`
2. Run all variants on the full round
3. Save results to `Round 3/analysis/backtest_results.csv` with columns: `variant, day, final_pnl, run_dir, timestamp`
4. Append to `Round 3/analysis/backtest_results.md` with: variant name, mean PnL, std PnL across days, per-product attribution table, qualitative notes
5. Reject any variant that improves mean PnL but inflates std without justification (Hard Rule #3)

### What agents should NOT do

- Do not edit files inside `~/prosperity_rust_backtester/` (it's a third-party repo)
- Do not modify the symlink without updating CLAUDE.md
- Do not run the IMC website backtest as the primary metric (Hard Rule #4)
- Do not draw conclusions from a single day's PnL — always all 3 days

## Key Equations & Conventions

**Black-Scholes call** (r=0, no divs):
$$C(S, K, T, \sigma) = S \cdot N(d_1) - K \cdot N(d_2)$$
$$d_1 = \frac{\log(S/K) + 0.5\sigma^2 T}{\sigma\sqrt{T}}, \quad d_2 = d_1 - \sigma\sqrt{T}$$

**Greeks**: $\Delta = N(d_1)$, $\nu = S \cdot \phi(d_1) \cdot \sqrt{T}$ (vega), $\Gamma = \phi(d_1) / (S \sigma \sqrt{T})$.

**Moneyness for smile fit**: $m_t = \log(K/S_t) / \sqrt{T}$ (this is FH's convention; both reference writeups use it).

**Quadratic smile**: $\hat{v}(m) = a m^2 + b m + c$. Intercept $c$ ≈ ATM base IV. Track over time as a level signal.

**TTE in years**: divide TTE-in-days by 365. FH's formula: `tte = 1 - (DAYS_PER_YEAR - 8 + DAY + timestamp_fraction) / DAYS_PER_YEAR` simplifies to `(8 - DAY - tf) / 365`.

## Vocabulary Additions for R3

Define inline when first used per document: implied volatility (IV), volatility smile, moneyness, delta, vega, gamma, theta, ATM/ITM/OTM, pin risk, wall mid (deepest visible MM quote midpoint), residual demeaning, gamma scalping, IV mean reversion.

## R3 EDA Plan (Phase 1)

Four parallel notebooks under `Round 3/analysis/`:

1. **01_underlying_eda.ipynb** — characterize HYDROGEL_PACK and VEV (stationarity, autocorrelation, mean-reversion tests)
2. **02_voucher_market_structure.ipynb** — per-strike liquidity, spread, ATM tracking, hedge feasibility
3. **03_iv_smile_analysis.ipynb** — BS pricer, IV inversion, smile fitting (hardcoded + per-tick variants), residuals in IV and price space
4. **04_signal_validation_and_fh_features.ipynb** — 1-lag autocorr tests, base IV mean reversion, vega vs residual rank, wall_mid signal comparison, FH switch gate replication

XML agent prompts for these notebooks are in `Round 3/R3_EDA_AGENTS.xml`.

## R3 Trader Implementation Plan (Phase 2 — after EDA)

After agents finish EDA and findings are reviewed:

1. **trader-r3-v1-fh-replica.py** — Direct replication of FH's logic adapted to VEV vouchers. Hardcoded smile (fitted offline), best_bid/ask signal, EMA demeaning, switch gate. Baseline.
2. **trader-r3-v2-perTick-smile.py** — Same as v1 but with per-tick smile refit instead of hardcoded.
3. **trader-r3-v2b-...** — variations on individual FH features (signal anchor, EMA windows, switch threshold, strike segmentation cutoff).
4. **trader-r3-v3-with-hedge.py** — Add explicit delta hedge using VEV (FH skipped this; we shouldn't at TTE=5d).
5. **trader-r3-v4-with-overlays.py** — Add HYDROGEL_PACK strategy + (optional) VEV mean-reversion overlay.

Each version is backtested across all 3 historical days **by the agent making the change**, using the Local Backtester section's standard invocation. Results go to `Round 3/analysis/backtest_results.csv` and `Round 3/analysis/backtest_results.md`. Compare mean PnL, std PnL, per-product attribution. Reject changes that improve mean but inflate variance without justification.

## Workflow Expectations

When starting a session:
1. Read this file
2. Read most recent WORKLOG.md entry
3. Read whichever EDA notebook or trader file is the active focus
4. Summarize current state in 2 sentences before doing anything else

When proposing strategy changes:
1. Show the diff before applying
2. Run the Rust backtester after every meaningful change (see "Local Backtester" section for the command)
3. Append results to `Round 3/analysis/backtest_results.csv` and update `backtest_results.md` with a one-paragraph commentary
4. Compare new PnL to old PnL across all 3 days, not just one. Report mean, std, per-product breakdown, and qualitative notes.
5. Reject changes that improve mean PnL but increase variance significantly without justification
6. Never delete prior backtest results — keep them as the historical record so we can see what was tried

When committing to git:
- Use descriptive messages: "add IV smile fit to R3 analysis" not "update"
