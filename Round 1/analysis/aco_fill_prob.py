"""
aco_fill_prob.py — A4: Fill Probability by Offset
===================================================

Computes counterfactual fill probabilities and expected PnL for passive quotes
posted at best_bid - N (bid side) or best_ask + N (ask side) for N in {1..10}.

Counterfactual fill model:
  - A hypothetical bid at price P (size 1) posted at tick t fills at tick t+k
    if the trade stream at tick t+k contains a seller-initiated trade at price <= P.
  - A hypothetical ask at price P (size 1) posted at tick t fills at tick t+k
    if the trade stream at tick t+k contains a buyer-initiated trade at price >= P.
  - "Seller-initiated" = trade price <= bid_price_1 (hitting the bid).
  - "Buyer-initiated"  = trade price >= ask_price_1 (lifting the ask).
  - "Within K ticks" means within the next K price-row ticks (not timestamps).

Fair value: mmbot_mid (volume >= 15 filter, A2's convention).

IMPORTANT — Sanity check note:
  v8's aco_make() quotes are NOT at best_bid - N. They are at floor(fv) - N - skew,
  which is typically ~5.6 ticks ABOVE best_bid (i.e., inside the spread, near mid).
  The 'offset' in v8's code means offset-from-FV, not offset-from-best-bid.
  Sanity check uses v8's actual fv-based quotes against the public trade stream:
  this reproduces A3's passive fill count to within ~3%.

Output:
  - aco_fill_prob_results.json: per-day per-N tables
  - plots/aco_deep/pnl_vs_offset.png: E[PnL/fill @K=50] vs offset per day
"""

import os
import sys
import json
import math
import warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

BASE     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "..", "r1_data_capsule")
PLOT_DIR = os.path.join(BASE, "plots", "aco_deep")
os.makedirs(PLOT_DIR, exist_ok=True)

DAYS       = [-2, -1, 0]
OFFSETS    = [1, 2, 3, 4, 5, 6, 8, 10]
PNL_KS     = [10, 50, 200]         # ticks for E[PnL/fill]
VOL_THRESH = 15                    # mmbot_mid filter threshold (A2)
EOD_START  = 950_000
MAX_LOOK   = 210                   # max ticks to look ahead (covers K=200 + fill search)

# A3 passive fill counts (ground truth from aco_decomp_results.json)
A3_PASSIVE_FILLS = {-2: 390, -1: 397, 0: 377}


# ---------------------------------------------------------------------------
# Utility: mmbot_mid
# ---------------------------------------------------------------------------

def mmbot_mid_fn(bid1, bv1, bid2, bv2, bid3, bv3,
                 ask1, av1, ask2, av2, ask3, av3,
                 thresh=VOL_THRESH):
    def best(levels):
        filt = [(p, v) for p, v in levels
                if not (math.isnan(p) or math.isnan(v)) and v >= thresh]
        if not filt:
            filt = [(p, v) for p, v in levels
                    if not (math.isnan(p) or math.isnan(v))]
        return filt
    bids = best([(bid1, bv1), (bid2, bv2), (bid3, bv3)])
    asks = best([(ask1, av1), (ask2, av2), (ask3, av3)])
    if not bids or not asks:
        return float('nan')
    return (max(p for p, _ in bids) + min(p for p, _ in asks)) / 2.0


def safe_float(x):
    try:
        v = float(x)
        return v if not math.isnan(v) else float('nan')
    except Exception:
        return float('nan')


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_prices(day):
    path = os.path.join(DATA_DIR, f"prices_round_1_day_{day}.csv")
    df = pd.read_csv(path, sep=';')
    df = df[df['product'] == 'ASH_COATED_OSMIUM'].copy()
    df = df.dropna(subset=['bid_price_1', 'ask_price_1']).reset_index(drop=True)
    # Fill NaN volume columns with 0 for mmbot_mid computation
    for col in ['bid_volume_1','bid_volume_2','bid_volume_3',
                'ask_volume_1','ask_volume_2','ask_volume_3',
                'bid_price_2','bid_price_3','ask_price_2','ask_price_3']:
        if col not in df.columns:
            df[col] = float('nan')

    df['mmbot_mid'] = df.apply(lambda r: mmbot_mid_fn(
        safe_float(r['bid_price_1']), safe_float(r['bid_volume_1']),
        safe_float(r['bid_price_2']), safe_float(r['bid_volume_2']),
        safe_float(r['bid_price_3']), safe_float(r['bid_volume_3']),
        safe_float(r['ask_price_1']), safe_float(r['ask_volume_1']),
        safe_float(r['ask_price_2']), safe_float(r['ask_volume_2']),
        safe_float(r['ask_price_3']), safe_float(r['ask_volume_3']),
    ), axis=1)
    return df


