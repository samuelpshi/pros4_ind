"""
ACO Order Book Structure Analysis — Section B of aco_deep_eda
Produces:
  - plots/aco_deep/book_depth_dist.png
  - plots/aco_deep/spread_hist_per_day.png
  - plots/aco_deep/refill_cdf.png
  - printed markdown tables (captured by notebook)
"""
import os, json, warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

# ── paths ──────────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "..", "r1_data_capsule")
PLOT = os.path.join(BASE, "plots", "aco_deep")
os.makedirs(PLOT, exist_ok=True)

DAYS = [-2, -1, 0]

# ── load & filter ──────────────────────────────────────────────────────────
def load_prices(day):
    path = os.path.join(DATA, f"prices_round_1_day_{day}.csv")
    df = pd.read_csv(path, sep=";")
    df = df[df["product"] == "ASH_COATED_OSMIUM"].copy()
    # drop rows where both L1 bid and L1 ask are missing
    df = df.dropna(subset=["bid_price_1", "ask_price_1"])
    df = df.reset_index(drop=True)
    return df

def load_trades(day):
    path = os.path.join(DATA, f"trades_round_1_day_{day}.csv")
    df = pd.read_csv(path, sep=";")
    df = df[df["symbol"] == "ASH_COATED_OSMIUM"].copy()
    df = df.reset_index(drop=True)
    return df

prices = {d: load_prices(d) for d in DAYS}
trades = {d: load_trades(d) for d in DAYS}

print(f"Rows per day (prices): { {d: len(prices[d]) for d in DAYS} }")
print(f"Rows per day (trades): { {d: len(trades[d]) for d in DAYS} }")

# ══════════════════════════════════════════════════════════════════════════
# 1. PER-LEVEL VOLUME DISTRIBUTION
# ══════════════════════════════════════════════════════════════════════════
print("\n## 1. Per-Level Volume Distribution")

level_stats = {}
for d in DAYS:
    df = prices[d]
    stats = {}
    for side, prefix in [("bid", "bid_volume_"), ("ask", "ask_volume_")]:
        for lvl in [1, 2, 3]:
            col = f"{prefix}{lvl}"
            vals = df[col].dropna()
            stats[f"{side}_L{lvl}"] = {
                "mean": round(vals.mean(), 2),
                "p10":  round(vals.quantile(0.10), 2),
                "p50":  round(vals.quantile(0.50), 2),
                "p90":  round(vals.quantile(0.90), 2),
                "pct_present": round(vals.notna().mean() * 100, 1),
            }
    level_stats[d] = stats

# Print markdown table
print()
for d in DAYS:
    print(f"### Day {d}")
    print(f"| Level | Side | mean | p10 | p50 | p90 | % rows present |")
    print(f"|-------|------|------|-----|-----|-----|----------------|")
    for side in ["bid", "ask"]:
        for lvl in [1, 2, 3]:
            k = f"{side}_L{lvl}"
            s = level_stats[d][k]
            print(f"| L{lvl} | {side} | {s['mean']} | {s['p10']} | {s['p50']} | {s['p90']} | {s['pct_present']}% |")
    print()

# ── plot ──────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(3, 2, figsize=(14, 12))
for row, d in enumerate(DAYS):
    df = prices[d]
    for col_idx, (side, prefix) in enumerate([("Bid", "bid_volume_"), ("Ask", "ask_volume_")]):
        ax = axes[row, col_idx]
        data_by_level = []
        labels = []
        for lvl in [1, 2, 3]:
            col = f"{prefix}{lvl}"
            vals = df[col].dropna()
            data_by_level.append(vals.values)
            labels.append(f"L{lvl}")
        ax.boxplot(data_by_level, labels=labels, showfliers=False)
        ax.set_title(f"Day {d} — {side} volume by level", fontsize=10)
        ax.set_ylabel("Volume")
        ax.set_xlabel("Level")
plt.suptitle("ACO Book Depth Distribution (whiskers = 5th–95th pct)", fontsize=12)
plt.tight_layout()
plt.savefig(os.path.join(PLOT, "book_depth_dist.png"), dpi=120)
plt.close()
print("Saved: book_depth_dist.png")

# ══════════════════════════════════════════════════════════════════════════
# 2. SPREAD DISTRIBUTION
# ══════════════════════════════════════════════════════════════════════════
print("\n## 2. Spread Distribution")

spread_stats = {}
for d in DAYS:
    df = prices[d]
    spread = df["ask_price_1"] - df["bid_price_1"]
    spread_stats[d] = {
        "p10": round(spread.quantile(0.10), 2),
        "p50": round(spread.quantile(0.50), 2),
        "p90": round(spread.quantile(0.90), 2),
        "mean": round(spread.mean(), 2),
        "mode": float(spread.mode().iloc[0]),
    }

