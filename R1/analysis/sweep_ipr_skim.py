#!/usr/bin/env python3
"""
sweep_ipr_skim.py — IPR skim/refill parameter sweep runner.
IMC Prosperity 4 Round 1.

Sweeps 3 IPR parameters injected via env vars into trader-v8-173159.py:
  IPR_SKIM_SIZE        [3, 5, 7, 10, 15]
  IPR_SKIM_OFFSET      [1, 2, 3, 4, 5]
  IPR_REFILL_MAX_SIZE  [5, 10, 15, 20]

Protocol:
  1. Backward-compat check: no env vars, merged, must match 256,580 ± 1.
  2. Corner test (8 corners × merged): if max-min IPR PnL spread < 5,000, STOP.
  3. Full 5×5×4=100 grid × 4 scenarios = 400 runs.
  4. Top-10 merged sensitivity under --match-trades worse = 10 more runs.
  5. ACO PnL sanity: must stay within ±200 across same-scenario runs.

Outputs:
  Round 1/analysis/sweep_results_ipr_skim.csv
  Round 1/analysis/sweep_log_index_ipr.md
  runs/ipr_sweep/*.log

Usage (from repo root):
  python "Round 1/analysis/sweep_ipr_skim.py"
"""

import subprocess
import re
import os
import csv
import sys
from pathlib import Path
from itertools import product as iterproduct

# ---- Paths ----
REPO_ROOT   = Path("/Users/samuelshi/IMC-Prosperity-2026-personal")
TRADER      = REPO_ROOT / "Round 1" / "traders" / "trader-v8-173159.py"
RUNS_DIR    = REPO_ROOT / "runs" / "ipr_sweep"
CSV_OUT     = REPO_ROOT / "Round 1" / "analysis" / "sweep_results_ipr_skim.csv"
INDEX_OUT   = REPO_ROOT / "Round 1" / "analysis" / "sweep_log_index_ipr.md"

# ---- Sweep dimensions ----
SKIM_SIZES        = [3, 5, 7, 10, 15]        # 5 values; v8 default = 5
SKIM_OFFSETS      = [1, 2, 3, 4, 5]          # 5 values; v8 default = 2
REFILL_MAX_SIZES  = [5, 10, 15, 20]          # 4 values; v8 default = 10

# Corner extremes for gate test
CORNERS = list(iterproduct(
    [SKIM_SIZES[0], SKIM_SIZES[-1]],
    [SKIM_OFFSETS[0], SKIM_OFFSETS[-1]],
    [REFILL_MAX_SIZES[0], REFILL_MAX_SIZES[-1]],
))  # 8 points

# ---- Gate ----
CORNER_GATE_THRESHOLD = 5_000  # min spread (max_ipr - min_ipr) to proceed

# ---- Baseline expected PnL (no env vars) ----
BASELINE_TOTAL_PNL = 256_580
BASELINE_TOLERANCE = 1          # allow ±1 for fill-ordering noise

# ---- ACO sanity: max allowed ACO PnL variation per scenario ----
ACO_SANITY_THRESHOLD = 200

# ---- Scenarios ----
# (label, day_arg, merge_pnl, match_trades_worse)
SCENARIOS = [
    ("merged",  "1",    True,  False),
    ("day_-2",  "1--2", False, False),
    ("day_-1",  "1--1", False, False),
    ("day_0",   "1-0",  False, False),
]
MERGED_WORSE_SCENARIO = ("merged_worse", "1", True, True)

# ---- Columns for CSV ----
CSV_FIELDS = [
    "skim_size", "skim_offset", "refill_max_size",
    "scenario", "ipr_pnl", "aco_pnl", "total_pnl",
    "max_ipr_pos", "log_path",
]


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def param_tag(sz, off, rfl):
    return f"sz{sz}_off{off}_rfl{rfl}"


def log_path_for(sz, off, rfl, scenario):
    return RUNS_DIR / f"{param_tag(sz, off, rfl)}_{scenario}.log"


