"""
a2_lhs_search.py — A2: LHS Joint Search for ACO Pass 2.6
=========================================================

Steps:
  1. LHS sampling (seed=42, n=300), dedup after int-casting
  2. Evaluate each combo via A3 tagging-layer replay on cached logs
  3. Rank by worst_of_6
  4. Null-baseline gate + histogram
  5. Prosperity4btest GT confirmation for top 10
  6. Top-3 candidate selection

Run from: Round 1/analysis/
"""

import os, sys, re, json, math, time, shutil, subprocess, warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import qmc, spearmanr

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERE        = os.path.dirname(os.path.abspath(__file__))
ANALYSIS    = os.path.dirname(HERE)         # Round 1/analysis
ROUND1      = os.path.dirname(ANALYSIS)     # Round 1/
REPO        = os.path.dirname(ROUND1)       # repo root

LOG_DIR     = os.path.join(ROUND1, "runs", "pass2_6")
TRADERS_DIR = os.path.join(ROUND1, "traders")
SCRATCH     = HERE
CAND_DIR    = os.path.join(HERE, "a2_candidates")
PLOT_DIR    = os.path.join(ANALYSIS, "plots", "aco_pass2_6")
TEMPLATE    = os.path.join(TRADERS_DIR, "trader-v9-aco-qo5-ms8-te3.py")

os.makedirs(CAND_DIR, exist_ok=True)
os.makedirs(PLOT_DIR, exist_ok=True)

# Add analysis dir to path for imports
if ANALYSIS not in sys.path:
    sys.path.insert(0, ANALYSIS)

from a3_tagging import (
    parse_log_activities,
    parse_log_trade_history,
    classify_our_fills,
    attribute_pnl,
    mmbot_mid_from_levels,
    EOD_START,
    LIMIT,
)

# ---------------------------------------------------------------------------
# Champion baselines (from baselines.json / A0 verified)
# ---------------------------------------------------------------------------
QO5_FULL   = {-2: 9201.0, -1: 10793.0, 0: 9013.0}
QO5_HALF2  = {-2: 4139.0, -1: 5494.0,  0: 4588.0}
QO5_WORST6 = min(list(QO5_FULL.values()) + list(QO5_HALF2.values()))  # 4139

# ---------------------------------------------------------------------------
# Step 1: LHS Sampling
# ---------------------------------------------------------------------------

def step1_lhs_sampling():
    t0 = time.time()
    print("\n" + "="*60)
    print("STEP 1: LHS Sampling")
    print("="*60)

    # Parameter ranges
    # quote_offset: int [2, 8]
    # max_skew:     int [4, 12]
    # take_edge:    float [1.5, 5.0]
    # ema_alpha:    float [0.05, 0.25]
    low  = [2,    4,  1.5, 0.05]
    high = [8,   12,  5.0, 0.25]

    sampler = qmc.LatinHypercube(d=4, scramble=True, seed=42)
    raw = sampler.random(n=300)  # shape (300, 4), values in [0, 1)

    # Scale to ranges
    scaled = qmc.scale(raw, low, high)

    # Cast int params
    scaled[:, 0] = np.round(scaled[:, 0]).astype(int)  # quote_offset
    scaled[:, 1] = np.round(scaled[:, 1]).astype(int)  # max_skew

    # Dedup after casting
    seen = set()
    samples = []
    for row in scaled:
        key = (int(row[0]), int(row[1]), round(float(row[2]), 4), round(float(row[3]), 4))
        if key not in seen:
            seen.add(key)
            samples.append({
                "quote_offset": int(row[0]),
                "max_skew":     int(row[1]),
                "take_edge":    round(float(row[2]), 4),
                "ema_alpha":    round(float(row[3]), 4),
            })

    n_raw = 300
    n_dedup = len(samples)
    elapsed = time.time() - t0

    print(f"  Raw samples:  {n_raw}")
    print(f"  After dedup:  {n_dedup}")
    print(f"  Time:         {elapsed:.2f}s")

    # Save
    out_path = os.path.join(SCRATCH, "a2_lhs_samples.json")
    with open(out_path, "w") as f:
        json.dump({"seed": 42, "n_raw": n_raw, "n_dedup": n_dedup,
                   "samples": samples}, f, indent=2)
    print(f"  Saved: {out_path}")
    return samples, elapsed


# ---------------------------------------------------------------------------
# Tagging-layer replay engine
# ---------------------------------------------------------------------------

def _load_day_data(day: int) -> tuple:
    """Load and parse one day's log. Returns (act_df, th_df)."""
    log_path = os.path.join(LOG_DIR, f"qo5_day{day}.log")
    if not os.path.exists(log_path):
        raise FileNotFoundError(f"Missing log: {log_path}")
    act_df = parse_log_activities(log_path)
    th_df  = parse_log_trade_history(log_path)
    return act_df, th_df


