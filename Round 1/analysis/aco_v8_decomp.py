"""
aco_v8_decomp.py — A3: v8 ACO Replay and PnL Decomposition Module
===================================================================

Reusable tagging module for A4, A5, A7, A8.

Given a prosperity4btest log for v8, produces:
  1. Tagged fill records (timestamp, price, signed_qty, side, our_role, mid_at_fill)
  2. PnL attribution across four mutually-exclusive buckets that sum to GT PnL:
       spread_capture    : (mid_at_fill - price) * signed_qty for passive fills (ts <= EOD_START)
       reversion_capture : (mid_at_fill - price) * signed_qty for aggressive fills (ts <= EOD_START)
       inventory_carry   : final_pos * final_mid - sum(mid_at_fill_i * signed_qty_i)
       eod_flatten       : (mid_at_fill - price) * signed_qty for any fill at ts > 950000
  3. Adverse-selection metrics at K in {10, 50, 200} ticks (informational, not in total):
       adv_sel@K : (mid_{t+K} - fill_price) * signed_qty per fill, summed across all fills

Accounting identity (verified, zero residual):
  Total PnL = cash_flow + final_pos * final_mid
            = sum((mid_i - price_i) * dq_i) + (final_pos * final_mid - sum(mid_i * dq_i))
            = spread_capture + reversion_capture + eod_flatten + inventory_carry

Passive/Aggressive classification convention (documented for A4/A5 consumers):
  buyer='SUBMISSION' + fill_price >= ask1_at_tick  -> AGGRESSIVE buy (aco_take crossed ask)
  buyer='SUBMISSION' + fill_price <  ask1_at_tick  -> PASSIVE buy (aco_make bid got hit)
  seller='SUBMISSION' + fill_price <= bid1_at_tick -> AGGRESSIVE sell (aco_take crossed bid)
  seller='SUBMISSION' + fill_price >  bid1_at_tick -> PASSIVE sell (aco_make ask got lifted)
  buyer='', seller='' -> bot-to-bot, excluded

mid_at_fill is mmbot_mid (volume >= 15 filter, per A2 recommendation). Falls back to
naive mid if mmbot_mid is unavailable at the fill timestamp.

Usage (standalone):
    cd "Round 1/analysis/"
    python3 aco_v8_decomp.py

Usage (importable):
    from aco_v8_decomp import run_decomposition, parse_log_activities, classify_our_fills
    res = run_decomposition(day=-2, log_path="runs/v8_day-2.log")
    # res['fills_df']    : tagged fills DataFrame
    # res['attribution'] : dict with bucket PnL values
    # res['adverse_sel'] : dict K -> summed adv_sel
    # res['validation']  : {'gt_pnl', 'modeled_pnl', 'residual', 'passed'}

Dependencies: numpy, pandas, matplotlib (all standard in the project environment).
"""

import os
import re
import json
import math
import warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
BASE      = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE, "..", "r1_data_capsule")
LOG_DIR   = os.path.join(BASE, "..", "..", "runs")
PLOT_DIR  = os.path.join(BASE, "plots")
OUT_JSON  = os.path.join(BASE, "aco_decomp_results.json")
os.makedirs(PLOT_DIR, exist_ok=True)

DAYS       = [-2, -1, 0]
EOD_START  = 950_000
LIMIT      = 80

# Ground-truth ACO PnL from prosperity4btest (v8_backtest_results.md §2, verified per-day)
V8_ACO_PNL_GT = {-2: 6335.0, -1: 6972.0, 0: 5249.0}

# ---------------------------------------------------------------------------
# ACO_CFG — verbatim from trader-v8-173159.py
# A4/A5 can import this directly; do NOT edit
# ---------------------------------------------------------------------------
ACO_CFG = {
    "ema_alpha":       0.12,
    "quote_offset":    2,
    "take_edge":       3,
    "max_skew":        5,
    "panic_threshold": 0.75,
}


# ---------------------------------------------------------------------------
# v8 ACO logic — ported verbatim from trader-v8-173159.py
# (A4 counterfactual engine reuses these)
# ---------------------------------------------------------------------------

