# Plan — Insiders Scalp (Dennis / Alpha Scalp) on WEEX

> ## ⛔ FINAL VERDICT 2026-05-28 (late session): DO NOT PAY DENNIS
> The "+76%" that justified this whole plan was a **simulator bug**
> (phantom mark-to-end exit prices — see msg 79: claimed exit 76,095
> when real BTC max was 69,958 and SL hit at 65,081). A proper
> event-driven backtest that actually models his partial closes +
> trailing stops on clean price data gives **~+10%/83 days** (stable
> 9.6–10.2%), WR 45.5%, PF 1.22. Live execution erodes that further.
> Dennis is **not a fraud** — real trades, honest prices (14/16
> win-claims verified) — but the marketing oversells the edge 5-10×,
> and he earns subscription + WEEX-affiliate revenue regardless of
> your PnL. The capital paradox kills it: small capital (freeze-safe)
> is sub-negative vs the $275 cost; large capital (clears the sub) is
> big enough to trip WEEX's profit-freeze engine. **If ever copied:
> mirror on Binance, never WEEX.** Full findings:
> `~/.claude/projects/-Users-palmer-Work-Dev-master-trader/memory/project_insiders_weex_validation_2026-05-28.md`.
> Everything below (D-lite architecture, phases) is sound engineering
> but moot unless the economics change (trial pricing + R&D framing).

**Status update 2026-05-28 (late session):** Phase 0 validation
complete. Architecture choice and codex re-review both shifted.
Original Option C (Freqtrade + WEEX) is **dead** — ccxt doesn't
support WEEX and Freqtrade rejects unlisted exchanges. We replaced
it with **Option D-lite: custom Python REST client, direct WEEX**.
Live-tested end-to-end with $0.27 burn (probes + custody test).
The integration WORKS; the trade just isn't worth paying for.

## TL;DR (revised)

- **Pay Dennis 1.500 BRL (~$275)** for 6-month Alpha Scalp access,
  treated as R&D spend, not guaranteed ROI.
- **Ship D-lite**: drop Freqtrade for Insiders, talk WEEX REST
  directly from `services/insiders-receiver/`. WeexClient built and
  live-validated (`weex_probe/weex_client.py`).
- **One-way (COMBINED) margin mode mandatory.** Hedge mode is
  broken for management endpoints in WEEX (-1054 silent reject).
- **Atomic bracket** via attached SL+TP at entry — no naked-position
  window. (Codex's main earlier concern.)
- **Start at $300-500 venue balance, $100-250 actively allocated.**
  Not $1k day-one. Scale after 2-4 weeks of clean logs + repeated
  custody tests.
- KillersScalp pipeline stays on Binance unchanged.
- Dennis approved direct access → drop Eduardo .session dependency
  (Phase 1 plan unblocked).

## Phase 0 — what we live-validated this session

### Live trade primitives (all on operator's WEEX account, hedge mode)
- Auth (HMAC-SHA256-base64 + key + secret + passphrase, OKX-style): ✅
- Mac IP allowlist (`187.89.221.175`) accepted: ✅
- `GET /capi/v3/account/balance`, `/accountConfig`: ✅
- `POST /account/marginType` (ISOLATED + SEPARATED/COMBINED): ✅
- `POST /account/leverage` (5x isolated long+short): ✅
- `POST /capi/v3/order` MARKET BUY with attached `slTriggerPrice`
  + `tpTriggerPrice` — **atomic bracket in one HTTP call**: ✅
- Auto-spawned algos: STOP_MARKET + TAKE_PROFIT_MARKET, both
  `reduceOnly=true`, `workingType=MARK_PRICE`, UNTRIGGERED: ✅
- `POST /capi/v3/closePositions` flattens position AND cancels
  child algos atomically: ✅

### Hedge mode (SEPARATED) — partially broken
- `placeTpSlOrder` returns `-1054 INVALID_ARGUMENT: Position ID
  missing in separated mode`. Tested 5 field-name variants
  (positionId/posId/holdSide/query-string/body, int/str). None work.
- `/order SELL` opposing side: same -1054.
- `/closePositions` with `quantity` field: **ignores quantity**,
  always closes the full position. Cannot use for partial close.

### One-way (COMBINED) mode — fully functional
- Partial close via `/order SELL` with quantity: ✅ (closed
  0.0001 of 0.0002 position cleanly)
- Move SL via `/modifyTpSlOrder` (trigger price change,
  algoId stable): ✅
- All other endpoints from hedge-mode set: ✅

### Public-endpoint probe (no auth, all 7 checks passed)
- 739 USDT-M perp symbols listed in `/market/exchangeInfo`
- **28/29 of Dennis's top signal symbols are on WEEX** (PUMP, ASTER,
  FF, HYPE, RENDER, ARB, APT, FARTCOIN, SIREN — all listed).
  Only XTIU not found. Earlier "23% DEAD bucket" was wrong.
