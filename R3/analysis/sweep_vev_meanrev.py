"""
Phase-3 sweep driver for trader-r3-v1-vev-meanrev.py.

Revised grid (post-attribution from Stage-1 findings):
    fair_value_ema_window     in {30, 50, 80, 120}
    take_edge                 in {0, 1, 2, 3, 4}
    skew_strength             in {0.5, 1.0, 1.5, 2.0, 2.5, 3.0}
    aggressive_take_size_cap  in {20, 30, 50}

quote_offset is FIXED at 2 (not swept). Stage-1 sanity showed qo=1
produces 16 trades / 3d in local backtest because the trade-replay
matching model only fills at historical bot trade prices, and bot trades
on VEV happen at the wall (fv +- 2.5). qo=2 puts us at-wall, generating
~21+ trades; qo=3 sits outside the wall, even worse. The qo question is
a live-vs-local-backtest unknown, not a parameter to optimize.

Total combos: 4 * 5 * 6 * 3 = 360.

Schema-compatible with sweep_v1_5_results.json so heatmap notebooks read
it. Score = mean - 1.0 * stdev.

Run as: python3 R3/analysis/sweep_vev_meanrev.py
"""

import json
import re
import subprocess
import sys
import time
from itertools import product
from pathlib import Path
from statistics import mean, stdev

REPO = Path(__file__).resolve().parents[2]
TRADER = REPO / "R3/traders/trader-r3-v1-vev-meanrev.py"
CONFIG_PATH = REPO / "R3/traders/configs/vev_meanrev_v1.json"
RESULTS_CSV = REPO / "R3/analysis/backtest_results.csv"
RESULTS_JSON = REPO / "R3/analysis/sweep_vev_meanrev_results.json"
BACKTESTER_REPO = Path("/Users/samuelshi/prosperity_rust_backtester")

# Base config; only the swept keys vary. quote_offset hard-fixed at 2.
BASE_CONFIG = {
    "fair_value_ema_window": 50,
    "quote_offset": 2,
    "skew_strength": 1.0,
    "take_edge": 2,
    "passive_quote_size": 20,
    "aggressive_take_size_cap": 30,
    "position_limit": 200,
    "kill_threshold": 150,
    "kill_dwell_ticks": 500,
    "kill_release": 100,
}

EMA_GRID = [30, 50, 80, 120]
# Pruned post-pilot: te=3,4 dominated (mean ~-1480, pos% 12.5%); kept 0/1/2.
TE_GRID = [0, 1, 2]
# Pruned post-pilot: sk=2.5,3.0 dominated by sk=0.5/1.0/1.5; kept low half.
SK_GRID = [0.5, 1.0, 1.5, 2.0]
# Pruned post-pilot: tc=50 worse than tc=20/30 across axis.
TC_GRID = [20, 30]

ROW_RE = re.compile(r"^(D[=+]\S+)\s+(-?\d+)\s+(\d+)\s+(\d+)\s+(-?[\d.]+)\s+(\S+)$")


def parse_pnls(stdout: str):
    pnls, trades, run_dirs = {}, {}, {}
    for line in stdout.splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        _, day, _ticks, own_trades, final, run = m.groups()
        d = int(day)
        if d in (0, 1, 2):
            pnls[d] = float(final)
            trades[d] = int(own_trades)
            run_dirs[d] = run
    return pnls, trades, run_dirs


def trajectory_stats(run_dir: Path):
    """From a run dir's trades.csv, compute max |pos| and ticks at |pos|>80
    for the VEV product. ticks counted as (timestamp gaps / 100), starting
    from t=0 to t=999900 (10000 ticks per day)."""
    tcsv = run_dir / "trades.csv"
    if not tcsv.exists():
        return 0, 0
    fills = []  # (timestamp, signed_qty)
    with open(tcsv) as f:
        import csv as _csv
        rdr = _csv.DictReader(f, delimiter=";")
        for row in rdr:
            if row["symbol"] != "VELVETFRUIT_EXTRACT":
                continue
            t = int(row["timestamp"])
            q = int(row["quantity"])
            if row["buyer"] == "SUBMISSION":
                fills.append((t, +q))
            elif row["seller"] == "SUBMISSION":
                fills.append((t, -q))
    fills.sort()
    pos = 0
    last_t = 0
    max_abs = 0
    pinned = 0  # in ts units, divide by 100 at end
    for t, q in fills:
        # interval [last_t, t): pos was at previous level
        if abs(pos) > 80:
            pinned += t - last_t
        pos += q
        if abs(pos) > max_abs:
            max_abs = abs(pos)
        last_t = t
    # tail interval to end-of-day (t=999900 last tick)
    end_t = 1_000_000
    if abs(pos) > 80:
        pinned += end_t - last_t
    return max_abs, pinned // 100


def run_combo(ema, te, sk, tc, days_arg=None):
    cfg = dict(BASE_CONFIG)
    cfg["fair_value_ema_window"] = ema
    cfg["take_edge"] = te
    cfg["skew_strength"] = sk
    cfg["aggressive_take_size_cap"] = tc
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    cmd = ["rust_backtester",
           "--trader", str(TRADER),
           "--dataset", "round3",
           "--products", "summary",
           "--persist"]
    if days_arg is not None:
        cmd += ["--day", str(days_arg)]
    res = subprocess.run(
        cmd,
        cwd=str(BACKTESTER_REPO),
        capture_output=True,
        text=True,
        timeout=300,
    )
    pnls, trades, run_dirs = parse_pnls(res.stdout)
    return pnls, trades, run_dirs, res.stdout, res.stderr