def run_backtest(sz, off, rfl, scenario_label, day_arg, merge_pnl,
                 match_trades_worse, log_path):
    """
    Run prosperity4btest with env-var overrides for IPR params.
    Returns dict: ok, ipr_pnl, aco_pnl, total_pnl, max_ipr_pos, error.
    """
    env = os.environ.copy()
    env["IPR_SKIM_SIZE"]       = str(sz)
    env["IPR_SKIM_OFFSET"]     = str(off)
    env["IPR_REFILL_MAX_SIZE"] = str(rfl)

    cmd = [
        "prosperity4btest",
        str(TRADER),
        day_arg,
        "--no-progress",
        "--out", str(log_path),
    ]
    if merge_pnl:
        cmd.append("--merge-pnl")
    if match_trades_worse:
        cmd.extend(["--match-trades", "worse"])

    print(f"  Running {param_tag(sz, off, rfl)} / {scenario_label} ...", flush=True)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            cwd=str(REPO_ROOT), env=env,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "")[:500]
            print(f"    FAILED (rc={proc.returncode}): {err}")
            return {"ok": False, "error": err,
                    "ipr_pnl": None, "aco_pnl": None, "total_pnl": None,
                    "max_ipr_pos": None}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout",
                "ipr_pnl": None, "aco_pnl": None, "total_pnl": None,
                "max_ipr_pos": None}
    except FileNotFoundError:
        return {"ok": False, "error": "prosperity4btest not found",
                "ipr_pnl": None, "aco_pnl": None, "total_pnl": None,
                "max_ipr_pos": None}

    stdout = proc.stdout
    ipr_pnl, aco_pnl, total_pnl = parse_pnl(stdout)
    max_ipr_pos = parse_max_ipr_pos(log_path)
    print(f"    total={total_pnl}  aco={aco_pnl}  ipr={ipr_pnl}  max_ipr_pos={max_ipr_pos}")
    return {
        "ok": True, "error": None,
        "ipr_pnl": ipr_pnl,
        "aco_pnl": aco_pnl,
        "total_pnl": total_pnl,
        "max_ipr_pos": max_ipr_pos,
    }


def parse_pnl(stdout):
    """Extract IPR, ACO, and total PnL from prosperity4btest stdout."""
    ipr_pnl  = None
    aco_pnl  = None
    total_pnl = None

    # Patterns: "INTARIAN_PEPPER_ROOT: 238,024" or "Profit: 238024"
    ipr_vals, aco_vals = [], []
    for line in stdout.splitlines():
        ls = line.strip()
        m = re.match(r"INTARIAN_PEPPER_ROOT[:\s]+([-\d,]+)", ls)
        if m:
            ipr_vals.append(int(m.group(1).replace(",", "")))
        m = re.match(r"ASH_COATED_OSMIUM[:\s]+([-\d,]+)", ls)
        if m:
            aco_vals.append(int(m.group(1).replace(",", "")))
        # Total profit line
        m = re.search(r"[Tt]otal\s+[Pp]rofit[:\s]+([-\d,]+)", ls)
        if m:
            total_pnl = int(m.group(1).replace(",", ""))

    # prosperity4btest prints one line per product per day (and merged total);
    # use sum of all product lines (for multi-day merged, they appear as single vals)
    if ipr_vals:
        ipr_pnl = sum(ipr_vals)
    if aco_vals:
        aco_pnl = sum(aco_vals)

    return ipr_pnl, aco_pnl, total_pnl


def parse_max_ipr_pos(log_path):
    """
    Parse the log file to find max absolute position for INTARIAN_PEPPER_ROOT.
    Returns integer or None if log doesn't exist / can't be parsed.
    """
    if not log_path.exists():
        return None
    max_pos = 0
    try:
        with open(log_path, "r", errors="replace") as f:
            for line in f:
                # Look for position columns in the log format
                if "INTARIAN_PEPPER_ROOT" in line:
                    # Match signed integer after product name
                    m = re.search(r"INTARIAN_PEPPER_ROOT.*?(-?\d+)", line)
                    if m:
                        val = abs(int(m.group(1)))
                        if val > max_pos:
                            max_pos = val
    except Exception:
        return None
    return max_pos if max_pos > 0 else None


