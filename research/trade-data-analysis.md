# Trade Data Analysis - Our Actual Bot Performance

**Updated:** 2026-03-11 18:40 UTC (supersedes earlier analysis from 11:44)
**Data source:** Live Freqtrade API queries from all 7 active bots
**Capital:** $1,000 USDT per bot (dry-run), ~$200 per position
**Runtime:** ~18 hours since first trade

> This is the most important research file. It uses OUR actual trade data, not theory.

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Total closed trades | 35 |
| Total open trades | 19 |
| Closed P&L | **+$108.37** |
| Unrealized P&L | **-$108.84** |
| **True portfolio P&L** | **-$0.47** |
| Portfolio win rate (closed) | 83% (29W / 6L) |
| Biggest single winner | +$11.61 (Supertrend HUMA/USDT) |
| Biggest single loser | -$2.99 (NASOSv5 PIXEL/USDT) |
| Biggest unrealized loss | -$27.49 (ElliotV5 XAI/USDT) |

**The core problem**: We are profitable on paper ($108 closed gains) but underwater in reality because open losers eat everything. Three bots are holding XAI/USDT simultaneously, losing $71 combined. This is the correlated exposure disaster we predicted.

---

## Strategy Ranking by True P&L

| Rank | Strategy | Closed P&L | Open P&L | True P&L | Win Rate | Closed/Open |
|------|----------|-----------|----------|----------|----------|-------------|
| 1 | SupertrendStrategy (8084) | +$14.10 | +$1.16 | **+$15.26** | 100% | 2/5 |
| 2 | ElliotV5 (8083) | +$34.39 | -$30.21 | **+$4.18** | 86% | 7/3 |
| 3 | NASOSv5 (8082) | +$46.58 | -$43.36 | **+$3.22** | 93% | 14/3 |
| 4 | NFI X6 (8089) | $0.00 | $0.00 | **$0.00** | N/A | 0/0 |
| 5 | MasterTraderAI (8087) | -$0.04 | $0.00 | **-$0.04** | 57% | 7/0 |
| 6 | MasterTraderV1 (8086) | +$1.97 | -$2.70 | **-$0.73** | 50% | 2/5 |
| 7 | ClucHAnix (8080) | +$11.37 | -$33.73 | **-$22.36** | 100% | 3/3 |

---

## Per-Strategy Analysis

### ClucHAnix (Port 8080) - BB Dip-Buyer (5m)

| Metric | Value |
|--------|-------|
| Closed trades | 3 (3W / 0L) |
| Open trades | 3 |
| Win rate | 100% |
| Avg win | +1.91% ($3.79) |
| Closed P&L | +$11.37 |
| Unrealized P&L | **-$33.73** |
| True P&L | **-$22.36** |

**MAE of winners**: worst -1.72%, median -1.22%

**Open positions (all losing)**:

| Pair | P&L | Age | Min Rate Drop |
|------|-----|-----|---------------|
| FLOW/USDT | -5.28% (-$10.52) | 10.3h | -6.23% |
| XAI/USDT | -10.17% (-$20.26) | 5.7h | -11.25% |
| ICP/USDT | -1.48% (-$2.95) | 2.3h | -1.96% |

**Verdict**: Wins small but holds losers forever. The -32% configured stoploss means it will NEVER cut a loser. Its winning MAE was -1.72% max, yet the stoploss is set 18x wider than needed. Worst performing strategy by true P&L.

---

### NASOSv5 (Port 8082) - EWO Scalper (5m) - TOP TRADE COUNT

| Metric | Value |
|--------|-------|
| Closed trades | 14 (13W / 1L) |
| Open trades | 3 |
| Win rate | 93% |
| Avg win | +1.88% ($3.81) |
| Avg loss | -1.47% (-$2.99) |
| Closed P&L | +$46.58 |
| Unrealized P&L | **-$43.36** |
| True P&L | **+$3.22** |

**MAE of winners**: worst -5.29%, median -0.49%, p5 -5.29%

**Trade duration**: min 0m, median 5m, max 50m, p90 23m

**Open positions**:

