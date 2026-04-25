"""
r1_eda_script.py — Full EDA for ACO + IPR, IMC Prosperity 4 Round 1.
Run with: python3 r1_eda_script.py
Outputs JSON with all numeric results + PNGs in plots/
"""

import os, json, warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats
from statsmodels.tsa.stattools import adfuller, acf
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant

warnings.filterwarnings("ignore")

DATA_DIR = "/Users/samuelshi/IMC-Prosperity-2026-personal/Round 1/r1_data_capsule"
PLOTS_DIR = "/Users/samuelshi/IMC-Prosperity-2026-personal/Round 1/analysis/plots"
os.makedirs(PLOTS_DIR, exist_ok=True)

results = {}

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — Load & Clean
# ─────────────────────────────────────────────────────────────────────────────
print("=== Section 1: Load & Clean ===")
days = [-2, -1, 0]
price_frames = []
trade_frames = []

for d in days:
    pf = pd.read_csv(f"{DATA_DIR}/prices_round_1_day_{d}.csv", sep=";")
    pf["day"] = d
    price_frames.append(pf)
    tf = pd.read_csv(f"{DATA_DIR}/trades_round_1_day_{d}.csv", sep=";")
    tf["day"] = d
    trade_frames.append(tf)

prices_raw = pd.concat(price_frames, ignore_index=True)
trades_all = pd.concat(trade_frames, ignore_index=True)

# Clean: drop rows where mid_price == 0 (empty book)
prices_raw = prices_raw[prices_raw["mid_price"] != 0].copy()
# Drop one-sided rows (bid_price_1 OR ask_price_1 NaN)
prices_clean = prices_raw.dropna(subset=["bid_price_1", "ask_price_1"]).copy()

ACO_prices = prices_clean[prices_clean["product"] == "ASH_COATED_OSMIUM"].copy()
IPR_prices = prices_clean[prices_clean["product"] == "INTARIAN_PEPPER_ROOT"].copy()

ACO_trades = trades_all[trades_all["symbol"] == "ASH_COATED_OSMIUM"].copy()
IPR_trades = trades_all[trades_all["symbol"] == "INTARIAN_PEPPER_ROOT"].copy()

print(f"  ACO rows (clean): {len(ACO_prices)}")
print(f"  IPR rows (clean): {len(IPR_prices)}")
print(f"  ACO trades: {len(ACO_trades)}")
print(f"  IPR trades: {len(IPR_trades)}")

results["data_summary"] = {
    "aco_price_rows": len(ACO_prices),
    "ipr_price_rows": len(IPR_prices),
    "aco_trade_rows": len(ACO_trades),
    "ipr_trade_rows": len(IPR_trades),
}

# Compute mid returns per product
for df, name in [(ACO_prices, "ACO"), (IPR_prices, "IPR")]:
    df.sort_values(["day", "timestamp"], inplace=True)
    df["ret"] = df.groupby("day")["mid_price"].transform(lambda x: x.diff())
    df["ret_pct"] = df.groupby("day")["mid_price"].transform(lambda x: x.pct_change())

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — Stationarity / Mean Reversion
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Section 2: Stationarity / Mean Reversion ===")

results["stationarity"] = {}

LAGS = [1, 5, 20, 100]

