# Smart agentic copier — technical-feasibility validation (2026-06-03)

**Verdict: VALIDATED (technical feasibility only).** An LLM agent can interpret and track
Dennis's (Insiders Scalp) actively-managed trading book — openers, partial closes, full
closes, stop moves — message-by-message under enforced causality, at scale, where a
mechanical copier structurally cannot. **This does NOT establish profitability or execution
quality** — those are the explicitly-scoped next phase.

This supersedes the "don't build" framing of the cost-based ceiling test
([`AGENTIC-COPIER-PLAN-2026-05-31.md`](AGENTIC-COPIER-PLAN-2026-05-31.md)): that test
answered "does mechanical copying clear costs" (no). The stakeholder reframed the question
to "can a *smart* agent track his book at all" — capital/cost/risk out of scope. This
document answers that reframed question.

---

## The question

A mechanical (regex) copier cannot follow Dennis because his posts are not clean orders:
entry *zones* not prices, "from here" market calls, staged ladders, running averages, and
management by discretion ("closing around be", "got stopped", "add back what I closed").
Prior sessions proved mechanical copying loses (−31% to −41% net). The open question:
**can an LLM that reads each message in the context of the open position reconstruct and
follow his book the way a skilled human member does?**

## The substrate (causality-enforced harness)

Built under [`research/insiders_april_replication/causal_replay/`](../../research/insiders_april_replication/causal_replay/).
The design principle: **causality is enforced by the harness, never self-reported by the model.**

- **`oracle.py`** — `PointInTimeFeed` / `PriceOracle`. The ONLY module that reads raw
  message/candle files. A candle is observable at decision time T iff `t + 60000 <= T_ms`
  (fully-closed minutes only); any future query **raises `CausalityViolation`** — the
  future is *absent*, not ignored. `messages(last_n, within_ms)` windows the prompt
  *after* the causal gate (can only shrink the ≤T set, never leak forward).
- **`ledger.py`** — `PositionLedger`, harness-owned. Tracks side / size / avg / current_sl
  / status per symbol; `%`-of-remaining vs `%`-of-original compounding; watcher→filled only
  on a price-confirmed candle or an explicit Dennis declaration. The interpreter sees a
  read-only snapshot; it cannot mutate the book.
- **`interpreter.py`** — pluggable. `ClaudeCliInterpreter` (real LLM, tools/network/file
  disabled; routable to a remote `claude` via `cmd_override`) + `MockInterpreter`
  (deterministic, for unit tests). Output is a structured `Intent` with cited `Evidence`
  (msg ids + candle refs) — **no `used_only_causal_prefix` self-cert flag.**
- **`audit.py`** — re-resolves every cited ref against T through the same bounded slice.
  Rejects `future_msg` / `future_candle` / `missing_candle`. **Fail-closed gates:**
  `scalar_price` (the interpreter may not set an exit price via a raw scalar — the ledger
  derives every fill/exit from the oracle), and `unbound_sl` (an `open_meta.sl` must be
  corroborated by the text of a cited ≤T message, so a fabricated stop cannot inflate the R
  denominator).
- **`replay.py`** — streams messages + candle-close events in strict timestamp order;
  per decision: bounded prompt → interpret → audit → apply → persist.
- **`baseline.py`** — `RegexBaselineInterpreter`, the deliberately-dumb stateless comparator.
- **`tests/test_causality.py`** — 11 unit tests (oracle raises on future, future-evidence
  rejected, scalar/SL cheats rejected fail-closed, compounding math exact, watcher
  confirmation, no-global-state, model-derived `open_meta` flows). All pass.

## The runs

| Run | What | Result |
|---|---|---|
| Causal kill-test (6 hard cases, no future messages) | incl. the BTC-1609 breakeven trap | 5/5 + trap caught |
| Blind 1609 (real logged model, bounded prompt) | machine-verified zero >T data | `close_full` @ breakeven (+0.077R), audit clean — NOT the phantom +5.75R TP |
| **Full-May streaming (178 decisions)** | real Sonnet via VPS, windowed prompt, vs regex | see below |

## Headline result — full-May, message-by-message vs frozen truth

Truth file `trades_may.json` was frozen **2026-05-30**; the LLM run executed **2026-06-03**
(openers not curated against these outputs). Graded in pure Python.

| Dimension | LLM (Sonnet, causal) | Regex baseline |
|---|---|---|
| Curated openers | **32 / 32** | 0 / 32 |
| Management events (closes / partials / SL-moves) | **55 / 55** | 41 / 55 |
| **Combined intent accuracy** | **87 / 87 (100%)** | 41 / 87 |
| Causal audit violations across 178 decisions | **0** | — |

The LLM confusion matrix is perfectly diagonal. The regex baseline's 46 errors concentrate
in exactly the meaning-dependent cases that define active position management:

- `"Closing around be"` → regex `sl_to` (the 1609 trap — regex holds, would ride to a fake
  multi-R win); LLM `close_full`.
- `"Got stopped"` / `"Got stopped at breakeven"` → regex `abstain`/`sl_to` (misses the
  close); LLM `close_full`.
- `"Reached tp and fully closed"` → regex `open` (inverts — opens instead of closing); LLM
  `close_full`.
- Openers like `"BTC Short … SL 84500"` → regex `sl_to` (the "SL <n>" token); LLM `open`.

## Cost engineering (why the run was affordable)

The first attempt re-sent the **entire ≤T history** every call (~64–76k tokens, ~$0.47/call,
tripped the 5-hour Max cap). Fix: window the prompt to the **last 40 messages / 48h** — the
harness-owned ledger already carries older state, so old raw chat is redundant. Result:
~1–3k tokens/call, **~$0.086/call**, fidelity intact (the 1611 trap still caught; 11/11
tests green). Full 178 = **~$15** vs ~$83 the naïve way. Two cheaper alternatives were
tested and **killed by evidence**: a regex prefilter (broke opener-catch 21/21→14/21) and
Haiku (failed the 1611 trap and stop-out closes — Sonnet is required).

## Honest boundaries (what this does NOT prove)

1. **Not profitability / execution.** "Correct intent" ≠ correct sizing/PnL ≠ a real fill.
   Dennis's edge is the WEEX fill (entry timing/price), which late-relayed text cannot
   reproduce. Between-message hard-SL auto-triggering is not modelled.
2. **Not superiority over a *smart* mechanical baseline.** The regex comparator is
   deliberately dumb; a stateful rules engine is untested.
3. **Single signaler, single month** (May; April only spot-checked + held-out #1106).
4. **Ledger state-ratcheting** — an early LLM error becomes later prompt state (realistic
   for deployment, but later decisions aren't fully truth-independent).
5. Truth built in prior validation sessions, not by a blind independent labeler.

Codex-reviewed (the claim was softened from "tracks his book" to "opener + management intent
fidelity at scale" on its recommendation, then the management confusion matrix was added to
earn the stronger phrasing).

## Next steps

See [`SMART-AGENT-NEXT-STEPS.md`](SMART-AGENT-NEXT-STEPS.md).

## Artifacts (on disk)

- Substrate + tests: `research/insiders_april_replication/causal_replay/*.py`, `tests/`
- Persisted run + evidence: `causal_replay/runs/full_may/` (178 windowed decision caches,
  `baseline.json`, `llm.json`, `summary.json`); `runs/blind_1611_vps/` (logged blind 1609);
  `runs/btc1609_mock/` (deterministic acceptance)
- Grades: `/tmp/grade178.json`, `/tmp/mgmt_matrix.json` (regenerable from the caches)
- Price caches (WEEX/Binance 1-min) live on the VPS / gitignored — bulk data, not committed
