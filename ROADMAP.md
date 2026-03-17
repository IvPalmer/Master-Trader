# Master Trader — Strategic Roadmap

> Last updated: 2026-03-15
> Core principle: Obsessed about not losing money. Win big, lose small.
> Only superstars go live. Patience + data > hope + speed.

---

## Current State Assessment

### What we have
- 6 bots running dry-run on Freqtrade (Docker)
- Full monitoring stack (Prometheus + Grafana)
- 9 automation scripts, evolution tracker, graduation criteria
- 156 passing tests, CI-ready test suite
- Evidence-based stoploss (-5% spot, -3% futures) validated by MAE analysis

### What we don't have
- Any bot that passes graduation (closest: SupertrendStrategy at 27/30 trades, 2/14 days)
- Live trading experience (zero real-money trades)
- Understanding of backtest-to-live performance gap for our strategies
- Sufficient capital for meaningful returns

### Key risks
- **Correlated exposure**: all bots trade same 40 coins, 3 of 6 are 1h trend-followers
- **Backtest-to-live gap**: expect PF to drop 30-50% going live (industry data)
- **Fee drag**: at small capital, fees eat 15-20% of profits
- **Over-engineering**: infrastructure built for $50K, capital is R$1,140

---

## Phase 1: Prove It (Weeks 1-6)

**Goal:** Get at least one bot through graduation gates on dry-run.

### Actions
- [ ] Let all 6 bots run undisturbed for 14+ days to accumulate trades
- [ ] Weekly: run `bot_evolution_tracker.py snapshot` + `graduation` check
- [ ] If EMACrossoverV1 has 0 trades after 7 more days, loosen ADX from 25→20 or kill it
- [ ] Run `walk_forward.py` on SupertrendStrategy (3-month backtest, 1-month OOS validation)
- [ ] Run `walk_forward.py` on BollingerRSI (same)
- [ ] Do NOT change strategy parameters during this phase (let data accumulate cleanly)

### Success criteria
- At least 1 bot passes all 4 graduation gates
- Walk-forward validation confirms strategy isn't overfit
- 30+ trades with PF ≥ 2.0, WR ≥ 55%, MaxDD < 15%

### Capital needed: R$0 (dry-run only)

---

## Phase 2: First Blood (Weeks 7-10)

**Goal:** Go live with 1 bot, prove it works with real money.

### Actions
- [ ] Fund Binance account with R$570 (~$100 USD)
- [ ] Deploy ONLY the top graduating bot (likely SupertrendStrategy)
- [ ] Config: `dry_run: false`, max_open_trades: 3, ~$33/trade
- [ ] Enable Telegram notifications for every trade
- [ ] Monitor daily: compare live PF vs dry-run PF
- [ ] Log every trade in evolution tracker
- [ ] Keep all other bots on dry-run (they keep accumulating data)

### Success criteria
- 30 days live, 20+ trades
- Live PF ≥ 1.5x (expecting ~50% drop from dry-run)
- Net profitable after fees
- No single loss > 5%
- Document the backtest-to-live gap for future calibration

### Capital: R$570 ($100)
### Expected return: R$5-15/month (5-15% monthly if strategy holds)

---

## Phase 3: Add Firepower (Weeks 11-18)

**Goal:** Scale to 2-3 live bots, increase capital.

### Actions
- [ ] If Phase 2 successful: add remaining bots to live
- [ ] $500 per bot (4 bots = $2,000 total). Equal allocation while all bots are probation tier
- [ ] Once a bot graduates (30 trades, PF≥2.0), apply tier-based rebalancing (S=30%, A=20%, B=15%)
- [ ] Anti-correlation pairlists already implemented (OffsetFilter, VolatilityFilter differentiation)
- [ ] FuturesSniperV1 operates as bear market revenue engine (shorts during BTC < SMA200)
- [ ] Start monthly capital contributions from salary (see Capital Plan below)
- [ ] Review and potentially kill underperformers monthly

