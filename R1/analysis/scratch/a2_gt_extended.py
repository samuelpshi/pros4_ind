"""
a2_gt_extended.py — Extended GT runs for A2
============================================
Since tagging-layer is unreliable (rho=0.04), run GT on top 50 by full_day_worst3.
This replaces tagging-based ranking with GT-based ranking for Step 6.
"""

import os, sys, json, re, subprocess, time
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE     = os.path.dirname(os.path.abspath(__file__))
ANALYSIS = os.path.dirname(HERE)
ROUND1   = os.path.dirname(ANALYSIS)
REPO     = os.path.dirname(ROUND1)

TRADERS_DIR = os.path.join(ROUND1, "traders")
CAND_DIR    = os.path.join(HERE, "a2_candidates")
TEMPLATE    = os.path.join(TRADERS_DIR, "trader-v9-aco-qo5-ms8-te3.py")

os.makedirs(CAND_DIR, exist_ok=True)

QO5_FULL  = {-2: 9201.0, -1: 10793.0, 0: 9013.0}
QO5_HALF2 = {-2: 4139.0, -1: 5494.0,  0: 4588.0}


def make_candidate_trader(cfg, label):
    with open(TEMPLATE, "r") as f:
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
    src_new = re.sub(
        r'ACO_CFG\s*=\s*\{[^}]*\}',
        new_cfg, src, count=1, flags=re.DOTALL
    )
    out_path = os.path.join(CAND_DIR, f"a2_ext_{label}.py")
    with open(out_path, "w") as f:
        f.write(src_new)
    return out_path


