"""
a3_tagging.py — A0 (Pass 2.6) tagging adapter module
======================================================

Re-exports the A3 decomposition machinery from aco_v8_decomp.py so that
downstream Pass 2.6 agents (A1, A2, ...) can import from a stable name:

    from a3_tagging import (
        run_decomposition,
        parse_log_activities,
        parse_log_trade_history,
        classify_our_fills,
        attribute_pnl,
        plot_cumulative_buckets,
        V8_ACO_PNL_GT,
        QO5_ACO_PNL_GT,
    )

The underlying implementation lives in aco_v8_decomp.py (unchanged).
This module is the hard gate: if it imports cleanly, A3 machinery is
available to all downstream agents.

Added constants for Pass 2.6:
  QO5_ACO_PNL_GT  : ground-truth ACO PnL for v9-qo5-ms8-te3 (verified A0)
"""

import os
import sys

# Ensure the analysis directory is on sys.path regardless of cwd
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from aco_v8_decomp import (  # noqa: F401
    run_decomposition,
    parse_log_activities,
    parse_log_trade_history,
    classify_our_fills,
    attribute_pnl,
    plot_cumulative_buckets,
    mmbot_mid_from_levels,
    V8_ACO_PNL_GT,
    ACO_CFG,
    EOD_START,
    LIMIT,
)

# Ground-truth ACO PnL for v9-qo5-ms8-te3 (verified in Pass 2.6 A0 via fresh
# prosperity4btest runs; matches baselines.json exactly)
QO5_ACO_PNL_GT = {-2: 9201.0, -1: 10793.0, 0: 9013.0}

# v9-qo5 ACO CFG — verbatim from trader-v9-aco-qo5-ms8-te3.py
QO5_ACO_CFG = {
    "ema_alpha":       0.12,
    "quote_offset":    5,
    "take_edge":       3,
    "max_skew":        8,
    "panic_threshold": 0.75,
}
