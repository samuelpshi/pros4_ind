"""
Phase-3 Module-A-only sweep driver for v1.5-moduleA-only.

75-combo extended grid that pushes past the v1.5 boundaries:
    passive_wait_ticks      in {8, 12, 18, 25, 35}
    aggressive_z_threshold  in {3.5, 4.5, 6.0, 8.0, inf}
    max_step_size           in {1, 3, 5}

The `inf` az case = passive-only, never escalate; diagnostic anchor.
JSON-serialised as a Python `float('inf')` (Python's json module
defaults to allow_nan=True and writes/reads `Infinity`).

Module B is hard-disabled via `enable_module_b: false`. The trader's
defensive assertion will crash if state ever leaks across the flip.

Schema of the output JSON matches sweep_v1_5_results.json so the
existing heatmap notebook only needs a path change.

Run as: python3 R3/analysis/sweep_v1_5_moduleA_extended.py
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
TRADER = REPO / "R3/traders/trader-r3-v1-vev-v1.5-moduleA-only.py"
CONFIG_PATH = REPO / "R3/traders/configs/vev_v1.5-moduleA-only.json"
RESULTS_CSV = REPO / "R3/analysis/backtest_results.csv"
RESULTS_JSON = REPO / "R3/analysis/sweep_v1_5_moduleA_extended_results.json"
BACKTESTER_REPO = Path(os.path.expanduser("~/prosperity_rust_backtester"))

# Base config (everything except the swept keys). enable_module_b is
# hard-False — the whole point of the sweep is to optimise Module A in
# isolation.
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
    "enable_module_b": False,
}

PW_GRID = [8, 12, 18, 25, 35]
AZ_GRID = [3.5, 4.5, 6.0, 8.0, float("inf")]
MS_GRID = [1, 3, 5]

ROW_RE = re.compile(r"^(D[=+]\S+)\s+(-?\d+)\s+(\d+)\s+(\d+)\s+(-?[\d.]+)\s+(\S+)$")


def az_label(az: float) -> str:
    return "inf" if az == float("inf") else f"{az}"


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
    cfg["aggressive_z_threshold"] = az  # float('inf') -> JSON Infinity
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
        timeout=180,
    )
    pnls, trades = parse_pnls(res.stdout)
    if len(pnls) != 3:
        print(f"WARN combo pw={pw} az={az_label(az)} ms={ms}: parsed {pnls}", file=sys.stderr)
        print(res.stdout[-2000:], file=sys.stderr)
        print("STDERR:", res.stderr[-2000:], file=sys.stderr)
    return pnls, trades


def append_csv_rows(combo_label, pnls, trades, run_dir_placeholder="runs/sweep"):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(RESULTS_CSV, "a") as f:
        for d in (0, 1, 2):
            if d not in pnls:
                continue
            f.write(",".join([
                ts,
                "trader-r3-v1-vev-v1.5-moduleA-only.py",
                str(d),
                f"{pnls[d]:.2f}",
                run_dir_placeholder,
                combo_label,
                f"sweep moduleA; trades={trades.get(d, 0)}",
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
        label = f"v1.5mA-pw{pw}-az{az_label(az)}-ms{ms}"
        append_csv_rows(label, pnls, trades)
        rows.append({
            "pw": pw,
            # Numeric az; float('inf') survives a json.dumps/loads round-trip
            # (allow_nan=True default writes `Infinity`). Schema-compatible
            # with sweep_v1_5_results.json so the heatmap notebook reads it.
            "az": az,
            "ms": ms,
            "d0": vals[0], "d1": vals[1], "d2": vals[2],
            "mean": m, "stdev": s, "score": score,
            "trades_total": sum(trades.values()),
            "label": label,
        })
        elapsed = time.time() - t_start
        eta = elapsed / (i + 1) * (len(combos) - i - 1)
        print(f"[{i+1:3d}/{len(combos)}] {label:34s} mean={m:10.1f} std={s:9.1f} score={score:10.1f}  eta={eta/60:.1f}min", flush=True)

    rows.sort(key=lambda r: r["score"], reverse=True)
    with open(RESULTS_JSON, "w") as f:
        json.dump(rows, f, indent=2)
    print(f"\nResults written to {RESULTS_JSON}")
    print("\nTop 10 by score:")
    for r in rows[:10]:
        print(f"  {r['label']:34s} mean={r['mean']:10.1f} std={r['stdev']:9.1f} score={r['score']:10.1f}")


if __name__ == "__main__":
    main()
