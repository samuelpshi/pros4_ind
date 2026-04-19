"""
A3_refine analysis: Steps 3-6 (adjacency, sensitivity, walk-forward, decision).
All evaluation uses full prosperity4btest GT.
"""
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ── Paths ──────────────────────────────────────────────────────────────────────
REPO    = Path("/Users/samuelshi/IMC-Prosperity-2026-personal")
TRADERS = REPO / "Round 1" / "traders"
SCRATCH = REPO / "Round 1" / "analysis" / "scratch"
CAND_DIR = SCRATCH / "a3_candidates"
PLOTS   = REPO / "Round 1" / "analysis" / "plots" / "aco_pass2_6"
BASE_TRADER = TRADERS / "trader-v9-aco-qo5-ms8-te3.py"

CAND_DIR.mkdir(parents=True, exist_ok=True)
PLOTS.mkdir(parents=True, exist_ok=True)

# ── v9-qo5 baseline (from A0) ──────────────────────────────────────────────────
V9_QO5_GT = {-2: 9201.0, -1: 10793.0, 0: 9013.0}

# ── Load grid results ──────────────────────────────────────────────────────────
results = json.loads((SCRATCH / "a3_local_grid_gt.json").read_text())
BASE_TEXT = BASE_TRADER.read_text()

# ── Fix half2 extraction ──────────────────────────────────────────────────────
# Timestamps in the log are global-continuous: day -2 = [0, 999900],
# day -1 = [1000000, 1999900], day 0 = [2000000, 2999900].
# Half-2 = ts >= day_start + 500000 per day.
DAY_STARTS = {-2: 0, -1: 1_000_000, 0: 2_000_000}

def extract_pnl_from_log(log_path):
    """Return {(day, product): final_pnl} and {(day, product): half2_pnl}."""
    with open(log_path) as f:
        lines = f.read().splitlines()
    start = end = None
    for i, ln in enumerate(lines):
        if ln.startswith("Activities log:"):
            start = i + 1
        elif start is not None and ln.startswith("Trade History:"):
            end = i
            break
    if start is None:
        raise RuntimeError(f"No Activities section in {log_path}")
    header = lines[start].split(";")
    ci_pnl  = header.index("profit_and_loss")
    ci_day  = header.index("day")
    ci_prod = header.index("product")
    ci_ts   = header.index("timestamp")

    rows = defaultdict(list)
    for ln in lines[start+1:end if end else len(lines)]:
        if not ln.strip(): continue
        parts = ln.split(";")
        if len(parts) <= ci_pnl: continue
        try:
            day  = int(parts[ci_day])
            ts   = int(parts[ci_ts])
            prod = parts[ci_prod]
            pnl  = float(parts[ci_pnl]) if parts[ci_pnl] else 0.0
        except ValueError:
            continue
        rows[(day, prod)].append((ts, pnl))

    full_pnl  = {}
    half2_pnl = {}
    for (day, prod), series in rows.items():
        series.sort()
        final_pnl = series[-1][1]
        full_pnl[(day, prod)] = final_pnl

        # Find PnL at day_start + 500_000 (using global ts)
        split_ts = DAY_STARTS.get(day, 0) + 500_000
        split_pnl = 0.0
        for ts, pnl in series:
            if ts <= split_ts:
                split_pnl = pnl
        half2_pnl[(day, prod)] = final_pnl - split_pnl

    return full_pnl, half2_pnl

