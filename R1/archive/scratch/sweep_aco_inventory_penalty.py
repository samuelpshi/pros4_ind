#!/usr/bin/env python3
"""
sweep_aco_inventory_penalty.py — ACO inventory penalty sweep runner.
Pass 5 of IMC Prosperity 4 Round 1 optimization.

Strategy:
  - Creates temp copies of trader-v9-r1.py in scratch/ with each penalty value
    (sed-replace the single constant line ACO_INVENTORY_PENALTY = 0.025)
  - Invokes prosperity4btest for each (penalty, scenario) combination
  - Saves logs to runs/pass5/<logname>.log
  - Outputs CSV and log-index markdown

NOTE: This script was written but the full sweep was NOT run because the
corner test gate failed (ACO delta = +270, threshold = 2,000).
The corner test results (0.025 and 0.050 merged) are already in
runs/pass5/ and sweep_results_aco_inv_penalty.csv.

To run the full sweep anyway, set SKIP_GATE = True below.

Usage:
  python scratch/sweep_aco_inventory_penalty.py
  (Run from repo root: /Users/samuelshi/IMC-Prosperity-2026-personal/)
"""

import subprocess
import re
import os
import sys
import csv
import json
from pathlib import Path

# ---- Configuration ----
REPO_ROOT = Path("/Users/samuelshi/IMC-Prosperity-2026-personal")
SOURCE_TRADER = REPO_ROOT / "Round 1" / "traders" / "trader-v9-r1.py"
SCRATCH_DIR = REPO_ROOT / "scratch"
RUNS_DIR = REPO_ROOT / "runs" / "pass5"
CSV_OUT = REPO_ROOT / "Round 1" / "analysis" / "sweep_results_aco_inv_penalty.csv"
INDEX_OUT = REPO_ROOT / "Round 1" / "analysis" / "sweep_log_index.md"
PARSE_LOGS_PY = REPO_ROOT / "scratch" / "parse_logs.py"

# Sweep values for full sweep (Step 2)
SWEEP_PENALTIES = [0.025, 0.030, 0.035, 0.040, 0.045, 0.050]

# Scenarios: (label, prosperity4btest day arg, merge-pnl flag)
SCENARIOS = [
    ("day_-2",   "1--2", False),
    ("day_-1",   "1--1", False),
    ("day_0",    "1-0",  False),
    ("merged",   "1",    True),
    # merged_worse: --match-trades worse (skip if unsupported)
    ("merged_worse", "1", True),
]

# Gate: corner test delta threshold
GATE_THRESHOLD = 2000
SKIP_GATE = False  # set True to force full sweep regardless of gate


def penalty_to_safe_str(v: float) -> str:
    """0.025 -> '0_025'"""
    return f"{v:.3f}".replace(".", "_")


def make_sweep_trader(penalty: float) -> Path:
    """Create a copy of trader-v9-r1.py with the given penalty value."""
    safe = penalty_to_safe_str(penalty)
    out_path = SCRATCH_DIR / f"sweep_aco_{safe}.py"
    if out_path.exists():
        # Check if already correct
        content = out_path.read_text()
        expected = f"ACO_INVENTORY_PENALTY   = {penalty}"
        if expected in content:
            print(f"  [skip] {out_path.name} already exists with correct penalty")
            return out_path

    source_content = SOURCE_TRADER.read_text()
    new_content = re.sub(
        r"ACO_INVENTORY_PENALTY\s*=\s*[\d.]+",
        f"ACO_INVENTORY_PENALTY   = {penalty}",
        source_content
    )
    if new_content == source_content:
        raise RuntimeError(f"ACO_INVENTORY_PENALTY line not found in {SOURCE_TRADER}")
    out_path.write_text(new_content)
    print(f"  [created] {out_path.name}")
    return out_path


