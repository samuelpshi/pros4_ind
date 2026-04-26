"""
Phase-3.5 z_open diagnostic.

Holds execution constant at the prior canonical config
(pw=8, az=3.5, ms=5) -- NOT the Phase-3 sweep winner -- and varies
z_open_threshold across [1.5, 2.0, 2.5, 3.0, 3.5]. Module B stays off.

For each value:
  1. Copy the matching config into the canonical slot
     (vev_v1.5-moduleA-only.json) so the trader picks it up.
  2. Run rust_backtester with --persist + --products full.
  3. Parse stdout for per-day total PnL + own_trades.
  4. Parse pnl_by_product.csv (last row per day) for per-strike PnL.
  5. Parse trades.csv per day for per-strike own-fill counts.
  6. Run diagnostics_v1_5.compute_diagnostics on each day's submission.log
     for per-strike capture-to-cost ratio.

Output: R3/analysis/zopen_diagnostic_results.json (one block per
z_open) plus pretty stdout.

Run: python3 R3/analysis/zopen_diagnostic.py
"""

import json
import os  # standalone driver, NOT a trader file -> os import is fine here
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from statistics import mean, stdev

REPO = Path(__file__).resolve().parents[2]
TRADER = REPO / "R3/traders/trader-r3-v1-vev-v1.5-moduleA-only.py"
CFG_DIR = REPO / "R3/traders/configs"
CANONICAL = CFG_DIR / "vev_v1.5-moduleA-only.json"
RESULTS_CSV = REPO / "R3/analysis/backtest_results.csv"
RESULTS_JSON = REPO / "R3/analysis/zopen_diagnostic_results.json"
BACKTESTER_REPO = Path(os.path.expanduser("~/prosperity_rust_backtester"))

ACTIVE_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
Z_OPEN_VALUES = [1.5, 2.0, 2.5, 3.0, 3.5]

# Match rust_backtester table rows.
ROW_RE = re.compile(r"^(D[=+]\S+)\s+(-?\d+)\s+(\d+)\s+(\d+)\s+(-?[\d.]+)\s+(\S+)$")
BUNDLE_RE = re.compile(r"bundle:\s+(runs/[\w-]+)")


def parse_pnls_and_runs(stdout: str):
    """Returns ({day: pnl}, {day: trades}, {day: run_dir_relative})."""
    pnls, trades, runs = {}, {}, {}
    for line in stdout.splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        _, day, _ticks, own_trades, final, run = m.groups()
        d = int(day)
        if d in (0, 1, 2):
            pnls[d] = float(final)
            trades[d] = int(own_trades)
            runs[d] = run
    return pnls, trades, runs


def per_strike_from_run(run_abs: Path):
    """Per-strike (fills, end-of-day PnL) for one run dir."""
    fills = {K: 0 for K in ACTIVE_STRIKES}
    pnl = {K: 0.0 for K in ACTIVE_STRIKES}

    trades_csv = run_abs / "trades.csv"
    if trades_csv.is_file():
        with open(trades_csv) as f:
            header = f.readline().strip().split(";")
            idx = {h: i for i, h in enumerate(header)}
            for line in f:
                cells = line.rstrip("\n").split(";")
                if len(cells) < len(header):
                    continue
                buyer = cells[idx["buyer"]]
                seller = cells[idx["seller"]]
                if buyer != "SUBMISSION" and seller != "SUBMISSION":
                    continue
                sym = cells[idx["symbol"]]
                if not sym.startswith("VEV_"):
                    continue
                try:
                    K = int(sym.split("_")[1])
                except ValueError:
                    continue
                if K not in fills:
                    continue
                qty = int(cells[idx["quantity"]])
                fills[K] += qty

    pnl_csv = run_abs / "pnl_by_product.csv"
    if pnl_csv.is_file():
        with open(pnl_csv) as f:
            header = f.readline().strip().split(";")
            idx = {h: i for i, h in enumerate(header)}
            last_cells = None
            for line in f:
                cells = line.rstrip("\n").split(";")
                if len(cells) >= len(header):
                    last_cells = cells
            if last_cells is not None:
                for K in ACTIVE_STRIKES:
                    sym = f"VEV_{K}"
                    if sym in idx:
                        try:
                            pnl[K] = float(last_cells[idx[sym]])
                        except (ValueError, IndexError):
                            pnl[K] = 0.0
    return fills, pnl


def diagnostics_per_strike(submission_log_path: Path):
    """Calls into diagnostics_v1_5.compute_diagnostics for one day's
    submission.log; returns {K: {capture_to_cost, n_round_trips, hit_rate, ...}}.
    """
    sys.path.insert(0, str(REPO / "R3/analysis"))
    try:
        from diagnostics_v1_5 import compute_diagnostics  # noqa
    except Exception as e:
        print(f"WARN: diagnostics_v1_5 import failed: {e}", file=sys.stderr)
        return None
    try:
        return compute_diagnostics(str(submission_log_path))
    except Exception as e:
        print(f"WARN: diagnostics on {submission_log_path} failed: {e}", file=sys.stderr)
        return None


