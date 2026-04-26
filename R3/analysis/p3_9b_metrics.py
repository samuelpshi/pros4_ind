"""P3.9b — closed-RT + spread-gate diagnostics for 4 variants."""

import json
import sys
sys.path.insert(0, "/Users/samuelshi/IMC-Prosperity-2026-personal/R3/analysis")

from p3_9a_metrics import (
    BT, load_fills, reconstruct_round_trips, stats, ACTIVE,
)

from collections import defaultdict
from pathlib import Path
from statistics import mean, median, pstdev

OUT = Path("/Users/samuelshi/IMC-Prosperity-2026-personal/R3/analysis/cache/p3_9b_metrics.json")
OUT.parent.mkdir(parents=True, exist_ok=True)

VARIANTS = {
    "baseline": "1777191667502",  # gate off (control)
    "gate1":    "1777191682878",
    "gate2":    "1777191697946",
    "gate3":    "1777191712905",
}


def parse_lambda(run_dir):
    """Return list of (ts, sg_blk, spr_dict)."""
    f = run_dir / "submission.log"
    out = []
    if not f.is_file():
        return out
    with open(f) as fh:
        try:
            obj = json.load(fh)
        except json.JSONDecodeError:
            return out
    for entry in obj.get("logs", []):
        ll = entry.get("lambdaLog", "")
        if not ll:
            continue
        try:
            d = json.loads(ll)
        except json.JSONDecodeError:
            continue
        out.append((entry.get("timestamp"), d.get("sg_blk", 0),
                    d.get("spr", {}), d.get("z", {})))
    return out


