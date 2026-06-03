# Agentic copier — plan (2026-05-31)

Capstone of the validation session. We proved a **mechanical** copier of Dennis's
signals loses (−31% market / −11% limit on the +2702% May ledger; limit misses 13 of
14 winners to adverse selection). His edge is **discretionary, averaged, live position
management** — the posts are only a shadow of it. A skilled human member who reads each
post *in context of the open position* and watches the chart can approximate him; the
goal is an **agent that automates that judgment**, not a parser. Codex-reviewed.

## Core principle
**The LLM is a reasoning MODULE, not the trading system.** Deterministic code owns
state, risk, sizing, execution, reconciliation, and kill switches. The LLM only
*interprets intent* and *proposes* actions. If the LLM can place orders, resize, or
override risk, the design is wrong.

## Architecture (layers)
```
Telegram ingest + price/account feed
  → message normalization + event store (persist BEFORE any decision)
  → LLM interpretation IN CONTEXT (Claude Code runtime, Max sub — NOT API key)
  → position-state engine        (event-sourced; Dennis-inferred state + OUR actual state)
  → decision engine              (deterministic where possible)
  → risk guard                   (hard, non-LLM gate — written like custody code)
  → Binance futures executor     (NOT WEEX — WEEX freezes profitable bots)
  → reconciler                   (exchange = source of truth; freeze on mismatch)
  → audit/replay store           (same event format offline & live)
```

**Position-state engine is the most important piece.** Event-sourced ledger so
"add back what I closed" / "my average is 77,240" actually resolve. Track per symbol:
Dennis-inferred (side, avg, size-state starter/partial/full/reduced/runner, stop, TPs,
uncertainty) AND our actual (Binance size, avg, leverage, open orders, realized/unreal
PnL, max adverse excursion, remaining risk budget). Never act on "latest message only" —
that's exactly why mechanical copying loses.

**LLM does:** interpret ambiguous text, resolve references ("what I closed", "lower"),
distinguish his-position vs advice vs narration, translate staged entries into candidate
plans, decide when NO action is right. **LLM does NOT:** balance/leverage/liquidation
math, stop validation, order submission, fill reconciliation, PnL, kill decisions.
LLM returns schema-validated JSON {intent, symbol, side, confidence, conditions,
suggested_action, invalid_if, reasoning}; deterministic code decides if it's executable.

## Two loops
- **Message loop** (on post): load context + state → LLM interpret → update inferred
  state → create/modify/cancel plan → risk-check → execute if approved → audit.
- **Market-watch loop** (on price/tick): evaluate watchers, stops, invalidations, stale
  plans, risk limits; execute triggered plans only if still valid; reconcile.
Many posts are NOT immediate orders: "we'll add at 81,300–81,700" → a **watcher**
(zone, max-age, requires-existing-position, invalidate-if), re-evaluated when price
arrives. "wait for Asia open" → time-watcher that **re-runs interpretation** with fresh
price, never blindly fires the old plan. Ambiguity default order:
**NO_ACTION > WATCHER > SMALLER_SIZE > FULL_ACTION** (capital preservation).

## Hard risk guardrails (non-negotiable, operator is risk-averse — start FAR below Dennis)
- Initial trade risk **0.25–0.50%**; max fully-built trade **1.0%**; max daily loss
  **1.0%**; hard weekly stop **3.0%**; max open risk across book 1–2%; max leverage cap
  regardless of his x5–7; max open symbols; drawdown-from-HWM lockout; consecutive-loss
  cooldown; halt on API/exchange instability.
- Per-position: mandatory stop/invalidation; no size increase if stop unknown or
  unrealized loss past threshold; max time-in-trade; slippage + liquidation-proximity caps.
- **Averaging guard (the dangerous part — his −371% NEAR was an averaged blow-up):**
  never average without a known invalidation; adds must consume remaining risk budget;
  max 2 adds, max 2× initial size (NOT 5×); no add after structural invalidation or sharp
  adverse move unless pre-planned staged entry; **never widen a stop without reducing
  size**; if LLM says "averaging but stop unclear" → reject.