def run_one(z_open: float):
    cfg_src = CFG_DIR / f"vev_v1.5-moduleA-only-zopen-{z_open}.json"
    if not cfg_src.is_file():
        raise FileNotFoundError(cfg_src)
    shutil.copy(cfg_src, CANONICAL)

    res = subprocess.run(
        ["rust_backtester",
         "--trader", str(TRADER),
         "--dataset", "round3",
         "--products", "full",
         "--persist"],
        cwd=str(BACKTESTER_REPO),
        capture_output=True,
        text=True,
        timeout=180,
    )
    pnls, trades, runs = parse_pnls_and_runs(res.stdout)
    if len(pnls) != 3:
        print(f"WARN z_open={z_open}: got {pnls}", file=sys.stderr)
        print(res.stdout[-2000:], file=sys.stderr)
        return None

    # Per-day per-strike fills + pnl + capture/cost diagnostics
    per_day = {}
    for d in (0, 1, 2):
        run_abs = BACKTESTER_REPO / runs[d]
        fills, pnl = per_strike_from_run(run_abs)
        diag = diagnostics_per_strike(run_abs / "submission.log")
        per_day[d] = {
            "total_pnl": pnls[d],
            "own_trades_total": trades[d],
            "run_dir": runs[d],
            "per_strike_fills": fills,
            "per_strike_pnl": pnl,
            "per_strike_diagnostics": diag,
        }
    return per_day


def aggregate_3day(per_day):
    pnls = [per_day[d]["total_pnl"] for d in (0, 1, 2)]
    trades = [per_day[d]["own_trades_total"] for d in (0, 1, 2)]
    fills_3d = {K: 0 for K in ACTIVE_STRIKES}
    pnl_3d = {K: 0.0 for K in ACTIVE_STRIKES}
    rt_pnl_3d = {K: [] for K in ACTIVE_STRIKES}      # avg per share, per-day
    cap_cost_3d = {K: [] for K in ACTIVE_STRIKES}
    n_rt_3d = {K: 0 for K in ACTIVE_STRIKES}
    for d in (0, 1, 2):
        for K in ACTIVE_STRIKES:
            fills_3d[K] += per_day[d]["per_strike_fills"][K]
            pnl_3d[K] += per_day[d]["per_strike_pnl"][K]
            diag = per_day[d].get("per_strike_diagnostics")
            if not diag:
                continue
            m = diag.get(K, {})
            n_rt_3d[K] += m.get("n_round_trips", 0)
            if m.get("avg_rt_pnl_per_share") is not None:
                rt_pnl_3d[K].append(m["avg_rt_pnl_per_share"])
            if m.get("capture_to_cost") is not None:
                cap_cost_3d[K].append(m["capture_to_cost"])

    return {
        "mean_pnl": mean(pnls),
        "stdev_pnl": stdev(pnls),
        "trades_total": sum(trades),
        "trades_per_day": sum(trades) / 3.0,
        "per_day_pnl": {str(d): pnls[d] for d in (0, 1, 2)},
        "per_strike_fills_3d": fills_3d,
        "per_strike_pnl_3d": pnl_3d,
        "per_strike_n_rt_3d": n_rt_3d,
        "per_strike_avg_rt_pnl_per_share": {
            K: (mean(v) if v else None) for K, v in rt_pnl_3d.items()
        },
        "per_strike_avg_capture_to_cost": {
            K: (mean(v) if v else None) for K, v in cap_cost_3d.items()
        },
    }


def append_csv_rows(z_open, per_day):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(RESULTS_CSV, "a") as f:
        for d in (0, 1, 2):
            f.write(",".join([
                ts,
                "trader-r3-v1-vev-v1.5-moduleA-only.py",
                str(d),
                f"{per_day[d]['total_pnl']:.2f}",
                per_day[d]["run_dir"],
                f"v1.5mA-zopen{z_open}-pw8-az3.5-ms5",
                f"P3.5 zopen diagnostic; trades={per_day[d]['own_trades_total']}",
            ]) + "\n")


def main():
    out = []
    for z in Z_OPEN_VALUES:
        print(f"\n=== z_open = {z} ===", flush=True)
        t0 = time.time()
        per_day = run_one(z)
        if per_day is None:
            continue
        agg = aggregate_3day(per_day)
        append_csv_rows(z, per_day)
        block = {
            "z_open": z,
            "config": f"vev_v1.5-moduleA-only-zopen-{z}.json",
            "per_day": per_day,
            "summary": agg,
        }
        out.append(block)
        dt = time.time() - t0
        print(f"  mean PnL/day = {agg['mean_pnl']:8.2f}  "
              f"stdev = {agg['stdev_pnl']:7.2f}  "
              f"trades/day = {agg['trades_per_day']:5.1f}  "
              f"({dt:.1f}s)")
        print(f"  per-strike fills (3d): {agg['per_strike_fills_3d']}")
        print(f"  per-strike PnL    (3d): "
              + ", ".join(f"{K}={agg['per_strike_pnl_3d'][K]:.1f}" for K in ACTIVE_STRIKES))
        print(f"  per-strike cap/cost  : "
              + ", ".join(
                  f"{K}={(v if v is not None else float('nan')):+.2f}"
                  for K, v in agg["per_strike_avg_capture_to_cost"].items()
              ))

    with open(RESULTS_JSON, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nResults JSON: {RESULTS_JSON}")
    print("\nSummary table:")
    print(f"{'z_open':>7} {'mean_pnl':>10} {'stdev':>8} {'trades/d':>10} {'trades/3d':>11}")
    for b in out:
        s = b["summary"]
        print(f"{b['z_open']:>7} {s['mean_pnl']:>10.2f} {s['stdev_pnl']:>8.2f} "
              f"{s['trades_per_day']:>10.1f} {s['trades_total']:>11}")


if __name__ == "__main__":
    main()
