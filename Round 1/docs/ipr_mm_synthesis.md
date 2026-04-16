# IPR Market-Making Synthesis

User's analysis on whether RR/KELP-style MM logic applies to IPR,
given its drifting fair value. Written 2026-04-16 during Pass 3 prep.
Binding input for IPR strategy design.

---

Short answer: yes, in principle — but with a critical caveat that changes the design.

**Why the analogy works**

RAINFOREST_RESIN (RR) works for market making because the "fair value" is stable and known (flat mid). You quote tight around it, capture the bid-ask bounce, and as long as the mid doesn't run away from you, inventory mean-reverts naturally — any long you accumulate gets unwound when price ticks back up, any short gets unwound when it ticks back down.

IPR has the same bid-ask bounce structure (your lag-1 autocorr of −0.488 confirms it — same magnitude as ACO). Your variance ratios (VR(2)=0.511, halving each doubling) are the classic signature of bid-ask bounce. So the micro-level inefficiency RR exploits *is present in IPR*. You can absolutely quote around a fair value and scalp the bounce.

The twist is that the fair value isn't flat — it's a linear function of time: `fv(t) = fv(0) + drift·t`. That's fine conceptually. You just quote `fv(t) ± spread/2` instead of `constant ± spread/2`. Call this a "drifting fair value market maker."

**The critical caveat: inventory risk is asymmetric**

Here's where RR and IPR diverge hard.

On RR, if you accidentally accumulate a short position, no big deal — the mid is flat, price will tick back up, you'll unwind. Inventory is *naturally mean-reverting* because the fair value is.

On IPR, if you accumulate a short position, **the fair value keeps walking away from you at +1001.3/day**. Every tick, your short gets deeper underwater. There's no mean reversion to bail you out — the drift *is* the process.

This is an inventory asymmetry problem. Going long is "free" (drift works for you while you wait to unwind). Going short is bleeding (drift works against you). A symmetric RR-style market maker treats both sides equally and will get slaughtered on the short side.

**What this means for design**

If you wanted to do market making on IPR, you'd need:

1. **Asymmetric quoting.** Quote tight on the bid (happy to accumulate longs — drift pays you to hold them), quote wider on the ask or skip asks entirely when you're flat/short. You only sell from an existing long inventory, never to go short.

2. **A long-only floor.** Minimum inventory = 0 (or better, some positive number). Never let yourself go net short. This is structurally different from RR where you're symmetric around zero.

3. **Reconciliation with Config A.** And this is the real question — Config A is *already* "buy to +80 and hold." If you're pinned at the position limit, there's no room to market-make at all. You literally cannot accumulate more longs, so the bid side is dead. You could potentially market-make on the *way up* to the limit (quote tight bids, get filled, skim occasional asks when price spikes above your fair value), but once you hit 80 you're just holding.

**The realistic synthesis**

The interesting question isn't "MM instead of Config A" — it's "can MM improve Config A's *entry*?" Right now your entry plan is "take to 80 by ts≈400" (i.e., cross the spread and pay up). A drifting-fair-value market maker could instead post passive bids at `fv(t) − spread/2` during the accumulation phase, filling at better prices and capturing the bounce on the way up. Same end state (long 80), better cost basis.

Your `skim_size=5` is already gesturing at this — once you're pinned at 80, you skim 5 units off the top when price spikes, rebuy on the dip. That's essentially one-sided market making around the drift. You could make it more aggressive: larger skim size, tighter skim triggers, as long as you're confident you can refill before end of day.

**Where the RR analogy breaks down entirely**

RR market making works because the fair value is *known and stable*. On IPR, your fair value estimate is `fv(0) + drift·t`, and **the drift is the thing you're uncertain about** (IPR-5 risk from your other analysis). If the drift reverses intraday, your quotes are anchored to a fair value that's now wrong by a growing amount per tick, and you'll accumulate a position at prices that look good relative to your (stale) fair value but are actually disastrous. RR doesn't have this failure mode because there's no drift parameter to be wrong about.

So: yes, MM is compatible with the data structure. But the drift-dependence is exactly the same existential risk as Config A, just dressed up differently. It doesn't give you a new source of edge independent of the drift thesis — it gives you a *better entry and skim* on top of the drift thesis.

**Bottom line:** Use MM-style logic for entry (passive bids on the way to the limit) and for skim (tighter, more active than size=5). Don't treat it as a standalone strategy, and keep the long-only asymmetry hard-coded — never quote an ask that could take you net short.