def aco_fv_update(mid: float, prev_fv: float,
                  alpha: float = ACO_CFG["ema_alpha"]) -> float:
    """
    EMA fair-value update used by v8 ACO.
    Defined: fv_t = alpha * mid_t + (1 - alpha) * fv_{t-1}
    alpha = 0.12 means the EMA decays ~95% in ~25 ticks.
    """
    return alpha * mid + (1.0 - alpha) * prev_fv


def aco_take_orders(fv: float, pos: int,
                    depth_bids: dict, depth_asks: dict,
                    limit: int = LIMIT,
                    edge: float = ACO_CFG["take_edge"]):
    """
    Port of aco_take() from trader-v8-173159.py.

    Takes liquidity aggressively when:
      - best_ask <= fv - edge  (and pos >= 0, so threshold tightens)
      - best_bid >= fv + edge  (and pos <= 0)

    Returns (list of (price, signed_qty), new_pos).
    Signed_qty: positive = buy, negative = sell.
    """
    orders = []
    pos2   = pos
    for ap in sorted(depth_asks.keys()):
        threshold = fv - edge if pos2 >= 0 else fv
        if ap > threshold:
            break
        room = limit - pos2
        if room <= 0:
            break
        qty = min(-depth_asks[ap], room)
        orders.append((ap, qty))
        pos2 += qty
    for bp in sorted(depth_bids.keys(), reverse=True):
        threshold = fv + edge if pos2 <= 0 else fv
        if bp < threshold:
            break
        room = limit + pos2
        if room <= 0:
            break
        qty = min(depth_bids[bp], room)
        orders.append((bp, -qty))
        pos2 -= qty
    return orders, pos2


def aco_make_orders(fv: float, pos: int,
                    limit: int = LIMIT,
                    cfg: dict = ACO_CFG,
                    urgency: float = 0.0):
    """
    Port of aco_make() from trader-v8-173159.py.

    Posts passive limit orders with inventory skew:
      bid_px = floor(fv) - offset - skew
      ask_px = ceil(fv) + offset - skew
    where skew = round(inv_ratio * max_skew), inv_ratio = pos / limit.

    Returns list of (price, signed_qty).
    """
    offset    = cfg["quote_offset"]
    max_skew  = cfg["max_skew"]
    panic_thr = cfg["panic_threshold"]
    inv_ratio = pos / limit
    skew      = round(inv_ratio * max_skew)
    panic_extra = 0
    if abs(inv_ratio) >= panic_thr:
        panic_extra = round((abs(inv_ratio) - panic_thr) / (1.0 - panic_thr) * 3)
    if urgency > 0 and abs(pos) > 0:
        offset = max(0, offset - round(urgency * offset))
        skew   = round(inv_ratio * (max_skew + urgency * 4))
    bid_px = math.floor(fv) - offset - skew
    ask_px = math.ceil(fv)  + offset - skew
    if pos > 0 and panic_extra > 0:
        ask_px -= panic_extra
    elif pos < 0 and panic_extra > 0:
        bid_px += panic_extra
    if urgency > 0.5 or abs(inv_ratio) >= panic_thr:
        bid_px = min(bid_px, math.floor(fv))
        ask_px = max(ask_px, math.ceil(fv))
    else:
        bid_px = min(bid_px, math.floor(fv) - 1)
        ask_px = max(ask_px, math.ceil(fv) + 1)
    if ask_px <= bid_px:
        ask_px = bid_px + 1
    buy_qty  = limit - pos
    sell_qty = limit + pos
    orders = []
    if buy_qty  > 0 and bid_px > 0:
        orders.append((bid_px,  buy_qty))
    if sell_qty > 0 and ask_px > 0:
        orders.append((ask_px, -sell_qty))
    return orders


def eod_urgency(timestamp: int,
                eod_start: int = EOD_START,
                ts_max:    int = 999_900) -> float:
    if timestamp < eod_start:
        return 0.0
    return min(1.0, (timestamp - eod_start) / (ts_max - eod_start))