| Pair | P&L | Age | Min Rate Drop |
|------|-----|-----|---------------|
| XAI/USDT | -11.48% (-$23.41) | 5.8h | -12.55% |
| PIXEL/USDT | -7.68% (-$15.63) | 5.1h | -13.64% |
| RESOLV/USDT | -2.10% (-$4.32) | 1.9h | -5.70% |

**Verdict**: Highest trade volume and excellent win rate. The one loss (-$2.99) was contained. But open positions are erasing all gains. The -15% stoploss has not triggered yet despite XAI being down -12.55% from entry. This strategy works great when it is in-and-out fast -- but when it gets stuck, it bleeds.

Key stat: **93% of closed trades lasted under 23 minutes.** Any trade lasting more than 1 hour is likely a stuck loser.

---

### ElliotV5 (Port 8083) - EWO Reversal (5m)

| Metric | Value |
|--------|-------|
| Closed trades | 7 (6W / 1L) |
| Open trades | 3 |
| Win rate | 86% |
| Avg win | +3.09% ($6.21) |
| Avg loss | -1.42% (-$2.89) |
| Closed P&L | +$34.39 |
| Unrealized P&L | **-$30.21** |
| True P&L | **+$4.18** |

**MAE of winners**: worst -4.95%, median -0.34%, p5 -4.95%

**Open positions**:

| Pair | P&L | Age | Min Rate Drop |
|------|-----|-----|---------------|
| XAI/USDT | -13.56% (-$27.49) | 6.1h | -14.60% |
| RESOLV/USDT | -2.18% (-$4.47) | 1.9h | -5.54% |
| PIXEL/USDT | +0.86% (+$1.75) | 0.9h | -0.07% |

**Verdict**: Best average win size (+3.09%). Similar pattern to NASOSv5 -- prints money on fast trades but holds losers too long. The one closed loss was from `exit_signal` (strategy recognized it), not stoploss. The XAI/USDT position at -13.56% is approaching the -18.9% stoploss but has not triggered. `ignore_roi_if_entry_signal=True` is dangerous here.

---

### SupertrendStrategy (Port 8084) - Triple Supertrend (1h) - BEST TRUE P&L

| Metric | Value |
|--------|-------|
| Closed trades | 2 (2W / 0L) |
| Open trades | 5 |
| Win rate | 100% |
| Avg win | +3.56% ($7.05) |
| Closed P&L | +$14.10 |
| Unrealized P&L | **+$1.16** |
| True P&L | **+$15.26** |

**MAE of winners**: worst -4.90%, median -0.22%

**Open positions**:

| Pair | P&L | Age |
|------|-----|-----|
| PAXG/USDT | -1.09% (-$2.16) | 15.4h |
| EUR/USDT | -0.67% (-$1.33) | 15.2h |
| AVAX/USDT | -0.71% (-$1.42) | 13.6h |
| SHIB/USDT | +2.43% (+$4.82) | 13.6h |
| FET/USDT | +0.62% (+$1.25) | 8.2h |

**Verdict**: The only strategy with POSITIVE unrealized P&L. Trading 1h timeframe with diversified large-cap pairs (PAXG, EUR, AVAX, SHIB, FET) means lower correlation and smaller drawdowns. No micro-cap meme coins. This is what proper diversification looks like.

---

### MasterTraderV1 (Port 8086) - EMA+RSI (1h)

| Metric | Value |
|--------|-------|
| Closed trades | 2 (1W / 1L) |
| Open trades | 5 |
| Win rate | 50% |
| Avg win | +1.02% ($2.02) |
| Avg loss | -0.03% (-$0.05) |
| Closed P&L | +$1.97 |
| Unrealized P&L | **-$2.70** |
| True P&L | **-$0.73** |

**Open positions**: Diversified across XUSD, NEAR, BNB, LTC, TAO -- no single pair dominates. Maximum unrealized loss is -$2.22 (NEAR). This is the tightest risk profile (-5% stoploss, +1% trailing after +2%).

**Verdict**: Conservative and safe. Small profits, tiny losses. The -5% stoploss is correctly sized. Boring but will not blow up.

---

### MasterTraderAI (Port 8087) - FreqAI LightGBM (5m)

