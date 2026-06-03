# Smart agentic copier — next steps (2026-06-03)

Status: **technical feasibility of interpretation+tracking VALIDATED**
([`SMART-AGENT-VALIDATION-2026-06-03.md`](SMART-AGENT-VALIDATION-2026-06-03.md)). The
"can a smart agent read and follow Dennis's book" question is answered yes. What remains is
everything *downstream* of reading: does following it actually make money, and can we
execute it under our real constraints.

The work splits into two independent tracks. **Track A is cheap and answers the only
question that matters before any build. Track B is the build, and should not start until
Track A clears.**

---

## Track A — Does the *edge* survive? (cheap, do first)

The agent reads perfectly. That is necessary, not sufficient. The prior ceiling test showed
mechanical copying loses on costs; this track asks whether *smart* management changes that.

1. **PnL of the validated intent stream, net of costs.** Wire the 178 graded LLM decisions
   through a fill+cost model (the existing `cost_ceiling.py` machinery: WEEX/Binance fees,
   slippage, funding, realistic fill timing). We have the correct *intents* now — feed them
   to execution and see the R. This is the direct test the ceiling test couldn't run because
   it lacked correct intents. **Zero new LLM spend** (intents are cached).
   - Kill-gate: if the smart-managed book is still net-negative after costs, the reading
     edge does not convert to a trading edge, and the project stops at "interesting, not
     fundable" — exactly as the operator pre-agreed.

2. **Model the between-message stop.** Current replay only closes on a posted message. Add
   hard-SL auto-triggering on the price loop (the harness already has the oracle + ledger
   SL). This is the single biggest fidelity gap for PnL (not for intent).

3. **Sizing fidelity, not just intent.** Grade the `frac` / `frac_of_remaining` compounding
   against the curated `events[]` amounts (the harness math was unit-tested exact; confirm
   end-to-end on the real run). Intent ≠ dollars; this closes that.

4. **Adverse-selection check under smart entry.** The −8.7%/+18% reachable-vs-unreachable
   split was the mechanical killer. Re-measure it when the *agent* chooses entry behavior
   (market vs wait-for-zone vs skip) rather than a fixed rule. Does judgment beat the
   adverse-selection tax, or not?

If Track A clears (positive expectancy net of costs, edge not from one tail trade), **then**
Track B is justified. If it doesn't, document and shelve — the reading substrate is still a
reusable asset (claim-auditing, journaling, the very thing that debunked the +2702%).

---

## Track B — Productionize (only if Track A clears)

Per the original [`AGENTIC-COPIER-PLAN-2026-05-31.md`](AGENTIC-COPIER-PLAN-2026-05-31.md)
architecture, now with a validated interpreter core.

1. **Live two-loop runtime.** Message loop (interpret on post) + market-watch loop (price
   ticks → fills, stops, watcher triggers). The substrate's oracle/ledger/audit port
   directly; replace the offline feed with a live Telethon + price stream.
2. **Execution-semantics realism** — `reduce_only`, close→cancel-resting-SL/TP, partial-fill
   handling, the `UNREPRODUCIBLE` tag for BTC continuous-averaging (a single-signal copier
   can't mirror his averaged swing — the agent must flag, not fake it).
3. **Hard risk guard** (the operator is risk-averse — start far below Dennis): the
   non-LLM gate from the plan (% -equity risk, daily/weekly stops, max adds, leverage cap,
   DD lockout). The LLM proposes; this gate disposes.
4. **Venue reality — WEEX.** Dennis confirmed (via Eduardo, 2026-06-02) that trades must be
   on WEEX. But validation memory flags WEEX *freezes profitable bots* and the affiliate
   funnel. Decision required before any capital: WEEX (his constraint, custody risk) vs
   Binance (our preference, but then we're not mirroring his exact fills). The historical
   replay can run all three venues (WEEX+Binance cached; HL is a Binance-proxy — no usable
   1-min history) — but *live* must pick one.
5. **Paper → tiny capital**, the plan's Stage 3–4 graduation gates, unchanged.

---

## Decision points for the stakeholder

- **A1 (PnL net of costs) is the gate.** Recommend running it next — it's cheap, uses cached
  intents, and tells us if there's any point in Track B at all.
- **Venue (B4)** is a real fork that needs an explicit call (WEEX-only-and-its-risks vs
  Binance-but-not-his-fills). Not urgent until Track A clears.
- Everything else is execution detail on top of those two.

## Immediate, concrete

Run **Track A.1** (PnL of the cached intent stream net of costs) — no new LLM spend, directly
extends `cost_ceiling.py`, and is the honest go/no-go before any further build.
