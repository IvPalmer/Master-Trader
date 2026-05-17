# Insiders Scalp Copy-Trader — Session Handoff

> Start here if you're a new session picking up this work. Self-contained — read
> top-to-bottom and you'll have full context.

## What we're building

A copy-trading bot that mirrors signals from the **"Insiders Scalp"** private
Telegram channel (signals from "Eduardo" — channel owner, friend of the
project). Pipeline:

```
Telegram channel → Telethon listener (Eduardo's user session)
                 → Claude Haiku 4.5 classifier (structured JSON out)
                 → FastAPI receiver in ft_userdata/
                 → Freqtrade futures bot, dry-run first
```

The goal of this phase is to **convince Eduardo the LLM is reliable enough** to
trust real capital to, then build an MVP that paper-trades against the live
channel for 14+ days before any money is at stake.

## Source material (not in this repo)

Eduardo shipped a paper-trading prototype as a zip:
`papertrading copy/` — contains:
- `reader.py` (Telethon, hardcoded `API_ID=28296606`, `API_HASH=04f9d5...`,
  `CHANNEL_ID=-1003881583689` — Eduardo's channel, his user session)
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

## Open decisions

These are the things the user said "we can decide" but haven't. Resolve
before MVP-3:

1. **Position sizing.** Fixed $ per trade, fixed % of free balance, or scale
   by R:R? User said "not important right now" but MVP-3 needs an answer.
2. **"By market" entries** (~25% of opens). Take immediate market order, or
   skip? Recommendation: take, but only if signal includes SL.
3. **Multi-coin updates** ("BTC and ETH, close 30%"). Fan out the action.
   The LLM provides `applies_to`; the receiver needs to iterate.
4. **VPS region** for the listener — Eduardo's country. (Marginal for v1.)
5. **Re-verify Binance Futures coverage** from a non-blocked IP. PUMP/FF/MNT
   absence on Binance Futures came from testnet; could be stale.

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
