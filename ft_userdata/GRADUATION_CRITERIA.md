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

Updated: 2026-03-24

| Bot | Trades | Days | PF | WR | MaxDD | Max Loss | Status |
|-----|--------|------|-----|-----|-------|----------|--------|
| SupertrendStrategy | 43 | 13 | 1.82x | 63% | 5.3% | -5.2% | **GATE 2 NEAR** — PF needs 2.0x, day 14 tomorrow |
| MasterTraderV1 | 25 | 13 | 0.81x | 60% | 2.5% | -5.2% | **GATE 2 FAIL** (PF < 2.0) |
| AlligatorTrendV1 | 0 | 7 | -- | -- | -- | -- | **GATE 1 FAIL** (zero trades, daily TF — expected) |
| GaussianChannelV1 | 0 | 7 | -- | -- | -- | -- | **GATE 1 FAIL** (zero trades, daily TF — expected) |
| BearCrashShortV1 | 0 | 1 | -- | -- | -- | -- | **GATE 1 FAIL** (no bear regime detected yet) |
| ~~BollingerRSIMeanReversion~~ | 24 | -- | 0.50x | 63% | 6.3% | -5.3% | **KILLED** 2026-03-20 |
| ~~FuturesSniperV1~~ | 9 | -- | 0.10x | 22% | 7.9% | -7.9% | **KILLED** 2026-03-20 |

**No bot is currently ready for live trading.**

SupertrendStrategy is closest: passes Gate 1 (43 trades, 13 days) and most Gate 2 metrics,
but PF 1.82x is still below the 2.0x threshold. One contaminated 4h-config trade (DOT/USDT
-$1.64, opened under 4h config on 2026-03-18) was removed from the database on 2026-03-24.
The remaining 5 stoploss hits from Mar 16-17 were legitimate 1h trades during a market dip.

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
