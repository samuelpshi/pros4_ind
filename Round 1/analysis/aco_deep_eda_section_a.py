"""
ACO Deep EDA — Section A: Price Process Per Day
Generates all stats and plots for Section A of aco_deep_eda.ipynb.
Run from any directory; uses absolute paths.
"""
import os, json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from statsmodels.tsa.stattools import adfuller, acf
import warnings
warnings.filterwarnings("ignore")

# ── paths ──────────────────────────────────────────────────────────────────────
BASE = "/Users/samuelshi/IMC-Prosperity-2026-personal/Round 1"
DATA = os.path.join(BASE, "r1_data_capsule")
PLOT_DIR = os.path.join(BASE, "analysis", "plots", "aco_deep")
os.makedirs(PLOT_DIR, exist_ok=True)

DAY_FILES = {
    -2: os.path.join(DATA, "prices_round_1_day_-2.csv"),
    -1: os.path.join(DATA, "prices_round_1_day_-1.csv"),
     0: os.path.join(DATA, "prices_round_1_day_0.csv"),
}

ACO_ADVERSE_VOLUME = 15   # matches trader-v9

# ── helpers ────────────────────────────────────────────────────────────────────
def load_aco(path):
    df = pd.read_csv(path, sep=";")
    df = df[df["product"] == "ASH_COATED_OSMIUM"].copy()
    # Drop rows missing both sides of order book
    df = df.dropna(subset=["bid_price_1", "ask_price_1"])
    df = df[df["mid_price"] != 0]
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df

def compute_mmbot_mid(df):
    """
    mmbot_mid = mid of best filtered bid / ask where |vol| >= ACO_ADVERSE_VOLUME.
    Falls back to previous value when one side is missing.
    """
    mmbot = np.full(len(df), np.nan)
    prev = np.nan
    BID_COLS = [("bid_price_1","bid_volume_1"), ("bid_price_2","bid_volume_2"), ("bid_price_3","bid_volume_3")]
    ASK_COLS = [("ask_price_1","ask_volume_1"), ("ask_price_2","ask_volume_2"), ("ask_price_3","ask_volume_3")]
    for i, row in enumerate(df.itertuples(index=False)):
        fb = None
        for pc, vc in BID_COLS:
            p, v = getattr(row, pc, np.nan), getattr(row, vc, np.nan)
            if pd.notna(p) and pd.notna(v) and abs(v) >= ACO_ADVERSE_VOLUME:
                fb = p; break
        fa = None
        for pc, vc in ASK_COLS:
            p, v = getattr(row, pc, np.nan), getattr(row, vc, np.nan)
            if pd.notna(p) and pd.notna(v) and abs(v) >= ACO_ADVERSE_VOLUME:
                fa = p; break
        if fb is not None and fa is not None:
            val = (fb + fa) / 2.0
        else:
            val = prev
        mmbot[i] = val
        prev = val
    return mmbot

def ou_halflife(returns):
    """
    AR(1) fit: r_t = a + b*r_{t-1} + eps
    Half-life = -ln(2)/ln(|b|) if |b| < 1
    Returns (phi, halflife_ticks) where phi = b
    """
    r = np.array(returns)
    r = r[~np.isnan(r)]
    y = r[1:]
    x = r[:-1]
    X = np.column_stack([np.ones(len(x)), x])
    coef, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    a, b = coef
    ab = abs(b)
    if ab < 1.0 and ab > 0:
        hl = -np.log(2) / np.log(ab)
    else:
        hl = np.inf
    return b, hl

def variance_ratio(returns, k):
    """
    VR(k) = Var(k-period returns) / (k * Var(1-period returns))
    """
    r = np.array(returns)
    r = r[~np.isnan(r)]
    var1 = np.var(r, ddof=1)
    if var1 == 0:
        return np.nan
    # k-period returns
    rk = r[k-1:] - r[:len(r)-k+1] if k == 1 else np.array([r[i:i+k].sum() for i in range(len(r)-k+1)])
    # More efficient: cumulative sum
    cumr = np.cumsum(r)
    rk2 = cumr[k:] - cumr[:-k] if k <= len(cumr) else np.array([])
    if len(rk2) < 10:
        return np.nan
    vark = np.var(rk2, ddof=1)
    return vark / (k * var1)

# ── main loop ──────────────────────────────────────────────────────────────────
results = {}
acf_store = {}
rolling_store_100 = {}
rolling_store_1000 = {}

for day, path in sorted(DAY_FILES.items()):
    print(f"\n=== Day {day} ===")
    df = load_aco(path)
    print(f"  Rows after cleaning: {len(df)}")

    # compute mmbot_mid
    mm = compute_mmbot_mid(df)
    df["mmbot_mid"] = mm
    df = df.dropna(subset=["mmbot_mid"])
    print(f"  Rows with valid mmbot_mid: {len(df)}")

    series = df["mmbot_mid"].values
    rets = np.diff(series)  # tick-by-tick returns

    # 1. ADF test
    adf_res = adfuller(series, maxlag=20, regression="c", autolag="AIC")
    adf_stat, adf_p = adf_res[0], adf_res[1]
    print(f"  ADF stat={adf_stat:.4f}, p={adf_p:.4f}")

    # 2. ACF of returns, lags 1..3000
    nlags = min(3000, len(rets) - 1)
    acf_vals = acf(rets, nlags=nlags, fft=True, alpha=None)
    acf_store[day] = acf_vals[1:]   # skip lag 0 (=1.0)

    # 3. OU half-life via AR(1)
    phi, hl = ou_halflife(rets)
    print(f"  OU phi={phi:.6f}, halflife={hl:.1f} ticks")

    # 4. Variance ratio at k in {2,5,10,50,200}
    vr = {}
    for k in [2, 5, 10, 50, 200]:
        vr[k] = variance_ratio(rets, k)
    print(f"  VR: {vr}")

    # 5. Rolling stddev of returns at windows 100, 1000
    rets_s = pd.Series(rets)
    rolling_store_100[day] = rets_s.rolling(100).std().values
    rolling_store_1000[day] = rets_s.rolling(1000).std().values

    results[day] = {
        "n_rows": len(df),
        "adf_stat": adf_stat,
        "adf_p": adf_p,
        "ou_phi": phi,
        "ou_halflife_ticks": hl,
        "vr2": vr[2],
        "vr5": vr[5],
        "vr10": vr[10],
        "vr50": vr[50],
        "vr200": vr[200],
        "ret_std": float(np.std(rets)),
    }

