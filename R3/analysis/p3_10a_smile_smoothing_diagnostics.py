"""
P3.10a smile-smoothing diagnostic — analysis-only, no trader change.

For each smile-update regime, recomputes per-strike residuals on the
historical 3 days and asks two structural questions:

  1. Do residuals mean-revert at any horizon? (lag-k autocorr at
     k=1,5,10,50,200)
  2. Does entry |z| predict future residual movement? (forward-
     residual-PnL by |z| bucket at h=5,20,100,200)

Plus a same-sign clustering diagnostic for |z|>2.0 events: of the
next 5 ticks, what fraction share the sign of the entry z?

Gate (per Sam):
  - At least one autocorr-lag in {1,5,10,50,200} is materially
    negative (|corr| > 0.05 and corr < 0) on the average-across-
    strikes residual, in at least one regime.
  - Forward-residual-PnL grows monotonically with entry |z|
    bucket on a per-trade basis, in at least one regime.

If either fails -> verdict "GATE FAILED, do not auto-pivot, surface
to Sam".

Output: prints summary tables; writes
R3/analysis/cache/p3_10a_metrics.json for the verdict log.
"""

import csv
import json
import math
from pathlib import Path
from statistics import NormalDist
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "r3_datacap"
CACHE_DIR = ROOT / "analysis" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Match noTrade-5100 config: fit on 6 strikes, evaluate residuals on 5 active
FIT_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
ACTIVE_STRIKES = [5000, 5200, 5300, 5400, 5500]
PRODUCT_VEV = "VELVETFRUIT_EXTRACT"

DAY_TO_TTE_DAYS = {0: 8, 1: 7, 2: 6}

# Trader z-score conventions (must match trader)
EMA_WINDOW = 20
Z_WINDOW = 100
Z_OPEN = 2.0
HARDCODED_FALLBACK = (0.143, -0.002, 0.236)

LAGS = [1, 5, 10, 50, 200]
HORIZONS = [5, 20, 100, 200]
Z_BUCKETS = [(0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 2.5),
             (2.5, 3.0), (3.0, 4.0), (4.0, 1e9)]
SAME_SIGN_WINDOW = 5

_N = NormalDist()


def bs_call(S, K, T, sigma):
    if T <= 0.0 or sigma <= 0.0 or S <= 0.0:
        intrinsic = max(0.0, S - K)
        return intrinsic, (1.0 if S > K else 0.0), 0.0
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    return (S * _N.cdf(d1) - K * _N.cdf(d2),
            _N.cdf(d1),
            S * _N.pdf(d1) * sqrtT)


def solve_iv(market_price, S, K, T, initial=0.23):
    intrinsic = max(0.0, S - K)
    if market_price <= intrinsic + 1e-6 or market_price >= S:
        return None
    sigma = max(initial, 0.05)
    for _ in range(20):
        price, _, vega = bs_call(S, K, T, sigma)
        diff = price - market_price
        if abs(diff) < 1e-5:
            return sigma
        if vega < 1e-6:
            break
        sigma_new = sigma - diff / vega
        if sigma_new <= 0.0 or sigma_new > 5.0:
            break
        if abs(sigma_new - sigma) < 1e-7:
            return sigma_new
        sigma = sigma_new
    lo, hi = 0.01, 2.0
    p_lo, _, _ = bs_call(S, K, T, lo)
    p_hi, _, _ = bs_call(S, K, T, hi)
    if (p_lo - market_price) * (p_hi - market_price) > 0.0:
        return None
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        p_mid, _, _ = bs_call(S, K, T, mid)
        if abs(p_mid - market_price) < 1e-5:
            return mid
        if (p_lo - market_price) * (p_mid - market_price) <= 0.0:
            hi = mid
        else:
            lo = mid
            p_lo = p_mid
    return 0.5 * (lo + hi)


