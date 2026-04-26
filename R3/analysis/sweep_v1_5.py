"""
Stage-2a-extended sweep driver for v1.5-scalp-only.

Sweeps:
    passive_wait_ticks  in {1, 2, 3, 5, 8}
    aggressive_z_threshold in {1.8, 2.0, 2.5, 3.0, 3.5}
    max_step_size in {5, 10, 15, 25, 40}

For each of the 125 combos: writes the trader's config JSON, runs the
rust backtester for 3 days (single CLI invocation, current_day=0 used
throughout — Module C is gone so the ~13% TTE-induced delta error has
no hedge to amplify; smile-fit absorbs the residual on the alpha side
per the v1.3-vs-v1.4 finding in P2_v1_4_execution_log.md), parses
FINAL_PNL per day, appends to backtest_results.csv, computes
score = mean(pnl) - 1.0 * stdev(pnl).

Run as: python3 R3/analysis/sweep_v1_5.py
"""

import json
import os  # standalone driver, NOT a trader file -> os import is fine here
import re
import subprocess
import sys
import time
from itertools import product
from pathlib import Path
from statistics import mean, stdev

REPO = Path(__file__).resolve().parents[2]
TRADER = REPO / "R3/traders/trader-r3-v1-vev-v1.5-scalp-only.py"
CONFIG_PATH = REPO / "R3/traders/configs/vev_v1.5-scalp-only.json"
RESULTS_CSV = REPO / "R3/analysis/backtest_results.csv"
BACKTESTER_REPO = Path(os.path.expanduser("~/prosperity_rust_backtester"))

# Base config (everything except the swept keys).
BASE_CONFIG = {
    "active_strikes": [5000, 5100, 5200, 5300, 5400, 5500],
    "smile_fit_min_strikes": 4,
    "smile_hardcoded_fallback": {"a": 0.143, "b": -0.002, "c": 0.236},
    "ema_demean_window": 20,
    "zscore_stdev_window": 100,
    "z_open_threshold": 1.5,
    "z_close_threshold": 0.5,
    "strike_position_caps": {
        "5000": 60, "5100": 80, "5200": 120, "5300": 120, "5400": 80, "5500": 60,
    },
    "base_iv_zscore_window": 500,
    "base_iv_z_open": 1.5,
    "base_iv_z_close": 0.5,
    "base_iv_position_size": 25,
    "voucher_position_limit": 300,
    "round_day_to_tte_days": {"0": 8, "1": 7, "2": 6, "3": 5, "4": 4, "5": 3},
    "current_day": 0,
    "min_hold_ticks": 5,
    "cooldown_ticks": 10,
}

PW_GRID = [1, 2, 3, 5, 8]
AZ_GRID = [1.8, 2.0, 2.5, 3.0, 3.5]
MS_GRID = [5, 10, 15, 25, 40]

ROW_RE = re.compile(r"^(D[=+]\S+)\s+(-?\d+)\s+(\d+)\s+(\d+)\s+(-?[\d.]+)\s+(\S+)$")


def parse_pnls(stdout: str):
    pnls = {}
    trades = {}
    for line in stdout.splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        _, day, _ticks, own_trades, final, _run = m.groups()
        d = int(day)
        if d in (0, 1, 2):
            pnls[d] = float(final)
            trades[d] = int(own_trades)
    return pnls, trades


def run_combo(pw, az, ms):
    cfg = dict(BASE_CONFIG)
    cfg["passive_wait_ticks"] = pw
    cfg["aggressive_z_threshold"] = az
    cfg["max_step_size"] = ms
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    res = subprocess.run(
        ["rust_backtester",
         "--trader", str(TRADER),
         "--dataset", "round3",
         "--products", "summary"],
        cwd=str(BACKTESTER_REPO),
        capture_output=True,
        text=True,
        timeout=120,
    )
    pnls, trades = parse_pnls(res.stdout)
    if len(pnls) != 3:
        print(f"WARN combo pw={pw} az={az} ms={ms}: parsed {pnls}", file=sys.stderr)
        print(res.stdout[-2000:], file=sys.stderr)
    return pnls, trades


def append_csv_rows(combo_label, pnls, trades, run_dir_placeholder="runs/sweep"):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(RESULTS_CSV, "a") as f:
        for d in (0, 1, 2):
            if d not in pnls:
                continue
            f.write(",".join([
                ts,
                "trader-r3-v1-vev-v1.5-scalp-only.py",
                str(d),
                f"{pnls[d]:.2f}",
                run_dir_placeholder,
                combo_label,
                f"sweep; trades={trades.get(d, 0)}",
            ]) + "\n")


def main():
    combos = list(product(PW_GRID, AZ_GRID, MS_GRID))
    print(f"Running {len(combos)} combos...", flush=True)
    rows = []
    t_start = time.time()
    for i, (pw, az, ms) in enumerate(combos):
        pnls, trades = run_combo(pw, az, ms)
        if len(pnls) != 3:
            continue
        vals = [pnls[0], pnls[1], pnls[2]]
        m = mean(vals)
        s = stdev(vals)
        score = m - 1.0 * s
        label = f"v1.5-pw{pw}-az{az}-ms{ms}"
        append_csv_rows(label, pnls, trades)
        rows.append({
            "pw": pw, "az": az, "ms": ms,
            "d0": vals[0], "d1": vals[1], "d2": vals[2],
            "mean": m, "stdev": s, "score": score,
            "trades_total": sum(trades.values()),
            "label": label,
        })
        elapsed = time.time() - t_start
        eta = elapsed / (i + 1) * (len(combos) - i - 1)
        print(f"[{i+1:3d}/{len(combos)}] {label:30s} mean={m:10.1f} std={s:9.1f} score={score:10.1f}  eta={eta/60:.1f}min", flush=True)

    rows.sort(key=lambda r: r["score"], reverse=True)
    out = REPO / "R3/analysis/sweep_v1_5_results.json"
    with open(out, "w") as f:
        json.dump(rows, f, indent=2)
    print(f"\nResults written to {out}")
    print("\nTop 10 by score:")
    for r in rows[:10]:
        print(f"  {r['label']:30s} mean={r['mean']:10.1f} std={r['stdev']:9.1f} score={r['score']:10.1f}")


if __name__ == "__main__":
    main()
