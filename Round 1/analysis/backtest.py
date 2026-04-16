"""
Minimal local backtester for IMC Prosperity Round 1.

Reads CSV price data, constructs OrderDepth / TradingState stubs,
calls Trader.run() each timestep, matches resulting orders against
the order book, and tracks PnL.

Matching rules (conservative, mimicking IMC engine):
- BUY orders fill against the ask side of the book if order price >= ask price
- SELL orders fill against the bid side of the book if order price <= bid price
- Fill quantity is min(order_qty, available_volume_at_that_level)
- We walk through book levels in price priority (best first)
- No self-trade (our passive quotes don't sit in the book across timesteps)

PnL accounting:
- Track position and cash separately
- At end of day, mark to mid-price (last valid mid)
- PnL = cash + position * last_mid
"""

import sys, os, math
import pandas as pd
import numpy as np

# Add trader directory to path so we can import the trader
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'our_trader'))

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
        self.buy_orders = {}   # price -> positive qty
        self.sell_orders = {}  # price -> negative qty

class TradingState:
    def __init__(self, timestamp, order_depths, position, trader_data):
        self.timestamp = timestamp
        self.order_depths = order_depths
        self.position = position
        self.traderData = trader_data
        self.own_trades = {}
        self.market_trades = {}
        self.observations = {}

# Monkey-patch the datamodel module so the trader can import from it
import types
datamodel_mod = types.ModuleType('datamodel')
datamodel_mod.OrderDepth = OrderDepth
datamodel_mod.TradingState = TradingState
datamodel_mod.Order = Order
sys.modules['datamodel'] = datamodel_mod

# Now import the trader
from importlib import import_module
import importlib.util
spec = importlib.util.spec_from_file_location("trader_module",
    os.path.join(os.path.dirname(__file__), '..', 'our_trader', '173159.py'))
trader_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trader_mod)
TraderClass = trader_mod.Trader

# Also grab config for reversal tracking
IPR_CFG = trader_mod.IPR_CFG
POSITION_LIMITS = trader_mod.POSITION_LIMITS


def build_order_depth(row):
    """Build OrderDepth from a prices CSV row."""
    depth = OrderDepth()
    for lvl in [1, 2, 3]:
        bp = row.get(f'bid_price_{lvl}')
        bv = row.get(f'bid_volume_{lvl}')
        if pd.notna(bp) and pd.notna(bv) and bv > 0:
            depth.buy_orders[int(bp)] = int(bv)
        ap = row.get(f'ask_price_{lvl}')
        av = row.get(f'ask_volume_{lvl}')
        if pd.notna(ap) and pd.notna(av) and av > 0:
            depth.sell_orders[int(ap)] = -int(av)  # IMC convention: negative
    return depth