def fit_quadratic_smile(ms, ivs):
    n = len(ms)
    if n < 3 or n != len(ivs):
        return None
    s0 = float(n)
    s1 = sum(ms)
    s2 = sum(x * x for x in ms)
    s3 = sum(x * x * x for x in ms)
    s4 = sum(x * x * x * x for x in ms)
    t0 = sum(ivs)
    t1 = sum(x * y for x, y in zip(ms, ivs))
    t2 = sum(x * x * y for x, y in zip(ms, ivs))
    M = [[s4, s3, s2, t2],
         [s3, s2, s1, t1],
         [s2, s1, s0, t0]]
    for i in range(3):
        piv = i
        for k in range(i + 1, 3):
            if abs(M[k][i]) > abs(M[piv][i]):
                piv = k
        if piv != i:
            M[i], M[piv] = M[piv], M[i]
        if abs(M[i][i]) < 1e-12:
            return None
        for k in range(i + 1, 3):
            f = M[k][i] / M[i][i]
            for j in range(i, 4):
                M[k][j] -= f * M[i][j]
    c = M[2][3] / M[2][2]
    b = (M[1][3] - M[1][2] * c) / M[1][1]
    a = (M[0][3] - M[0][1] * b - M[0][2] * c) / M[0][0]
    return a, b, c


def smile_iv(coefs, m):
    a, b, c = coefs
    return a * m * m + b * m + c


def voucher_symbol(K):
    return f"VEV_{K}"


def load_day(day):
    """Returns dict: ts -> {product -> mid}. Sorted by timestamp."""
    f = DATA_DIR / f"prices_round_3_day_{day}.csv"
    by_ts = {}
    with open(f, "r") as fp:
        reader = csv.DictReader(fp, delimiter=";")
        for row in reader:
            ts = int(row["timestamp"])
            prod = row["product"]
            mid = row.get("mid_price")
            if mid is None or mid == "":
                continue
            try:
                m = float(mid)
            except ValueError:
                continue
            by_ts.setdefault(ts, {})[prod] = m
    return by_ts


def per_tick_pertick_smile(ts_data, day):
    """For each timestamp, compute baseline per-tick smile coefs +
    per-strike residuals + per-strike z. Returns:
      timestamps (sorted),
      S_arr,
      iv_inputs[t] -> {K: iv}  (only for strikes in FIT_STRIKES with valid mid+iv)
      moneyness[t] -> {K: m}   (for all strikes in FIT_STRIKES with valid mid)
    Also returns voucher_mids[t] -> {K: mid} for ACTIVE_STRIKES with valid mid.
    """
    tte_days_at_start = DAY_TO_TTE_DAYS[day]
    timestamps = sorted(ts_data.keys())
    S_arr = []
    iv_inputs_per_t = []
    moneyness_per_t = []
    voucher_mids_active = []
    Ts = []
    for ts in timestamps:
        snap = ts_data[ts]
        S = snap.get(PRODUCT_VEV)
        if S is None:
            S_arr.append(None)
            iv_inputs_per_t.append({})
            moneyness_per_t.append({})
            voucher_mids_active.append({})
            Ts.append(None)
            continue
        tf = ts / 1_000_000.0
        T = max((tte_days_at_start - tf) / 365.0, 1e-6)
        sqrtT = math.sqrt(T)
        ivin = {}
        mny = {}
        for K in FIT_STRIKES:
            mid = snap.get(voucher_symbol(K))
            if mid is None:
                continue
            m = math.log(K / S) / sqrtT
            mny[K] = m
            iv = solve_iv(mid, S, K, T)
            if iv is not None:
                ivin[K] = iv
        actives = {}
        for K in ACTIVE_STRIKES:
            mid = snap.get(voucher_symbol(K))
            if mid is None:
                continue
            actives[K] = mid
            if K not in mny:
                mny[K] = math.log(K / S) / sqrtT
        S_arr.append(S)
        iv_inputs_per_t.append(ivin)
        moneyness_per_t.append(mny)
        voucher_mids_active.append(actives)
        Ts.append(T)
    return timestamps, S_arr, Ts, iv_inputs_per_t, moneyness_per_t, voucher_mids_active