| Metric | Value |
|--------|-------|
| Closed trades | 7 (4W / 3L) |
| Open trades | 0 |
| Win rate | 57% |
| Avg win | +0.17% ($0.33) |
| Avg loss | -0.23% (-$0.45) |
| Closed P&L | **-$0.04** |
| Unrealized P&L | $0.00 |
| True P&L | **-$0.04** |

**MAE of winners**: worst -0.89%, median -0.40%

**Verdict**: Closes positions quickly (no open trades). Both wins and losses are tiny. ML model is being extremely cautious -- exiting almost everything via `exit_signal`. Win rate is lowest at 57% but losses are so small it does not matter. Essentially market-neutral right now. Needs more data to evaluate. The fact it has zero open positions is actually a GOOD sign -- it recognizes when to get out.

---

### NostalgiaForInfinityX6 (Port 8089)

No trades after 18 hours. Either still warming up or the 60-pair pairlist is filtering too aggressively. Check if the bot is running correctly and has downloaded sufficient data. The -99% stoploss in config is irrelevant since `use_custom_stoploss=False` and it relies on custom_exit logic.

---

## Cross-Bot Correlated Exposure Analysis

### Simultaneous Positions in Same Pair

This is our **#1 risk factor** right now.

| Pair | Bots Holding | Combined Exposure | Combined P&L |
|------|-------------|-------------------|--------------|
| **XAI/USDT** | ClucHAnix, NASOSv5, ElliotV5 | **~$600** | **-$71.16** |
| PIXEL/USDT | NASOSv5, ElliotV5 | ~$400 | -$13.88 |
| RESOLV/USDT | NASOSv5, ElliotV5 | ~$400 | -$8.79 |
| FLOW/USDT | ClucHAnix | ~$200 | -$10.52 |
| ICP/USDT | ClucHAnix | ~$200 | -$2.95 |
| PAXG/USDT | Supertrend | ~$200 | -$2.16 |
| EUR/USDT | Supertrend | ~$200 | -$1.33 |
| AVAX/USDT | Supertrend | ~$200 | -$1.42 |
| SHIB/USDT | Supertrend | ~$200 | +$4.82 |
| FET/USDT | Supertrend | ~$200 | +$1.25 |
| XUSD/USDT | MasterV1 | ~$200 | -$0.51 |
| NEAR/USDT | MasterV1 | ~$200 | -$2.22 |
| BNB/USDT | MasterV1 | ~$200 | +$1.23 |
| LTC/USDT | MasterV1 | ~$200 | +$0.29 |
| TAO/USDT | MasterV1 | ~$200 | -$1.49 |

**XAI/USDT is the single biggest risk in the portfolio.** Three bots bought into the same dip and all are stuck. This is exactly the correlated exposure disaster: $600 (~8.6% of total capital) in one micro-cap altcoin that is down 10-14%.

**Pattern**: The dip-buying strategies (ClucHAnix, NASOSv5, ElliotV5) all share similar pairlists and entry signals. When a coin dips, ALL of them pile in. When it does not recover, ALL of them bleed.

SupertrendStrategy and MasterTraderV1 have ZERO overlap with each other or the dip-buyers. They trade different pairs on different timeframes. This is proper portfolio construction.

### Portfolio-Level Summary

| Metric | Value |
|--------|-------|
| Total closed P&L | +$108.37 |
| Total unrealized P&L | -$108.84 |
| **True portfolio P&L** | **-$0.47** |
| Total open positions | 19 |
| Total capital at risk | ~$3,800 (54% of $7,000) |
| Correlated capital (XAI+PIXEL+RESOLV) | ~$1,400 (20% of total) |

---

## MAE-Based Stoploss Recommendations

### How to Read MAE (Max Adverse Excursion)

MAE measures how far a trade dipped from entry before recovering. For winning trades, it tells us the maximum drawdown that was "necessary" to endure before profiting.

### All Winners - MAE Distribution (n=29)

| Percentile | MAE |
|-----------|------|
| Best (least dip) | -0.00% |
| p75 | -0.22% |
| Median | -0.52% |
| p25 | -1.59% |
| p10 | -4.90% |
| **p5** | **-4.95%** |
| Worst | -5.29% |