# ---------------------------------------------------------------------------
# Backward-compat check
# ---------------------------------------------------------------------------

def backward_compat_check():
    """
    Run v8 with NO env vars set on merged. Must match BASELINE_TOTAL_PNL ± BASELINE_TOLERANCE.
    """
    print("\n=== BACKWARD-COMPAT CHECK ===")
    log_path = RUNS_DIR / "baseline_no_envvars_merged.log"

    # Clear env vars to ensure defaults are used
    env = {k: v for k, v in os.environ.items()
           if k not in ("IPR_SKIM_SIZE", "IPR_SKIM_OFFSET", "IPR_REFILL_MAX_SIZE")}
    cmd = [
        "prosperity4btest", str(TRADER), "1",
        "--no-progress", "--merge-pnl", "--out", str(log_path),
    ]
    print(f"  Command: {' '.join(str(c) for c in cmd)}")
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            cwd=str(REPO_ROOT), env=env,
        )
        if proc.returncode != 0:
            print(f"  FAILED: {proc.stderr[:500]}")
            return False, None
    except Exception as e:
        print(f"  EXCEPTION: {e}")
        return False, None

    ipr_pnl, aco_pnl, total_pnl = parse_pnl(proc.stdout)
    print(f"  total={total_pnl}  aco={aco_pnl}  ipr={ipr_pnl}")
    print(f"  Expected total: {BASELINE_TOTAL_PNL} ± {BASELINE_TOLERANCE}")

    if total_pnl is None:
        print("  FAILED: could not parse total PnL from stdout")
        print("  STDOUT:", proc.stdout[:2000])
        return False, None

    delta = abs(total_pnl - BASELINE_TOTAL_PNL)
    if delta <= BASELINE_TOLERANCE:
        print(f"  PASS: delta={delta} <= {BASELINE_TOLERANCE}")
        return True, {"ipr_pnl": ipr_pnl, "aco_pnl": aco_pnl, "total_pnl": total_pnl}
    else:
        print(f"  FAIL: delta={delta} > {BASELINE_TOLERANCE}. "
              "Trader modification has a bug — halting.")
        return False, None


# ---------------------------------------------------------------------------
# Corner test
# ---------------------------------------------------------------------------

def run_corner_test():
    """
    Run 8 corners × merged only.
    Returns (gate_passed, results_dict) where results_dict maps corner tuple → result dict.
    """
    print("\n=== CORNER TEST (8 corners × merged) ===")
    results = {}
    for sz, off, rfl in CORNERS:
        lp = log_path_for(sz, off, rfl, "merged")
        r = run_backtest(sz, off, rfl, "merged", "1", True, False, lp)
        results[(sz, off, rfl)] = r

    # Collect IPR PnLs
    ipr_vals = [r["ipr_pnl"] for r in results.values()
                if r["ok"] and r["ipr_pnl"] is not None]
    if len(ipr_vals) < 8:
        print(f"\n  WARNING: only {len(ipr_vals)}/8 corners succeeded.")

    if not ipr_vals:
        print("  CANNOT EVALUATE — no successful corner runs")
        return False, results

    spread = max(ipr_vals) - min(ipr_vals)
    best_corner = max(results.items(), key=lambda kv: kv[1].get("ipr_pnl") or -1e9)
    worst_corner = min(results.items(), key=lambda kv: kv[1].get("ipr_pnl") or 1e9)

    print(f"\n  Corner IPR PnL range: {min(ipr_vals)} to {max(ipr_vals)}")
    print(f"  Spread: {spread}")
    print(f"  Gate threshold: {CORNER_GATE_THRESHOLD}")
    print(f"  Best corner: sz={best_corner[0][0]}, off={best_corner[0][1]}, "
          f"rfl={best_corner[0][2]}, ipr={best_corner[1]['ipr_pnl']}")
    print(f"  Worst corner: sz={worst_corner[0][0]}, off={worst_corner[0][1]}, "
          f"rfl={worst_corner[0][2]}, ipr={worst_corner[1]['ipr_pnl']}")

    gate_passed = spread >= CORNER_GATE_THRESHOLD
    print(f"  Gate: {'PASSED — proceeding to full 400-run sweep' if gate_passed else 'FAILED — space too flat, stopping'}")
    return gate_passed, results