def load_trades(day):
    path = os.path.join(DATA_DIR, f"trades_round_1_day_{day}.csv")
    df = pd.read_csv(path, sep=';')
    df = df[df['symbol'] == 'ASH_COATED_OSMIUM'].copy()
    return df.sort_values('timestamp').reset_index(drop=True)


def classify_trades(trades_df, prices_df):
    """
    Classify each trade as buyer- or seller-initiated:
      - Buyer-initiated  (lifts ask): price >= ask_price_1 -> could fill passive BID at P <= price
      - Seller-initiated (hits bid):  price <= bid_price_1 -> could fill passive ASK at P >= price
    """
    trades_sorted = trades_df.sort_values('timestamp').reset_index(drop=True)
    prices_sorted = prices_df.sort_values('timestamp').reset_index(drop=True)
    merged = pd.merge_asof(
        trades_sorted,
        prices_sorted[['timestamp', 'bid_price_1', 'ask_price_1', 'mmbot_mid']],
        on='timestamp',
        direction='backward',
    )
    merged['direction'] = 'unclear'
    merged.loc[merged['price'] >= merged['ask_price_1'], 'direction'] = 'buy'
    merged.loc[merged['price'] <= merged['bid_price_1'], 'direction'] = 'sell'
    return merged


def build_trade_lookup(prices_df, classified_trades_df):
    """
    For each price-row index i, collect lists of:
      sell_prices[i]: prices of seller-initiated trades at that timestamp
      buy_prices[i]:  prices of buyer-initiated trades at that timestamp
    """
    ts_arr = prices_df['timestamp'].values.astype(int)
    ts_to_idxs = {}
    for i, ts in enumerate(ts_arr):
        ts_to_idxs.setdefault(int(ts), []).append(i)

    n = len(prices_df)
    sell_prices = [[] for _ in range(n)]
    buy_prices  = [[] for _ in range(n)]

    for _, row in classified_trades_df.iterrows():
        ts  = int(row['timestamp'])
        p   = float(row['price'])
        d   = str(row['direction'])
        for idx in ts_to_idxs.get(ts, []):
            if d == 'sell':
                sell_prices[idx].append(p)
            elif d == 'buy':
                buy_prices[idx].append(p)

    return sell_prices, buy_prices


# ---------------------------------------------------------------------------
# Sanity check: v8's ACTUAL fv-based quote placement (not best_bid-N)
# ---------------------------------------------------------------------------

def counterfactual_v8_fv_quotes(prices_df, sell_prices_by_idx, buy_prices_by_idx,
                                 eod_start=EOD_START, limit=80):
    """
    Sanity check: simulate v8's aco_make() using actual EMA fair-value formula
    (floor(fv) - offset - skew for bids), then check public trade stream at t+1.

    NOTE: v8's quote price is NOT best_bid - N. It is floor(fv) - N - skew,
    where fv is the EMA of mmbot_mid. This is typically ~5.6 ticks ABOVE best_bid
    (inside the spread). The 'offset' parameter in v8 = offset from FV, not from best_bid.

    Returns (bid_fills, ask_fills, total).
    """
    offset = 2; max_skew = 5; panic_thr = 0.75; ema_alpha = 0.12
    n        = len(prices_df)
    ts_arr   = prices_df['timestamp'].values.astype(int)
    bid1_arr = prices_df['bid_price_1'].values.astype(float)
    ask1_arr = prices_df['ask_price_1'].values.astype(float)
    mmbot_arr= prices_df['mmbot_mid'].values.astype(float)

    fv  = next(v for v in mmbot_arr if not math.isnan(v))
    pos = 0
    bid_fills = 0
    ask_fills = 0

    for i in range(n - 1):
        if ts_arr[i] >= eod_start:
            continue
        if math.isnan(bid1_arr[i]) or math.isnan(ask1_arr[i]):
            continue
        m = mmbot_arr[i]
        if not math.isnan(m):
            fv = ema_alpha * m + (1 - ema_alpha) * fv

        inv_ratio   = pos / limit
        skew        = round(inv_ratio * max_skew)
        panic_extra = 0
        if abs(inv_ratio) >= panic_thr:
            panic_extra = round((abs(inv_ratio) - panic_thr) / (1.0 - panic_thr) * 3)

        bid_px = math.floor(fv) - offset - skew
        ask_px = math.ceil(fv)  + offset - skew
        if pos > 0 and panic_extra > 0:
            ask_px -= panic_extra
        elif pos < 0 and panic_extra > 0:
            bid_px += panic_extra
        if abs(inv_ratio) >= panic_thr:
            bid_px = min(bid_px, math.floor(fv))
            ask_px = max(ask_px, math.ceil(fv))
        else:
            bid_px = min(bid_px, math.floor(fv) - 1)
            ask_px = max(ask_px, math.ceil(fv) + 1)
        if ask_px <= bid_px:
            ask_px = bid_px + 1

        buy_qty  = limit - pos
        sell_qty = limit + pos
        j = i + 1

        if buy_qty > 0:
            for sp in sell_prices_by_idx[j]:
                if sp <= bid_px:
                    pos += 1
                    bid_fills += 1
                    break
        if sell_qty > 0:
            for bp in buy_prices_by_idx[j]:
                if bp >= ask_px:
                    pos -= 1
                    ask_fills += 1
                    break

    return bid_fills, ask_fills, bid_fills + ask_fills


