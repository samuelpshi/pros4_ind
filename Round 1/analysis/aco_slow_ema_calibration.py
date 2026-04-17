"""
aco_slow_ema_calibration.py — Pass 6.1 calibration of ACO slow-EMA half-life.

Goal: characterize the slow-oscillation component found in Pass 2 EDA
(half-period 1000-2000 ts; lag-2000 level autocorr = -0.340) and narrow
the plausible EMA half-life grid for Pass 6.5's sweep.

Inputs:
  Round 1/r1_data_capsule/prices_round_1_day_{-2,-1,0}.csv

Outputs (all under Round 1/analysis/):
  plots/acf_aco_day{-2,-1,0}.png               (raw ACF 0..3000 lag)
  plots/acf_aco_day{-2,-1,0}_filtered.png      (ACF after fast-component removal)
  plots/spectrum_aco_day{-2,-1,0}.png          (periodogram with slow peak marked)
  plots/slow_ema_tracking_day{-2,-1,0}.png     (mid + slow EMA at median candidate hl)
  aco_slow_ema_calibration_results.json        (all numbers)

Does NOT: touch trader code, run backtests, recommend a single half-life.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import acf

DATA_DIR = "/Users/samuelshi/IMC-Prosperity-2026-personal/Round 1/r1_data_capsule"
ANALYSIS_DIR = "/Users/samuelshi/IMC-Prosperity-2026-personal/Round 1/analysis"
PLOTS_DIR = os.path.join(ANALYSIS_DIR, "plots")
os.makedirs(PLOTS_DIR, exist_ok=True)

DAYS = [-2, -1, 0]
MAX_LAG = 3000
ADVERSE_VOLUME = 15  # matches v9 trader (ACO_ADVERSE_VOLUME)
PRODUCT = "ASH_COATED_OSMIUM"


# ---------------------------------------------------------------------------
# 1. Load + build mmbot mid
# ---------------------------------------------------------------------------
def load_day(day: int) -> pd.DataFrame:
    """Return cleaned ACO price rows for one day, sorted by timestamp."""
    p = pd.read_csv(f"{DATA_DIR}/prices_round_1_day_{day}.csv", sep=";")
    p = p[p["product"] == PRODUCT].copy()
    p = p[p["mid_price"] != 0]
    p = p.dropna(subset=["bid_price_1", "ask_price_1"]).copy()
    p = p.sort_values("timestamp").reset_index(drop=True)
    return p


def mmbot_mid_row(row, adverse: int, prev: float) -> float:
    """Filter book to quotes with volume >= adverse on each side; take midpoint.
    Fallback to prev when filtered book is empty on either side.
    Mirrors trader-v9-r1-aco-only.py :: aco_mmbot_mid.
    """
    bids = []
    asks = []
    for lvl in (1, 2, 3):
        bp = row.get(f"bid_price_{lvl}")
        bv = row.get(f"bid_volume_{lvl}")
        ap = row.get(f"ask_price_{lvl}")
        av = row.get(f"ask_volume_{lvl}")
        if pd.notna(bp) and pd.notna(bv) and bv >= adverse:
            bids.append(bp)
        if pd.notna(ap) and pd.notna(av) and abs(av) >= adverse:
            asks.append(ap)
    if not bids or not asks:
        return prev
    return (max(bids) + min(asks)) / 2.0


def build_series(day: int) -> pd.DataFrame:
    df = load_day(day)
    # raw mid (already in file as mid_price)
    raw_mid = df["mid_price"].to_numpy(dtype=float)
    # build mmbot mid with running fallback
    mm = np.empty(len(df), dtype=float)
    prev = float(raw_mid[0])  # seed with raw mid
    for i, (_, row) in enumerate(df.iterrows()):
        v = mmbot_mid_row(row, ADVERSE_VOLUME, prev)
        mm[i] = v
        prev = v
    df["mmbot_mid"] = mm
    return df[["timestamp", "mid_price", "mmbot_mid"]].copy()


# ---------------------------------------------------------------------------
# 2. ACF helpers
# ---------------------------------------------------------------------------
def compute_acf(x: np.ndarray, nlags: int = MAX_LAG) -> np.ndarray:
    """statsmodels acf, up to and including nlags; returns array of length nlags+1."""
    return acf(x, nlags=nlags, fft=True, missing="drop")


def fast_component_filter(x: np.ndarray, window: int = 40) -> np.ndarray:
    """Centered moving average smoother to suppress the bid-ask-bounce fast component.
    Window ~= 5 * fast OU half-life (8.4 ts) so the slow structure is preserved."""
    s = pd.Series(x).rolling(window=window, min_periods=1, center=True).mean()
    return s.to_numpy()


# ---------------------------------------------------------------------------
# 3. Method A — ACF zero-crossing / argmin for half-period
# ---------------------------------------------------------------------------
def half_period_acf(r: np.ndarray, min_lag: int = 100) -> dict:
    """Look for slow structure in ACF beyond min_lag.
    Returns:
      zero_cross_lag : first lag >= min_lag where ACF crosses from pos to neg
      argmin_lag     : lag of the most negative ACF value in [min_lag, MAX_LAG]
      acf_min_value  : ACF at argmin_lag
      half_period    : argmin_lag (since ACF trough of a sinusoid is at T/2)
    """
    # scan for zero crossing (pos -> neg) after min_lag
    zc = None
    for lag in range(min_lag, len(r) - 1):
        if r[lag] > 0 and r[lag + 1] <= 0:
            # linear interp
            f = r[lag] / (r[lag] - r[lag + 1])
            zc = lag + f
            break
    # arg-min in [min_lag, end]
    idx_min = int(np.argmin(r[min_lag:]) + min_lag)
    return {
        "zero_cross_lag": zc,
        "argmin_lag": idx_min,
        "acf_min_value": float(r[idx_min]),
        "half_period": idx_min,
    }


# ---------------------------------------------------------------------------
# 4. Method B — spectral peak
# ---------------------------------------------------------------------------
def spectral_half_period(
    x: np.ndarray,
    min_period: int = 400,
    max_period: int = 6000,
) -> dict:
    """Welch-style periodogram on the demeaned series; return dominant period in
    [min_period, max_period]. half_period = period / 2.
    """
    y = x - np.mean(x)
    # zero-pad to next power of 2 for cleaner freq grid
    n = len(y)
    fft = np.fft.rfft(y)
    power = np.abs(fft) ** 2
    freqs = np.fft.rfftfreq(n, d=1.0)  # cycles per timestep unit
    periods = np.where(freqs > 0, 1.0 / np.maximum(freqs, 1e-12), np.inf)
    mask = (periods >= min_period) & (periods <= max_period)
    if not np.any(mask):
        return {"period": None, "half_period": None, "power": None}
    idx_rel = int(np.argmax(power[mask]))
    # map back to absolute index
    abs_idxs = np.where(mask)[0]
    idx = abs_idxs[idx_rel]
    period = float(periods[idx])
    return {
        "period": period,
        "half_period": period / 2.0,
        "power": float(power[idx]),
        "freqs_all": freqs,
        "power_all": power,
        "mask": mask,
    }


# ---------------------------------------------------------------------------
# 5. EMA helpers
# ---------------------------------------------------------------------------
def ema_half_life_range(half_period: float) -> tuple[float, float]:
    """Per task spec: EMA half-life in [H/pi, H/2]."""
    return (half_period / np.pi, half_period / 2.0)


def ema_from_half_life(x: np.ndarray, hl: float) -> np.ndarray:
    """Standard RM-EMA: alpha = 1 - 2**(-1/hl)."""
    alpha = 1.0 - 2.0 ** (-1.0 / hl)
    out = np.empty_like(x, dtype=float)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
    return out


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------
def main():
    all_results: dict = {"days": {}}

    # Load all days first so we can compare
    day_series: dict[int, pd.DataFrame] = {}
    for d in DAYS:
        day_series[d] = build_series(d)
        s = day_series[d]
        print(
            f"day {d}: n={len(s)}  raw_mid mean={s['mid_price'].mean():.2f}  "
            f"mmbot mean={s['mmbot_mid'].mean():.2f}  "
            f"raw vs mmbot diff std={np.std(s['mid_price']-s['mmbot_mid']):.3f}"
        )

    # Choose price series: mmbot_mid (consistent with v9's fast-FV source).
    # Compare long-lag stability to raw mid as a check before locking in.
    series_choice_info = {}
    for d in DAYS:
        s = day_series[d]
        raw = s["mid_price"].to_numpy(dtype=float)
        mm = s["mmbot_mid"].to_numpy(dtype=float)
        # compare ACF at lag 2000 and stddev of increments
        acf_raw_2000 = float(compute_acf(raw, 2000)[2000])
        acf_mm_2000 = float(compute_acf(mm, 2000)[2000])
        series_choice_info[d] = {
            "raw_acf_lag2000": acf_raw_2000,
            "mmbot_acf_lag2000": acf_mm_2000,
            "raw_inc_std": float(np.std(np.diff(raw))),
            "mmbot_inc_std": float(np.std(np.diff(mm))),
        }
    all_results["series_choice_comparison"] = series_choice_info
    print("series comparison:", json.dumps(series_choice_info, indent=2))

    # Lock choice: mmbot_mid
    price_field = "mmbot_mid"
    all_results["price_series_used"] = price_field

    # Per-day analysis
    per_day = {}
    for d in DAYS:
        s = day_series[d]
        x = s[price_field].to_numpy(dtype=float)

        # Raw ACF (0..MAX_LAG)
        r_raw = compute_acf(x, MAX_LAG)

        # Filtered ACF: smooth fast bounce with 40-ts centered MA (~5 * fast OU hl)
        x_filt = fast_component_filter(x, window=40)
        r_filt = compute_acf(x_filt, MAX_LAG)

        # Method A: on the filtered series (fast bounce removed) for cleaner zero cross
        meth_a = half_period_acf(r_filt, min_lag=100)
        # Method B: spectral on raw demeaned series
        spec = spectral_half_period(x, min_period=400, max_period=6000)

        # EMA half-life ranges
        hp_a = meth_a["half_period"]
        hp_b = spec["half_period"]
        hl_a = ema_half_life_range(hp_a) if hp_a else (None, None)
        hl_b = ema_half_life_range(hp_b) if hp_b else (None, None)

        # Agreement between methods
        if hp_a and hp_b:
            disagree_pct = abs(hp_a - hp_b) / max(hp_a, hp_b)
        else:
            disagree_pct = None

        # Signal magnitude check at median candidate half-life
        # Use midpoint of union of both method ranges as the median candidate
        candidates = [v for v in (hl_a[0], hl_a[1], hl_b[0], hl_b[1]) if v]
        if candidates:
            median_hl = float(np.median(candidates))
        else:
            median_hl = 500.0
        ema_slow = ema_from_half_life(x, median_hl)
        resid = x - ema_slow
        resid_std = float(np.std(resid))

        per_day[d] = {
            "n_rows": int(len(x)),
            "method_a_acf": {
                "zero_cross_lag": meth_a["zero_cross_lag"],
                "argmin_lag": meth_a["argmin_lag"],
                "acf_min_value": meth_a["acf_min_value"],
                "half_period": float(meth_a["half_period"]),
            },
            "method_b_spectral": {
                "period": spec["period"],
                "half_period": spec["half_period"],
            },
            "methods_disagreement_pct": disagree_pct,
            "ema_half_life_range_method_a": hl_a,
            "ema_half_life_range_method_b": hl_b,
            "median_candidate_hl": median_hl,
            "signal_magnitude_stddev": resid_std,
            "raw_acf_at_lags": {
                "lag_1000": float(r_raw[1000]),
                "lag_1500": float(r_raw[1500]),
                "lag_2000": float(r_raw[2000]),
                "lag_2500": float(r_raw[2500]),
                "lag_3000": float(r_raw[3000]),
            },
        }

        # ---- Plots ----
        # ACF raw
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.plot(np.arange(MAX_LAG + 1), r_raw, lw=0.8, label="raw ACF")
        ax.axhline(0, color="k", lw=0.5)
        ax.axvline(meth_a["argmin_lag"], color="red", lw=0.8, ls="--",
                   label=f"ACF argmin lag={meth_a['argmin_lag']}")
        if spec["half_period"]:
            ax.axvline(spec["half_period"], color="green", lw=0.8, ls=":",
                       label=f"spectral T/2={spec['half_period']:.0f}")
        ax.set_title(f"ACO mmbot-mid ACF, day {d}")
        ax.set_xlabel("lag (timesteps)")
        ax.set_ylabel("autocorrelation")
        ax.legend(loc="upper right", fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS_DIR, f"acf_aco_day{d}.png"), dpi=100)
        plt.close(fig)

        # ACF filtered (fast component suppressed)
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.plot(np.arange(MAX_LAG + 1), r_filt, lw=0.8, color="C1",
                label="ACF of 40-ts smoothed series")
        ax.axhline(0, color="k", lw=0.5)
        ax.axvline(meth_a["argmin_lag"], color="red", lw=0.8, ls="--",
                   label=f"argmin lag={meth_a['argmin_lag']}")
        if meth_a["zero_cross_lag"]:
            ax.axvline(meth_a["zero_cross_lag"], color="blue", lw=0.8, ls="--",
                       label=f"zero cross={meth_a['zero_cross_lag']:.0f}")
        ax.set_title(f"ACO mmbot-mid (fast-component-filtered) ACF, day {d}")
        ax.set_xlabel("lag (timesteps)")
        ax.set_ylabel("autocorrelation")
        ax.legend(loc="upper right", fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS_DIR, f"acf_aco_day{d}_filtered.png"), dpi=100)
        plt.close(fig)

        # Spectrum
        fig, ax = plt.subplots(figsize=(9, 4))
        freqs = spec["freqs_all"]
        power = spec["power_all"]
        mask = spec["mask"]
        # plot only the range we searched over (log-log periodogram)
        ax.loglog(1.0 / np.maximum(freqs[1:], 1e-12), power[1:], lw=0.6)
        if spec["period"]:
            ax.axvline(spec["period"], color="green", lw=1.0, ls="--",
                       label=f"peak period={spec['period']:.0f} ts  →  T/2={spec['period']/2:.0f}")
        ax.axvspan(400, 6000, color="gray", alpha=0.1, label="search window [400, 6000]")
        ax.set_xlabel("period (timesteps)")
        ax.set_ylabel("power")
        ax.set_title(f"ACO mmbot-mid periodogram, day {d}")
        ax.legend(loc="upper right", fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS_DIR, f"spectrum_aco_day{d}.png"), dpi=100)
        plt.close(fig)

        # Slow EMA tracking
        fig, ax = plt.subplots(figsize=(11, 4))
        ax.plot(x, lw=0.5, label=f"{price_field}", color="C0")
        ax.plot(ema_slow, lw=1.0, label=f"slow EMA hl={median_hl:.0f}", color="C3")
        ax.set_title(
            f"ACO {price_field} with slow EMA, day {d}   "
            f"resid std={resid_std:.2f}"
        )
        ax.set_xlabel("tick index")
        ax.set_ylabel("price (XIRECS)")
        ax.legend(loc="upper right", fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS_DIR, f"slow_ema_tracking_day{d}.png"), dpi=100)
        plt.close(fig)

    all_results["days"] = per_day

    # Cross-day stability
    hp_a_all = [per_day[d]["method_a_acf"]["half_period"] for d in DAYS]
    hp_b_all = [per_day[d]["method_b_spectral"]["half_period"] for d in DAYS if per_day[d]["method_b_spectral"]["half_period"]]
    hl_lows = []
    hl_highs = []
    for d in DAYS:
        for rng in (per_day[d]["ema_half_life_range_method_a"],
                    per_day[d]["ema_half_life_range_method_b"]):
            if rng[0] is not None:
                hl_lows.append(rng[0])
                hl_highs.append(rng[1])

    stability = {
        "per_day_half_period_method_a": hp_a_all,
        "per_day_half_period_method_b": hp_b_all,
        "method_a_cross_day_spread_pct":
            float((max(hp_a_all) - min(hp_a_all)) / max(hp_a_all)) if hp_a_all else None,
        "method_b_cross_day_spread_pct":
            float((max(hp_b_all) - min(hp_b_all)) / max(hp_b_all)) if len(hp_b_all) > 1 else None,
        "union_hl_low": float(min(hl_lows)) if hl_lows else None,
        "union_hl_high": float(max(hl_highs)) if hl_highs else None,
    }
    all_results["cross_day"] = stability

    # Sweep grid: 5 log-spaced points over union range, rounded to nearest 25
    if hl_lows and hl_highs:
        lo = max(100.0, min(hl_lows))
        hi = min(2000.0, max(hl_highs))
        # clamp to plausible scale
        grid_log = np.geomspace(lo, hi, num=5)
        grid_rounded = [int(round(g / 25.0) * 25) for g in grid_log]
        # dedupe
        seen = []
        for g in grid_rounded:
            if g not in seen:
                seen.append(g)
        sweep_grid = seen
    else:
        sweep_grid = []
    all_results["recommended_sweep_grid"] = sweep_grid

    # Signal magnitude summary
    resid_stds = [per_day[d]["signal_magnitude_stddev"] for d in DAYS]
    all_results["signal_magnitude_summary"] = {
        "per_day_resid_std": resid_stds,
        "min": float(min(resid_stds)),
        "median": float(np.median(resid_stds)),
    }

    # Serialize (drop numpy arrays from spectral)
    def _json_sanitize(o):
        if isinstance(o, np.ndarray):
            return None  # skip arrays
        if isinstance(o, (np.floating, np.integer)):
            return float(o)
        raise TypeError(str(type(o)))

    # Strip arrays inside per_day? (we didn't save them) — just strip top-level spec arrays if any
    out_path = os.path.join(ANALYSIS_DIR, "aco_slow_ema_calibration_results.json")
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2, default=_json_sanitize)
    print(f"results → {out_path}")
    print(f"sweep grid: {sweep_grid}")
    print(f"resid stds: {resid_stds}")


if __name__ == "__main__":
    main()
