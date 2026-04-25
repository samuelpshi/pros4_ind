"""
backtest_sweep.py — CLI-argument-aware backtester for ACO inventory penalty sweep.

Wraps the same engine logic as backtest.py but accepts:
  --trader <absolute-path-to-trader.py>
  --days   comma-separated subset of days, e.g. "-2,-1,0" (default: all 3)
  --output <path>  print output to file in addition to stdout

Usage example (from any directory):
  python /path/to/backtest_sweep.py --trader /path/to/trader.py --days -2,-1,0

Returns structured summary lines parseable by the sweep runner:
  PRODUCT_PNL: <product>  day=<d>  pnl=<n>  pos=<p>  fills=<n>
  TOTAL_PNL: <n>
  MAX_ABS_POS: <product>  <n>
"""

import sys, os, math, argparse
import pandas as pd
import numpy as np
import collections

# --- parse args FIRST before any side-effect imports ---
parser = argparse.ArgumentParser()
parser.add_argument('--trader', required=True, help='Absolute path to trader .py file')
parser.add_argument('--days', default='-2,-1,0', help='Comma-separated days to run')
parser.add_argument('--output', default=None, help='Optional path to write output')
args = parser.parse_args()

TRADER_PATH = os.path.abspath(args.trader)
DAYS = [int(d) for d in args.days.split(',')]

# --- Stubs for the IMC datamodel ---
class Order:
    def __init__(self, symbol: str, price: int, quantity: int):
        self.symbol = symbol
        self.price = price
        self.quantity = quantity
    def __repr__(self):
        return f"Order({self.symbol}, {self.price}, {self.quantity})"

class OrderDepth:
    def __init__(self):
        self.buy_orders = {}
        self.sell_orders = {}

class TradingState:
    def __init__(self, timestamp, order_depths, position, trader_data):
        self.timestamp = timestamp
        self.order_depths = order_depths
        self.position = position
        self.traderData = trader_data
        self.own_trades = {}
        self.market_trades = {}
        self.observations = {}

import types
datamodel_mod = types.ModuleType('datamodel')
datamodel_mod.OrderDepth = OrderDepth
datamodel_mod.TradingState = TradingState
datamodel_mod.Order = Order
sys.modules['datamodel'] = datamodel_mod

import importlib.util
spec = importlib.util.spec_from_file_location("trader_module", TRADER_PATH)
trader_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trader_mod)
TraderClass = trader_mod.Trader
POSITION_LIMITS = trader_mod.POSITION_LIMITS


def build_order_depth(row):
    depth = OrderDepth()
    for lvl in [1, 2, 3]:
        bp = row.get(f'bid_price_{lvl}')
        bv = row.get(f'bid_volume_{lvl}')
        if pd.notna(bp) and pd.notna(bv) and bv > 0:
            depth.buy_orders[int(bp)] = int(bv)
        ap = row.get(f'ask_price_{lvl}')
        av = row.get(f'ask_volume_{lvl}')
        if pd.notna(ap) and pd.notna(av) and av > 0:
            depth.sell_orders[int(ap)] = -int(av)
    return depth


def match_orders(orders, depth, pos, limit):
    fills = []
    cash = 0.0
    for order in orders:
        if order.quantity > 0:
            for ap in sorted(depth.sell_orders.keys()):
                if order.price < ap:
                    break
                avail = -depth.sell_orders[ap]
                can_buy = min(order.quantity, avail, limit - pos)
                if can_buy <= 0:
                    continue
                fills.append((ap, can_buy))
                cash -= ap * can_buy
                pos += can_buy
                order.quantity -= can_buy
                depth.sell_orders[ap] += can_buy
                if depth.sell_orders[ap] == 0:
                    del depth.sell_orders[ap]
                if order.quantity <= 0:
                    break
        elif order.quantity < 0:
            sell_qty = -order.quantity
            for bp in sorted(depth.buy_orders.keys(), reverse=True):
                if order.price > bp:
                    break
                avail = depth.buy_orders[bp]
                can_sell = min(sell_qty, avail, limit + pos)
                if can_sell <= 0:
                    continue
                fills.append((bp, -can_sell))
                cash += bp * can_sell
                pos -= can_sell
                sell_qty -= can_sell
                depth.buy_orders[bp] -= can_sell
                if depth.buy_orders[bp] == 0:
                    del depth.buy_orders[bp]
                if sell_qty <= 0:
                    break
    return fills, pos, cash