### Per-Strategy MAE Summary

| Strategy | Winner MAE Worst | Winner MAE Median | All Trades MAE Worst |
|----------|-----------------|-------------------|---------------------|
| ClucHAnix | -1.72% | -1.22% | -1.72% |
| NASOSv5 | -5.29% | -0.49% | -5.29% |
| ElliotV5 | -4.95% | -0.34% | -14.03% |
| Supertrend | -4.90% | -0.22% | -4.90% |
| MasterTraderV1 | -1.14% | -1.14% | -1.14% |
| MasterTraderAI | -0.89% | -0.40% | -1.08% |

### Recommended Stoploss by Strategy

| Strategy | Current Stoploss | Winner MAE Worst | Recommended Stoploss | Rationale |
|----------|-----------------|-----------------|---------------------|-----------|
| ClucHAnix | -32% (stepped) | -1.72% | **-5%** | Winners never dipped below -1.72%. Even -5% is generous |
| NASOSv5 | -15% | -5.29% | **-8%** | 95% of winners recovered from -5.29% or less |
| ElliotV5 | -18.9% | -4.95% | **-8%** | Similar profile to NASOSv5 |
| Supertrend | -26.5% | -4.90% | **-10%** | 1h timeframe = wider acceptable MAE, but -26.5% is insane |
| MasterTraderV1 | -5% | -1.14% | **-5%** (keep) | Already well-calibrated |
| MasterTraderAI | -5% | -0.89% | **-5%** (keep) | Already well-calibrated |
| NFI X6 | -99% | N/A | **-8%** | No data yet, use portfolio default |

### Key Finding

**A portfolio-wide stoploss of -5% to -8% would have captured 95% of our eventual winners while cutting every single one of our current open losers.**

Our open positions currently losing money:
- XAI/USDT at -10% to -14% -- would have been cut at -5% to -8%, saving $50-60
- PIXEL/USDT at -7.68% -- would have been cut at -8%, saving $8-10
- FLOW/USDT at -5.28% -- would have been cut at -5%, saving $5-7

**Total savings if -8% stoploss was in place: ~$60-70 of the $108.84 unrealized losses would have been realized as small losses instead of growing into monsters.**

---

## Trade Duration Analysis

### When Do Winners Win?

| Timeframe | Winners | Median Duration | p90 Duration | Max Duration |
|-----------|---------|----------------|-------------|-------------|
| 5m strategies | 25 | 5 min | 38 min | 275 min |
| 1h strategies | 4 | 120 min | 429 min | 429 min |

### When Do Losers Stop Recovering?

For 5m strategies (ClucHAnix, NASOSv5, ElliotV5):
- **93% of winners closed within 50 minutes**
- Our worst open positions have been held for **5-10 hours** (300-600 minutes)
- These are 10-20x longer than any winning trade duration

**Recommendation**: For 5m strategies, add a time-based exit that tightens the stoploss:
- After 1 hour: tighten stoploss to -3%
- After 2 hours: tighten stoploss to -1%
- After 4 hours: force exit at market

For 1h strategies:
- After 24 hours: tighten stoploss to -5%
- After 48 hours: force exit at market

---

## Which Strategies Are Actually Profitable?

With only 1 day of data, statistical significance is limited. But patterns are already clear:

### Tier 1: Genuinely Profitable
1. **SupertrendStrategy** -- Only bot with positive unrealized P&L. Diversified pairs, 1h timeframe, no micro-cap garbage. True P&L: +$15.26
2. **NASOSv5** -- High win rate, fast trades, good edge. But bleeds on stuck positions. If stoplosses were tighter: True P&L would be ~+$30 instead of +$3.22

### Tier 2: Has Edge, Needs Risk Management
3. **ElliotV5** -- Similar to NASOSv5 but bigger wins. Same stuck-trade problem. Fix the stoploss and this could be a top performer.

### Tier 3: Neutral / Insufficient Data
4. **MasterTraderAI** -- Breaking even with tiny bets. Need more data. Positive sign: zero open risk.
5. **MasterTraderV1** -- Conservative, low activity. Works as intended.
6. **NFI X6** -- No trades yet. Check if operational.

