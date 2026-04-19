"""Extract final PnL per product from prosperity4btest log files."""
import sys
import os
import json
from pathlib import Path

def extract_pnl(log_path):
    """Parse Activities log section, return {(day, product): final_pnl}."""
    with open(log_path) as f:
        lines = f.read().splitlines()
    # find Activities section
    start = None
    end = None
    for i, ln in enumerate(lines):
        if ln.startswith("Activities log:"):
            start = i + 1
        elif start is not None and ln.startswith("Trade History:"):
            end = i
            break
    if start is None:
        raise RuntimeError(f"no Activities section in {log_path}")
    header = lines[start].split(";")
    col_pnl = header.index("profit_and_loss")
    col_day = header.index("day")
    col_product = header.index("product")
    col_ts = header.index("timestamp")

    last_pnl = {}  # (day, product) -> (ts, pnl)
    for ln in lines[start+1:end]:
        if not ln.strip():
            continue
        parts = ln.split(";")
        if len(parts) <= col_pnl:
            continue
        try:
            day = int(parts[col_day])
            ts = int(parts[col_ts])
            product = parts[col_product]
            pnl = float(parts[col_pnl]) if parts[col_pnl] else 0.0
        except ValueError:
            continue
        key = (day, product)
        if key not in last_pnl or ts > last_pnl[key][0]:
            last_pnl[key] = (ts, pnl)
    return {k: v[1] for k, v in last_pnl.items()}

def extract_half2_pnl(log_path, ts_split=500000):
    """Return {(day, product): pnl_at_last_tick_minus_pnl_at_split}.
    Approximates PnL contribution from second half of the day."""
    with open(log_path) as f:
        lines = f.read().splitlines()
    start = None
    end = None
    for i, ln in enumerate(lines):
        if ln.startswith("Activities log:"):
            start = i + 1
        elif start is not None and ln.startswith("Trade History:"):
            end = i
            break
    header = lines[start].split(";")
    col_pnl = header.index("profit_and_loss")
    col_day = header.index("day")
    col_product = header.index("product")
    col_ts = header.index("timestamp")

    # per (day, product): collect (ts, pnl) and compute pnl at or just before ts_split
    rows = {}
    for ln in lines[start+1:end]:
        if not ln.strip():
            continue
        parts = ln.split(";")
        if len(parts) <= col_pnl:
            continue
        try:
            day = int(parts[col_day])
            ts = int(parts[col_ts])
            product = parts[col_product]
            pnl = float(parts[col_pnl]) if parts[col_pnl] else 0.0
        except ValueError:
            continue
        rows.setdefault((day, product), []).append((ts, pnl))

    half2 = {}
    for key, series in rows.items():
        series.sort()
        # pnl at first ts >= ts_split
        split_pnl = 0.0
        for ts, pnl in series:
            if ts >= ts_split:
                split_pnl = pnl
                break
        final_pnl = series[-1][1]
        half2[key] = final_pnl - split_pnl
    return half2

if __name__ == "__main__":
    runs = Path("/Users/samuelshi/IMC-Prosperity-2026-personal/runs")
    logs = {
        "v8_day-2": runs / "v8_day-2.log",
        "v8_day-1": runs / "v8_day-1.log",
        "v8_day0":  runs / "v8_day0.log",
        "v8_merged": runs / "v8_merged.log",
        "qo5_day-2": runs / "qo5_ms8_te3_day-2.log",
        "qo5_day-1": runs / "qo5_ms8_te3_day-1.log",
        "qo5_day0":  runs / "qo5_ms8_te3_day0.log",
    }
    full = {name: extract_pnl(p) for name, p in logs.items()}
    half2 = {name: extract_half2_pnl(p) for name, p in logs.items()}

    # Print concise report
    print("=== Full-day ACO PnL ===")
    for name, res in full.items():
        aco_vals = {d: v for (d, prod), v in res.items() if prod == "ASH_COATED_OSMIUM"}
        ipr_vals = {d: v for (d, prod), v in res.items() if prod == "INTARIAN_PEPPER_ROOT"}
        print(f"{name:12s}  ACO: {aco_vals}  IPR: {ipr_vals}")

    print("\n=== Second-half (ts>=500000) ACO PnL ===")
    for name, res in half2.items():
        aco_vals = {d: round(v, 1) for (d, prod), v in res.items() if prod == "ASH_COATED_OSMIUM"}
        print(f"{name:12s}  ACO_half2: {aco_vals}")

    # Save baselines.json
    out = {
        "full_day": {
            name: {
                f"{prod}_day{d}": v
                for (d, prod), v in res.items()
            } for name, res in full.items()
        },
        "half2": {
            name: {
                f"{prod}_day{d}": v
                for (d, prod), v in res.items()
            } for name, res in half2.items()
        },
    }
    outpath = Path("/Users/samuelshi/IMC-Prosperity-2026-personal/Round 1/analysis/baselines.json")
    outpath.write_text(json.dumps(out, indent=2))
    print(f"\nSaved {outpath}")
