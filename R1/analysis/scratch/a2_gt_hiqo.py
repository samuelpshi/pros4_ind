"""
a2_gt_hiqo.py — GT runs for high-qo candidates
================================================
Since tagging layer is biased against qo>=5 (uses qo5 fill stream,
wider quotes look like 0 fills), run GT on all qo=5,6,7,8 candidates
(75 combos) to find true best in that regime.
Also run top 20 by tagging full_sum3 for qo=4 (already have some from extended).
"""

import os, sys, json, re, subprocess, time
import numpy as np
import pandas as pd

HERE     = os.path.dirname(os.path.abspath(__file__))
ANALYSIS = os.path.dirname(HERE)
ROUND1   = os.path.dirname(ANALYSIS)
TRADERS_DIR = os.path.join(ROUND1, "traders")
CAND_DIR    = os.path.join(HERE, "a2_candidates")
TEMPLATE    = os.path.join(TRADERS_DIR, "trader-v9-aco-qo5-ms8-te3.py")
os.makedirs(CAND_DIR, exist_ok=True)

QO5_FULL = {-2: 9201.0, -1: 10793.0, 0: 9013.0}


def make_trader(cfg, label):
    with open(TEMPLATE) as f:
        src = f.read()
    new_cfg = (
        f'ACO_CFG = {{\n'
        f'    "ema_alpha":       {cfg["ema_alpha"]},\n'
        f'    "quote_offset":    {cfg["quote_offset"]},\n'
        f'    "take_edge":       {cfg["take_edge"]},\n'
        f'    "max_skew":        {cfg["max_skew"]},\n'
        f'    "panic_threshold": 0.75,\n'
        f'}}'
    )
    src_new = re.sub(r'ACO_CFG\s*=\s*\{[^}]*\}', new_cfg, src, count=1, flags=re.DOTALL)
    out = os.path.join(CAND_DIR, f"a2_hiqo_{label}.py")
    with open(out, "w") as f:
        f.write(src_new)
    return out


def run_day(trader_path, day):
    log_path = trader_path.replace(".py", f"_day{day}.log")
    r = subprocess.run(
        ["prosperity4btest", trader_path, f"1-{day}", "--out", log_path],
        capture_output=True, text=True, timeout=120
    )
    if r.returncode != 0:
        return None
    try:
        with open(log_path) as f:
            lines = f.read().splitlines()
        start = next(i for i, l in enumerate(lines) if l.startswith("Activities log:"))
        header = lines[start+1].split(";")
        cp = header.index("profit_and_loss")
        pp = header.index("product")
        tp = header.index("timestamp")
        best = (0, 0.0)
        end = next((i for i in range(start+2,len(lines)) if lines[i].startswith("Trade History:")), len(lines))
        for l in lines[start+2:end]:
            parts = l.split(";")
            if len(parts) <= cp: continue
            try:
                ts = int(parts[tp]); prod = parts[pp]; pnl = float(parts[cp]) if parts[cp] else 0.0
                if prod == "ASH_COATED_OSMIUM" and ts > best[0]:
                    best = (ts, pnl)
            except: continue
        return best[1]
    except Exception as e:
        print(f"  WARN: {e}")
        return None


