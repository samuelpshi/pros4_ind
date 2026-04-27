"""Round 2 of sophisticated probes:
  #3  Microprice edge (vs mid edge) — does book imbalance refine the picture?
  #10 Inter-arrival pacing for Mark 67 — does sudden compression precede edge?
  #11 Pre-jump trader composition — who is on the right side BEFORE big mid moves?
  #12 Cross-day stability ranking — which signals replicate?
"""

import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path("/Users/samuelshi/IMC-Prosperity-2026-personal/R4/analysis/counterparty")
T = pd.read_pickle(OUT / "trades_enriched.pkl")
P = pd.read_pickle(OUT / "mid_panel.pkl")

# We need bid/ask volume to compute microprice. Reload from raw prices.
DAYS = [1, 2, 3]
DATA = Path("/Users/samuelshi/IMC-Prosperity-2026-personal/R4/r4_datacap")
parts = []
for d in DAYS:
    p = pd.read_csv(DATA / f"prices_round_4_day_{d}.csv", sep=";")
    p["day"] = d
    parts.append(p)
PR = pd.concat(parts, ignore_index=True)

# Microprice = (best_bid * ask_size + best_ask * bid_size) / (bid_size + ask_size)
# It pulls toward the heavier side of the book.
PR["bid1"] = PR["bid_price_1"]; PR["ask1"] = PR["ask_price_1"]
PR["bv1"] = PR["bid_volume_1"]; PR["av1"] = PR["ask_volume_1"]
denom = PR["bv1"].fillna(0) + PR["av1"].fillna(0)
PR["microprice"] = np.where(denom > 0,
                            (PR["bid1"]*PR["av1"] + PR["ask1"]*PR["bv1"]) / denom.replace(0, np.nan),
                            PR["mid_price"])
PR_micro = PR[["day", "timestamp", "product", "microprice"]].rename(columns={"product": "symbol"})

# === #3 Microprice edge ===
# Re-merge microprice into trades, then compute edge_micro = side*(microprice_5k - price)*qty
T2 = T.merge(PR_micro, on=["day","symbol","timestamp"], how="left").rename(columns={"microprice":"micro_at_trade"})

# Build forward microprice at +5k via merge_asof
T2["ts_plus_5k"] = T2["timestamp"] + 5000
L = T2[["day","symbol","ts_plus_5k"]].rename(columns={"ts_plus_5k":"timestamp"}).copy()
L["_idx"] = np.arange(len(L))
L = L.sort_values(["timestamp","day","symbol"]).reset_index(drop=True)
R = PR_micro.sort_values(["timestamp","day","symbol"]).reset_index(drop=True)
m = pd.merge_asof(L, R, on="timestamp", by=["day","symbol"], direction="forward")
T2["micro_5k"] = m.sort_values("_idx")["microprice"].values

print("=== #3 Microprice-based edge per fill, per trader ===")
def trader_view(T):
    rows = []
    for side, who in ((+1,"buyer"), (-1,"seller")):
        sub = T.copy(); sub["trader"] = sub[who]; sub["side"] = side
        rows.append(sub)
    V = pd.concat(rows, ignore_index=True)
    V["edge_micro_5k"] = V["side"] * (V["micro_5k"] - V["price"]) * V["quantity"]
    V["edge_mid_5k"]   = V["side"] * (V["mid_plus_5000"] - V["price"]) * V["quantity"]
    V["edge_close"]    = V["side"] * (V["day_close"] - V["price"]) * V["quantity"]
    return V
V = trader_view(T2)

cmp = V.groupby("trader").agg(
    n=("edge_micro_5k","size"),
    edge_mid_5k_per_fill=("edge_mid_5k","mean"),
    edge_micro_5k_per_fill=("edge_micro_5k","mean"),
    edge_close_per_fill=("edge_close","mean"),
).round(2).sort_values("edge_close_per_fill", ascending=False)
print(cmp.to_string())

# Compare per trader: does microprice rank traders differently?
print("\nDifference (micro - mid) per fill:")
print((cmp["edge_micro_5k_per_fill"] - cmp["edge_mid_5k_per_fill"]).round(3).to_string())

# === #10 Mark 67 inter-arrival pacing ===
print("\n=== #10 Mark 67 inter-arrival pacing on VELVETFRUIT ===")
m67 = T[(T.buyer == "Mark 67") & (T.symbol == "VELVETFRUIT_EXTRACT")].sort_values(["day","timestamp"]).copy()
m67["dt"] = m67.groupby("day")["timestamp"].diff()
m67["fwd_5k_ret"] = m67["mid_plus_5000"] - m67["mid_at_trade"]
m67["fwd_close_ret"] = m67["day_close"] - m67["price"]
print(f"Mean inter-arrival (ts): {m67['dt'].mean():.0f}, median: {m67['dt'].median():.0f}, p10: {m67['dt'].quantile(0.1):.0f}, p90: {m67['dt'].quantile(0.9):.0f}")

# Bin pacing: short-gap (compressed), medium, long-gap (slow)
m67_v = m67.dropna(subset=["dt"]).copy()
m67_v["pace_q"] = pd.qcut(m67_v["dt"], 3, labels=["compressed","normal","slow"])
print("\nForward edge by pacing bucket:")
print(m67_v.groupby("pace_q", observed=True).agg(
    n=("dt","size"),
    avg_dt=("dt","mean"),
    fwd_5k_ret=("fwd_5k_ret","mean"),
    fwd_close_ret=("fwd_close_ret","mean"),
    qty=("quantity","mean"),
).round(2).to_string())