# ---------------------------------------------------------------------------
# Full sweep
# ---------------------------------------------------------------------------

def run_full_sweep():
    """
    Run all 100 parameter points × 4 scenarios = 400 runs.
    Returns list of row dicts for CSV.
    """
    print("\n=== FULL SWEEP (100 points × 4 scenarios = 400 runs) ===")
    all_rows = []
    total_points = len(SKIM_SIZES) * len(SKIM_OFFSETS) * len(REFILL_MAX_SIZES)
    done = 0

    for sz, off, rfl in iterproduct(SKIM_SIZES, SKIM_OFFSETS, REFILL_MAX_SIZES):
        done += 1
        print(f"\n--- Point {done}/{total_points}: sz={sz}, off={off}, rfl={rfl} ---")
        for scenario_label, day_arg, merge_pnl, worse in SCENARIOS:
            lp = log_path_for(sz, off, rfl, scenario_label)
            r = run_backtest(sz, off, rfl, scenario_label, day_arg,
                             merge_pnl, worse, lp)
            all_rows.append({
                "skim_size": sz,
                "skim_offset": off,
                "refill_max_size": rfl,
                "scenario": scenario_label,
                "ipr_pnl": r.get("ipr_pnl"),
                "aco_pnl": r.get("aco_pnl"),
                "total_pnl": r.get("total_pnl"),
                "max_ipr_pos": r.get("max_ipr_pos"),
                "log_path": str(lp),
            })

    return all_rows


# ---------------------------------------------------------------------------
# Sensitivity: top-10 merged under --match-trades worse
# ---------------------------------------------------------------------------

def run_sensitivity(all_rows):
    """
    Find top 10 by merged IPR PnL, run each under --match-trades worse.
    Returns list of additional row dicts.
    """
    print("\n=== SENSITIVITY: top-10 under --match-trades worse ===")
    merged_rows = [r for r in all_rows if r["scenario"] == "merged"
                   and r["ipr_pnl"] is not None]
    merged_rows.sort(key=lambda r: r["ipr_pnl"], reverse=True)
    top10 = merged_rows[:10]

    extra_rows = []
    for i, row in enumerate(top10):
        sz, off, rfl = row["skim_size"], row["skim_offset"], row["refill_max_size"]
        print(f"\n  Sensitivity {i+1}/10: sz={sz}, off={off}, rfl={rfl}, "
              f"merged_ipr={row['ipr_pnl']}")
        lp = log_path_for(sz, off, rfl, "merged_worse")
        r = run_backtest(sz, off, rfl, "merged_worse", "1", True, True, lp)
        extra_rows.append({
            "skim_size": sz,
            "skim_offset": off,
            "refill_max_size": rfl,
            "scenario": "merged_worse",
            "ipr_pnl": r.get("ipr_pnl"),
            "aco_pnl": r.get("aco_pnl"),
            "total_pnl": r.get("total_pnl"),
            "max_ipr_pos": r.get("max_ipr_pos"),
            "log_path": str(lp),
        })

    return extra_rows


# ---------------------------------------------------------------------------
# ACO sanity check
# ---------------------------------------------------------------------------

def aco_sanity_check(rows):
    """
    For each scenario, check ACO PnL variance across all parameter points.
    Halt (print warning) if any scenario has ACO range > 200.
    Returns True if all ok, False if violation found.
    """
    print("\n=== ACO SANITY CHECK ===")
    ok = True
    by_scenario = {}
    for r in rows:
        s = r["scenario"]
        aco = r.get("aco_pnl")
        if aco is not None:
            by_scenario.setdefault(s, []).append(aco)

    for scenario, vals in sorted(by_scenario.items()):
        lo, hi = min(vals), max(vals)
        spread = hi - lo
        status = "OK" if spread <= ACO_SANITY_THRESHOLD else "VIOLATION"
        print(f"  {scenario}: ACO range [{lo}, {hi}], spread={spread} — {status}")
        if spread > ACO_SANITY_THRESHOLD:
            print(f"  *** ACO PnL varies by {spread} > {ACO_SANITY_THRESHOLD} "
                  "in scenario '{scenario}' — possible cross-product interaction or bug!")
            ok = False

    return ok


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_csv(rows, path):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    print(f"\nWrote CSV: {path}  ({len(rows)} rows)")


