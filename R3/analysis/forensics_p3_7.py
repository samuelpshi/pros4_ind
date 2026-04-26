"""
Phase 3.7 — D+2 forensics for noTrade-5100 config.

Loads existing logs from the noTrade-5100 backtest (runs/backtest-1777186830609-*)
and computes 6 analyses to classify the +1256 D+2 PnL spike into V1
(regime-dependent edge), V2 (lucky few trades), or V3 (high-variance edge
with no usable gate).

No new backtest required. Outputs:
  - R3/analysis/forensics_p3_7_results.json (machine-readable)
  - stdout: human-readable per-analysis breakdown.
"""

import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, pstdev

REPO = Path(__file__).resolve().parents[2]
BT = Path("/Users/samuelshi/prosperity_rust_backtester")
RUN_DIRS = {
    0: BT / "runs/backtest-1777186830609-round3-day-0",
    1: BT / "runs/backtest-1777186830609-round3-day-1",
    2: BT / "runs/backtest-1777186830609-round3-day-2",
}
ACTIVE = [5000, 5200, 5300, 5400, 5500]
ALL_VEV = [5000, 5100, 5200, 5300, 5400, 5500]
DAY_TO_TTE_DAYS = {0: 8, 1: 7, 2: 6}
OUT = REPO / "R3/analysis/forensics_p3_7_results.json"


def percentile(sorted_xs, p):
    if not sorted_xs:
        return None
    k = (len(sorted_xs) - 1) * p
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return sorted_xs[lo]
    return sorted_xs[lo] + (sorted_xs[hi] - sorted_xs[lo]) * (k - lo)


def stats(xs):
    if not xs:
        return None
    s = sorted(xs)
    return {
        "n": len(xs),
        "mean": mean(xs),
        "stdev": pstdev(xs) if len(xs) > 1 else 0.0,
        "median": median(xs),
        "min": s[0],
        "max": s[-1],
        "p25": percentile(s, 0.25),
        "p75": percentile(s, 0.75),
    }


def load_trades(run_dir):
    """Returns list of own fills sorted by (ts, K)."""
    fills = []
    f = run_dir / "trades.csv"
    if not f.is_file():
        return fills
    with open(f) as fh:
        header = fh.readline().strip().split(";")
        idx = {h: i for i, h in enumerate(header)}
        for line in fh:
            cells = line.rstrip("\n").split(";")
            if len(cells) < len(header):
                continue
            buyer = cells[idx["buyer"]]
            seller = cells[idx["seller"]]
            sym = cells[idx["symbol"]]
            if buyer != "SUBMISSION" and seller != "SUBMISSION":
                continue
            if not sym.startswith("VEV_"):
                continue
            try:
                K = int(sym.split("_")[1])
            except ValueError:
                continue
            ts = int(cells[idx["timestamp"]])
            qty = int(cells[idx["quantity"]])
            price = float(cells[idx["price"]])
            side = +1 if buyer == "SUBMISSION" else -1
            fills.append({"ts": ts, "K": K, "side": side, "qty": qty, "price": price})
    fills.sort(key=lambda r: (r["ts"], r["K"]))
    return fills


def load_lambda(run_dir):
    """Returns {ts: parsed_lambda_dict}."""
    f = run_dir / "submission.log"
    out = {}
    with open(f) as fh:
        obj = json.load(fh)
    for entry in obj["logs"]:
        ll = entry.get("lambdaLog", "")
        if not ll:
            continue
        try:
            d = json.loads(ll)
        except json.JSONDecodeError:
            continue
        ts = entry.get("timestamp")
        out[ts] = d
    return out


def load_activity(run_dir):
    """Returns {(ts, product): {bid, ask, mid}} from activity.csv."""
    f = run_dir / "activity.csv"
    out = {}
    with open(f) as fh:
        header = fh.readline().strip().split(";")
        idx = {h: i for i, h in enumerate(header)}
        for line in fh:
            cells = line.rstrip("\n").split(";")
            if len(cells) < len(header):
                continue
            try:
                ts = int(cells[idx["timestamp"]])
                product = cells[idx["product"]]
                mid_s = cells[idx["mid_price"]]
                bid_s = cells[idx["bid_price_1"]]
                ask_s = cells[idx["ask_price_1"]]
                mid = float(mid_s) if mid_s else None
                bid = float(bid_s) if bid_s else None
                ask = float(ask_s) if ask_s else None
                out[(ts, product)] = {"bid": bid, "ask": ask, "mid": mid}
            except (KeyError, ValueError):
                continue
    return out


