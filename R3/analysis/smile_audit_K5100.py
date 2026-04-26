"""
Smile-fit audit: is K=5100's mid contaminating the per-tick smile fit?

Loads the 3-day round3 prices, inverts IV at each of the 6 strikes per tick,
fits a quadratic smile y = a*m^2 + b*m + c twice -- once with all 6 strikes,
once dropping K=5100 -- and compares:

  (a) R^2 distribution of the two fits.
  (b) Per-strike residual time-series (mean, stdev, abs-mean, autocorrelation
      lag-1, kurtosis-proxy via P95/P50 of |resid|) under each regime.
  (c) Smile coefficients (a, b, c) per tick under each regime, plus the
      shift in c (ATM IV) that dropping K=5100 induces.
  (d) Per-strike residual under regime-A scored against the realized
      next-tick mid move at each strike (does the residual that drives
      a trade actually predict mean reversion at K=5100 vs at K=5000/5300?).

Output: R3/analysis/smile_audit_K5100_results.json with all aggregates,
plus a short stdout summary for the agent log.

Run: python3 R3/analysis/smile_audit_K5100.py
"""

import json
import math
from pathlib import Path
from statistics import mean, median, pstdev

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "R3/r3_datacap"
OUT = REPO / "R3/analysis/smile_audit_K5100_results.json"

STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
DAY_TO_TTE_DAYS = {0: 8, 1: 7, 2: 6}


def Phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call_price(S, K, T, sigma):
    if T <= 0 or sigma <= 0 or S <= 0:
        return max(0.0, S - K)
    sqrtT = math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    return S * Phi(d1) - K * Phi(d2)


def solve_iv(price, S, K, T, lo=0.01, hi=3.0, tol=1e-5, max_iter=80):
    """Bisection IV. Returns None if not bracketable."""
    intrinsic = max(0.0, S - K)
    if price < intrinsic - 1e-6:
        return None
    f_lo = bs_call_price(S, K, T, lo) - price
    f_hi = bs_call_price(S, K, T, hi) - price
    if f_lo * f_hi > 0:
        return None
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = bs_call_price(S, K, T, mid) - price
        if abs(f_mid) < tol:
            return mid
        if f_lo * f_mid <= 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid
    return 0.5 * (lo + hi)


def fit_quadratic(ms, ys):
    """Returns (a, b, c, r2) for y = a*m^2 + b*m + c via normal equations."""
    n = len(ms)
    if n < 3:
        return None
    Sx0 = n
    Sx1 = sum(ms)
    Sx2 = sum(m * m for m in ms)
    Sx3 = sum(m ** 3 for m in ms)
    Sx4 = sum(m ** 4 for m in ms)
    Sy0 = sum(ys)
    Sy1 = sum(m * y for m, y in zip(ms, ys))
    Sy2 = sum(m * m * y for m, y in zip(ms, ys))
    # Solve: [[Sx4, Sx3, Sx2],[Sx3, Sx2, Sx1],[Sx2, Sx1, Sx0]] * [a,b,c] = [Sy2, Sy1, Sy0]
    M = [
        [Sx4, Sx3, Sx2, Sy2],
        [Sx3, Sx2, Sx1, Sy1],
        [Sx2, Sx1, Sx0, Sy0],
    ]
    # Gaussian elimination
    for i in range(3):
        # pivot
        piv = max(range(i, 3), key=lambda r: abs(M[r][i]))
        M[i], M[piv] = M[piv], M[i]
        if abs(M[i][i]) < 1e-12:
            return None
        for j in range(i + 1, 3):
            f = M[j][i] / M[i][i]
            for k in range(i, 4):
                M[j][k] -= f * M[i][k]
    c = M[2][3] / M[2][2]
    b = (M[1][3] - M[1][2] * c) / M[1][1]
    a = (M[0][3] - M[0][1] * b - M[0][2] * c) / M[0][0]
    y_mean = Sy0 / n
    ss_res = sum((y - (a * m * m + b * m + c)) ** 2 for m, y in zip(ms, ys))
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 1.0
    return a, b, c, r2


