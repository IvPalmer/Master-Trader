# Smart agentic copier — next steps (2026-06-03)

Status: **technical feasibility of interpretation+tracking VALIDATED**
([`SMART-AGENT-VALIDATION-2026-06-03.md`](SMART-AGENT-VALIDATION-2026-06-03.md)). The
"can a smart agent read and follow Dennis's book" question is answered yes (87/87 intent).

**UPDATE 2026-06-03 (FINAL, supersedes the NO-GO below) — Track A reopened Track B.** The
A.1 NO-GO tested the WRONG member behaviour (market entry + his discretionary closes = −31%).
Testing the FULL entry×exit matrix (`track_a_matrix.py`) — what a real member does, **limit in
the posted zone + his posted TP ladder** — flips it POSITIVE: **+6% (near-edge, fills 31/32) to
+33% (patient midpoint, fills 18/32)** net of costs, verified not survivorship (the 14 missed
mid-limit trades averaged +0.14R, not avoided losers), winners distributed (BTC-1609/HYPE/
BTC-1644/BTC-1634). Codex-reviewed verdict: *there is copyable edge under patient limit
execution + posted TPs* — concentrated (survives ex-top, not ex-top-2), placement-sensitive,
**one month / 31 trades**, so "promising, not proven." See
[`TRACK-A-FILL-FEASIBILITY-2026-06-03.md`](TRACK-A-FILL-FEASIBILITY-2026-06-03.md).

⇒ The gating question is no longer "does any edge exist" (it does, in-sample) but **"does it
hold OUT of sample."** Next = a multi-month limit-in-zone + posted-TP run.

> The NO-GO text below is RETAINED for the record but SUPERSEDED — it was a methodology error
> (wrong fill model), not a finding about his signals.

---

## Track A — Does the *edge* survive? → ran A.1, NO-GO

The agent reads perfectly. That is necessary, not sufficient.

1. **PnL of the validated intent stream, net of costs.** ✅ **DONE — NO-GO** (`track_a_pnl.py`).
   Applied a cost model (cost_R = roundtrip / sl_dist_pct; market roundtrip 0.20%) to the
   harness-computed gross R of the 20 closed LLM-managed May positions. Gross +1.65R → **net
   market −0.10R**, **−0.82R ex-top-winner**. Cost-fragile, concentration-fragile, and the
   only positive (maker/limit +1.30R) is the less-achievable fill. Underpowered (20 trades)
   but operationally insufficient. **The reading edge does not convert to a trading edge on
   this month.** Zero new LLM spend (cached intents).

The remaining Track-A items below were the planned follow-ups *if A.1 had cleared.* Since it
did not, they are now "only if we ever revisit with a bigger sample" — not active work:

2. *(deferred)* **Model the between-message stop.** Current replay closes only on a posted
   message; a real copier places exchange stops, so some positions should stop before Dennis
   posts management. Codex flagged this as the biggest reason A.1's gross **flatters** the
   result — modelling it would likely make the book *worse*, reinforcing the no-go.
3. *(deferred)* **Sizing fidelity.** 3 of 20 openers lacked curated sl_dist (1585 isn't even a
   clean opener — a data smell to clean before any re-test).
4. *(deferred)* **Adverse-selection under smart entry** — only meaningful with a larger,
   multi-month, stop-aware replay.

**Conclusion: shelve productionization.** The reading substrate is a reusable asset
(claim-auditing, journaling, the thing that debunked the +2702%) and stands on its own. Do
not build Track B unless a larger, stop-aware execution replay across multiple months stays
net-positive AND survives concentration — none of which current evidence supports.

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

- **A.1 (the gate) ran → NO-GO.** Productionization is not justified by current evidence.
  Venue (B4) is moot until/unless a future larger sample reopens the question.
- **What's banked regardless:** the causality-enforced reading substrate (87/87 intent
  fidelity, 11/11 tests) is a validated, reusable asset — useful for claim-auditing any
  signaler's channel and for trade journaling, independent of whether we ever copy-trade.

## Where this lands

The session's question — *"a mechanical copier can't, but could a smart agent?"* — is fully
answered on both halves:
- **Reading/tracking: YES**, validated at scale (the hard, novel part).
- **Profitable copying: NOT on this evidence** — perfect reading is consumed by execution
  costs; Dennis's edge is the WEEX fill, which late-relayed text cannot reproduce.

Recommend **shelving the copier** and keeping the substrate on the shelf as tooling. Reopen
only with a fundamentally larger dataset (multiple months / signalers) and a stop-aware
execution model — and only if there's appetite to chase a thin, unproven edge.
