"""
P3.9a — closed-RT PnL + hold-time + close-trigger metrics for the
4 exit_mode variants. Reads each variant's trades.csv (own fills) and
submission.log (lambda log for close_trigger attribution).
"""

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, pstdev

BT = Path("/Users/samuelshi/prosperity_rust_backtester")
OUT = Path("/Users/samuelshi/IMC-Prosperity-2026-personal/R3/analysis/cache/p3_9a_metrics.json")
OUT.parent.mkdir(parents=True, exist_ok=True)

VARIANTS = {
    "legacy":     "1777189677739",
    "loose_z":    "1777189696343",
    "time_based": "1777189713599",
    "hybrid":     "1777189730662",
}

ACTIVE = [5000, 5200, 5300, 5400, 5500]


def load_fills(run_dir):
    f = run_dir / "trades.csv"
    fills = []
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
                continue  # exclude VELVETFRUIT_EXTRACT hedge fills
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


def reconstruct_round_trips(fills):
    pos = defaultdict(int)
    open_trip = defaultdict(lambda: None)
    rts = []

    def close_trip(K, exit_ts, trip):
        avg_entry = sum(f["qty"] * f["price"] for f in trip["entry_fills"]) / max(
            sum(f["qty"] for f in trip["entry_fills"]), 1
        )
        avg_exit = sum(f["qty"] * f["price"] for f in trip["exit_fills"]) / max(
            sum(f["qty"] for f in trip["exit_fills"]), 1
        )
        side = trip["side"]
        entry_qty_total = sum(f["qty"] for f in trip["entry_fills"])
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
            "hold_ticks": (exit_ts - trip["entry_fills"][0]["ts"]) // 100,
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
                    close_trip(K, ts, trip)
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


def parse_close_triggers(run_dir):
    """Parse submission.log lambda lines for `cls` triggers (z|t)
    and return per-K counts and per-event timestamps."""
    f = run_dir / "submission.log"
    counts = {"z": 0, "t": 0}
    per_K_counts = {K: {"z": 0, "t": 0} for K in ACTIVE}
    if not f.is_file():
        return counts, per_K_counts
    with open(f) as fh:
        try:
            obj = json.load(fh)
        except json.JSONDecodeError:
            return counts, per_K_counts
    for entry in obj.get("logs", []):
        ll = entry.get("lambdaLog", "")
        if not ll:
            continue
        try:
            d = json.loads(ll)
        except json.JSONDecodeError:
            continue
        cls = d.get("cls", {})
        if not isinstance(cls, dict):
            continue
        for K_str, trig in cls.items():
            if trig in counts:
                counts[trig] += 1
            try:
                K = int(K_str)
                if K in per_K_counts and trig in per_K_counts[K]:
                    per_K_counts[K][trig] += 1
            except ValueError:
                pass
    return counts, per_K_counts


