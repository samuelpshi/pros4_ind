"""Sophisticated counterparty analyses:
1. Aggressor (taker) vs maker classification
2. Lead-lag: Mark X net VEV_4000 inventory -> VELVETFRUIT future return
3. Multi-leg trade detection (same trader, same ts, multiple products)
4. Size-as-conviction: per trader, edge per unit by trade size bucket
"""

import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path("/Users/samuelshi/IMC-Prosperity-2026-personal/R4/analysis/counterparty")
T = pd.read_pickle(OUT / "trades_enriched.pkl")
P = pd.read_pickle(OUT / "mid_panel.pkl")

# === 1) AGGRESSOR CLASSIFICATION ===
# A trade at the prevailing ask -> buyer was aggressor (took the offer).
# A trade at the prevailing bid -> seller was aggressor (hit the bid).
# Trades inside the spread are ambiguous (often midpoint matches / off-book).
def classify_aggressor(row):
    if pd.isna(row["bid_price_1"]) or pd.isna(row["ask_price_1"]):
        return "unknown"
    p = row["price"]
    bid, ask = row["bid_price_1"], row["ask_price_1"]
    # Allow tiny tolerance for floating-point
    if p >= ask - 1e-6:
        return "buyer"   # buyer aggressor
    if p <= bid + 1e-6:
        return "seller"  # seller aggressor
    return "inside"      # inside the spread / matched midpoint / cross

T["aggressor"] = T.apply(classify_aggressor, axis=1)

# Aggressor share per trader, split by buy/sell role
def aggr_share(group, role):
    sub = group[group[role] == group["trader_focus"]]
    if len(sub) == 0: return np.nan
    target = "buyer" if role == "buyer" else "seller"
    return (sub["aggressor"] == target).mean()

# Build per-trader aggressor stats
print("=== Aggressor mix per trader (overall) ===")
rows = []
for trader in sorted(set(T.buyer) | set(T.seller)):
    bf = T[T.buyer == trader]   # rows where trader is buyer
    sf = T[T.seller == trader]  # rows where trader is seller
    n_buy = len(bf); n_sell = len(sf)
    buy_aggr = (bf["aggressor"] == "buyer").sum() if n_buy else 0
    sell_aggr = (sf["aggressor"] == "seller").sum() if n_sell else 0
    inside_buy = (bf["aggressor"] == "inside").sum()
    inside_sell = (sf["aggressor"] == "inside").sum()
    # If they were buyer, count when seller was aggressor (i.e., the trader was passive maker)
    passive_buy = (bf["aggressor"] == "seller").sum()    # trader sat on the bid, seller crossed (rare; usually means trader's bid got hit?)
    # Actually if trade at bid -> seller aggressor -> the buyer (this trader) was the resting bid -> passive
    passive_sell = (sf["aggressor"] == "buyer").sum()
    rows.append({
        "trader": trader,
        "n_as_buyer": n_buy,
        "buy_aggr_pct": buy_aggr / max(n_buy,1),     # bought at ask = took offer
        "buy_passive_pct": passive_buy / max(n_buy,1),  # buy at bid = was resting bid
        "buy_inside_pct": inside_buy / max(n_buy,1),
        "n_as_seller": n_sell,
        "sell_aggr_pct": sell_aggr / max(n_sell,1),  # sold at bid = hit bid
        "sell_passive_pct": passive_sell / max(n_sell,1),  # sold at ask = was resting offer
        "sell_inside_pct": inside_sell / max(n_sell,1),
    })
df_aggr = pd.DataFrame(rows).round(2)
print(df_aggr.to_string(index=False))

# Aggressor edge: edge_close conditioned on whether trader was taker
print("\n=== Edge_close conditioned on aggressor role (per trader) ===")
edge_rows = []
for trader in sorted(set(T.buyer) | set(T.seller)):
    bf = T[T.buyer == trader].copy(); bf["side"] = +1
    sf = T[T.seller == trader].copy(); sf["side"] = -1
    both = pd.concat([bf, sf], ignore_index=True)
    both["edge_close"] = both["side"] * (both["day_close"] - both["price"]) * both["quantity"]
    # Was this trader the aggressor on this fill?
    both["was_aggr"] = ((both["side"] == 1) & (both["aggressor"] == "buyer")) | \
                      ((both["side"] == -1) & (both["aggressor"] == "seller"))
    g = both.groupby("was_aggr")["edge_close"].agg(["count", "sum", "mean"]).reset_index()
    for _, r in g.iterrows():
        edge_rows.append({"trader": trader, "was_aggressor": bool(r["was_aggr"]),
                          "n": int(r["count"]), "edge_total": r["sum"], "edge_per_fill": r["mean"]})
edge_df = pd.DataFrame(edge_rows)
print(edge_df.round(2).to_string(index=False))

# === 2) LEAD-LAG: Mark X VEV_4000 net inventory -> VELVETFRUIT 5k-tick forward return ===
print("\n=== Lead-lag: trader net inventory in VEV_4000 vs VELVETFRUIT next-5k mid move ===")
# For each trader who trades VEV_4000, compute their cumulative inventory over time;
# then merge against VELVETFRUIT mid 5k ticks later; look at correlation per trader.
vev = T[T.symbol == "VEV_4000"].copy()
vfx = P[P.symbol == "VELVETFRUIT_EXTRACT"][["day", "timestamp", "mid_price"]].copy()
vfx = vfx.sort_values(["day", "timestamp"]).rename(columns={"mid_price": "vfx_mid"})