def reconstruct_round_trips(fills):
    """Walk fills per strike, splitting at zero-crossings. Returns
    list of {K, entry_ts, exit_ts, side, entry_qty, avg_entry_px,
    avg_exit_px, realized_pnl}."""
    pos = defaultdict(int)
    open_trip = defaultdict(lambda: None)
    rts = []

    def close_trip(K, exit_ts, exit_qty, exit_px, trip):
        avg_entry = sum(f["qty"] * f["price"] for f in trip["entry_fills"]) / max(
            sum(f["qty"] for f in trip["entry_fills"]), 1
        )
        # exit fills include this one
        all_exits = trip["exit_fills"]
        avg_exit = sum(f["qty"] * f["price"] for f in all_exits) / max(
            sum(f["qty"] for f in all_exits), 1
        )
        side = trip["side"]
        # PnL per share = side * (avg_exit - avg_entry); times entry_qty
        entry_qty_total = sum(f["qty"] for f in trip["entry_fills"])
        # exit_qty_total should equal entry_qty_total when fully closed
        pnl = side * (avg_exit - avg_entry) * entry_qty_total
        rts.append({
            "K": K,
            "entry_ts": trip["entry_fills"][0]["ts"],
            "exit_ts": exit_ts,
            "side": side,
            "entry_qty": entry_qty_total,
            "avg_entry_px": avg_entry,
            "avg_exit_px": avg_exit,
            "realized_pnl": pnl,
        })

    for f in fills:
        K = f["K"]
        side = f["side"]
        qty = f["qty"]
        price = f["price"]
        ts = f["ts"]
        prev = pos[K]
        new_pos = prev + side * qty
        trip = open_trip[K]
        if prev == 0:
            # opens new trip
            open_trip[K] = {
                "side": side,
                "entry_fills": [{"ts": ts, "qty": qty, "price": price}],
                "exit_fills": [],
            }
        else:
            same_dir = (prev > 0 and side > 0) or (prev < 0 and side < 0)
            if same_dir:
                trip["entry_fills"].append({"ts": ts, "qty": qty, "price": price})
            else:
                close_qty = min(abs(prev), qty)
                trip["exit_fills"].append({"ts": ts, "qty": close_qty, "price": price})
                if prev + side * close_qty == 0:
                    close_trip(K, ts, close_qty, price, trip)
                    leftover = qty - close_qty
                    if leftover > 0:
                        open_trip[K] = {
                            "side": side,
                            "entry_fills": [{"ts": ts, "qty": leftover, "price": price}],
                            "exit_fills": [],
                        }
                    else:
                        open_trip[K] = None
        pos[K] = new_pos
    return rts


# ---------- Analyses ----------

def analysis_1_concentration(per_day_rts, per_day_pnl):
    out = {}
    for day in (0, 1, 2):
        rts = per_day_rts[day]
        pnls = [r["realized_pnl"] for r in rts]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        sorted_abs = sorted(rts, key=lambda r: abs(r["realized_pnl"]), reverse=True)
        top5 = sorted_abs[:5]
        top5_pnl = sum(r["realized_pnl"] for r in top5)
        total_rt_pnl = sum(pnls)
        out[day] = {
            "n_round_trips": len(rts),
            "win_rate": (len(wins) / len(pnls)) if pnls else None,
            "mean_win": mean(wins) if wins else None,
            "mean_loss": mean(losses) if losses else None,
            "n_wins": len(wins),
            "n_losses": len(losses),
            "total_rt_pnl": total_rt_pnl,
            "day_pnl_from_backtest": per_day_pnl[day],
            "top5_pnl": top5_pnl,
            "top5_share_of_rt_pnl": (top5_pnl / total_rt_pnl) if total_rt_pnl else None,
            "top5_share_of_day_pnl": (top5_pnl / per_day_pnl[day]) if per_day_pnl[day] else None,
            "top5_detail": [
                {"K": r["K"], "entry_ts": r["entry_ts"], "exit_ts": r["exit_ts"],
                 "side": r["side"], "qty": r["entry_qty"],
                 "pnl": r["realized_pnl"]}
                for r in top5
            ],
            "pnl_distribution": stats(pnls),
        }
    return out