def run_backtest():
    # Data dir relative to THIS file's location (backtest_sweep.py is in Round 1/analysis/)
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'r1_data_capsule')

    all_results = []
    max_abs_pos = {}  # product -> max abs position seen across all days

    for day in DAYS:
        prices = pd.read_csv(f'{DATA_DIR}/prices_round_1_day_{day}.csv', sep=';')
        products = prices['product'].unique()

        grouped = prices.groupby('timestamp')
        timestamps = sorted(grouped.groups.keys())

        trader = TraderClass()
        trader_data = ""
        position = {}
        cash = {p: 0.0 for p in products}
        day_fills = {p: [] for p in products}
        day_max_abs_pos = {p: 0 for p in products}

        for ts in timestamps:
            ts_rows = grouped.get_group(ts)

            order_depths = {}
            for _, row in ts_rows.iterrows():
                product = row['product']
                depth = build_order_depth(row)
                if depth.buy_orders or depth.sell_orders:
                    order_depths[product] = depth

            if not order_depths:
                continue

            state = TradingState(ts, order_depths, dict(position), trader_data)

            try:
                result, conversions, trader_data = trader.run(state)
            except Exception as e:
                print(f"  ERROR at day={day} ts={ts}: {e}", file=sys.stderr)
                continue

            for product, orders in result.items():
                if product not in order_depths:
                    continue
                limit = POSITION_LIMITS.get(product, 80)
                pos = position.get(product, 0)
                depth = order_depths[product]

                fills, new_pos, cash_delta = match_orders(orders, depth, pos, limit)
                position[product] = new_pos
                cash[product] += cash_delta
                day_fills[product].extend(fills)

                # track max abs position
                abs_p = abs(new_pos)
                if abs_p > day_max_abs_pos.get(product, 0):
                    day_max_abs_pos[product] = abs_p

        # End of day mark-to-market
        last_ts_rows = grouped.get_group(timestamps[-1])
        for _, row in last_ts_rows.iterrows():
            product = row['product']
            last_mid = row['mid_price']
            pos = position.get(product, 0)
            mtm = cash.get(product, 0) + pos * last_mid
            n_fills = len(day_fills.get(product, []))
            mp = day_max_abs_pos.get(product, 0)

            all_results.append({
                'day': day, 'product': product,
                'final_pos': pos, 'cash': cash.get(product, 0),
                'last_mid': last_mid, 'mtm_pnl': mtm,
                'n_fills': n_fills,
                'max_abs_pos': mp,
            })

            # update global max
            if mp > max_abs_pos.get(product, 0):
                max_abs_pos[product] = mp

    # --- Structured output ---
    lines = []
    lines.append("=" * 70)
    lines.append("BACKTEST RESULTS (backtest_sweep.py)")
    lines.append(f"TRADER: {TRADER_PATH}")
    lines.append(f"DAYS: {DAYS}")
    lines.append("=" * 70)

    rdf = pd.DataFrame(all_results)
    total_pnl = 0.0
    product_pnl = {}

    for product in sorted(rdf['product'].unique()):
        lines.append(f"\n--- {product} ---")
        prod_data = rdf[rdf['product'] == product]
        prod_total = prod_data['mtm_pnl'].sum()
        product_pnl[product] = prod_total
        for _, row in prod_data.iterrows():
            line = (f"  Day {row['day']:+d}: pos={row['final_pos']:+d}, "
                    f"cash={row['cash']:+,.0f}, last_mid={row['last_mid']:.1f}, "
                    f"PnL={row['mtm_pnl']:+,.0f} ({row['n_fills']} fills) "
                    f"max_abs_pos={row['max_abs_pos']}")
            lines.append(line)
            total_pnl += row['mtm_pnl']
            # machine-readable line
            lines.append(f"PRODUCT_PNL: {product}  day={row['day']}  "
                         f"pnl={row['mtm_pnl']:.2f}  pos={row['final_pos']}  "
                         f"fills={row['n_fills']}  max_abs_pos={row['max_abs_pos']}")
        lines.append(f"  Subtotal: {prod_total:+,.0f}")

    lines.append(f"\n{'=' * 70}")
    lines.append(f"TOTAL_PNL: {total_pnl:.2f}")
    for p, v in product_pnl.items():
        lines.append(f"PRODUCT_TOTAL: {p}  {v:.2f}")
    for p, v in max_abs_pos.items():
        lines.append(f"MAX_ABS_POS: {p}  {v}")
    lines.append(f"{'=' * 70}")

    output = "\n".join(lines)
    print(output)
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
    return total_pnl, product_pnl, max_abs_pos


if __name__ == '__main__':
    run_backtest()