### Success criteria
- 3-4 bots live, all PF > 1.5x over 30 days
- Portfolio-level MaxDD < 10%
- Monthly P/L consistently positive
- FuturesSniperV1 profitable during bear periods (validates all-weather design)
- Clear understanding of which market conditions favor which bot

### Capital: $2,000 (4 × $500)
### Expected monthly return: $50-150 (2.5-7.5%)

---

## Phase 4: Compound & Scale (Months 5-12)

**Goal:** Build the compounding snowball.

### Actions
- [ ] Increase capital to R$5,000-10,000 through monthly contributions + reinvested profits
- [ ] Add proven strategies from dry-run pipeline
- [ ] Consider adding FuturesSniperV1 if it graduates (requires separate risk allocation)
- [ ] Implement proper portfolio-level position sizing (Kelly criterion or fixed fractional)
- [ ] Add market regime detection at portfolio level (reduce all positions in high-VIX/fear periods)
- [ ] Start backtesting new strategy ideas for next generation

### Success criteria
- R$5,000+ deployed capital
- 3-4 live bots with diversified strategy types
- Annualized return 20-30% (realistic, evidence-based target)
- System runs with minimal daily intervention (< 15 min/day)

### Capital: R$5,000-10,000
### Expected monthly return: R$100-250

---

## Phase 5: Passive Income Machine (Year 2+)

**Goal:** Self-sustaining system that compounds.

### Actions
- [ ] Capital target: R$20,000-50,000
- [ ] Monthly contributions taper as profits compound
- [ ] Explore additional exchanges (KuCoin, Bybit) for arbitrage opportunities
- [ ] Consider FreqAI integration for adaptive strategies
- [ ] Build strategy factory: systematic pipeline to develop, test, graduate, deploy new strategies
- [ ] Consider VPS migration for 99.9% uptime (no more PC crash risk)

### Success criteria
- Monthly passive income R$500-1,500 (1-3% monthly on R$50K)
- System handles market regime changes without manual intervention
- New strategies regularly graduate from dry-run pipeline
- Can survive a 30% market crash without portfolio-level drawdown > 15%

---

## Capital Allocation Plan

### Monthly Budget (R$50K income)

Conservative allocation: **5-10% of income** to trading capital until system is proven.

| Month | Contribution | Cumulative Capital | Est. Monthly Return | Notes |
|-------|-------------|-------------------|--------------------|----|
| 1-2 | R$0 | R$0 | R$0 | Dry-run only (Phase 1) |
| 3 | R$570 | R$570 | R$5-15 | First live bot |
| 4 | R$1,500 | R$2,000 | R$50-100 | Add bot #2 if Phase 2 passed |
| 5 | R$1,500 | R$3,500 | R$90-175 | Phase 3 scaling |
| 6 | R$1,500 | R$5,000 | R$125-250 | Compounding kicks in |
| 7-9 | R$2,000/mo | R$11,000 | R$275-550 | Accelerate if profitable |
| 10-12 | R$2,500/mo | R$20,000+ | R$500-1,000 | + reinvested profits |
| Year 2 | R$2,500/mo | R$50,000+ | R$1,250-2,500 | Compound snowball |

### Allocation Rules

1. **Never invest more than you can afford to lose entirely.** R$2,500/month on R$50K income = 5%. Losing it all hurts but doesn't change your life.

2. **Reinvest 80% of profits, withdraw 20%.** The 20% withdrawal proves the system works and keeps you motivated. The 80% compounds.

3. **Scale capital ONLY after proven months.** Don't add R$2,500 to a bot that's losing. Only increase allocation to bots with PF > 1.5x over trailing 30 days.

4. **Per-bot allocation by performance tier:**

   | Tier | Criteria | Max Allocation |
   |------|----------|---------------|
   | S-tier | PF > 3.0, WR > 60%, 60+ trades | 30% of portfolio |
   | A-tier | PF > 2.0, WR > 55%, 30+ trades | 20% of portfolio |
   | B-tier | PF > 1.5, WR > 50%, 30+ trades | 15% of portfolio |
   | Probation | PF < 1.5 or < 30 trades live | 10% max |
   | Kill | PF < 1.0 for 14 days | 0% — remove from live |

