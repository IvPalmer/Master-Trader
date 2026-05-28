# Plan — Insiders Scalp (Dennis / Alpha Scalp) on WEEX

**Status:** decision made 2026-05-28. Session handoff doc for the next
session to execute. **Nothing committed/deployed against this plan yet.**

## TL;DR

- Pay Dennis 1.500 BRL (~$275) for the 6-month "Alpha Scalp" plan to
  get direct access to the Insiders Scalp Telegram channel.
- Switch our existing Insiders pipeline from Binance USDT-M Futures to
  **WEEX** USDT-M futures.
- Drops the Eduardo Melo .session dependency that's been blocking
  MVP-2 for 9+ days.
- Target live capital: $500–$1.000 to start.
- KillersScalp pipeline stays on Binance — independent signaler
  (Binance Killers VIP), no change.

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

### Option C — Pay Dennis, port our pipeline to WEEX **← chosen**
- ✅ Captures WEEX bonus ($250 worth, exact amount TBD)
- ✅ Mirrors Dennis's setup exactly — TP fills hit same order book
- ✅ Affiliate alignment if we ever want strategic partnership
- ⚠️ Requires WEEX integration in Freqtrade (CCXT supports WEEX —
  unverified for USDT-M futures specifically)
- ⚠️ Requires re-validating Binance-mark-based guards (slippage gate,
  target guard) against WEEX mark or accepting cross-exchange basis
  drift

## What needs to change

### 1. WEEX exchange integration in Freqtrade
- Verify CCXT supports `weex` exchange + USDT-M perp futures
- Update `ft_userdata/user_data/configs/InsidersScalpV1.json`:
  - `"exchange.name": "weex"` (currently `"binance"`)
  - WEEX API key / secret from a new sub-account
  - Verify supported `pair_whitelist` matches Dennis's signal universe
- Test paper-trade on WEEX with dry-run wallet $200 BEFORE flipping
  to live

### 2. Mark price source for guards
Current code in `services/insiders-receiver/app/executor.py`:
- `get_mark_price()` fetches from `fapi.binance.com/fapi/v1/premiumIndex`
- Used by: slippage gate, target guard, market-sanity band

Options:
- (a) Keep Binance mark — cross-exchange basis is usually tight on
  major pairs (<0.1%) but can widen on alts. Risk: skip-or-not
  decisions made on Binance might not match what WEEX fills at.
- (b) Switch to WEEX mark — needs API discovery (WEEX premium index
  endpoint?). May not exist; WEEX is less mature than Binance.
- (c) Hybrid — Binance for the slippage gate (where we just need
  "is the market roughly there?") + WEEX for the actual fill price
  (after the order is placed, FT knows the fill).

Recommendation: start with (a), monitor basis drift, switch to (c) if
divergence > 0.5%.

### 3. Symbol mapping
Current code:
- `to_freqtrade_pair("BTC")` → `"BTC/USDT:USDT"` (Binance perp format)
- `to_binance_perp_symbol("BTC")` → `"BTCUSDT"` (Binance API symbol)

WEEX uses its own naming. Need to:
- Verify which signal symbols are tradeable on WEEX
- Update `SYMBOL_ALIASES` for any pairs WEEX names differently
- Check WEEX support for 1000-prefix alts (1000PEPE, 1000SHIB, etc.)

### 4. Listener (.session) source
Current plan: use Eduardo's .session.
New plan: generate our OWN .session for Palmer's Telegram account, now
that Dennis approved us as a direct member.