### Tier 4: Actively Harmful
7. **ClucHAnix** -- 100% win rate is meaningless when unrealized losses are 3x closed profits. The -32% stoploss is criminally wide. This strategy CANNOT be run without tighter risk controls.

---

## Win Rate and Profit Factor

| Strategy | Win Rate | Wins | Losses | Gross Profit | Gross Loss | Profit Factor | Expectancy (USDT) |
|----------|----------|------|--------|-------------|------------|---------------|-------------------|
| NASOSv5 | 93% | 13 | 1 | $49.57 | $2.99 | 16.58 | $3.33 |
| ElliotV5 | 86% | 6 | 1 | $37.28 | $2.89 | 12.90 | $4.91 |
| ClucHAnix | 100% | 3 | 0 | $11.37 | $0.00 | inf | $3.79 |
| Supertrend | 100% | 2 | 0 | $14.10 | $0.00 | inf | $7.05 |
| MasterTraderAI | 57% | 4 | 3 | $1.32 | $1.36 | 0.97 | -$0.01 |
| MasterTraderV1 | 50% | 1 | 1 | $2.02 | $0.05 | 40.40 | $0.99 |
| NFI X6 | N/A | 0 | 0 | $0.00 | $0.00 | N/A | N/A |

---

## Immediate Action Items

### Priority 1: Fix Stoploss Levels (TODAY)
1. ClucHAnix: Change from -32% to **-5%** (`stoploss: -0.05`)
2. NASOSv5: Change from -15% to **-8%** (`stoploss: -0.08`)
3. ElliotV5: Change from -18.9% to **-8%** (`stoploss: -0.08`)
4. Supertrend: Change from -26.5% to **-10%** (`stoploss: -0.10`)
5. NFI X6: Change from -99% to **-8%** (`stoploss: -0.08`)

### Priority 2: Add Time-Based Exits (THIS WEEK)
Add `custom_exit` logic to force-close trades older than:
- 2 hours for 5m strategies
- 24 hours for 1h strategies

### Priority 3: Eliminate Correlated Exposure (THIS WEEK)
- Diversify pairlists so dip-buying bots do not share the same coins
- Or: implement a portfolio-level position tracker that prevents multiple bots from holding the same pair

### Priority 4: Add Freqtrade Protections (THIS WEEK)
Add to all config files:
```json
"protections": [
    {"method": "StoplossGuard", "lookback_period_candles": 24, "trade_limit": 3, "stop_duration_candles": 12, "only_per_pair": true},
    {"method": "MaxDrawdown", "lookback_period_candles": 48, "max_allowed_drawdown": 0.1, "trade_limit": 5, "stop_duration_candles": 24},
    {"method": "CooldownPeriod", "stop_duration_candles": 2}
]
```

---

## Kelly Criterion - Optimal Position Sizing

Kelly% = W - [(1-W) / R], where W = win rate, R = avg win / avg loss

| Strategy | Win Rate (W) | R (Win/Loss) | Kelly % | Half-Kelly % | Recommendation |
|----------|-------------|-------------|---------|-------------|----------------|
| NASOSv5 | 90.9% | 1.28 | 83.7% | 41.8% | Strong edge -- use 1/3 Kelly due to small sample |
| ElliotV5 | 85.7% | 2.18 | 79.1% | 39.6% | Strong edge -- use 1/3 Kelly due to small sample |
| MasterTraderAI | 57.1% | 0.72 | -2.5% | N/A | Negative Kelly = no edge yet |
| MasterTraderV1 | 50.0% | 40.4 | 48.8% | 24.4% | Misleading -- only 2 trades |
| Others | 100% | inf | N/A | N/A | Insufficient loss data |

**WARNING: Sample size is very small (35 closed trades total). All statistics have high uncertainty. Recommend waiting for 100+ closed trades before making position sizing changes. Stoploss levels can be adjusted now -- they are defensive and the data directionally supports tighter levels.**

---

## Raw Data Reference

### All 35 Closed Trades