def stats(xs):
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    return {
        "n": len(xs),
        "mean": mean(xs),
        "median": median(xs),
        "min": s[0],
        "max": s[-1],
        "p25": s[max(0, len(s) // 4 - 1)],
        "p75": s[min(len(s) - 1, 3 * len(s) // 4)],
        "stdev": pstdev(xs) if len(xs) > 1 else 0.0,
    }


def main():
    out = {}
    for variant, run_id in VARIANTS.items():
        out[variant] = {"run_id": run_id, "per_day": {}}
        all_rts = []
        all_cls = {"z": 0, "t": 0}
        for d in (0, 1, 2):
            run_dir = BT / f"runs/backtest-{run_id}-round3-day-{d}"
            fills = load_fills(run_dir)
            rts = reconstruct_round_trips(fills)
            cls, per_K_cls = parse_close_triggers(run_dir)
            pnls = [r["realized_pnl"] for r in rts]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            holds = [r["hold_ticks"] for r in rts]
            out[variant]["per_day"][d] = {
                "n_fills": len(fills),
                "n_round_trips": len(rts),
                "closed_rt_pnl": sum(pnls),
                "win_rate": len(wins) / len(pnls) if pnls else None,
                "n_wins": len(wins),
                "n_losses": len(losses),
                "mean_win": mean(wins) if wins else None,
                "mean_loss": mean(losses) if losses else None,
                "hold_ticks_stats": stats(holds),
                "close_trigger_counts": cls,
                "close_trigger_per_K": per_K_cls,
            }
            all_rts.extend(rts)
            all_cls["z"] += cls["z"]
            all_cls["t"] += cls["t"]
        all_pnls = [r["realized_pnl"] for r in all_rts]
        all_holds = [r["hold_ticks"] for r in all_rts]
        all_wins = [p for p in all_pnls if p > 0]
        all_losses = [p for p in all_pnls if p < 0]
        out[variant]["aggregate"] = {
            "n_round_trips": len(all_rts),
            "closed_rt_pnl_3d": sum(all_pnls),
            "win_rate": len(all_wins) / len(all_pnls) if all_pnls else None,
            "mean_win": mean(all_wins) if all_wins else None,
            "mean_loss": mean(all_losses) if all_losses else None,
            "hold_ticks_stats": stats(all_holds),
            "close_trigger_counts_3d": all_cls,
            "pnl_distribution": stats(all_pnls),
        }

    OUT.write_text(json.dumps(out, indent=1, default=str))
    print(f"wrote {OUT}\n")

    # ---- Headline table ----
    print("=" * 78)
    print("CLOSED-RT PnL per variant (THE METRIC)")
    print("=" * 78)
    print(f"{'variant':<14}{'D=0':>10}{'D+1':>10}{'D+2':>10}{'3-day':>10}"
          f"{'#RT':>6}{'win%':>8}")
    for v, d in out.items():
        rt0 = d["per_day"][0]["closed_rt_pnl"]
        rt1 = d["per_day"][1]["closed_rt_pnl"]
        rt2 = d["per_day"][2]["closed_rt_pnl"]
        tot = d["aggregate"]["closed_rt_pnl_3d"]
        nrt = d["aggregate"]["n_round_trips"]
        wr = d["aggregate"]["win_rate"]
        wrs = f"{wr*100:.0f}%" if wr is not None else "-"
        print(f"{v:<14}{rt0:>10.1f}{rt1:>10.1f}{rt2:>10.1f}{tot:>10.1f}"
              f"{nrt:>6d}{wrs:>8}")

    # ---- Hold-time + close-trigger ----
    print("\n" + "=" * 78)
    print("Hold-time (ticks) + close-trigger counts")
    print("=" * 78)
    print(f"{'variant':<14}{'mean':>8}{'med':>8}{'p25':>8}{'p75':>8}"
          f"{'max':>8}{'z-trig':>8}{'t-trig':>8}")
    for v, d in out.items():
        h = d["aggregate"]["hold_ticks_stats"]
        c = d["aggregate"]["close_trigger_counts_3d"]
        if h["n"] == 0:
            print(f"{v:<14}{'-':>8}{'-':>8}{'-':>8}{'-':>8}{'-':>8}"
                  f"{c['z']:>8}{c['t']:>8}")
        else:
            print(f"{v:<14}{h['mean']:>8.1f}{int(h['median']):>8d}"
                  f"{int(h['p25']):>8d}{int(h['p75']):>8d}{int(h['max']):>8d}"
                  f"{c['z']:>8}{c['t']:>8}")

    # ---- Mean win / mean loss ----
    print("\n" + "=" * 78)
    print("Win/loss profile (per round-trip)")
    print("=" * 78)
    print(f"{'variant':<14}{'mean_win':>10}{'mean_loss':>12}{'#wins':>8}"
          f"{'#loss':>8}")
    for v, d in out.items():
        a = d["aggregate"]
        mw = f"{a['mean_win']:.1f}" if a["mean_win"] is not None else "-"
        ml = f"{a['mean_loss']:.1f}" if a["mean_loss"] is not None else "-"
        nw = sum(d["per_day"][k]["n_wins"] for k in (0, 1, 2))
        nl = sum(d["per_day"][k]["n_losses"] for k in (0, 1, 2))
        print(f"{v:<14}{mw:>10}{ml:>12}{nw:>8d}{nl:>8d}")


if __name__ == "__main__":
    main()
