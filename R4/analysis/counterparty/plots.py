"""Per-product trade overlay plots colored by trader.

For each (product, day), plot mid_price as a thin grey line, then overlay every trade as a
scatter point colored by counterparty. We render two perspectives per panel:
  - top: BUYS by trader (upward triangles)
  - bottom: SELLS by trader (downward triangles)

Saves PNGs to figures/.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

OUT = Path("/Users/samuelshi/IMC-Prosperity-2026-personal/R4/analysis/counterparty")
FIG = OUT / "figures"
FIG.mkdir(exist_ok=True)

T = pd.read_pickle(OUT / "trades_enriched.pkl")
P = pd.read_pickle(OUT / "mid_panel.pkl")

TRADER_COLORS = {
    "Mark 01": "#1f77b4",
    "Mark 14": "#2ca02c",   # green = informed delta-1
    "Mark 22": "#d62728",   # red = high-strike loser
    "Mark 38": "#ff7f0e",   # orange = HYDROGEL/VEV_4000 loser
    "Mark 49": "#8c564b",   # brown = VELVETFRUIT loser
    "Mark 55": "#9467bd",
    "Mark 67": "#e377c2",   # pink = VELVETFRUIT directional buyer
}

PRODUCTS = sorted(T.symbol.unique())
DAYS = [1, 2, 3]

def plot_product_day(symbol, day):
    p = P[(P.day == day) & (P["symbol"] == symbol)].sort_values("timestamp")
    t = T[(T.day == day) & (T["symbol"] == symbol)]
    if len(p) == 0 or len(t) == 0:
        return
    fig, ax = plt.subplots(figsize=(15, 6))
    ax.plot(p["timestamp"], p["mid_price"], color="grey", lw=0.6, alpha=0.7, label="mid")

    for trader in sorted(set(t.buyer.unique()) | set(t.seller.unique())):
        c = TRADER_COLORS.get(trader, "black")
        # Buys (trader is buyer)
        b = t[t.buyer == trader]
        if len(b):
            ax.scatter(b.timestamp, b.price, marker="^", color=c, s=18, alpha=0.7,
                       edgecolors="white", linewidths=0.3,
                       label=f"{trader} BUY ({len(b)} fills)")
        # Sells
        s = t[t.seller == trader]
        if len(s):
            ax.scatter(s.timestamp, s.price, marker="v", color=c, s=18, alpha=0.7,
                       edgecolors="black", linewidths=0.3,
                       label=f"{trader} SELL ({len(s)} fills)")

    ax.set_title(f"{symbol} — day {day} — trades overlaid by trader (▲ buy, ▼ sell)")
    ax.set_xlabel("timestamp")
    ax.set_ylabel("price")
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=7, ncol=1)
    plt.tight_layout()
    out = FIG / f"{symbol}_day{day}.png"
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out

made = []
for sym in PRODUCTS:
    for d in DAYS:
        out = plot_product_day(sym, d)
        if out: made.append(out)

print(f"Saved {len(made)} plots to {FIG}")
for p in made:
    print(f"  {p.name}")