def load_day(day):
    """Returns list of dicts: {ts, S, mids: {K: mid}}."""
    f = DATA / f"prices_round_3_day_{day}.csv"
    rows_by_ts = {}
    with open(f) as fh:
        header = fh.readline().strip().split(";")
        idx = {h: i for i, h in enumerate(header)}
        for line in fh:
            cells = line.rstrip("\n").split(";")
            if len(cells) < len(header):
                continue
            try:
                ts = int(cells[idx["timestamp"]])
                product = cells[idx["product"]]
                mid_s = cells[idx["mid_price"]]
                if not mid_s:
                    continue
                mid = float(mid_s)
            except (KeyError, ValueError):
                continue
            ent = rows_by_ts.setdefault(ts, {"ts": ts, "S": None, "mids": {}})
            if product == "VELVETFRUIT_EXTRACT":
                ent["S"] = mid
            elif product.startswith("VEV_"):
                try:
                    K = int(product.split("_")[1])
                except ValueError:
                    continue
                if K in STRIKES:
                    ent["mids"][K] = mid
    rows = [rows_by_ts[t] for t in sorted(rows_by_ts) if rows_by_ts[t]["S"] is not None]
    return rows


def autocorr_lag1(xs):
    n = len(xs)
    if n < 3:
        return None
    mu = sum(xs) / n
    num = sum((xs[i] - mu) * (xs[i - 1] - mu) for i in range(1, n))
    den = sum((x - mu) ** 2 for x in xs)
    if den < 1e-12:
        return None
    return num / den


def percentile(sorted_xs, p):
    if not sorted_xs:
        return None
    k = (len(sorted_xs) - 1) * p
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return sorted_xs[lo]
    return sorted_xs[lo] + (sorted_xs[hi] - sorted_xs[lo]) * (k - lo)


def stats(xs):
    if not xs:
        return None
    s = sorted(xs)
    return {
        "n": len(xs),
        "mean": mean(xs),
        "stdev": pstdev(xs) if len(xs) > 1 else 0.0,
        "median": median(xs),
        "abs_mean": mean(abs(x) for x in xs),
        "p05": percentile(s, 0.05),
        "p50": percentile(s, 0.50),
        "p95": percentile(s, 0.95),
        "abs_p95": percentile(sorted(abs(x) for x in xs), 0.95),
        "abs_p50": percentile(sorted(abs(x) for x in xs), 0.50),
        "autocorr_lag1": autocorr_lag1(xs),
    }


