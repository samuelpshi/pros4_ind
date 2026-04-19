"""
A3_refine — local grid refinement + robustness checks for ACO Pass 2.6
All evaluation uses full prosperity4btest GT (no tagging replay).
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
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
REPO   = Path("/Users/samuelshi/IMC-Prosperity-2026-personal")
TRADERS = REPO / "Round 1" / "traders"
SCRATCH = REPO / "Round 1" / "analysis" / "scratch"
CAND_DIR = SCRATCH / "a3_candidates"
PLOTS   = REPO / "Round 1" / "analysis" / "plots" / "aco_pass2_6"
BASE_TRADER = TRADERS / "trader-v9-aco-qo5-ms8-te3.py"

CAND_DIR.mkdir(parents=True, exist_ok=True)
PLOTS.mkdir(parents=True, exist_ok=True)

# ── Search space ───────────────────────────────────────────────────────────────
SPACE = {
    "qo":    (2,    8,    int),   # quote_offset
    "ms":    (4,    12,   int),   # max_skew
    "te":    (1.5,  5.0,  float), # take_edge
    "alpha": (0.05, 0.25, float), # ema_alpha
}
STEPS = {"qo": 1, "ms": 1, "te": 0.35, "alpha": 0.02}

# A2 top-3
A2_TOP3 = [
    {"qo": 7, "ms": 5, "te": 2.6849, "alpha": 0.1468},
    {"qo": 7, "ms": 5, "te": 4.2578, "alpha": 0.1692},
    {"qo": 7, "ms": 4, "te": 4.2985, "alpha": 0.0921},
]

# ── Grid generation ────────────────────────────────────────────────────────────
def clamp(v, lo, hi, typ):
    v = max(lo, min(hi, v))
    if typ == int:
        v = round(v)
    return typ(v)

def round_to_step(v, step, lo, typ):
    """Round to nearest step grid."""
    n_steps = round((v - lo) / step)
    result = lo + n_steps * step
    return typ(result)

def generate_local_grid(center, max_l1=3):
    """All combos within L1 <= max_l1 steps of center."""
    dims = ["qo", "ms", "te", "alpha"]
    offsets_per_dim = {}
    for d in dims:
        lo, hi, typ = SPACE[d]
        step = STEPS[d]
        # range of offsets (in step units) that keep value in bounds
        max_neg = round((center[d] - lo) / step)
        max_pos = round((hi - center[d]) / step)
        offsets_per_dim[d] = list(range(-min(max_l1, max_neg), min(max_l1, max_pos)+1))

    combos = []
    for oq, om, ot, oa in itertools.product(
        offsets_per_dim["qo"], offsets_per_dim["ms"],
        offsets_per_dim["te"], offsets_per_dim["alpha"]
    ):
        l1 = abs(oq) + abs(om) + abs(ot) + abs(oa)
        if l1 > max_l1:
            continue
        c = {
            "qo":    clamp(center["qo"]    + oq * STEPS["qo"],    *SPACE["qo"][:2],    int),
            "ms":    clamp(center["ms"]    + om * STEPS["ms"],    *SPACE["ms"][:2],    int),
            "te":    clamp(round(center["te"]    + ot * STEPS["te"],    4), *SPACE["te"][:2],    float),
            "alpha": clamp(round(center["alpha"] + oa * STEPS["alpha"], 4), *SPACE["alpha"][:2], float),
        }
        combos.append(c)
    return combos

def dedup_combos(all_combos):
    seen = set()
    out = []
    for c in all_combos:
        key = (c["qo"], c["ms"], round(c["te"], 4), round(c["alpha"], 4))
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out

# ── Trader file creation ───────────────────────────────────────────────────────
BASE_TEXT = BASE_TRADER.read_text()

def make_trader(params, uid):
    """Create a temp trader file with modified ACO_CFG.
    uid must be an integer or safe string (no dots) since Python uses filename as module name.
    """
    txt = BASE_TEXT
    # Replace ACO_CFG block
    new_cfg = (
        f'ACO_CFG = {{\n'
        f'    "ema_alpha":       {params["alpha"]},\n'
        f'    "quote_offset":    {params["qo"]},\n'
        f'    "take_edge":       {params["te"]},\n'
        f'    "max_skew":        {params["ms"]},\n'
        f'    "panic_threshold": 0.75,\n'
        f'}}'
    )
    txt = re.sub(r'ACO_CFG\s*=\s*\{[^}]+\}', new_cfg, txt, flags=re.DOTALL)
    # Use integer uid to avoid dots in filename (Python treats dots as module separators)
    path = CAND_DIR / f"a3_c{uid:04d}.py"
    path.write_text(txt)
    return path

# ── GT evaluation ──────────────────────────────────────────────────────────────
def extract_pnl_from_log(log_path):
    """Return {(day, product): final_pnl}."""
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
    col_pnl     = header.index("profit_and_loss")
    col_day     = header.index("day")
    col_product = header.index("product")
    col_ts      = header.index("timestamp")
    last_pnl = {}
    for ln in lines[start+1:end if end else len(lines)]:
        if not ln.strip(): continue
        parts = ln.split(";")
        if len(parts) <= col_pnl: continue
        try:
            day  = int(parts[col_day])
            ts   = int(parts[col_ts])
            prod = parts[col_product]
            pnl  = float(parts[col_pnl]) if parts[col_pnl] else 0.0
        except ValueError:
            continue
        key = (day, prod)
        if key not in last_pnl or ts > last_pnl[key][0]:
            last_pnl[key] = (ts, pnl)
    return {k: v[1] for k, v in last_pnl.items()}

def extract_half2_pnl(log_path, ts_split=500_000):
    """PnL earned in second half (ts > 500k) per (day, product)."""
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
    col_pnl     = header.index("profit_and_loss")
    col_day     = header.index("day")
    col_product = header.index("product")
    col_ts      = header.index("timestamp")
    rows = {}
    for ln in lines[start+1:end if end else len(lines)]:
        if not ln.strip(): continue
        parts = ln.split(";")
        if len(parts) <= col_pnl: continue
        try:
            day  = int(parts[col_day])
            ts   = int(parts[col_ts])
            prod = parts[col_product]
            pnl  = float(parts[col_pnl]) if parts[col_pnl] else 0.0
        except ValueError:
            continue
        rows.setdefault((day, prod), []).append((ts, pnl))
    half2 = {}
    for key, series in rows.items():
        series.sort()
        split_pnl = 0.0
        for ts, pnl in series:
            if ts >= ts_split:
                split_pnl = pnl
                break
        final_pnl = series[-1][1]
        half2[key] = final_pnl - split_pnl
    return half2

def run_gt(params, uid):
    """Run GT for one param set. Returns dict with per-day and half2 ACO PnL."""
    path = make_trader(params, uid)
    log_path = CAND_DIR / f"a3_c{uid:04d}.log"
    cmd = ["prosperity4btest", str(path), "1", "--out", str(log_path), "--no-progress"]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO))
    elapsed = time.time() - t0
    if r.returncode != 0:
        print(f"  ERROR uid={uid}: {r.stderr[:200]}")
        return None

    full  = extract_pnl_from_log(log_path)
    half2 = extract_half2_pnl(log_path)

    aco_full  = {d: full.get((d, "ASH_COATED_OSMIUM"), 0)  for d in [-2, -1, 0]}
    aco_half2 = {d: half2.get((d, "ASH_COATED_OSMIUM"), 0) for d in [-2, -1, 0]}

    worst3       = min(aco_full[d] for d in [-2, -1, 0])
    worst_of_6   = min(list(aco_full.values()) + list(aco_half2.values()))
    sum3         = sum(aco_full[d] for d in [-2, -1, 0])

    return {
        "params": params,
        "aco_full_d-2": aco_full[-2],
        "aco_full_d-1": aco_full[-1],
        "aco_full_d0":  aco_full[0],
        "aco_half2_d-2": aco_half2[-2],
        "aco_half2_d-1": aco_half2[-1],
        "aco_half2_d0":  aco_half2[0],
        "worst3":   worst3,
        "worst_of_6": worst_of_6,
        "sum3":     sum3,
        "elapsed_s": round(elapsed, 1),
    }


# ── STEP 1: Generate local grid ────────────────────────────────────────────────
print("=== Step 1: Generating local grid ===")
all_combos = []
for ctr in A2_TOP3:
    all_combos.extend(generate_local_grid(ctr, max_l1=3))

grid = dedup_combos(all_combos)
print(f"Total unique combos (L1<=3): {len(grid)}")

grid_path = SCRATCH / "a3_local_grid.json"
grid_path.write_text(json.dumps(grid, indent=2))
print(f"Saved grid to {grid_path}")

# ── STEP 2: GT evaluation ──────────────────────────────────────────────────────
print(f"\n=== Step 2: GT evaluation ({len(grid)} combos) ===")
t_start = time.time()

results_path = SCRATCH / "a3_local_grid_gt.json"
# Resume from partial results if they exist
if results_path.exists():
    existing = json.loads(results_path.read_text())
    print(f"  Resuming from {len(existing)} existing results")
else:
    existing = []

def params_key(p):
    return (p["qo"], p["ms"], round(p["te"], 4), round(p["alpha"], 4))

done_keys = {params_key(r["params"]) for r in existing}
remaining = [c for c in grid if params_key(c) not in done_keys]
print(f"  Remaining: {len(remaining)} combos")

results = list(existing)
for i, params in enumerate(remaining):
    uid = len(existing) + i  # integer uid — no dots in filename
    elapsed_so_far = time.time() - t_start
    eta = (elapsed_so_far / (i + 0.001)) * (len(remaining) - i) if i > 0 else 0
    print(f"  [{i+1}/{len(remaining)}] qo={params['qo']} ms={params['ms']} "
          f"te={params['te']} alpha={params['alpha']}  "
          f"(wall={elapsed_so_far:.0f}s, ETA={eta:.0f}s)")
    r = run_gt(params, uid)
    if r:
        results.append(r)
        # Save incrementally
        results_path.write_text(json.dumps(results, indent=2))

    # Wall-time safeguard: if > 25 min, drop to L1<=2
    if time.time() - t_start > 1500 and len(remaining) > 50:
        print(f"  Wall-time exceeded 25 min with {len(remaining)-i-1} remaining. Stopping early.")
        print("  Grid adequately sampled for L1<=2 neighborhood.")
        break

total_wall = time.time() - t_start
print(f"\nTotal GT wall time: {total_wall:.1f}s ({total_wall/60:.1f} min)")
print(f"Total evaluated: {len(results)}")

# ── Sort and top 10 ────────────────────────────────────────────────────────────
results.sort(key=lambda r: -r["worst_of_6"])
print("\n=== Top 10 by worst_of_6 ===")
print(f"{'#':<4} {'qo':>4} {'ms':>4} {'te':>7} {'alpha':>7} | "
      f"{'d-2':>8} {'d-1':>8} {'d0':>8} | "
      f"{'worst3':>8} {'worst6':>8} {'sum3':>8}")
print("-" * 90)
for i, r in enumerate(results[:10]):
    p = r["params"]
    print(f"{i+1:<4} {p['qo']:>4} {p['ms']:>4} {p['te']:>7.4f} {p['alpha']:>7.4f} | "
          f"{r['aco_full_d-2']:>8.1f} {r['aco_full_d-1']:>8.1f} {r['aco_full_d0']:>8.1f} | "
          f"{r['worst3']:>8.1f} {r['worst_of_6']:>8.1f} {r['sum3']:>8.1f}")

print(f"\nSaved {len(results)} results to {results_path}")
print("\nResults ready. Run a3_analysis.py for Steps 3-6.")