def run_gt_day(trader_path, day):
    log_path = trader_path.replace(".py", f"_day{day}.log")
    cmd = ["prosperity4btest", trader_path, f"1-{day}", "--out", log_path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        return None
    try:
        with open(log_path) as f:
            lines = f.read().splitlines()
        start = next(i for i, l in enumerate(lines) if l.startswith("Activities log:"))
        header = lines[start + 1].split(";")
        col_pnl = header.index("profit_and_loss")
        col_product = header.index("product")
        col_ts = header.index("timestamp")
        last_aco = (0, 0.0)
        end = next((i for i in range(start+2, len(lines)) if lines[i].startswith("Trade History:")), len(lines))
        for l in lines[start+2:end]:
            parts = l.split(";")
            if len(parts) <= col_pnl: continue
            try:
                ts = int(parts[col_ts])
                prod = parts[col_product]
                pnl = float(parts[col_pnl]) if parts[col_pnl] else 0.0
                if prod == "ASH_COATED_OSMIUM" and ts > last_aco[0]:
                    last_aco = (ts, pnl)
            except ValueError:
                continue
        return last_aco[1]
    except Exception as e:
        print(f"    WARN parse: {e}")
        return None


def run_extended_gt(top_n=50):
    t0 = time.time()
    print(f"Extended GT runs for top {top_n} by tagging full_day_worst3")

    with open(os.path.join(HERE, "a2_eval_results.json")) as f:
        results = json.load(f)

    df = pd.DataFrame(results)
    df['full_worst3'] = df[['full_day_-2', 'full_day_-1', 'full_day_0']].min(axis=1)
    df['full_sum3'] = df['full_day_-2'] + df['full_day_-1'] + df['full_day_0']
    df = df.sort_values('full_worst3', ascending=False).reset_index(drop=True)
    df['tag_rank'] = df.index + 1

    # Already have GT for tagging top-10 (by worst_of_6)
    with open(os.path.join(HERE, "a2_top10_gt.json")) as f:
        existing_gt = json.load(f)
    done_keys = set()
    existing_map = {}
    for r in existing_gt:
        k = (int(r['quote_offset']), int(r['max_skew']),
             round(float(r['take_edge']), 4), round(float(r['ema_alpha']), 4))
        done_keys.add(k)
        existing_map[k] = r

    gt_results = []
    skipped = 0

    for i, (_, row) in enumerate(df.head(top_n).iterrows()):
        cfg = {
            "quote_offset": int(row["quote_offset"]),
            "max_skew":     int(row["max_skew"]),
            "take_edge":    round(float(row["take_edge"]), 4),
            "ema_alpha":    round(float(row["ema_alpha"]), 4),
        }
        k = (cfg["quote_offset"], cfg["max_skew"], cfg["take_edge"], cfg["ema_alpha"])

        if k in done_keys:
            # Reuse existing GT
            ex = existing_map[k]
            gt_results.append({
                "tag_rank_full": int(row["tag_rank"]),
                "tag_full_worst3": float(row["full_worst3"]),
                "tag_full_sum3": float(row["full_sum3"]),
                **cfg,
                "gt_day_-2": ex.get("gt_day_-2"),
                "gt_day_-1": ex.get("gt_day_-1"),
                "gt_day_0":  ex.get("gt_day_0"),
                "gt_worst3": ex.get("gt_worst_3"),
                "gt_sum3":   ex.get("gt_sum"),
                "reused": True,
            })
            skipped += 1
            continue

        print(f"  [{i+1}/{top_n}] qo={cfg['quote_offset']} ms={cfg['max_skew']} "
              f"te={cfg['take_edge']} alpha={cfg['ema_alpha']}")

        trader_path = make_candidate_trader(cfg, f"{i:03d}")
        day_pnls = {}
        for day in [-2, -1, 0]:
            pnl = run_gt_day(trader_path, day)
            day_pnls[day] = pnl

        valid = [v for v in day_pnls.values() if v is not None]
        gt_results.append({
            "tag_rank_full": int(row["tag_rank"]),
            "tag_full_worst3": float(row["full_worst3"]),
            "tag_full_sum3": float(row["full_sum3"]),
            **cfg,
            "gt_day_-2": day_pnls.get(-2),
            "gt_day_-1": day_pnls.get(-1),
            "gt_day_0":  day_pnls.get(0),
            "gt_worst3": min(valid) if valid else None,
            "gt_sum3":   sum(valid) if valid else None,
            "reused": False,
        })

    print(f"\nDone. {len(gt_results)} total, {skipped} reused from existing GT.")
    print(f"Wall time: {time.time()-t0:.1f}s")

    # Sort by GT worst3
    gt_df = pd.DataFrame(gt_results)
    gt_df = gt_df.sort_values("gt_worst3", ascending=False, na_position='last').reset_index(drop=True)
    gt_df["gt_rank"] = gt_df.index + 1

    # Save
    out_path = os.path.join(HERE, "a2_gt_extended.json")
    gt_df.to_json(out_path, orient="records", indent=2)
    print(f"Saved: {out_path}")

    # Spearman
    valid_df = gt_df.dropna(subset=["gt_worst3"])
    if len(valid_df) > 2:
        rho, pval = spearmanr(valid_df["tag_rank_full"], valid_df["gt_rank"])
        print(f"\nSpearman ρ (tag full_worst3_rank vs GT worst3_rank): {rho:.3f}  (p={pval:.4f})")

    print("\nTop 20 by GT worst3:")
    cols = ["gt_rank","tag_rank_full","quote_offset","max_skew","take_edge","ema_alpha",
            "gt_day_-2","gt_day_-1","gt_day_0","gt_worst3","gt_sum3"]
    print(gt_df[cols].head(20).to_string(index=False))

    print(f"\nv9-qo5 GT baseline: worst3=9013, sum3=29007")
    print(f"Best GT worst3 found: {gt_df['gt_worst3'].max():.1f}")
    print(f"Combos beating qo5 worst3 (>9013): {(gt_df['gt_worst3'] > 9013).sum()}")
    print(f"Combos beating qo5 sum3  (>29007): {(gt_df['gt_sum3'] > 29007).sum()}")

    return gt_df


if __name__ == "__main__":
    gt_df = run_extended_gt(top_n=50)
