# R3 COMBINED FINAL submission. Two independent MM modules sharing one
# Trader.run() entry point and a namespaced traderData JSON dict.
#
# Module 1 — HYDROGEL_PACK MM (the locked v3-sym-h4 config from
#   trader-r3-hydrogel-mm-FINAL.py, md5 670d347940ff0ed4b85970197d125f4d
#   when standalone). State keys: hydrogel_*
#
# Module 2 — VELVETFRUIT_EXTRACT MM (the v1 from
#   trader-r3-vev-mm-v1.py). State keys: vev_*
#
# Logic is byte-identical to the two source files; this file only inlines
# them under a single Trader class. No shared state, no cross-module logic.
# All decisions and audit trail in:
#   R3/analysis/agent_logs/P2_hydrogel_mm_log.md  (HYDROGEL ship decision)
#   R3/analysis/agent_logs/P2_vev_scalp_log.md    (VEV MM "last shot" sprint)
from datamodel import OrderDepth, TradingState, Order
import json
import math


# =============================================================================
# Module 1 constants — HYDROGEL_PACK (v3-sym-h4 locked config)
# =============================================================================
HYDRO_SYMBOL = "HYDROGEL_PACK"
HYDRO_POS_LIMIT = 200
HYDRO_EMA_WINDOW = 300
HYDRO_EMA_ALPHA = 2.0 / (HYDRO_EMA_WINDOW + 1)
HYDRO_WARMUP_TICKS = 300
HYDRO_SKEW_ALPHA = 0.01            # DEAD by design (banker's rounding)
HYDRO_MIN_QUOTE_SPREAD = 3
HYDRO_QUOTE_SIZE_CAP = 15
HYDRO_BID_EDGE = 4
HYDRO_ASK_EDGE = 4

# =============================================================================
# Module 2 constants — VELVETFRUIT_EXTRACT (vev-mm-v1)
# =============================================================================
VEV_SYMBOL = "VELVETFRUIT_EXTRACT"
VEV_POS_LIMIT = 200
VEV_EMA_WINDOW = 200
VEV_EMA_ALPHA = 2.0 / (VEV_EMA_WINDOW + 1)
VEV_WARMUP_TICKS = 200
VEV_SKEW_ALPHA = 0.01              # DEAD by design (banker's rounding)
VEV_MIN_QUOTE_SPREAD = 3
VEV_QUOTE_SIZE_CAP = 8
VEV_BID_EDGE = 2
VEV_ASK_EDGE = 2


