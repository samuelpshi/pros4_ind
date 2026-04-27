"""Deep dive: WHEN does each trader fire, and how does forward price move?

Per (trader, product), report:
  - first/last fill time, n fills, signed-volume ts-arrival pattern
  - average price percentile of day at trade
  - mean and CI of forward return at H ticks (close-to-trade)
  - "wins": fraction of fills with positive edge_close

Then drill into the four most-suspicious pairs:
  Mark 14 vs Mark 38 (HYDROGEL, VEV_4000)
  Mark 67 vs Mark 49 (VELVETFRUIT)
  Mark 01 (high-strike vouchers)
  Mark 14 (HYDROGEL signal)
"""

import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path("/Users/samuelshi/IMC-Prosperity-2026-personal/R4/analysis/counterparty")
T = pd.read_pickle(OUT / "trades_enriched.pkl")
P = pd.read_pickle(OUT / "mid_panel.pkl")

# Build trader-side view
def trader_view(T):
    rows = []
    for side, who in ((+1, "buyer"), (-1, "seller")):
        sub = T.copy()
        sub["trader"] = sub[who]
        sub["side"] = side
        sub["counterparty"] = sub["seller" if who == "buyer" else "buyer"]
        rows.append(sub)
    V = pd.concat(rows, ignore_index=True)
    V["signed_qty"] = V["side"] * V["quantity"]
    V["edge_close"] = V["side"] * (V["day_close"] - V["price"]) * V["quantity"]
    V["edge_5k"] = V["side"] * (V["mid_plus_5000"] - V["price"]) * V["quantity"]
    V["edge_50k"] = V["side"] * (V["mid_plus_50000"] - V["price"]) * V["quantity"]
    V["fill_won_close"] = V["edge_close"] > 0
    V["fill_won_5k"] = V["edge_5k"] > 0
    return V

V = trader_view(T)

# === 1) Per (trader, symbol, day) timing summary ===
def summarize(group):
    n = len(group)
    return pd.Series({
        "n": n,
        "buy_qty": group.loc[group.side==1, "quantity"].sum(),
        "sell_qty": group.loc[group.side==-1, "quantity"].sum(),
        "first_ts": group["timestamp"].min(),
        "last_ts": group["timestamp"].max(),
        "median_ts": int(group["timestamp"].median()),
        "buy_pct_of_day": group.loc[group.side==1, "price_pct_of_day"].mean(),
        "sell_pct_of_day": group.loc[group.side==-1, "price_pct_of_day"].mean(),
        "edge_close": group["edge_close"].sum(),
        "edge_5k": group["edge_5k"].sum(),
        "win_rate_close": group["fill_won_close"].mean(),
        "win_rate_5k": group["fill_won_5k"].mean(),
        "edge_close_per_unit": group["edge_close"].sum() / max(group["quantity"].sum(), 1),
    })

per = V.groupby(["trader", "symbol", "day"]).apply(summarize, include_groups=False).reset_index()
per.to_csv(OUT / "trader_symbol_day_timing.csv", index=False)

# === 2) Focus traders ===
print("=" * 100)
print("FOCUS: Mark 14 (suspected informed delta-1 trader)")
print("=" * 100)
m = per[per.trader == "Mark 14"].sort_values(["symbol", "day"])
print(m.round(2).to_string(index=False))

print("\n" + "=" * 100)
print("FOCUS: Mark 67 (only-buys VELVETFRUIT, suspected directional signal)")
print("=" * 100)
m = per[per.trader == "Mark 67"].sort_values(["symbol", "day"])
print(m.round(2).to_string(index=False))

print("\n" + "=" * 100)
print("FOCUS: Mark 49 (only-sells VELVETFRUIT, the loser counter-signal)")
print("=" * 100)
m = per[per.trader == "Mark 49"].sort_values(["symbol", "day"])
print(m.round(2).to_string(index=False))

print("\n" + "=" * 100)
print("FOCUS: Mark 01 (informed on high-strike vouchers)")
print("=" * 100)
m = per[per.trader == "Mark 01"].sort_values(["symbol", "day"])
print(m.round(2).to_string(index=False))

print("\n" + "=" * 100)
print("FOCUS: Mark 38 (suspected uninformed loser on HYDROGEL/VEV_4000)")
print("=" * 100)
m = per[per.trader == "Mark 38"].sort_values(["symbol", "day"])
print(m.round(2).to_string(index=False))

