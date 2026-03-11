# Backtest Results - Strategy Comparison

**Date:** 2026-03-11
**Freqtrade Version:** 2026.2
**Exchange:** Binance (spot)
**Period:** 2025-12-11 to 2026-03-11 (90 days)
**Starting Balance:** 1,000 USDT
**Max Open Trades:** 5
**Stake Amount:** unlimited (divided equally among open trades)
**Market Conditions:** Bearish (-24% to -33% across pairs)

## Pairs Tested

BTC/USDT, ETH/USDT, SOL/USDT, XRP/USDT, DOGE/USDT, BNB/USDT, ADA/USDT, AVAX/USDT, LINK/USDT, NEAR/USDT

---

## Results Summary

| Strategy | TF | Trades | Total Profit | Profit % | Win Rate | Max Drawdown | Sharpe | Sortino | SQN | Profit Factor |
|----------|-----|--------|-------------|----------|----------|--------------|--------|---------|-----|---------------|
| **ClucHAnix** | 5m | 96 | +69.62 USDT | **+6.96%** | 57.3% | 2.82% | 4.62 | 3.21 | 2.18 | 2.16 |
| **CombinedBinHAndCluc** | 5m | 31 | +30.67 USDT | **+3.07%** | 83.9% | 2.83% | 1.11 | 72.88 | 0.93 | 1.60 |
| **NASOSv5** | 5m | 1 | +3.33 USDT | **+0.33%** | 100% | 0.00% | N/A | N/A | N/A | N/A |
| ElliotV5 | 5m | 4 | -7.94 USDT | -0.79% | 25.0% | 1.05% | -0.51 | -0.70 | -1.02 | 0.25 |
| DoubleEMACrossoverWithTrend | 1h | 80 | -85.20 USDT | -8.52% | 22.5% | 13.67% | -3.51 | -10.33 | -1.83 | 0.57 |
| SupertrendStrategy | 1h | 135 | -122.89 USDT | -12.29% | 43.0% | 16.95% | -3.69 | -6.19 | -1.34 | 0.75 |

---

## Detailed Analysis

### 1. ClucHAnix (WINNER - Best Overall)

- **Profit:** +69.62 USDT (+6.96%)
- **CAGR:** 31.79%
- **Trades:** 96 (avg ~1/day)
- **Win Rate:** 57.3% (55 wins, 31 draws, 10 losses)
- **Max Drawdown:** 2.82% (28.74 USDT)
- **Best Trade:** LINK/USDT +2.54%
- **Worst Trade:** SOL/USDT -6.91%
- **Exit Breakdown:** 19 trailing stops (avg +2.27%), 67 ROI exits (avg +0.32%), 10 exit signals (avg -2.98%)
- **Risk-Adjusted:** Excellent Sharpe (4.62) and Sortino (3.21). SQN of 2.18 indicates a good system.
- **Note:** Originally designed for 1m timeframe but adapted to 5m. Uses Heikin-Ashi smoothing + Bollinger Bands with custom interpolated stoploss. Strong performance even in a -30% market.

### 2. CombinedBinHAndCluc (Runner-Up - Best Win Rate)

- **Profit:** +30.67 USDT (+3.07%)
- **CAGR:** 13.03%
- **Trades:** 31 (avg 0.34/day - very selective)
- **Win Rate:** 83.9% (26 wins, 0 draws, 5 losses)
- **Max Drawdown:** 2.83% (28.32 USDT)
- **Best Trade:** ETH/USDT +5.00%
- **Worst Trade:** ETH/USDT -5.19%
- **Exit Breakdown:** 5 ROI exits (avg +5.00%), 21 exit signals (avg +0.81%), 5 stop losses (avg -5.19%)
- **Risk-Adjusted:** Extremely high Sortino (72.88) due to very few losing days. Low drawdown.
- **Note:** Simple, clean strategy. Combines BinHV45 (BB delta squeeze) with ClucMay72018 (deep dip buying). Tight -5% stoploss with 5% ROI target provides good risk/reward.

### 3. NASOSv5 (Insufficient Data)

