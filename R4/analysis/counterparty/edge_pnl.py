"""Per-trader directional PnL and timing metrics.

For each trade, build:
  side  = +1 if trader is buyer, -1 if trader is seller
  edge_H = side * (mid_plus_H - price) * quantity     [signed XIRECS at horizon H]
  edge_close = side * (day_close - price) * quantity  [held to EoD]

Aggregates per (trader, product, day) and per (trader).
Also: trade-side timing percentile of day (buyers near low / sellers near high?).

Also computes a simple end-of-day MTM-PnL per trader:
  EoD PnL = sum over fills of [-side * price * qty] + side*qty*day_close
         = sum over fills of side * qty * (day_close - price)
This is "edge_close" summed.

Outputs a Markdown report to stdout and CSVs alongside.
"""

import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path("/Users/samuelshi/IMC-Prosperity-2026-personal/R4/analysis/counterparty")
T = pd.read_pickle(OUT / "trades_enriched.pkl")

HORIZONS = [100, 1_000, 5_000, 50_000]

# Build the per-side trader view (one row per trader-fill: each trade emits 2 rows).
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
    V["cash_flow"] = -V["side"] * V["price"] * V["quantity"]  # buyers pay, sellers receive
    for H in HORIZONS:
        V[f"edge_{H}"] = V["side"] * (V[f"mid_plus_{H}"] - V["price"]) * V["quantity"]
    V["edge_close"] = V["side"] * (V["day_close"] - V["price"]) * V["quantity"]
    # Trade timing percentile: for buyers, low percentile = buying near the day low (good).
    # For sellers, high percentile = selling near the day high (good).
    # Build a unified "timing edge" in [-0.5, 0.5]: side * (0.5 - price_pct_of_day)
    V["timing_edge"] = V["side"] * (0.5 - V["price_pct_of_day"])
    return V

V = trader_view(T)

# === 1) Per-trader, all-product, all-day summary ===
g = V.groupby("trader")
summary = pd.DataFrame({
    "n_fills": g.size(),
    "gross_qty": g["quantity"].sum(),
    "n_buys": g["side"].apply(lambda s: (s == 1).sum()),
    "n_sells": g["side"].apply(lambda s: (s == -1).sum()),
    "edge_close_total": g["edge_close"].sum(),
    "edge_close_per_fill": g["edge_close"].mean(),
    "edge_close_per_unit": g.apply(lambda x: x["edge_close"].sum() / x["quantity"].sum()),
    "edge_5k_total": g["edge_5000"].sum(),
    "edge_5k_per_unit": g.apply(lambda x: x["edge_5000"].sum() / x["quantity"].sum()),
    "edge_50k_total": g["edge_50000"].sum(),
    "edge_50k_per_unit": g.apply(lambda x: x["edge_50000"].sum() / x["quantity"].sum()),
    "timing_mean": g["timing_edge"].mean(),
})
summary = summary.sort_values("edge_close_total", ascending=False)
summary.to_csv(OUT / "trader_summary.csv")
print("=== Per-trader summary (all products, all days) ===")
print(summary.round(2).to_string())

# === 2) Per-trader x product x day directional PnL (edge to close) ===
gpd = V.groupby(["trader", "symbol", "day"])
ppd = pd.DataFrame({
    "n_fills": gpd.size(),
    "gross_qty": gpd["quantity"].sum(),
    "edge_close": gpd["edge_close"].sum(),
    "edge_5k": gpd["edge_5000"].sum(),
    "edge_50k": gpd["edge_50000"].sum(),
}).reset_index()
ppd.to_csv(OUT / "trader_product_day.csv", index=False)

# Print product x trader edge_close pivot per day
print("\n=== edge_close by trader x product (sum across all days) ===")
piv = ppd.groupby(["trader", "symbol"])["edge_close"].sum().unstack(fill_value=0)
print(piv.round(0).to_string())

print("\n=== edge_close by trader x day (sum across products) ===")
piv2 = ppd.groupby(["trader", "day"])["edge_close"].sum().unstack(fill_value=0)
piv2["total"] = piv2.sum(axis=1)
print(piv2.round(0).sort_values("total", ascending=False).to_string())

# === 3) Counterparty matrix: who-vs-who PnL ===
cm = V.groupby(["trader", "counterparty"])["edge_close"].agg(["sum", "count"])
cm.columns = ["edge_close_sum", "n_fills"]
cm = cm.reset_index()
cm.to_csv(OUT / "counterparty_matrix.csv", index=False)
print("\n=== Counterparty matrix (trader vs counterparty) — edge_close_sum ===")
piv3 = cm.pivot_table(index="trader", columns="counterparty",
                      values="edge_close_sum", fill_value=0)
print(piv3.round(0).to_string())

# === 4) Per-trader average trade size & directional bias by product ===
print("\n=== Per-trader, per-product: avg qty, %buy, n_fills ===")
def pct_buy(s): return (s == 1).mean()
ag = V.groupby(["trader", "symbol"]).agg(
    n=("quantity", "size"),
    avg_qty=("quantity", "mean"),
    pct_buy=("side", pct_buy),
    edge_close=("edge_close", "sum"),
).reset_index()
ag.to_csv(OUT / "trader_product_breakdown.csv", index=False)

# === 5) Bootstrap p-value: is edge per fill significantly nonzero per trader? ===
print("\n=== Bootstrap p-value on edge_close > 0 (per trader, all products combined) ===")
rng = np.random.default_rng(0)
boot_rows = []
for trader, grp in V.groupby("trader"):
    e = grp["edge_close"].values
    n = len(e)
    if n < 30: continue
    mean_obs = e.mean()
    # Bootstrap: resample edges with replacement, get distribution of means
    boots = rng.choice(e, size=(2000, n), replace=True).mean(axis=1)
    p_pos = (boots <= 0).mean() if mean_obs > 0 else (boots >= 0).mean()
    boot_rows.append({"trader": trader, "n": n, "mean_edge_close": mean_obs,
                      "boot_p_one_sided": p_pos,
                      "ci_lo": np.quantile(boots, 0.025),
                      "ci_hi": np.quantile(boots, 0.975)})
boot = pd.DataFrame(boot_rows).sort_values("mean_edge_close", ascending=False)
boot.to_csv(OUT / "trader_bootstrap.csv", index=False)
print(boot.round(3).to_string(index=False))

print("\nDone.")