- Liquidity is real, but thin on the meme tail (PUMP $807k/24h on
  WEEX vs $81M Binance). Tradeable, just worse fills.
- Klines work at 1m/5m/15m/1h/4h/1d (research spec was wrong about
  intraday being broken).
- BTC leverage cap: 400x. Maker 0.02% / Taker 0.08%.

### Custody test — PASSED ($5 WEEX → Binance Polygon)
- WEEX submit: 15:55:16
- WEEX processing: 15:55:35 (19s queue)
- Binance detected: 15:56:21 (1m 5s after submit)
- Binance credited Concluído: <2 min after detection
- **Total round-trip: <3 minutes. Fee: $0.20 on Polygon.**
- Txid: `0xc6cc321fb02abe08cbe5fc0192b2d441c8542277e53101bff3b7647d5e7fed60`
- No WEEX risk-bot delay or freeze at $5 scale.

### Signal kind coverage matrix (from replay export)

Source: `docs/insiders-signals/replay/classifications.jsonl` (428
messages classified) + `replay/trades_llm_2026-05-26.json` (147
trades, +76.4% return over 83 days).

| Kind | Classifications | Trade events | WEEX path (one-way) |
|---|---|---|---|
| open | 91 | n/a | `/order` MARKET + attached SL+TP atomic ✅ |
| close_full | 41 | 75 | `/closePositions` ✅ |
| close_partial | 64 | 98 | `/order SELL` w/ quantity ✅ |
| move_sl | 24 | 61 | `/modifyTpSlOrder` ✅ |
| increase | 6 | 44 | `/order BUY` + cancel/replace SL+TP (4 calls — naked window risk) ⚠️ |

All 5 signal kinds have a working path. Increase is the only one
with operational risk (codex flagged: re-introduces naked window).
Recommendation: **alert-only at launch** for increases.

### Live burn this session
- Trade probes (5+ cycles entry/SL/TP/close): $0.07
- Custody withdrawal fee: $0.20
- **Total: $0.27** for full end-to-end validation
- Wallet residual: $24.29 USDT (split Spot 1 + Futures 23.29) on WEEX
  + 4.80 USDT on Binance

## Context — what we learned today

### Who's who

- **Dennis** is the Alpha Scalp / Insiders Scalp channel owner +
  signaler. (Previously labeled "unknown group leader" in our memory.
  Identity confirmed 2026-05-28 via Telegram DM with him.) Username
  in his Telegram chat: "Dennis🦂".
- **Eduardo Melo** (WhatsApp `554884635471`, LID `30077823754391@lid`)
  is a friend-of-project + member of Dennis's channel. We were
  piggybacking through his `.session` file (Phase 1 plan) because
  Dennis doesn't add bots and we didn't have direct access.
- **Us (Palmer)** — Dennis approved Palmer as a member of his team
  after Eduardo's referral + the trading-experience conversation.

### Channel mechanics (verified in chat with Dennis)

> "we all trade on WEEX" — Dennis, 2026-05-28 11:08 Telegram

Dennis explicitly trades on WEEX. The channel is structured around
WEEX. Why WEEX:
1. He has affiliate revenue share on WEEX
2. WEEX offers a "$250 trading bonus" via his referral (advertised in
   the channel; actual extractable amount needs verification — see
   "Open questions" below)
3. WEEX has the perp pairs the Killers/Alpha-style signals trade

### Subscription plans (from channel)

| Plan | Price | $/mo |
|---|---|---|
| 2 months | $149 | $75 |
| 4 months | $229 | $58 |
| 6 months | **$299** | **$50** ← best value |
| 12 months + 1-on-1 mentorship | $3.490 | $290 |

Dennis quoted us **1.500 BRL ≈ $275 USD** for what's clearly the 6mo
plan (BRL pricing with small forex shave).

## Why migrate FROM Binance TO WEEX (instead of staying on Binance)

