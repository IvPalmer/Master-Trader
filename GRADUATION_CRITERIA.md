# Bot Graduation Criteria — Dry-Run to Live

> Core principle: Obsessed about not losing money. Win big, lose small.
> Only superstars go live. OK is not good enough.

## Gate 1: Minimum Sample Size

A bot cannot be evaluated until it has enough data. Random variance dominates small samples.

| Metric | Requirement |
|--------|-------------|
| Closed trades | **>= 30** |
| Days running | **>= 14** |
| Unique pairs traded | **>= 8** |

**Why 30 trades?** Below 20, a single outlier can fake a 70% win rate. At 30+ we can
trust the statistics. Our killed bots looked decent at 10 trades then collapsed.

**Why 14 days?** Must survive at least one weekend (low liquidity), one news cycle,
and both bullish and bearish micro-regimes.

**Why 8 pairs?** A bot that only profits on one pair is fragile. It must prove
it works across diverse coins.

---

## Gate 2: Superstar Metrics

ALL of these must be met simultaneously. One miss = not ready.

| Metric | Threshold | Why |
|--------|-----------|-----|
| **Profit Factor** | **>= 2.0x** | Every killed bot was < 1.6x. Superstars are 1.9x+. Hard floor. |
| **Win Rate** | **>= 55%** | Below this, the bot needs outsized R:R to compensate. Our best have 59-75%. |
| **Net P/L** | **> 0 (profitable)** | Non-negotiable. Must make money after fees. |
| **Max Single Loss** | **< 5% of stake** | With -5% SL this should be automatic. Any loss > 5% = bug or config error. |
| **Max Drawdown** | **< 15% of wallet** | Our killed bots had 20-44% drawdowns. Superstar ceiling is 15%. |
| **Consecutive Losses** | **<= 4** | MasterTraderAI had 8 in a row. Supertrend's worst was 4 — that's the ceiling. |
| **Force/Emergency Exits** | **0** | These indicate bugs, crashes, or config problems. Must be zero. |

---

## Gate 3: Consistency Check

Passing Gate 2 once isn't enough. The bot must be consistent, not lucky.

| Metric | Threshold | Why |
|--------|-----------|-----|
| **Rolling 7-day P/L** | **No 7-day window negative by > 5%** | A superstar doesn't have bad weeks that wipe a month of gains. |
| **Win rate stability** | **Never drops below 45% over any 10-trade window** | Detects strategies that "work then die." |
| **No single trade > 30% of total P/L** | Required | If one lucky trade carries the bot, it's fragile. |

---

## Gate 4: Live Readiness Checklist

Technical requirements before deploying real money.

- [ ] `stoploss_on_exchange: true` in config
- [ ] `stoploss_on_exchange_interval: 60` in config
- [ ] `cancel_open_orders_on_exit: true` in config
- [ ] API keys configured (key + secret)
- [ ] `dry_run: false`
- [ ] `dry_run_wallet` removed or ignored
- [ ] Wallet funded with allocated USDT
- [ ] `max_open_trades` set for capital (trades * $10 minimum < wallet)
- [ ] Telegram notifications enabled
- [ ] Circuit breaker active (10% portfolio drawdown kills all bots)
- [ ] VPN bypass configured (`extra_hosts` in docker-compose)
- [ ] One manual test trade placed and verified

---

## Current Bot Status vs Criteria

Updated: 2026-03-15

| Bot | Trades | Days | PF | WR | MaxDD | Max Loss | Status |
|-----|--------|------|-----|-----|-------|----------|--------|
| SupertrendStrategy | 27 | 2 | 4.7x | 59% | $4.91 | -2.4% | **GATE 1 FAIL** (need 30 trades, 14 days) |
| BollingerRSI | 12 | 2 | 1.9x | 75% | $12.64 | -6.2% | **GATE 1 FAIL** (need 30 trades, 14 days) |
| MasterTraderV1 | 20 | 3 | 0.9x | 60% | $22.99 | -9.9% | **GATE 2 FAIL** (PF < 2.0, MaxDD > 15%) |
| IchimokuTrendV1 | 2 | 0 | 0.2x | 50% | $20.01 | -10.1% | **GATE 1 FAIL** (way too early) |
| EMACrossoverV1 | 0 | 0 | -- | -- | -- | -- | **GATE 1 FAIL** (zero trades) |
| FuturesSniperV1 | 1 | 0 | 0.0x | 0% | $19.66 | -7.9% | **GATE 1 FAIL** (way too early) |

**No bot is currently ready for live trading.**

Closest: SupertrendStrategy needs 3 more trades and 12 more days of dry-run.
After that, if its metrics hold, it will be the first to graduate.

---

## Promotion / Demotion Rules

### Promote to live:
- Pass all 4 gates
- Manual review and approval before going live

### Demote from live (kill switch):
If ANY of these trigger on a live bot, immediately stop it:
- P/L drops below -5% of allocated capital
- 3 consecutive losses
- Any single trade loss > 5%
- Profit factor drops below 1.5x (trailing 20-trade window)

### Re-evaluation:
- Killed bots can re-enter dry-run with parameter changes
- Must pass all gates again from scratch — no credit for past performance
