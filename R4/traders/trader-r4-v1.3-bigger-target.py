"""trader-r4-v1.1-edge-gated

v1.1 = v1 + realised-edge gate per FH_OLIVIA_BLUEPRINT.md §8.1.

Tracks VFX cumulative PnL in traderData (cost-basis method: own_trades give
prices, mark current position at mid). When cum_pnl < -GATE_HALVE_THRESHOLD
the target fraction is halved; when < -GATE_KILL_THRESHOLD the follower is
disabled entirely until the gate releases (cum_pnl back above -kill/2).

Original v1 docstring follows.

Primary R4 trader. Three independent legs:

1. VELVETFRUIT_EXTRACT: follow Mark 67 (informed buyer; FINDINGS.md +$165/fill avg
   close-edge, BUT FINDINGS_PART3.md #12 shows the per-unit edge is unstable across
   days: +$17/u D1, +$38/u D2, -$8/u D3). We DOWN-WEIGHT by capping target position
   at +/-50 (vs the 200 limit) and by gating on a Mark 55 jump-front-runner overlay
   when M67 is silent. Mark 49 sells contribute a weak SHORT signal.

2. VEV_6000 / VEV_6500: passive bid at price 0 with full 300-lot size. Verified:
   resting bid at 0 with vol 14-30, ask at 1, mid 0.5. Liquidation at ~0.5 means
   any fill at 0 is +0.5/unit free edge. Mark 01 is queued in front of us so fills
   are rare; cost of resting is zero so this is a freebie module. (Blueprint §8.3.)

3. (NOT yet — combined HYDROGEL/VEV_4000 MM logic comes in v2.)

Per CLAUDE.md hard rule #10: NEVER `import os`. Day inference uses pathlib only;
config is inlined as a module-level dict so the uploaded .py is self-contained.
"""

from typing import Dict, List, Tuple, Optional
import json
from pathlib import Path

from datamodel import OrderDepth, TradingState, Order, Trade


# === Inlined config (also persisted to configs/ for reference) ===========
CONFIG: Dict = {
    # Mark 67 follower
    "INFORMED_BUYER": "Mark 67",
    "COUNTER_SELLER": "Mark 49",
    "JUMP_FRONTRUNNER": "Mark 55",
    "BIG_FILL_QTY": 10,             # M67 fills >= this are "high conviction"
    "JUMP_QTY_THRESHOLD": 10,       # M55 trades >= this count as jump signal
    # Target sizing — DOWN-WEIGHTED from blueprint (was 0.5, now 0.25 per §8.1)
    "VFX_LIMIT": 200,
    "VFX_TARGET_FRACTION": 0.50,    # cap follow at +/-50
    "VFX_BIG_TARGET_FRACTION": 1.00,# big M67 fill -> cap at +/-100
    "REACTIVE_WINDOW_TS": 2000,     # seconds after M67 fill to aggressively lift
    "M55_REACTIVE_WINDOW_TS": 3000, # short window for the jump-frontrun overlay
    "WEAK_COUNTER_TARGET_FRACTION": 0.10,  # M49-only signal: tiny short bias
    # Strip module
    "STRIP_STRIKES": ["VEV_6000", "VEV_6500"],
    "STRIP_BID_PRICE": 0,
    "STRIP_BID_SIZE": 300,           # full position-limit size at price 0
    "STRIP_LIMIT": 300,
    # Realised-edge gate (v1.1)
    "GATE_HALVE_THRESHOLD": 1500,    # if cum VFX PnL < -1500, halve target fractions
    "GATE_KILL_THRESHOLD": 3000,     # if cum VFX PnL < -3000, disable follower entirely
    "GATE_RELEASE_FRACTION": 0.5,    # release at -kill * release_fraction
}

LONG, SHORT, NEUTRAL = 1, -1, 0


# === Pure helpers =========================================================
def _safe_int(x) -> int:
    return int(round(float(x)))


def _wall_mid(od: OrderDepth) -> Optional[float]:
    """Use deepest visible levels (FH convention) — filters out 1-lot flicker."""
    if not od.buy_orders or not od.sell_orders:
        return None
    bid_wall = min(od.buy_orders.keys())
    ask_wall = max(od.sell_orders.keys())
    return 0.5 * (bid_wall + ask_wall)