print()
print("| Day | p10 | p50 | p90 | mean | mode |")
print("|-----|-----|-----|-----|------|------|")
for d in DAYS:
    s = spread_stats[d]
    print(f"| {d} | {s['p10']} | {s['p50']} | {s['p90']} | {s['mean']} | {s['mode']} |")

fig, axes = plt.subplots(1, 3, figsize=(15, 4))
for i, d in enumerate(DAYS):
    df = prices[d]
    spread = df["ask_price_1"] - df["bid_price_1"]
    axes[i].hist(spread.dropna(), bins=40, color="steelblue", edgecolor="white", linewidth=0.5)
    axes[i].set_title(f"Day {d} spread histogram")
    axes[i].set_xlabel("Spread (ticks)")
    axes[i].set_ylabel("Count")
    axes[i].axvline(spread.median(), color="red", linestyle="--", label=f"median={spread.median():.1f}")
    axes[i].legend(fontsize=8)
plt.suptitle("ACO Bid-Ask Spread Distribution", fontsize=12)
plt.tight_layout()
plt.savefig(os.path.join(PLOT, "spread_hist_per_day.png"), dpi=120)
plt.close()
print("Saved: spread_hist_per_day.png")

# ══════════════════════════════════════════════════════════════════════════
# 3. BOOK REFILL DYNAMICS
# ══════════════════════════════════════════════════════════════════════════
print("\n## 3. Book Refill Dynamics")

def refill_ticks(df, trades_df):
    """
    For each trade, identify the pre-trade mean volume at the touched price level.
    Then count how many ticks until bid_volume_1 or ask_volume_1 returns to that mean.
    We use the trades timestamp to find the corresponding price row, then walk forward.
    """
    # Build a ts -> row index map using the price DataFrame timestamps
    ts_index = {row["timestamp"]: idx for idx, row in df.iterrows()}
    # Pre-trade mean volumes (global)
    mean_bid_vol1 = df["bid_volume_1"].mean()
    mean_ask_vol1 = df["ask_volume_1"].mean()

    refill_wait = []
    ts_sorted = df["timestamp"].values
    n = len(df)

    for _, trade in trades_df.iterrows():
        ts = trade["timestamp"]
        # find closest price row at or after trade ts
        idx_arr = np.searchsorted(ts_sorted, ts)
        if idx_arr >= n:
            continue
        row_idx = idx_arr

        trade_price = trade["price"]
        bid_at_trade = df.at[row_idx, "bid_price_1"] if row_idx < n else np.nan
        ask_at_trade = df.at[row_idx, "ask_price_1"] if row_idx < n else np.nan

        # Determine if trade hit bid or ask side
        if pd.notna(bid_at_trade) and abs(trade_price - bid_at_trade) <= 1:
            target_col = "bid_volume_1"
            mean_vol = mean_bid_vol1
        elif pd.notna(ask_at_trade) and abs(trade_price - ask_at_trade) <= 1:
            target_col = "ask_volume_1"
            mean_vol = mean_ask_vol1
        else:
            continue  # unclear which side

        # Walk forward from row_idx+1 until volume recovers
        recovered = False
        for k in range(1, min(200, n - row_idx)):
            future_vol = df.at[row_idx + k, target_col] if (row_idx + k) < n else np.nan
            if pd.notna(future_vol) and future_vol >= mean_vol * 0.8:
                refill_wait.append(k)
                recovered = True
                break
        if not recovered:
            refill_wait.append(200)  # censored at 200 ticks

    return refill_wait

refill_data = {}
for d in DAYS:
    print(f"  Computing refill for day {d}...")
    rw = refill_ticks(prices[d], trades[d])
    refill_data[d] = rw
    arr = np.array(rw)
    print(f"    N trades used: {len(arr)}, median refill: {np.median(arr):.1f}, p90: {np.percentile(arr, 90):.1f}")

# Plot CDF
fig, ax = plt.subplots(figsize=(8, 5))
colors = ["steelblue", "darkorange", "green"]
for i, d in enumerate(DAYS):
    arr = np.sort(refill_data[d])
    cdf = np.arange(1, len(arr) + 1) / len(arr)
    ax.plot(arr, cdf, label=f"Day {d}", color=colors[i], linewidth=2)
ax.axvline(5, color="gray", linestyle=":", alpha=0.7, label="5-tick mark")
ax.axvline(20, color="gray", linestyle="--", alpha=0.7, label="20-tick mark")
ax.set_xlabel("Ticks until refill (capped at 200)")
ax.set_ylabel("CDF")
ax.set_title("ACO Book Refill CDF — ticks until L1 vol recovers to 80% of mean")
ax.legend()
ax.set_xlim(0, 100)
plt.tight_layout()
plt.savefig(os.path.join(PLOT, "refill_cdf.png"), dpi=120)
plt.close()
print("Saved: refill_cdf.png")