def match_orders(orders, depth, pos, limit):
    """
    Match a list of Order objects against the book.
    Returns (fills, new_pos, cash_delta).
    fills: list of (price, qty) where qty>0 = bought, qty<0 = sold.
    """
    fills = []
    cash = 0.0

    for order in orders:
        if order.quantity > 0:
            # BUY order: match against asks
            for ap in sorted(depth.sell_orders.keys()):
                if order.price < ap:
                    break
                avail = -depth.sell_orders[ap]  # positive
                can_buy = min(order.quantity, avail, limit - pos)
                if can_buy <= 0:
                    continue
                fills.append((ap, can_buy))
                cash -= ap * can_buy
                pos += can_buy
                order.quantity -= can_buy
                depth.sell_orders[ap] += can_buy  # reduce available
                if depth.sell_orders[ap] == 0:
                    del depth.sell_orders[ap]
                if order.quantity <= 0:
                    break
        elif order.quantity < 0:
            # SELL order: match against bids
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
    DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'ROUND1')
    DAYS = [-2, -1, 0]

    all_results = []
    reversal_events = []

    for day in DAYS:
        prices = pd.read_csv(f'{DATA_DIR}/prices_round_1_day_{day}.csv', sep=';')
        products = prices['product'].unique()

        # Group by timestamp
        grouped = prices.groupby('timestamp')
        timestamps = sorted(grouped.groups.keys())

        trader = TraderClass()
        trader_data = ""
        position = {}
        cash = {p: 0.0 for p in products}
        day_fills = {p: [] for p in products}

        # For reversal tracking: manually compute EMAs
        ema_fast = {}
        ema_slow = {}
        prev_target = {}

        for ts in timestamps:
            ts_rows = grouped.get_group(ts)

            # Build order depths
            order_depths = {}
            mid_prices = {}
            for _, row in ts_rows.iterrows():
                product = row['product']
                depth = build_order_depth(row)
                if depth.buy_orders or depth.sell_orders:
                    order_depths[product] = depth
                mid_prices[product] = row['mid_price']

            if not order_depths:
                continue

            # Build state
            state = TradingState(ts, order_depths, dict(position), trader_data)

            # Run trader
            try:
                result, conversions, trader_data = trader.run(state)
            except Exception as e:
                print(f"  ERROR at day={day} ts={ts}: {e}")
                continue

            # Track reversal signals for IPR
            if 'INTARIAN_PEPPER_ROOT' in order_depths:
                ipr_depth = order_depths['INTARIAN_PEPPER_ROOT']
                if ipr_depth.buy_orders and ipr_depth.sell_orders:
                    # Compute mid the same way the trader does (vwap_mid)
                    mid = trader_mod.vwap_mid(ipr_depth)
                    af = IPR_CFG["ema_fast"]
                    as_ = IPR_CFG["ema_slow"]
                    pf = ema_fast.get('IPR', mid)
                    ps = ema_slow.get('IPR', mid)
                    fast = af * mid + (1 - af) * pf
                    slow = as_ * mid + (1 - as_) * ps
                    ema_fast['IPR'] = fast
                    ema_slow['IPR'] = slow

                    gap = fast - slow
                    target = IPR_CFG["target_long"]
                    if gap < IPR_CFG["strong_reversal_thr"]:
                        target = -POSITION_LIMITS["INTARIAN_PEPPER_ROOT"]
                    elif gap < IPR_CFG["reversal_threshold"]:
                        target = 0

                    old_target = prev_target.get('IPR', IPR_CFG["target_long"])
                    if target != old_target and target < IPR_CFG["target_long"]:
                        reversal_events.append({
                            'day': day, 'timestamp': ts,
                            'gap': gap, 'new_target': target,
                            'old_target': old_target,
                            'mid': mid, 'fast_ema': fast, 'slow_ema': slow,
                            'position': position.get('INTARIAN_PEPPER_ROOT', 0),
                        })
                    prev_target['IPR'] = target

            # Match orders for each product
            for product, orders in result.items():
                if product not in order_depths:
                    continue
                limit = POSITION_LIMITS.get(product, 20)
                pos = position.get(product, 0)
                depth = order_depths[product]

                fills, new_pos, cash_delta = match_orders(orders, depth, pos, limit)
                position[product] = new_pos
                cash[product] += cash_delta
                day_fills[product].extend(fills)

        # End of day: mark to market
        # Get last valid mid for each product
        last_ts_rows = grouped.get_group(timestamps[-1])
        for _, row in last_ts_rows.iterrows():
            product = row['product']
            last_mid = row['mid_price']
            pos = position.get(product, 0)
            mtm = cash.get(product, 0) + pos * last_mid
            n_fills = len(day_fills.get(product, []))

            all_results.append({
                'day': day, 'product': product,
                'final_pos': pos, 'cash': cash.get(product, 0),
                'last_mid': last_mid, 'mtm_pnl': mtm,
                'n_fills': n_fills,
            })

    # Print results
    print("=" * 70)
    print("BACKTEST RESULTS")
    print("=" * 70)

    rdf = pd.DataFrame(all_results)
    total_pnl = 0
    for product in sorted(rdf['product'].unique()):
        print(f"\n--- {product} ---")
        prod_data = rdf[rdf['product'] == product]
        for _, row in prod_data.iterrows():
            print(f"  Day {row['day']:+d}: pos={row['final_pos']:+d}, cash={row['cash']:+,.0f}, "
                  f"last_mid={row['last_mid']:.1f}, PnL={row['mtm_pnl']:+,.0f} ({row['n_fills']} fills)")
            total_pnl += row['mtm_pnl']
        print(f"  Subtotal: {prod_data['mtm_pnl'].sum():+,.0f}")

    print(f"\n{'=' * 70}")
    print(f"TOTAL PnL (all products, all days): {total_pnl:+,.0f}")
    print(f"v8 baseline (IPR only, 1 day): +3,660")
    print(f"{'=' * 70}")

    # Reversal events
    print(f"\n--- REVERSAL SIGNAL TRACKING (IPR) ---")
    if not reversal_events:
        print("  No reversal signals fired across all 3 days.")
    else:
        print(f"  {len(reversal_events)} reversal signal(s) fired:")
        for ev in reversal_events:
            print(f"  Day {ev['day']:+d} ts={ev['timestamp']}: "
                  f"gap={ev['gap']:+.2f}, target {ev['old_target']}->{ev['new_target']}, "
                  f"mid={ev['mid']:.1f}, pos={ev['position']:+d}")


if __name__ == '__main__':
    run_backtest()
