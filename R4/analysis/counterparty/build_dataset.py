"""Build the master trade-level analysis dataframe for R4 counterparty analysis.

Joins each trade against:
  - mid at trade time (from prices CSV, same product, same timestamp)
  - mid at +H ticks for several horizons
  - end-of-day mid for that product
  - day's high/low/close mid (for percentile timing analysis)

Outputs:
  R4/analysis/counterparty/trades_enriched.parquet
  R4/analysis/counterparty/mid_panel.parquet
"""

import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path("/Users/samuelshi/IMC-Prosperity-2026-personal/R4")
DATA = ROOT / "r4_datacap"
OUT = ROOT / "analysis" / "counterparty"
OUT.mkdir(parents=True, exist_ok=True)

DAYS = [1, 2, 3]
HORIZONS = [100, 1_000, 5_000, 50_000]  # ticks ahead

def load_prices():
    parts = []
    for d in DAYS:
        p = pd.read_csv(DATA / f"prices_round_4_day_{d}.csv", sep=";")
        p["day"] = d
        parts.append(p)
    P = pd.concat(parts, ignore_index=True)
    P["mid_price"] = pd.to_numeric(P["mid_price"], errors="coerce")
    return P[["day", "timestamp", "product", "mid_price",
              "bid_price_1", "ask_price_1"]].rename(columns={"product": "symbol"})

def load_trades():
    parts = []
    for d in DAYS:
        t = pd.read_csv(DATA / f"trades_round_4_day_{d}.csv", sep=";")
        t["day"] = d
        parts.append(t)
    T = pd.concat(parts, ignore_index=True)
    return T

def main():
    P = load_prices()
    T = load_trades()

    # Pivot mids per (day, symbol) into ts-indexed series for efficient horizon lookup.
    P_sorted = P.sort_values(["day", "symbol", "timestamp"]).reset_index(drop=True)

    # Build a long mid panel keyed on (day, symbol, ts) -> mid
    mid_panel = P_sorted.set_index(["day", "symbol", "timestamp"])["mid_price"].sort_index()

    # Day high/low/close mid for percentile-of-day timing
    dhlc = (P_sorted.groupby(["day", "symbol"])["mid_price"]
            .agg(day_high="max", day_low="min",
                 day_open="first", day_close="last").reset_index())

    # Merge mid at trade time
    T2 = T.merge(P_sorted[["day", "symbol", "timestamp", "mid_price",
                           "bid_price_1", "ask_price_1"]],
                 on=["day", "symbol", "timestamp"], how="left")
    T2 = T2.rename(columns={"mid_price": "mid_at_trade"})

    # Merge horizon mids
    for H in HORIZONS:
        T2[f"ts_plus_{H}"] = T2["timestamp"] + H

    # Build forward-mid lookup using merge_asof per (day, symbol) on a sorted ts axis.
    # Strategy: for each horizon, do merge_asof against the price panel.
    P_for_asof = P_sorted[["day", "symbol", "timestamp", "mid_price"]].copy()

    def fwd_mid(target_col, out_col):
        T_local = T2[["day", "symbol", target_col]].copy()
        T_local = T_local.rename(columns={target_col: "timestamp"})
        T_local["_idx"] = np.arange(len(T_local))
        # merge_asof requires global sort on the on-key
        L = T_local.sort_values(["timestamp", "day", "symbol"]).reset_index(drop=True)
        R = P_for_asof.sort_values(["timestamp", "day", "symbol"]).reset_index(drop=True)
        merged = pd.merge_asof(L, R, on="timestamp", by=["day", "symbol"],
                               direction="forward", allow_exact_matches=True)
        merged = merged.sort_values("_idx")
        T2[out_col] = merged["mid_price"].values

    for H in HORIZONS:
        fwd_mid(f"ts_plus_{H}", f"mid_plus_{H}")

    # End-of-day mid (per day,symbol) -- use day_close from dhlc
    T2 = T2.merge(dhlc, on=["day", "symbol"], how="left")

    # Position-of-trade-in-day-range (0=at low, 1=at high)
    rng = (T2["day_high"] - T2["day_low"]).replace(0, np.nan)
    T2["price_pct_of_day"] = (T2["price"] - T2["day_low"]) / rng

    # Save
    T2.to_pickle(OUT / "trades_enriched.pkl")
    P_sorted.to_pickle(OUT / "mid_panel.pkl")
    print(f"Wrote {len(T2)} enriched trades to {OUT/'trades_enriched.pkl'}")
    print(f"Sample columns: {list(T2.columns)}")

if __name__ == "__main__":
    main()