- **LLM confidence gates:** NO_ACTION any; CREATE_WATCHER ≥0.60; OPEN_STARTER ≥0.75;
  ADD ≥0.85; widen-stop forbidden by default. Reject on bad schema / uncertain symbol or
  side / missing stop for a risk-increasing action / promotional-or-retrospective text.

## Validation — the crux (mechanical LOSES, so we must PROVE the agent adds edge first)
- **Stage 0 — replay parity:** same event format + same decision/risk code offline &
  live; simulated slippage/fees/funding; delayed-message + partial-fill model; **no
  lookahead** (LLM only sees messages available at that replay timestamp). If the offline
  agent can see the future, results are worthless.
- **Stage 1 — historical replay** vs 4 baselines (mechanical-market −31%, patient-limit,
  conservative-no-averaging, Dennis-adjusted). HARD FAIL if: net ≤0 after costs; max DD
  >10% at 1× risk; any trade loses > its cap; profit comes from one uncapped averaged
  winner; or it misses most winners like limit did. **Target: capture 30–50% of his
  return with materially lower drawdown and no uncapped averaging.** Don't annualize one
  month.
- **Stage 2 — walk-forward / PROMPT FREEZE.** April/May are now **contaminated** (we
  tuned on them) — useful for engineering, weak as proof. Real proof = new unseen data,
  prompts/policies/thresholds frozen before the run.
- **Stage 3 — live paper, 4–6 weeks / 50+ actionable signals:** real Telegram latency,
  real Binance stream, simulated execution, full reconciliation, operator dashboard.
  Pass = positive expectancy net of costs, DD within limits, zero risk-rule violations,
  zero hallucinated trades, no state drift, **beats a conservative non-LLM baseline.**
  Also score decision quality (correct no-action rate, add/reduce accuracy, post→decision
  latency, % LLM proposals rejected). If most profit is 1–2 trades → keep papering.
- **Stage 4 — tiny capital ($100–250), proves OPERATIONS not profit:** risk 0.1–0.25%/
  trade, no compounding month 1, disable on any guardrail breach. Graduate after 30 days
  with zero reconciliation failures / zero unbounded exposure / no schema-failure trades /
  no emergency intervention / live ≈ paper.

## Build order
1. **State + replay** — event schema, position-state + watcher engines, deterministic
   risk guard, offline replay, LLM output schema, audit log. (No live execution.)
2. **Agent interpretation** — Claude Code runtime wrapper, context-pack builder, golden
   test set of ambiguous Dennis messages, schema validator, confidence policy, no-action
   bias. (Paper decisions only.)
3. **Offline agent replay** — run April/May no-lookahead vs baselines; attribute PnL by
   decision type (entries/adds/exits/avoided-trades). Reject if it only wins via big
   averaged risk.
4. **Live paper** — same code path, Binance market data, simulated fills, reconciliation,
   daily report.
5. **Tiny capital** — Binance real, reduced size, hard kill switches, no autonomous
   stop-widening, no high-confidence override path.

Reuse existing infra: Telethon listener, Claude classifier (98.8%), hardened FastAPI
receiver (slippage gate / atomic dedup / 3-state response / reconciler / operator
endpoints), the offline harness + April/May datasets. Execute on **Binance** (not WEEX).

## Opinionated v1 (codex) — and the honest stance
First profitable version should **NOT fully mirror Dennis.** It should: (1) enter only on
a clear actionable setup at a still-acceptable price; (2) use watchers for planned levels
instead of chasing posts; (3) **manage risk BETTER than Dennis** (cap adds, cut
ambiguity). It may underperform him in a hot month — acceptable. The goal is to prove
**LLM interpretation + state beats mechanical copying under conservative risk + realistic
latency, without importing his blow-up risk.**

**If it can't beat mechanical copying conservatively, it has no edge. If it only beats it
by averaging aggressively, it isn't safe.** Abandon if: after 2–3 months live-paper no
positive expectancy net of costs; live-paper underperforms the conservative baseline over
50+ signals; any averaged trade exceeds its planned max loss; or entry-slippage vs
actionable-post-price exceeds the edge for 3–4 weeks. Don't tune indefinitely — that's
strategy mining.

Open risk acknowledged: his +120–130% may be leverage/variance/survivorship/unposted
discretion, not copyable skill. The validation gates exist to find that out cheaply,
before capital.
