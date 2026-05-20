# Insiders Scalp Copy-Trader — Session Handoff

> Start here if you're a new session picking up this work. Self-contained — read
> top-to-bottom and you'll have full context.

## What we're building

A copy-trading bot that mirrors signals from the **"Insiders Scalp"** private
Telegram group.

Eduardo (friend of project) is a **member** of the group — NOT the signaler.
The signaler is the group leader (unknown to us); they post their real-money
trades into the channel. Eduardo has a proven track record copying these
signals himself; we vouch through him.

Phase 1 (this build): we don't have direct access to the group, so we
piggyback through Eduardo's Telegram user session.

```
Signaler (group leader)
   → Telegram group
       → Eduardo (member, his Telegram client)
           → our Telethon listener (uses Eduardo's .session file)
               → Claude classifier (via Max subscription / agent runtime)
                   → FastAPI receiver
                       → Freqtrade futures bot (dry-run, then live)
```

Phase 2 (if phase 1 works): we get our own access to the group, drop the
Eduardo-hop to reduce lag, and help Eduardo build his own copy bot. Same
code base, two deployments — ours and his.

The goal of this phase is to **prove the plumbing works end-to-end** —
classifier matches the leader's intent, orders execute correctly, position
state stays reconciled. Eduardo's session is a single point of failure for
phase 1; phase 2 removes that dependency.

## Source material (not in this repo)

