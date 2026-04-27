"""Focused plots for the candidate informed traders.

Per (trader, product, day):
  Top: price/mid line + that trader's buys (green ^) and sells (red v), sized by quantity.
  Bottom: cumulative signed inventory of that trader through the day.

Then: cumulative inventory across all 3 days for the headline candidates.
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

def trader_fills(trader, symbol, day=None):
    sub = T[T.symbol == symbol]
    if day is not None:
        sub = sub[sub.day == day]
    rows = []
    for _, r in sub.iterrows():
        if r.buyer == trader:
            rows.append({**r.to_dict(), "side": +1})
        if r.seller == trader:
            rows.append({**r.to_dict(), "side": -1})
    return pd.DataFrame(rows)

def focused(trader, symbol, day, fname):
    p = P[(P.day == day) & (P["symbol"] == symbol)].sort_values("timestamp")
    f = trader_fills(trader, symbol, day)
    if len(p) == 0:
        return
    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]})
    ax = axes[0]
    ax.plot(p.timestamp, p.mid_price, color="grey", lw=0.6, alpha=0.7)
    if len(f):
        b = f[f.side == 1]; s = f[f.side == -1]
        if len(b):
            ax.scatter(b.timestamp, b.price, marker="^", color="#2ca02c",
                       s=8 + 4*b.quantity, alpha=0.75, label=f"{trader} BUY (n={len(b)}, qty={b.quantity.sum()})",
                       edgecolors="black", linewidths=0.3)
        if len(s):
            ax.scatter(s.timestamp, s.price, marker="v", color="#d62728",
                       s=8 + 4*s.quantity, alpha=0.75, label=f"{trader} SELL (n={len(s)}, qty={s.quantity.sum()})",
                       edgecolors="black", linewidths=0.3)
    edge = 0
    if len(f):
        edge = (f.side * (f.day_close - f.price) * f.quantity).sum()
    ax.set_title(f"{trader} on {symbol} day {day}  |  edge_close={edge:+.0f}  |  "
                 f"close={p.mid_price.iloc[-1]:.1f}, range={p.mid_price.min():.1f}–{p.mid_price.max():.1f}")
    ax.legend(loc="upper left")
    ax.set_ylabel("price")

    ax2 = axes[1]
    if len(f):
        f2 = f.sort_values("timestamp").copy()
        f2["signed"] = f2.side * f2.quantity
        f2["pos"] = f2.signed.cumsum()
        ax2.plot(f2.timestamp, f2.pos, color="black", lw=1.0, drawstyle="steps-post")
        ax2.axhline(0, color="grey", lw=0.5)
    ax2.set_ylabel("cum qty (long+, short-)")
    ax2.set_xlabel("timestamp")
    plt.tight_layout()
    fig.savefig(FIG / fname, dpi=110)
    plt.close(fig)

# Headline focused plots
for d in (1, 2, 3):
    focused("Mark 67", "VELVETFRUIT_EXTRACT", d, f"focus_Mark67_VELVETFRUIT_day{d}.png")
    focused("Mark 49", "VELVETFRUIT_EXTRACT", d, f"focus_Mark49_VELVETFRUIT_day{d}.png")
    focused("Mark 14", "HYDROGEL_PACK", d, f"focus_Mark14_HYDROGEL_day{d}.png")
    focused("Mark 38", "HYDROGEL_PACK", d, f"focus_Mark38_HYDROGEL_day{d}.png")
    focused("Mark 14", "VEV_4000", d, f"focus_Mark14_VEV4000_day{d}.png")
    focused("Mark 01", "VEV_5300", d, f"focus_Mark01_VEV5300_day{d}.png")
    focused("Mark 01", "VEV_5400", d, f"focus_Mark01_VEV5400_day{d}.png")

print("Saved focused plots.")
