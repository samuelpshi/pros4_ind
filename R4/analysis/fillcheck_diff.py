"""
Diff own_trades between local Rust backtester log and IMC website log.
Both log files share schema: top-level JSON with 'tradeHistory' list of
{timestamp, buyer, seller, symbol, price, quantity, ...}.

Own trades are those where buyer == 'SUBMISSION' (BUY) or seller == 'SUBMISSION' (SELL).

Usage:
    python R4/analysis/fillcheck_diff.py <local_submission.log> <imc.log>
"""
import json
import sys
from collections import defaultdict
from pathlib import Path


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def own_trades(log: dict) -> list[dict]:
    out = []
    for t in log["tradeHistory"]:
        if t["buyer"] == "SUBMISSION":
            side = "BUY"
        elif t["seller"] == "SUBMISSION":
            side = "SELL"
        else:
            continue
        out.append(
            {
                "ts": int(t["timestamp"]),
                "side": side,
                "symbol": t["symbol"],
                "price": float(t["price"]),
                "qty": int(t["quantity"]),
            }
        )
    return out


def group(trades: list[dict]):
    """Group by (ts, symbol, side); each value is list of (price, qty) splits."""
    g = defaultdict(list)
    for t in trades:
        g[(t["ts"], t["symbol"], t["side"])].append((t["price"], t["qty"]))
    # Sort price/qty within each cell so split-fill order doesn't cause spurious diffs
    for k in g:
        g[k].sort()
    return g


def fmt_cell(cell):
    return ",".join(f"{p:g}@{q}" for p, q in cell) if cell else "(none)"


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    local_path, imc_path = sys.argv[1], sys.argv[2]

    local_log = load(local_path)
    imc_log = load(imc_path)

    local_trades = own_trades(local_log)
    imc_trades = own_trades(imc_log)

    if not imc_trades:
        print("WARNING: no SUBMISSION trades found in IMC log.")
        sys.exit(2)

    imc_max_ts = max(t["ts"] for t in imc_trades)
    imc_min_ts = min(t["ts"] for t in imc_trades)
    print(f"IMC trades:    {len(imc_trades)} (ts {imc_min_ts}..{imc_max_ts})")
    print(f"Local trades:  {len(local_trades)} total")

    # Clip local to IMC's ts window for apples-to-apples comparison
    local_clipped = [t for t in local_trades if t["ts"] <= imc_max_ts]
    print(f"Local clipped: {len(local_clipped)} (ts <= {imc_max_ts})")
    print()

    L = group(local_clipped)
    I = group(imc_trades)

    all_keys = sorted(set(L) | set(I))
    exact = 0
    mismatch = []
    only_local = []
    only_imc = []

    for k in all_keys:
        l = L.get(k)
        i = I.get(k)
        if l and not i:
            only_local.append((k, l))
        elif i and not l:
            only_imc.append((k, i))
        elif l == i:
            exact += 1
        else:
            mismatch.append((k, l, i))

    n = len(all_keys)
    print(f"=== summary ({n} unique (ts, sym, side) cells) ===")
    print(f"  exact match:    {exact:>6}  ({100*exact/n:.1f}%)")
    print(f"  price/qty diff: {len(mismatch):>6}")
    print(f"  only in local:  {len(only_local):>6}")
    print(f"  only in IMC:    {len(only_imc):>6}")
    print()

    def show(label, items, fmt):
        if not items:
            return
        print(f"--- first 10 {label} ---")
        for row in items[:10]:
            print(fmt(row))
        if len(items) > 10:
            print(f"  ... ({len(items) - 10} more)")
        print()

    show(
        "price/qty mismatches",
        mismatch,
        lambda r: f"  ts={r[0][0]:>6} {r[0][1]:<22} {r[0][2]:<4} local={fmt_cell(r[1])}  imc={fmt_cell(r[2])}",
    )
    show(
        "only-in-local cells",
        only_local,
        lambda r: f"  ts={r[0][0]:>6} {r[0][1]:<22} {r[0][2]:<4} local={fmt_cell(r[1])}",
    )
    show(
        "only-in-IMC cells",
        only_imc,
        lambda r: f"  ts={r[0][0]:>6} {r[0][1]:<22} {r[0][2]:<4} imc={fmt_cell(r[1])}",
    )

    # Aggregate fill stats per side
    def agg(trades):
        buy_qty = sum(t["qty"] for t in trades if t["side"] == "BUY")
        sell_qty = sum(t["qty"] for t in trades if t["side"] == "SELL")
        buy_n = sum(1 for t in trades if t["side"] == "BUY")
        sell_n = sum(1 for t in trades if t["side"] == "SELL")
        return buy_n, buy_qty, sell_n, sell_qty

    print("=== aggregate fills ===")
    print(f"  local: BUY n={agg(local_clipped)[0]} qty={agg(local_clipped)[1]}, "
          f"SELL n={agg(local_clipped)[2]} qty={agg(local_clipped)[3]}")
    print(f"  imc:   BUY n={agg(imc_trades)[0]} qty={agg(imc_trades)[1]}, "
          f"SELL n={agg(imc_trades)[2]} qty={agg(imc_trades)[3]}")


if __name__ == "__main__":
    main()
