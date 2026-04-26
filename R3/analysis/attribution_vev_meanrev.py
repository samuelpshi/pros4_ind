"""
Attribution for trader-r3-v1-vev-meanrev.py at the pilot D2 winner config
(ema=50, te=1, sk=1.0, tc=30, qo=2). Reads the persisted run dirs from a
3-day run, reconstructs EMA50 fair value from the prices CSV, classifies
each own_trade as passive_zone vs aggressive_zone based on |price - fv|,
and reports:

  - per-day fill count, PnL (FIFO-realized + mark-to-end), zone split
  - 50-tick-forward "edge captured": qty_signed * (mid[t+50] - price),
    averaged per fill, by zone
  - worst 5-trade-cluster PnL stretches per day to characterize bleed

Zone definitions (te=1, qo=2):
  aggressive_zone: |price - fv| <= 1.5   (take fires at fv +- 1)
  passive_zone:    |price - fv| >  1.5   (passive quotes at fv +- 2 +- skew)

Run as:  python3 R3/analysis/attribution_vev_meanrev.py
"""

from pathlib import Path
import csv
import json

REPO = Path(__file__).resolve().parents[2]
PRICES = {
    0: REPO / "R3/r3_datacap/prices_round_3_day_0.csv",
    1: REPO / "R3/r3_datacap/prices_round_3_day_1.csv",
    2: REPO / "R3/r3_datacap/prices_round_3_day_2.csv",
}
RUN_BASE = Path("/Users/samuelshi/prosperity_rust_backtester/runs")
RUN_PREFIX = "backtest-1777186937237-round3-day-"

EMA_WINDOW = 50
PRODUCT = "VELVETFRUIT_EXTRACT"
ZONE_BOUND = 1.5  # |price-fv| <= 1.5 => aggressive zone
FORWARD_TICKS = 50


def load_mid_series(path):
    """Returns dict timestamp -> mid for VEV from semicolon CSV."""
    mids = {}
    with open(path) as f:
        rdr = csv.DictReader(f, delimiter=";")
        for row in rdr:
            if row["product"] != PRODUCT:
                continue
            t = int(row["timestamp"])
            mid = float(row["mid_price"])
            mids[t] = mid
    return mids


def compute_ema(mids):
    """Returns dict t -> EMA50(mid) using the trader's exact recursion."""
    alpha = 2.0 / (EMA_WINDOW + 1.0)
    ema = None
    out = {}
    for t in sorted(mids):
        m = mids[t]
        ema = m if ema is None else alpha * m + (1.0 - alpha) * ema
        out[t] = ema
    return out


def load_own_trades(run_dir):
    """Returns list of (timestamp, signed_qty, price). signed: +buy, -sell."""
    out = []
    path = run_dir / "trades.csv"
    if not path.exists():
        return out
    with open(path) as f:
        rdr = csv.DictReader(f, delimiter=";")
        for row in rdr:
            if row["symbol"] != PRODUCT:
                continue
            t = int(row["timestamp"])
            qty = int(row["quantity"])
            price = float(row["price"])
            if row["buyer"] == "SUBMISSION":
                out.append((t, +qty, price))
            elif row["seller"] == "SUBMISSION":
                out.append((t, -qty, price))
    return out


def fifo_pnl(trades, final_mid):
    """Realized + mark-to-final via FIFO matching."""
    book = []  # list of [signed_qty_remaining, price]
    realized = 0.0
    for _t, q, p in trades:
        # match against existing opposite-sign book
        while q != 0 and book and (book[0][0] > 0) != (q > 0):
            top = book[0]
            if abs(top[0]) <= abs(q):
                if top[0] > 0:  # book is long, q is short (sell)
                    realized += top[0] * (p - top[1])
                else:
                    realized += (-top[0]) * (top[1] - p)
                q += top[0]  # opposite signs cancel
                book.pop(0)
            else:
                if top[0] > 0:
                    realized += (-q) * (p - top[1])
                else:
                    realized += q * (top[1] - p)
                top[0] += q
                q = 0
        if q != 0:
            book.append([q, p])
    # mark-to-final
    pos = sum(b[0] for b in book)
    avg_cost = (sum(b[0] * b[1] for b in book) / pos) if pos != 0 else 0.0
    mtm = pos * (final_mid - avg_cost)
    return realized, mtm, pos