def run_gt_full(params, uid_str):
    """Run GT, extract correct full + half2 PnL per day."""
    # Write trader
    new_cfg = (
        f'ACO_CFG = {{\n'
        f'    "ema_alpha":       {params["alpha"]},\n'
        f'    "quote_offset":    {params["qo"]},\n'
        f'    "take_edge":       {params["te"]},\n'
        f'    "max_skew":        {params["ms"]},\n'
        f'    "panic_threshold": 0.75,\n'
        f'}}'
    )
    txt = re.sub(r'ACO_CFG\s*=\s*\{[^}]+\}', new_cfg, BASE_TEXT, flags=re.DOTALL)
    path = CAND_DIR / f"a3_{uid_str}.py"
    path.write_text(txt)
    log_path = CAND_DIR / f"a3_{uid_str}.log"
    cmd = ["prosperity4btest", str(path), "1", "--out", str(log_path), "--no-progress"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO))
    if r.returncode != 0:
        raise RuntimeError(f"prosperity4btest failed: {r.stderr[:200]}")
    full, half2 = extract_pnl_from_log(log_path)
    aco_full  = {d: full.get((d, "ASH_COATED_OSMIUM"), 0)  for d in [-2, -1, 0]}
    aco_half2 = {d: half2.get((d, "ASH_COATED_OSMIUM"), 0) for d in [-2, -1, 0]}
    worst3      = min(aco_full.values())
    worst_of_6  = min(list(aco_full.values()) + list(aco_half2.values()))
    sum3        = sum(aco_full.values())
    return {
        "params": params,
        "aco_full": aco_full,
        "aco_half2": aco_half2,
        "worst3": worst3,
        "worst_of_6": worst_of_6,
        "sum3": sum3,
    }

# ── Re-extract half2 correctly for all grid results ────────────────────────────
print("Re-extracting half2 with correct day-relative timestamps...")
corrected = []
uid = 0
for r in results:
    p = r["params"]
    uid_str = f"c{uid:04d}"
    log_path = CAND_DIR / f"a3_{uid_str}.log"
    if log_path.exists():
        try:
            full, half2 = extract_pnl_from_log(log_path)
            aco_full  = {d: full.get((d, "ASH_COATED_OSMIUM"), 0)  for d in [-2, -1, 0]}
            aco_half2 = {d: half2.get((d, "ASH_COATED_OSMIUM"), 0) for d in [-2, -1, 0]}
            worst3     = min(aco_full.values())
            worst_of_6 = min(list(aco_full.values()) + list(aco_half2.values()))
            sum3       = sum(aco_full.values())
            corrected.append({
                "params": p,
                "aco_full_d-2": aco_full[-2],
                "aco_full_d-1": aco_full[-1],
                "aco_full_d0":  aco_full[0],
                "aco_half2_d-2": aco_half2[-2],
                "aco_half2_d-1": aco_half2[-1],
                "aco_half2_d0":  aco_half2[0],
                "worst3": worst3,
                "worst_of_6": worst_of_6,
                "sum3": sum3,
            })
        except Exception as e:
            print(f"  Error for uid={uid_str}: {e}")
    uid += 1

print(f"  Corrected {len(corrected)}/{len(results)} entries")

# Save corrected results
corrected_path = SCRATCH / "a3_local_grid_gt_corrected.json"
corrected_path.write_text(json.dumps(corrected, indent=2))
print(f"  Saved to {corrected_path}")

# Sort by worst_of_6
corrected.sort(key=lambda r: -r["worst_of_6"])

print("\n=== Top 10 by worst_of_6 (corrected half2) ===")
print(f"{'#':<4} {'qo':>4} {'ms':>4} {'te':>7} {'alpha':>7} | "
      f"{'d-2':>8} {'d-1':>8} {'d0':>8} | "
      f"{'h2d-2':>7} {'h2d-1':>7} {'h2d0':>7} | "
      f"{'worst3':>8} {'worst6':>8} {'sum3':>8}")
print("-" * 110)
for i, r in enumerate(corrected[:10]):
    p = r["params"]
    print(f"{i+1:<4} {p['qo']:>4} {p['ms']:>4} {p['te']:>7.4f} {p['alpha']:>7.4f} | "
          f"{r['aco_full_d-2']:>8.1f} {r['aco_full_d-1']:>8.1f} {r['aco_full_d0']:>8.1f} | "
          f"{r['aco_half2_d-2']:>7.1f} {r['aco_half2_d-1']:>7.1f} {r['aco_half2_d0']:>7.1f} | "
          f"{r['worst3']:>8.1f} {r['worst_of_6']:>8.1f} {r['sum3']:>8.1f}")

# ── STEP 3: Adjacency check ────────────────────────────────────────────────────
STEPS = {"qo": 1, "ms": 1, "te": 0.35, "alpha": 0.02}
SPACE = {"qo": (2, 8), "ms": (4, 12), "te": (1.5, 5.0), "alpha": (0.05, 0.25)}