Steps:
1. Run `killers_bot/generate_session.py` adapted for Insiders
   (or reuse since it's the same Telethon flow)
2. Use Palmer's API_ID / API_HASH from `my.telegram.org`
   (already on VPS — reused for Killers observer)
3. Subscribe to Dennis's channel from Palmer's account (Dennis's chat
   should have an invite link)
4. Drop the new `palmer-insiders.session` at
   `ft_userdata/insiders_bridge/secrets/insiders.session` on VPS
5. Listener picks it up + subscribes — same env path that was
   blocked waiting for Eduardo

### 5. KillersScalp untouched
- Killers VIP is a separate signaler, traded on Binance
- Their pipeline (`services/killers-receiver/`) stays exactly as
  deployed yesterday (commit `dfa5a2a`)
- DO NOT confuse the two when refactoring the Insiders receiver

## Open questions to resolve in next session

1. **Real WEEX bonus extractable amount.** Channel says "$250", WEEX
   homepage shows up to "$12.000" but in trading credits with
   lockups. Net cash equivalent likely $50-150. Confirm with Dennis
   what specifically maps to our affiliate signup.
2. **WEEX API availability + rate limits.** Sign up for a sub-account,
   generate API key, test REST + WebSocket reachability from the VPS.
3. **CCXT support for WEEX USDT-M futures.** Open the CCXT exchange
   list, verify `weex` is there + futures methods work. If not, may
   need ccxt fork or proxy through a different exchange ID.
4. **Liquidity on WEEX for Dennis's signal universe.** Pull 24h
   volume per pair Dennis trades. If liquidity is thin on alts, may
   need pair-whitelist trimming (skip thin pairs to avoid slippage
   eating the edge).
5. **Funding rate basis vs Binance.** WEEX perp funding may differ
   meaningfully from Binance. Audit before sizing up.

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

## Concrete next-session execution order

The next session should pick this up in roughly this order:

### Phase 0 — pre-pay validation (30 min)
1. Discover the actual WEEX welcome-bonus structure (which coupons,
   what lockups, what's cash-equivalent)
2. Verify CCXT supports WEEX USDT-M futures via Freqtrade
3. Confirm Dennis's pair universe is liquid enough on WEEX

If any of these fails → re-evaluate Option A (Binance + pay Dennis +
just take the bonus separately).

### Phase 1 — payment + access (1 hour)
1. Pay Dennis 1.500 BRL via whatever rails he prefers (likely PIX or
   crypto)
2. Wait for him to add Palmer to the channel
3. Generate Palmer's `.session` for the Insiders channel via
   Telethon auth flow (reuse `killers_bot/generate_session.py`
   pattern)
4. Encrypt the new session via age + drop at
   `ft_userdata/insiders_bridge/secrets/insiders.session` on VPS

### Phase 2 — WEEX paper trade (2-4 hours)
1. Create WEEX account (already done — operator did 2026-05-28 13:52)
2. Sub-account + API key for the bot (NOT the master key)
3. Modify `InsidersScalpV1.json` exchange config to WEEX
4. Build + deploy a separate `ft-insiders-scalp-weex` container
   (alongside the existing Binance one — keep both up for parity
   comparison during the trial)
5. Verify the slippage gate, target guard, active TP placement, and
   reconciler all work with WEEX's order responses (some FT REST
   responses are exchange-specific)
6. Run paper for 7-14 days, compare PnL vs the parallel Binance
   dry-run

### Phase 3 — go live (after Phase 2 passes)
1. Fund WEEX sub-account with $500-$1.000
2. Flip `dry_run: false` in the config
3. Watch first 5 real fills closely
4. Update memory + session log + this plan doc

## Files that will change

- `ft_userdata/user_data/configs/InsidersScalpV1.json` — exchange
  config (weex, sub-account creds, pair whitelist)
- `ft_userdata/docker-compose.prod.yml` — add `insiders-scalp-weex`
  service if running in parallel during trial, or just modify the
  existing one if cutting over directly
- `services/insiders-receiver/app/executor.py` — possibly switch
  `get_mark_price` to WEEX endpoint (or hybrid)
- `services/insiders-receiver/app/main.py` — likely no changes
  (the strategy file + Freqtrade-side config carries the exchange)
- `ft_userdata/insiders_bridge/.env.example` — note WEEX API keys
- `ft_userdata/insiders_bridge/secrets/` — new `insiders.session` for
  Palmer's direct access

## What does NOT change

- The whole hardening bundle we shipped 2026-05-27 (slippage gate,
  rule fast-path, active TP placement, ingress audit, atomic dedup,
  observer retry, exception middleware) — all exchange-agnostic
- Killers receiver stays on Binance (separate signaler)
- Insiders receiver business logic stays the same (only the Freqtrade
  config + possibly mark-price source changes)

## Risks

- **CCXT WEEX integration may be incomplete.** If futures methods
  aren't supported, we're either stuck on Binance for the bot or
  need to write custom WEEX REST glue. Mitigation: verify in Phase 0
  before paying.
- **Cross-exchange basis on alts.** Slippage gate currently fetches
  Binance mark. If WEEX alt prices diverge >0.5% routinely, the
  gate's decisions don't match the actual fill exchange. Mitigation:
  monitor + switch to WEEX-mark or hybrid.
- **WEEX is less mature** than Binance — possible REST API quirks,
  rate limit differences, downtime risk. Mitigation: smaller capital
  in Phase 3.
- **Dennis approval is informal.** If he later wants to renegotiate
  or revoke, we're exposed. Mitigation: keep using Binance pipeline
  for Killers; Insiders is just one of multiple signalers if it falls
  through.

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
