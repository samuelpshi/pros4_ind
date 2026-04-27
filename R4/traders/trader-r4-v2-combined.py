"""trader-r4-v2-combined

v2 = v1.4 (M67 follower, tighter ±30/±60 target) + R3 HYDROGEL_PACK leg + passive
0-bid strip on VEV_6000/6500. VEV_4000 is intentionally untouched (Mark 14
captures the spread there at +$10.59/u every day per FINDINGS_PART3.md #12; we
defensively avoid trading it).

Three independent legs, traderData carries all state in one JSON blob:
  - "_gate", "VELVETFRUIT_EXTRACT" → M67 follower (v1.4 logic verbatim)
  - "ema_fv" → HYDROGEL_PACK EMA fair value (R3 hydrogel logic verbatim)
"""

from typing import Dict, List, Tuple, Optional
import json
from pathlib import Path

from datamodel import OrderDepth, TradingState, Order, Trade


CONFIG: Dict = {
    # === M67 follower (v1.4 verbatim) ===
    "INFORMED_BUYER": "Mark 67",
    "COUNTER_SELLER": "Mark 49",
    "JUMP_FRONTRUNNER": "Mark 55",
    "BIG_FILL_QTY": 10,
    "JUMP_QTY_THRESHOLD": 10,
    "VFX_LIMIT": 200,
    "VFX_TARGET_FRACTION": 0.15,    # ±30
    "VFX_BIG_TARGET_FRACTION": 0.30,# ±60 on big M67 fills
    "REACTIVE_WINDOW_TS": 2000,
    "M55_REACTIVE_WINDOW_TS": 3000,
    "WEAK_COUNTER_TARGET_FRACTION": 0.10,
    # Strip
    "STRIP_STRIKES": ["VEV_6000", "VEV_6500"],
    "STRIP_BID_PRICE": 0,
    "STRIP_BID_SIZE": 300,
    "STRIP_LIMIT": 300,
    # Edge gate
    "GATE_HALVE_THRESHOLD": 1500,
    "GATE_KILL_THRESHOLD": 3000,
    "GATE_RELEASE_FRACTION": 0.5,
    # === HYDROGEL leg (R3 trader-r3-v1-hydrogel verbatim) ===
    "HG_FV_EMA_WINDOW": 50,
    "HG_QUOTE_OFFSET": 3,
    "HG_SKEW_STRENGTH": 1.0,
    "HG_TAKE_EDGE": 4,
    "HG_PASSIVE_SIZE": 30,
    "HG_TAKE_CAP": 50,
    "HG_LIMIT": 200,
}

LONG, SHORT, NEUTRAL = 1, -1, 0


def _safe_int(x) -> int:
    return int(round(float(x)))


def _wall_mid(od: OrderDepth) -> Optional[float]:
    if not od.buy_orders or not od.sell_orders:
        return None
    return 0.5 * (min(od.buy_orders) + max(od.sell_orders))