def params_key(p):
    return (p["qo"], p["ms"], round(p["te"], 4), round(p["alpha"], 4))

def l1_distance(p1, p2):
    return (abs(p1["qo"] - p2["qo"]) / STEPS["qo"] +
            abs(p1["ms"] - p2["ms"]) / STEPS["ms"] +
            abs(round(p1["te"] - p2["te"], 4)) / STEPS["te"] +
            abs(round(p1["alpha"] - p2["alpha"], 4)) / STEPS["alpha"])

# Build lookup by key
key_to_result = {params_key(r["params"]): r for r in corrected}

def adjacency_check(winner_result, all_results, label=""):
    """Find L1=1 neighbors, compute ratio."""
    winner_pnl = winner_result["worst_of_6"]
    wp = winner_result["params"]

    # Find neighbors with L1 distance ~1 step in any single dim
    neighbors = []
    for r in all_results:
        if params_key(r["params"]) == params_key(wp):
            continue
        dist = l1_distance(r["params"], wp)
        if abs(dist - 1.0) < 0.15:  # L1 == 1 (one step in one dim)
            neighbors.append(r)

    if not neighbors:
        print(f"  {label}: No L1=1 neighbors found in grid!")
        return None, False

    nbr_pnls = [n["worst_of_6"] for n in neighbors]
    ratio = min(nbr_pnls) / winner_pnl if winner_pnl > 0 else 0
    passed = ratio >= 0.80

    print(f"\n=== Adjacency Check: {label} ===")
    print(f"  Winner worst_of_6: {winner_pnl:.1f}")
    print(f"  Neighbor count (L1=1): {len(neighbors)}")
    print(f"  Neighbor worst_of_6: mean={np.mean(nbr_pnls):.1f}  min={min(nbr_pnls):.1f}  max={max(nbr_pnls):.1f}")
    print(f"  Ratio (min_nbr / winner): {ratio:.4f}  →  {'PASS' if passed else 'FAIL'} (gate ≥ 0.80)")
    return ratio, passed

# ── STEP 4: Sensitivity analysis ──────────────────────────────────────────────
def sensitivity_analysis(winner_params, winner_pnl, label=""):
    """16 runs: 4 params × 4 perturbations."""
    RANGES = {"qo": 6.0, "ms": 8.0, "te": 3.5, "alpha": 0.20}
    perturbations = [("±10%", [+0.10, -0.10]), ("±25%", [+0.25, -0.25])]

    print(f"\n=== Sensitivity Analysis: {label} ===")
    print(f"{'Param':<8} {'Perturbation':>14} {'New Value':>10} | {'worst6':>8} {'delta_abs':>10} {'delta_pct':>10} | {'Status':>8}")
    print("-" * 80)

    any_fail = False
    all_rows = []
    run_id = 0
    for param in ["qo", "ms", "te", "alpha"]:
        for pct_label, pcts in perturbations:
            for pct in pcts:
                perturb = pct * RANGES[param]
                new_val = winner_params[param] + perturb
                # Clamp
                lo, hi = SPACE[param]
                new_val = max(lo, min(hi, new_val))
                if param in ["qo", "ms"]:
                    new_val = round(new_val)

                new_params = dict(winner_params)
                new_params[param] = round(new_val, 4) if param not in ["qo", "ms"] else int(new_val)

                uid_str = f"sens_{label}_{param}_{run_id:02d}"

                # Check if this combo is already in grid
                key = params_key(new_params)
                if key in key_to_result:
                    r = key_to_result[key]
                    pnl = r["worst_of_6"]
                else:
                    # Run GT
                    print(f"  Running GT for {param}={new_params[param]} (new combo)...")
                    try:
                        res = run_gt_full(new_params, uid_str)
                        pnl = res["worst_of_6"]
                        # Add to lookup
                        key_to_result[key] = {
                            "params": new_params,
                            "aco_full_d-2": res["aco_full"][-2],
                            "aco_full_d-1": res["aco_full"][-1],
                            "aco_full_d0":  res["aco_full"][0],
                            "aco_half2_d-2": res["aco_half2"][-2],
                            "aco_half2_d-1": res["aco_half2"][-1],
                            "aco_half2_d0":  res["aco_half2"][0],
                            "worst3": res["worst3"],
                            "worst_of_6": pnl,
                            "sum3": res["sum3"],
                        }
                    except Exception as e:
                        print(f"  ERROR: {e}")
                        pnl = 0.0

                delta_abs = pnl - winner_pnl
                delta_pct = delta_abs / winner_pnl * 100 if winner_pnl > 0 else 0

                # Gate: ±10% perturbation dropping > 15% fails
                is_10pct = abs(pct) == 0.10
                fail_gate = is_10pct and delta_pct < -15.0
                if fail_gate:
                    any_fail = True
                status = "FAIL" if fail_gate else "ok"

                row = {
                    "param": param,
                    "pct": pct,
                    "pct_label": f"{pct*100:+.0f}%",
                    "new_val": new_val,
                    "worst6": pnl,
                    "delta_abs": delta_abs,
                    "delta_pct": delta_pct,
                    "status": status,
                }
                all_rows.append(row)
                print(f"  {param:<8} {f'{pct*100:+.0f}%':>14} {new_val:>10.4f} | {pnl:>8.1f} {delta_abs:>10.1f} {delta_pct:>9.1f}% | {status:>8}")
                run_id += 1

    passed = not any_fail
    print(f"\n  Sensitivity gate: {'PASS' if passed else 'FAIL'} (any ±10% drop > 15% fails)")
    return all_rows, passed