def attribute_day(day):
    mids = load_mid_series(PRICES[day])
    fv = compute_ema(mids)
    sorted_ts = sorted(mids)
    final_mid = mids[sorted_ts[-1]]
    run_dir = RUN_BASE / f"{RUN_PREFIX}{day}"
    trades = load_own_trades(run_dir)
    # split by zone
    agg_trades, pas_trades = [], []
    for tr in trades:
        t, q, p = tr
        f = fv.get(t)
        if f is None:
            continue
        if abs(p - f) <= ZONE_BOUND:
            agg_trades.append(tr)
        else:
            pas_trades.append(tr)
    # forward-edge per trade
    agg_edge = []
    pas_edge = []
    for bucket, target in ((agg_trades, agg_edge), (pas_trades, pas_edge)):
        for t, q, p in bucket:
            t_fwd = t + FORWARD_TICKS * 100
            # nearest available
            mid_fwd = mids.get(t_fwd)
            if mid_fwd is None:
                # use last available
                avail = [tt for tt in sorted_ts if tt >= t_fwd]
                if not avail:
                    continue
                mid_fwd = mids[avail[0]]
            target.append(q * (mid_fwd - p))
    # FIFO PnL per zone (treating each as a standalone book)
    agg_real, agg_mtm, agg_pos = fifo_pnl(agg_trades, final_mid)
    pas_real, pas_mtm, pas_pos = fifo_pnl(pas_trades, final_mid)
    tot_real, tot_mtm, tot_pos = fifo_pnl(trades, final_mid)
    return {
        "day": day,
        "n_trades": len(trades),
        "n_agg": len(agg_trades),
        "n_pas": len(pas_trades),
        "agg_pnl": agg_real + agg_mtm,
        "pas_pnl": pas_real + pas_mtm,
        "tot_pnl_fifo": tot_real + tot_mtm,
        "tot_pos_end": tot_pos,
        "agg_edge_sum": sum(agg_edge),
        "pas_edge_sum": sum(pas_edge),
        "agg_edge_avg": (sum(agg_edge) / len(agg_edge)) if agg_edge else 0.0,
        "pas_edge_avg": (sum(pas_edge) / len(pas_edge)) if pas_edge else 0.0,
    }


def main():
    print(f"Attribution: ema={EMA_WINDOW}, te=1, sk=1.0, tc=30, qo=2 (pilot D2 winner)")
    print(f"Zone bound: |price-fv| <= {ZONE_BOUND} => aggressive_zone, else passive_zone")
    print(f"Forward edge horizon: {FORWARD_TICKS} ticks (= {FORWARD_TICKS*100} ts units)")
    print()
    print(f"{'day':>3}  {'n':>4}  {'agg':>4}  {'pas':>4}  {'agg_PnL':>9}  {'pas_PnL':>9}  {'tot_FIFO':>9}  {'pos_end':>7}  {'agg_avg':>8}  {'pas_avg':>8}")
    print("-" * 100)
    rows = []
    for d in (0, 1, 2):
        r = attribute_day(d)
        rows.append(r)
        print(f"{r['day']:>3}  {r['n_trades']:>4}  {r['n_agg']:>4}  {r['n_pas']:>4}  "
              f"{r['agg_pnl']:>9.1f}  {r['pas_pnl']:>9.1f}  {r['tot_pnl_fifo']:>9.1f}  "
              f"{r['tot_pos_end']:>7d}  {r['agg_edge_avg']:>8.2f}  {r['pas_edge_avg']:>8.2f}")
    print()
    tot = {
        "agg_pnl": sum(r["agg_pnl"] for r in rows),
        "pas_pnl": sum(r["pas_pnl"] for r in rows),
        "tot_fifo": sum(r["tot_pnl_fifo"] for r in rows),
        "n_agg": sum(r["n_agg"] for r in rows),
        "n_pas": sum(r["n_pas"] for r in rows),
        "agg_edge_sum": sum(r["agg_edge_sum"] for r in rows),
        "pas_edge_sum": sum(r["pas_edge_sum"] for r in rows),
    }
    print(f"3-day totals: agg_PnL={tot['agg_pnl']:.0f} ({tot['n_agg']} fills), "
          f"pas_PnL={tot['pas_pnl']:.0f} ({tot['n_pas']} fills), "
          f"FIFO total={tot['tot_fifo']:.0f}")
    print(f"3-day fwd-edge totals: agg={tot['agg_edge_sum']:.0f}, pas={tot['pas_edge_sum']:.0f}")


if __name__ == "__main__":
    main()