# ══════════════════════════════════════════════════════════════════════════
# 4. QUOTE PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════
print("\n## 4. Quote Persistence  P(best_{t+k} == best_t)")

ks = [1, 2, 5, 10]
persistence = {}
for d in DAYS:
    df = prices[d]
    n = len(df)
    bid = df["bid_price_1"].values
    ask = df["ask_price_1"].values
    row = {}
    for k in ks:
        if n <= k:
            row[k] = (np.nan, np.nan)
            continue
        bid_persist = np.nanmean(bid[:-k] == bid[k:])
        ask_persist = np.nanmean(ask[:-k] == ask[k:])
        row[k] = (round(bid_persist, 4), round(ask_persist, 4))
    persistence[d] = row

print()
print("| Day | k=1 bid | k=1 ask | k=2 bid | k=2 ask | k=5 bid | k=5 ask | k=10 bid | k=10 ask |")
print("|-----|---------|---------|---------|---------|---------|---------|----------|----------|")
for d in DAYS:
    r = persistence[d]
    vals = " | ".join([f"{r[k][0]:.3f} | {r[k][1]:.3f}" for k in ks])
    print(f"| {d} | {vals} |")

# ══════════════════════════════════════════════════════════════════════════
# 5. FAIR VALUE PROXY COMPARISON
# ══════════════════════════════════════════════════════════════════════════
print("\n## 5. Fair Value Proxy Comparison")

def compute_proxies(df):
    """
    Returns DataFrame with columns: timestamp, naive_mid, vwap_mid, mmbot_mid
    naive_mid  = (bid_price_1 + ask_price_1) / 2  [= mid_price column]
    vwap_mid   = volume-weighted average of top-3 levels on each side
    mmbot_mid  = mid of levels where abs volume >= 15 (filter out small quotes)
    """
    out = df[["timestamp"]].copy()
    out["naive_mid"] = df["mid_price"]

    # vwap_mid: weight each price level by its volume, compute weighted mid
    # bid side: sum(price_i * vol_i) / sum(vol_i) ; same for ask
    def vwap_side(df, prefix_p, prefix_v):
        total_vol = np.zeros(len(df))
        weighted_p = np.zeros(len(df))
        for lvl in [1, 2, 3]:
            p = df[f"{prefix_p}{lvl}"].fillna(0).values
            v = df[f"{prefix_v}{lvl}"].fillna(0).values
            weighted_p += p * v
            total_vol += v
        safe = total_vol > 0
        result = np.where(safe, weighted_p / total_vol, np.nan)
        return result

    bid_vwap = vwap_side(df, "bid_price_", "bid_volume_")
    ask_vwap = vwap_side(df, "ask_price_", "ask_volume_")
    out["vwap_mid"] = (bid_vwap + ask_vwap) / 2

    # mmbot_mid: only consider levels with volume >= 15
    def mmbot_best(df, prefix_p, prefix_v, side):
        result = np.full(len(df), np.nan)
        for i, row in df.reset_index(drop=True).iterrows():
            candidates = []
            for lvl in [1, 2, 3]:
                p = row.get(f"{prefix_p}{lvl}", np.nan)
                v = row.get(f"{prefix_v}{lvl}", np.nan)
                if pd.notna(p) and pd.notna(v) and v >= 15:
                    candidates.append(p)
            if candidates:
                result[i] = min(candidates) if side == "ask" else max(candidates)
        return result

    # Vectorized mmbot (faster approach)
    def mmbot_best_vec(df, prefix_p, prefix_v, side):
        result = np.full(len(df), np.nan)
        for lvl in [1, 2, 3]:
            p = df[f"{prefix_p}{lvl}"].values
            v = df[f"{prefix_v}{lvl}"].fillna(0).values
            mask = v >= 15
            p_masked = np.where(mask, p, np.nan)
            if side == "ask":
                # take minimum of valid candidates
                result = np.fmin(result, p_masked)  # fmin ignores NaN
            else:
                result = np.fmax(result, p_masked)
        return result

    bid_mm = mmbot_best_vec(df, "bid_price_", "bid_volume_", "bid")
    ask_mm = mmbot_best_vec(df, "ask_price_", "ask_volume_", "ask")
    out["mmbot_mid"] = (bid_mm + ask_mm) / 2

    return out

