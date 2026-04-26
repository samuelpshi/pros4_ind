"""
Stage-2a-extended diagnostics. Computes per-strike round-trip metrics
from a persisted backtest (submission.log JSON):

  1. Hit rate (round-trip P&L > 0 fraction)
  2. Avg residual capture per round trip
  3. Avg spread paid per round trip
  4. Capture-to-cost ratio (2 / 3)
  5. Passive fill rate (fraction of fills tagged passive)
  6. Passive fill capture (avg per-share spread saved on passive fills)

Usage:
    python3 R3/analysis/diagnostics_v1_5.py <submission.log>
"""

import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

ACTIVE_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
DAY_TO_TTE_DAYS = {0: 8, 1: 7, 2: 6}


def smile_iv(a, b, c, m):
    return a * m * m + b * m + c


def bs_call_price(S, K, T, sigma):
    if T <= 0 or sigma <= 0 or S <= 0:
        return max(0.0, S - K)
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    # Numerical Phi via erf
    def Phi(x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
    return S * Phi(d1) - K * Phi(d2)


def parse_activities(activities_log):
    """Returns {(timestamp, product): {'bid': bid_px, 'ask': ask_px, 'mid': mid}}."""
    book = {}
    rows = activities_log.split("\n")
    if not rows:
        return book
    header = rows[0].split(";")
    idx = {name: i for i, name in enumerate(header)}
    for row in rows[1:]:
        cells = row.split(";")
        if len(cells) < len(header):
            continue
        try:
            ts = int(cells[idx["timestamp"]])
            product = cells[idx["product"]]
            bid = cells[idx["bid_price_1"]]
            ask = cells[idx["ask_price_1"]]
            mid = cells[idx["mid_price"]]
            bid = int(bid) if bid else None
            ask = int(ask) if ask else None
            mid = float(mid) if mid else None
            book[(ts, product)] = {"bid": bid, "ask": ask, "mid": mid}
        except (KeyError, ValueError):
            continue
    return book


def parse_lambda_logs(logs):
    """Returns {timestamp: {'a': a, 'b': b, 'c': c, 'pas': [...], 'agg': [...]}}."""
    out = {}
    for entry in logs:
        ts = entry.get("timestamp")
        ll = entry.get("lambdaLog", "")
        if not ll:
            continue
        try:
            d = json.loads(ll)
        except json.JSONDecodeError:
            continue
        # The "ts" inside the lambdaLog is the same as the outer timestamp.
        out[ts] = {
            "a": d.get("a"),
            "b": d.get("b"),
            "c": d.get("c"),
            "S": d.get("S"),
            "pas": set(d.get("pas", []) or []),
            "agg": set(d.get("agg", []) or []),
        }
    return out


def get_own_trades(trade_history):
    """Returns list of own trades chronologically."""
    own = []
    for t in trade_history:
        sym = t.get("symbol", "")
        if not sym.startswith("VEV_"):
            continue
        K = int(sym.split("_")[1])
        if K not in ACTIVE_STRIKES:
            continue
        buyer = t.get("buyer", "")
        seller = t.get("seller", "")
        if buyer == "SUBMISSION":
            side = +1
        elif seller == "SUBMISSION":
            side = -1
        else:
            continue
        own.append({
            "ts": int(t["timestamp"]),
            "K": K,
            "side": side,
            "qty": int(t["quantity"]),
            "price": float(t["price"]),
        })
    own.sort(key=lambda r: (r["ts"], r["K"]))
    return own


def compute_diagnostics(submission_log_path):
    with open(submission_log_path, "r") as f:
        obj = json.load(f)
    day = obj.get("logs", [{}])[0].get("day", 0) if obj.get("logs") else 0
    book = parse_activities(obj["activitiesLog"])
    lambda_logs = parse_lambda_logs(obj["logs"])
    own_trades = get_own_trades(obj["tradeHistory"])

    # TTE for residual computation; assume current_day=day.
    tte_days_at_start = DAY_TO_TTE_DAYS.get(day, 8)

    # Per-strike round-trip walk: a "round trip" is a sequence of fills
    # that returns position to 0 (or flips through 0). We split at zero
    # crossings.
    per_strike_trips = defaultdict(list)
    pos = defaultdict(int)
    open_trip = defaultdict(lambda: {
        "entry_fills": [],   # list of {ts, side, qty, price, mid, resid, pas}
        "exit_fills": [],
        "side": 0,           # +1 long, -1 short
    })

    # Per-fill tagging requires looking at lambda_logs for the same ts to
    # know if K was passive or aggressive at that tick.
    def fill_tag(ts, K):
        ll = lambda_logs.get(ts) or lambda_logs.get(ts - 100)
        if not ll:
            return None
        if K in ll["pas"]:
            return "passive"
        if K in ll["agg"]:
            return "aggressive"
        return None

    def fill_residual(ts, K, mid):
        ll = lambda_logs.get(ts) or lambda_logs.get(ts - 100)
        if not ll or ll["a"] is None:
            return None
        S = ll.get("S")
        if S is None:
            return None
        T = max((tte_days_at_start - ts / 1_000_000.0) / 365.0, 1e-6)
        m = math.log(K / S) / math.sqrt(T)
        iv = smile_iv(ll["a"], ll["b"], ll["c"], m)
        if iv <= 0:
            return None
        theo = bs_call_price(S, K, T, iv)
        return mid - theo

    for tr in own_trades:
        K = tr["K"]
        side = tr["side"]
        qty = tr["qty"]
        price = tr["price"]
        ts = tr["ts"]
        mkt = book.get((ts, f"VEV_{K}"))
        mid = mkt["mid"] if mkt else None
        bid = mkt["bid"] if mkt else None
        ask = mkt["ask"] if mkt else None
        spread = (ask - bid) if (bid is not None and ask is not None) else None
        slip = (price - mid) if mid is not None else None  # slip per share, signed
        resid = fill_residual(ts, K, mid) if mid is not None else None
        tag = fill_tag(ts, K)

        signed_qty = side * qty
        prev_pos = pos[K]
        new_pos = prev_pos + signed_qty
        trip = open_trip[K]

        # Determine entry vs exit pieces
        # If prev_pos == 0: this opens the trip. side defines trip direction.
        # If sign(prev_pos) == side: adding to existing direction (entry add).
        # If sign(prev_pos) != side: closing (exit) up to |prev_pos| qty;
        #   any remaining size opens a new trip in the new direction.
        if prev_pos == 0:
            trip["side"] = side
            trip["entry_fills"].append({
                "ts": ts, "K": K, "qty": qty, "price": price,
                "mid": mid, "bid": bid, "ask": ask, "spread": spread,
                "slip": slip, "resid": resid, "tag": tag,
            })
        else:
            same_dir = (prev_pos > 0 and side > 0) or (prev_pos < 0 and side < 0)
            if same_dir:
                trip["entry_fills"].append({
                    "ts": ts, "K": K, "qty": qty, "price": price,
                    "mid": mid, "bid": bid, "ask": ask, "spread": spread,
                    "slip": slip, "resid": resid, "tag": tag,
                })
            else:
                # Closing portion = min(|prev_pos|, qty); any extra opens new trip.
                close_qty = min(abs(prev_pos), qty)
                trip["exit_fills"].append({
                    "ts": ts, "K": K, "qty": close_qty, "price": price,
                    "mid": mid, "bid": bid, "ask": ask, "spread": spread,
                    "slip": slip, "resid": resid, "tag": tag,
                })
                # If trip is fully closed, finalize.
                new_pos_after_close = prev_pos + side * close_qty
                if new_pos_after_close == 0:
                    per_strike_trips[K].append(trip)
                    open_trip[K] = {"entry_fills": [], "exit_fills": [], "side": 0}
                    # Any leftover quantity opens a new trip
                    leftover = qty - close_qty
                    if leftover > 0:
                        open_trip[K]["side"] = side
                        open_trip[K]["entry_fills"].append({
                            "ts": ts, "K": K, "qty": leftover, "price": price,
                            "mid": mid, "bid": bid, "ask": ask, "spread": spread,
                            "slip": slip, "resid": resid, "tag": tag,
                        })
        pos[K] = new_pos

    # Compute per-strike metrics
    per_strike_metrics = {}
    all_fills = [t for tr_list in per_strike_trips.values() for trip in tr_list
                 for t in (trip["entry_fills"] + trip["exit_fills"])]
    # Add open-trip fills (incomplete trips) for fill-rate computation only
    for K, ot in open_trip.items():
        all_fills.extend(ot["entry_fills"] + ot["exit_fills"])

    for K in ACTIVE_STRIKES:
        trips = per_strike_trips.get(K, [])
        n_trips = len(trips)
        # Round-trip P&L
        rt_pnls = []
        rt_residual_caps = []
        rt_spreads = []
        for trip in trips:
            entries = trip["entry_fills"]
            exits = trip["exit_fills"]
            if not entries or not exits:
                continue
            side = trip["side"]
            entry_qty = sum(f["qty"] for f in entries)
            exit_qty = sum(f["qty"] for f in exits)
            avg_entry_px = sum(f["qty"] * f["price"] for f in entries) / max(entry_qty, 1)
            avg_exit_px = sum(f["qty"] * f["price"] for f in exits) / max(exit_qty, 1)
            # P&L per share for this round trip (long: exit-entry; short: entry-exit)
            pnl_per_share = side * (avg_exit_px - avg_entry_px)
            rt_pnls.append(pnl_per_share)

            # Residual capture: sign-corrected (entry resid - exit resid) for long
            # (we expect to enter when undervalued, exit when fair).
            entry_resids = [f["resid"] for f in entries if f["resid"] is not None]
            exit_resids = [f["resid"] for f in exits if f["resid"] is not None]
            if entry_resids and exit_resids:
                avg_entry_resid = mean(entry_resids)
                avg_exit_resid = mean(exit_resids)
                # Long was opened when resid < 0 (undervalued); want exit_resid > entry_resid
                # Short was opened when resid > 0; want exit_resid < entry_resid
                # So capture = side * (exit_resid - entry_resid).
                rt_residual_caps.append(side * (avg_exit_resid - avg_entry_resid))

            # Spread paid: for each fill, |slip| ~ half-spread crossed (signed).
            # Use the abs() so passive fills (negative slip = price improvement)
            # show up as spread captured (negative cost).
            spr_paid = []
            for f in entries + exits:
                if f["slip"] is None:
                    continue
                # For a buy fill, positive slip = lift beyond mid = paid spread.
                # For a sell fill, negative slip = hit below mid = paid spread.
                # Convert to per-share signed spread cost (positive = paid).
                if f in entries:
                    s = side
                else:
                    s = -side
                # buy = paid (price - mid); sell = paid (mid - price); same sign ⇒ slip*s>0 = cost.
                cost = f["slip"] * s
                spr_paid.append(cost)
            if spr_paid:
                rt_spreads.append(mean(spr_paid))

        # Hit rate
        hit_rate = (sum(1 for p in rt_pnls if p > 0) / max(len(rt_pnls), 1)) if rt_pnls else None
        avg_rt_pnl = mean(rt_pnls) if rt_pnls else None
        avg_resid_cap = mean(rt_residual_caps) if rt_residual_caps else None
        avg_spr = mean(rt_spreads) if rt_spreads else None
        cap_cost_ratio = (avg_resid_cap / avg_spr) if (avg_resid_cap is not None and avg_spr is not None and avg_spr != 0) else None

        # Fill-rate metrics include open-trip fills too.
        K_fills = [f for tr in trips for f in (tr["entry_fills"] + tr["exit_fills"])]
        K_fills += open_trip.get(K, {"entry_fills": [], "exit_fills": []})["entry_fills"]
        K_fills += open_trip.get(K, {"entry_fills": [], "exit_fills": []})["exit_fills"]
        n_fills = len(K_fills)
        n_passive = sum(1 for f in K_fills if f["tag"] == "passive")
        n_aggressive = sum(1 for f in K_fills if f["tag"] == "aggressive")
        n_untagged = n_fills - n_passive - n_aggressive
        passive_fill_rate = (n_passive / n_fills) if n_fills else None
        # Passive fill capture: for a passive buy at best_bid that filled, the
        # price improvement vs the marketable equivalent (best_ask) is
        # (ask - bid) per share = spread. Same magnitude for passive sells.
        passive_caps = []
        for f in K_fills:
            if f["tag"] != "passive":
                continue
            if f["spread"] is None:
                continue
            passive_caps.append(f["spread"])
        passive_capture = mean(passive_caps) if passive_caps else None

        per_strike_metrics[K] = {
            "n_round_trips": n_trips,
            "n_fills": n_fills,
            "hit_rate": hit_rate,
            "avg_rt_pnl_per_share": avg_rt_pnl,
            "avg_residual_capture": avg_resid_cap,
            "avg_spread_paid": avg_spr,
            "capture_to_cost": cap_cost_ratio,
            "passive_fill_rate": passive_fill_rate,
            "passive_fill_capture": passive_capture,
            "n_passive": n_passive,
            "n_aggressive": n_aggressive,
            "n_untagged": n_untagged,
        }

    return per_strike_metrics


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    paths = sys.argv[1:]
    for p in paths:
        print(f"\n=== {p} ===")
        metrics = compute_diagnostics(p)
        # Pretty table
        cols = ["K", "n_rt", "n_fills", "hit%", "avg_rt_pnl", "resid_cap",
                "spr_paid", "cap/cost", "pas_rate%", "pas_cap"]
        widths = [6, 6, 8, 7, 11, 10, 9, 9, 10, 8]
        header = " ".join(f"{c:>{w}}" for c, w in zip(cols, widths))
        print(header)
        print("-" * len(header))
        for K in ACTIVE_STRIKES:
            m = metrics[K]
            def f(v, fmt):
                return f"{v:{fmt}}" if v is not None else "    --"
            print(" ".join([
                f"{K:>{widths[0]}}",
                f"{m['n_round_trips']:>{widths[1]}}",
                f"{m['n_fills']:>{widths[2]}}",
                f(m['hit_rate'] * 100 if m['hit_rate'] is not None else None, "6.1f") if m['hit_rate'] is not None else "    --",
                f(m['avg_rt_pnl_per_share'], "10.3f"),
                f(m['avg_residual_capture'], "9.3f"),
                f(m['avg_spread_paid'], "8.3f"),
                f(m['capture_to_cost'], "8.3f"),
                f(m['passive_fill_rate'] * 100 if m['passive_fill_rate'] is not None else None, "9.1f") if m['passive_fill_rate'] is not None else "    --",
                f(m['passive_fill_capture'], "7.2f"),
            ]))


if __name__ == "__main__":
    main()
