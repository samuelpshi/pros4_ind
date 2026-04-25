"""
a2_finalize.py — Compile all GT results, rerun null-baseline, produce final artifacts.
"""

import os, sys, json, time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import spearmanr

HERE     = os.path.dirname(os.path.abspath(__file__))
ANALYSIS = os.path.dirname(HERE)
PLOT_DIR = os.path.join(ANALYSIS, "plots", "aco_pass2_6")
os.makedirs(PLOT_DIR, exist_ok=True)

QO5_FULL  = {-2: 9201.0, -1: 10793.0, 0: 9013.0}
QO5_HALF2 = {-2: 4139.0, -1: 5494.0,  0: 4588.0}
QO5_WORST6 = 4139.0
QO5_WORST3 = 9013.0
QO5_SUM3   = 29007.0


def main():
    # -------------------------------------------------------------------------
    # Load all GT results
    # -------------------------------------------------------------------------
    all_gt = []
    seen = set()

    for fname in ["a2_top10_gt.json", "a2_gt_extended.json", "a2_gt_hiqo.json"]:
        fpath = os.path.join(HERE, fname)
        if not os.path.exists(fpath):
            continue
        with open(fpath) as f:
            data = json.load(f)
        rows = data if isinstance(data, list) else []
        for r in rows:
            k = (int(r['quote_offset']), int(r['max_skew']),
                 round(float(r['take_edge']), 4), round(float(r['ema_alpha']), 4))
            if k in seen:
                continue
            seen.add(k)
            gt_d2 = r.get('gt_day_-2')
            gt_d1 = r.get('gt_day_-1')
            gt_d0 = r.get('gt_day_0')
            valid = [v for v in [gt_d2, gt_d1, gt_d0] if v is not None]
            all_gt.append({
                "quote_offset": int(r['quote_offset']),
                "max_skew":     int(r['max_skew']),
                "take_edge":    round(float(r['take_edge']), 4),
                "ema_alpha":    round(float(r['ema_alpha']), 4),
                "gt_day_-2":    gt_d2,
                "gt_day_-1":    gt_d1,
                "gt_day_0":     gt_d0,
                "gt_worst3":    min(valid) if valid else None,
                "gt_sum3":      sum(valid) if valid else None,
            })

    gt_df = pd.DataFrame(all_gt)
    gt_df = gt_df.dropna(subset=["gt_worst3"])
    gt_df = gt_df.sort_values("gt_worst3", ascending=False).reset_index(drop=True)
    gt_df["gt_rank"] = gt_df.index + 1

    print(f"Total GT evaluations: {len(gt_df)}")
    print(f"v9-qo5 GT: worst3={QO5_WORST3}, sum3={QO5_SUM3}")
    print(f"Best GT worst3: {gt_df['gt_worst3'].max():.1f}")
    print(f"Combos beating qo5 worst3: {(gt_df['gt_worst3'] > QO5_WORST3).sum()}")
    print(f"Combos beating qo5 sum3:   {(gt_df['gt_sum3'] > QO5_SUM3).sum()}")

    # -------------------------------------------------------------------------
    # Also load tagging eval for tagging vs GT correlation on what we have
    # -------------------------------------------------------------------------
    with open(os.path.join(HERE, "a2_eval_results.json")) as f:
        tag_results = json.load(f)
    tag_df = pd.DataFrame(tag_results)
    tag_df['tag_full_worst3'] = tag_df[['full_day_-2','full_day_-1','full_day_0']].min(axis=1)

    # Merge with GT
    merged = gt_df.merge(
        tag_df[['quote_offset','max_skew','take_edge','ema_alpha','tag_full_worst3']],
        on=['quote_offset','max_skew','take_edge','ema_alpha'],
        how='left'
    )
    tag_rank = merged['tag_full_worst3'].rank(ascending=False)
    gt_rank  = merged['gt_worst3'].rank(ascending=False)
    rho, pval = spearmanr(tag_rank, gt_rank)
    print(f"\nSpearman ρ (tagging full_worst3 vs GT worst3, n={len(merged)}): {rho:.3f}  p={pval:.4f}")
    if rho < 0.7:
        print("  => tagging-layer ranking is unreliable; GT is the authoritative ranking")

    # -------------------------------------------------------------------------
    # Null-baseline using GT worst3 distribution
    # -------------------------------------------------------------------------
    w3_arr = gt_df['gt_worst3'].values
    median_w3  = float(np.percentile(w3_arr, 50))
    p95_w3     = float(np.percentile(w3_arr, 95))
    noise_spread = p95_w3 - median_w3
    threshold = QO5_WORST3 + noise_spread

    print(f"\n{'='*50}")
    print("NULL-BASELINE (GT-based)")
    print(f"{'='*50}")
    print(f"  v9-qo5 GT worst3:         {QO5_WORST3:,.0f}")
    print(f"  Median GT worst3:          {median_w3:,.1f}")
    print(f"  95th pct GT worst3:        {p95_w3:,.1f}")
    print(f"  Noise spread (95-50):      {noise_spread:,.1f}")
    print(f"  Threshold (v9+noise):      {threshold:,.1f}")
    print(f"  Combos above threshold:    {(w3_arr > threshold).sum()}")

    # -------------------------------------------------------------------------
    # Top 20 table
    # -------------------------------------------------------------------------
    print(f"\nTop 20 by GT worst3:")
    cols = ["gt_rank","quote_offset","max_skew","take_edge","ema_alpha",
            "gt_day_-2","gt_day_-1","gt_day_0","gt_worst3","gt_sum3"]
    print(gt_df[cols].head(20).to_string(index=False))

    # -------------------------------------------------------------------------
    # Identify top 3 candidates
    # -------------------------------------------------------------------------
    # Criterion 1: GT worst3 > threshold
    crit1 = gt_df[gt_df['gt_worst3'] > threshold]

    # Criterion 2: beats qo5 worst3 AND sum3
    crit2 = gt_df[(gt_df['gt_worst3'] > QO5_WORST3) & (gt_df['gt_sum3'] > QO5_SUM3)]

    print(f"\nCrit 1 (GT worst3 > threshold {threshold:.0f}): {len(crit1)}")
    print(f"Crit 2 (GT worst3 > {QO5_WORST3} AND sum3 > {QO5_SUM3}): {len(crit2)}")

    candidates = pd.concat([crit1, crit2]).drop_duplicates(
        subset=["quote_offset","max_skew","take_edge","ema_alpha"]
    ).sort_values("gt_worst3", ascending=False).reset_index(drop=True)

    print(f"\nTotal qualifying candidates: {len(candidates)}")

    # -------------------------------------------------------------------------
    # Histogram plot (GT-based)
    # -------------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.hist(w3_arr, bins=40, color="steelblue", alpha=0.7, edgecolor="white")
    ax.axvline(QO5_WORST3, color="crimson", linewidth=2.5,
               label=f"v9-qo5 GT worst3 = {QO5_WORST3:,.0f}")
    ax.axvline(threshold, color="darkorange", linewidth=2.5, linestyle="--",
               label=f"Threshold = {threshold:,.0f}")
    ax.axvline(median_w3, color="green", linewidth=1.5, linestyle=":",
               label=f"Median = {median_w3:,.0f}")
    ax.set_xlabel("GT worst_of_3 (XIREC)")
    ax.set_ylabel("Count")
    ax.set_title("A2: Distribution of GT worst_of_3 across 245 evaluated combos")
    ax.legend(fontsize=10)
    plt.tight_layout()
    plot_path = os.path.join(PLOT_DIR, "a2_worst_of_6_dist.png")
    fig.savefig(plot_path, dpi=120)
    plt.close(fig)
    print(f"\nHistogram saved: {plot_path}")

    # -------------------------------------------------------------------------
    # Save final top3 and comprehensive eval
    # -------------------------------------------------------------------------
    # Save consolidated GT eval
    gt_df.to_json(os.path.join(HERE, "a2_eval_gt_all.json"), orient="records", indent=2)

    top3 = candidates.head(3)
    if len(top3) == 0:
        out = {"result": "null", "reason": "No combo beats threshold or criteria."}
    else:
        out_list = []
        for _, row in top3.iterrows():
            out_list.append({
                "quote_offset": int(row["quote_offset"]),
                "max_skew":     int(row["max_skew"]),
                "take_edge":    float(row["take_edge"]),
                "ema_alpha":    float(row["ema_alpha"]),
                "panic_threshold": 0.75,
                "gt_day_-2":    float(row["gt_day_-2"]),
                "gt_day_-1":    float(row["gt_day_-1"]),
                "gt_day_0":     float(row["gt_day_0"]),
                "gt_worst3":    float(row["gt_worst3"]),
                "gt_sum3":      float(row["gt_sum3"]),
            })
        out = {"result": "candidates", "top3": out_list}

    with open(os.path.join(HERE, "a2_top3_candidates.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(f"Top-3 saved: {os.path.join(HERE, 'a2_top3_candidates.json')}")

    print("\nTop 3 candidates:")
    print(top3[["quote_offset","max_skew","take_edge","ema_alpha",
                "gt_day_-2","gt_day_-1","gt_day_0","gt_worst3","gt_sum3"]].to_string(index=False))

    return gt_df, candidates, threshold, rho


if __name__ == "__main__":
    main()