# Same for Mark 49 sells
print("\n=== Mark 49 inter-arrival pacing on VELVETFRUIT ===")
m49 = T[(T.seller == "Mark 49") & (T.symbol == "VELVETFRUIT_EXTRACT")].sort_values(["day","timestamp"]).copy()
m49["dt"] = m49.groupby("day")["timestamp"].diff()
m49["fwd_close_ret"] = m49["day_close"] - m49["price"]
m49_v = m49.dropna(subset=["dt"]).copy()
m49_v["pace_q"] = pd.qcut(m49_v["dt"], 3, labels=["compressed","normal","slow"])
print(m49_v.groupby("pace_q", observed=True).agg(
    n=("dt","size"),
    avg_dt=("dt","mean"),
    fwd_close_ret=("fwd_close_ret","mean"),
    qty=("quantity","mean"),
).round(2).to_string())

# === #11 Pre-jump trader composition ===
# For each (day, symbol), find ts where mid moves >= 3*sigma over a 5k tick window.
# Then look at trader net flow in the 20k ticks BEFORE the jump.
print("\n=== #11 Pre-jump trader composition (3-sigma jumps in VELVETFRUIT) ===")
for sym in ["VELVETFRUIT_EXTRACT", "HYDROGEL_PACK"]:
    print(f"\n-- {sym} --")
    for d in DAYS:
        ps = PR[(PR.day == d) & (PR["product"] == sym)].sort_values("timestamp").reset_index(drop=True)
        # 5k-tick rolling forward return
        ps["fwd_ret_5k"] = ps["mid_price"].shift(-50) - ps["mid_price"]   # 50 rows = 5000 ts
        sigma = ps["fwd_ret_5k"].std()
        thr = 3 * sigma
        jumps = ps[ps["fwd_ret_5k"].abs() >= thr].sort_values("fwd_ret_5k", key=abs, ascending=False).head(5)
        for _, j in jumps.iterrows():
            jt = j.timestamp
            window = T[(T.day == d) & (T.symbol == sym) & (T.timestamp >= jt - 20_000) & (T.timestamp < jt)].copy()
            if len(window) == 0: continue
            buyer_flow = window.groupby("buyer")["quantity"].sum()
            seller_flow = window.groupby("seller")["quantity"].sum()
            net = buyer_flow.subtract(seller_flow, fill_value=0)
            sign = "UP" if j.fwd_ret_5k > 0 else "DOWN"
            print(f"  day {d} ts={jt} | jump {sign} {j.fwd_ret_5k:+.1f} (sigma={sigma:.2f}) | "
                  f"pre-window n_trades={len(window)} | net flow: "
                  + ", ".join(f"{k}{net[k]:+.0f}" for k in net.sort_values(key=abs, ascending=False).index[:5]))

# === #12 Cross-day stability ranking ===
print("\n=== #12 Cross-day stability ranking — per (trader, symbol) edge_close per unit ===")
def per_unit(group):
    if group.quantity.sum() == 0: return 0
    return (group.side * (group.day_close - group.price) * group.quantity).sum() / group.quantity.sum()

V = trader_view(T2)
agg = V.groupby(["trader","symbol","day"]).apply(per_unit, include_groups=False).reset_index(name="edge_per_unit")
agg_pivot = agg.pivot_table(index=["trader","symbol"], columns="day", values="edge_per_unit").reset_index()
agg_pivot["mean"] = agg_pivot[[1,2,3]].mean(axis=1)
agg_pivot["std"] = agg_pivot[[1,2,3]].std(axis=1)
agg_pivot["min_day"] = agg_pivot[[1,2,3]].min(axis=1)
# Stability: positive on every day OR negative on every day
agg_pivot["stable_pos"] = (agg_pivot[[1,2,3]] > 0).all(axis=1)
agg_pivot["stable_neg"] = (agg_pivot[[1,2,3]] < 0).all(axis=1)
agg_pivot["sign_consistent"] = agg_pivot["stable_pos"] | agg_pivot["stable_neg"]

# Filter to non-trivial sample sizes
counts = V.groupby(["trader","symbol"])["quantity"].sum().rename("total_qty")
agg_pivot = agg_pivot.merge(counts.reset_index(), on=["trader","symbol"])
agg_pivot = agg_pivot[agg_pivot["total_qty"] >= 30]

print("\nStable POSITIVE-edge cells (winning every day, |total_qty| >= 30):")
sp = agg_pivot[agg_pivot.stable_pos].sort_values("mean", ascending=False)
print(sp[["trader","symbol",1,2,3,"mean","total_qty"]].round(2).to_string(index=False))

print("\nStable NEGATIVE-edge cells (losing every day):")
sn = agg_pivot[agg_pivot.stable_neg].sort_values("mean")
print(sn[["trader","symbol",1,2,3,"mean","total_qty"]].round(2).to_string(index=False))

print("\nUNSTABLE cells (sign flipped across days), top by |mean|:")
un = agg_pivot[~agg_pivot.sign_consistent].copy()
un["abs_mean"] = un["mean"].abs()
print(un.sort_values("abs_mean", ascending=False).head(15)[
    ["trader","symbol",1,2,3,"mean","std","total_qty"]].round(2).to_string(index=False))