def run_backtest(trader_path: Path, day_arg: str, merge_pnl: bool,
                 match_trades_worse: bool, log_path: Path) -> dict:
    """
    Run prosperity4btest and return parsed results.
    Returns dict with keys: total_pnl, aco_pnl, ipr_pnl, aco_max_abs_pos,
                             ipr_max_abs_pos, engine_rejections_aco, ok, error
    """
    cmd = ["prosperity4btest", str(trader_path), day_arg, "--no-progress",
           "--out", str(log_path)]
    if merge_pnl:
        cmd.append("--merge-pnl")
    if match_trades_worse:
        cmd.extend(["--match-trades", "worse"])

    print(f"  Running: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                              cwd=str(REPO_ROOT))
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr[:500]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except FileNotFoundError:
        return {"ok": False, "error": "prosperity4btest not found"}

    # Parse stdout for quick numbers
    stdout = proc.stdout
    total_match = re.search(r"Total profit:\s*([\d,]+)", stdout)
    total_pnl = float(total_match.group(1).replace(",", "")) if total_match else None

    # Get per-product from last occurrence in stdout
    aco_vals, ipr_vals = [], []
    for line in stdout.splitlines():
        m_aco = re.match(r"ASH_COATED_OSMIUM:\s*([\d,]+)", line.strip())
        m_ipr = re.match(r"INTARIAN_PEPPER_ROOT:\s*([\d,]+)", line.strip())
        if m_aco:
            aco_vals.append(float(m_aco.group(1).replace(",", "")))
        if m_ipr:
            ipr_vals.append(float(m_ipr.group(1).replace(",", "")))

    aco_pnl = sum(aco_vals) if aco_vals else None
    ipr_pnl = sum(ipr_vals) if ipr_vals else None

    # Parse log for max position and rejections
    result = {
        "ok": True, "error": None,
        "total_pnl": total_pnl,
        "aco_pnl": aco_pnl,
        "ipr_pnl": ipr_pnl,
        "aco_max_abs_pos": None,
        "ipr_max_abs_pos": None,
        "engine_rejections_aco": None,
    }

    if log_path.exists():
        # Use parse_logs if available
        try:
            sys.path.insert(0, str(SCRATCH_DIR))
            from parse_logs import parse_log
            parsed = parse_log(str(log_path))
            prods = parsed.get("products", {})
            aco_p = prods.get("ASH_COATED_OSMIUM", {})
            ipr_p = prods.get("INTARIAN_PEPPER_ROOT", {})
            # Per-day max abs: take max(abs(max_pos), abs(min_pos))
            aco_max = max(abs(aco_p.get("max_position", 0) or 0),
                          abs(aco_p.get("min_position", 0) or 0))
            ipr_max = max(abs(ipr_p.get("max_position", 0) or 0),
                          abs(ipr_p.get("min_position", 0) or 0))
            result["aco_max_abs_pos"] = aco_max
            result["ipr_max_abs_pos"] = ipr_max
            result["engine_rejections_aco"] = parsed.get("exceeded_limit_aco", 0)
        except Exception as e:
            print(f"    [warn] parse_logs failed: {e}")

    return result


def run_corner_test():
    """Step 1: corner test with 0.025 and 0.050 in merged scenario."""
    print("\n=== CORNER TEST ===")
    results = {}
    for penalty in [0.025, 0.050]:
        safe = penalty_to_safe_str(penalty)
        trader = make_sweep_trader(penalty)
        log_path = RUNS_DIR / f"corner_{safe}_merged.log"
        print(f"\n  penalty={penalty}")
        r = run_backtest(trader, "1", merge_pnl=True, match_trades_worse=False,
                         log_path=log_path)
        results[penalty] = r
        if r["ok"]:
            print(f"    total={r['total_pnl']:.0f}  aco={r['aco_pnl']:.0f}  ipr={r['ipr_pnl']:.0f}")
        else:
            print(f"    FAILED: {r['error']}")

    r025 = results.get(0.025, {})
    r050 = results.get(0.050, {})
    if not r025.get("ok") or not r050.get("ok"):
        print("  GATE: CANNOT EVALUATE — backtest failed")
        return False, results

    delta = (r050.get("aco_pnl") or 0) - (r025.get("aco_pnl") or 0)
    print(f"\n  ACO delta (0.050 - 0.025) = {delta:.1f}")
    print(f"  Gate threshold = {GATE_THRESHOLD}")
    gate_pass = delta >= GATE_THRESHOLD
    print(f"  Gate: {'PASSED — proceed to full sweep' if gate_pass else 'FAILED — NO_MEANINGFUL_SIGNAL'}")
    return gate_pass, results


def run_full_sweep():
    """Step 2: full sweep over all penalty values and scenarios."""
    print("\n=== FULL SWEEP ===")
    all_rows = []
    index_entries = []

    for penalty in SWEEP_PENALTIES:
        safe = penalty_to_safe_str(penalty)
        trader = make_sweep_trader(penalty)

        for scenario_label, day_arg, merge_pnl in SCENARIOS:
            match_worse = (scenario_label == "merged_worse")
            log_name = f"sweep_{safe}_{scenario_label}.log"
            log_path = RUNS_DIR / log_name
            print(f"\n  penalty={penalty}  scenario={scenario_label}")
            r = run_backtest(trader, day_arg, merge_pnl=merge_pnl,
                             match_trades_worse=match_worse, log_path=log_path)

            row = {
                "penalty": penalty,
                "scenario": scenario_label,
                "total_pnl": r.get("total_pnl"),
                "aco_pnl": r.get("aco_pnl"),
                "ipr_pnl": r.get("ipr_pnl"),
                "aco_max_abs_pos": r.get("aco_max_abs_pos"),
                "ipr_max_abs_pos": r.get("ipr_max_abs_pos"),
                "engine_rejections": r.get("engine_rejections_aco"),
            }
            all_rows.append(row)
            index_entries.append((penalty, scenario_label, log_path))

            if r.get("ok"):
                print(f"    total={r['total_pnl']:.0f}  aco={r['aco_pnl']:.0f}  "
                      f"ipr={r['ipr_pnl']:.0f}")
            else:
                print(f"    FAILED: {r.get('error')}")

    return all_rows, index_entries


def write_csv(rows, path):
    fieldnames = ["penalty", "scenario", "total_pnl", "aco_pnl", "ipr_pnl",
                  "aco_max_abs_pos", "ipr_max_abs_pos", "engine_rejections"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    print(f"\nWrote CSV: {path}")


def write_log_index(entries, path):
    lines = [
        "# Pass 5 — ACO Inventory Penalty Sweep Log Index",
        "",
        "| penalty | scenario | log_path |",
        "|---------|----------|----------|",
    ]
    for penalty, scenario, log_path in entries:
        lines.append(f"| {penalty} | {scenario} | `{log_path}` |")
    lines.append("")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"Wrote index: {path}")


def main():
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Corner test
    gate_passed, corner_results = run_corner_test()

    # Write corner-test CSV
    csv_rows = []
    for penalty in [0.025, 0.050]:
        r = corner_results.get(penalty, {})
        csv_rows.append({
            "penalty": penalty,
            "scenario": "merged",
            "total_pnl": r.get("total_pnl"),
            "aco_pnl": r.get("aco_pnl"),
            "ipr_pnl": r.get("ipr_pnl"),
            "aco_max_abs_pos": r.get("aco_max_abs_pos"),
            "ipr_max_abs_pos": r.get("ipr_max_abs_pos"),
            "engine_rejections": r.get("engine_rejections_aco"),
        })

    if not gate_passed and not SKIP_GATE:
        write_csv(csv_rows, CSV_OUT)
        print("\nGate FAILED. Stopping. See pass5_corner_test_verdict.md for details.")
        return

    # Step 2: Full sweep
    all_rows, index_entries = run_full_sweep()

    # Combine corner results with full sweep (avoid duplicates)
    # Use full sweep results for 0.025 and 0.050 merged if available
    write_csv(all_rows, CSV_OUT)
    write_log_index(index_entries, INDEX_OUT)


if __name__ == "__main__":
    main()