def main():
    t0 = time.time()
    with open(os.path.join(HERE, "a2_eval_results.json")) as f:
        results = json.load(f)

    df = pd.DataFrame(results)
    df['full_sum3'] = df['full_day_-2'] + df['full_day_-1'] + df['full_day_0']
    df['full_worst3'] = df[['full_day_-2','full_day_-1','full_day_0']].min(axis=1)

    # Load already-done GT keys
    done = {}
    for fname in ["a2_top10_gt.json", "a2_gt_extended.json"]:
        fpath = os.path.join(HERE, fname)
        if os.path.exists(fpath):
            data = json.load(open(fpath))
            if isinstance(data, list):
                rows = data
            else:
                rows = data
            for r in (rows if isinstance(rows, list) else []):
                k = (int(r['quote_offset']), int(r['max_skew']),
                     round(float(r['take_edge']), 4), round(float(r['ema_alpha']), 4))
                gt_d2  = r.get('gt_day_-2') or r.get('gt_day_{-2}')
                gt_d1  = r.get('gt_day_-1') or r.get('gt_day_{-1}')
                gt_d0  = r.get('gt_day_0')  or r.get('gt_day_{0}')
                if gt_d2 is not None:
                    done[k] = {"gt_day_-2": gt_d2, "gt_day_-1": gt_d1, "gt_day_0": gt_d0}

    # Candidates: all qo >= 5 + top20 qo=4 by full_sum3
    hi = df[df['quote_offset'] >= 5].copy()
    mid = df[df['quote_offset'] == 4].sort_values('full_sum3', ascending=False).head(20)
    todo = pd.concat([hi, mid]).drop_duplicates(
        subset=['quote_offset','max_skew','take_edge','ema_alpha']).reset_index(drop=True)

    print(f"Candidates to GT: {len(todo)}  (qo>=5: {len(hi)}, top20 qo=4: {len(mid)})")
    print(f"Already done: {len(done)}")

    gt_rows = []
    new_count = 0

    for i, (_, row) in enumerate(todo.iterrows()):
        cfg = {
            "quote_offset": int(row["quote_offset"]),
            "max_skew":     int(row["max_skew"]),
            "take_edge":    round(float(row["take_edge"]), 4),
            "ema_alpha":    round(float(row["ema_alpha"]), 4),
        }
        k = (cfg["quote_offset"], cfg["max_skew"], cfg["take_edge"], cfg["ema_alpha"])

        if k in done:
            ex = done[k]
            day_pnls = {-2: ex["gt_day_-2"], -1: ex["gt_day_-1"], 0: ex["gt_day_0"]}
        else:
            trader_path = make_trader(cfg, f"hq_{i:03d}")
            day_pnls = {}
            for day in [-2, -1, 0]:
                day_pnls[day] = run_day(trader_path, day)
            new_count += 1
            if new_count % 10 == 0:
                print(f"  {new_count} new GT runs done ({time.time()-t0:.0f}s)")

        valid = [v for v in day_pnls.values() if v is not None]
        gt_rows.append({
            **cfg,
            "gt_day_-2": day_pnls.get(-2),
            "gt_day_-1": day_pnls.get(-1),
            "gt_day_0":  day_pnls.get(0),
            "gt_worst3": min(valid) if valid else None,
            "gt_sum3":   sum(valid) if valid else None,
            "tag_full_worst3": float(row["full_worst3"]),
            "tag_full_sum3":   float(row["full_sum3"]),
        })

    gt_df = pd.DataFrame(gt_rows).sort_values("gt_worst3", ascending=False,
                                               na_position='last').reset_index(drop=True)
    gt_df["gt_rank"] = gt_df.index + 1

    out = os.path.join(HERE, "a2_gt_hiqo.json")
    gt_df.to_json(out, orient="records", indent=2)
    print(f"\nSaved: {out}")
    print(f"Total wall time: {time.time()-t0:.1f}s  ({new_count} new GT runs)")

    print(f"\nv9-qo5 baseline: worst3=9013, sum3=29007")
    print(f"Best GT worst3 found: {gt_df['gt_worst3'].dropna().max():.1f}")
    print(f"Combos beating qo5 worst3 (>9013): {(gt_df['gt_worst3'] > 9013).sum()}")
    print(f"Combos beating qo5 sum3  (>29007): {(gt_df['gt_sum3'] > 29007).sum()}")
    print()
    print("Top 20 by GT worst3:")
    cols = ["gt_rank","quote_offset","max_skew","take_edge","ema_alpha",
            "gt_day_-2","gt_day_-1","gt_day_0","gt_worst3","gt_sum3"]
    print(gt_df[cols].head(20).to_string(index=False))

    return gt_df


if __name__ == "__main__":
    main()