- **Profit:** +3.33 USDT (+0.33%)
- **Trades:** 1 (NEAR/USDT only)
- **Win Rate:** 100% (but only 1 trade)
- **Note:** Extremely selective in this market period. The lookback protection and tight EWO filters meant almost no entries qualified. Would need a longer backtest period or hyperopt tuning for current conditions to generate meaningful signals. Not enough data to evaluate properly.

### 4. ElliotV5 (Marginal Loss)

- **Profit:** -7.94 USDT (-0.79%)
- **Trades:** 4
- **Win Rate:** 25.0% (1 win, 3 losses)
- **Note:** Similar to NASOSv5, very few trades generated. The EWO momentum filters were too restrictive for this bearish period. May perform better in trending/bullish markets.

### 5. DoubleEMACrossoverWithTrend (Loss - Poor in Bear Market)

- **Profit:** -85.20 USDT (-8.52%)
- **Trades:** 80
- **Win Rate:** 22.5% (18 wins, 62 losses)
- **Max Drawdown:** 13.67%
- **Note:** The EMA crossover strategy suffered significantly in this bearish market. The EMA 200 trend filter is supposed to prevent buying in downtrends, but brief bounces generated false signals. 31 consecutive losses at one point. Not suitable for current market conditions.

### 6. SupertrendStrategy (Worst - Trend Following in Bear Market)

- **Profit:** -122.89 USDT (-12.29%)
- **Trades:** 135
- **Win Rate:** 43.0% (58 wins, 22 draws, 55 losses)
- **Max Drawdown:** 16.95%
- **Note:** 888 rejected entry signals shows the strategy was trying to enter frequently but being blocked. Trend-following strategies inherently struggle in choppy/bear markets. The triple-Supertrend confirmation wasn't enough to avoid whipsaws.

---

## Key Insights

1. **Bear market context matters:** The test period saw -24% to -33% market declines. Strategies that performed well are those designed for dip-buying with tight risk management (ClucHAnix, CombinedBinHAndCluc), not trend-following (Supertrend, DoubleEMA).

2. **Dip-buying strategies won:** Both profitable strategies (ClucHAnix and CombinedBinHAndCluc) use Bollinger Band-based dip detection with quick exits. They profit from mean-reversion rather than trend continuation.

3. **Tight stoploss = better in bear markets:** CombinedBinHAndCluc's -5% stoploss kept losses controlled. SupertrendStrategy's -26.5% stoploss allowed losses to compound.

4. **5m timeframe outperformed 1h:** All profitable strategies used 5m timeframe. The 1h strategies (Supertrend, DoubleEMA) had too much lag to react to quick reversals.

5. **Selectivity matters:** NASOSv5 and ElliotV5 generated very few signals but avoided major losses. Their filters successfully identified that conditions weren't favorable.

---

## Recommendations

### For Paper Trading (dry-run):
1. **ClucHAnix** - Best overall performance, good trade frequency, low drawdown
2. **CombinedBinHAndCluc** - Highest win rate, simplest code, easiest to understand/modify

### Next Steps:
- Run hyperopt on ClucHAnix and CombinedBinHAndCluc to optimize for current conditions
- Consider combining elements of both strategies
- Test with longer timerange (6-12 months) to see performance across market cycles
- Paper trade the top 2 strategies for 2-4 weeks before committing real capital

### Do NOT use in current market:
- SupertrendStrategy (trend-following, bad in bear market)
- DoubleEMACrossoverWithTrend (same issue)

---

## Strategy Files

All strategies installed at: `~/ft_userdata/user_data/strategies/`

| File | Strategy | Status |
|------|----------|--------|
| NASOSv5.py | NASOSv5 | Updated to v3 API |
| CombinedBinHAndCluc.py | CombinedBinHAndCluc | Already v3 API |
| ClucHAnix.py | ClucHAnix | Updated to v3 API, changed to 5m TF |
| SupertrendStrategy.py | SupertrendStrategy | Already v3 API |
| DoubleEMACrossoverWithTrend.py | DoubleEMACrossoverWithTrend | Updated to v3 API |
| ElliotV5.py | ElliotV5 | Updated to v3 API |

## Backtest Config

A backtest-specific config was created at `~/ft_userdata/user_data/config-backtest.json` using StaticPairList (the live config's VolumePairList doesn't support backtesting).
