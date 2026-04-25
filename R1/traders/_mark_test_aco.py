"""
_mark_test_aco.py — Throwaway marking-convention test trader for ACO.

Purpose: Buy exactly 1 unit of ASH_COATED_OSMIUM at t=0 (at the current
best ask, guaranteeing a fill if any ask volume exists), then do nothing
for the rest of the day. This lets us read the final reported PnL and
back-solve which price the backtester uses to mark the open position.

Do NOT delete — this file is evidence for backtester_marking_verified.md.
"""

from datamodel import OrderDepth, TradingState, Order  # type: ignore
from typing import Dict, List


class Trader:
    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        # Only act at timestamp 0
        if state.timestamp == 0:
            depth: OrderDepth = state.order_depths.get("ASH_COATED_OSMIUM")
            if depth is not None and depth.sell_orders:
                best_ask = min(depth.sell_orders.keys())
                result["ASH_COATED_OSMIUM"] = [Order("ASH_COATED_OSMIUM", best_ask, 1)]

        # No orders for IPR, no orders on any other timestamp
        return result, 0, ""