class Trader:
    def run(self, state: TradingState):
        result: dict[str, list[Order]] = {}
        conversions = 0

        # try/except documented per Hard Rule #7: traderData == "" on the
        # very first tick is not valid JSON.
        trader_data: dict = {}
        if state.traderData:
            try:
                trader_data = json.loads(state.traderData)
            except json.JSONDecodeError:
                trader_data = {}

        # ---------------------------------------------------------------
        # Module 1 — HYDROGEL_PACK (verbatim from
        # trader-r3-hydrogel-mm-FINAL.py with state-key prefix kept)
        # ---------------------------------------------------------------
        hydro_ema = trader_data.get("hydrogel_ema")
        hydro_n_ticks = trader_data.get("hydrogel_n_ticks", 0)
        hydro_prev_state = trader_data.get("hydrogel_prev_state")
        hydro_warmup_done_logged = trader_data.get("hydrogel_warmup_done_logged", False)

        hydro_position = state.position.get(HYDRO_SYMBOL, 0)
        ts = state.timestamp

        if HYDRO_SYMBOL not in state.order_depths:
            hydro_quote_state = "NO_BOOK"
            if hydro_quote_state != hydro_prev_state:
                print(f"[HYDROGEL] tick={ts} pos={hydro_position} fv=- bid=- ask=- state={hydro_quote_state}")
        else:
            hydro_depth: OrderDepth = state.order_depths[HYDRO_SYMBOL]
            if not hydro_depth.buy_orders or not hydro_depth.sell_orders:
                hydro_quote_state = "ONE_SIDED"
                if hydro_quote_state != hydro_prev_state:
                    print(f"[HYDROGEL] tick={ts} pos={hydro_position} fv=- bid=- ask=- state={hydro_quote_state}")
            else:
                best_bid = max(hydro_depth.buy_orders.keys())
                best_ask = min(hydro_depth.sell_orders.keys())
                mid = (best_bid + best_ask) / 2.0

                if hydro_ema is None:
                    hydro_ema = mid
                else:
                    hydro_ema = HYDRO_EMA_ALPHA * mid + (1.0 - HYDRO_EMA_ALPHA) * hydro_ema
                hydro_n_ticks += 1

                spread = best_ask - best_bid

                if spread < HYDRO_MIN_QUOTE_SPREAD:
                    hydro_quote_state = "SKIP_TIGHT"
                    bid_price = ask_price = None
                elif hydro_n_ticks <= HYDRO_WARMUP_TICKS:
                    bid_price = best_bid
                    ask_price = best_ask
                    hydro_quote_state = "WARMUP_JOIN"
                else:
                    skew = round(HYDRO_SKEW_ALPHA * hydro_position)
                    ema_bid_cap = hydro_ema - HYDRO_BID_EDGE
                    ema_ask_floor = hydro_ema + HYDRO_ASK_EDGE
                    raw_bid = min(best_bid + 1, ema_bid_cap)
                    raw_ask = max(best_ask - 1, ema_ask_floor)
                    bid_price = math.floor(raw_bid - skew)
                    ask_price = math.ceil(raw_ask - skew)
                    hydro_quote_state = "ACTIVE"

                hydro_orders: list[Order] = []
                if bid_price is not None and ask_price is not None:
                    max_buy = max(0, HYDRO_POS_LIMIT - hydro_position)
                    max_sell = max(0, HYDRO_POS_LIMIT + hydro_position)
                    bid_volume = min(HYDRO_QUOTE_SIZE_CAP, max_buy)
                    ask_volume = min(HYDRO_QUOTE_SIZE_CAP, max_sell)
                    if bid_volume > 0:
                        hydro_orders.append(Order(HYDRO_SYMBOL, bid_price, bid_volume))
                    if ask_volume > 0:
                        hydro_orders.append(Order(HYDRO_SYMBOL, ask_price, -ask_volume))
                if hydro_orders:
                    result[HYDRO_SYMBOL] = hydro_orders

                bid_str = bid_price if bid_price is not None else "-"
                ask_str = ask_price if ask_price is not None else "-"

                if hydro_quote_state == "ACTIVE" and not hydro_warmup_done_logged:
                    print(f"[HYDROGEL] WARMUP_DONE ema={hydro_ema:.2f} first_active_tick={ts} bid_edge={HYDRO_BID_EDGE} ask_edge={HYDRO_ASK_EDGE}")
                    hydro_warmup_done_logged = True

                hydro_sampled = (ts % 10000 == 0)
                hydro_state_changed = (hydro_quote_state != hydro_prev_state)
                if hydro_sampled or hydro_state_changed:
                    print(f"[HYDROGEL] tick={ts} pos={hydro_position} fv={hydro_ema:.2f} bid={bid_str} ask={ask_str} state={hydro_quote_state}")

        trader_data["hydrogel_ema"] = hydro_ema
        trader_data["hydrogel_n_ticks"] = hydro_n_ticks
        trader_data["hydrogel_prev_state"] = hydro_quote_state
        trader_data["hydrogel_warmup_done_logged"] = hydro_warmup_done_logged

        # ---------------------------------------------------------------
        # Module 2 — VELVETFRUIT_EXTRACT (verbatim from trader-r3-vev-mm-v1.py)
        # ---------------------------------------------------------------
        vev_ema = trader_data.get("vev_ema")
        vev_n_ticks = trader_data.get("vev_n_ticks", 0)
        vev_prev_state = trader_data.get("vev_prev_state")
        vev_warmup_done_logged = trader_data.get("vev_warmup_done_logged", False)

        vev_position = state.position.get(VEV_SYMBOL, 0)

        if VEV_SYMBOL not in state.order_depths:
            vev_quote_state = "NO_BOOK"
            if vev_quote_state != vev_prev_state:
                print(f"[VEV] tick={ts} pos={vev_position} fv=- bid=- ask=- state={vev_quote_state}")
        else:
            vev_depth: OrderDepth = state.order_depths[VEV_SYMBOL]
            if not vev_depth.buy_orders or not vev_depth.sell_orders:
                vev_quote_state = "ONE_SIDED"
                if vev_quote_state != vev_prev_state:
                    print(f"[VEV] tick={ts} pos={vev_position} fv=- bid=- ask=- state={vev_quote_state}")
            else:
                vev_best_bid = max(vev_depth.buy_orders.keys())
                vev_best_ask = min(vev_depth.sell_orders.keys())
                vev_mid = (vev_best_bid + vev_best_ask) / 2.0

                if vev_ema is None:
                    vev_ema = vev_mid
                else:
                    vev_ema = VEV_EMA_ALPHA * vev_mid + (1.0 - VEV_EMA_ALPHA) * vev_ema
                vev_n_ticks += 1

                vev_spread = vev_best_ask - vev_best_bid

                if vev_spread < VEV_MIN_QUOTE_SPREAD:
                    vev_quote_state = "SKIP_TIGHT"
                    vev_bid_price = vev_ask_price = None
                elif vev_n_ticks <= VEV_WARMUP_TICKS:
                    vev_bid_price = vev_best_bid
                    vev_ask_price = vev_best_ask
                    vev_quote_state = "WARMUP_JOIN"
                else:
                    vev_skew = round(VEV_SKEW_ALPHA * vev_position)
                    vev_ema_bid_cap = vev_ema - VEV_BID_EDGE
                    vev_ema_ask_floor = vev_ema + VEV_ASK_EDGE
                    vev_raw_bid = min(vev_best_bid + 1, vev_ema_bid_cap)
                    vev_raw_ask = max(vev_best_ask - 1, vev_ema_ask_floor)
                    vev_bid_price = math.floor(vev_raw_bid - vev_skew)
                    vev_ask_price = math.ceil(vev_raw_ask - vev_skew)
                    vev_quote_state = "ACTIVE"

                vev_orders: list[Order] = []
                if vev_bid_price is not None and vev_ask_price is not None:
                    vev_max_buy = max(0, VEV_POS_LIMIT - vev_position)
                    vev_max_sell = max(0, VEV_POS_LIMIT + vev_position)
                    vev_bid_volume = min(VEV_QUOTE_SIZE_CAP, vev_max_buy)
                    vev_ask_volume = min(VEV_QUOTE_SIZE_CAP, vev_max_sell)
                    if vev_bid_volume > 0:
                        vev_orders.append(Order(VEV_SYMBOL, vev_bid_price, vev_bid_volume))
                    if vev_ask_volume > 0:
                        vev_orders.append(Order(VEV_SYMBOL, vev_ask_price, -vev_ask_volume))
                if vev_orders:
                    result[VEV_SYMBOL] = vev_orders

                vev_bid_str = vev_bid_price if vev_bid_price is not None else "-"
                vev_ask_str = vev_ask_price if vev_ask_price is not None else "-"

                if vev_quote_state == "ACTIVE" and not vev_warmup_done_logged:
                    print(f"[VEV] WARMUP_DONE ema={vev_ema:.2f} first_active_tick={ts} bid_edge={VEV_BID_EDGE} ask_edge={VEV_ASK_EDGE} size={VEV_QUOTE_SIZE_CAP}")
                    vev_warmup_done_logged = True

                vev_sampled = (ts % 10000 == 0)
                vev_state_changed = (vev_quote_state != vev_prev_state)
                if vev_sampled or vev_state_changed:
                    print(f"[VEV] tick={ts} pos={vev_position} fv={vev_ema:.2f} bid={vev_bid_str} ask={vev_ask_str} state={vev_quote_state}")

        trader_data["vev_ema"] = vev_ema
        trader_data["vev_n_ticks"] = vev_n_ticks
        trader_data["vev_prev_state"] = vev_quote_state
        trader_data["vev_warmup_done_logged"] = vev_warmup_done_logged

        return result, conversions, json.dumps(trader_data)