# Build per-trader signed quantity flow from VEV_4000 trades
def trader_signed_flow(trader, sym):
    s1 = T[(T.buyer == trader) & (T.symbol == sym)].copy()
    s1["signed"] = s1["quantity"]
    s2 = T[(T.seller == trader) & (T.symbol == sym)].copy()
    s2["signed"] = -s2["quantity"]
    return pd.concat([s1, s2])[["day", "timestamp", "signed"]].sort_values(["day", "timestamp"])

for trader in ["Mark 14", "Mark 38", "Mark 01", "Mark 22"]:
    flow = trader_signed_flow(trader, "VEV_4000").reset_index(drop=True)
    if len(flow) < 30: continue
    flow["cum_pos"] = flow.groupby("day")["signed"].cumsum()
    flow["_idx"] = np.arange(len(flow))

    # vfx mid 5k ticks after fill
    L = flow[["day", "timestamp", "_idx"]].copy()
    L["timestamp"] = L["timestamp"] + 5000
    L = L.sort_values(["timestamp", "day"]).reset_index(drop=True)
    R = vfx.sort_values(["timestamp", "day"]).reset_index(drop=True)
    m_fwd = pd.merge_asof(L, R, on="timestamp", by="day", direction="forward")
    fwd = m_fwd.sort_values("_idx").set_index("_idx")["vfx_mid"]

    # vfx mid AT fill time
    L0 = flow[["day", "timestamp", "_idx"]].sort_values(["timestamp", "day"]).reset_index(drop=True)
    m_now = pd.merge_asof(L0, R, on="timestamp", by="day", direction="backward")
    now = m_now.sort_values("_idx").set_index("_idx")["vfx_mid"]

    flow["vfx_now"] = flow["_idx"].map(now)
    flow["vfx_5k_later"] = flow["_idx"].map(fwd)
    flow["vfx_5k_ret"] = flow["vfx_5k_later"] - flow["vfx_now"]
    # Correlation between cum_pos (or signed flow) and forward vfx return
    corr_signed = flow[["signed", "vfx_5k_ret"]].corr().iloc[0,1]
    corr_pos = flow[["cum_pos", "vfx_5k_ret"]].corr().iloc[0,1]
    # Mean future return when trader is BUYING vs SELLING
    buy_ret = flow.loc[flow["signed"] > 0, "vfx_5k_ret"].mean()
    sell_ret = flow.loc[flow["signed"] < 0, "vfx_5k_ret"].mean()
    print(f"  {trader}: corr(signed_qty, vfx_5k_ret)={corr_signed:+.3f} | "
          f"corr(cum_pos, vfx_5k_ret)={corr_pos:+.3f} | "
          f"vfx_5k mean: BUY={buy_ret:+.2f} SELL={sell_ret:+.2f} (n_b={flow.signed.gt(0).sum()}, n_s={flow.signed.lt(0).sum()})")

# === 3) MULTI-LEG TRADE DETECTION ===
print("\n=== Multi-leg trades: same trader+counterparty trading multiple products at same timestamp ===")
# Group by (day, timestamp, buyer, seller) and count distinct symbols
ml = T.groupby(["day", "timestamp", "buyer", "seller"])["symbol"].agg(list).reset_index()
ml["n_legs"] = ml["symbol"].apply(len)
ml = ml[ml["n_legs"] >= 2].sort_values("n_legs", ascending=False)
print(f"Total multi-leg events: {len(ml)}")
print("Top 15 by leg count:")
print(ml.head(15).to_string(index=False))

# Aggregate: for each trader pair, how many multi-leg trades?
print("\nMulti-leg event count by (buyer, seller) pair:")
pair_ml = ml.groupby(["buyer","seller"]).size().reset_index(name="n_multileg_events")
print(pair_ml.sort_values("n_multileg_events", ascending=False).to_string(index=False))

# === 4) SIZE-AS-CONVICTION ===
print("\n=== Size-as-conviction: edge per unit by trade-size quantile, per trader ===")
def trader_view(T):
    rows = []
    for side, who in ((+1, "buyer"), (-1, "seller")):
        sub = T.copy(); sub["trader"] = sub[who]; sub["side"] = side
        rows.append(sub)
    V = pd.concat(rows, ignore_index=True)
    V["edge_close"] = V["side"] * (V["day_close"] - V["price"]) * V["quantity"]
    V["edge_per_unit"] = V["side"] * (V["day_close"] - V["price"])
    return V
V = trader_view(T)

for trader in sorted(set(T.buyer) | set(T.seller)):
    sub = V[V.trader == trader]
    if len(sub) < 100:
        continue
    # 4-quantile by quantity
    try:
        sub = sub.assign(qty_q=pd.qcut(sub["quantity"], 4, duplicates="drop", labels=False))
    except ValueError:
        continue
    g = sub.groupby("qty_q").agg(
        n=("quantity","size"),
        avg_qty=("quantity","mean"),
        edge_per_unit=("edge_per_unit","mean"),
        edge_close=("edge_close","sum"),
    ).round(2)
    print(f"\n{trader}:")
    print(g.to_string())