# ---------------------------------------------------------------------------
# Fair-value proxy: mmbot_mid (A2's recommended proxy)
# ---------------------------------------------------------------------------

def mmbot_mid_from_levels(bid1, bv1, bid2, bv2, bid3, bv3,
                           ask1, av1, ask2, av2, ask3, av3,
                           vol_threshold: int = 15) -> float:
    """
    A2's recommended fair-value proxy.
    Filters order-book levels to those with volume >= vol_threshold (default 15),
    then returns midpoint of best filtered bid and best filtered ask.
    Falls back to all available levels if no level passes the threshold.

    vol_threshold=15 sits above p50 L1 volume (13) and below L2/L3 mean (24-25),
    so it naturally selects deeper, more stable quote layers.
    """
    def best_levels(levels):
        filt = [(p, v) for p, v in levels
                if not math.isnan(p) and not math.isnan(v) and v >= vol_threshold]
        if not filt:
            filt = [(p, v) for p, v in levels
                    if not math.isnan(p) and not math.isnan(v)]
        return filt

    bids = best_levels([(bid1, bv1), (bid2, bv2), (bid3, bv3)])
    asks = best_levels([(ask1, av1), (ask2, av2), (ask3, av3)])
    if not bids or not asks:
        return float('nan')
    return (max(p for p, _ in bids) + min(p for p, _ in asks)) / 2.0


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

def _flt(x) -> float:
    try:
        v = str(x).strip()
        return float(v) if v else float('nan')
    except Exception:
        return float('nan')


def parse_log_trade_history(log_path: str,
                            symbol: str = "ASH_COATED_OSMIUM") -> pd.DataFrame:
    """
    Parse the Trade History section of a prosperity4btest log.
    Returns DataFrame: timestamp, buyer, seller, price, quantity.
    Only returns rows where symbol matches.
    """
    with open(log_path) as f:
        content = f.read()
    th_start = content.index("Trade History:")
    th_text  = content[th_start:]

    entries = []
    pattern = re.compile(r'\{[^}]+\}', re.DOTALL)
    for m in pattern.finditer(th_text):
        blob = re.sub(r',\s*\}', '}', m.group(0))
        try:
            d = json.loads(blob)
            if d.get('symbol') == symbol:
                entries.append({
                    'timestamp': int(d.get('timestamp', 0)),
                    'buyer':     str(d.get('buyer', '')),
                    'seller':    str(d.get('seller', '')),
                    'price':     float(d.get('price', 0)),
                    'quantity':  int(d.get('quantity', 0)),
                })
        except Exception:
            pass
    return (pd.DataFrame(entries)
            .sort_values('timestamp')
            .reset_index(drop=True))


def parse_log_activities(log_path: str,
                         symbol: str = "ASH_COATED_OSMIUM") -> pd.DataFrame:
    """
    Parse the Activities log section of a prosperity4btest log.
    Returns DataFrame with columns:
      day, timestamp, bid1-3, bv1-3, ask1-3, av1-3, mid, pnl
    Filtered to `symbol` rows, sorted by timestamp.
    """
    with open(log_path) as f:
        content = f.read()
    lines = content.split('\n')
    act_idx = next(i for i, l in enumerate(lines) if 'Activities log:' in l)
    rows = []
    for l in lines[act_idx + 2:]:
        if 'Trade History:' in l:
            break
        parts = l.split(';')
        if len(parts) < 16 or parts[2] != symbol:
            continue
        try:
            rows.append({
                'day':       int(parts[0]),
                'timestamp': int(parts[1]),
                'bid1': _flt(parts[3]),  'bv1': _flt(parts[4]),
                'bid2': _flt(parts[5]),  'bv2': _flt(parts[6]),
                'bid3': _flt(parts[7]),  'bv3': _flt(parts[8]),
                'ask1': _flt(parts[9]),  'av1': _flt(parts[10]),
                'ask2': _flt(parts[11]), 'av2': _flt(parts[12]),
                'ask3': _flt(parts[13]), 'av3': _flt(parts[14]),
                'mid':  _flt(parts[15]),
                'pnl':  _flt(parts[16]) if len(parts) > 16 else float('nan'),
            })
        except Exception:
            pass
    return (pd.DataFrame(rows)
            .sort_values('timestamp')
            .reset_index(drop=True))