# ── STEP 5: Walk-forward ──────────────────────────────────────────────────────
def walk_forward(all_results):
    """3 splits: pick best params on train, evaluate on test vs v9-qo5."""
    splits = [
        {"train": [-2, -1], "test": 0},
        {"train": [-2],      "test": -1},
        {"train": [-1, 0],   "test": -2},
    ]

    print("\n=== Walk-Forward Analysis ===")
    print(f"{'Split':>20} | {'Train Days':>12} | {'Test Day':>9} | {'Chosen Params':>35} | "
          f"{'Test GT':>9} | {'qo5 GT':>9} | {'Delta':>9} | {'Win?':>5}")
    print("-" * 130)

    wins = 0
    rows = []
    for sp in splits:
        train_days = sp["train"]
        test_day   = sp["test"]

        # Pick params maximizing mean train-day PnL (full-day ACO)
        best_r = None
        best_train_mean = -float("inf")
        for r in all_results:
            train_mean = np.mean([
                r[f"aco_full_d{d}" if d != 0 else "aco_full_d0"] if d == 0 else
                r.get(f"aco_full_d{d}", r.get(f"aco_full_d-2" if d == -2 else "aco_full_d-1"))
                for d in train_days
            ])
            if train_mean > best_train_mean:
                best_train_mean = train_mean
                best_r = r

        # Helper to get full-day ACO PnL
        def get_full(r, d):
            if d == -2: return r["aco_full_d-2"]
            if d == -1: return r["aco_full_d-1"]
            return r["aco_full_d0"]

        chosen_test_pnl = get_full(best_r, test_day)
        qo5_test_pnl    = V9_QO5_GT[test_day]
        delta           = chosen_test_pnl - qo5_test_pnl
        win             = chosen_test_pnl > qo5_test_pnl
        if win:
            wins += 1

        p = best_r["params"]
        param_str = f"qo={p['qo']} ms={p['ms']} te={p['te']:.4f} a={p['alpha']:.4f}"
        train_str = str(train_days)
        row = {
            "split": f"train{train_days} test{test_day}",
            "train_days": train_days,
            "test_day": test_day,
            "chosen_params": p,
            "test_gt": chosen_test_pnl,
            "qo5_gt": qo5_test_pnl,
            "delta": delta,
            "win": win,
        }
        rows.append(row)
        print(f"  {'train'+str(train_days)+' test'+str(test_day):>20} | {str(train_days):>12} | {test_day:>9} | "
              f"{param_str:>35} | {chosen_test_pnl:>9.1f} | {qo5_test_pnl:>9.1f} | {delta:>+9.1f} | {'YES' if win else 'NO':>5}")

    passed = wins >= 2
    print(f"\n  Walk-forward wins: {wins}/3  →  {'PASS' if passed else 'FAIL'} (gate ≥ 2/3)")
    return rows, passed, wins