def _replay_aco_cfg(act_df: pd.DataFrame, th_df: pd.DataFrame,
                    cfg: dict, ts_cutoff: int = None) -> float:
    """
    Replay the ACO trading logic against cached trade history using A3 approach.

    The key insight (from A0 decomposition): the fill CLASSIFICATION only
    depends on order-book state, not on which specific trader placed the order.
    The QUANTITY of fills is what's trader-dependent.

    HOWEVER: because we're varying parameters that change the QUOTES (bid/ask
    prices), the passive fills change too. The A3 tagging approach identifies
    fills where we were the counterparty, using SUBMISSION buyer/seller tags.
    Changing ACO_CFG means different quote prices → different fills.

    Limitation: the cached logs are from qo5 runs. We can't simulate what
    different params would fill without fresh backtester runs, since the fill
    history is param-dependent.

    Resolution (matching A3/Pass 2.5 approach): use the qo5 fill history as
    an approximation, reweight by comparing quote distances to identify which
    fills would STILL occur under the candidate params. Specifically:
    - For each passive fill, check if the candidate's quote price would still
      be ≤ fill_price (buy) or ≥ fill_price (sell). If yes, fill occurs.
    - For aggressive fills: check if fill_price satisfies candidate's take_edge
      condition at that timestamp.
    - Recompute PnL using candidate's fill set.

    This is the "tagging replay" approach described in the A2 task spec.
    """
    import math as _math

    # Build book snapshot map from act_df
    act_clean = (act_df.dropna(subset=['bid1', 'ask1'])
                       .drop_duplicates('timestamp')
                       .sort_values('timestamp')
                       .reset_index(drop=True))

    ts_arr  = act_clean['timestamp'].values.astype(int)
    mid_arr = act_clean['mid'].values.astype(float)

    # Build mmbot_mid map and book map
    mmbot_map = {}
    book_map = {}
    for _, r in act_clean.iterrows():
        ts = int(r['timestamp'])
        m = mmbot_mid_from_levels(
            r['bid1'], r['bv1'], r['bid2'], r['bv2'], r['bid3'], r['bv3'],
            r['ask1'], r['av1'], r['ask2'], r['av2'], r['ask3'], r['av3'],
        )
        mmbot_map[ts] = m
        book_map[ts] = r

    ts_to_idx = {int(ts): i for i, ts in enumerate(ts_arr)}

    # Replay EMA fair-value with candidate alpha
    alpha = cfg["ema_alpha"]
    offset = cfg["quote_offset"]
    max_skew = cfg["max_skew"]
    take_edge = cfg["take_edge"]
    panic_thr = cfg.get("panic_threshold", 0.75)

    # Build EMA series
    fv_arr = np.zeros(len(ts_arr))
    fv = float(mid_arr[0]) if len(mid_arr) > 0 else 0.0
    for i, mid in enumerate(mid_arr):
        fv = alpha * mid + (1.0 - alpha) * fv
        fv_arr[i] = fv

    fv_map = {int(ts_arr[i]): fv_arr[i] for i in range(len(ts_arr))}

    # Process fills from trade history
    # Only consider fills up to ts_cutoff (for half2: only ts > 500000)
    # For full_day, ts_cutoff=None
    sub_fills = th_df[(th_df['buyer'] == 'SUBMISSION') |
                      (th_df['seller'] == 'SUBMISSION')].copy()

    if ts_cutoff is not None:
        sub_fills = sub_fills[sub_fills['timestamp'] > ts_cutoff]

    # Simulate which fills would occur under candidate params
    # We replay position + quote logic and check fill feasibility
    pos = 0
    cash = 0.0
    sum_mid_dq = 0.0
    final_mid = float(mid_arr[-1]) if len(mid_arr) > 0 else 0.0

    # Build fill lookup by timestamp
    fills_by_ts = {}
    for _, row in sub_fills.iterrows():
        ts = int(row['timestamp'])
        fills_by_ts.setdefault(ts, []).append(row)

    # Walk through time in order
    pnl_mid_dq = 0.0
    for i, ts in enumerate(ts_arr):
        fv = fv_arr[i]
        mid = mid_arr[i]
        snap = book_map.get(ts)

        inv_ratio = pos / LIMIT if LIMIT != 0 else 0.0
        skew = round(inv_ratio * max_skew)
        panic_extra = 0
        if abs(inv_ratio) >= panic_thr:
            panic_extra = round((abs(inv_ratio) - panic_thr) / (1.0 - panic_thr) * 3)

        urgency = 0.0
        if ts >= 950000:
            urgency = min(1.0, (ts - 950000) / (999900 - 950000))

        if urgency > 0 and abs(pos) > 0:
            eff_offset = max(0, offset - round(urgency * offset))
            eff_skew = round(inv_ratio * (max_skew + urgency * 4))
        else:
            eff_offset = offset
            eff_skew = skew

        bid_px = _math.floor(fv) - eff_offset - eff_skew
        ask_px = _math.ceil(fv) + eff_offset - eff_skew

        if pos > 0 and panic_extra > 0:
            ask_px -= panic_extra
        elif pos < 0 and panic_extra > 0:
            bid_px += panic_extra

        if urgency > 0.5 or abs(inv_ratio) >= panic_thr:
            bid_px = min(bid_px, _math.floor(fv))
            ask_px = max(ask_px, _math.ceil(fv))
        else:
            bid_px = min(bid_px, _math.floor(fv) - 1)
            ask_px = max(ask_px, _math.ceil(fv) + 1)

        if ask_px <= bid_px:
            ask_px = bid_px + 1

        # Check for fills at this timestamp
        for fill_row in fills_by_ts.get(ts, []):
            buyer  = str(fill_row.get('buyer', ''))
            seller = str(fill_row.get('seller', ''))
            price  = float(fill_row['price'])
            qty    = int(fill_row['quantity'])

            if buyer == 'SUBMISSION':
                # We tried to buy
                ask1 = float(snap['ask1']) if snap is not None else float('nan')
                if not _math.isnan(ask1) and price >= ask1:
                    # AGGRESSIVE: check take_edge condition
                    fv_here = fv_map.get(ts, fv)
                    threshold = fv_here - take_edge if pos >= 0 else fv_here
                    if price <= threshold and pos < LIMIT:
                        actual_qty = min(qty, LIMIT - pos)
                        m = mmbot_map.get(ts, mid)
                        if _math.isnan(m): m = mid
                        pnl_mid_dq += (m - price) * actual_qty
                        sum_mid_dq += m * actual_qty
                        pos += actual_qty
                else:
                    # PASSIVE: check if our bid_px >= price (we'd still hit)
                    if bid_px >= price and pos < LIMIT:
                        actual_qty = min(qty, LIMIT - pos)
                        m = mmbot_map.get(ts, mid)
                        if _math.isnan(m): m = mid
                        pnl_mid_dq += (m - price) * actual_qty
                        sum_mid_dq += m * actual_qty
                        pos += actual_qty

            elif seller == 'SUBMISSION':
                # We tried to sell
                bid1 = float(snap['bid1']) if snap is not None else float('nan')
                if not _math.isnan(bid1) and price <= bid1:
                    # AGGRESSIVE: check take_edge condition
                    fv_here = fv_map.get(ts, fv)
                    threshold = fv_here + take_edge if pos <= 0 else fv_here
                    if price >= threshold and pos > -LIMIT:
                        actual_qty = min(qty, LIMIT + pos)
                        m = mmbot_map.get(ts, mid)
                        if _math.isnan(m): m = mid
                        pnl_mid_dq += (m - price) * (-actual_qty)
                        sum_mid_dq += m * (-actual_qty)
                        pos -= actual_qty
                else:
                    # PASSIVE: check if our ask_px <= price (we'd still get lifted)
                    if ask_px <= price and pos > -LIMIT:
                        actual_qty = min(qty, LIMIT + pos)
                        m = mmbot_map.get(ts, mid)
                        if _math.isnan(m): m = mid
                        pnl_mid_dq += (m - price) * (-actual_qty)
                        sum_mid_dq += m * (-actual_qty)
                        pos -= actual_qty

    inventory_carry = pos * final_mid - sum_mid_dq
    total_pnl = pnl_mid_dq + inventory_carry
    return total_pnl