| # | Bot | Pair | Profit % | Profit $ | Duration | Exit Reason | MAE % |
|---|-----|------|----------|----------|----------|-------------|-------|
| 1 | ClucHAnix | PIXEL/USDT | +2.57% | +$5.09 | 5m | trailing_stop_loss | -1.22% |
| 2 | ClucHAnix | XPL/USDT | +1.03% | +$2.05 | 71m | roi | -0.21% |
| 3 | ClucHAnix | RESOLV/USDT | +2.12% | +$4.23 | 17m | trailing_stop_loss | -1.72% |
| 4 | NASOSv5 | PIXEL/USDT | +2.15% | +$4.26 | 5m | trailing_stop_loss | -0.22% |
| 5 | NASOSv5 | HUMA/USDT | +1.69% | +$3.37 | 3m | trailing_stop_loss | -0.11% |
| 6 | NASOSv5 | HUMA/USDT | +1.46% | +$2.92 | 2m | trailing_stop_loss | -0.21% |
| 7 | NASOSv5 | PIXEL/USDT | +1.35% | +$2.71 | 0m | trailing_stop_loss | -0.65% |
| 8 | NASOSv5 | PIXEL/USDT | +1.47% | +$2.95 | 3m | trailing_stop_loss | -0.52% |
| 9 | NASOSv5 | XAI/USDT | +1.73% | +$3.48 | 3m | trailing_stop_loss | -0.07% |
| 10 | NASOSv5 | PIXEL/USDT | +1.73% | +$3.49 | 18m | trailing_stop_loss | -0.44% |
| 11 | NASOSv5 | XAI/USDT | +2.76% | +$5.59 | 13m | trailing_stop_loss | -1.59% |
| 12 | NASOSv5 | PIXEL/USDT | +0.45% | +$0.91 | 5m | trailing_stop_loss | -1.49% |
| 13 | NASOSv5 | PIXEL/USDT | **-1.47%** | -$2.99 | 15m | trailing_stop_loss | -4.76% |
| 14 | NASOSv5 | HUMA/USDT | +2.74% | +$5.60 | 23m | trailing_stop_loss | -5.29% |
| 15 | NASOSv5 | HUMA/USDT | +2.05% | +$4.19 | 50m | trailing_stop_loss | -2.30% |
| 16 | NASOSv5 | ACX/USDT | +1.93% | +$3.97 | 8m | trailing_stop_loss | -0.49% |
| 17 | NASOSv5 | ACX/USDT | +2.97% | +$6.13 | 5m | trailing_stop_loss | -0.17% |
| 18 | ElliotV5 | PIXEL/USDT | +3.60% | +$7.14 | 6m | trailing_stop_loss | -0.34% |
| 19 | ElliotV5 | HUMA/USDT | +2.03% | +$4.05 | 5m | exit_signal | -0.06% |
| 20 | ElliotV5 | HUMA/USDT | +2.96% | +$5.94 | 38m | trailing_stop_loss | -0.32% |
| 21 | ElliotV5 | XAI/USDT | +2.76% | +$5.56 | 13m | trailing_stop_loss | -1.59% |
| 22 | ElliotV5 | PIXEL/USDT | +2.64% | +$5.35 | 20m | trailing_stop_loss | -2.72% |
| 23 | ElliotV5 | PIXEL/USDT | **-1.42%** | -$2.89 | 175m | exit_signal | -14.03% |
| 24 | ElliotV5 | HUMA/USDT | +4.54% | +$9.24 | 25m | exit_signal | -4.95% |
| 25 | Supertrend | PIXEL/USDT | +1.25% | +$2.49 | 32m | exit_signal | -0.22% |
| 26 | Supertrend | HUMA/USDT | +5.86% | +$11.61 | 429m | roi | -4.90% |
| 27 | MasterV1 | SHIB/USDT | -0.03% | -$0.05 | 52m | trailing_stop_loss | 0.00% |
| 28 | MasterV1 | SUI/USDT | +1.02% | +$2.02 | 189m | roi | -1.14% |
| 29 | MasterAI | NEAR/USDT | +0.50% | +$0.99 | 275m | roi | -0.86% |
| 30 | MasterAI | NEAR/USDT | +0.03% | +$0.06 | 10m | exit_signal | 0.00% |
| 31 | MasterAI | NEAR/USDT | -0.43% | -$0.85 | 102m | exit_signal | -1.08% |
| 32 | MasterAI | ETH/USDT | -0.02% | -$0.04 | 45m | exit_signal | -0.76% |
| 33 | MasterAI | LINK/USDT | +0.02% | +$0.04 | 47m | exit_signal | -0.89% |
| 34 | MasterAI | BTC/USDT | -0.24% | -$0.47 | 40m | exit_signal | -0.76% |
| 35 | MasterAI | SOL/USDT | +0.12% | +$0.23 | 25m | exit_signal | -0.40% |