We had three options. Captured here for next-session context:

### Option A — Pay Dennis, keep our bot on Binance
- ✅ No bot rewrite needed
- ✅ Binance has deeper liquidity
- ❌ Doesn't capture the WEEX bonus
- ❌ Signal prices reference WEEX's order book; mark price tracking
  could diverge across exchanges for some alts
- ❌ Less aligned with Dennis's setup → if he ever does WEEX-specific
  orders (limit ladders at WEEX-specific tick sizes), we'd miss them

### Option B — Pay Dennis, manual trading on WEEX
- ❌ Time sink (~30-45 min/day per Palmer reacting to every signal)
- ❌ Misses our slippage gate, target guard, active TP placement
  (the entire bundle from yesterday's work)
- ❌ Defeats the point of having an automated copy-trader

### Option C — Pay Dennis, port via Freqtrade + ccxt **← BLOCKED**
- ❌ ccxt 4.5.44 does not include `weex` exchange (issue #27680
  is a feature request, zero comments, no PR)
- ❌ Freqtrade `SUPPORTED_EXCHANGES` whitelist excludes WEEX
- ❌ Multi-week unblock minimum even if upstream lands soon
- Abandoned 2026-05-28 in favor of Option D-lite (custom Python
  client, bypass ccxt + Freqtrade entirely for Insiders).

### Option D-lite — Custom WEEX REST client **← chosen, live-validated**
- ✅ ccxt + Freqtrade unblock not needed
- ✅ Mirrors Dennis's venue exactly
- ✅ Live-validated in this session: all primitives + custody
- ⚠️ We own the trade state, reconciler, journal previously handled
  by Freqtrade. Codex blessed this as "viable as a tightly capped
  experiment" — not "clean production migration."
- See "D-lite architecture" section above for the build spec.

## Replay numbers (baseline for ROI math)

Snapshot 2026-05-26 — 1.087-msg export, 83 days, $1k virtual account:
- WR 51.1%, PF 2.75
- Realized +$573,81 + mark +$190 = **+$763,96 (+76,4%)**
- avg leverage 8.9×, worst single loss -$13,17

Live haircut assumption (slippage + fees + funding + our slippage
gate skipping HYPE-style late entries): **50%** → realistic **$5/day
per $1k capital** live.

### Capital break-even table (6mo plan, $275 cost)

| Capital | 6mo PnL est | vs $275 gross | vs ~$25 net (with bonus) |
|---|---|---|---|
| $200 | $180 | 0,65× ❌ | 7,2× ✓ |
| $500 | $450 | 1,6× | 18× |
| **$1.000** | $900 | 3,3× ✓ | 36× |
| $2.000 | $1.800 | 6,5× | 72× |
| $5.000 | $4.500 | 16× | 180× |

**Conservative recommendation:** start with $500-1.000 live capital
on WEEX after passing 30 days dry-run on WEEX.

## D-lite architecture (build target)

### High-level
- Drop Freqtrade for Insiders entirely. KillersScalp stays on
  Freqtrade+Binance untouched.
- `services/insiders-receiver/` keeps signal parser, classifier
  (Claude Haiku 4.5), slippage gate, target guard, atomic dedup,
  audit log.
- Replace the freqtrade `/forceenter` hop in `executor.py` with
  direct WEEX REST via `WeexClient` (`weex_probe/weex_client.py`
  → port to `services/insiders-receiver/app/weex_client.py`).
- State management we now own:
  - positions table (sqlite, keyed by symbol)
  - algoId tracking per position (so we can modify SL, cancel TP)
  - reconciler that polls `/account/position/allPosition` +
    `/openAlgoOrders` and detects drift vs DB
  - operation journal with explicit phases (see Risks section)

### Hard constraints (load-bearing)
1. **One-way (COMBINED) margin mode mandatory.** Receiver must
   `set_margin_type(symbol, ISOLATED, COMBINED)` under a symbol-
   scoped mutex before first entry on a new symbol. Idempotent if
   already set. Race risk if two signals on a new symbol fire
   near-simultaneously — lock per symbol.
2. **Atomic bracket required on entry.** Every `/order` MUST include
   `slTriggerPrice` (and TP1 if present in signal). No 2-call open.
3. **`closePositions` is the only emergency primitive.** It flattens
   position + cancels child algos atomically.
4. **Increases are alert-only at launch.** The "buy + cancel SL +
   cancel TP + replace" sequence reintroduces naked window.
   Operator/Slack alert; bot does not execute.
5. **Operation journal** (sqlite or jsonl) on every action:
   `intent_created` → `preflight_ok` → `order_submitted` →
   `order_acknowledged` → `exchange_seen` → `protective_algos_seen`
   → `position_state_matched` → `complete` | `uncertain` |
   `manual_required`. On timeout: `uncertain`, NOT `failed`. Poll
   exchange state before retry.
6. **Hard kill switch on drift.** If reconciler finds DB vs WEEX
   divergence (size, side, missing SL algo), pause new entries
   immediately and alert.
7. **Pair whitelist trimmed for thin liquidity.** Skip symbols with
   24h WEEX quote volume < $5M for MVP (drops PUMP, ASTER, FF,
   XTIU, others — ~12 symbols, ~12-15% of signal volume).
   Re-evaluate after 30 days.

### Endpoints used (all live-verified)
- `POST /capi/v3/order` — entry MARKET/LIMIT with attached SL+TP1
- `POST /capi/v3/closePositions` — full close + emergency
- `POST /capi/v3/order` opposing side w/ qty — partial close
- `POST /capi/v3/modifyTpSlOrder` — SL move (trigger price)
- `GET /capi/v3/account/position/allPosition` — position state
- `GET /capi/v3/openAlgoOrders` — SL/TP plan state
- `GET /capi/v3/account/balance` — balance / reconciler
- `POST /capi/v3/account/marginType` — one-way + isolated setup
- `POST /capi/v3/account/leverage` — per-symbol leverage
- `GET /capi/v3/market/premiumIndex` — mark price for slippage gate

### Out of scope for MVP (defer or alert-only)
- TP2/TP3 ladders (only TP1 attached at entry)
- Increases (alert-only)
- Hedge mode
- Symbols below $5M 24h WEEX volume
- Auto-repair of mismatched algos (manual fix only)

## Central invariant (codex round 3 — load-bearing)

> **No retry of any order-changing action until current exchange
> state is observed and matched to the original intent.**

This is more important than the custody-test pass. The dangerous
case is not clean API failure — it's: request timed out, WEEX
accepted it, bot retries, position doubles or protection is
replaced incorrectly. Every code path that places, modifies, or
cancels orders MUST: idempotent client ID → submit → on
timeout/error → poll exchange state → compare to intent → only
then decide retry vs success vs manual-required.

## Concrete next-session execution order

### Phase 1 — pay + access (1-2 hours)
1. Pay Dennis 1.500 BRL via his preferred rail (PIX or crypto)
2. Wait for him to add Palmer to the Insiders Scalp channel
3. Generate Palmer's `.session` via Telethon (reuse
   `killers_bot/generate_session.py` pattern, swap API_ID/HASH if
   needed)