# ── Plot 1: ACF per day overlaid ───────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(14, 5))
colors = {-2: "steelblue", -1: "darkorange", 0: "seagreen"}
lag_axis = np.arange(1, 3001)
for day in sorted(acf_store.keys()):
    vals = acf_store[day]
    n = min(len(vals), 3000)
    ax.plot(lag_axis[:n], vals[:n], color=colors[day], alpha=0.8, lw=0.8, label=f"Day {day}")
ax.axhline(0, color="black", lw=0.5)
# Approximate 95% CI band (±1.96/sqrt(N))
for day in sorted(results.keys()):
    N = results[day]["n_rows"]
    ci = 1.96 / np.sqrt(N)
ax.axhline(ci, color="gray", ls="--", lw=0.7, label=f"±95% CI (~{ci:.3f})")
ax.axhline(-ci, color="gray", ls="--", lw=0.7)
ax.set_xlabel("Lag (ticks)")
ax.set_ylabel("ACF of mmbot_mid returns")
ax.set_title("ACO mmbot_mid return ACF — per day (lags 1–3000)")
ax.legend()
ax.set_xlim(0, 3000)
plt.tight_layout()
plt.savefig(os.path.join(PLOT_DIR, "acf_per_day.png"), dpi=150)
plt.close()
print("\nSaved acf_per_day.png")

# ── Plot 2: Rolling stddev per day ────────────────────────────────────────────
fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=False)
for i, day in enumerate(sorted(results.keys())):
    ax = axes[i]
    n = len(rolling_store_100[day])
    ax.plot(range(n), rolling_store_100[day], color=colors[day], alpha=0.7, lw=0.6, label="window=100")
    ax.plot(range(len(rolling_store_1000[day])), rolling_store_1000[day], color=colors[day], lw=1.2, ls="--", label="window=1000")
    ax.set_title(f"Day {day} — rolling stddev of mmbot_mid returns")
    ax.set_ylabel("Stddev")
    ax.legend(fontsize=8)
plt.suptitle("ACO mmbot_mid return rolling volatility", y=1.01)
plt.tight_layout()
plt.savefig(os.path.join(PLOT_DIR, "vol_profile_per_day.png"), dpi=150)
plt.close()
print("Saved vol_profile_per_day.png")

# ── Plot 3: Variance ratio per day ────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 5))
ks = [2, 5, 10, 50, 200]
for day in sorted(results.keys()):
    vrs = [results[day][f"vr{k}"] for k in ks]
    ax.plot(ks, vrs, marker="o", color=colors[day], label=f"Day {day}")
ax.axhline(1.0, color="black", ls="--", lw=0.8, label="VR=1 (random walk)")
ax.set_xlabel("k (holding period, ticks)")
ax.set_ylabel("Variance Ratio VR(k)")
ax.set_title("ACO mmbot_mid Variance Ratio test — per day")
ax.set_xscale("log")
ax.legend()
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(PLOT_DIR, "variance_ratio_per_day.png"), dpi=150)
plt.close()
print("Saved variance_ratio_per_day.png")

# ── Dispersion table ──────────────────────────────────────────────────────────
stats_keys = ["adf_stat", "adf_p", "ou_phi", "ou_halflife_ticks", "vr2", "vr5", "vr10", "vr50", "vr200"]
disp = {}
for sk in stats_keys:
    vals = [results[d][sk] for d in sorted(results.keys()) if not (results[d][sk] == np.inf)]
    if len(vals) == 0:
        vals = [np.inf]*3
    mn, mx, me = min(vals), max(vals), np.mean(vals)
    cv = (mx - mn) / abs(me) if me != 0 else np.inf
    flag = "NOT STABLE" if cv > 0.30 else "stable"
    disp[sk] = {"min": mn, "max": mx, "mean": me, "cv": cv, "flag": flag}

print("\n=== Dispersion table ===")
print(f"{'Stat':<25} {'Min':>10} {'Max':>10} {'Mean':>10} {'CV':>8} {'Flag'}")
print("-"*75)
for sk, v in disp.items():
    print(f"{sk:<25} {v['min']:>10.4f} {v['max']:>10.4f} {v['mean']:>10.4f} {v['cv']:>8.3f}  {v['flag']}")

# ── Save JSON ──────────────────────────────────────────────────────────────────
def _ser(v):
    if isinstance(v, str): return v
    if v == np.inf or (isinstance(v, float) and np.isinf(v)): return "inf"
    return float(v)

out = {
    "per_day": {str(d): {k: _ser(v) for k, v in r.items()} for d, r in results.items()},
    "dispersion": {sk: {k: _ser(v) for k, v in vd.items()} for sk, vd in disp.items()},
}
json_path = os.path.join(BASE, "analysis", "aco_deep_eda_section_a_results.json")
with open(json_path, "w") as f:
    json.dump(out, f, indent=2)
print(f"\nResults saved to {json_path}")
print("Done.")