def compute_smile_series(iv_inputs_per_t, moneyness_per_t, regime):
    """Returns smile_coefs_per_t list. regime is a dict:
       {"kind": "pertick"} | {"kind": "ema", "N": 20|50|100}
       | {"kind": "refit_every", "N": 20|50|100}
    Always falls back to last_smile or hardcoded fallback when fit fails.
    """
    out = []
    last_coefs = None
    last_fit = HARDCODED_FALLBACK
    n_steps = len(iv_inputs_per_t)
    if regime["kind"] == "pertick":
        for ivin, mny in zip(iv_inputs_per_t, moneyness_per_t):
            if len(ivin) >= 4:
                ms = [mny[K] for K in ivin]
                ivs = [ivin[K] for K in ivin]
                fit = fit_quadratic_smile(ms, ivs)
            else:
                fit = None
            if fit is not None:
                last_fit = fit
            out.append(last_fit)
        return out
    if regime["kind"] == "ema":
        N = regime["N"]
        alpha = 2.0 / (N + 1.0)
        ema = None
        for ivin, mny in zip(iv_inputs_per_t, moneyness_per_t):
            if len(ivin) >= 4:
                ms = [mny[K] for K in ivin]
                ivs = [ivin[K] for K in ivin]
                fit = fit_quadratic_smile(ms, ivs)
            else:
                fit = None
            if fit is not None:
                if ema is None:
                    ema = fit
                else:
                    ema = (alpha * fit[0] + (1 - alpha) * ema[0],
                           alpha * fit[1] + (1 - alpha) * ema[1],
                           alpha * fit[2] + (1 - alpha) * ema[2])
                last_fit = ema
            out.append(last_fit)
        return out
    if regime["kind"] == "refit_every":
        N = regime["N"]
        held = None
        for i, (ivin, mny) in enumerate(zip(iv_inputs_per_t, moneyness_per_t)):
            if held is None or i % N == 0:
                if len(ivin) >= 4:
                    ms = [mny[K] for K in ivin]
                    ivs = [ivin[K] for K in ivin]
                    fit = fit_quadratic_smile(ms, ivs)
                    if fit is not None:
                        held = fit
                        last_fit = fit
            out.append(held if held is not None else last_fit)
        return out
    raise ValueError(regime)


def compute_residuals(timestamps, S_arr, Ts, voucher_mids_active,
                      moneyness_per_t, smile_coefs_per_t):
    """Returns {K: list(residual or None)}, len == len(timestamps).
    residual = mid - bs_call(S, K, T, smile_iv(coefs, m))
    """
    out = {K: [None] * len(timestamps) for K in ACTIVE_STRIKES}
    for i, (S, T, mids, mny, coefs) in enumerate(
        zip(S_arr, Ts, voucher_mids_active, moneyness_per_t, smile_coefs_per_t)
    ):
        if S is None or T is None or coefs is None:
            continue
        for K in ACTIVE_STRIKES:
            if K not in mids or K not in mny:
                continue
            iv = smile_iv(coefs, mny[K])
            theo, _, _ = bs_call(S, K, T, iv)
            out[K][i] = mids[K] - theo
    return out


def compute_z_series(residuals_per_K):
    """Replicate trader's EMA-demean + rolling stdev z. Returns
    {K: list(z or None)}, demeaned residuals {K: list}, EMA series.
    """
    out_z = {K: [None] * len(residuals_per_K[next(iter(residuals_per_K))])
             for K in residuals_per_K}
    out_dem = {K: [None] * len(out_z[next(iter(out_z))]) for K in residuals_per_K}
    alpha = 2.0 / (EMA_WINDOW + 1.0)
    for K, series in residuals_per_K.items():
        ema = None
        buf = []
        for i, r in enumerate(series):
            if r is None:
                continue
            ema = r if ema is None else alpha * r + (1 - alpha) * ema
            dem = r - ema
            buf.append(dem)
            if len(buf) > Z_WINDOW:
                buf = buf[-Z_WINDOW:]
            out_dem[K][i] = dem
            if len(buf) >= 20:
                mu = sum(buf) / len(buf)
                var = sum((x - mu) ** 2 for x in buf) / max(len(buf) - 1, 1)
                sd = math.sqrt(var) if var > 0 else 0.0
                if sd > 1e-9:
                    out_z[K][i] = (dem - mu) / sd
                else:
                    out_z[K][i] = 0.0
    return out_z, out_dem


def autocorr_lag(series, k):
    """Autocorr of dem-residual at lag k, ignoring None pairs."""
    xs = []
    ys = []
    for i in range(len(series) - k):
        a, b = series[i], series[i + k]
        if a is None or b is None:
            continue
        xs.append(a)
        ys.append(b)
    n = len(xs)
    if n < 30:
        return None, n
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None, n
    return num / (dx * dy), n