def analysis_2_per_strike(per_day_rts):
    out = {}
    for day in (0, 1, 2):
        rts = per_day_rts[day]
        per_K = defaultdict(lambda: {"n": 0, "pnl": 0.0, "wins": 0, "losses": 0})
        for r in rts:
            d = per_K[r["K"]]
            d["n"] += 1
            d["pnl"] += r["realized_pnl"]
            if r["realized_pnl"] > 0:
                d["wins"] += 1
            elif r["realized_pnl"] < 0:
                d["losses"] += 1
        out[day] = {K: dict(v) for K, v in per_K.items()}
    return out


def realized_vol(mids, window=50):
    if len(mids) < 2:
        return None
    rets = [(mids[i] - mids[i - 1]) / mids[i - 1] for i in range(1, len(mids)) if mids[i - 1]]
    if not rets:
        return None
    rolling = []
    for i in range(window, len(rets) + 1):
        w = rets[i - window:i]
        m = sum(w) / window
        var = sum((r - m) ** 2 for r in w) / window
        rolling.append(math.sqrt(var))
    return rolling, rets


def analysis_3_regime_variables(per_day_lambda, per_day_activity):
    out = {}
    for day in (0, 1, 2):
        lam = per_day_lambda[day]
        act = per_day_activity[day]
        ts_sorted = sorted(lam.keys())
        S = [lam[t]["S"] for t in ts_sorted if lam[t].get("S") is not None]
        a_coef = [lam[t]["a"] for t in ts_sorted if lam[t].get("a") is not None]
        b_coef = [lam[t]["b"] for t in ts_sorted if lam[t].get("b") is not None]
        c_coef = [lam[t]["c"] for t in ts_sorted if lam[t].get("c") is not None]
        # Realized vol of S (10000 ticks)
        rv = realized_vol(S, window=50) if len(S) >= 51 else (None, None)
        rolling_vol, rets = rv if rv else (None, None)
        # Spread by strike
        spread_by_K = {K: [] for K in ALL_VEV}
        for (ts, prod), bk in act.items():
            if not prod.startswith("VEV_"):
                continue
            try:
                K = int(prod.split("_")[1])
            except ValueError:
                continue
            if K not in spread_by_K:
                continue
            if bk["bid"] is not None and bk["ask"] is not None:
                spread_by_K[K].append(bk["ask"] - bk["bid"])
        out[day] = {
            "S_stats": stats(S),
            "S_range": (max(S) - min(S)) if S else None,
            "S_open_close": (S[0], S[-1]) if S else None,
            "S_realized_vol_50tick_mean": mean(rolling_vol) if rolling_vol else None,
            "S_realized_vol_50tick_p95": percentile(sorted(rolling_vol), 0.95) if rolling_vol else None,
            "ret_abs_mean": mean(abs(r) for r in rets) if rets else None,
            "a_coef_stats": stats(a_coef),
            "b_coef_stats": stats(b_coef),
            "c_coef_stats": stats(c_coef),
            "spread_by_K_mean": {K: (mean(v) if v else None) for K, v in spread_by_K.items()},
        }
    return out


