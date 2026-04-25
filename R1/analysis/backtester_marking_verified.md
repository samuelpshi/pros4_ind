# Backtester Marking Convention — Empirical Verification

**Date:** 2026-04-16
**Author:** Agent 6 (Backtester Verifier), Pass 4
**Status:** GATE result — verdict below controls whether Pass 4 continues.

---

## 1. Setup Summary

Two throwaway traders were written (`_mark_test_aco.py` and `_mark_test_ipr.py`). Each buys exactly 1 unit of its target product at timestamp 0 using a limit order at the current best ask (guaranteeing a fill if any ask volume exists), then submits no further orders for the remainder of the day. This isolates the open-inventory PnL for a single unit held from fill through end-of-day. Both were run against `prosperity4btest` on round 1, day 0, producing independently verifiable logs. The fill price and the final reported PnL were then compared against four candidate marking formulas: mid, last trade, bid, and ask.

---

## 2. Fee Structure

Source: `Round 1/docs/r1_product_mechanics.md`, sections "Fee / Tariff / Conversion Mechanics" for ACO and IPR.

- **ACO:** "No explicit transaction fee or per-trade tariff is described for ACO in the algo-trading primer." No conversion mechanic confirmed for Round 1.
- **IPR:** "No per-trade transaction fee is described for IPR." No conversion mechanic confirmed for Round 1.

**Conclusion: total_fees = 0 for both products.** All candidate formulas simplify to `marked_price - fill_price`.

---

## 3. ACO Numeric Evidence

**Backtest run:** `prosperity4btest "Round 1/traders/_mark_test_aco.py" 1-0 --out runs/mark_test_aco.log`

**Fill confirmation:** Trade History entry at timestamp 0 shows `buyer: "SUBMISSION", symbol: "ASH_COATED_OSMIUM", price: 10013, quantity: 1`. Fill confirmed.

| Field | Value | Source |
|-------|-------|--------|
| fill_price | 10013 | Trade History, t=0, buyer=SUBMISSION |
| final_bid | 9998 | Activities log, t=999900, bid_price_1 |
| final_ask | 10016 | Activities log, t=999900, ask_price_1 |
| final_mid | 10007.0 | Activities log, t=999900, mid_price column |
| final_last_trade | 9999 | Trade History, last ACO trade at t=998400 |
| total_fees | 0 | Per fee structure above |
| reported_final_pnl | -6.0 | Activities log, t=999900, profit_and_loss column |

**Candidate formula results:**

| Formula | Calculation | Result | Matches reported (-6.0)? |
|---------|-------------|--------|--------------------------|
| PnL_mid | 10007.0 - 10013 | **-6.0** | YES (exact) |
| PnL_last | 9999 - 10013 | -14.0 | No (diff = 8.0) |
| PnL_bid | 9998 - 10013 | -15.0 | No (diff = 9.0) |
| PnL_ask | 10016 - 10013 | +3.0 | No (diff = 9.0) |

**Discrimination check:** `|final_mid - final_last_trade| = |10007.0 - 9999| = 8.0`, which is well above the 0.5-tick tolerance. The four candidates are cleanly separated; PnL_mid is the unambiguous match.

**Match:** **PnL_mid**

---

## 4. IPR Numeric Evidence

**Backtest run:** `prosperity4btest "Round 1/traders/_mark_test_ipr.py" 1-0 --out runs/mark_test_ipr.log`

**Fill confirmation:** Trade History entry at timestamp 0 shows `buyer: "SUBMISSION", symbol: "INTARIAN_PEPPER_ROOT", price: 12006, quantity: 1`. Fill confirmed.

| Field | Value | Source |
|-------|-------|--------|
| fill_price | 12006 | Trade History, t=0, buyer=SUBMISSION |
| final_bid | 12990 | Activities log, t=999900, bid_price_1 |
| final_ask | 13010 | Activities log, t=999900, ask_price_1 |
| final_mid | 13000.0 | Activities log, t=999900, mid_price column |
| final_last_trade | 13005 | Trade History, last IPR trade at t=998400 |
| total_fees | 0 | Per fee structure above |
| reported_final_pnl | 994.0 | Activities log, t=999900, profit_and_loss column |

**Candidate formula results:**

| Formula | Calculation | Result | Matches reported (994.0)? |
|---------|-------------|--------|---------------------------|
| PnL_mid | 13000.0 - 12006 | **994.0** | YES (exact) |
| PnL_last | 13005 - 12006 | 999.0 | No (diff = 5.0) |
| PnL_bid | 12990 - 12006 | 984.0 | No (diff = 10.0) |
| PnL_ask | 13010 - 12006 | 1004.0 | No (diff = 10.0) |

**Discrimination check:** `|final_mid - final_last_trade| = |13000.0 - 13005| = 5.0`, which is well above the 0.5-tick tolerance. The four candidates are cleanly separated; PnL_mid is the unambiguous match.

**Match:** **PnL_mid**

---

## 5. Verdict

**MID CONFIRMED**

Both products independently match the PnL_mid formula exactly (within 0.0 of the reported value, tolerance 0.5). On both products, final_mid and final_last_trade differ by more than the tolerance (8.0 for ACO, 5.0 for IPR), so the discrimination is clean and unambiguous. Both fills were confirmed via Trade History (buyer=SUBMISSION at t=0). Positions at end of day were non-zero (ACO position = +1 throughout; IPR position = +1 throughout), verified by PnL tracking.

---

## 6. PLAN.md ACO-5 Alignment

**Yes.** ACO-5 in r1_product_mechanics.md states: "RESOLVED BY PLAN.md Pass 3: local backtester uses mark-to-mid (backtest.py lines 239-247); accept any discrepancy vs IMC's internal marking as acceptable per CLAUDE.md Hard Rule 4." The empirical result confirms `prosperity4btest` also uses mark-to-mid. The objective function used for ACO calibration (reversion_beta = -0.45, adverse_volume = 15) is valid under the correct marking convention.

---

## 7. Log File Paths

- ACO log: `/Users/samuelshi/IMC-Prosperity-2026-personal/runs/mark_test_aco.log`
- IPR log: `/Users/samuelshi/IMC-Prosperity-2026-personal/runs/mark_test_ipr.log`
- ACO test trader: `/Users/samuelshi/IMC-Prosperity-2026-personal/Round 1/traders/_mark_test_aco.py`
- IPR test trader: `/Users/samuelshi/IMC-Prosperity-2026-personal/Round 1/traders/_mark_test_ipr.py`