Eduardo shipped HIS paper-trading prototype as a zip — this is what HE built
to copy the group leader's signals into his own account. We're using his
prototype as the reference for what good looks like:
`papertrading copy/` — contains:
- `reader.py` (Telethon, hardcoded `API_ID=28296606`, `API_HASH=04f9d5...`,
  `CHANNEL_ID=-1003881583689` — the Insiders Scalp group, accessed via
  Eduardo's user session)
- `parser.py` — the regex parser we're **replacing** with the LLM
- `simulator.py` — thread builder + trade lifecycle, **keep this**
- `weex.py` — WEEX/Bybit kline resolver for PnL backtesting, **keep this**
- `last_month_messages.json` — **428 messages over 30 days**, raw Telegram
  dump (uses a JSON quirk: extra data after first doc; load with
  `json.JSONDecoder().raw_decode(content)`)
- `messages_may13_now.json` — recent slice
- `project.md` — channel format spec

**Get the zip from the user** before doing anything. The prototype is
gitignored intentionally — `API_ID/API_HASH` are Eduardo's credentials and
shouldn't live in this repo.

## Key decisions already made (don't relitigate)

1. **Drop the regex parser, use Claude Haiku 4.5.** Regex passes 27/50 on the
   hand-labeled sample with a 35% false-close rate on chat that mentions
   "stop". Validated cost: ~$0.04 to classify 50 messages with prompt caching.
2. **Binance USDT-M Futures, not Spot.** 49% of signals are shorts; spot
   would kill half the signal volume. Futures: 82.5% coin coverage, full
   long/short. New Freqtrade service, separate from the existing 6 spot bots.
3. **Skip HYPE, FARTCOIN, MNT, PUMP, FF for v1** — coins missing from Binance
   Futures. 7.5% of signal volume. Revisit with WEEX fallback later.
4. **Listener runs on the existing "elder brain" VPS** alongside Master
   Trader, not a dedicated box. Blast-radius isolation is a v2 concern.
5. **Eduardo does NOT need anything running locally.** One-time login on his
   laptop generates a `.session` file → encrypted → uploaded to our VPS.
   That's it. The session persists for months as long as we receive updates.

## Where the work lives in this repo

- `docs/insiders-signals/llm-validation.md` — **the Eduardo-facing deliverable.**
  Has the LLM prompt, JSON schema, the 50-message regex-vs-ground-truth
  comparison table, aggregate scores, and a 1-paragraph pitch.
- `docs/insiders-signals/validate_llm.py` — **self-contained validation
  script** (embeds 50 messages + ground truth). Run with
  `pip install anthropic && ANTHROPIC_API_KEY=sk-... python validate_llm.py`.
  Prints ✓/✗ per message + confusion matrix. ~$0.04 total.
- `docs/insiders-signals/replay-results.md` — **MVP-1 results doc for Eduardo.**
  Side-by-side LLM vs regex on all 428 messages: LLM +$230.80 / 23.08% vs
  regex +$188.07 / 18.81%. The $42.73 delta is almost entirely from 16
  market-entry trades the LLM recovers via WEEX kline fill.
- `docs/insiders-signals/replay/classifications.jsonl` — frozen artifact:
  428 LLM classifications, reproducible without API access.
- `ft_userdata/insiders_bridge/{regex_replay,llm_simulator,render_report}.py`
  — MVP-1 pipeline scripts. See `replay-results.md` for the reproduce steps.
- `docs/insiders-signals/session-handoff.md` — this file.

Committed on branch `claude/understand-project-Vo5vk` (commits `499efec` +
MVP-1 wrap-up).

## MVP-1 status — DONE (2026-05-17)

Eduardo shipped an updated prototype (`telegram.zip`, 2026-05-17) that
overhauled `weex.py` and `simulator.py`:
- Chronological event walk: SL moves now applied as the kline walk progresses
- Partials book realized PnL at the close-event price
- Breakeven stops labeled `manual` (scratch), not `sl` (loss)
- Adaptive kline interval ladder (1m / 5m / 15m / 1h)
- Risk-budget sizing model: $1k account, $10 risk/trade, $50 margin → variable
  leverage = $10/SL_distance%

His regex baseline on this updated prototype: **+$187.37 / 18.74% return,
9.7x avg leverage** (per his `summary.md`). We reproduce within $1.

The replay pipeline (`regex_replay.py`, `llm_simulator.py`, `render_report.py`)
is parser-agnostic — both pipelines feed `simulator.simulate` (regex) /
`build_trades` (LLM events) into Eduardo's `weex.resolve_exits` unchanged.

**Gate passed:** LLM PnL ($230.80) > regex PnL ($188.07) by $42.73 / 4.27pp.
No catastrophic false-close events. The bare-`stop` regex bug is gone (LLM
correctly classifies all "Got stopped" / "stop-loss" mentions as either
close_full or chat per their actual semantic).

## Three-lane investigation — compressed findings

### Lane 1: parser audit (regex)
- 428 messages → 71 trade opens (+2 fake tickers leaked: XTIU, CLOSE)
- 89% have a management event; 75% have entry; 93% have SL; 69% have TP
- 25% are "by market" entries (no fill rule)
- WEEX-resolved PnL: +$119 / 30 days at $100/trade, 38.5% win rate, median
  R:R 3.15 — signals are positive-EV
- **Killer bug:** `_FULL_CLOSE_RE` matches bare `stop(?:ped)?` → flags 24/71
  trades (34%) as fully closed on chat mentions of "stop". Catastrophic.

### Lane 2: live ingestion
- **Telethon `events.NewMessage` + `events.MessageEdited`** on a long-lived
  asyncio loop, supervised by docker-compose or systemd. Pyrogram/TDLib offer
  no measurable benefit; Bot API requires the channel admin to add a bot
  (won't happen on a private third-party channel).
- **Two-part thread handling:** buffer header messages for ~8 s before
  emitting, to merge with the reply that carries entry/SL/TP. Emit-and-revise
  rejected — wrong forceenter is real money.
- **Deduping:** SQLite cursor at `insiders_bridge/state.sqlite`, primary key
  `msg_id`. On startup `iter_messages(min_id=last_id, limit=200)` to backfill
  outage gaps.
- **Forwarding:** HTTP POST to FastAPI on `localhost:8089` (mirrors the
  existing `tv_bridge` pattern in `ft_userdata/`).
- **Latency budget:** ~0.5-2 s single-part trades, ~2-10 s two-part.

### Lane 3: session/connection
- Generate `.session` file once on Eduardo's laptop with his phone + 2FA. He
  encrypts with `age -p` and hands it over. Done forever (or until he hits
  "Terminate session" in his app).
- He should rename the session to **"MT-Listener"** in Telegram → Settings →
  Devices, so he doesn't kill it by accident.
- Heartbeat from the listener → Discord/Telegram alert if no event for >5 min.
- Pre-built `gen_session.sh` for re-auth in <10 min if it dies.
- Session can run for months headless; 180-day inactivity timer resets on
  any received update, and an always-on listener never trips it.

## Exchange coverage table (for reference)

| exchange | unique coins | weighted % | what's missing |
|---|---|---|---|
| Binance Spot (current MT) | 18/23 | 90% | HYPE, FARTCOIN, MNT — **but no shorts → loses 49% via direction** |
| **Binance USDT-M Futures (chosen)** | 18/23 | **82.5%** | PUMP, FF, MNT |
| Bybit linear perps | 19/23 | 86.2% | PUMP, TST |
| WEEX futures | 21/23 | 97.5% | nothing real |

Binance numbers came from `data-api.binance.vision` mirror + futures testnet
(prod was geo-blocked in the sandbox). **Re-verify from a clean IP** before
final coin list.

## Build plan — 4 MVPs, gated

### MVP-0 — Eduardo signs off (today, no infra, $0.04)
- Clone repo, `cd docs/insiders-signals`
- `pip install anthropic && ANTHROPIC_API_KEY=sk-... python validate_llm.py`
- Both Eduardo and the user run it independently, read the ✓/✗ table.
- **Gate:** Eduardo approves the LLM approach.

### MVP-1 — full replay simulator (1 day, all offline)
- New file `ft_userdata/insiders_bridge/replay.py`.
- Inputs: prototype's `last_month_messages.json`, the classifier from
  `validate_llm.py` extracted to a module.
- Pipeline: walk all 428 messages → classify with Haiku → emit structured
  events → feed the prototype's `simulator.py` (or a copy) → resolve PnL via
  `weex.py`.
- Output: trade log + PnL summary. Compare to the regex baseline ($119/30d).
- **Gate:** LLM-driven PnL ≥ regex PnL, with no catastrophic false-close
  events when manually spot-checking the trade log.

### MVP-2 — live listener, paper only (1-2 days)
- `ft_userdata/insiders_bridge/listener.py` — Telethon, uses Eduardo's
  session, classifies and writes structured events to a JSON log.
- **No execution yet.** Just prove we capture signals in real time.
- Run for 1 week alongside the channel. Compare classifier output against
  what Eduardo actually did.
- **Gate:** Eduardo signs off on classifier output for a full week.

### MVP-3 — Freqtrade dry-run wired (1-2 days)
- `ft_userdata/insiders_bridge/receiver.py` — FastAPI port 8089. Idempotent
  by `msg_id`. Maps events to Freqtrade REST: `forceenter`, `forceexit`,
  trailing SL adjustment.
- `ft_userdata/user_data/strategies/InsidersScalpV1.py` — futures pass-through
  strategy. No own entries. Respects per-signal SL/TP. Skip-list for missing
  coins.
- `docker-compose.yml`: new bot service, `trading_mode: "futures"`,
  `dry_run: true`, fresh port.
- **Gate:** passes `GRADUATION_CRITERIA.md` (14 days, 30 trades, PF ≥ 2,
  WR ≥ 55%, MaxDD < 15%, ≤4 consecutive losses, no force-exits).

### MVP-4 — live capital (only after MVP-3 graduates)
- $100-200 max for first deployment.
- Same demotion rules as every other bot.

## Resolved decisions (2026-05-19)

All 5 of the original open items resolved with the user in the post-travel
review session.

### 1. Position sizing — RISK-BUDGET, SCALED 5× DOWN

Replicate Eduardo's `stake = risk_$ / SL_distance_pct` model proportionally
to our wallet:

| Param | Eduardo's prototype | Ours (MVP-3) |
|---|---|---|
| Account size | $1,000 | $200 |
| Risk per trade | $10 | **$2** |
| Notional margin | $50 | **$10** |
| Leverage formula | `risk / SL_distance_pct` | same |

Preserves his R:R backtest math (median R:R 3.15, +18.81% in 30 days).
Variable leverage by design — 0.5% SL trade gets 20×, 5% SL trade gets 2×.
This is the same risk-equalization mechanic that worked in his replay.

### 2. Market entries — TAKE, only if explicit SL present

Market signals are where the LLM's edge over regex came from (+$42.73 / +4.27pp
of the +$230 total). Wire it to take immediate market order at the signal
timestamp **only if the signal carries an explicit SL**. No SL → skip (can't
size safely under the risk-budget model).

### 3. Multi-coin signals — FAN OUT per coin

LLM provides `applies_to=["BTC", "ETH"]`. Receiver iterates: each action
(close 30%, move SL, etc.) gets applied to every coin in the list. Loses
0 signal coverage and matches Eduardo's intent.

### 4. Listener VPS — EXISTING Elder Brain VPS

Telegram delivery is region-agnostic. Binance Futures works from Oracle IPs
(verified 24/25 USDT-M perps reachable from the VPS — see decision #5).
No reason to spin up a separate region-matched box for v1.

### 5. Binance Futures coverage — RE-VERIFIED FROM VPS (2026-05-19)

Production Binance Futures USDT-M perps list (527 total): **24/25 Eduardo
coins available**. Testnet number (18/23) was stale — production has HYPE,
FARTCOIN, PUMP, FF.

```
Available: BTC ETH SOL BNB XRP ADA DOGE LINK AVAX NEAR SUI HBAR LTC BCH
           TRX UNI ARB ENA ZEC TAO HYPE FARTCOIN PUMP FF
MISSING:   MNT
```

Skip-list for v1: just `MNT`. <1% of signal volume.

## MVP-3 build requirements (codex-reviewed 2026-05-19)

Codex architecture review nailed the design before any real-money MVP-3 build.
Latency profile and 9 mandatory changes below.

### Latency profile to plan for

| Path | p50 | p90 | p99 |
|---|---|---|---|
| Single-part, LLM in path | 3–4s | 6–8s | 12s+ |
| **Single-part, regex fast-path** | **0.7–1.2s** | 2s | — |
| Two-part (8s adaptive buffer) | 11–13s | 16–20s | — |

Verdict: 2–5s usable for $100–200 measurement bot. 10–13s materially
degrades 0.5% SL scalps vs zero-latency backtest. Two-part signals are
lower-quality by construction.

### Required architecture changes before MVP-3 build

1. **Regex fast-path + LLM as shadow validator.** Strict allowlist:
   single-message signal with symbol + side + entry + SL + TP + Binance-valid
   pair + no ambiguity + no reply dependency. Fire order at T+0.7s. LLM
   validates by T+3s. **If LLM disagrees → `forceexit`, do NOT reverse.**
   LLM remains primary for everything else.
2. **Price-age + slippage gates** before entry. Reject if signal age > 8s
   (single) or > 18s (two-part). Reject if price moved > 20-25% of SL
   distance against expected R:R.
3. **Persist every event before action** (raw msg → LLM/regex output →
   order request → exchange response → trade_id). Audit/replay spine.
4. **Reconciliation loop.** Poll Freqtrade + Binance position every few
   seconds, repair mismatches. *"Worst failure is not 'missed trade'; it
   is believing you are flat when Binance has exposure."*
5. **Fail-closed on opens, fail-loud on exits.** Anthropic outage blocks
   new entries (fail-closed). Close/move-SL need regex fallback + alert +
   manual override (fail-loud).
6. **Telegram health checks.** Heartbeat, alert on receive-lag > 5s,
   reconnects, auth errors.
7. **Don't open on header-only two-part signals.** No SL → no size, no
   invalidation. Adaptive buffering: bypass when complete, wait up to 8s
   when incomplete.
8. **Near-null Freqtrade strategy.** Disable ROI (`{}` or ceiling), disable
   strategy exit signals, no own entry logic. Entries via `forceenter` REST,
   exits via `forceexit` REST + `custom_stoploss` for move_sl.
9. **Multi-coin signals = independent idempotent per-symbol commands.**
   Partial failure is normal; log + alert explicitly.

### Latency-degradation forecast (precursor task, must run before MVP-3)

Replay each of the 428 signals with synthetic delays (1s / 3s / 8s / 13s),
recompute fills using Binance/WEEX second-level data. Output: latency
sensitivity curve. Tells us what to expect live vs MVP-1 backtest's +$230.

### Codex's "do not" list
- Don't drop the LLM entirely (the +$42 / +4.27pp it added is real, mostly
  market-entry recovery).
- Don't reverse on LLM disagreement after fast-path — just exit.
- Don't open on header-only two-part signals.

## Codex architecture review v2 (2026-05-19) — corrected frame

After the role correction (Eduardo = group member, signaler = unknown group
leader) and user's policy frame ("trust the signaler, don't backtest"),
codex re-reviewed. Verdict: plan is sound for $100-200 measurement, but
three areas need work before MVP-3.

### Trust frame: defensible as small-capital experiment, NOT proof of edge

Gaps to flag explicitly:
- Signaler is unknown to us (Eduardo vouches, that's it)
- Survivorship bias unknown
- Edited/deleted Telegram message behavior unknown
- Fill/slippage at live speed unknown

OK to start at $100-200. Not OK to scale aggressively before live evidence.

### Hardening item 1 — Eduardo .session SPOF handling

**Don't auto-close everything on session loss.** A transient listener
outage shouldn't become guaranteed realized loss. Right approach:

- On session loss: **pause new entries immediately**
- Use **exchange-side SL/TP orders on Binance Futures** so positions stay
  protected even when our listener is dead. (Memory note:
  `feedback_stoploss_on_exchange_dryrun.md` warned against this in
  Freqtrade dry-run mode — irrelevant for live futures.)
- Alert aggressively
- After N minutes no-recovery: optionally flatten positions WITHOUT
  exchange-side protection, never the protected ones.

### Hardening item 2 — Classifier latency determinism (split rule + agent)

**Don't put a Claude agent loop on the critical entry hot path.** Agent
runtime is less deterministic than a stateless API call. Better:

- Rule fast-path (`classifier.py`, sub-50ms) for COMPLETE opens only
  (symbol+side+entry+SL+TP in one message, no ambiguity, Binance-valid pair)
- Claude agent runtime via Max subscription for management messages
  (close, close_partial, move_sl, increase, multi-coin, replies, breakeven,
  ambiguous chatter) — latency OK here, more complex semantics
- Hard timeout with deterministic fallback
- Persist raw message immediately, classify async where possible
- Benchmark p50/p95/p99 before going live

This actually USES the Max subscription correctly — agents on heavy lifting
(reasoning over position state, ambiguous management), not on the
milliseconds-matter open path.

### Hardening item 3 — Credential isolation in shared image

For the eventual multi-deployment world (ours + Eduardo's own bot from
same image):
- Never bake sessions, API keys, stake sizes, or account IDs into image
  layers
- Separate `.env`, volumes, logs, dbs, Telegram sessions per deployment
- Binance keys: **no-withdrawal permission, IP-restricted**
- Instance identity explicit in every log/alert/order tag (so the two
  deployments' logs never get confused)

### Codex's revised wiring rules

| Item | Verdict |
|---|---|
| Strict-rule fast-path on complete opens | KEEP (latency win) |
| Claude primary for non-open / ambiguous | KEEP (operational parser) |
| Market sanity bands (symbol/price band) before exec | KEEP (mandatory bug catcher) |
| Claude shadow on rule opens → forceexit on disagree | **CHANGE** → log/alert/quarantine only. Block before entry on parser-corruption signal, don't override a successful copy after entry. |

### The biggest risk we're still under-thinking

Codex flagged this as the dominant risk class — bigger than signal quality:

> *"Message semantics drift under leverage: edits, replies, partial closes,
> 'cancel previous,' multi-target changes, late corrections, and ambiguous
> 'close half / move BE' instructions being applied to the wrong open
> position. That is where copy-traders lose money despite good signalers."*

**The actual core product** is not the classifier — it's the **position-link
graph + idempotency**. Every classification action must reconcile against:
- msg_id and reply chain
- symbol, side, entry batch
- current open position state
- prior management history

before executing. The LLM's role: given the graph + the message, reason about
which specific position(s) the leader's action applies to. Execution against
Freqtrade is deterministic afterward.

The audit spine codex originally called for is not a log file — it's
first-class state.

## Classifier benchmark (2026-05-19) — codex-blessed architecture

Ran `classifier.py` (467 lines of curated Python rules) against Claude's
`classifications.jsonl` on the same 428 messages, identical simulator. Full
writeup: [classifier-benchmark-2026-05-19.md](classifier-benchmark-2026-05-19.md).

Headlines:
- 90.2% agreement on `kind` (386/428).
- On REALIZED closed trades, Claude beats rule by +$95 ($356 vs $261).
- Rule's apparent +$360 PnL edge is phantom — comes from positions that
  never closed in the window due to missed-close bugs + symbol-parse bugs
  (e.g. ETH SHORT with entry=77100, a BTC price).

**Production architecture** (codex-blessed 2026-05-19):

```
incoming Telegram message
   │
   ├── strict-rule open detector (single message, symbol+side+entry+SL+TP,
   │   no ambiguity, no reply dependency, Binance-valid pair)
   │      │ if match
   │      ▼
   │   FAST-PATH: place order at T+0.7s, LLM validates in parallel
   │   if LLM disagrees on kind/symbol/side/price → forceexit
   │
   └── LLM primary for everything else:
       close_full, close_partial, move_sl, increase, hedge management,
       replies, breakeven, ambiguous operator chatter
```

Plus hard market sanity checks before EVERY execution: symbol-relative price
band check (live mark price or recent kline range) — catches `entry=77100`
bug class even if both classifiers miss it.

Missed-close prevention is the dominant safety concern. Close/SL-move stays
LLM-led until much stronger evidence.

## How to onboard yourself (new session, fresh clone)

```bash
git clone https://github.com/IvPalmer/master-trader.git
cd master-trader
git checkout claude/understand-project-Vo5vk

# Read the deliverable
cat docs/insiders-signals/llm-validation.md

# Run the validation (need the user's ANTHROPIC_API_KEY)
cd docs/insiders-signals
pip install anthropic
ANTHROPIC_API_KEY=sk-ant-... python validate_llm.py
```

Then ask the user for `papertrading copy.zip` (Eduardo's prototype, contains
the 428-message dataset and the channel credentials), unzip outside the
repo (NOT into the repo — those credentials shouldn't be tracked), and you
have everything you need to start MVP-1.

## What the user is committed to and what they're not

- **Committed:** Binance Futures, LLM-over-regex, listener on existing
  elder-brain VPS, no separate VPS, MVP build path above, skipping the 5
  missing coins for v1.
- **Open:** sizing, market-entry policy, VPS region. The user said "size is
  up to us we can decide on a allocation ourselves, not important right now"
  — flag the decision when MVP-3 is being built, don't assume.
- **Eduardo's role:** 15-minute one-time onboarding (generate session,
  encrypt, hand over, rename to "MT-Listener"). After that he runs nothing.

## Watch out for

- The prototype's `parser.py` is being **replaced**, not extended. Don't
  build on top of its regex bugs.
- `last_month_messages.json` has a JSON quirk — extra data after first doc.
  Always load with `json.JSONDecoder().raw_decode(content)`.
- The `_FULL_CLOSE_RE` regex catches bare "stop" — if you write a sanity
  fallback that uses any regex from the prototype, this bug will follow you.
- Binance is geo-restricted from some IPs (parent repo has
  `bypass_vpn_binance.sh` for this). The listener VPS needs an unblocked IP.
- Eduardo's `.session` file == full account access. Encrypted at rest,
  secrets manager only, never in git.
- The original prototype's PnL backtest uses **WEEX** klines. We're moving
  execution to **Binance Futures**, but PnL backtest can still use WEEX
  (broader coverage) — or switch to Binance Futures klines for consistency.
  Worth thinking about in MVP-1.

## Key file references

In this repo:
- `docs/insiders-signals/llm-validation.md` — Eduardo-facing deliverable
- `docs/insiders-signals/validate_llm.py` — runnable validator
- `ft_userdata/tv_bridge/` — pattern to mirror for the FastAPI receiver
- `ft_userdata/bots_config.json` — bot-to-port map (read before picking a
  new port for the listener)
- `GRADUATION_CRITERIA.md` — dry-run-to-live gate, same applies here
- `ROADMAP.md` — overall project trajectory

In Eduardo's prototype (need the zip):
- `papertrading copy/last_month_messages.json` — 428-message dataset
- `papertrading copy/simulator.py` — thread builder, keep
- `papertrading copy/weex.py` — PnL resolver, keep
- `papertrading copy/project.md` — channel format spec (long-form)