def _build_mmbot_series(act_df: pd.DataFrame) -> dict:
    """Build timestamp -> mmbot_mid mapping from activities DataFrame."""
    result = {}
    for _, r in act_df.iterrows():
        m = mmbot_mid_from_levels(
            r['bid1'], r['bv1'], r['bid2'], r['bv2'], r['bid3'], r['bv3'],
            r['ask1'], r['av1'], r['ask2'], r['av2'], r['ask3'], r['av3'],
        )
        result[int(r['timestamp'])] = m
    return result


# ---------------------------------------------------------------------------
# Passive/Aggressive classification
# ---------------------------------------------------------------------------

def classify_our_fills(th_df: pd.DataFrame,
                       act_df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter Trade History to SUBMISSION-involved fills, classify each as
    passive or aggressive, and return a tagged DataFrame.

    Passive/Aggressive convention:
    -----------------------------------------------------------------------
    buyer='SUBMISSION', seller='' — WE bought:
      fill_price >= ask1_at_tick  -> AGGRESSIVE (aco_take crossed the ask)
      fill_price <  ask1_at_tick  -> PASSIVE    (aco_make bid got hit)

    seller='SUBMISSION', buyer='' — WE sold:
      fill_price <= bid1_at_tick  -> AGGRESSIVE (aco_take crossed the bid)
      fill_price >  bid1_at_tick  -> PASSIVE    (aco_make ask was lifted)

    buyer='', seller='' — bot-to-bot, excluded.
    -----------------------------------------------------------------------

    Returns DataFrame with columns:
      timestamp, price, qty (always positive), side ('buy'/'sell'),
      our_role ('passive'/'aggressive'), signed_qty (+qty for buy, -qty for sell),
      ask1_at_fill, bid1_at_fill
    """
    # Timestamp -> book snapshot
    book = (act_df.drop_duplicates('timestamp')
                  .set_index('timestamp'))

    def get_snap(ts):
        if ts in book.index:
            return book.loc[ts]
        prior = book.index[book.index <= ts]
        return book.loc[prior[-1]] if len(prior) > 0 else None

    records = []
    for _, t in th_df.iterrows():
        buyer  = str(t.get('buyer', ''))
        seller = str(t.get('seller', ''))
        if buyer != 'SUBMISSION' and seller != 'SUBMISSION':
            continue
        ts    = int(t['timestamp'])
        price = float(t['price'])
        qty   = int(t['quantity'])
        snap  = get_snap(ts)
        ask1  = float(snap['ask1']) if snap is not None else float('nan')
        bid1  = float(snap['bid1']) if snap is not None else float('nan')

        if buyer == 'SUBMISSION':
            side = 'buy'
            role = ('aggressive'
                    if not math.isnan(ask1) and price >= ask1
                    else 'passive')
            signed_qty = qty
        else:
            side = 'sell'
            role = ('aggressive'
                    if not math.isnan(bid1) and price <= bid1
                    else 'passive')
            signed_qty = -qty

        records.append({
            'timestamp':    ts,
            'price':        price,
            'qty':          qty,
            'side':         side,
            'our_role':     role,
            'signed_qty':   signed_qty,
            'ask1_at_fill': ask1,
            'bid1_at_fill': bid1,
        })
    return (pd.DataFrame(records)
            .sort_values('timestamp')
            .reset_index(drop=True))


# ---------------------------------------------------------------------------
# PnL Attribution
# ---------------------------------------------------------------------------

def attribute_pnl(fills_df: pd.DataFrame,
                  act_df:   pd.DataFrame,
                  adverse_ks: tuple = (10, 50, 200)) -> dict:
    """
    Walk fills in timestamp order and compute PnL attribution.

    Decomposition (accounting identity, zero residual guaranteed):
    ---------------------------------------------------------------
    Total PnL = cash_flow + final_pos * final_mid
              = Σ (mid_i - price_i) * dq_i                [fill edges]
                + (final_pos * final_mid - Σ mid_i * dq_i) [inventory carry]

    Where mid_i = mmbot_mid at fill timestamp (falls back to naive mid).

    Buckets:
      spread_capture    : fill_edge for passive fills at ts <= EOD_START
      reversion_capture : fill_edge for aggressive fills at ts <= EOD_START
      eod_flatten       : fill_edge for any fill at ts > EOD_START
      inventory_carry   : final_pos * final_mid - Σ mid_i * dq_i

    Adverse selection (informational only, NOT in total):
      adv_sel@K = Σ (mid_{t+K} - price_i) * dq_i
      Sign: positive = market moved in our favor K ticks after fill
                       (NOT adversely selected — we sold at a local high/bought at low)
            negative = market moved against us (adversely selected)

    Parameters
    ----------
    fills_df   : DataFrame from classify_our_fills()
    act_df     : DataFrame from parse_log_activities()
    adverse_ks : tuple of K values for adverse selection horizons

    Returns
    -------
    dict with keys:
      spread_capture, reversion_capture, inventory_carry, eod_flatten,
      total_modeled, adverse_by_k (dict K -> float), adverse_df (DataFrame)
    """
    act_clean = (act_df.dropna(subset=['mid'])
                       .drop_duplicates('timestamp')
                       .sort_values('timestamp')
                       .reset_index(drop=True))
    ts_arr   = act_clean['timestamp'].values.astype(int)
    mid_arr  = act_clean['mid'].values.astype(float)
    ts_to_idx = {int(ts): i for i, ts in enumerate(ts_arr)}
    mmbot_map = _build_mmbot_series(act_clean)

    final_mid = float(mid_arr[-1])

    spread_capture    = 0.0
    reversion_capture = 0.0
    eod_flatten       = 0.0
    sum_mid_dq        = 0.0
    final_pos         = 0

    adv_records = []

    for _, fill in fills_df.iterrows():
        ts         = int(fill['timestamp'])
        price      = float(fill['price'])
        signed_qty = int(fill['signed_qty'])
        role       = str(fill['our_role'])

        # mid at fill: prefer mmbot_mid, fall back to naive mid
        m = mmbot_map.get(ts, float('nan'))
        if math.isnan(m):
            idx = ts_to_idx.get(ts)
            m = float(mid_arr[idx]) if idx is not None else float('nan')

        fill_edge  = (m - price) * signed_qty
        sum_mid_dq += m * signed_qty
        final_pos  += signed_qty

        if ts > EOD_START:
            eod_flatten += fill_edge
        elif role == 'passive':
            spread_capture += fill_edge
        else:
            reversion_capture += fill_edge

        # Adverse selection at K ticks ahead
        fill_idx = ts_to_idx.get(ts)
        for K in adverse_ks:
            if fill_idx is not None and fill_idx + K < len(mid_arr):
                adv = (float(mid_arr[fill_idx + K]) - price) * signed_qty
            else:
                adv = float('nan')
            adv_records.append({
                'timestamp':  ts,
                'K':          K,
                'fill_price': price,
                'signed_qty': signed_qty,
                'our_role':   role,
                'adv_sel':    adv,
            })

    inventory_carry = final_pos * final_mid - sum_mid_dq
    total_modeled   = (spread_capture + reversion_capture
                       + eod_flatten + inventory_carry)

    adverse_df = pd.DataFrame(adv_records)
    adverse_by_k = {
        K: float(adverse_df[adverse_df['K'] == K]['adv_sel'].dropna().sum())
        for K in adverse_ks
    }

    return {
        'spread_capture':    spread_capture,
        'reversion_capture': reversion_capture,
        'inventory_carry':   inventory_carry,
        'eod_flatten':       eod_flatten,
        'total_modeled':     total_modeled,
        'adverse_by_k':      adverse_by_k,
        'adverse_df':        adverse_df,
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_decomposition(day: int,
                      log_path: str,
                      gt_pnl: float = None,
                      tol: float = 0.5) -> dict:
    """
    Full decomposition pipeline for one day.

    Parameters
    ----------
    day      : int, day index (e.g. -2)
    log_path : str, path to prosperity4btest log
    gt_pnl   : float, ground-truth ACO PnL for validation gate
    tol      : float, tolerance for validation (default 0.5 XIREC)

    Returns
    -------
    dict:
      fills_df    : tagged fills DataFrame
      attribution : bucket PnL dict
      adverse_sel : K -> summed adv_sel
      validation  : {gt_pnl, modeled_pnl, residual, passed}
    """
    print(f"\n=== Day {day} ===")
    act_df   = parse_log_activities(log_path)
    th_df    = parse_log_trade_history(log_path)
    fills_df = classify_our_fills(th_df, act_df)

    n_sub = len(th_df[(th_df['buyer'] == 'SUBMISSION') |
                       (th_df['seller'] == 'SUBMISSION')])
    n_pas = int((fills_df['our_role'] == 'passive').sum())
    n_agg = int((fills_df['our_role'] == 'aggressive').sum())
    print(f"  Activity rows: {len(act_df)}  |  Trade History (all): {len(th_df)}")
    print(f"  Our ACO fills: {n_sub}  |  Passive: {n_pas}, Aggressive: {n_agg}")

    attr = attribute_pnl(fills_df, act_df)
    result = {
        'day':        day,
        'fills_df':   fills_df,
        'attribution': attr,
        'adverse_sel': attr['adverse_by_k'],
    }

    if gt_pnl is not None:
        residual = attr['total_modeled'] - gt_pnl
        passed   = abs(residual) <= tol
        result['validation'] = {
            'gt_pnl':      gt_pnl,
            'modeled_pnl': attr['total_modeled'],
            'residual':    residual,
            'passed':      bool(passed),
        }
        status = "PASS" if passed else f"FAIL (residual={residual:.4f})"
        print(f"  Buckets: spread={attr['spread_capture']:.1f} | "
              f"rev={attr['reversion_capture']:.1f} | "
              f"carry={attr['inventory_carry']:.1f} | "
              f"eod={attr['eod_flatten']:.1f}")
        print(f"  Validation: modeled={attr['total_modeled']:.1f}, "
              f"gt={gt_pnl:.1f}, residual={residual:.4f} → {status}")
    return result


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_cumulative_buckets(day: int,
                             fills_df: pd.DataFrame,
                             act_df:   pd.DataFrame,
                             save_path: str = None):
    """
    Plot cumulative PnL by bucket over time for one day.
    One line per bucket + total. EOD window marked with vertical line.
    """
    act_clean = (act_df.dropna(subset=['mid'])
                       .drop_duplicates('timestamp')
                       .sort_values('timestamp')
                       .reset_index(drop=True))
    ts_arr   = act_clean['timestamp'].values.astype(int)
    mid_arr  = act_clean['mid'].values.astype(float)
    mmbot_map = _build_mmbot_series(act_clean)

    final_mid = float(mid_arr[-1])
    fills_by_ts: dict = {}
    for _, row in fills_df.iterrows():
        fills_by_ts.setdefault(int(row['timestamp']), []).append(row)

    # Running state
    r_spread = r_rev = r_eod = r_carry = 0.0
    sum_mid_dq = 0.0
    final_pos  = 0

    # Pre-compute running inventory carry incrementally:
    # inventory_carry_up_to_t = final_pos_t * mid_t - sum_mid_dq_t
    # But "final_pos" changes at fills, so we track cumulative
    ts_plot    = []
    c_spread   = []
    c_rev      = []
    c_eod      = []
    c_carry    = []

    for ts, mid in zip(ts_arr, mid_arr):
        # Update fill edges first
        for fill in fills_by_ts.get(ts, []):
            dq    = int(fill['signed_qty'])
            price = float(fill['price'])
            m     = mmbot_map.get(ts, float('nan'))
            if math.isnan(m):
                m = mid
            fe = (m - price) * dq
            sum_mid_dq += m * dq
            final_pos  += dq
            if ts > EOD_START:
                r_eod += fe
            elif fill['our_role'] == 'passive':
                r_spread += fe
            else:
                r_rev += fe

        # Carry: snapshot at every tick
        r_carry = final_pos * mid - sum_mid_dq

        ts_plot.append(ts)
        c_spread.append(r_spread)
        c_rev.append(r_rev)
        c_eod.append(r_eod)
        c_carry.append(r_carry)

    c_total = [s + rv + e + c for s, rv, e, c in
               zip(c_spread, c_rev, c_eod, c_carry)]

    fig, ax = plt.subplots(figsize=(14, 6))
    colors  = {'spread': 'steelblue', 'rev': 'darkorange',
               'carry':  'green',     'eod': 'crimson', 'total': 'black'}
    labels  = {'spread': 'Spread capture (passive)',
               'rev':    'Reversion capture (aggressive)',
               'carry':  'Inventory carry',
               'eod':    'EOD flatten',
               'total':  'Total (modeled)'}
    for k, arr in [('spread', c_spread), ('rev', c_rev),
                   ('carry', c_carry),   ('eod', c_eod), ('total', c_total)]:
        ax.plot(ts_plot, arr,
                color=colors[k], label=labels[k],
                linewidth=2.5 if k == 'total' else 1.5,
                linestyle='--' if k == 'total' else '-',
                alpha=0.9 if k == 'total' else 0.8)

    ax.axvline(EOD_START, color='gray', linestyle=':', alpha=0.7,
               label='EOD start (ts=950000)')
    ax.set_xlabel('Timestamp')
    ax.set_ylabel('Cumulative PnL (XIREC)')
    ax.set_title(f'ACO v8 PnL Attribution — Day {day}')
    ax.legend(fontsize=9)
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, _: f'{x:,.0f}'))
    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=120)
        plt.close(fig)
        print(f"  Saved: {save_path}")
    else:
        plt.show()
    return fig


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    LOG_PATHS = {
        -2: os.path.join(LOG_DIR, "v8_day-2.log"),
        -1: os.path.join(LOG_DIR, "v8_day-1.log"),
         0: os.path.join(LOG_DIR, "v8_day0.log"),
    }

    all_results = {}
    for day in DAYS:
        log_path = LOG_PATHS[day]
        if not os.path.exists(log_path):
            print(f"ERROR: missing log {log_path}")
            continue
        res = run_decomposition(day, log_path,
                                gt_pnl=V8_ACO_PNL_GT[day])
        all_results[day] = res

        plot_path = os.path.join(PLOT_DIR, f"aco_decomp_day{day}.png")
        plot_cumulative_buckets(
            day, res['fills_df'],
            parse_log_activities(log_path),
            save_path=plot_path)

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("ACO v8 PnL Decomposition — Per-Day and Merged")
    print("=" * 72)
    print(f"{'Bucket':<28} {'Day -2':>9} {'Day -1':>9} {'Day 0':>9} {'Merged':>9}")
    print("-" * 72)

    bucket_keys = ['spread_capture', 'reversion_capture',
                   'inventory_carry', 'eod_flatten']
    bucket_lbls = ['Spread capture (passive)',
                   'Reversion capture (aggr)',
                   'Inventory carry',
                   'EOD flatten']
    merged_vals = {}
    day_attr    = {d: all_results[d]['attribution'] for d in all_results}

    for k, lbl in zip(bucket_keys, bucket_lbls):
        vals = [day_attr.get(d, {}).get(k, float('nan')) for d in DAYS]
        merged = sum(v for v in vals if not math.isnan(v))
        merged_vals[k] = merged
        print(f"{lbl:<28} " +
              " ".join(f"{v:>9.1f}" for v in vals) +
              f" {merged:>9.1f}")

    print("-" * 72)
    totals = [day_attr.get(d, {}).get('total_modeled', float('nan')) for d in DAYS]
    gt_vals = [V8_ACO_PNL_GT.get(d, float('nan'))  for d in DAYS]
    residuals = [(day_attr.get(d, {}).get('total_modeled', 0) - V8_ACO_PNL_GT.get(d, 0))
                 for d in DAYS]
    merged_total    = sum(v for v in totals    if not math.isnan(v))
    merged_gt       = sum(v for v in gt_vals   if not math.isnan(v))
    merged_residual = sum(residuals)
    print(f"{'Total (modeled)':<28} " +
          " ".join(f"{v:>9.1f}" for v in totals) +
          f" {merged_total:>9.1f}")
    print(f"{'GT (prosperity4btest)':<28} " +
          " ".join(f"{v:>9.1f}" for v in gt_vals) +
          f" {merged_gt:>9.1f}")
    print(f"{'Residual':<28} " +
          " ".join(f"{v:>9.4f}" for v in residuals) +
          f" {merged_residual:>9.4f}")

    print("\n" + "=" * 72)
    print("Adverse Selection (informational only — NOT added to total)")
    print("Sign: positive = market moved in our favor; negative = adverse selection")
    print("-" * 55)
    print(f"{'Horizon':<12} {'Day -2':>9} {'Day -1':>9} {'Day 0':>9} {'Merged':>9}")
    for K in [10, 50, 200]:
        vals = [all_results.get(d, {}).get('adverse_sel', {}).get(K, float('nan'))
                for d in DAYS]
        merged = sum(v for v in vals if not math.isnan(v))
        print(f"adv_sel@{K:<4} " +
              " ".join(f"{v:>9.1f}" for v in vals) +
              f" {merged:>9.1f}")

    sc_merged  = merged_vals.get('spread_capture', 1.0)
    adv50_merged = sum(all_results.get(d, {}).get('adverse_sel', {}).get(50, 0)
                       for d in all_results)
    if sc_merged != 0:
        adv50_pct = adv50_merged / sc_merged * 100
        print(f"\nadv_sel@50 / spread_capture = {adv50_pct:.1f}%")
        print("(>0 = favorable post-fill movement; v8 ACO is NOT adversely selected)")

    # Validation summary
    print("\n" + "=" * 72)
    print("Validation Gate (residual must be < 0.5 XIREC per day)")
    all_pass = True
    for d in DAYS:
        v = all_results.get(d, {}).get('validation', {})
        passed = v.get('passed', False)
        if not passed:
            all_pass = False
        status = "PASS" if passed else "FAIL"
        print(f"  Day {d:>3}: modeled={v.get('modeled_pnl', 0):.1f}  "
              f"gt={v.get('gt_pnl', 0):.1f}  "
              f"residual={v.get('residual', 0):.4f}  → {status}")
    print(f"\n  Overall: {'ALL PASS ✓' if all_pass else 'SOME FAILED ✗'}")

    # Save JSON
    json_out = {}
    for day, res in all_results.items():
        attr = res['attribution']
        v    = res.get('validation', {})
        json_out[str(day)] = {
            'gt_pnl':           V8_ACO_PNL_GT[day],
            'spread_capture':   round(attr['spread_capture'], 4),
            'reversion_capture': round(attr['reversion_capture'], 4),
            'inventory_carry':  round(attr['inventory_carry'], 4),
            'eod_flatten':      round(attr['eod_flatten'], 4),
            'total_modeled':    round(attr['total_modeled'], 4),
            'residual':         round(v.get('residual', float('nan')), 6),
            'validation_pass':  bool(v.get('passed', False)),
            'adverse_sel': {
                str(K): round(val, 4)
                for K, val in attr['adverse_by_k'].items()
            },
            'fill_counts': {
                'passive':    int((res['fills_df']['our_role'] == 'passive').sum()),
                'aggressive': int((res['fills_df']['our_role'] == 'aggressive').sum()),
            },
        }
    with open(OUT_JSON, 'w') as f:
        json.dump(json_out, f, indent=2)
    print(f"\nResults saved: {OUT_JSON}")
    print(f"Plots saved:   {PLOT_DIR}/aco_decomp_day*.png")

    return all_results


if __name__ == "__main__":
    main()