def compute_6scores(cfg: dict, day_data: dict) -> dict:
    """Compute 6 PnL scores for one parameter combo."""
    scores = {}
    for day in [-2, -1, 0]:
        act_df, th_df = day_data[day]

        # Full day: no cutoff on timestamp, process all fills
        full_pnl = _replay_aco_cfg(act_df, th_df, cfg, ts_cutoff=None)
        scores[f"full_day_{day}"] = round(full_pnl, 2)

        # Half-2: only fills with ts > 500000
        # For inventory carry: use final mid, and only fills in second half
        half2_pnl = _compute_half2(act_df, th_df, cfg)
        scores[f"half2_{day}"] = round(half2_pnl, 2)

    return scores


def _compute_half2(act_df, th_df, cfg):
    """Compute PnL for second half only (ts > 500000), starting from mid-day position."""
    import math as _math

    TS_SPLIT = 500_000

    act_clean = (act_df.dropna(subset=['bid1', 'ask1'])
                       .drop_duplicates('timestamp')
                       .sort_values('timestamp')
                       .reset_index(drop=True))
    ts_arr  = act_clean['timestamp'].values.astype(int)
    mid_arr = act_clean['mid'].values.astype(float)

    mmbot_map = {}
    book_map = {}
    for _, r in act_clean.iterrows():
        ts = int(r['timestamp'])
        m = mmbot_mid_from_levels(
            r['bid1'], r['bv1'], r['bid2'], r['bv2'], r['bid3'], r['bv3'],
            r['ask1'], r['av1'], r['ask2'], r['av2'], r['ask3'], r['av3'],
        )
        mmbot_map[ts] = m
        book_map[ts] = r

    # Build EMA series (full day for accurate state at split point)
    alpha = cfg["ema_alpha"]
    offset = cfg["quote_offset"]
    max_skew = cfg["max_skew"]
    take_edge = cfg["take_edge"]
    panic_thr = cfg.get("panic_threshold", 0.75)

    fv = float(mid_arr[0]) if len(mid_arr) > 0 else 0.0
    fv_arr = np.zeros(len(ts_arr))
    for i, mid in enumerate(mid_arr):
        fv = alpha * mid + (1.0 - alpha) * fv
        fv_arr[i] = fv

    fv_map = {int(ts_arr[i]): fv_arr[i] for i in range(len(ts_arr))}

    # Simulate position up to split to get starting pos for half2
    sub_fills = th_df[(th_df['buyer'] == 'SUBMISSION') |
                      (th_df['seller'] == 'SUBMISSION')].copy()

    fills_by_ts = {}
    for _, row in sub_fills.iterrows():
        ts = int(row['timestamp'])
        fills_by_ts.setdefault(ts, []).append(row)

    # First pass: build pos at split point
    pos_at_split = 0
    for i, ts in enumerate(ts_arr):
        if ts > TS_SPLIT:
            break
        fv_i = fv_arr[i]
        mid = mid_arr[i]
        snap = book_map.get(ts)
        inv_ratio = pos_at_split / LIMIT if LIMIT != 0 else 0.0
        skew = round(inv_ratio * max_skew)
        panic_extra = 0
        if abs(inv_ratio) >= panic_thr:
            panic_extra = round((abs(inv_ratio) - panic_thr) / (1.0 - panic_thr) * 3)
        urgency = 0.0
        if urgency > 0 and abs(pos_at_split) > 0:
            eff_offset = max(0, offset - round(urgency * offset))
            eff_skew = round(inv_ratio * (max_skew + urgency * 4))
        else:
            eff_offset = offset
            eff_skew = skew

        bid_px = _math.floor(fv_i) - eff_offset - eff_skew
        ask_px = _math.ceil(fv_i) + eff_offset - eff_skew
        if pos_at_split > 0 and panic_extra > 0: ask_px -= panic_extra
        elif pos_at_split < 0 and panic_extra > 0: bid_px += panic_extra
        if urgency > 0.5 or abs(inv_ratio) >= panic_thr:
            bid_px = min(bid_px, _math.floor(fv_i))
            ask_px = max(ask_px, _math.ceil(fv_i))
        else:
            bid_px = min(bid_px, _math.floor(fv_i) - 1)
            ask_px = max(ask_px, _math.ceil(fv_i) + 1)
        if ask_px <= bid_px: ask_px = bid_px + 1

        for fill_row in fills_by_ts.get(ts, []):
            buyer  = str(fill_row.get('buyer', ''))
            seller = str(fill_row.get('seller', ''))
            price  = float(fill_row['price'])
            qty    = int(fill_row['quantity'])
            ask1 = float(snap['ask1']) if snap is not None else float('nan')
            bid1 = float(snap['bid1']) if snap is not None else float('nan')
            if buyer == 'SUBMISSION':
                if not _math.isnan(ask1) and price >= ask1:
                    fv_here = fv_map.get(ts, fv_i)
                    threshold = fv_here - take_edge if pos_at_split >= 0 else fv_here
                    if price <= threshold and pos_at_split < LIMIT:
                        pos_at_split += min(qty, LIMIT - pos_at_split)
                else:
                    if bid_px >= price and pos_at_split < LIMIT:
                        pos_at_split += min(qty, LIMIT - pos_at_split)
            elif seller == 'SUBMISSION':
                if not _math.isnan(bid1) and price <= bid1:
                    fv_here = fv_map.get(ts, fv_i)
                    threshold = fv_here + take_edge if pos_at_split <= 0 else fv_here
                    if price >= threshold and pos_at_split > -LIMIT:
                        pos_at_split -= min(qty, LIMIT + pos_at_split)
                else:
                    if ask_px <= price and pos_at_split > -LIMIT:
                        pos_at_split -= min(qty, LIMIT + pos_at_split)

    # Second pass: PnL from split onwards
    pos = pos_at_split
    pnl_mid_dq = 0.0
    sum_mid_dq = 0.0

    # Reference mid at split point
    split_idx = None
    for i, ts in enumerate(ts_arr):
        if ts >= TS_SPLIT:
            split_idx = i
            break
    if split_idx is None:
        split_idx = len(ts_arr) - 1

    final_mid = float(mid_arr[-1]) if len(mid_arr) > 0 else 0.0

    # The half2 PnL = pnl from ts > TS_SPLIT using mid at split as reference
    # Recompute: only fills at ts > TS_SPLIT, starting from pos_at_split
    for i in range(split_idx, len(ts_arr)):
        ts = int(ts_arr[i])
        fv_i = fv_arr[i]
        mid = mid_arr[i]
        snap = book_map.get(ts)

        inv_ratio = pos / LIMIT if LIMIT != 0 else 0.0
        skew = round(inv_ratio * max_skew)
        panic_extra = 0
        if abs(inv_ratio) >= panic_thr:
            panic_extra = round((abs(inv_ratio) - panic_thr) / (1.0 - panic_thr) * 3)
        urgency = 0.0
        if ts >= 950000:
            urgency = min(1.0, (ts - 950000) / (999900 - 950000))
        if urgency > 0 and abs(pos) > 0:
            eff_offset = max(0, offset - round(urgency * offset))
            eff_skew = round(inv_ratio * (max_skew + urgency * 4))
        else:
            eff_offset = offset
            eff_skew = skew

        bid_px = _math.floor(fv_i) - eff_offset - eff_skew
        ask_px = _math.ceil(fv_i) + eff_offset - eff_skew
        if pos > 0 and panic_extra > 0: ask_px -= panic_extra
        elif pos < 0 and panic_extra > 0: bid_px += panic_extra
        if urgency > 0.5 or abs(inv_ratio) >= panic_thr:
            bid_px = min(bid_px, _math.floor(fv_i))
            ask_px = max(ask_px, _math.ceil(fv_i))
        else:
            bid_px = min(bid_px, _math.floor(fv_i) - 1)
            ask_px = max(ask_px, _math.ceil(fv_i) + 1)
        if ask_px <= bid_px: ask_px = bid_px + 1

        for fill_row in fills_by_ts.get(ts, []):
            buyer  = str(fill_row.get('buyer', ''))
            seller = str(fill_row.get('seller', ''))
            price  = float(fill_row['price'])
            qty    = int(fill_row['quantity'])
            ask1 = float(snap['ask1']) if snap is not None else float('nan')
            bid1 = float(snap['bid1']) if snap is not None else float('nan')
            if buyer == 'SUBMISSION':
                if not _math.isnan(ask1) and price >= ask1:
                    fv_here = fv_map.get(ts, fv_i)
                    threshold = fv_here - take_edge if pos >= 0 else fv_here
                    if price <= threshold and pos < LIMIT:
                        actual_qty = min(qty, LIMIT - pos)
                        m = mmbot_map.get(ts, mid)
                        if _math.isnan(m): m = mid
                        pnl_mid_dq += (m - price) * actual_qty
                        sum_mid_dq += m * actual_qty
                        pos += actual_qty
                else:
                    if bid_px >= price and pos < LIMIT:
                        actual_qty = min(qty, LIMIT - pos)
                        m = mmbot_map.get(ts, mid)
                        if _math.isnan(m): m = mid
                        pnl_mid_dq += (m - price) * actual_qty
                        sum_mid_dq += m * actual_qty
                        pos += actual_qty
            elif seller == 'SUBMISSION':
                if not _math.isnan(bid1) and price <= bid1:
                    fv_here = fv_map.get(ts, fv_i)
                    threshold = fv_here + take_edge if pos <= 0 else fv_here
                    if price >= threshold and pos > -LIMIT:
                        actual_qty = min(qty, LIMIT + pos)
                        m = mmbot_map.get(ts, mid)
                        if _math.isnan(m): m = mid
                        pnl_mid_dq += (m - price) * (-actual_qty)
                        sum_mid_dq += m * (-actual_qty)
                        pos -= actual_qty
                else:
                    if ask_px <= price and pos > -LIMIT:
                        actual_qty = min(qty, LIMIT + pos)
                        m = mmbot_map.get(ts, mid)
                        if _math.isnan(m): m = mid
                        pnl_mid_dq += (m - price) * (-actual_qty)
                        sum_mid_dq += m * (-actual_qty)
                        pos -= actual_qty

    inventory_carry = pos * final_mid - sum_mid_dq
    return pnl_mid_dq + inventory_carry