def next_trade_price(price_df, trade_df, horizon):
    """
    For each price row at timestamp t, find the next trade price within
    `horizon` ticks (in terms of row index, not time).
    Returns array of length len(price_df), NaN where no trade found.
    """
    price_ts = price_df["timestamp"].values
    n = len(price_ts)

    # Build a fast lookup: for each price row index, what is the next trade price?
    trade_ts = trade_df["timestamp"].values
    trade_price_vals = trade_df["price"].values

    result = np.full(n, np.nan)

    # For efficiency: for each price row, find next trade using searchsorted
    for i in range(n):
        t = price_ts[i]
        # Find first trade at or after this timestamp
        idx = np.searchsorted(trade_ts, t)
        # Look ahead up to `horizon` price rows to bound the time window
        max_t = price_ts[min(i + horizon, n - 1)]
        # Find trades in [t, max_t]
        j = idx
        while j < len(trade_ts) and trade_ts[j] <= max_t:
            result[i] = trade_price_vals[j]
            break  # use the FIRST trade found
            j += 1

    return result

print("  Computing proxies and MSE (this may take a moment)...")

horizons = [1, 10, 100]
proxy_cols = ["naive_mid", "vwap_mid", "mmbot_mid"]

fv_results = {}
for d in DAYS:
    print(f"  Day {d}...")
    df = prices[d].reset_index(drop=True)
    tdf = trades[d].sort_values("timestamp").reset_index(drop=True)

    proxies = compute_proxies(df)
    day_results = {}

    for h in horizons:
        next_tp = next_trade_price(df, tdf, h)
        mask = ~np.isnan(next_tp)
        row = {}
        for col in proxy_cols:
            pval = proxies[col].values
            valid = mask & ~np.isnan(pval)
            if valid.sum() == 0:
                row[col] = (np.nan, np.nan, 0)
                continue
            residuals = pval[valid] - next_tp[valid]
            mse = np.mean(residuals ** 2)
            std = np.std(residuals)
            row[col] = (round(mse, 4), round(std, 4), int(valid.sum()))
        day_results[h] = row
    fv_results[d] = day_results

# Print MSE table
print()
for d in DAYS:
    print(f"### Day {d} — Fair Value Proxy MSE vs Next Trade Price")
    print(f"| Horizon | naive_mid MSE | naive_mid std | vwap_mid MSE | vwap_mid std | mmbot_mid MSE | mmbot_mid std | N pairs |")
    print(f"|---------|--------------|--------------|-------------|-------------|--------------|--------------|---------|")
    for h in horizons:
        row = fv_results[d][h]
        n_pairs = row["naive_mid"][2]
        print(
            f"| {h} ticks | {row['naive_mid'][0]} | {row['naive_mid'][1]} | "
            f"{row['vwap_mid'][0]} | {row['vwap_mid'][1]} | "
            f"{row['mmbot_mid'][0]} | {row['mmbot_mid'][1]} | {n_pairs} |"
        )
    print()

# ── Determine best proxy per horizon (lowest mean MSE across days) ──
print("\n### Best Proxy Summary (average MSE across all 3 days)")
print(f"| Horizon | naive_mid avg MSE | vwap_mid avg MSE | mmbot_mid avg MSE | Winner |")
print(f"|---------|------------------|-----------------|------------------|--------|")
for h in horizons:
    mses = {}
    for col in proxy_cols:
        vals = [fv_results[d][h][col][0] for d in DAYS if not np.isnan(fv_results[d][h][col][0])]
        mses[col] = np.mean(vals) if vals else np.nan
    winner = min(mses, key=lambda k: mses[k] if not np.isnan(mses[k]) else 1e18)
    print(
        f"| {h} ticks | {mses['naive_mid']:.4f} | {mses['vwap_mid']:.4f} | "
        f"{mses['mmbot_mid']:.4f} | **{winner}** |"
    )

print("\n## Analysis Complete — all plots saved to plots/aco_deep/")

# ── Save results to JSON for notebook import ──
output = {
    "level_stats": {str(d): level_stats[d] for d in DAYS},
    "spread_stats": {str(d): spread_stats[d] for d in DAYS},
    "persistence": {str(d): {str(k): list(v) for k, v in persistence[d].items()} for d in DAYS},
    "fv_results": {
        str(d): {
            str(h): {col: list(fv_results[d][h][col]) for col in proxy_cols}
            for h in horizons
        }
        for d in DAYS
    },
    "refill_summary": {
        str(d): {
            "median": round(float(np.median(refill_data[d])), 2),
            "p90": round(float(np.percentile(refill_data[d], 90)), 2),
            "n": len(refill_data[d])
        }
        for d in DAYS
    }
}
results_path = os.path.join(BASE, "aco_ob_results.json")
with open(results_path, "w") as f:
    json.dump(output, f, indent=2)
print(f"Results saved to: {results_path}")