# ---------------------------------------------------------------------------
# Core counterfactual engine: size=1, best_bid-N / best_ask+N
# ---------------------------------------------------------------------------

def counterfactual_fills_size1(prices_df, sell_prices, buy_prices,
                               offset, eod_start=EOD_START):
    """
    For each non-EOD tick i, post:
      bid at best_bid - offset  (fills if seller-initiated trade <= bid_px within MAX_LOOK ticks)
      ask at best_ask + offset  (fills if buyer-initiated trade  >= ask_px within MAX_LOOK ticks)

    Returns (bid_fills, ask_fills) where each is a list of dicts with fill metadata.
    """
    n        = len(prices_df)
    ts_arr   = prices_df['timestamp'].values.astype(int)
    bid1_arr = prices_df['bid_price_1'].values.astype(float)
    ask1_arr = prices_df['ask_price_1'].values.astype(float)
    mmbot_arr= prices_df['mmbot_mid'].values.astype(float)

    bid_fills = []
    ask_fills = []

    for i in range(n):
        if ts_arr[i] >= eod_start:
            continue
        if math.isnan(bid1_arr[i]) or math.isnan(ask1_arr[i]):
            continue

        bid_px = bid1_arr[i] - offset
        ask_px = ask1_arr[i] + offset

        bid_fill_tick = None
        ask_fill_tick = None

        for k in range(1, MAX_LOOK + 1):
            j = i + k
            if j >= n:
                break
            if bid_fill_tick is None:
                for sp in sell_prices[j]:
                    if sp <= bid_px:
                        bid_fill_tick = k
                        break
            if ask_fill_tick is None:
                for bp in buy_prices[j]:
                    if bp >= ask_px:
                        ask_fill_tick = k
                        break
            if bid_fill_tick is not None and ask_fill_tick is not None:
                break

        def future_mid(fill_k):
            fill_j = i + fill_k
            # mid at fill
            m_fill = mmbot_arr[fill_j] if fill_j < n and not math.isnan(mmbot_arr[fill_j]) else mmbot_arr[i]
            # future mids at K ahead of fill
            adv = {}
            for K in PNL_KS:
                fj2 = fill_j + K
                if fj2 < n and not math.isnan(mmbot_arr[fj2]):
                    adv[K] = float(mmbot_arr[fj2])
                else:
                    adv[K] = float('nan')
            return float(m_fill), adv

        if bid_fill_tick is not None:
            mid_at_fill, future_mids = future_mid(bid_fill_tick)
            adv = {}
            for K in PNL_KS:
                fm = future_mids[K]
                adv[K] = fm - bid_px if not math.isnan(fm) else float('nan')
            bid_fills.append({
                'tick':         int(i),
                'fill_tick':    int(bid_fill_tick),
                'fill_price':   float(bid_px),
                'mid_at_fill':  float(mid_at_fill),
                'edge_at_fill': float(mid_at_fill - bid_px),
                'adv_sel':      adv,
            })

        if ask_fill_tick is not None:
            mid_at_fill, future_mids = future_mid(ask_fill_tick)
            adv = {}
            for K in PNL_KS:
                fm = future_mids[K]
                adv[K] = ask_px - fm if not math.isnan(fm) else float('nan')
            ask_fills.append({
                'tick':         int(i),
                'fill_tick':    int(ask_fill_tick),
                'fill_price':   float(ask_px),
                'mid_at_fill':  float(mid_at_fill),
                'edge_at_fill': float(ask_px - mid_at_fill),
                'adv_sel':      adv,
            })

    return bid_fills, ask_fills