def forward_resid_pnl_buckets(residuals_per_K, z_per_K, horizons):
    """Per-trade signed PnL = -sign(z[t]) * (resid[t+h] - resid[t]).
    Bucket by |z[t]| crossing into a band. We define "events" as ticks
    where |z[t]| in [lo, hi). To avoid double-counting clustered events,
    require |z[t-1]| < lo (a fresh crossing).

    Returns: per_K[K][bucket_label][horizon] -> {"n": ..., "mean":...,
    "median":..., "sum":...}, plus same aggregated across K.
    """
    from collections import defaultdict
    per_K = {}
    overall = {}

    def empty():
        return {f"{lo:.1f}-{hi:.1f}" if hi < 1e8 else f"{lo:.1f}+":
                {h: [] for h in horizons} for lo, hi in Z_BUCKETS}

    overall = empty()
    for K in z_per_K:
        per_K[K] = empty()
        zs = z_per_K[K]
        rs = residuals_per_K[K]
        prev_abs = 0.0
        for i, z in enumerate(zs):
            if z is None or rs[i] is None:
                continue
            absz = abs(z)
            for lo, hi in Z_BUCKETS:
                if lo <= absz < hi and prev_abs < lo:
                    bucket = f"{lo:.1f}-{hi:.1f}" if hi < 1e8 else f"{lo:.1f}+"
                    sign_z = 1 if z > 0 else -1
                    for h in horizons:
                        if i + h >= len(rs):
                            continue
                        rh = rs[i + h]
                        if rh is None:
                            continue
                        pnl = -sign_z * (rh - rs[i])
                        per_K[K][bucket][h].append(pnl)
                        overall[bucket][h].append(pnl)
                    break
            prev_abs = absz

    def summarize(buckets):
        out = {}
        for bk, hd in buckets.items():
            out[bk] = {}
            for h, vals in hd.items():
                if not vals:
                    out[bk][h] = {"n": 0, "mean": None, "median": None,
                                  "sum": 0.0}
                    continue
                vals_s = sorted(vals)
                m = sum(vals) / len(vals)
                med = vals_s[len(vals_s) // 2]
                out[bk][h] = {"n": len(vals), "mean": m,
                              "median": med, "sum": sum(vals)}
        return out

    return ({K: summarize(per_K[K]) for K in per_K},
            summarize(overall))


def same_sign_clustering(z_per_K, threshold=Z_OPEN, window=SAME_SIGN_WINDOW):
    """For each event |z|>threshold (fresh crossing), measure fraction
    of next `window` ticks with same sign of z (z[i+1..i+w]). Reports
    mean fraction, median, n events.
    """
    out = {}
    all_fracs = []
    for K, zs in z_per_K.items():
        fracs = []
        prev_abs = 0.0
        for i, z in enumerate(zs):
            if z is None:
                continue
            absz = abs(z)
            if absz > threshold and prev_abs <= threshold:
                sign_z = 1 if z > 0 else -1
                same = 0
                ct = 0
                for j in range(1, window + 1):
                    if i + j >= len(zs):
                        break
                    zj = zs[i + j]
                    if zj is None:
                        continue
                    ct += 1
                    if (zj > 0 and sign_z > 0) or (zj < 0 and sign_z < 0):
                        same += 1
                if ct > 0:
                    fracs.append(same / ct)
            prev_abs = absz
        if fracs:
            fracs_s = sorted(fracs)
            out[K] = {"n_events": len(fracs),
                      "mean_same_sign_frac": sum(fracs) / len(fracs),
                      "median_same_sign_frac": fracs_s[len(fracs_s) // 2]}
            all_fracs.extend(fracs)
        else:
            out[K] = {"n_events": 0, "mean_same_sign_frac": None,
                      "median_same_sign_frac": None}
    if all_fracs:
        all_s = sorted(all_fracs)
        out["__overall__"] = {"n_events": len(all_fracs),
                              "mean_same_sign_frac": sum(all_fracs) / len(all_fracs),
                              "median_same_sign_frac": all_s[len(all_s) // 2]}
    else:
        out["__overall__"] = {"n_events": 0, "mean_same_sign_frac": None,
                              "median_same_sign_frac": None}
    return out


def stdev(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None
    mu = sum(xs) / len(xs)
    var = sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(var)


def run_regime(day, ts_data, regime):
    timestamps, S_arr, Ts, iv_inputs, mny, mids = per_tick_pertick_smile(ts_data, day)
    coefs = compute_smile_series(iv_inputs, mny, regime)
    residuals = compute_residuals(timestamps, S_arr, Ts, mids, mny, coefs)
    z, dem = compute_z_series(residuals)

    # avg-across-strikes dem-residual for autocorr-on-aggregate
    n = len(timestamps)
    avg_dem = []
    for i in range(n):
        vals = [dem[K][i] for K in ACTIVE_STRIKES if dem[K][i] is not None]
        avg_dem.append(sum(vals) / len(vals) if vals else None)

    autocorrs_avg = {k: autocorr_lag(avg_dem, k) for k in LAGS}
    autocorrs_perK = {K: {k: autocorr_lag(dem[K], k) for k in LAGS}
                      for K in ACTIVE_STRIKES}

    fwd_perK, fwd_overall = forward_resid_pnl_buckets(residuals, z, HORIZONS)
    cluster = same_sign_clustering(z)

    res_stdev_perK = {K: stdev(residuals[K]) for K in ACTIVE_STRIKES}

    return {
        "regime": regime,
        "n_ticks": n,
        "residual_stdev_perK": res_stdev_perK,
        "autocorr_avg_dem": {k: {"corr": v[0], "n": v[1]}
                             for k, v in autocorrs_avg.items()},
        "autocorr_perK": {K: {k: {"corr": v[0], "n": v[1]}
                              for k, v in d.items()}
                          for K, d in autocorrs_perK.items()},
        "forward_pnl_perK": fwd_perK,
        "forward_pnl_overall": fwd_overall,
        "same_sign_clustering": cluster,
    }


def main():
    regimes = [
        {"kind": "pertick", "label": "pertick"},
        {"kind": "ema", "N": 20, "label": "ema-20"},
        {"kind": "ema", "N": 50, "label": "ema-50"},
        {"kind": "ema", "N": 100, "label": "ema-100"},
        {"kind": "refit_every", "N": 20, "label": "refit-20"},
        {"kind": "refit_every", "N": 50, "label": "refit-50"},
        {"kind": "refit_every", "N": 100, "label": "refit-100"},
    ]

    all_results = {}
    for day in [0, 1, 2]:
        print(f"\n=== Day {day} — loading ===")
        ts_data = load_day(day)
        print(f"  loaded {len(ts_data)} ticks")
        all_results[day] = {}
        for regime in regimes:
            label = regime["label"]
            r = {k: v for k, v in regime.items() if k != "label"}
            print(f"  regime: {label}")
            res = run_regime(day, ts_data, r)
            all_results[day][label] = res

    out_path = CACHE_DIR / "p3_10a_metrics.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=1, default=str)
    print(f"\nWrote {out_path}")

    # ---- Summary tables ----
    print("\n" + "=" * 78)
    print("SUMMARY: residual stdev (avg across strikes), per regime per day")
    print("=" * 78)
    print(f"{'regime':<14}" + "".join(f"{'D'+str(d):>10}" for d in [0, 1, 2]))
    for regime in regimes:
        label = regime["label"]
        row = [label]
        for d in [0, 1, 2]:
            sds = list(all_results[d][label]["residual_stdev_perK"].values())
            sds = [x for x in sds if x is not None]
            avg = sum(sds) / len(sds) if sds else float("nan")
            row.append(f"{avg:>10.3f}")
        print(f"{row[0]:<14}" + "".join(row[1:]))

    print("\n" + "=" * 78)
    print("SUMMARY: avg-dem autocorr at lag k (3-day avg), per regime")
    print("=" * 78)
    header = f"{'regime':<14}" + "".join(f"{'k='+str(k):>10}" for k in LAGS)
    print(header)
    for regime in regimes:
        label = regime["label"]
        row = [label]
        for k in LAGS:
            vals = []
            for d in [0, 1, 2]:
                v = all_results[d][label]["autocorr_avg_dem"][k]["corr"]
                if v is not None:
                    vals.append(v)
            avg = sum(vals) / len(vals) if vals else float("nan")
            row.append(f"{avg:>10.4f}")
        print(f"{row[0]:<14}" + "".join(row[1:]))

    print("\n" + "=" * 78)
    print("SUMMARY: forward-resid-PnL per-trade mean by |z| bucket, h=20")
    print("(overall pooled across active strikes; positive => signal works)")
    print("=" * 78)
    bucket_labels = list(all_results[0][regimes[0]["label"]]["forward_pnl_overall"].keys())
    header = f"{'regime':<14}" + "".join(f"{bk:>10}" for bk in bucket_labels)
    print(header)
    for regime in regimes:
        label = regime["label"]
        row = [label]
        for bk in bucket_labels:
            ns = []
            sums = []
            for d in [0, 1, 2]:
                stats = all_results[d][label]["forward_pnl_overall"][bk][20]
                if stats["n"] > 0:
                    ns.append(stats["n"])
                    sums.append(stats["sum"])
            if ns:
                row.append(f"{sum(sums)/sum(ns):>10.3f}")
            else:
                row.append(f"{'-':>10}")
        print(f"{row[0]:<14}" + "".join(row[1:]))

    print("\n" + "=" * 78)
    print("SUMMARY: forward-resid-PnL per-trade mean by |z| bucket, h=200")
    print("=" * 78)
    print(header)
    for regime in regimes:
        label = regime["label"]
        row = [label]
        for bk in bucket_labels:
            ns = []
            sums = []
            for d in [0, 1, 2]:
                stats = all_results[d][label]["forward_pnl_overall"][bk][200]
                if stats["n"] > 0:
                    ns.append(stats["n"])
                    sums.append(stats["sum"])
            if ns:
                row.append(f"{sum(sums)/sum(ns):>10.3f}")
            else:
                row.append(f"{'-':>10}")
        print(f"{row[0]:<14}" + "".join(row[1:]))

    print("\n" + "=" * 78)
    print("SUMMARY: same-sign clustering for |z|>2.0 events (window 5)")
    print("(fraction of next 5 ticks with same sign as entry z)")
    print("=" * 78)
    print(f"{'regime':<14}{'D0_frac':>10}{'D1_frac':>10}{'D2_frac':>10}{'agg_n':>10}")
    for regime in regimes:
        label = regime["label"]
        row = [label]
        ns = 0
        for d in [0, 1, 2]:
            v = all_results[d][label]["same_sign_clustering"]["__overall__"]
            ns += v["n_events"] or 0
            f = v["mean_same_sign_frac"]
            row.append(f"{f:>10.3f}" if f is not None else f"{'-':>10}")
        row.append(f"{ns:>10d}")
        print(f"{row[0]:<14}" + "".join(row[1:]))

    # ---- GATE ----
    print("\n" + "=" * 78)
    print("GATE EVALUATION")
    print("=" * 78)

    def gate_eval():
        # Gate A: at least one regime has avg-dem autocorr at some lag with
        # corr < -0.05 (3-day average).
        pass_A = False
        best_A = ("none", None, 0.0)
        for regime in regimes:
            label = regime["label"]
            for k in LAGS:
                vals = []
                for d in [0, 1, 2]:
                    v = all_results[d][label]["autocorr_avg_dem"][k]["corr"]
                    if v is not None:
                        vals.append(v)
                if not vals:
                    continue
                avg = sum(vals) / len(vals)
                if avg < best_A[2]:
                    best_A = (label, k, avg)
                if avg < -0.05:
                    pass_A = True

        # Gate B: at least one regime has overall forward-PnL means
        # monotonic non-decreasing across |z| buckets above 1.0, at h=20
        # AND h=200, AND positive in the top bucket. We aggregate
        # buckets across 3 days.
        pass_B = False
        best_B = "none"
        for regime in regimes:
            label = regime["label"]
            for h in [20, 200]:
                bucket_means = []
                for bk in bucket_labels:
                    if float(bk.split("-")[0].rstrip("+")) < 1.0:
                        continue
                    ns = 0
                    sm = 0.0
                    for d in [0, 1, 2]:
                        st = all_results[d][label]["forward_pnl_overall"][bk][h]
                        if st["n"] > 0:
                            ns += st["n"]
                            sm += st["sum"]
                    bucket_means.append(sm / ns if ns > 0 else None)
                vs = [v for v in bucket_means if v is not None]
                if len(vs) < 3:
                    continue
                # check monotonic non-decreasing
                mono = all(vs[i] <= vs[i + 1] + 1e-9 for i in range(len(vs) - 1))
                if mono and vs[-1] > 0:
                    pass_B = True
                    best_B = f"{label} (h={h})"
                    break
            if pass_B:
                break

        return pass_A, best_A, pass_B, best_B

    pA, bA, pB, bB = gate_eval()
    print(f"Gate A — autocorr < -0.05: {'PASS' if pA else 'FAIL'} "
          f"(best: regime={bA[0]} lag={bA[1]} corr={bA[2]:.4f})")
    print(f"Gate B — fwd-PnL monotonic + positive top: "
          f"{'PASS' if pB else 'FAIL'} (best: {bB})")
    overall = pA and pB
    print(f"\nOVERALL GATE: {'PASS' if overall else 'FAIL'}")
    if not overall:
        print("Per Sam: surface verdict, do NOT auto-pivot.")


if __name__ == "__main__":
    main()
