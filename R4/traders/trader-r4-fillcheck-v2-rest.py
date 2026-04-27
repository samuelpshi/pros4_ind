from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List

PRODUCT = "VELVETFRUIT_EXTRACT"
POS_CAP = 100  # stay well inside the 200 limit


class Trader:
    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {PRODUCT: []}

        if PRODUCT not in state.order_depths:
            return result, 0, ""

        od: OrderDepth = state.order_depths[PRODUCT]
        if not od.buy_orders or not od.sell_orders:
            return result, 0, ""

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        if best_ask - best_bid < 2:
            return result, 0, ""

        pos = state.position.get(PRODUCT, 0)
        orders: List[Order] = []
        if pos < POS_CAP:
            orders.append(Order(PRODUCT, best_bid + 1, 1))
        if pos > -POS_CAP:
            orders.append(Order(PRODUCT, best_ask - 1, -1))

        result[PRODUCT] = orders
        return result, 0, ""