# ── STEP 6: Heatmaps ──────────────────────────────────────────────────────────
def make_heatmaps(winner_params, all_results, label):
    """2D slices through the winner."""
    dims_pairs = [("qo", "ms"), ("te", "alpha"), ("qo", "te")]
    for dx, dy in dims_pairs:
        # Collect data where other two dims match winner
        other_dims = [d for d in ["qo", "ms", "te", "alpha"] if d not in [dx, dy]]
        data = {}
        for r in all_results:
            p = r["params"]
            # Check other dims match winner
            ok = all(
                abs(p[d] - winner_params[d]) < STEPS[d] * 0.5
                for d in other_dims
            )
            if ok:
                data[(p[dx], p[dy])] = r["worst3"]  # use worst3 for heatmap (full days)

        if not data:
            continue

        xs = sorted(set(k[0] for k in data))
        ys = sorted(set(k[1] for k in data))
        grid = np.full((len(ys), len(xs)), np.nan)
        for (x, y), v in data.items():
            if x in xs and y in ys:
                grid[ys.index(y), xs.index(x)] = v

        fig, ax = plt.subplots(figsize=(8, 6))
        im = ax.imshow(grid, origin="lower", aspect="auto",
                       extent=[xs[0] - 0.5, xs[-1] + 0.5,
                                ys[0] - 0.5 * STEPS[dy], ys[-1] + 0.5 * STEPS[dy]])
        plt.colorbar(im, ax=ax, label="ACO worst3 PnL")
        ax.set_xlabel(dx)
        ax.set_ylabel(dy)
        ax.set_title(f"ACO worst3 heatmap ({dx} vs {dy})\n"
                     f"Fixed: {', '.join(f'{d}={winner_params[d]}' for d in other_dims)}\n"
                     f"Winner: {dx}={winner_params[dx]}, {dy}={winner_params[dy]}")
        # Mark winner
        ax.plot(winner_params[dx], winner_params[dy], "r*", markersize=15, label="winner")
        ax.legend()
        out_path = PLOTS / f"a3_heatmap_{dx}_{dy}.png"
        plt.tight_layout()
        plt.savefig(out_path, dpi=150)
        plt.close()
        print(f"  Saved heatmap: {out_path}")

# ── Main flow ─────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("=== Step 3: Adjacency Check ===")
print("="*60)

# Try candidates in order of worst_of_6
gate_adjacency = False
gate_sensitivity = False
gate_walk_forward = False
ship_candidate = None

CANDIDATE_PRIORITY = corrected  # already sorted by worst_of_6

tested_adjacency = []
for rank, candidate_r in enumerate(CANDIDATE_PRIORITY[:5]):  # Try top 5
    label = f"rank{rank+1}"
    wp = candidate_r["params"]
    ratio, adj_passed = adjacency_check(candidate_r, corrected, label=label)

    tested_adjacency.append({
        "rank": rank + 1,
        "params": wp,
        "worst_of_6": candidate_r["worst_of_6"],
        "worst3": candidate_r["worst3"],
        "adj_ratio": ratio,
        "adj_passed": adj_passed,
    })

    if not adj_passed:
        print(f"  → Candidate rank{rank+1} FAILS adjacency. Moving to next.")
        continue

    # Adjacency passed — run sensitivity
    print(f"\n=== Step 4: Sensitivity Analysis for rank{rank+1} ===")
    sens_rows, sens_passed = sensitivity_analysis(wp, candidate_r["worst_of_6"], label=label)

    if not sens_passed:
        print(f"  → Candidate rank{rank+1} FAILS sensitivity. Moving to next.")
        continue

    # Adjacency + Sensitivity passed — check walk-forward
    print(f"\n=== Step 5: Walk-Forward for confirmed candidate rank{rank+1} ===")
    wf_rows, wf_passed, wf_wins = walk_forward(corrected)

    if not wf_passed:
        print(f"  → Walk-forward FAILS ({wf_wins}/3). No ship candidate.")
        gate_adjacency = adj_passed
        gate_sensitivity = sens_passed
        gate_walk_forward = False
        # Walk-forward is fatal regardless
        break

    # All gates passed!
    gate_adjacency = True
    gate_sensitivity = True
    gate_walk_forward = True
    ship_candidate = candidate_r
    print(f"\n  → All gates PASSED. Ship candidate: rank{rank+1}")
    make_heatmaps(wp, corrected, label=label)
    break
