from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List

PRODUCT = "VELVETFRUIT_EXTRACT"


class Trader:
    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        orders: List[Order] = []

        if PRODUCT in state.order_depths:
            od: OrderDepth = state.order_depths[PRODUCT]
            if od.sell_orders:
                best_ask = min(od.sell_orders.keys())
                orders.append(Order(PRODUCT, best_ask, 1))
            if od.buy_orders:
                best_bid = max(od.buy_orders.keys())
                orders.append(Order(PRODUCT, best_bid, -1))

        result[PRODUCT] = orders
        return result, 0, ""