def main():
    summary = {}
    for variant, run_id in VARIANTS.items():
        per_day = {}
        all_rts = []
        for d in (0, 1, 2):
            run_dir = BT / f"runs/backtest-{run_id}-round3-day-{d}"
            fills = load_fills(run_dir)
            rts = reconstruct_round_trips(fills)
            lam = parse_lambda(run_dir)
            blocks = sum(b for _, b, _, _ in lam)
            # spread distribution at |z|>2 events (any K)
            zopen_events = 0
            zopen_spread_buckets = defaultdict(int)
            for ts, blk, spr, zs in lam:
                if not isinstance(zs, dict) or not isinstance(spr, dict):
                    continue
                for K_str, z_val in zs.items():
                    try:
                        if abs(float(z_val)) > 2.0:
                            zopen_events += 1
                            sp = int(spr.get(K_str, -1))
                            zopen_spread_buckets[sp] += 1
                    except (TypeError, ValueError):
                        pass
            per_day[d] = {
                "n_fills": len(fills),
                "n_round_trips": len(rts),
                "closed_rt_pnl": sum(r["realized_pnl"] for r in rts),
                "n_wins": sum(1 for r in rts if r["realized_pnl"] > 0),
                "n_losses": sum(1 for r in rts if r["realized_pnl"] < 0),
                "spread_blocks": blocks,
                "zopen_events": zopen_events,
                "zopen_spread_buckets": dict(zopen_spread_buckets),
                "hold_ticks_stats": stats([r["hold_ticks"] for r in rts]),
            }
            all_rts.extend(rts)
        all_pnls = [r["realized_pnl"] for r in all_rts]
        all_wins = [p for p in all_pnls if p > 0]
        all_losses = [p for p in all_pnls if p < 0]
        agg = {
            "n_round_trips": len(all_rts),
            "closed_rt_pnl_3d": sum(all_pnls),
            "win_rate": len(all_wins) / len(all_pnls) if all_pnls else None,
            "mean_win": mean(all_wins) if all_wins else None,
            "mean_loss": mean(all_losses) if all_losses else None,
            "spread_blocks_3d": sum(per_day[d]["spread_blocks"] for d in (0,1,2)),
            "zopen_events_3d": sum(per_day[d]["zopen_events"] for d in (0,1,2)),
            "hold_ticks_stats": stats([r["hold_ticks"] for r in all_rts]),
        }
        # per-K closed-RT split
        per_K_pnl = defaultdict(float)
        per_K_n = defaultdict(int)
        for r in all_rts:
            per_K_pnl[r["K"]] += r["realized_pnl"]
            per_K_n[r["K"]] += 1
        agg["per_K"] = {K: {"n": per_K_n[K], "pnl": per_K_pnl[K]} for K in sorted(per_K_pnl)}
        summary[variant] = {"run_id": run_id, "per_day": per_day, "aggregate": agg}

    OUT.write_text(json.dumps(summary, indent=1, default=str))
    print(f"wrote {OUT}\n")

    print("=" * 78)
    print("CLOSED-RT PnL per variant — THE METRIC")
    print("=" * 78)
    print(f"{'variant':<10}{'D=0':>10}{'D+1':>10}{'D+2':>10}{'3-day':>10}"
          f"{'#RT':>6}{'win%':>8}{'mean_win':>10}{'mean_loss':>10}")
    for v, d in summary.items():
        rt0 = d["per_day"][0]["closed_rt_pnl"]
        rt1 = d["per_day"][1]["closed_rt_pnl"]
        rt2 = d["per_day"][2]["closed_rt_pnl"]
        a = d["aggregate"]
        wr = f"{a['win_rate']*100:.0f}%" if a["win_rate"] is not None else "-"
        mw = f"{a['mean_win']:.1f}" if a["mean_win"] is not None else "-"
        ml = f"{a['mean_loss']:.1f}" if a["mean_loss"] is not None else "-"
        print(f"{v:<10}{rt0:>10.1f}{rt1:>10.1f}{rt2:>10.1f}"
              f"{a['closed_rt_pnl_3d']:>10.1f}{a['n_round_trips']:>6d}"
              f"{wr:>8}{mw:>10}{ml:>10}")

    print("\n" + "=" * 78)
    print("Per-strike closed-RT PnL (3d)")
    print("=" * 78)
    Ks = sorted({K for v in summary.values() for K in v["aggregate"]["per_K"]})
    print(f"{'variant':<10}" + "".join(f"{'K='+str(K):>10}" for K in Ks))
    for v, d in summary.items():
        row = [v]
        for K in Ks:
            rec = d["aggregate"]["per_K"].get(K, {"pnl": 0.0, "n": 0})
            if rec["n"]:
                row.append(f"{rec['pnl']:>+5.0f}/{rec['n']}")
            else:
                row.append(f"{'-':>10}")
        s = f"{row[0]:<10}"
        for r in row[1:]:
            s += f"{r:>10}"
        print(s)

    print("\n" + "=" * 78)
    print("Spread-gate diagnostics — blocks per variant + spread @ |z|>2 events")
    print("=" * 78)
    print(f"{'variant':<10}{'blocks':>10}{'zopen3d':>10}{'sp1':>8}{'sp2':>8}"
          f"{'sp3':>8}{'sp4-5':>8}{'sp6-7':>8}{'sp8+':>8}")
    for v, d in summary.items():
        a = d["aggregate"]
        bks = defaultdict(int)
        for day in (0, 1, 2):
            for s, n in d["per_day"][day]["zopen_spread_buckets"].items():
                bks[s] += n
        bins = {"1": bks[1], "2": bks[2], "3": bks[3],
                "4-5": bks[4] + bks[5],
                "6-7": bks[6] + bks[7],
                "8+": sum(bks[s] for s in bks if s >= 8)}
        print(f"{v:<10}{a['spread_blocks_3d']:>10}{a['zopen_events_3d']:>10}"
              f"{bins['1']:>8}{bins['2']:>8}{bins['3']:>8}"
              f"{bins['4-5']:>8}{bins['6-7']:>8}{bins['8+']:>8}")


if __name__ == "__main__":
    main()