else:
    # No candidate passed adjacency/sensitivity (or walk-forward stopped us)
    if not gate_adjacency:
        print("\n  No candidate passed adjacency check in top 5.")

# If no ship candidate yet but adjacency failed for all, still run walk-forward
# (to fully report), and run sensitivity on first candidate for reporting
if ship_candidate is None and not gate_walk_forward:
    # Run walk-forward anyway for reporting
    print("\n=== Step 5: Walk-Forward (reporting only — gates already failed) ===")
    wf_rows, wf_passed, wf_wins = walk_forward(corrected)
    gate_walk_forward = wf_passed

# ── STEP 6: Final decision ────────────────────────────────────────────────────
print("\n" + "="*60)
print("=== Step 6: Final Decision ===")
print("="*60)

all_gates = gate_adjacency and gate_sensitivity and gate_walk_forward

if ship_candidate and all_gates:
    decision = "ship_new"
    p = ship_candidate["params"]
    reason = (
        f"qo={p['qo']} ms={p['ms']} te={p['te']} alpha={p['alpha']} "
        f"passed adjacency (ratio={tested_adjacency[0]['adj_ratio']:.3f}), "
        f"sensitivity, and walk-forward ({wf_wins}/3)"
    )
    gt_per_day = [ship_candidate["aco_full_d-2"],
                  ship_candidate["aco_full_d-1"],
                  ship_candidate["aco_full_d0"]]
    gt_merged  = sum(gt_per_day)
    print(f"  Decision: SHIP NEW — {reason}")
    print(f"  GT per day: {gt_per_day}")
    print(f"  GT merged:  {gt_merged}")
else:
    decision = "ship_qo5_unchanged"
    failed_gates = []
    if not gate_adjacency:   failed_gates.append("adjacency")
    if not gate_sensitivity: failed_gates.append("sensitivity")
    if not gate_walk_forward: failed_gates.append("walk_forward")
    reason = f"Failed gates: {', '.join(failed_gates)}"
    print(f"  Decision: SHIP v9-qo5 UNCHANGED — {reason}")

result_json = {
    "decision": decision,
    "reason": reason,
    "gates": {
        "adjacency": gate_adjacency,
        "sensitivity": gate_sensitivity,
        "walk_forward": gate_walk_forward,
    },
}
if decision == "ship_new":
    result_json["params"] = ship_candidate["params"]
    result_json["gt_per_day"] = gt_per_day
    result_json["gt_merged"] = gt_merged

out_path = SCRATCH / "a3_ship_decision.json"
out_path.write_text(json.dumps(result_json, indent=2))
print(f"\nSaved decision to {out_path}")

# ── Summary report ────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("=== Summary ===")
print("="*60)

print(f"\nLocal grid: 312 unique combos, 9.9 min GT evaluation")
print(f"\nTop 10 by worst_of_6 (corrected):")
print(f"{'#':<4} {'qo':>4} {'ms':>4} {'te':>7} {'alpha':>7} | "
      f"{'d-2':>8} {'d-1':>8} {'d0':>8} | "
      f"{'h2d-2':>7} {'h2d-1':>7} {'h2d0':>7} | "
      f"{'worst3':>8} {'worst6':>8} {'sum3':>8}")
print("-" * 110)
for i, r in enumerate(corrected[:10]):
    p = r["params"]
    print(f"{i+1:<4} {p['qo']:>4} {p['ms']:>4} {p['te']:>7.4f} {p['alpha']:>7.4f} | "
          f"{r['aco_full_d-2']:>8.1f} {r['aco_full_d-1']:>8.1f} {r['aco_full_d0']:>8.1f} | "
          f"{r['aco_half2_d-2']:>7.1f} {r['aco_half2_d-1']:>7.1f} {r['aco_half2_d0']:>7.1f} | "
          f"{r['worst3']:>8.1f} {r['worst_of_6']:>8.1f} {r['sum3']:>8.1f}")