4. Drop the new `insiders.session` at
   `ft_userdata/insiders_bridge/secrets/insiders.session` on VPS,
   age-encrypted

### Phase 2 — observe-only listener (24-72h) **runs in parallel with Phase 3**
1. Wire the listener to consume Dennis's channel using Palmer's
   `.session`, route every message into the existing classifier
2. **Do NOT trade.** Receiver runs in DRY_RUN mode.
3. Log each classifier decision next to the raw message
4. Compare classifier output vs what a human would do — sanity check
   the LLM is reading Dennis correctly
5. At end of window: confirm classifier latency, classification
   accuracy, no missed messages

> Codex round 3: do NOT wait 72h to start Phase 3. Observe while
> building. Phases 2 + 3 overlap.

### Phase 3 — build D-lite executor
1. Port `weex_probe/weex_client.py` into
   `services/insiders-receiver/app/weex_client.py`. Add async
   variant if executor.py stays aiohttp-based.
2. Add `services/insiders-receiver/app/symbol_mode_lock.py` —
   per-symbol mutex for the COMBINED/ISOLATED + leverage setup
3. Add `services/insiders-receiver/app/positions_db.py` — sqlite
   table for our position state + algoIds
4. Add `services/insiders-receiver/app/operation_journal.py` — the
   intent-phase journal codex required
5. Add `services/insiders-receiver/app/reconciler_weex.py` — polls
   positions + openAlgoOrders, compares to DB, alerts on drift
6. Rewrite `services/insiders-receiver/app/executor.py`:
   - Remove FreqtradeClient + force_enter/force_exit
   - Add WeexExecutor with: open_with_bracket, full_close,
     partial_close, move_sl, alert_on_increase