# ---------------------------------------------------------------------------
# Bootstrap CI on P(fill)
# ---------------------------------------------------------------------------

def bootstrap_ci_pfill(fill_flags, n_bootstrap=1000, ci=0.95):
    n = len(fill_flags)
    if n == 0:
        return float('nan'), float('nan'), float('nan')
    arr = np.array(fill_flags, dtype=float)
    mean = float(arr.mean())
    rng = np.random.default_rng(42)
    boot_means = np.array([rng.choice(arr, size=n, replace=True).mean()
                           for _ in range(n_bootstrap)])
    alpha = (1 - ci) / 2
    return mean, float(np.quantile(boot_means, alpha)), float(np.quantile(boot_means, 1 - alpha))


# ---------------------------------------------------------------------------
# Main analysis per day
# ---------------------------------------------------------------------------

def analyze_day(day):
    print(f"\n=== Day {day} ===")
    prices_df  = load_prices(day)
    trades_df  = load_trades(day)
    classified = classify_trades(trades_df, prices_df)

    dir_counts = classified['direction'].value_counts()
    print(f"  Trades: {len(classified)} total | buy={dir_counts.get('buy',0)} | "
          f"sell={dir_counts.get('sell',0)} | unclear={dir_counts.get('unclear',0)}")

    sell_prices, buy_prices = build_trade_lookup(prices_df, classified)

    n_non_eod = int((prices_df['timestamp'] < EOD_START).sum())
    print(f"  Non-EOD ticks: {n_non_eod} of {len(prices_df)}")

    # --- Sanity check: v8 fv-based quotes vs A3 ---
    cf_bid, cf_ask, cf_total = counterfactual_v8_fv_quotes(
        prices_df, sell_prices, buy_prices)
    a3_count = A3_PASSIVE_FILLS[day]
    pct_diff = (cf_total - a3_count) / a3_count * 100
    sanity_pass = abs(pct_diff) <= 20.0
    print(f"  Sanity (fv-quote CF): bid={cf_bid} ask={cf_ask} total={cf_total} "
          f"vs A3={a3_count} | delta={pct_diff:+.1f}%  {'PASS' if sanity_pass else 'FAIL'}")
    print(f"  [Note: v8 quotes at floor(fv)-2-skew, ~5.6 ticks ABOVE best_bid on average]")

    # --- Main offset sweep (best_bid-N / best_ask+N, size=1) ---
    n_ticks = len(prices_df)
    all_tick_indices = prices_df[prices_df['timestamp'] < EOD_START].index.tolist()
    tick_index_set_non_eod = set(all_tick_indices)

    results = {}
    for N in OFFSETS:
        bid_fills_raw, ask_fills_raw = counterfactual_fills_size1(
            prices_df, sell_prices, buy_prices, offset=N)

        row = {}
        for side_name, fills in [('bid', bid_fills_raw), ('ask', ask_fills_raw)]:
            # P(fill within 10 and 100 ticks)
            filled_10_ticks  = set(r['tick'] for r in fills if r['fill_tick'] <= 10)
            filled_100_ticks = set(r['tick'] for r in fills if r['fill_tick'] <= 100)

            flags_10  = [1 if t in filled_10_ticks  else 0 for t in all_tick_indices]
            flags_100 = [1 if t in filled_100_ticks else 0 for t in all_tick_indices]

            pfill_10,  ci10_lo,  ci10_hi  = bootstrap_ci_pfill(flags_10)
            pfill_100, ci100_lo, ci100_hi = bootstrap_ci_pfill(flags_100)

            n_fills = len(fills)
            edge_vals = [r['edge_at_fill'] for r in fills if not math.isnan(r['edge_at_fill'])]
            mean_edge = float(np.mean(edge_vals)) if edge_vals else float('nan')

            mean_pnl_k = {}
            for K in PNL_KS:
                pnl_vals = [r['adv_sel'][K] for r in fills
                            if K in r['adv_sel'] and not math.isnan(r['adv_sel'][K])]
                mean_pnl_k[K] = float(np.mean(pnl_vals)) if pnl_vals else float('nan')

            if n_fills < 100:
                print(f"    WARNING: N={N}, {side_name}: only {n_fills} fills — CI flagged")

            row[side_name] = {
                'n_fills':      n_fills,
                'n_opps':       n_non_eod,
                'pfill_10':     pfill_10,
                'ci10':         [ci10_lo, ci10_hi],
                'pfill_100':    pfill_100,
                'ci100':        [ci100_lo, ci100_hi],
                'mean_edge':    mean_edge,
                'mean_pnl_10':  mean_pnl_k.get(10,  float('nan')),
                'mean_pnl_50':  mean_pnl_k.get(50,  float('nan')),
                'mean_pnl_200': mean_pnl_k.get(200, float('nan')),
            }

        results[N] = row

    return {
        'day':          day,
        'n_non_eod':    n_non_eod,
        'sanity_check': {
            'cf_bid':   int(cf_bid),
            'cf_ask':   int(cf_ask),
            'cf_total': int(cf_total),
            'a3_count': int(a3_count),
            'pct_diff': float(pct_diff),
            'pass':     bool(sanity_pass),
        },
        'offsets': results,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_table(day_result):
    day = day_result['day']
    print(f"\n{'='*105}")
    print(f"Day {day} — Fill Probability & Expected PnL by Offset (size=1, from best_bid/ask)")
    print(f"{'='*105}")

    sc = day_result['sanity_check']
    flag = '' if sc['pass'] else '  <-- FAIL'
    print(f"Sanity (fv-quote CF): total={sc['cf_total']} vs A3={sc['a3_count']} "
          f"delta={sc['pct_diff']:+.1f}%{flag}")
    print()

    hdr = (f"{'N':>3}  {'Side':>4}  {'N_fills':>7}  "
           f"{'P(fill@10)':>10}  {'P(fill@100)':>11}  "
           f"{'E[edge]':>8}  {'E[PnL@10]':>10}  "
           f"{'E[PnL@50]':>10}  {'E[PnL@200]':>11}  "
           f"{'CI10 (95%)':>20}")
    print(hdr)
    print('-' * len(hdr))

    for N in OFFSETS:
        for side in ['bid', 'ask']:
            r  = day_result['offsets'][N][side]
            ci10 = f"[{r['ci10'][0]:.3f},{r['ci10'][1]:.3f}]"
            lf = '*' if r['n_fills'] < 100 else ' '
            print(f"{N:>3}  {side:>4}  {r['n_fills']:>7}{lf}"
                  f"  {r['pfill_10']:>10.4f}  {r['pfill_100']:>11.4f}"
                  f"  {r['mean_edge']:>8.2f}  {r['mean_pnl_10']:>10.2f}"
                  f"  {r['mean_pnl_50']:>10.2f}  {r['mean_pnl_200']:>11.2f}"
                  f"  {ci10:>20}")


def find_optimal_offset(day_result):
    best_n = None
    best_pnl = -np.inf
    for N in OFFSETS:
        bp = day_result['offsets'][N]['bid']['mean_pnl_50']
        ap = day_result['offsets'][N]['ask']['mean_pnl_50']
        if math.isnan(bp) or math.isnan(ap):
            continue
        avg = (bp + ap) / 2
        if avg > best_pnl:
            best_pnl = avg
            best_n   = N
    return best_n, best_pnl


# ---------------------------------------------------------------------------
# Plot: E[PnL/fill @K=50] vs offset
# ---------------------------------------------------------------------------

def plot_pnl_vs_offset(all_results):
    fig, axes = plt.subplots(1, 3, figsize=(18, 6), sharey=False)
    colors = {'bid': 'steelblue', 'ask': 'darkorange', 'avg': 'black'}

    for col_idx, dr in enumerate(all_results):
        ax  = axes[col_idx]
        day = dr['day']

        bid_pnls, ask_pnls, avg_pnls = [], [], []
        for N in OFFSETS:
            bp = dr['offsets'][N]['bid']['mean_pnl_50']
            ap = dr['offsets'][N]['ask']['mean_pnl_50']
            bid_pnls.append(bp)
            ask_pnls.append(ap)
            avg_pnls.append((bp + ap) / 2 if not (math.isnan(bp) or math.isnan(ap)) else float('nan'))

        ax.plot(OFFSETS, bid_pnls, 'o-', color=colors['bid'], label='bid side', linewidth=2)
        ax.plot(OFFSETS, ask_pnls, 's-', color=colors['ask'], label='ask side', linewidth=2)
        ax.plot(OFFSETS, avg_pnls, '^--', color=colors['avg'], label='avg', linewidth=2.5, alpha=0.9)

        ax.axvline(2, color='red', linestyle=':', alpha=0.7, label='v8 N=2 (from FV, not best_bid)')
        opt_n, opt_pnl = find_optimal_offset(dr)
        ax.axvline(opt_n, color='green', linestyle='--', alpha=0.7, label=f'optimal N={opt_n}')

        ax.set_title(f'Day {day}', fontsize=12)
        ax.set_xlabel('Offset N (ticks from best bid / best ask)')
        ax.set_ylabel('E[PnL/fill @ K=50 ticks] (XIREC)')
        ax.legend(fontsize=9)
        ax.set_xticks(OFFSETS)
        ax.grid(True, alpha=0.3)

    plt.suptitle('ACO: E[PnL/fill @K=50] vs Passive Offset from best_bid/ask (size=1)',
                 fontsize=12, y=1.02)
    plt.tight_layout()
    plot_path = os.path.join(PLOT_DIR, 'pnl_vs_offset.png')
    plt.savefig(plot_path, dpi=130, bbox_inches='tight')
    print(f"\nPlot saved: {plot_path}")
    plt.close()
    return plot_path


# ---------------------------------------------------------------------------
# JSON serialization helper
# ---------------------------------------------------------------------------

def to_serializable(obj):
    if isinstance(obj, dict):
        return {k: to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [to_serializable(v) for v in obj]
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, float) and math.isnan(obj):
        return None
    else:
        return obj


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    all_results = []
    for day in DAYS:
        dr = analyze_day(day)
        print_table(dr)
        all_results.append(dr)

    # Optimal offset per day
    print("\n" + "="*65)
    print("OPTIMAL OFFSET SUMMARY (E[PnL/fill @K=50], bid+ask avg)")
    print("="*65)
    opt_by_day = {}
    for dr in all_results:
        day = dr['day']
        best_n, best_pnl = find_optimal_offset(dr)
        opt_by_day[day] = (best_n, best_pnl)
        v2_n2_pnl = (dr['offsets'][2]['bid']['mean_pnl_50'] +
                     dr['offsets'][2]['ask']['mean_pnl_50']) / 2
        match = '' if best_n == 2 else f'  <- differs from v8 concept (v8 N=2 @FV, not best_bid)'
        print(f"  Day {day:>3}: optimal N={best_n} (E[PnL@50]={best_pnl:.2f}) | "
              f"v8-equiv N=2 from best_bid: E[PnL@50]={v2_n2_pnl:.2f}{match}")

    opt_ns = [n for n, _ in opt_by_day.values()]
    if max(opt_ns) - min(opt_ns) > 1:
        print("\n  FLAG: optimal N differs by >1 across days -> REGIME-DEPENDENT")
    else:
        consensus = int(np.median(opt_ns))
        print(f"\n  Consensus optimal N={consensus} (range {min(opt_ns)}-{max(opt_ns)})")

    # Headline table
    print("\n" + "="*70)
    print("HEADLINE TABLE: E[PnL/fill @K=50] for N in {1,2,3,4,5}")
    print("(N = offset from best_bid / best_ask; size=1)")
    print("="*70)
    hdr_ns = [1, 2, 3, 4, 5]
    print(f"{'Day':>5} {'Side':>5} " + " ".join(f"{'N='+str(n):>10}" for n in hdr_ns))
    print("-" * 70)
    for dr in all_results:
        for side in ['bid', 'ask', 'avg']:
            row_vals = []
            for N in hdr_ns:
                if side == 'avg':
                    bp = dr['offsets'][N]['bid']['mean_pnl_50']
                    ap = dr['offsets'][N]['ask']['mean_pnl_50']
                    v = (bp + ap) / 2 if not (math.isnan(bp) or math.isnan(ap)) else float('nan')
                else:
                    v = dr['offsets'][N][side]['mean_pnl_50']
                row_vals.append(v)
            print(f"{dr['day']:>5} {side:>5} " + " ".join(f"{v:>10.2f}" for v in row_vals))

    plot_path = plot_pnl_vs_offset(all_results)

    # Save JSON
    out = {}
    for dr in all_results:
        day = dr['day']
        out[str(day)] = {
            'n_non_eod':    int(dr['n_non_eod']),
            'sanity_check': dr['sanity_check'],
            'offsets':      {}
        }
        for N in OFFSETS:
            out[str(day)]['offsets'][str(N)] = to_serializable(dr['offsets'][N])

    out_path = os.path.join(BASE, 'aco_fill_prob_results.json')
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\nResults saved: {out_path}")