def analysis_4_intraday_timing(per_day_rts, per_day_pnl):
    """Bucket round trips into 10 windows (by entry_ts) and aggregate
    realized_pnl per bucket. Per-day."""
    out = {}
    for day in (0, 1, 2):
        rts = per_day_rts[day]
        buckets = [[] for _ in range(10)]
        for r in rts:
            ts = r["entry_ts"]
            bucket = min(9, ts // 100_000)  # 0..9 (100k ticks per day)
            buckets[bucket].append(r["realized_pnl"])
        per_bucket = []
        for i, b in enumerate(buckets):
            per_bucket.append({
                "window": i,
                "ts_start": i * 100_000,
                "ts_end": (i + 1) * 100_000,
                "n_trips": len(b),
                "pnl_sum": sum(b),
            })
        out[day] = per_bucket
    return out


def analysis_5_signal_truth(per_day_rts, per_day_lambda):
    """For each round trip, look up the entry-tick lambda log to get z at
    entry. Determine: did the residual revert by exit (i.e. did |z| at
    exit drop below |z| at entry)?
    """
    out = {}
    for day in (0, 1, 2):
        rts = per_day_rts[day]
        lam = per_day_lambda[day]
        rows = []
        # round to lambda log timestamps (every 100 ticks usually); we'll use
        # the tick at or just before entry_ts/exit_ts
        ts_sorted = sorted(lam.keys())
        for r in rts:
            K_str = str(r["K"])
            entry_z = None
            exit_z = None
            # find the lambda entry at or before entry_ts
            ll_entry = lam.get(r["entry_ts"]) or lam.get(r["entry_ts"] - 100)
            ll_exit = lam.get(r["exit_ts"]) or lam.get(r["exit_ts"] - 100)
            if ll_entry and "z" in ll_entry:
                entry_z = ll_entry["z"].get(K_str)
            if ll_exit and "z" in ll_exit:
                exit_z = ll_exit["z"].get(K_str)
            reverted = None
            if entry_z is not None and exit_z is not None:
                reverted = abs(exit_z) < abs(entry_z)
            rows.append({
                "K": r["K"],
                "side": r["side"],
                "entry_z": entry_z,
                "exit_z": exit_z,
                "abs_entry_z": abs(entry_z) if entry_z is not None else None,
                "abs_exit_z": abs(exit_z) if exit_z is not None else None,
                "reverted": reverted,
                "pnl": r["realized_pnl"],
                "hold_ticks": r["exit_ts"] - r["entry_ts"],
            })
        rev_known = [row for row in rows if row["reverted"] is not None]
        n_rev = sum(1 for row in rev_known if row["reverted"])
        n_winning = sum(1 for row in rows if row["pnl"] > 0)
        # mean reversion magnitude conditional on entry
        rev_magnitudes = [
            row["abs_entry_z"] - row["abs_exit_z"]
            for row in rev_known
            if row["abs_entry_z"] is not None
        ]
        out[day] = {
            "n_trips": len(rows),
            "n_with_z_data": len(rev_known),
            "hit_rate_signal_reverted": (n_rev / len(rev_known)) if rev_known else None,
            "hit_rate_pnl_positive": (n_winning / len(rows)) if rows else None,
            "mean_reversion_magnitude": mean(rev_magnitudes) if rev_magnitudes else None,
            "median_reversion_magnitude": median(rev_magnitudes) if rev_magnitudes else None,
            "mean_abs_entry_z": mean(row["abs_entry_z"] for row in rev_known
                                    if row["abs_entry_z"] is not None) if rev_known else None,
            "mean_hold_ticks": mean(row["hold_ticks"] for row in rows) if rows else None,
        }
    return out


def analysis_6_loss_pattern(per_day_rts, per_day_lambda):
    """For D+0/D+1 specifically: were the days flat-via-scratches,
    flat-via-no-edge, or flat-via-inactivity?"""
    out = {}
    for day in (0, 1):
        rts = per_day_rts[day]
        n_rts = len(rts)
        # Number of ticks where any |z| > z_open=2.0
        signal_ticks = 0
        lam = per_day_lambda[day]
        for ts, ll in lam.items():
            zd = ll.get("z", {})
            if any(abs(zd.get(str(K), 0.0)) > 2.0 for K in ACTIVE):
                signal_ticks += 1
        pnls = [r["realized_pnl"] for r in rts]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        out[day] = {
            "n_trips": n_rts,
            "n_signal_ticks_z_gt_2": signal_ticks,
            "total_lambda_ticks": len(lam),
            "frac_ticks_with_signal": signal_ticks / max(len(lam), 1),
            "trip_pnl_stats": stats(pnls),
            "n_wins": len(wins),
            "n_losses": len(losses),
            "win_rate": (len(wins) / n_rts) if n_rts else None,
            "mean_win_pnl": mean(wins) if wins else None,
            "mean_loss_pnl": mean(losses) if losses else None,
            "abs_mean_pnl": mean(abs(p) for p in pnls) if pnls else None,
        }
    return out


# ---------- Main ----------

def main():
    per_day_pnl_target = {0: -5.0, 1: -79.5, 2: 1255.5}  # from backtest stdout
    per_day_fills = {}
    per_day_rts = {}
    per_day_lambda = {}
    per_day_activity = {}
    for day in (0, 1, 2):
        rd = RUN_DIRS[day]
        print(f"loading day {day} from {rd.name} ...", flush=True)
        fills = load_trades(rd)
        rts = reconstruct_round_trips(fills)
        lam = load_lambda(rd)
        act = load_activity(rd)
        per_day_fills[day] = fills
        per_day_rts[day] = rts
        per_day_lambda[day] = lam
        per_day_activity[day] = act
        print(f"  fills={len(fills)} round_trips={len(rts)} lambda_ticks={len(lam)}")

    a1 = analysis_1_concentration(per_day_rts, per_day_pnl_target)
    a2 = analysis_2_per_strike(per_day_rts)
    a3 = analysis_3_regime_variables(per_day_lambda, per_day_activity)
    a4 = analysis_4_intraday_timing(per_day_rts, per_day_pnl_target)
    a5 = analysis_5_signal_truth(per_day_rts, per_day_lambda)
    a6 = analysis_6_loss_pattern(per_day_rts, per_day_lambda)

    out = {
        "per_day_target_pnl": per_day_pnl_target,
        "fill_counts": {d: len(per_day_fills[d]) for d in (0, 1, 2)},
        "round_trip_counts": {d: len(per_day_rts[d]) for d in (0, 1, 2)},
        "analysis_1_concentration": a1,
        "analysis_2_per_strike": a2,
        "analysis_3_regime_variables": a3,
        "analysis_4_intraday_timing": a4,
        "analysis_5_signal_truth": a5,
        "analysis_6_loss_pattern": a6,
    }
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print(f"\nWrote {OUT}")

    # ---- Pretty stdout ----
    print("\n" + "=" * 70)
    print("ANALYSIS 1 — Trade-level PnL concentration")
    print("=" * 70)
    print(f"{'day':>4} {'rts':>5} {'win%':>7} {'meanW':>8} {'meanL':>8} "
          f"{'sumRT':>9} {'btPnL':>9} {'top5RT':>9} {'top5/btPnL%':>12}")
    for d in (0, 1, 2):
        s = a1[d]
        wr = s["win_rate"]
        mw = s["mean_win"]
        ml = s["mean_loss"]
        wr_s = f"{wr*100:.1f}" if wr is not None else "  -  "
        mw_s = f"{mw:+.1f}" if mw is not None else "  -  "
        ml_s = f"{ml:+.1f}" if ml is not None else "  -  "
        t5 = s["top5_share_of_day_pnl"]
        t5_s = f"{t5*100:+.1f}%" if t5 is not None else "  -  "
        print(f"{d:>4} {s['n_round_trips']:>5} {wr_s:>7} {mw_s:>8} {ml_s:>8} "
              f"{s['total_rt_pnl']:>+9.1f} {s['day_pnl_from_backtest']:>+9.1f} "
              f"{s['top5_pnl']:>+9.1f} {t5_s:>12}")
    for d in (0, 1, 2):
        print(f"\nday {d} top-5 trades:")
        for r in a1[d]["top5_detail"]:
            print(f"  K={r['K']} side={r['side']:+d} qty={r['qty']:>3} "
                  f"entry_ts={r['entry_ts']:>7} exit_ts={r['exit_ts']:>7} "
                  f"pnl={r['pnl']:+.1f}")

    print("\n" + "=" * 70)
    print("ANALYSIS 2 — Per-strike PnL attribution per day")
    print("=" * 70)
    print(f"{'day':>4}", end="")
    for K in ACTIVE:
        print(f"  {K:>5}n  {K:>5}P", end="")
    print()
    for d in (0, 1, 2):
        print(f"{d:>4}", end="")
        for K in ACTIVE:
            v = a2[d].get(K, {"n": 0, "pnl": 0.0})
            print(f"  {v['n']:>6}  {v['pnl']:>+6.1f}", end="")
        print()

    print("\n" + "=" * 70)
    print("ANALYSIS 3 — Exogenous regime variables")
    print("=" * 70)
    for d in (0, 1, 2):
        s = a3[d]
        ss = s["S_stats"]
        cs = s["c_coef_stats"]
        as_ = s["a_coef_stats"]
        bs = s["b_coef_stats"]
        print(f"\nday {d}:")
        print(f"  S: range={s['S_range']:.1f} open={s['S_open_close'][0]:.1f} "
              f"close={s['S_open_close'][1]:.1f} mean={ss['mean']:.1f} stdev={ss['stdev']:.2f}")
        print(f"  S realized vol (50-tick): mean={s['S_realized_vol_50tick_mean']:.5f} "
              f"p95={s['S_realized_vol_50tick_p95']:.5f}  ret_abs_mean={s['ret_abs_mean']:.5f}")
        print(f"  smile c: mean={cs['mean']:+.5f} stdev={cs['stdev']:.5f} "
              f"min={cs['min']:+.5f} max={cs['max']:+.5f}")
        print(f"  smile a: mean={as_['mean']:+.5f} stdev={as_['stdev']:.5f}")
        print(f"  smile b: mean={bs['mean']:+.5f} stdev={bs['stdev']:.5f}")
        print(f"  spread by K: " + ", ".join(
            f"{K}={(s['spread_by_K_mean'][K] or 0):.2f}" for K in ALL_VEV))

    print("\n" + "=" * 70)
    print("ANALYSIS 4 — Intraday timing (10 windows of 100k ticks)")
    print("=" * 70)
    print(f"{'win':>4}", end="")
    for d in (0, 1, 2):
        print(f"  d{d}_n  d{d}_pnl", end="")
    print()
    for w in range(10):
        print(f"{w:>4}", end="")
        for d in (0, 1, 2):
            b = a4[d][w]
            print(f"  {b['n_trips']:>4}  {b['pnl_sum']:>+7.1f}", end="")
        print()

    print("\n" + "=" * 70)
    print("ANALYSIS 5 — Signal-truth correlation per day")
    print("=" * 70)
    print(f"{'day':>4} {'n':>4} {'wD':>4} {'hitRev':>7} {'hitPnl':>7} "
          f"{'meanRev|z|':>11} {'meanEntZ':>10} {'meanHold':>10}")
    for d in (0, 1, 2):
        s = a5[d]
        hr = s["hit_rate_signal_reverted"]
        hp = s["hit_rate_pnl_positive"]
        mr = s["mean_reversion_magnitude"]
        me = s["mean_abs_entry_z"]
        mh = s["mean_hold_ticks"]
        hr_s = f"{hr*100:.1f}%" if hr is not None else "  -  "
        hp_s = f"{hp*100:.1f}%" if hp is not None else "  -  "
        mr_s = f"{mr:+.3f}" if mr is not None else "  -  "
        me_s = f"{me:.3f}" if me is not None else "  -  "
        mh_s = f"{mh:.0f}" if mh is not None else "  -  "
        print(f"{d:>4} {s['n_trips']:>4} {s['n_with_z_data']:>4} {hr_s:>7} {hp_s:>7} "
              f"{mr_s:>11} {me_s:>10} {mh_s:>10}")

    print("\n" + "=" * 70)
    print("ANALYSIS 6 — D+0 / D+1 loss pattern")
    print("=" * 70)
    for d in (0, 1):
        s = a6[d]
        print(f"\nday {d}:")
        print(f"  trips={s['n_trips']} signal_ticks(|z|>2)={s['n_signal_ticks_z_gt_2']} "
              f"of {s['total_lambda_ticks']} ({s['frac_ticks_with_signal']*100:.1f}%)")
        print(f"  win_rate={(s['win_rate'] or 0)*100:.1f}%  "
              f"mean_win={(s['mean_win_pnl'] or 0):+.2f}  "
              f"mean_loss={(s['mean_loss_pnl'] or 0):+.2f}  "
              f"abs_mean_pnl={(s['abs_mean_pnl'] or 0):.2f}")
        ps = s["trip_pnl_stats"]
        if ps:
            print(f"  trip pnl: median={ps['median']:+.2f}  "
                  f"p25={ps['p25']:+.2f}  p75={ps['p75']:+.2f}  "
                  f"min={ps['min']:+.2f}  max={ps['max']:+.2f}")


if __name__ == "__main__":
    main()