def cleanup_run_dirs(run_dirs):
    """Delete heavy artifacts to keep disk usage bounded; keep trades.csv
    in case we want to re-derive trajectory stats later."""
    for d, rd in run_dirs.items():
        rdp = BACKTESTER_REPO / rd
        for fname in ("bundle.json", "combined.log", "submission.log",
                      "activity.csv", "pnl_by_product.csv", "metrics.json"):
            fp = rdp / fname
            if fp.exists():
                try:
                    fp.unlink()
                except OSError:
                    pass


def append_csv_rows(combo_label, pnls, trades, run_dir_placeholder="runs/sweep"):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(RESULTS_CSV, "a") as f:
        for d in (0, 1, 2):
            if d not in pnls:
                continue
            f.write(",".join([
                ts,
                "trader-r3-v1-vev-meanrev.py",
                str(d),
                f"{pnls[d]:.2f}",
                run_dir_placeholder,
                combo_label,
                f"sweep vev_meanrev; trades={trades.get(d, 0)}",
            ]) + "\n")


def main():
    pilot_only = "--pilot" in sys.argv
    pilot_day = 2  # day 2 has the most bot trades (477) and best signal density

    combos = list(product(EMA_GRID, TE_GRID, SK_GRID, TC_GRID))
    print(f"Running {len(combos)} combos {'(PILOT D2 only)' if pilot_only else '(full 3-day)'}...", flush=True)
    rows = []
    t_start = time.time()
    for i, (ema, te, sk, tc) in enumerate(combos):
        if pilot_only:
            pnls, trades, run_dirs, _, _ = run_combo(ema, te, sk, tc, days_arg=pilot_day)
            if pilot_day not in pnls:
                print(f"WARN combo ema={ema} te={te} sk={sk} tc={tc}: parse failed", file=sys.stderr)
                continue
            label = f"vmr-ema{ema}-te{te}-sk{sk}-tc{tc}"
            d2_pnl = pnls[pilot_day]
            d2_trd = trades[pilot_day]
            rows.append({"ema": ema, "te": te, "sk": sk, "tc": tc,
                         "d2": d2_pnl, "d2_trades": d2_trd, "label": label})
            elapsed = time.time() - t_start
            eta = elapsed / (i + 1) * (len(combos) - i - 1)
            print(f"[{i+1:3d}/{len(combos)}] {label:34s} d2={d2_pnl:9.1f} trd={d2_trd:4d}  eta={eta/60:.1f}min", flush=True)
        else:
            pnls, trades, run_dirs, _, _ = run_combo(ema, te, sk, tc)
            if len(pnls) != 3:
                print(f"WARN combo ema={ema} te={te} sk={sk} tc={tc}: parsed {pnls}", file=sys.stderr)
                continue
            # trajectory stats (max |pos|, ticks-at-|pos|>80) per day
            traj = {}
            for d in (0, 1, 2):
                rd = run_dirs.get(d)
                if rd is None:
                    traj[d] = (0, 0)
                else:
                    traj[d] = trajectory_stats(BACKTESTER_REPO / rd)
            max_abs_3d = max(traj[d][0] for d in (0, 1, 2))
            pinned_3d = sum(traj[d][1] for d in (0, 1, 2))
            cleanup_run_dirs(run_dirs)
            vals = [pnls[0], pnls[1], pnls[2]]
            m = mean(vals)
            s = stdev(vals)
            score = m - 1.0 * s
            label = f"vmr-ema{ema}-te{te}-sk{sk}-tc{tc}"
            append_csv_rows(label, pnls, trades)
            rows.append({
                "ema": ema, "te": te, "sk": sk, "tc": tc,
                "d0": vals[0], "d1": vals[1], "d2": vals[2],
                "mean": m, "stdev": s, "score": score,
                "trades_total": sum(trades.values()),
                "max_abs_pos_3d": max_abs_3d,
                "pinned_ticks_above_80_3d": pinned_3d,
                "max_abs_pos_per_day": [traj[0][0], traj[1][0], traj[2][0]],
                "pinned_ticks_above_80_per_day": [traj[0][1], traj[1][1], traj[2][1]],
                "label": label,
            })
            elapsed = time.time() - t_start
            eta = elapsed / (i + 1) * (len(combos) - i - 1)
            print(f"[{i+1:3d}/{len(combos)}] {label:34s} mean={m:9.1f} std={s:8.1f} score={score:9.1f}  trd={sum(trades.values()):4d}  maxpos={max_abs_3d:3d} pin>{pinned_3d:5d}  eta={eta/60:.1f}min", flush=True)

    if pilot_only:
        rows.sort(key=lambda r: r["d2"], reverse=True)
        out = REPO / "R3/analysis/sweep_vev_meanrev_pilot.json"
    else:
        rows.sort(key=lambda r: r["score"], reverse=True)
        out = RESULTS_JSON
    with open(out, "w") as f:
        json.dump(rows, f, indent=2)
    print(f"\nResults written to {out}")
    print("\nTop 10:")
    for r in rows[:10]:
        if pilot_only:
            print(f"  {r['label']:34s} d2={r['d2']:9.1f} trd={r['d2_trades']:4d}")
        else:
            print(f"  {r['label']:34s} mean={r['mean']:9.1f} std={r['stdev']:8.1f} score={r['score']:9.1f}")


if __name__ == "__main__":
    main()