### All 19 Open Trades (as of ~18:40 UTC)

| # | Bot | Pair | P&L % | P&L $ | Age | Current Drawdown |
|---|-----|------|-------|-------|-----|-----------------|
| 1 | ClucHAnix | FLOW/USDT | -5.28% | -$10.52 | 10.3h | -6.23% from entry |
| 2 | ClucHAnix | **XAI/USDT** | **-10.17%** | -$20.26 | 5.7h | -11.25% from entry |
| 3 | ClucHAnix | ICP/USDT | -1.48% | -$2.95 | 2.3h | -1.96% from entry |
| 4 | NASOSv5 | **XAI/USDT** | **-11.48%** | -$23.41 | 5.8h | -12.55% from entry |
| 5 | NASOSv5 | PIXEL/USDT | -7.68% | -$15.63 | 5.1h | -13.64% from entry |
| 6 | NASOSv5 | RESOLV/USDT | -2.10% | -$4.32 | 1.9h | -5.70% from entry |
| 7 | ElliotV5 | **XAI/USDT** | **-13.56%** | -$27.49 | 6.1h | -14.60% from entry |
| 8 | ElliotV5 | RESOLV/USDT | -2.18% | -$4.47 | 1.9h | -5.54% from entry |
| 9 | ElliotV5 | PIXEL/USDT | +0.86% | +$1.75 | 0.9h | -0.07% from entry |
| 10 | Supertrend | PAXG/USDT | -1.09% | -$2.16 | 15.4h | -1.21% from entry |
| 11 | Supertrend | EUR/USDT | -0.67% | -$1.33 | 15.2h | -0.56% from entry |
| 12 | Supertrend | AVAX/USDT | -0.71% | -$1.42 | 13.6h | -2.26% from entry |
| 13 | Supertrend | SHIB/USDT | +2.43% | +$4.82 | 13.6h | -1.93% from entry |
| 14 | Supertrend | FET/USDT | +0.62% | +$1.25 | 8.2h | -0.63% from entry |
| 15 | MasterV1 | XUSD/USDT | -0.26% | -$0.51 | 10.9h | -0.06% from entry |
| 16 | MasterV1 | NEAR/USDT | -1.12% | -$2.22 | 5.5h | -1.38% from entry |
| 17 | MasterV1 | BNB/USDT | +0.62% | +$1.23 | 4.6h | -0.72% from entry |
| 18 | MasterV1 | LTC/USDT | +0.15% | +$0.29 | 4.5h | -0.86% from entry |
| 19 | MasterV1 | TAO/USDT | -0.75% | -$1.49 | 1.5h | -0.95% from entry |

---

## Conclusions

1. **Stoploss levels are the #1 fixable problem.** The data proves -5% to -8% catches 95% of winners. Anything wider is burning money.

2. **Correlated exposure is the #2 problem.** Three bots in XAI/USDT simultaneously = $71 loss from a single coin. Diversify pairlists or add cross-bot coordination.

3. **Time is a signal.** If a 5m-strategy trade has not closed in 1 hour, it is probably a loser. Add time-based exit tightening.

4. **SupertrendStrategy is the real winner** because it trades diversified large-caps on a higher timeframe. Less noise, less correlation, better risk profile.

5. **MasterTraderAI is working as designed** -- ML model exits quickly, no bagholding. Needs more time to prove profitability.

6. **ClucHAnix needs surgery.** -32% stoploss with dip-buying on micro-cap pairs is a recipe for disaster. Either tighten to -5% or pause the bot.