7. Replace `services/insiders-receiver/app/main.py` route handlers
   to call WeexExecutor methods per signal kind
8. Slippage gate: keep but swap `get_mark_price` from Binance fapi
   → WEEX `/market/premiumIndex`
9. Pair whitelist: hardcode trim list (low-liquidity excluded)

### Phase 3.5 — replay/simulation gate (codex round 3, required before Phase 4)
1. Replay Dennis's classified history through D-lite executor
   with mocked WEEX responses
2. Use real `exchangeInfo` precision/min-size rules from live
   `weex_probe/weex_client.py` calls
3. Pass criteria: every classified event produces a valid
   intent + valid REST payload + journal phase progression
4. Shake out precision rounding, min-notional rejections, symbol
   mapping holes before any live exposure

### Phase 4 — dry-run with live signals (7-14 days)
1. Deploy receiver to VPS with DRY_RUN=true
2. Watch every Dennis message → classifier → would-have-executed log
3. Verify atomic bracket payload shapes against WEEX exchangeInfo
   precision rules
4. **Run the operation journal + reconciler against the
   would-have actions**, not just the classifier output. Shadow-
   verify the journal phases transition correctly.
5. Test 1 manual withdrawal of $20 (custody check at slightly
   higher volume than the $5 already proven)

### Phase 4 stress tests (codex round 3 — run during dry-run)
- **Timeout ambiguity**: order submitted, HTTP timeout, exchange
  actually accepted. Bot MUST poll before retry.
- **Duplicate signal/edit/forward/restart**: same Telegram message
  edited, forwarded, or seen after process restart. Idempotent.
- **Same-symbol concurrency**: open + move_sl + close_partial
  arriving close together.
- **Process crash recovery**: kill receiver mid-cascade, restart
  from journal, reconcile without doubling exposure.
- **API clock skew / signature failure**: deliberately skew clock,
  observe retry behavior.
- **Rate-limit burst**: queue 15 management actions in 1s, verify
  backoff queue handles.
- **WEEX degraded mode**: simulate order endpoint working but
  account/openAlgoOrders lagging or 5xx-ing.
- **Manual app intervention**: operator closes position on phone,
  reconciler MUST pause new entries + alert.
- **Partial close lifecycle**: after partial close, verify that
  the remaining SL/TP algo quantities are still correct (the
  unverified gap — codex flagged this as unknown). NOT just
  position size — algo size.
- **Trigger race**: SL/TP fires while bot is mid-modifying SL or
  mid-partial-close.
- **Precision/min-notional fuzzing**: every whitelisted pair, every
  edge quantity (just-at min, just-below min, at maxOrderSize).
- **Basis/slippage audit**: log WEEX mark vs WEEX best bid/ask vs
  Binance mark at every signal, especially thin alts. Quantify
  the cross-venue tax.
- **Funding + liquidation sanity**: high-leverage signals must not
  blindly map to account leverage; cap server-side.

### Phase 5 — micro-live ($100 actively allocated)
1. Fund $300 WEEX sub-account (Spot wallet)
2. Transfer $100 to Futures wallet
3. Flip DRY_RUN=false. **Cap per-trade notional at $20-25 for
   first 10 lifecycle trades** (codex round 3 — slower than
   original ramp).
4. Watch operation journal for `uncertain` outcomes — any
   uncertain = pause + manual review
5. After 10 clean lifecycle trades → notional cap $50
6. After 20 clean lifecycle trades + ≥1 partial-close verified
   live + clean reconciler → notional cap $100

### Phase 6 — scale path (week 2-4)
- Only after: ≥20 clean lifecycle trades, clean reconciler logs,
  ≥1 successful withdrawal at $50+ scale, partial-close→SL/TP-
  resize verified live
- Active capital raise to $250-$500
- Venue balance philosophy (codex round 3): **"minimum useful
  float," not a target.** Never park $500 if margin needs $200.
- 4-week mark = earliest moment to consider raising active above
  $500

## Files that will change

NEW (D-lite executor):
- `services/insiders-receiver/app/weex_client.py` — sync→async port
  of `weex_probe/weex_client.py`
- `services/insiders-receiver/app/symbol_mode_lock.py` — per-symbol
  setup mutex
- `services/insiders-receiver/app/positions_db.py` — sqlite position
  state