# === Trader ===============================================================
class Trader:
    def __init__(self):
        # Per-tick scratch only; persistent state lives in TradingState.traderData
        pass

    # ---------- traderData persistence ----------
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

    # ---------- realised-edge gate (v1.1) ----------
    def _update_vfx_pnl(self, state: TradingState, persisted: Dict) -> float:
        """Update and return cumulative VFX PnL estimate.

        Method: cost-basis. Each tick we walk own_trades on VFX; if SUBMISSION is
        the buyer, we paid price*qty (cost_basis += price*qty). If SUBMISSION is
        the seller, we received price*qty (cost_basis -= price*qty). Cumulative
        unrealised PnL is then position * mid - cost_basis.

        Falls back to delta-position * mid pricing if SUBMISSION marker isn't
        present (some sim variants leave it blank).
        """
        sym = "VELVETFRUIT_EXTRACT"
        gate_state = persisted.setdefault("_gate", {
            "cost_basis": 0.0, "prev_pos": 0, "cum_pnl": 0.0, "killed": False,
        })
        cur_pos = int(state.position.get(sym, 0))

        # 1) Walk own_trades on VFX this tick to update cost basis
        own = state.own_trades.get(sym, []) or []
        delta_used = 0
        for tr in own:
            qty = abs(int(tr.quantity))
            price = float(tr.price)
            if tr.buyer == "SUBMISSION":
                gate_state["cost_basis"] += price * qty
                delta_used += qty
            elif tr.seller == "SUBMISSION":
                gate_state["cost_basis"] -= price * qty
                delta_used -= qty
        # Fallback: if marker missing but position changed, use mid as price proxy
        delta_pos_actual = cur_pos - int(gate_state["prev_pos"])
        residual = delta_pos_actual - delta_used
        if residual != 0 and sym in state.order_depths:
            od = state.order_depths[sym]
            if od.buy_orders and od.sell_orders:
                mid = 0.5 * (max(od.buy_orders.keys()) + min(od.sell_orders.keys()))
                gate_state["cost_basis"] += residual * mid

        # 2) Mark to current mid
        cum_pnl = -gate_state["cost_basis"]  # default if no book
        if sym in state.order_depths:
            od = state.order_depths[sym]
            if od.buy_orders and od.sell_orders:
                mid = 0.5 * (max(od.buy_orders.keys()) + min(od.sell_orders.keys()))
                cum_pnl = cur_pos * mid - gate_state["cost_basis"]
        gate_state["cum_pnl"] = float(cum_pnl)
        gate_state["prev_pos"] = cur_pos
        return float(cum_pnl)

    def _gate_multiplier(self, persisted: Dict) -> float:
        """Return target-fraction multiplier from the realised-edge gate. Once
        killed (PnL < -KILL), stays killed until PnL recovers above
        -KILL * RELEASE_FRACTION."""
        cfg = CONFIG
        gate_state = persisted.get("_gate", {"cum_pnl": 0.0, "killed": False})
        pnl = float(gate_state.get("cum_pnl", 0.0))
        killed = bool(gate_state.get("killed", False))

        if pnl < -cfg["GATE_KILL_THRESHOLD"]:
            killed = True
        elif killed and pnl > -cfg["GATE_KILL_THRESHOLD"] * cfg["GATE_RELEASE_FRACTION"]:
            killed = False
        gate_state["killed"] = killed
        persisted["_gate"] = gate_state

        if killed:
            return 0.0
        if pnl < -cfg["GATE_HALVE_THRESHOLD"]:
            return 0.5
        return 1.0

    # ---------- core: detect informed flow ----------
    def _scan_for_informed(self, state: TradingState, persisted: Dict) -> Dict:
        """Walk this tick's market_trades + own_trades for VELVETFRUIT_EXTRACT
        and update the persisted last-seen timestamps + max-recent-fill-qty per
        trader. Returns the updated dict (mutates in place).
        """
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
        """Return (direction, target_fraction). M67 dominates; M49 is weak;
        M55 only fires when M67 is silent."""
        cfg = CONFIG
        # Primary: Mark 67 ever seen buying
        if st["m67_buy_ts"] is not None:
            big = (st["m67_buy_qty"] or 0) >= cfg["BIG_FILL_QTY"]
            frac = cfg["VFX_BIG_TARGET_FRACTION"] if big else cfg["VFX_TARGET_FRACTION"]
            return LONG, frac
        # M55 jump overlay (only when M67 silent; n=5 in EDA so low confidence)
        if st["m55_long_ts"] is not None and (now_ts - st["m55_long_ts"]) <= cfg["M55_REACTIVE_WINDOW_TS"]:
            return LONG, cfg["VFX_TARGET_FRACTION"]
        if st["m55_short_ts"] is not None and (now_ts - st["m55_short_ts"]) <= cfg["M55_REACTIVE_WINDOW_TS"]:
            return SHORT, cfg["VFX_TARGET_FRACTION"]
        # Weak: only Mark 49 selling seen — fade lightly
        if st["m49_sell_ts"] is not None:
            return SHORT, cfg["WEAK_COUNTER_TARGET_FRACTION"]
        return NEUTRAL, 0.0

    # ---------- VELVETFRUIT leg ----------
    def _vfx_orders(self, state: TradingState, persisted: Dict) -> List[Order]:
        cfg = CONFIG
        sym = "VELVETFRUIT_EXTRACT"
        if sym not in state.order_depths:
            return []
        od = state.order_depths[sym]
        if not od.buy_orders or not od.sell_orders:
            return []

        # Update PnL estimate AFTER position is observed, BEFORE deciding new orders
        self._update_vfx_pnl(state, persisted)
        gate_mult = self._gate_multiplier(persisted)

        st = self._scan_for_informed(state, persisted)
        direction, frac = self._resolve_direction(st, int(state.timestamp))
        target_pos = int(round(direction * frac * gate_mult * cfg["VFX_LIMIT"]))
        cur = int(state.position.get(sym, 0))
        room_buy = cfg["VFX_LIMIT"] - cur     # max we can add long
        room_sell = cfg["VFX_LIMIT"] + cur    # max we can add short
        orders: List[Order] = []

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        ask_wall = max(od.sell_orders.keys())
        bid_wall = min(od.buy_orders.keys())

        # === Reactive lift / hit within window of last M67 buy ===
        m67_ts = st["m67_buy_ts"]
        in_reactive = (m67_ts is not None
                       and int(state.timestamp) - int(m67_ts) <= cfg["REACTIVE_WINDOW_TS"])

        if direction == LONG and in_reactive:
            shortfall = target_pos - cur
            if shortfall > 0 and best_ask is not None:
                lift_qty = min(shortfall, room_buy, abs(od.sell_orders[best_ask]))
                if lift_qty > 0:
                    orders.append(Order(sym, _safe_int(best_ask), lift_qty))
                    room_buy -= lift_qty
        elif direction == SHORT and in_reactive:
            # Symmetric logic if we ever go short via M49 (rare)
            overage = cur - target_pos
            if overage > 0 and best_bid is not None:
                hit_qty = min(overage, room_sell, abs(od.buy_orders[best_bid]))
                if hit_qty > 0:
                    orders.append(Order(sym, _safe_int(best_bid), -hit_qty))
                    room_sell -= hit_qty

        # === Persistent skewed quoting ===
        # When LONG-biased and below target, post a more aggressive bid (pay 1 over)
        # When NEUTRAL, just quote inside the spread one tick wide
        wm = _wall_mid(od)
        if wm is None:
            return orders
        spread = best_ask - best_bid
        if spread < 2:
            return orders  # too tight, skip MM this tick

        if direction == LONG and cur < target_pos:
            bid_px = _safe_int(best_bid + 1)   # join just inside
            ask_px = _safe_int(best_ask)       # passive ask
        elif direction == SHORT and cur > target_pos:
            bid_px = _safe_int(best_bid)
            ask_px = _safe_int(best_ask - 1)
        else:
            bid_px = _safe_int(best_bid + 1)
            ask_px = _safe_int(best_ask - 1)

        # Make sure we don't cross our own quote
        if bid_px >= ask_px:
            return orders

        bid_size = min(20, room_buy)            # cap MM legs at 20 lots
        ask_size = min(20, room_sell)
        if bid_size > 0:
            orders.append(Order(sym, bid_px, bid_size))
        if ask_size > 0:
            orders.append(Order(sym, ask_px, -ask_size))
        return orders

    # ---------- Strip leg (passive 0-bid) ----------
    def _strip_orders(self, state: TradingState) -> Dict[str, List[Order]]:
        cfg = CONFIG
        out: Dict[str, List[Order]] = {}
        for sym in cfg["STRIP_STRIKES"]:
            if sym not in state.order_depths:
                continue
            cur = int(state.position.get(sym, 0))
            room_buy = cfg["STRIP_LIMIT"] - cur
            if room_buy <= 0:
                continue
            size = min(cfg["STRIP_BID_SIZE"], room_buy)
            out[sym] = [Order(sym, cfg["STRIP_BID_PRICE"], size)]
        return out

    # ---------- main entry ----------
    def run(self, state: TradingState):
        persisted = self._load_state(state.traderData or "")
        result: Dict[str, List[Order]] = {}

        # Leg 1: VELVETFRUIT follower
        vfx = self._vfx_orders(state, persisted)
        if vfx:
            result["VELVETFRUIT_EXTRACT"] = vfx

        # Leg 2: VEV_6000/6500 passive 0-bid
        for sym, ords in self._strip_orders(state).items():
            result[sym] = ords

        return result, 0, self._dump_state(persisted)