for df, name in [(ACO_prices, "ACO"), (IPR_prices, "IPR")]:
    res = {}
    # --- ADF test per day (and pooled by day-de-meaned returns) ---
    adf_pvals = []
    for d in days:
        sub = df[df["day"] == d]["mid_price"].dropna()
        if len(sub) < 20:
            continue
        adf_out = adfuller(sub, autolag="AIC")
        adf_pvals.append({"day": d, "adf_stat": adf_out[0], "adf_pval": adf_out[1], "n": len(sub)})
        print(f"  {name} day={d}: ADF stat={adf_out[0]:.4f}, p={adf_out[1]:.4f}")
    res["adf"] = adf_pvals

    # --- Return autocorrelation ---
    rets = df["ret"].dropna().values
    ac_vals = []
    for lag in LAGS:
        if len(rets) > lag:
            ac = float(np.corrcoef(rets[:-lag], rets[lag:])[0, 1])
        else:
            ac = np.nan
        ac_vals.append({"lag": lag, "acf": ac})
        print(f"  {name} lag={lag}: autocorr={ac:.4f}")
    res["autocorr"] = ac_vals

    # Bar chart
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar([str(l) for l in LAGS], [v["acf"] for v in ac_vals], color=["steelblue" if v["acf"] >= 0 else "salmon" for v in ac_vals])
    ax.axhline(0, color="black", linewidth=0.8)
    # 95% CI approx
    ci = 1.96 / np.sqrt(len(rets))
    ax.axhline(ci, color="gray", linestyle="--", linewidth=0.8, label="95% CI")
    ax.axhline(-ci, color="gray", linestyle="--", linewidth=0.8)
    ax.set_title(f"{name} Return Autocorrelation at lags {LAGS}")
    ax.set_xlabel("Lag")
    ax.set_ylabel("Autocorrelation")
    ax.legend()
    plt.tight_layout()
    plt.savefig(f"{PLOTS_DIR}/{name.lower()}_return_autocorr.png", dpi=150)
    plt.close()
    print(f"  Saved {name.lower()}_return_autocorr.png")

    # --- Variance Ratio Test (Lo-MacKinlay style) ---
    # VR(q) = Var(q-period return) / (q * Var(1-period return))
    # VR = 1 => random walk; VR < 1 => mean reversion; VR > 1 => momentum
    price_arr = df.groupby("day")["mid_price"].apply(lambda x: x.reset_index(drop=True))
    vr_results = []
    for q in [2, 4, 8, 16]:
        vr_list = []
        for d in days:
            sub = df[df["day"] == d]["mid_price"].dropna().values
            if len(sub) < q * 4:
                continue
            r1 = np.diff(sub)  # 1-period returns
            rq = sub[q:] - sub[:-q]  # q-period returns
            var1 = np.var(r1, ddof=1)
            varq = np.var(rq, ddof=1) / q
            if var1 > 0:
                vr_list.append(varq / var1)
        if vr_list:
            vr_results.append({"q": q, "vr_mean": float(np.mean(vr_list))})
            print(f"  {name} VR(q={q}): {np.mean(vr_list):.4f}")
    res["variance_ratio"] = vr_results

    # --- Hurst Exponent (R/S method) ---
    # H < 0.5: mean reverting; H = 0.5: random walk; H > 0.5: trending
    def hurst_rs(series, min_n=10, max_n=None):
        series = np.array(series, dtype=float)
        N = len(series)
        if max_n is None:
            max_n = N // 2
        ns = []
        rs_means = []
        for n in [int(N / k) for k in [2, 4, 8, 16, 32] if N // k >= min_n]:
            if n < min_n:
                continue
            chunks = [series[i:i+n] for i in range(0, N - n + 1, n)]
            rs_vals = []
            for chunk in chunks:
                mean_c = np.mean(chunk)
                dev = np.cumsum(chunk - mean_c)
                R = np.max(dev) - np.min(dev)
                S = np.std(chunk, ddof=1)
                if S > 0:
                    rs_vals.append(R / S)
            if rs_vals:
                ns.append(n)
                rs_means.append(np.mean(rs_vals))
        if len(ns) >= 2:
            log_ns = np.log(ns)
            log_rs = np.log(rs_means)
            slope, intercept, r, p, se = stats.linregress(log_ns, log_rs)
            return slope
        return np.nan

    all_prices = df["mid_price"].dropna().values
    H = hurst_rs(all_prices)
    res["hurst"] = float(H)
    print(f"  {name} Hurst (R/S): {H:.4f}")

    # --- OU Half-Life (if mean reversion plausible) ---
    # Estimate from AR(1): delta_p = alpha + beta * p_lag + eps
    # Half-life = -ln(2) / ln(1 + beta)
    diffs = np.diff(all_prices)
    lags_ar = all_prices[:-1]
    if len(diffs) > 2:
        X = add_constant(lags_ar)
        ols_res = OLS(diffs, X).fit()
        beta_ar = ols_res.params[1]
        if beta_ar < 0:
            half_life = -np.log(2) / np.log(1 + beta_ar)
        else:
            half_life = np.inf
        res["ou_half_life"] = float(half_life)
        res["ou_beta"] = float(beta_ar)
        print(f"  {name} OU beta={beta_ar:.6f}, half-life={half_life:.1f} timesteps")
    else:
        res["ou_half_life"] = np.nan
        res["ou_beta"] = np.nan

    results["stationarity"][name] = res

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — Order Flow / Microstructure
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Section 3: Order Flow / Microstructure ===")
results["microstructure"] = {}

# 3A: Trade-sign imbalance vs next-tick mid return
# Sign each trade: trades_all has price & quantity; use price relative to mid at same timestamp

for prod_prices, prod_trades, name in [
    (ACO_prices, ACO_trades, "ACO"),
    (IPR_prices, IPR_trades, "IPR"),
]:
    res = {}

    # Merge trade with nearest mid_price
    # trades_all columns: timestamp, buyer, seller, symbol, currency, price, quantity, day
    prod_trades = prod_trades.copy()
    prod_prices_sorted = prod_prices.sort_values(["day", "timestamp"]).reset_index(drop=True)

    # For each day, merge trade timestamp to price timestamp with merge_asof
    signed_trades_list = []
    for d in days:
        pt = prod_trades[prod_trades["day"] == d].copy()
        pp = prod_prices_sorted[prod_prices_sorted["day"] == d].copy()
        if len(pt) == 0 or len(pp) == 0:
            continue
        pt_s = pt.sort_values("timestamp")
        pp_s = pp.sort_values("timestamp")
        merged = pd.merge_asof(pt_s, pp_s[["timestamp", "mid_price"]], on="timestamp", direction="nearest")
        # Sign: buy if trade price >= mid, sell if below
        merged["sign"] = np.where(merged["price"] >= merged["mid_price"], 1, -1)
        # Weighted sign
        merged["signed_vol"] = merged["sign"] * merged["quantity"]
        signed_trades_list.append(merged)

    if signed_trades_list:
        signed_trades = pd.concat(signed_trades_list, ignore_index=True)

        # Aggregate sign imbalance per (day, timestamp bucket)
        # Next-tick mid: merge back to price data
        # Strategy: roll up to price-timestep level: sum of signed_vol in each price ts
        # Then correlate with next 1-tick return

        price_rets = prod_prices_sorted[["day", "timestamp", "mid_price", "ret"]].dropna().copy()

        # Compute sign imbalance per timestamp
        imb = signed_trades.groupby(["day", "timestamp"]).agg(
            signed_vol_sum=("signed_vol", "sum"),
            trade_count=("quantity", "count"),
        ).reset_index()

        # merge per day to avoid merge_asof multi-group sort issues
        merged2_parts = []
        for d2 in days:
            pr_d = price_rets[price_rets["day"] == d2].sort_values("timestamp").reset_index(drop=True)
            imb_d = imb[imb["day"] == d2].sort_values("timestamp").reset_index(drop=True)
            if len(pr_d) == 0 or len(imb_d) == 0:
                continue
            m = pd.merge_asof(pr_d, imb_d, on="timestamp", direction="backward", tolerance=200)
            merged2_parts.append(m)
        merged2 = pd.concat(merged2_parts, ignore_index=True) if merged2_parts else pd.DataFrame()

        valid = merged2.dropna(subset=["ret", "signed_vol_sum"])
        if len(valid) > 5:
            r_imb, p_imb = stats.pearsonr(valid["signed_vol_sum"], valid["ret"])
        else:
            r_imb, p_imb = np.nan, np.nan
        res["sign_imbalance_vs_ret_r"] = float(r_imb)
        res["sign_imbalance_vs_ret_p"] = float(p_imb)
        print(f"  {name} sign imbalance vs next-tick ret: r={r_imb:.4f}, p={p_imb:.4f}")

        # Scatter plot
        fig, ax = plt.subplots(figsize=(6, 4))
        if len(valid) > 5:
            ax.scatter(valid["signed_vol_sum"], valid["ret"], alpha=0.3, s=10)
            m, b, *_ = stats.linregress(valid["signed_vol_sum"].values, valid["ret"].values)
            xr = np.array([valid["signed_vol_sum"].min(), valid["signed_vol_sum"].max()])
            ax.plot(xr, m * xr + b, color="red", linewidth=1.5, label=f"r={r_imb:.3f}")
        ax.set_title(f"{name} Signed Flow vs Next-Tick Mid Return")
        ax.set_xlabel("Signed Volume (buy+, sell−)")
        ax.set_ylabel("Next-tick Mid Return (XIRECS)")
        ax.legend()
        plt.tight_layout()
        plt.savefig(f"{PLOTS_DIR}/{name.lower()}_flow_vs_ret.png", dpi=150)
        plt.close()
        print(f"  Saved {name.lower()}_flow_vs_ret.png")

        # Size-weighted flow vs next-tick mid return (same as signed flow here since we already weight)
        res["size_weighted_flow_note"] = "signed_vol_sum is already size-weighted (quantity * sign)"

    else:
        res["sign_imbalance_vs_ret_r"] = np.nan
        res["sign_imbalance_vs_ret_p"] = np.nan

    # 3B: Order book depth distribution
    depth_res = {}
    for d in days:
        sub = prod_prices[prod_prices["day"] == d]
        n = len(sub)
        if n == 0:
            continue
        # Bid side
        bid_lv1 = sub["bid_price_1"].notna().sum()
        bid_lv2 = sub["bid_price_2"].notna().sum()
        bid_lv3 = sub["bid_price_3"].notna().sum()
        ask_lv1 = sub["ask_price_1"].notna().sum()
        ask_lv2 = sub["ask_price_2"].notna().sum()
        ask_lv3 = sub["ask_price_3"].notna().sum()
        depth_res[d] = {
            "n_rows": n,
            "bid_lv1_pct": 100 * bid_lv1 / n,
            "bid_lv2_pct": 100 * bid_lv2 / n,
            "bid_lv3_pct": 100 * bid_lv3 / n,
            "ask_lv1_pct": 100 * ask_lv1 / n,
            "ask_lv2_pct": 100 * ask_lv2 / n,
            "ask_lv3_pct": 100 * ask_lv3 / n,
        }
        print(f"  {name} day={d}: bid L1={100*bid_lv1/n:.1f}% L2={100*bid_lv2/n:.1f}% L3={100*bid_lv3/n:.1f}%")
        print(f"           ask L1={100*ask_lv1/n:.1f}% L2={100*ask_lv2/n:.1f}% L3={100*ask_lv3/n:.1f}%")
    res["depth_pct"] = depth_res

    # Stacked bar chart of depth fractions
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for side_idx, (side, col_prefix) in enumerate([("Bid", "bid"), ("Ask", "ask")]):
        ax = axes[side_idx]
        day_labels = [str(d) for d in days]
        lv1_vals = [depth_res.get(d, {}).get(f"{col_prefix}_lv1_pct", 0) for d in days]
        lv2_vals = [depth_res.get(d, {}).get(f"{col_prefix}_lv2_pct", 0) for d in days]
        lv3_vals = [depth_res.get(d, {}).get(f"{col_prefix}_lv3_pct", 0) for d in days]
        ax.bar(day_labels, lv1_vals, label="Level 1", color="steelblue")
        ax.bar(day_labels, [v - lv1_vals[i] for i, v in enumerate(lv2_vals)], bottom=lv1_vals, label="Level 2", color="orange", alpha=0.7)
        ax.bar(day_labels, [max(0, v - lv2_vals[i]) for i, v in enumerate(lv3_vals)], bottom=lv2_vals, label="Level 3", color="green", alpha=0.7)
        ax.set_title(f"{name} {side} Depth Coverage %")
        ax.set_xlabel("Day")
        ax.set_ylabel("% of rows with level quoted")
        ax.legend()
    plt.suptitle(f"{name} Order Book Depth Distribution")
    plt.tight_layout()
    plt.savefig(f"{PLOTS_DIR}/{name.lower()}_depth_distribution.png", dpi=150)
    plt.close()
    print(f"  Saved {name.lower()}_depth_distribution.png")

    results["microstructure"][name] = res

# 3C: Bot identity recovery
print("\n  --- Bot Identity Recovery ---")
bot_res = {}
for sym, t_df in [("ACO", ACO_trades), ("IPR", IPR_trades)]:
    buyers = t_df["buyer"].dropna().unique().tolist() if "buyer" in t_df.columns else []
    sellers = t_df["seller"].dropna().unique().tolist() if "seller" in t_df.columns else []
    # Remove numeric-looking NaN strings
    named_buyers = [b for b in buyers if isinstance(b, str)]
    named_sellers = [s for s in sellers if isinstance(s, str)]
    all_named = list(set(named_buyers + named_sellers))
    print(f"  {sym} named bots: {all_named}")
    bot_res[sym] = {"named_bots": all_named}

    # For each named bot, check if their trades cluster at intraday extremes
    extremes_res = {}
    for bot in all_named:
        sub_buy = t_df[(t_df["buyer"] == bot)].copy()
        sub_sell = t_df[(t_df["seller"] == bot)].copy()
        day_extreme_hits = []
        for d in days:
            pp = ACO_prices if sym == "ACO" else IPR_prices
            day_prices = pp[pp["day"] == d]["mid_price"]
            if len(day_prices) == 0:
                continue
            day_lo = day_prices.min()
            day_hi = day_prices.max()
            price_range = day_hi - day_lo
            if price_range == 0:
                continue
            bot_buys_day = sub_buy[sub_buy["day"] == d]["price"].values
            bot_sells_day = sub_sell[sub_sell["day"] == d]["price"].values
            # "Near low" = within 5% of range from low
            near_lo_thresh = day_lo + 0.1 * price_range
            near_hi_thresh = day_hi - 0.1 * price_range
            buy_at_low = np.sum(bot_buys_day <= near_lo_thresh)
            sell_at_high = np.sum(bot_sells_day >= near_hi_thresh)
            day_extreme_hits.append({
                "day": d, "buy_at_low": int(buy_at_low), "sell_at_high": int(sell_at_high),
                "total_buys": len(bot_buys_day), "total_sells": len(bot_sells_day)
            })
        extremes_res[bot] = day_extreme_hits
        print(f"    {sym} bot={bot}: extreme hits by day: {day_extreme_hits}")
    bot_res[sym]["extremes"] = extremes_res

results["bot_identity"] = bot_res

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — Cross-Product Analysis
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Section 4: Cross-Product Analysis ===")
results["cross_product"] = {}

# Align ACO and IPR on (day, timestamp)
aco_ts = ACO_prices[["day", "timestamp", "mid_price", "ret"]].rename(columns={"mid_price": "aco_mid", "ret": "aco_ret"})
ipr_ts = IPR_prices[["day", "timestamp", "mid_price", "ret"]].rename(columns={"mid_price": "ipr_mid", "ret": "ipr_ret"})

merged_cross = pd.merge(aco_ts, ipr_ts, on=["day", "timestamp"], how="inner")
print(f"  Merged cross-product rows: {len(merged_cross)}")

# Level correlation
r_lev, p_lev = stats.pearsonr(merged_cross["aco_mid"], merged_cross["ipr_mid"])
# Return correlation
ret_valid = merged_cross.dropna(subset=["aco_ret", "ipr_ret"])
if len(ret_valid) > 5:
    r_ret, p_ret = stats.pearsonr(ret_valid["aco_ret"], ret_valid["ipr_ret"])
else:
    r_ret, p_ret = np.nan, np.nan
print(f"  ACO vs IPR level corr: r={r_lev:.4f}, p={p_lev:.4f}")
print(f"  ACO vs IPR return corr: r={r_ret:.4f}, p={p_ret:.4f}")
results["cross_product"]["level_corr_r"] = float(r_lev)
results["cross_product"]["level_corr_p"] = float(p_lev)
results["cross_product"]["return_corr_r"] = float(r_ret)
results["cross_product"]["return_corr_p"] = float(p_ret)

# Scatter plot
fig, axes = plt.subplots(1, 2, figsize=(12, 4))
axes[0].scatter(merged_cross["aco_mid"], merged_cross["ipr_mid"], alpha=0.1, s=5)
axes[0].set_title(f"ACO vs IPR Mid Levels\nr={r_lev:.3f}, p={p_lev:.4f}")
axes[0].set_xlabel("ACO Mid Price")
axes[0].set_ylabel("IPR Mid Price")
axes[1].scatter(ret_valid["aco_ret"], ret_valid["ipr_ret"], alpha=0.1, s=5)
axes[1].set_title(f"ACO vs IPR Returns\nr={r_ret:.3f}, p={p_ret:.4f}")
axes[1].set_xlabel("ACO Return")
axes[1].set_ylabel("IPR Return")
plt.tight_layout()
plt.savefig(f"{PLOTS_DIR}/cross_product_corr.png", dpi=150)
plt.close()
print("  Saved cross_product_corr.png")

# Engle-Granger cointegration (after ADF confirms unit roots for both)
# Use day-by-day to avoid non-stationarity from trend in IPR
from statsmodels.tsa.stattools import coint

coint_results = []
for d in days:
    sub = merged_cross[merged_cross["day"] == d].dropna(subset=["aco_mid", "ipr_mid"])
    if len(sub) < 20:
        continue
    t_stat, p_val, crit = coint(sub["aco_mid"], sub["ipr_mid"])
    coint_results.append({"day": d, "coint_stat": float(t_stat), "coint_pval": float(p_val)})
    print(f"  Engle-Granger coint day={d}: stat={t_stat:.4f}, p={p_val:.4f}")
results["cross_product"]["cointegration"] = coint_results

# If cointegrated, plot spread for each day
# Estimate hedge ratio via OLS: IPR = a + b*ACO + eps
fig, axes = plt.subplots(1, len(days), figsize=(15, 4))
for i, d in enumerate(days):
    sub = merged_cross[merged_cross["day"] == d].dropna(subset=["aco_mid", "ipr_mid"])
    if len(sub) < 20:
        continue
    ols_r = OLS(sub["ipr_mid"].values, add_constant(sub["aco_mid"].values)).fit()
    spread = sub["ipr_mid"].values - ols_r.params[0] - ols_r.params[1] * sub["aco_mid"].values
    axes[i].plot(sub["timestamp"].values, spread, linewidth=0.5)
    axes[i].set_title(f"Day {d} ACO-IPR Spread (OLS residual)")
    axes[i].set_xlabel("Timestamp")
    axes[i].set_ylabel("Residual")
plt.suptitle("ACO vs IPR Cointegration Spread")
plt.tight_layout()
plt.savefig(f"{PLOTS_DIR}/cross_product_spread.png", dpi=150)
plt.close()
print("  Saved cross_product_spread.png")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — Day / Regime Effect
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Section 5: Day / Regime Effect ===")
results["regime"] = {}

regime_rows = []
for df, name in [(ACO_prices, "ACO"), (IPR_prices, "IPR")]:
    for d in days:
        sub = df[df["day"] == d]["mid_price"].dropna()
        ret_sub = df[df["day"] == d]["ret"].dropna()
        if len(sub) < 2:
            continue
        vol = ret_sub.std()
        rng = sub.max() - sub.min()
        drift = sub.iloc[-1] - sub.iloc[0]
        regime_rows.append({
            "product": name, "day": d,
            "n_rows": len(sub),
            "volatility_per_tick": vol,
            "range": rng,
            "drift": drift,
        })
        print(f"  {name} day={d}: vol={vol:.4f}, range={rng:.1f}, drift={drift:.1f}")

regime_df = pd.DataFrame(regime_rows)
results["regime"]["table"] = regime_df.to_dict("records")

# Intraday pattern: 4 quartiles by timestamp, mean return per quartile per product per day
quartile_rows = []
for df, name in [(ACO_prices, "ACO"), (IPR_prices, "IPR")]:
    for d in days:
        sub = df[df["day"] == d].dropna(subset=["ret"]).copy()
        if len(sub) < 40:
            continue
        sub["q"] = pd.qcut(sub["timestamp"], 4, labels=["Q1", "Q2", "Q3", "Q4"])
        qmeans = sub.groupby("q", observed=True)["ret"].mean()
        for q, m in qmeans.items():
            quartile_rows.append({"product": name, "day": d, "quartile": q, "mean_ret": m})

quartile_df = pd.DataFrame(quartile_rows)
results["regime"]["quartile"] = quartile_df.to_dict("records")

# Plot quartile mean returns
fig, axes = plt.subplots(2, 3, figsize=(15, 8))
for i, (df, name) in enumerate([(ACO_prices, "ACO"), (IPR_prices, "IPR")]):
    for j, d in enumerate(days):
        ax = axes[i][j]
        sub = quartile_df[(quartile_df["product"] == name) & (quartile_df["day"] == d)]
        if len(sub) == 0:
            ax.set_visible(False)
            continue
        ax.bar(sub["quartile"].astype(str), sub["mean_ret"], color="steelblue")
        ax.axhline(0, color="black", linewidth=0.8)
        ax.set_title(f"{name} Day {d} Intraday Mean Return")
        ax.set_xlabel("Timestamp Quartile")
        ax.set_ylabel("Mean Return (XIRECS)")
plt.suptitle("Intraday Return Pattern by Quartile")
plt.tight_layout()
plt.savefig(f"{PLOTS_DIR}/intraday_quartile_returns.png", dpi=150)
plt.close()
print("  Saved intraday_quartile_returns.png")

# ─────────────────────────────────────────────────────────────────────────────
# Also: ACO mid price over all days (for visual check)
# ─────────────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(14, 4))
for ax, df, name in [(axes[0], ACO_prices, "ACO"), (axes[1], IPR_prices, "IPR")]:
    for d in days:
        sub = df[df["day"] == d]
        ax.plot(sub["timestamp"], sub["mid_price"], label=f"Day {d}", linewidth=0.8)
    ax.set_title(f"{name} Mid Price by Day")
    ax.set_xlabel("Timestamp")
    ax.set_ylabel("Mid Price (XIRECS)")
    ax.legend()
plt.tight_layout()
plt.savefig(f"{PLOTS_DIR}/mid_price_all_days.png", dpi=150)
plt.close()
print("  Saved mid_price_all_days.png")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 — ACO "Hidden Pattern" Test (intraday periodicity)
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Section 6: ACO Intraday Pattern ===")
# Check if ACO has a repeating intraday cycle via autocorrelation at longer lags
aco_day0 = ACO_prices[ACO_prices["day"] == 0]["mid_price"].dropna().values
ac_long = []
for lag in [100, 200, 500, 1000, 2000, 5000]:
    if len(aco_day0) > lag:
        ac = float(np.corrcoef(aco_day0[:-lag], aco_day0[lag:])[0, 1])
        ac_long.append({"lag": lag, "acf": ac})
        print(f"  ACO level autocorr at lag {lag}: {ac:.4f}")
results["aco_pattern"] = ac_long

fig, ax = plt.subplots(figsize=(8, 4))
ax.bar([str(r["lag"]) for r in ac_long], [r["acf"] for r in ac_long], color="steelblue")
ax.set_title("ACO Mid-Price Level Autocorrelation (Day 0) — Long Lags")
ax.set_xlabel("Lag (timesteps)")
ax.set_ylabel("Autocorrelation")
plt.tight_layout()
plt.savefig(f"{PLOTS_DIR}/aco_long_lag_autocorr.png", dpi=150)
plt.close()
print("  Saved aco_long_lag_autocorr.png")

# ACO rolling mean / range by day (to detect cyclic patterns)
fig, axes = plt.subplots(1, 3, figsize=(15, 4))
for j, d in enumerate(days):
    sub = ACO_prices[ACO_prices["day"] == d].copy()
    sub = sub.sort_values("timestamp")
    sub["rolling_mid"] = sub["mid_price"].rolling(200, center=True, min_periods=10).mean()
    axes[j].plot(sub["timestamp"], sub["mid_price"], alpha=0.4, linewidth=0.5, label="Mid")
    axes[j].plot(sub["timestamp"], sub["rolling_mid"], color="red", linewidth=1.5, label="200-ts rolling mean")
    axes[j].set_title(f"ACO Day {d}")
    axes[j].set_xlabel("Timestamp")
    axes[j].set_ylabel("Mid Price")
    axes[j].legend()
plt.suptitle("ACO Mid Price + 200-Timestep Rolling Mean")
plt.tight_layout()
plt.savefig(f"{PLOTS_DIR}/aco_rolling_mean.png", dpi=150)
plt.close()
print("  Saved aco_rolling_mean.png")

# ─────────────────────────────────────────────────────────────────────────────
# Save results JSON
# ─────────────────────────────────────────────────────────────────────────────
results_path = "/Users/samuelshi/IMC-Prosperity-2026-personal/Round 1/analysis/r1_eda_results.json"
with open(results_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nAll results saved to {results_path}")

# Count plots
plot_count = len([f for f in os.listdir(PLOTS_DIR) if f.endswith(".png")])
print(f"Total plots saved: {plot_count}")
print("\nAll sections complete.")