- `services/insiders-receiver/app/operation_journal.py` — intent
  phase journal
- `services/insiders-receiver/app/reconciler_weex.py` — WEEX-shaped
  reconciler (replaces freqtrade-shaped one)
- `services/insiders-receiver/app/weex_executor.py` — new executor

REWRITTEN:
- `services/insiders-receiver/app/executor.py` — strip
  FreqtradeClient. Mark-price source: Binance fapi → WEEX
  `/market/premiumIndex`
- `services/insiders-receiver/app/main.py` — route signal kinds to
  WeexExecutor methods
- `services/insiders-receiver/app/reconciler.py` — repurpose or
  delete (replaced by reconciler_weex.py)

SECRETS:
- `ft_userdata/insiders_bridge/secrets/insiders.session` — Palmer's
  Telethon session (after Dennis adds him)
- `services/insiders-receiver/.env` — add `WEEX_API_KEY`,
  `WEEX_API_SECRET`, `WEEX_PASSPHRASE`. Withdraw permission OFF on
  the key. IP allowlist = VPS public IP (`159.112.191.120`).
  (Mac IP `187.89.221.175` already on the existing test key.)

KEPT (no change):
- `services/killers-receiver/` — entire pipeline, Binance, untouched
- `ft_userdata/user_data/configs/InsidersScalpV1.json` — likely
  deleted at end of port; no longer used since Freqtrade is out
- `ft_userdata/docker-compose.prod.yml` — remove
  `ft-insiders-scalp` service when D-lite ships; receiver runs
  alone

## What does NOT change

- Signal parser, classifier (Claude Haiku 4.5), classifier
  dispatcher, ingress audit, atomic dedup, observer retry,
  exception middleware — all exchange-agnostic, all preserved
- Slippage gate, target guard — kept (mark-price source swapped)
- KillersScalp pipeline on Binance — separate signaler, no change
- The session-handoff doc / signaler-facing summaries

## Risks (updated post-Phase-0)

### Resolved
- ~~CCXT integration may be incomplete~~ — confirmed not available;
  bypassed entirely with custom client. Not a risk anymore.
- ~~Withdrawal may freeze (Trustpilot pattern at $5 scale)~~ —
  custody test passed in <3min. Still untested at $50+ scale.
- ~~No atomic bracket~~ — confirmed atomic via attached SL+TP on
  `/order`. Codex's main concern resolved.

### Active and load-bearing
- **WEEX venue trust at scale.** Trustpilot 2.9, Georgia C&D
  (final 2026-03-27), Arkansas C&D, "risk-bot freezes accounts"
  pattern. We proved $5 round-trips work; have not proved $200 or
  $1000 work. **Mitigation:** withdrawal tests at each capital tier
  before scaling. Keep venue balance ≤ $500 until 4-week mark.
- **Hedge-mode-broken endpoints could appear elsewhere.**
  `placeTpSlOrder` silently fails in hedge mode despite docs
  claiming otherwise. Other endpoints may have similar quirks under
  load or at scale. **Mitigation:** stick to the minimum endpoint
  surface confirmed working (see "Endpoints used" list above).
- **Symbol-mode-switch race condition.** If two new-symbol signals
  fire near-simultaneously, the `set_margin_type` + `set_leverage`
  calls could race. **Mitigation:** per-symbol mutex required
  (`symbol_mode_lock.py`).
- **Increase signal naked window.** "Buy more + cancel old SL +
  cancel old TP + place new SL + place new TP" is 5 sequential
  REST calls. Each window between calls is exposure. **Mitigation:**
  alert-only at launch; never auto-execute until properly
  designed.
- **Reconciler completeness.** Operation journal needs to
  distinguish `uncertain` (timeout, retry-after-poll) from `failed`
  (definitive). Retrying a `failed`-but-actually-`success` action
  doubles size. **Mitigation:** strict journal phases per codex;
  never blind-retry; always poll exchange state first.
- **WEEX rate limits at trade burst.** 10 req/s order/account. A
  cascade of management actions during a Dennis flurry could hit
  this. **Mitigation:** batch where possible; backoff queue with
  burst-limit awareness.
- **Telegram edit/reply context.** Dennis edits messages
  retroactively or replies into older threads. Classifier may
  attach a management action to the wrong active position.
  **Mitigation:** classifier already keys actions by symbol +
  direction; verify behaviour during the 24-72h observe window
  before live.