def write_log_index(rows, path):
    lines = [
        "# IPR Skim Sweep — Log File Index",
        "",
        "| skim_size | skim_offset | refill_max_size | scenario | ipr_pnl | log_path |",
        "|-----------|-------------|-----------------|----------|---------|----------|",
    ]
    for row in rows:
        ipr = row.get("ipr_pnl", "")
        lines.append(
            f"| {row['skim_size']} | {row['skim_offset']} | {row['refill_max_size']} "
            f"| {row['scenario']} | {ipr} | `{row['log_path']}` |"
        )
    lines.append("")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"Wrote index: {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    # ---- Step 0: Backward-compat check ----
    compat_ok, baseline = backward_compat_check()
    if not compat_ok:
        print("\nHALTING: backward-compat check failed. Fix the trader modification first.")
        sys.exit(1)

    # ---- Step 1: Corner test ----
    gate_passed, corner_results = run_corner_test()

    # Build corner rows for CSV
    corner_rows = []
    for (sz, off, rfl), r in corner_results.items():
        corner_rows.append({
            "skim_size": sz,
            "skim_offset": off,
            "refill_max_size": rfl,
            "scenario": "merged",
            "ipr_pnl": r.get("ipr_pnl"),
            "aco_pnl": r.get("aco_pnl"),
            "total_pnl": r.get("total_pnl"),
            "max_ipr_pos": r.get("max_ipr_pos"),
            "log_path": str(log_path_for(sz, off, rfl, "merged")),
        })

    if not gate_passed:
        # Write corner-only CSV and stop
        write_csv(corner_rows, CSV_OUT)
        write_log_index(corner_rows, INDEX_OUT)
        print("\nCorner test gate FAILED. Sweep stopped at 8 corners. "
              "Parameter space is too flat — recommend keeping v8 defaults.")
        aco_sanity_check(corner_rows)
        return

    # ---- Step 2: Full 400-run grid ----
    grid_rows = run_full_sweep()

    # ---- Step 3: ACO sanity check on grid ----
    aco_ok = aco_sanity_check(grid_rows)
    if not aco_ok:
        print("\nWARNING: ACO sanity check FAILED. Results may reflect a bug.")
        print("Writing partial CSV and halting sensitivity pass.")
        all_rows = corner_rows + grid_rows
        write_csv(all_rows, CSV_OUT)
        write_log_index(all_rows, INDEX_OUT)
        sys.exit(1)

    # ---- Step 4: Sensitivity (top-10, merged_worse) ----
    sensitivity_rows = run_sensitivity(grid_rows)

    # ---- Step 5: Write outputs ----
    all_rows = corner_rows + grid_rows + sensitivity_rows
    write_csv(all_rows, CSV_OUT)
    write_log_index(all_rows, INDEX_OUT)

    # ---- Step 6: Print top-5 summary ----
    merged_rows = [r for r in grid_rows
                   if r["scenario"] == "merged" and r["ipr_pnl"] is not None]
    merged_rows.sort(key=lambda r: r["ipr_pnl"], reverse=True)
    print("\n=== TOP 5 MERGED CANDIDATES (by IPR PnL) ===")
    for i, r in enumerate(merged_rows[:5]):
        print(f"  #{i+1}: sz={r['skim_size']}, off={r['skim_offset']}, "
              f"rfl={r['refill_max_size']}  ipr={r['ipr_pnl']}  total={r['total_pnl']}")

    print(f"\nTotal runs: {len(all_rows)} CSV rows "
          f"(1 baseline + 8 corners + {len(grid_rows)} grid + {len(sensitivity_rows)} sensitivity)")
    print("Done.")


if __name__ == "__main__":
    main()