class Trader:
    @staticmethod
    def _load_state(blob: str) -> Dict:
        if not blob:
            return {}
        try:
            return json.loads(blob)
        except Exception:
            return {}

    @staticmethod
    def _dump_state(s: Dict) -> str:
        return json.dumps(s, separators=(",", ":"))

    # ===== M67 follower leg (v1.4 verbatim) =====
    def _update_vfx_pnl(self, state: TradingState, persisted: Dict) -> float:
        sym = "VELVETFRUIT_EXTRACT"
        gs = persisted.setdefault("_gate", {
            "cost_basis": 0.0, "prev_pos": 0, "cum_pnl": 0.0, "killed": False,
        })
        cur_pos = int(state.position.get(sym, 0))
        own = state.own_trades.get(sym, []) or []
        delta_used = 0
        for tr in own:
            qty = abs(int(tr.quantity)); price = float(tr.price)
            if tr.buyer == "SUBMISSION":
                gs["cost_basis"] += price * qty; delta_used += qty
            elif tr.seller == "SUBMISSION":
                gs["cost_basis"] -= price * qty; delta_used -= qty
        residual = (cur_pos - int(gs["prev_pos"])) - delta_used
        if residual != 0 and sym in state.order_depths:
            od = state.order_depths[sym]
            if od.buy_orders and od.sell_orders:
                mid = 0.5 * (max(od.buy_orders) + min(od.sell_orders))
                gs["cost_basis"] += residual * mid
        cum_pnl = -gs["cost_basis"]
        if sym in state.order_depths:
            od = state.order_depths[sym]
            if od.buy_orders and od.sell_orders:
                mid = 0.5 * (max(od.buy_orders) + min(od.sell_orders))
                cum_pnl = cur_pos * mid - gs["cost_basis"]
        gs["cum_pnl"] = float(cum_pnl); gs["prev_pos"] = cur_pos
        return float(cum_pnl)

    def _gate_multiplier(self, persisted: Dict) -> float:
        cfg = CONFIG
        gs = persisted.get("_gate", {"cum_pnl": 0.0, "killed": False})
        pnl = float(gs.get("cum_pnl", 0.0))
        killed = bool(gs.get("killed", False))
        if pnl < -cfg["GATE_KILL_THRESHOLD"]:
            killed = True
        elif killed and pnl > -cfg["GATE_KILL_THRESHOLD"] * cfg["GATE_RELEASE_FRACTION"]:
            killed = False
        gs["killed"] = killed; persisted["_gate"] = gs
        if killed: return 0.0
        if pnl < -cfg["GATE_HALVE_THRESHOLD"]: return 0.5
        return 1.0

    def _scan_for_informed(self, state: TradingState, persisted: Dict) -> Dict:
        cfg = CONFIG
        sym = "VELVETFRUIT_EXTRACT"
        st = persisted.setdefault(sym, {
            "m67_buy_ts": None, "m67_buy_qty": 0,
            "m49_sell_ts": None, "m49_sell_qty": 0,
            "m55_long_ts": None, "m55_long_qty": 0,
            "m55_short_ts": None, "m55_short_qty": 0,
        })
        trades: List[Trade] = []
        trades.extend(state.market_trades.get(sym, []) or [])
        trades.extend(state.own_trades.get(sym, []) or [])
        for tr in trades:
            qty = abs(int(tr.quantity))
            if tr.buyer == cfg["INFORMED_BUYER"]:
                st["m67_buy_ts"] = int(tr.timestamp)
                st["m67_buy_qty"] = max(int(st["m67_buy_qty"] or 0), qty)
            if tr.seller == cfg["COUNTER_SELLER"]:
                st["m49_sell_ts"] = int(tr.timestamp)
                st["m49_sell_qty"] = max(int(st["m49_sell_qty"] or 0), qty)
            if tr.buyer == cfg["JUMP_FRONTRUNNER"] and qty >= cfg["JUMP_QTY_THRESHOLD"]:
                st["m55_long_ts"] = int(tr.timestamp)
                st["m55_long_qty"] = max(int(st["m55_long_qty"] or 0), qty)
            if tr.seller == cfg["JUMP_FRONTRUNNER"] and qty >= cfg["JUMP_QTY_THRESHOLD"]:
                st["m55_short_ts"] = int(tr.timestamp)
                st["m55_short_qty"] = max(int(st["m55_short_qty"] or 0), qty)
        return st

    def _resolve_direction(self, st: Dict, now_ts: int) -> Tuple[int, float]:
        cfg = CONFIG
        if st["m67_buy_ts"] is not None:
            big = (st["m67_buy_qty"] or 0) >= cfg["BIG_FILL_QTY"]
            return LONG, cfg["VFX_BIG_TARGET_FRACTION"] if big else cfg["VFX_TARGET_FRACTION"]
        if st["m55_long_ts"] is not None and (now_ts - st["m55_long_ts"]) <= cfg["M55_REACTIVE_WINDOW_TS"]:
            return LONG, cfg["VFX_TARGET_FRACTION"]
        if st["m55_short_ts"] is not None and (now_ts - st["m55_short_ts"]) <= cfg["M55_REACTIVE_WINDOW_TS"]:
            return SHORT, cfg["VFX_TARGET_FRACTION"]
        if st["m49_sell_ts"] is not None:
            return SHORT, cfg["WEAK_COUNTER_TARGET_FRACTION"]
        return NEUTRAL, 0.0

    def _vfx_orders(self, state: TradingState, persisted: Dict) -> List[Order]:
        cfg = CONFIG
        sym = "VELVETFRUIT_EXTRACT"
        if sym not in state.order_depths: return []
        od = state.order_depths[sym]
        if not od.buy_orders or not od.sell_orders: return []

        self._update_vfx_pnl(state, persisted)
        gate_mult = self._gate_multiplier(persisted)
        st = self._scan_for_informed(state, persisted)
        direction, frac = self._resolve_direction(st, int(state.timestamp))
        target_pos = int(round(direction * frac * gate_mult * cfg["VFX_LIMIT"]))
        cur = int(state.position.get(sym, 0))
        room_buy = cfg["VFX_LIMIT"] - cur
        room_sell = cfg["VFX_LIMIT"] + cur
        orders: List[Order] = []

        best_bid = max(od.buy_orders); best_ask = min(od.sell_orders)
        m67_ts = st["m67_buy_ts"]
        in_reactive = (m67_ts is not None
                       and int(state.timestamp) - int(m67_ts) <= cfg["REACTIVE_WINDOW_TS"])

        if direction == LONG and in_reactive:
            shortfall = target_pos - cur
            if shortfall > 0:
                lift_qty = min(shortfall, room_buy, abs(od.sell_orders[best_ask]))
                if lift_qty > 0:
                    orders.append(Order(sym, _safe_int(best_ask), lift_qty))
                    room_buy -= lift_qty
        elif direction == SHORT and in_reactive:
            overage = cur - target_pos
            if overage > 0:
                hit_qty = min(overage, room_sell, abs(od.buy_orders[best_bid]))
                if hit_qty > 0:
                    orders.append(Order(sym, _safe_int(best_bid), -hit_qty))
                    room_sell -= hit_qty

        if best_ask - best_bid < 2 or _wall_mid(od) is None:
            return orders

        if direction == LONG and cur < target_pos:
            bid_px = _safe_int(best_bid + 1); ask_px = _safe_int(best_ask)
        elif direction == SHORT and cur > target_pos:
            bid_px = _safe_int(best_bid); ask_px = _safe_int(best_ask - 1)
        else:
            bid_px = _safe_int(best_bid + 1); ask_px = _safe_int(best_ask - 1)
        if bid_px >= ask_px: return orders

        bid_size = min(20, room_buy); ask_size = min(20, room_sell)
        if bid_size > 0: orders.append(Order(sym, bid_px, bid_size))
        if ask_size > 0: orders.append(Order(sym, ask_px, -ask_size))
        return orders

    # ===== Strip leg (passive 0-bid) =====
    def _strip_orders(self, state: TradingState) -> Dict[str, List[Order]]:
        cfg = CONFIG
        out: Dict[str, List[Order]] = {}
        for sym in cfg["STRIP_STRIKES"]:
            if sym not in state.order_depths: continue
            cur = int(state.position.get(sym, 0))
            room_buy = cfg["STRIP_LIMIT"] - cur
            if room_buy <= 0: continue
            out[sym] = [Order(sym, cfg["STRIP_BID_PRICE"], min(cfg["STRIP_BID_SIZE"], room_buy))]
        return out

    # ===== HYDROGEL_PACK leg (R3 hydrogel verbatim) =====
    def _hydrogel_orders(self, state: TradingState, persisted: Dict) -> List[Order]:
        cfg = CONFIG
        sym = "HYDROGEL_PACK"
        depth = state.order_depths.get(sym)
        if depth is None or not depth.buy_orders or not depth.sell_orders:
            return []

        ema_window = cfg["HG_FV_EMA_WINDOW"]
        quote_offset = cfg["HG_QUOTE_OFFSET"]
        skew_strength = cfg["HG_SKEW_STRENGTH"]
        take_edge = cfg["HG_TAKE_EDGE"]
        passive_size = cfg["HG_PASSIVE_SIZE"]
        take_cap = cfg["HG_TAKE_CAP"]
        limit = cfg["HG_LIMIT"]

        ema = persisted.get("ema_fv")
        best_bid = max(depth.buy_orders); best_ask = min(depth.sell_orders)
        mid = 0.5 * (best_bid + best_ask)
        alpha = 2.0 / (ema_window + 1.0)
        ema = mid if ema is None else alpha * mid + (1.0 - alpha) * ema
        fv = ema
        persisted["ema_fv"] = ema

        pos = state.position.get(sym, 0)
        orders: List[Order] = []

        # Aggressive takes
        room_buy = limit - pos; take_buy_used = 0
        for ap in sorted(depth.sell_orders):
            if ap > fv - take_edge: break
            available = -depth.sell_orders[ap]
            qty = min(available, room_buy - take_buy_used, take_cap - take_buy_used)
            if qty <= 0: break
            orders.append(Order(sym, ap, qty)); take_buy_used += qty
            if take_buy_used >= take_cap or take_buy_used >= room_buy: break

        room_sell = limit + pos; take_sell_used = 0
        for bp in sorted(depth.buy_orders, reverse=True):
            if bp < fv + take_edge: break
            available = depth.buy_orders[bp]
            qty = min(available, room_sell - take_sell_used, take_cap - take_sell_used)
            if qty <= 0: break
            orders.append(Order(sym, bp, -qty)); take_sell_used += qty
            if take_sell_used >= take_cap or take_sell_used >= room_sell: break

        # Passive skewed quote
        proj_pos = pos + take_buy_used - take_sell_used
        room_buy_passive = limit - proj_pos
        room_sell_passive = limit + proj_pos
        inv_ratio = proj_pos / limit
        skew = inv_ratio * skew_strength
        bid_px = int(round(fv - quote_offset - skew))
        ask_px = int(round(fv + quote_offset - skew))
        if ask_px <= bid_px: ask_px = bid_px + 1
        bid_size = min(passive_size, room_buy_passive)
        ask_size = min(passive_size, room_sell_passive)
        if bid_size > 0: orders.append(Order(sym, bid_px, bid_size))
        if ask_size > 0: orders.append(Order(sym, ask_px, -ask_size))
        return orders

    # ===== main =====
    def run(self, state: TradingState):
        persisted = self._load_state(state.traderData or "")
        result: Dict[str, List[Order]] = {}

        vfx = self._vfx_orders(state, persisted)
        if vfx: result["VELVETFRUIT_EXTRACT"] = vfx

        hg = self._hydrogel_orders(state, persisted)
        if hg: result["HYDROGEL_PACK"] = hg

        for sym, ords in self._strip_orders(state).items():
            result[sym] = ords

        return result, 0, self._dump_state(persisted)