- **Dennis access is informal.** He approved Palmer manually. If
  he later revokes, the bot stops getting signals. **Mitigation:**
  this is just signal-source risk, not capital risk; revoking
  doesn't drain the account.
- **Polygon-only custody path.** We tested USDT/Polygon to
  Binance. TRC20 (USDT-Tron) is the other common rail with its own
  freeze patterns. **Mitigation:** stick to Polygon for the routine
  profit-extraction lane; verify TRC20 separately if ever needed.

### Codex's explicit failure modes to instrument
- WEEX accepts entry but algo spawn is delayed or missing
- Partial close succeeds but old TP/SL quantities don't adjust
  (UNVERIFIED — needs a probe)
- `modifyTpSlOrder` succeeds but modifies wrong algo type
- `closePositions` cancels child algos, partial close may not
  (UNVERIFIED)
- WEEX degraded: account endpoints fail while order endpoint still
  accepts
- Symbol precision/min-size rejection on thin pairs (verifiable
  in dry-run)
- Manual app action on operator's phone changes exchange state
  behind the bot — reconciler should catch
- Trigger fires while bot is mid-management sequence

## Trustworthiness assessment (codex framework)

### What we now trust (evidence-backed, codex round-3 corrected)
- WEEX REST surface ONLY for the exact tested low-frequency,
  one-way, small-size paths (10 endpoints, ~5 live cycles each)
- HMAC-SHA256-base64 signing + IP allowlist
- One-way mode + atomic bracket pattern
- Custody round-trip at $5 scale via Polygon (1 test, sub-3-min,
  $0.20 fee)
- Pair LISTING coverage of 28/29 Dennis symbols (listing ≠
  tradability)

### What we DON'T trust yet (verification work in Phase 4)
- Withdrawal at $50+ scale (sample size 1 at $5)
- WEEX's behavior under bot-like trade frequency
- **Partial-close auto-resize of SL/TP algos** — the unverified
  gap. After partial close, do the auto-spawned algos shrink, or
  do they keep the original size (and over-close on trigger)?
  Codex flagged this as the critical unknown.
- `modifyTpSlOrder` against repeated calls, partial fills,
  concurrent triggers
- WEEX rate-limit response under burst (10 req/s order/account)
- Whether Dennis's cadence + classifier latency fits within the
  slippage gate's tolerance
- Whether timeout-ambiguous order submissions can be cleanly
  reconciled (the central invariant — codex round 3)
- WEEX's documentation as authoritative — live probes are the
  source of truth (placeTpSlOrder hedge-mode silent break proved
  this)

### What is known broken / excluded
- Hedge (SEPARATED) mode for management endpoints. Not "don't
  trust" — actually broken. We exclude it architecturally.
- `placeTpSlOrder` in hedge mode (silently returns -1054)
- `/closePositions` with `quantity` field (ignores it, full
  flatten)
- Increase signal auto-execution. Architecturally alert-only at
  launch; classified as unsupported, not just untrusted.

### What we will never trust
- WEEX as long-term custody. C&D + Trustpilot pattern + closed-
  source venue. Withdrawals are the access path; never let balance
  grow beyond willingness-to-lose. Venue balance = "minimum useful
  float."
- The welcome bonus. Theatrical. Net ~$20.
- "96.5% listed" as a tradability claim. Listing ≠ liquidity ≠
  safe to trade. Volume filter is the real gate (<$5M 24h
  excluded).

## Reference threads / artifacts

- Today's chat with Dennis (Telegram screenshot in operator's
  message history)
- WEEX welcome-bonus page screenshot (operator's message history)
- Existing Insiders project memory:
  `~/.claude/projects/-Users-palmer-Work-Dev-master-trader/memory/project_insiders_scalp_copy_trader.md`
- Phase 2 active TP placement (just deployed for Killers):
  `~/.claude/projects/-Users-palmer-Work-Dev-master-trader/memory/project_killers_active_tp_phase2.md`
- Eduardo onboarding (now obsoleted by direct access path):
  `docs/insiders-signals/EDUARDO-ONBOARDING.md`
- Replay numbers + stack diagram (signaler-facing version, was
  drafted for Eduardo, applies to Dennis too):
  `docs/insiders-signals/eduardo-summary-2026-05-26.md`
- Session log for the killers transformation that produced the
  re-usable hardening bundle:
  `docs/SESSION-2026-05-27.md`