5. **Futures allocation: never > 15% of total portfolio.** Leverage amplifies mistakes. Until you have 6+ months of live futures data, keep it small.

6. **Emergency reserve: keep R$5,000 liquid.** If the market crashes and you need to intervene, you need cash available, not locked in trades.

7. **Monthly rebalance:** On the 1st of each month, run `tournament_manager.py` and `bot_evolution_tracker.py dashboard`. Redistribute capital based on trailing 30-day performance.

### Compounding Projection (Conservative: 2% monthly)

| End of | Capital | Monthly Return | Cumulative Profit |
|--------|---------|---------------|-------------------|
| Month 6 | R$5,000 | R$100 | R$300 |
| Month 12 | R$20,000 | R$400 | R$2,500 |
| Month 18 | R$35,000 | R$700 | R$7,000 |
| Month 24 | R$55,000 | R$1,100 | R$15,000 |
| Month 36 | R$90,000 | R$1,800 | R$40,000 |

*Assumes 2% net monthly return after fees + R$2,500/month contributions for 12 months then R$1,000/month.*
*Actual returns will vary. This is a planning model, not a prediction.*

---

## Anti-Correlation Strategy (Reducing Correlated Exposure)

Current problem: all bots trade same 40 coins. If BTC dumps, everything dumps.

### Solution: Pairlist Segmentation

Split the VolumePairList across bots so they trade different pairs:

| Bot | Pairs | Logic |
|-----|-------|-------|
| SupertrendStrategy | Top 40 by volume, offset 0 | Large caps, most liquid |
| BollingerRSI | Top 40 by volume, offset 10 | Mid-caps, different from Supertrend |
| MasterTraderV1 | Top 40 by volume, offset 20 | Different segment |
| FuturesSniperV1 | Top 20 futures by volume | Futures-specific list |

Or use `OffsetFilter` in pairlist config:
```json
{"method": "OffsetFilter", "offset": 10, "number_assets": 20}
```

This ensures that if BTC/USDT appears in SupertrendStrategy's list, it doesn't appear in BollingerRSI's.

---

## What This System Is NOT

- **Not passive income from day 1.** It's a 6-12 month engineering project before meaningful returns.
- **Not a get-rich scheme.** Realistic target: 20-30% annually once mature. That's excellent for algo trading.
- **Not set-and-forget.** Market regimes change. Strategies decay. Monthly review is mandatory.
- **Not risk-free.** Even with all protections, you can lose money. The goal is to lose less than you win.

## What This System IS

- **A disciplined, evidence-based approach** to building algo trading income.
- **A learning machine** that gets better over time through evolution tracking and graduation gates.
- **A risk-first system** where capital preservation always beats profit maximization.
- **A long-term compounding vehicle** that, if it works, becomes genuinely meaningful at R$50K+ capital.

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-14 | Killed NASOSv5, ElliotV5, ClucHAnix, MasterTraderAI | Poor PF, inverted R:R, bleeding capital |
| 2026-03-14 | Added IchimokuTrendV1, EMACrossoverV1 | Diversify strategy types, backtest showed promise |
| 2026-03-15 | Tightened all SL to -5% spot, -3% futures | MAE analysis: 0% recovery past -7%, 92% of winners never dip past -3% |
| 2026-03-15 | Enabled stoploss_on_exchange on all bots | Crash protection: exchange holds stop even if PC is off |
| 2026-03-15 | Created graduation criteria | No bot goes live without 30 trades, 14 days, PF≥2.0, WR≥55% |
| 2026-03-15 | Moved ft_userdata into git repo | Single source of truth, no more sync issues |
| 2026-03-15 | Built test suite (156 tests) | Catches config errors, known bugs, infra issues before they cost money |