print("\n" + "=" * 100)
print("FOCUS: Mark 22 (only-sells vouchers, the high-strike loser)")
print("=" * 100)
m = per[per.trader == "Mark 22"].sort_values(["symbol", "day"])
print(m.round(2).to_string(index=False))

# === 3) Sequential signal: after Mark 67 first BUY of VELVETFRUIT, what does price do? ===
print("\n" + "=" * 100)
print("Mark 67 first-buy-of-day on VELVETFRUIT — does price drift up?")
print("=" * 100)
v67 = V[(V.trader == "Mark 67") & (V.symbol == "VELVETFRUIT_EXTRACT") & (V.side == 1)]
for d in sorted(v67.day.unique()):
    g = v67[v67.day == d].sort_values("timestamp")
    if len(g) == 0: continue
    fbuy = g.iloc[0]
    last_buy = g.iloc[-1]
    px_close = fbuy.day_close
    print(f"day {d}: first buy @ ts={fbuy.timestamp} price={fbuy.price} (mid={fbuy.mid_at_trade}) "
          f"| last buy @ ts={last_buy.timestamp} price={last_buy.price} | day_close={px_close} | "
          f"day_low={fbuy.day_low} day_high={fbuy.day_high} "
          f"| n_buys={len(g)} total_qty={g.quantity.sum()}")

print("\n" + "=" * 100)
print("Mark 49 first-sell-of-day on VELVETFRUIT — does price drift down?")
print("=" * 100)
v49 = V[(V.trader == "Mark 49") & (V.symbol == "VELVETFRUIT_EXTRACT") & (V.side == -1)]
for d in sorted(v49.day.unique()):
    g = v49[v49.day == d].sort_values("timestamp")
    if len(g) == 0: continue
    fs = g.iloc[0]
    ls = g.iloc[-1]
    print(f"day {d}: first sell @ ts={fs.timestamp} price={fs.price} (mid={fs.mid_at_trade}) "
          f"| last sell @ ts={ls.timestamp} price={ls.price} | day_close={fs.day_close} | "
          f"day_low={fs.day_low} day_high={fs.day_high} "
          f"| n_sells={len(g)} total_qty={g.quantity.sum()}")

# === 4) For Mark 14: per-day, when does signal fire and direction? ===
print("\n" + "=" * 100)
print("Mark 14 directional bias on HYDROGEL_PACK by day")
print("=" * 100)
v14h = V[(V.trader == "Mark 14") & (V.symbol == "HYDROGEL_PACK")]
for d in sorted(v14h.day.unique()):
    g = v14h[v14h.day == d]
    nb = (g.side == 1).quantity.sum() if False else g.loc[g.side==1, "quantity"].sum()
    ns = g.loc[g.side==-1, "quantity"].sum()
    edge = g.edge_close.sum()
    open_ = g.day_open.iloc[0]
    close_ = g.day_close.iloc[0]
    print(f"day {d}: buys={nb} sells={ns} net={nb-ns} | edge_close={edge:.0f} | "
          f"day open={open_} close={close_} (range {g.day_low.iloc[0]}–{g.day_high.iloc[0]})")

print("\n" + "=" * 100)
print("Mark 14 directional bias on VEV_4000 by day")
print("=" * 100)
v14v = V[(V.trader == "Mark 14") & (V.symbol == "VEV_4000")]
for d in sorted(v14v.day.unique()):
    g = v14v[v14v.day == d]
    nb = g.loc[g.side==1, "quantity"].sum()
    ns = g.loc[g.side==-1, "quantity"].sum()
    edge = g.edge_close.sum()
    print(f"day {d}: buys={nb} sells={ns} net={nb-ns} | edge_close={edge:.0f} | "
          f"day open={g.day_open.iloc[0]} close={g.day_close.iloc[0]}")

# === 5) Win rate test: for each trader, fraction of fills with positive edge_close ===
print("\n" + "=" * 100)
print("Per-trader fill-level win rate (edge_close > 0)")
print("=" * 100)
wr = V.groupby("trader").agg(
    n_fills=("edge_close","size"),
    win_rate_close=("fill_won_close","mean"),
    win_rate_5k=("fill_won_5k","mean"),
    avg_edge_close=("edge_close","mean"),
).round(3)
print(wr.to_string())