def main():
    by_day = {}
    cross_day = {
        "r2_with5100": [],
        "r2_without5100": [],
        "a_with5100": [], "b_with5100": [], "c_with5100": [],
        "a_without5100": [], "b_without5100": [], "c_without5100": [],
        "delta_c": [],  # c(without) - c(with)
        "iv_at_5100_obs": [],   # observed IV at K=5100
        "iv_at_5100_pred_with": [],  # predicted by 6-strike fit
        "iv_at_5100_pred_without": [],  # predicted by 5-strike fit
    }
    per_strike_resid_with = {K: [] for K in STRIKES}
    per_strike_resid_without = {K: [] for K in STRIKES}

    for day in (0, 1, 2):
        tte_days = DAY_TO_TTE_DAYS[day]
        rows = load_day(day)
        n_ticks = 0
        n_full = 0
        for r in rows:
            ts = r["ts"]
            S = r["S"]
            mids = r["mids"]
            T = max((tte_days - ts / 1_000_000.0) / 365.0, 1e-6)
            ivs = {}
            ms = {}
            for K in STRIKES:
                if K not in mids:
                    continue
                m = math.log(K / S) / math.sqrt(T)
                iv = solve_iv(mids[K], S, K, T)
                if iv is None or iv <= 0:
                    continue
                ivs[K] = iv
                ms[K] = m
            if len(ivs) < 5:
                continue  # need at least 5 to fit both regimes
            n_ticks += 1
            # Fit with all available strikes
            fit_with = fit_quadratic([ms[K] for K in ivs], [ivs[K] for K in ivs])
            if fit_with is None:
                continue
            # Fit without 5100
            ks_wo = [K for K in ivs if K != 5100]
            if len(ks_wo) < 3:
                continue
            fit_wo = fit_quadratic([ms[K] for K in ks_wo], [ivs[K] for K in ks_wo])
            if fit_wo is None:
                continue
            n_full += 1
            a1, b1, c1, r2_1 = fit_with
            a2, b2, c2, r2_2 = fit_wo
            cross_day["r2_with5100"].append(r2_1)
            cross_day["r2_without5100"].append(r2_2)
            cross_day["a_with5100"].append(a1)
            cross_day["b_with5100"].append(b1)
            cross_day["c_with5100"].append(c1)
            cross_day["a_without5100"].append(a2)
            cross_day["b_without5100"].append(b2)
            cross_day["c_without5100"].append(c2)
            cross_day["delta_c"].append(c2 - c1)

            if 5100 in ivs:
                m51 = ms[5100]
                cross_day["iv_at_5100_obs"].append(ivs[5100])
                cross_day["iv_at_5100_pred_with"].append(a1 * m51 * m51 + b1 * m51 + c1)
                cross_day["iv_at_5100_pred_without"].append(a2 * m51 * m51 + b2 * m51 + c2)

            for K in STRIKES:
                if K not in ivs:
                    continue
                m = ms[K]
                # Residual = observed_iv - smile_fit_iv
                resid_with = ivs[K] - (a1 * m * m + b1 * m + c1)
                per_strike_resid_with[K].append(resid_with)
                resid_without = ivs[K] - (a2 * m * m + b2 * m + c2)
                per_strike_resid_without[K].append(resid_without)

        by_day[day] = {"n_ticks": n_ticks, "n_full": n_full}

    out = {
        "ticks_by_day": by_day,
        "ticks_total": sum(d["n_full"] for d in by_day.values()),
        "r2": {
            "with5100": stats(cross_day["r2_with5100"]),
            "without5100": stats(cross_day["r2_without5100"]),
            "delta": stats([
                a - b for a, b in zip(
                    cross_day["r2_without5100"], cross_day["r2_with5100"]
                )
            ]),
        },
        "smile_coeffs": {
            "with5100": {
                "a": stats(cross_day["a_with5100"]),
                "b": stats(cross_day["b_with5100"]),
                "c": stats(cross_day["c_with5100"]),
            },
            "without5100": {
                "a": stats(cross_day["a_without5100"]),
                "b": stats(cross_day["b_without5100"]),
                "c": stats(cross_day["c_without5100"]),
            },
            "delta_c": stats(cross_day["delta_c"]),
        },
        "iv_at_5100": {
            "obs": stats(cross_day["iv_at_5100_obs"]),
            "pred_with": stats(cross_day["iv_at_5100_pred_with"]),
            "pred_without": stats(cross_day["iv_at_5100_pred_without"]),
            "obs_minus_pred_with": stats([
                o - p for o, p in zip(
                    cross_day["iv_at_5100_obs"], cross_day["iv_at_5100_pred_with"]
                )
            ]),
            "obs_minus_pred_without": stats([
                o - p for o, p in zip(
                    cross_day["iv_at_5100_obs"], cross_day["iv_at_5100_pred_without"]
                )
            ]),
        },
        "per_strike_resid_with5100": {K: stats(per_strike_resid_with[K]) for K in STRIKES},
        "per_strike_resid_without5100": {K: stats(per_strike_resid_without[K]) for K in STRIKES},
    }

    with open(OUT, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"Wrote {OUT}")
    print(f"Ticks total (both fits valid): {out['ticks_total']}")

    print("\n=== R² distribution ===")
    print(f"  with-5100   mean={out['r2']['with5100']['mean']:.4f}  "
          f"p05={out['r2']['with5100']['p05']:.4f}  "
          f"p50={out['r2']['with5100']['p50']:.4f}  "
          f"p95={out['r2']['with5100']['p95']:.4f}")
    print(f"  without-5100 mean={out['r2']['without5100']['mean']:.4f}  "
          f"p05={out['r2']['without5100']['p05']:.4f}  "
          f"p50={out['r2']['without5100']['p50']:.4f}  "
          f"p95={out['r2']['without5100']['p95']:.4f}")
    print(f"  delta(without - with)  mean={out['r2']['delta']['mean']:+.5f}  "
          f"abs_mean={out['r2']['delta']['abs_mean']:.5f}")

    print("\n=== Smile coefficient c (ATM-base IV) ===")
    print(f"  with-5100   c: mean={out['smile_coeffs']['with5100']['c']['mean']:+.5f} "
          f"stdev={out['smile_coeffs']['with5100']['c']['stdev']:.5f}")
    print(f"  without-5100 c: mean={out['smile_coeffs']['without5100']['c']['mean']:+.5f} "
          f"stdev={out['smile_coeffs']['without5100']['c']['stdev']:.5f}")
    print(f"  delta_c: mean={out['smile_coeffs']['delta_c']['mean']:+.5f}  "
          f"stdev={out['smile_coeffs']['delta_c']['stdev']:.5f}")

    print("\n=== K=5100: observed IV vs smile prediction ===")
    if out['iv_at_5100']['obs']:
        print(f"  obs IV(5100):       mean={out['iv_at_5100']['obs']['mean']:+.5f} "
              f"stdev={out['iv_at_5100']['obs']['stdev']:.5f}")
        print(f"  pred (with-5100):   mean={out['iv_at_5100']['pred_with']['mean']:+.5f} "
              f"stdev={out['iv_at_5100']['pred_with']['stdev']:.5f}")
        print(f"  pred (without-5100): mean={out['iv_at_5100']['pred_without']['mean']:+.5f} "
              f"stdev={out['iv_at_5100']['pred_without']['stdev']:.5f}")
        print(f"  resid obs - pred(with):    "
              f"mean={out['iv_at_5100']['obs_minus_pred_with']['mean']:+.5f}  "
              f"abs_p95={out['iv_at_5100']['obs_minus_pred_with']['abs_p95']:.5f}  "
              f"AC1={out['iv_at_5100']['obs_minus_pred_with']['autocorr_lag1']}")
        print(f"  resid obs - pred(without): "
              f"mean={out['iv_at_5100']['obs_minus_pred_without']['mean']:+.5f}  "
              f"abs_p95={out['iv_at_5100']['obs_minus_pred_without']['abs_p95']:.5f}  "
              f"AC1={out['iv_at_5100']['obs_minus_pred_without']['autocorr_lag1']}")

    print("\n=== Per-strike residual stats (with-5100 fit) ===")
    print(f"{'K':>6} {'mean':>10} {'stdev':>10} {'abs_mean':>10} {'abs_p95':>10} {'AC1':>8}")
    for K in STRIKES:
        s = out['per_strike_resid_with5100'][K]
        if s:
            ac = s['autocorr_lag1']
            ac_s = f"{ac:+.3f}" if ac is not None else "  n/a"
            print(f"{K:>6} {s['mean']:>+10.5f} {s['stdev']:>10.5f} "
                  f"{s['abs_mean']:>10.5f} {s['abs_p95']:>10.5f} {ac_s:>8}")

    print("\n=== Per-strike residual stats (without-5100 fit) ===")
    print(f"{'K':>6} {'mean':>10} {'stdev':>10} {'abs_mean':>10} {'abs_p95':>10} {'AC1':>8}")
    for K in STRIKES:
        s = out['per_strike_resid_without5100'][K]
        if s:
            ac = s['autocorr_lag1']
            ac_s = f"{ac:+.3f}" if ac is not None else "  n/a"
            print(f"{K:>6} {s['mean']:>+10.5f} {s['stdev']:>10.5f} "
                  f"{s['abs_mean']:>10.5f} {s['abs_p95']:>10.5f} {ac_s:>8}")


if __name__ == "__main__":
    main()
