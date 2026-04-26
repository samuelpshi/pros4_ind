# VEV Mean-Reversion v2 Hybrid Design — collapsed

Owner: P3_vev_meanrev
Date: 2026-04-26
Status: closed without sketch.

The original Task 6 brief proposed a v2 hybrid that would gate the MM
template's aggressive-take leg behind a |z|-score filter, reasoning
that the take-side bleed was the dominant problem. The pre-sweep
attribution invalidates that motivation: the forward-50-tick edge per
fill is **negative in BOTH the aggressive zone (avg -61 to -110) AND
the passive zone (avg -10 to -57)**, and the passive zone holds 70% of
the fills. A z-gate addresses only ~30% of the bleed and leaves the
larger source — passive fills at the wall against informed flow —
completely untouched. Combined with the Option C force-flatten test
showing that **6.8× the half-spread cost** of the 3-day mean came from
a favourable closing-direction MTM rather than from any captureable
edge, no z-gated hybrid built on this MM template can plausibly
produce positive expected value at the local-backtester fill rate. We
do not pursue the v2 hybrid sketch and instead ship the rank-3 baseline
under the honest framing in `vev_meanrev_comparison.md`. If we revisit
VEV in R4+ it should be a clean architectural restart (likely event-
driven rather than continuous-quote), not an extension of this module.