# ---------------------------------------------------------------------------
# Step 2: Evaluate all combos
# ---------------------------------------------------------------------------

def step2_evaluate(samples, day_data):
    t0 = time.time()
    print("\n" + "="*60)
    print("STEP 2: Evaluate 6-score for each combo (tagging replay)")
    print("="*60)

    results = []
    for i, cfg in enumerate(samples):
        full_cfg = {**cfg, "panic_threshold": 0.75}
        scores = compute_6scores(full_cfg, day_data)
        w6 = min(scores.values())
        row = {**cfg, **scores, "worst_of_6": round(w6, 2)}
        results.append(row)
        if (i+1) % 50 == 0:
            elapsed = time.time() - t0
            print(f"  {i+1}/{len(samples)} done — {elapsed:.1f}s elapsed")

    elapsed = time.time() - t0
    print(f"  All {len(samples)} combos done in {elapsed:.1f}s")

    # Save
    out_path = os.path.join(SCRATCH, "a2_eval_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Saved: {out_path}")
    return results, elapsed


# ---------------------------------------------------------------------------
# Step 3: Rank by worst_of_6
# ---------------------------------------------------------------------------

def step3_rank(results):
    print("\n" + "="*60)
    print("STEP 3: Rank by worst_of_6")
    print("="*60)

    df = pd.DataFrame(results)
    df = df.sort_values("worst_of_6", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1

    print("\nTop 20 combos:")
    cols = ["rank", "quote_offset", "max_skew", "take_edge", "ema_alpha",
            "full_day_-2", "full_day_-1", "full_day_0",
            "half2_-2", "half2_-1", "half2_0", "worst_of_6"]
    print(df[cols].head(20).to_string(index=False))
    return df


# ---------------------------------------------------------------------------
# Step 4: Null-baseline
# ---------------------------------------------------------------------------

def step4_null_baseline(df):
    print("\n" + "="*60)
    print("STEP 4: Null-baseline gate")
    print("="*60)

    w6_arr = df["worst_of_6"].values
    median_w6  = float(np.percentile(w6_arr, 50))
    p95_w6     = float(np.percentile(w6_arr, 95))
    noise_spread = p95_w6 - median_w6
    threshold    = QO5_WORST6 + noise_spread

    print(f"  v9-qo5 worst_of_6:      {QO5_WORST6:,.0f}")
    print(f"  Median worst_of_6:      {median_w6:,.1f}")
    print(f"  95th pct worst_of_6:    {p95_w6:,.1f}")
    print(f"  Noise spread (95-50):   {noise_spread:,.1f}")
    print(f"  Threshold (v9+noise):   {threshold:,.1f}")
    print(f"  Combos above threshold: {(w6_arr > threshold).sum()}")

    # Histogram
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(w6_arr, bins=40, color="steelblue", alpha=0.7, edgecolor="white")
    ax.axvline(QO5_WORST6, color="crimson", linewidth=2.5,
               label=f"v9-qo5 worst_of_6 = {QO5_WORST6:,.0f}")
    ax.axvline(threshold, color="darkorange", linewidth=2.5, linestyle="--",
               label=f"Threshold = {threshold:,.0f}")
    ax.axvline(median_w6, color="green", linewidth=1.5, linestyle=":",
               label=f"Median = {median_w6:,.0f}")
    ax.set_xlabel("worst_of_6 (XIREC)")
    ax.set_ylabel("Count")
    ax.set_title("A2: Distribution of worst_of_6 across 300 LHS combos")
    ax.legend(fontsize=10)
    plt.tight_layout()
    plot_path = os.path.join(PLOT_DIR, "a2_worst_of_6_dist.png")
    fig.savefig(plot_path, dpi=120)
    plt.close(fig)
    print(f"  Plot saved: {plot_path}")

    return median_w6, p95_w6, noise_spread, threshold


# ---------------------------------------------------------------------------
# Step 5: GT prosperity4btest for top 10
# ---------------------------------------------------------------------------

def _make_candidate_trader(cfg, idx):
    """Write a candidate trader file with ACO_CFG overridden."""
    with open(TEMPLATE, "r") as f:
        src = f.read()

    # Replace the ACO_CFG block
    new_cfg = (
        f'ACO_CFG = {{\n'
        f'    "ema_alpha":       {cfg["ema_alpha"]},\n'
        f'    "quote_offset":    {cfg["quote_offset"]},\n'
        f'    "take_edge":       {cfg["take_edge"]},\n'
        f'    "max_skew":        {cfg["max_skew"]},\n'
        f'    "panic_threshold": 0.75,\n'
        f'}}'
    )
    # Replace ACO_CFG = { ... } block
    import re
    src_new = re.sub(
        r'ACO_CFG\s*=\s*\{[^}]*\}',
        new_cfg,
        src,
        count=1,
        flags=re.DOTALL
    )

    out_path = os.path.join(CAND_DIR, f"a2_cand_{idx:03d}.py")
    with open(out_path, "w") as f:
        f.write(src_new)
    return out_path


def _run_gt(trader_path, day):
    """Run prosperity4btest for one day, return ACO PnL."""
    log_path = os.path.join(CAND_DIR, f"gt_{os.path.basename(trader_path)}_day{day}.log")
    cmd = ["prosperity4btest", trader_path, f"1-{day}", "--out", log_path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"    WARN: prosperity4btest failed for day {day}: {result.stderr[:200]}")
        return None, None

    # Parse PnL from log
    try:
        with open(log_path) as f:
            lines = f.read().splitlines()
        start = next(i for i, l in enumerate(lines) if l.startswith("Activities log:"))
        header = lines[start + 1].split(";")
        col_pnl = header.index("profit_and_loss")
        col_product = header.index("product")
        col_ts = header.index("timestamp")
        last_aco = (0, 0.0)
        last_ipr = (0, 0.0)
        end = next((i for i in range(start+2, len(lines)) if lines[i].startswith("Trade History:")), len(lines))
        for l in lines[start+2:end]:
            parts = l.split(";")
            if len(parts) <= col_pnl: continue
            try:
                ts = int(parts[col_ts])
                prod = parts[col_product]
                pnl = float(parts[col_pnl]) if parts[col_pnl] else 0.0
                if prod == "ASH_COATED_OSMIUM" and ts > last_aco[0]:
                    last_aco = (ts, pnl)
                elif prod == "INTARIAN_PEPPER_ROOT" and ts > last_ipr[0]:
                    last_ipr = (ts, pnl)
            except ValueError:
                continue
        return last_aco[1], log_path
    except Exception as e:
        print(f"    WARN: parse failed: {e}")
        return None, log_path


def step5_gt_confirmation(df, top_n=10):
    t0 = time.time()
    print("\n" + "="*60)
    print(f"STEP 5: GT prosperity4btest for top {top_n}")
    print("="*60)

    top10_df = df.head(top_n).copy()
    gt_results = []

    for rank_i, (_, row) in enumerate(top10_df.iterrows(), 1):
        cfg = {
            "quote_offset": int(row["quote_offset"]),
            "max_skew":     int(row["max_skew"]),
            "take_edge":    float(row["take_edge"]),
            "ema_alpha":    float(row["ema_alpha"]),
        }
        print(f"\n  Candidate {rank_i}/10: qo={cfg['quote_offset']} ms={cfg['max_skew']} "
              f"te={cfg['take_edge']} alpha={cfg['ema_alpha']}")

        trader_path = _make_candidate_trader(cfg, rank_i)
        day_pnls = {}
        for day in [-2, -1, 0]:
            pnl, log_path = _run_gt(trader_path, day)
            day_pnls[day] = pnl
            print(f"    Day {day}: ACO PnL = {pnl}")

        valid_pnls = [v for v in day_pnls.values() if v is not None]
        gt_worst3  = min(valid_pnls) if valid_pnls else None
        gt_sum     = sum(valid_pnls) if valid_pnls else None

        gt_results.append({
            "tagging_rank": rank_i,
            "gt_worst_3":   gt_worst3,
            "gt_sum":       gt_sum,
            "gt_day_-2":    day_pnls.get(-2),
            "gt_day_-1":    day_pnls.get(-1),
            "gt_day_0":     day_pnls.get(0),
            **cfg,
            "tagging_worst_of_6": float(row["worst_of_6"]),
        })

    # Save
    out_path = os.path.join(SCRATCH, "a2_top10_gt.json")
    with open(out_path, "w") as f:
        json.dump(gt_results, f, indent=2)
    print(f"\n  Saved: {out_path}")

    # Compute GT ranking
    gt_df = pd.DataFrame(gt_results)
    gt_df = gt_df.sort_values("gt_worst_3", ascending=False).reset_index(drop=True)
    gt_df["gt_rank"] = gt_df.index + 1

    # Spearman rank correlation between tagging and GT
    tagging_ranks = gt_df["tagging_rank"].values
    gt_ranks      = gt_df["gt_rank"].values
    if len(tagging_ranks) > 2:
        rho, pval = spearmanr(tagging_ranks, gt_ranks)
    else:
        rho, pval = float("nan"), float("nan")

    print(f"\n  Spearman ρ (tagging vs GT top-10): {rho:.3f}  (p={pval:.3f})")
    if rho < 0.7:
        print("  WARNING: ρ < 0.7 — tagging-layer ranking unreliable!")

    print("\nTop-10 GT table:")
    disp_cols = ["tagging_rank", "gt_rank", "quote_offset", "max_skew",
                 "take_edge", "ema_alpha", "tagging_worst_of_6", "gt_worst_3", "gt_sum"]
    print(gt_df[disp_cols].to_string(index=False))

    elapsed = time.time() - t0
    print(f"\n  GT runs wall time: {elapsed:.1f}s")
    return gt_df, rho, elapsed


# ---------------------------------------------------------------------------
# Step 6: Top-3 candidates
# ---------------------------------------------------------------------------

def step6_top3(gt_df, df_ranked, threshold):
    print("\n" + "="*60)
    print("STEP 6: Top-3 candidates for A3_refine")
    print("="*60)

    # Criterion 1: beats threshold on tagging worst_of_6
    crit1 = gt_df[gt_df["tagging_worst_of_6"] > threshold].copy()

    # Criterion 2: beats qo5 on >= 4 of 6 AND on GT per-day min
    crit2_rows = []
    all_qo5_scores = [9201, 10793, 9013, 4139, 5494, 4588]
    for _, row in gt_df.iterrows():
        beat_count = 0
        # Compare tagging scores (from the ranked df, by matching params)
        match = df_ranked[
            (df_ranked["quote_offset"] == int(row["quote_offset"])) &
            (df_ranked["max_skew"] == int(row["max_skew"])) &
            (abs(df_ranked["take_edge"] - float(row["take_edge"])) < 0.001) &
            (abs(df_ranked["ema_alpha"] - float(row["ema_alpha"])) < 0.001)
        ]
        if len(match) > 0:
            r = match.iloc[0]
            cand_scores = [r["full_day_-2"], r["full_day_-1"], r["full_day_0"],
                           r["half2_-2"], r["half2_-1"], r["half2_0"]]
            for cs, qs in zip(cand_scores, all_qo5_scores):
                if cs > qs: beat_count += 1

        gt_min = row.get("gt_worst_3")
        beats_gt_min = gt_min is not None and gt_min > min(QO5_FULL.values())
        if beat_count >= 4 and beats_gt_min:
            crit2_rows.append(row)

    crit2 = pd.DataFrame(crit2_rows) if crit2_rows else pd.DataFrame()

    candidates = pd.concat([crit1, crit2]).drop_duplicates(
        subset=["quote_offset","max_skew","take_edge","ema_alpha"]) \
        .sort_values("gt_worst_3", ascending=False).reset_index(drop=True)

    if len(candidates) == 0:
        print("\n  NULL RESULT: No combo passes either criterion.")
        print("  Reason:")
        print(f"    - Threshold = {threshold:,.0f}; best tagging worst_of_6 = "
              f"{gt_df['tagging_worst_of_6'].max():,.0f}")
        print(f"    - No combo beats qo5 on >=4 of 6 AND GT per-day min > {min(QO5_FULL.values()):,.0f}")
        print("  Decision: ship v9-qo5 unchanged.")

        out = {"result": "null",
               "reason": (f"No combo beats threshold ({threshold:.0f}) or "
                          f">=4-of-6 + GT criteria. "
                          f"Best tagging worst_of_6 = {gt_df['tagging_worst_of_6'].max():.0f}. "
                          f"Ship v9-qo5 unchanged.")}
        out_path = os.path.join(SCRATCH, "a2_top3_candidates.json")
        with open(out_path, "w") as f:
            json.dump(out, f, indent=2)
        print(f"  Saved: {out_path}")
        return out

    top3 = candidates.head(3)
    print(f"\n  {len(candidates)} combos pass criteria; taking top 3 for A3_refine:")
    print(top3[["quote_offset","max_skew","take_edge","ema_alpha",
                "tagging_worst_of_6","gt_worst_3","gt_sum"]].to_string(index=False))

    out_list = []
    for _, row in top3.iterrows():
        out_list.append({
            "quote_offset": int(row["quote_offset"]),
            "max_skew":     int(row["max_skew"]),
            "take_edge":    float(row["take_edge"]),
            "ema_alpha":    float(row["ema_alpha"]),
            "panic_threshold": 0.75,
            "tagging_worst_of_6": float(row["tagging_worst_of_6"]),
            "gt_worst_3":    float(row["gt_worst_3"]) if row["gt_worst_3"] else None,
            "gt_sum":        float(row["gt_sum"]) if row["gt_sum"] else None,
        })

    out_path = os.path.join(SCRATCH, "a2_top3_candidates.json")
    with open(out_path, "w") as f:
        json.dump({"result": "candidates", "top3": out_list}, f, indent=2)
    print(f"  Saved: {out_path}")
    return {"result": "candidates", "top3": out_list}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    wall_start = time.time()
    print("A2: LHS Joint Search — ACO Pass 2.6")
    print(f"Start time: {time.strftime('%H:%M:%S')}")

    # Step 1
    samples, t_lhs = step1_lhs_sampling()

    # Pre-load day data once (cache in memory)
    print("\nLoading day data from cached pass2_6 logs...")
    t_load = time.time()
    day_data = {}
    for day in [-2, -1, 0]:
        day_data[day] = _load_day_data(day)
        print(f"  Day {day}: {len(day_data[day][0])} activity rows, "
              f"{len(day_data[day][1])} trade rows")
    print(f"  Load time: {time.time()-t_load:.1f}s")

    # Step 2
    results, t_eval = step2_evaluate(samples, day_data)

    # Step 3
    df_ranked = step3_rank(results)

    # Step 4
    median_w6, p95_w6, noise_spread, threshold = step4_null_baseline(df_ranked)

    # Step 5
    gt_df, rho, t_gt = step5_gt_confirmation(df_ranked, top_n=10)

    # Step 6
    decision = step6_top3(gt_df, df_ranked, threshold)

    total = time.time() - wall_start
    print(f"\n{'='*60}")
    print(f"WALL TIME: {total/60:.1f} min ({total:.0f}s)")
    print(f"  LHS sampling: {t_lhs:.1f}s")
    print(f"  Tagging eval ({len(samples)} combos): {t_eval:.1f}s")
    print(f"  GT runs (top 10): {t_gt:.1f}s")
    print(f"{'='*60}")

    return {
        "n_samples": len(samples),
        "eval_method": "tagging_replay",
        "t_eval_s": t_eval,
        "t_gt_s": t_gt,
        "t_total_s": total,
        "median_worst6": median_w6,
        "p95_worst6": p95_w6,
        "threshold": threshold,
        "spearman_rho": rho,
        "decision": decision,
    }


if __name__ == "__main__":
    main()
