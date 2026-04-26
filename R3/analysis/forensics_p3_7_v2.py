"""
Phase 3.7 forensics v2 — proper MTM accounting.

Round-trip-only accounting (v1) badly underestimated D+2's PnL because
most fills accumulated into open positions that liquidate at EOD. v2
computes per-tick MTM PnL: at each tick, position(K) is marked to the
contemporaneous mid; cumulative PnL is the integral of (delta_mid *
position_held) over the day.

This produces a per-tick PnL time series per (day, strike) that we can
slice by intraday window, by strike, by position state, and compare
against per-day exogenous regime variables.

Output: R3/analysis/forensics_p3_7_v2_results.json + stdout breakdown.
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
OUT = REPO / "R3/analysis/forensics_p3_7_v2_results.json"


def percentile(sorted_xs, p):
    if not sorted_xs:
        return None
    k = (len(sorted_xs) - 1) * p
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    if lo == hi:
        return sorted_xs[lo]
    return sorted_xs[lo] + (sorted_xs[hi] - sorted_xs[lo]) * (k - lo)


def stats(xs):
    if not xs:
        return None
    s = sorted(xs)
    return {"n": len(xs), "mean": mean(xs), "stdev": pstdev(xs) if len(xs) > 1 else 0.0,
            "median": median(xs), "min": s[0], "max": s[-1],
            "p25": percentile(s, 0.25), "p75": percentile(s, 0.75)}


def load_trades(rd):
    fills = []
    f = rd / "trades.csv"
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


def load_lambda(rd):
    out = {}
    f = rd / "submission.log"
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


def load_activity_mids(rd):
    """Returns {product: [(ts, mid)]} sorted by ts."""
    out = defaultdict(list)
    f = rd / "activity.csv"
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
                if not mid_s:
                    continue
                mid = float(mid_s)
                out[product].append((ts, mid))
            except (KeyError, ValueError):
                continue
    for p in out:
        out[p].sort()
    return out


def per_tick_mtm(fills, mids_by_product, products):
    """Returns {K: [(ts, position_after, cash_after, mtm_pnl_cum)]}.

    Cash accounting: when buying qty at price p, cash -= qty*p; selling: cash += qty*p.
    MTM pnl at tick t = cash + position * mid(t).
    """
    out = {}
    for K in products:
        sym = f"VEV_{K}"
        ticks = mids_by_product.get(sym, [])
        if not ticks:
            out[K] = []
            continue
        K_fills = [f for f in fills if f["K"] == K]
        # walk through ticks chronologically; apply fills at their ts
        position = 0
        cash = 0.0
        fi = 0
        series = []
        for ts, mid in ticks:
            # apply all fills at this ts (or earlier that haven't been applied)
            while fi < len(K_fills) and K_fills[fi]["ts"] <= ts:
                f = K_fills[fi]
                signed_qty = f["side"] * f["qty"]
                position += signed_qty
                cash -= signed_qty * f["price"]
                fi += 1
            mtm = cash + position * mid
            series.append((ts, position, cash, mtm))
        # if any leftover fills after last tick (shouldn't happen normally), apply
        while fi < len(K_fills):
            f = K_fills[fi]
            signed_qty = f["side"] * f["qty"]
            position += signed_qty
            cash -= signed_qty * f["price"]
            fi += 1
        out[K] = series
    return out


def main():
    per_day_target = {0: -5.0, 1: -79.5, 2: 1255.5}
    per_day_strike_target = {
        0: {5000: 0.0, 5300: 0.0, 5500: -9.0, 5400: 5.0, 5200: -1.0},
        1: {5000: -77.5, 5300: 11.0, 5500: 0.0, 5400: -13.0, 5200: 0.0},
        2: {5000: 859.5, 5300: 486.0, 5500: -90.0, 5400: 0.0, 5200: 0.0},
    }
    per_day_data = {}
    for day in (0, 1, 2):
        rd = RUN_DIRS[day]
        print(f"loading day {day} ...", flush=True)
        fills = load_trades(rd)
        lam = load_lambda(rd)
        mids = load_activity_mids(rd)
        mtm_by_K = per_tick_mtm(fills, mids, ACTIVE)
        per_day_data[day] = {
            "fills": fills, "lambda": lam, "mids": mids, "mtm": mtm_by_K
        }
        # Sanity: end-of-day MTM should match pnl_by_product
        print(f"  fills={len(fills)} lambda={len(lam)}")
        for K in ACTIVE:
            series = mtm_by_K[K]
            if not series:
                continue
            eod_pnl = series[-1][3]
            tgt = per_day_strike_target[day].get(K, 0.0)
            mark = "OK" if abs(eod_pnl - tgt) < 1.5 else "MISMATCH"
            print(f"    K={K}: eod_mtm={eod_pnl:+.2f}  target={tgt:+.2f}  {mark}")

    # ANALYSIS 1' — concentration via MTM, per-strike
    print("\n" + "=" * 70)
    print("ANALYSIS 1 (MTM) — Per-strike per-day end-of-day MTM")
    print("=" * 70)
    print(f"{'day':>4}", end="")
    for K in ACTIVE:
        print(f"  {K:>5}", end="")
    print(f"  {'tot':>7}")
    for d in (0, 1, 2):
        print(f"{d:>4}", end="")
        tot = 0.0
        for K in ACTIVE:
            s = per_day_data[d]["mtm"][K]
            v = s[-1][3] if s else 0.0
            print(f"  {v:+6.1f}", end="")
            tot += v
        print(f"  {tot:+7.1f}")

    # ANALYSIS 4 (MTM) — Intraday timing: PnL gained per 100k-tick window per day
    print("\n" + "=" * 70)
    print("ANALYSIS 4 (MTM) — Intraday MTM PnL by 100k-tick bucket")
    print("=" * 70)
    intraday = {}
    bucket_breakpoints = list(range(0, 1_100_000, 100_000))
    for d in (0, 1, 2):
        per_window = []
        for w in range(10):
            t0, t1 = bucket_breakpoints[w], bucket_breakpoints[w + 1]
            window_pnl = 0.0
            for K in ACTIVE:
                series = per_day_data[d]["mtm"][K]
                # find first ts >= t0 and last ts < t1
                start_pnl = 0.0
                end_pnl = 0.0
                # PnL gained in window = mtm at last ts < t1 minus mtm at last ts <= t0
                last_before_t0 = 0.0
                last_in_window = 0.0
                found_in_window = False
                for ts, _, _, mtm in series:
                    if ts < t0:
                        last_before_t0 = mtm
                    elif ts < t1:
                        last_in_window = mtm
                        found_in_window = True
                    else:
                        break
                if not found_in_window:
                    last_in_window = last_before_t0
                window_pnl += last_in_window - last_before_t0
            per_window.append({"window": w, "ts_start": t0, "ts_end": t1, "pnl": window_pnl})
        intraday[d] = per_window
    print(f"{'win':>4} {'ts_range':>20}", end="")
    for d in (0, 1, 2):
        print(f"  d{d}_pnl", end="")
    print()
    for w in range(10):
        t0, t1 = bucket_breakpoints[w], bucket_breakpoints[w + 1]
        print(f"{w:>4} {t0:>9}-{t1:<9}", end="")
        for d in (0, 1, 2):
            print(f"  {intraday[d][w]['pnl']:>+7.1f}", end="")
        print()

    # ANALYSIS 1'' — concentration: top-1, top-2, top-3 windows as % of day pnl
    print("\nIntraday concentration:")
    for d in (0, 1, 2):
        wins = [(w["window"], w["pnl"]) for w in intraday[d]]
        wins_sorted = sorted(wins, key=lambda x: abs(x[1]), reverse=True)
        day_total = sum(w[1] for w in wins)
        print(f"  day {d}: total={day_total:+.1f}")
        cum = 0.0
        for i, (wi, p) in enumerate(wins_sorted[:5]):
            cum += p
            share = (cum / day_total) if day_total else 0
            print(f"    top-{i+1}: window {wi} ({wi*100_000}-{(wi+1)*100_000}) "
                  f"pnl={p:+.1f}  cum_share={share*100:+.1f}%")

    # ANALYSIS 3 — exogenous regime variables (same as v1)
    print("\n" + "=" * 70)
    print("ANALYSIS 3 — Exogenous regime variables")
    print("=" * 70)
    regime_summary = {}
    for d in (0, 1, 2):
        lam = per_day_data[d]["lambda"]
        ts_sorted = sorted(lam.keys())
        S_series = [(t, lam[t].get("S")) for t in ts_sorted if lam[t].get("S") is not None]
        S = [s for _, s in S_series]
        c_coef = [lam[t]["c"] for t in ts_sorted if lam[t].get("c") is not None]
        a_coef = [lam[t]["a"] for t in ts_sorted if lam[t].get("a") is not None]
        b_coef = [lam[t]["b"] for t in ts_sorted if lam[t].get("b") is not None]
        S_returns = [(S[i] - S[i-1]) / S[i-1] for i in range(1, len(S)) if S[i-1]]
        # rolling realized vol over 50 ticks
        rolling_vol = []
        for i in range(50, len(S_returns) + 1):
            w = S_returns[i-50:i]
            mu = sum(w) / 50
            var = sum((r - mu) ** 2 for r in w) / 50
            rolling_vol.append(math.sqrt(var))
        regime_summary[d] = {
            "S_open": S[0] if S else None,
            "S_close": S[-1] if S else None,
            "S_max": max(S) if S else None,
            "S_min": min(S) if S else None,
            "S_range": (max(S) - min(S)) if S else None,
            "S_close_minus_open": (S[-1] - S[0]) if S else None,
            "S_realized_vol_50tick_mean": mean(rolling_vol) if rolling_vol else None,
            "S_realized_vol_50tick_p95": percentile(sorted(rolling_vol), 0.95) if rolling_vol else None,
            "S_abs_return_mean": mean(abs(r) for r in S_returns) if S_returns else None,
            "S_abs_return_p95": percentile(sorted(abs(r) for r in S_returns), 0.95) if S_returns else None,
            "c_mean": mean(c_coef), "c_stdev": pstdev(c_coef),
            "c_min": min(c_coef), "c_max": max(c_coef),
            "a_mean": mean(a_coef), "a_stdev": pstdev(a_coef),
            "b_mean": mean(b_coef), "b_stdev": pstdev(b_coef),
        }
        s = regime_summary[d]
        print(f"\nday {d}:")
        print(f"  S: open={s['S_open']:.1f} close={s['S_close']:.1f} "
              f"range={s['S_range']:.1f}  close-open={s['S_close_minus_open']:+.1f}")
        print(f"  S realized vol (50-tick): mean={s['S_realized_vol_50tick_mean']:.5f}  "
              f"p95={s['S_realized_vol_50tick_p95']:.5f}")
        print(f"  |S return|: mean={s['S_abs_return_mean']:.5f}  p95={s['S_abs_return_p95']:.5f}")
        print(f"  smile c: mean={s['c_mean']:+.5f} stdev={s['c_stdev']:.5f} "
              f"range=[{s['c_min']:.5f}, {s['c_max']:.5f}]")
        print(f"  smile a: mean={s['a_mean']:+.5f} stdev={s['a_stdev']:.5f}")
        print(f"  smile b: mean={s['b_mean']:+.5f} stdev={s['b_stdev']:.5f}")

    # ANALYSIS 5 — signal hit rate using lambda z-scores at every tick we hold
    # Define hit rate as: of all opening events (z crosses |z|>2 from below),
    # what fraction had |z| reverting (drop below |z_close|=0.5) within next 500 ticks?
    print("\n" + "=" * 70)
    print("ANALYSIS 5 — Signal-truth correlation (hit rate of |z|>2 mean reversion)")
    print("=" * 70)
    sig_summary = {}
    for d in (0, 1, 2):
        lam = per_day_data[d]["lambda"]
        ts_sorted = sorted(lam.keys())
        # for each strike, walk z over ticks; identify moments where |z| crosses above 2 from below
        # then check whether |z| drops below 0.5 within next 500 ticks
        per_K_events = {K: [] for K in ACTIVE}
        for K in ACTIVE:
            K_str = str(K)
            prev_abs_z = 0.0
            for i, ts in enumerate(ts_sorted):
                z = lam[ts].get("z", {}).get(K_str)
                if z is None:
                    continue
                abs_z = abs(z)
                if prev_abs_z <= 2.0 and abs_z > 2.0:
                    # opening event; look ahead
                    reverted = False
                    rev_ts = None
                    for j in range(i + 1, min(i + 1 + 500, len(ts_sorted))):
                        ts2 = ts_sorted[j]
                        z2 = lam[ts2].get("z", {}).get(K_str)
                        if z2 is None:
                            continue
                        if abs(z2) < 0.5:
                            reverted = True
                            rev_ts = ts2
                            break
                    per_K_events[K].append({"ts": ts, "abs_z": abs_z,
                                            "reverted_within_500": reverted,
                                            "rev_ts": rev_ts})
                prev_abs_z = abs_z
        # aggregate
        all_events = [e for K in ACTIVE for e in per_K_events[K]]
        n_total = len(all_events)
        n_reverted = sum(1 for e in all_events if e["reverted_within_500"])
        per_K_summary = {}
        for K in ACTIVE:
            evs = per_K_events[K]
            per_K_summary[K] = {
                "n_events": len(evs),
                "n_reverted": sum(1 for e in evs if e["reverted_within_500"]),
                "hit_rate": (sum(1 for e in evs if e["reverted_within_500"]) / len(evs)) if evs else None,
            }
        sig_summary[d] = {
            "n_total_events": n_total,
            "n_reverted_500": n_reverted,
            "overall_hit_rate": (n_reverted / n_total) if n_total else None,
            "per_K": per_K_summary,
        }
        print(f"\nday {d}: total_open_events={n_total}  reverted_within_500={n_reverted}  "
              f"overall_hit_rate={(n_reverted/n_total)*100 if n_total else 0:.1f}%")
        print(f"  per-K hit rates:")
        for K in ACTIVE:
            v = per_K_summary[K]
            hr = v["hit_rate"]
            hr_s = f"{hr*100:.1f}%" if hr is not None else "  -  "
            print(f"    K={K}: events={v['n_events']:>3} reverted={v['n_reverted']:>3} hit_rate={hr_s}")

    # ANALYSIS 4b — when did D+2's K=5000 PnL accumulate?
    print("\n" + "=" * 70)
    print("ANALYSIS 4b — D+2 K=5000 cumulative MTM trajectory (every 100k ticks)")
    print("=" * 70)
    for K in (5000, 5300, 5500):
        series = per_day_data[2]["mtm"][K]
        print(f"  K={K}:")
        for w in range(10):
            t0, t1 = w * 100_000, (w + 1) * 100_000
            last = None
            for ts, pos, cash, mtm in series:
                if ts < t1:
                    last = (ts, pos, mtm)
                else:
                    break
            if last:
                print(f"    end of window {w} (t<{t1}): pos={last[1]:>+4} mtm={last[2]:>+8.1f}")

    # ANALYSIS 6 — D+0/D+1 loss/scratch pattern via MTM
    print("\n" + "=" * 70)
    print("ANALYSIS 6 — D+0 / D+1 pattern: signal_ticks, max position held, MTM swings")
    print("=" * 70)
    for d in (0, 1):
        lam = per_day_data[d]["lambda"]
        signal_ticks = sum(
            1 for ts, ll in lam.items()
            if any(abs(ll.get("z", {}).get(str(K), 0.0)) > 2.0 for K in ACTIVE)
        )
        print(f"\nday {d}: signal_ticks(any |z|>2)={signal_ticks} of {len(lam)} "
              f"({signal_ticks/len(lam)*100:.1f}%)")
        for K in ACTIVE:
            series = per_day_data[d]["mtm"][K]
            if not series:
                continue
            positions = [p for _, p, _, _ in series]
            max_long = max(positions)
            max_short = min(positions)
            mtm_series = [m for _, _, _, m in series]
            mtm_max = max(mtm_series)
            mtm_min = min(mtm_series)
            mtm_eod = mtm_series[-1]
            n_nonzero = sum(1 for p in positions if p != 0)
            print(f"  K={K}: max_long={max_long:>+4} max_short={max_short:>+4}  "
                  f"mtm_swing=[{mtm_min:>+6.1f}, {mtm_max:>+6.1f}]  "
                  f"mtm_eod={mtm_eod:>+6.1f}  ticks_with_position={n_nonzero}")

    # Save full results
    out = {
        "per_day_target_pnl": per_day_target,
        "intraday_mtm_buckets": intraday,
        "regime_summary": regime_summary,
        "signal_hit_rates": sig_summary,
    }
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
