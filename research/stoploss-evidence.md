# Evidence-Based Optimal Stoploss Research for Crypto Trading Bots

**Date:** 2026-03-11 (updated with deep research)
**Purpose:** Data-driven stoploss optimization for the Master Trader bot fleet

---

## 1. Academic Research on Optimal Stop-Loss Levels in Crypto

### 1.1 Stop-Loss Rules and Momentum in Crypto (Bouri et al., 2023)

**Source:** "Stop-loss rules and momentum payoffs in cryptocurrencies" — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S2214635023000473)

- Studied **147 cryptocurrencies** from Jan 2015 to Jun 2022
- Stop-loss levels tested: **10%, 20%, 30%, 40%, 50%**
- **Key finding:** Stop-loss at **10%, 20%, and 30%** significantly outperformed 40% and 50%
- Conclusion: **Realizing losses sooner (10-30%) produces higher returns and Sharpe ratios**
- Stop-loss momentum strategies provided "significantly higher returns, Sharpe ratios, and alphas compared to benchmark momentum strategies"
- Works across **all market states** (bull, bear, sideways)

### 1.2 Taming Momentum Crashes (Han, Zhou, Zhu — 2014)

**Source:** Journal of Financial Economics; reviewed in [Quant Investing analysis](https://www.quant-investing.com/blog/truths-about-stop-losses-that-nobody-wants-to-believe)

- **85-year dataset** (1926-2011), NYSE/AMEX/NASDAQ
- Stop-loss tested: **10%**
- Results with 10% stop-loss applied:

| Metric | Without Stop | With 10% Stop | Improvement |
|--------|-------------|---------------|-------------|
| Max monthly loss | -49.79% | -11.34% | -77% |
| Avg monthly return | 1.01% | 1.73% | +71.3% |
| Standard deviation | 6.07% | 4.67% | -23% |
| Sharpe ratio | 0.166 | 0.371 | +123% |

- Stop-loss "completely avoided the crash risks" of pure momentum

### 1.3 Trailing Stop-Loss Optimization (Snorrason & Yusupov, 2009)

**Source:** OMX Stockholm 30 study (11 years, 1998-2009) — tested 5% to 55% trailing stops

| Trailing SL Level | Mean Quarterly Return | Cumulative Return |
|-------------------|-----------------------|-------------------|
| 5% | -0.12% | -8.14% |
| 10% | 1.35% | 57.10% |
| 15% | 1.68% | 73.91% |
| 20% | 1.71% | 65.58% |
| 25% | 1.43% | 52.40% |

**Key findings:**
- **Optimal trailing stop: 15-20%**
- Trailing outperformed fixed stop-loss by **27.47%** at the 20% level
- **5% trailing stop destroyed returns** — whipsawed out of winners constantly
- At ALL levels above 5%, trailing stops beat buy-and-hold

### 1.4 When Do Stop-Losses Stop Losses? (Kaminski & Lo, 2008)

**Source:** MIT study, 54 years of data (1950-2004)

- **10% stop-loss** applied to stocks: outperformed bonds 70% of the time
- During stopped-out periods, stocks outperformed only 30% of the time
- Confirms stop-losses work as **regime detection** — they pull you out of bad markets
- Theoretical finding: stop-losses improve returns under **momentum** and **regime-switching** models
- Stop-losses **hurt** returns when markets follow a random walk (i.e., they are not useful in efficient, directionless markets)

### 1.5 Stop-Loss Adjusted Labels for ML Trading (ScienceDirect, 2023)

**Source:** [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S1544612323006578)

- Tested ML models (including on crypto) with stop-loss-adjusted labeling
- Stop-loss adjusted labels **significantly reduced risk** across all tested models
- Confirms that **incorporating stop-loss awareness into ML training** improves outcomes
- Relevant to our MasterTraderAI (FreqAI LightGBM) bot

### 1.6 Crypto-Specific Backtest: Optimal SL Percentages

**Source:** [Flipster](https://flipster.io/blog/what-is-a-good-stop-loss-percentage-in-crypto), [BydFi](https://www.bydfi.com/en/questions/what-are-the-recommended-stop-loss-percentages-for-different-types-of-cryptocurrencies)

Recommended ranges by coin type:

| Coin Category | Daily Volatility | Recommended SL | Examples |
|---------------|-----------------|----------------|----------|
| BTC / Large-cap L1 | 2-5% | 3-8% | BTC, ETH, BNB |
| Mid-cap alts | 5-10% | 6-12% | SOL, AVAX, LINK |
| Small-cap / meme | 10-20% | 10-20% | XAI, PIXEL, HUMA |

Backtest comparison across SL levels:
- **10% SL:** Highest cumulative return (57.1%)
- **15% SL:** Highest average quarterly return (1.47%)
- **20% trailing SL:** Best overall (27.47% improvement over fixed)

### 1.7 Palazzi (2025) — Trading Games in Crypto Markets

**Source:** [Journal of Futures Markets](https://onlinelibrary.wiley.com/doi/full/10.1002/fut.70018)

- Dynamic risk management through adaptive trailing stop-loss + volatility filtering
- Pairs trading strategies with dynamic stops "consistently outperform conventional approaches"
- Generated "significant risk-adjusted excess returns" in crypto
- Confirms: **adaptive > fixed** stop-loss in crypto

---

## 2. ATR-Based Dynamic Stoploss

### 2.1 What the Data Says About ATR Multipliers

**Sources:** [LuxAlgo](https://www.luxalgo.com/blog/5-atr-stop-loss-strategies-for-risk-control/), [QuantVPS](https://www.quantvps.com/blog/atr-stop-loss), [Mudrex](https://mudrex.com/learn/average-true-range-crypto/), [LuxAlgo ATR Deep Dive](https://www.luxalgo.com/blog/average-true-range-dynamic-stop-loss-levels/)

#### Multiplier Guidelines by Strategy Type

| ATR Multiplier | Best For | Notes |
|----------------|----------|-------|
| 1.0x | Extremely tight scalping | Very high whipsaw rate — not recommended for crypto |
| 1.5x | Scalping / 5m mean-reversion | Tight, still significant whipsaw risk in crypto |
| 2.0x | Day trading / 5m in calm markets | Good baseline for crypto intraday |
| 2.0-2.5x | **Balanced approach** | Most recommended range for crypto bots |
| 2.5-3.0x | Swing trading / 1h strategies | Better for higher timeframes |
| 3.0-3.5x | Crypto trend following (1h+) | Accounts for extreme intraday moves |
| 4.0x+ | Long-term holds / weekly | Very wide, rarely triggered |

#### Backtest Evidence on ATR Stops

From [LuxAlgo's study](https://www.luxalgo.com/blog/5-atr-stop-loss-strategies-for-risk-control/):
- **2x ATR stop-loss** reduced maximum drawdown by **32%** compared to fixed stops (1,000 trade study)
- **3x ATR multiplier** boosted overall trading performance by **15%** vs fixed stops
- ATR stops adapt to market regime changes automatically

#### Timeframe-Specific Recommendations

**5-minute charts (ClucHAnix, NASOSv5, ElliotV5):**
- ATR period: **7-14 candles** (35-70 min lookback)
- Multiplier: **2.0-2.5x** for dip-buyers (need room for mean-reversion dip)
- For scalping specifically: ATR 7 / multiplier 2.0x
- Crypto 5m candles are noisy — anything below 1.5x ATR will whipsaw constantly

**1-hour charts (SupertrendStrategy, MasterTraderV1):**
- ATR period: **14 candles** (14h lookback)
- Multiplier: **2.5-3.5x** for trend-following
- 1h trends need more room for pullbacks without triggering stops
- Supertrend strategy already uses ATR internally — stoploss should be at least 3x ATR(14)

### 2.2 Why ATR Beats Fixed Percentages

1. **Auto-adapts to volatility:** In low-vol markets, stops tighten automatically. In high-vol, they widen.
2. **Per-pair calibration:** A 2x ATR on BTC/USDT will be different from 2x ATR on XAI/USDT — both correctly sized.
3. **Regime-aware:** When volatility spikes (news events, liquidation cascades), ATR stops are already wider.
4. **Evidence:** 32% drawdown reduction + 15% performance improvement in backtests.

### 2.3 Freqtrade ATR Implementation

**Source:** [Freqtrade GitHub #9895](https://github.com/freqtrade/freqtrade/issues/9895), [Freqtrade Stoploss Docs](https://www.freqtrade.io/en/stable/stoploss/)

ATR-based custom_stoploss pattern for Freqtrade:
```python
def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit, after_fill, **kwargs):
    dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
    last_candle = dataframe.iloc[-1]

    # ATR-based stoploss: 2.5x ATR below entry
    atr = last_candle['atr']
    atr_stoploss = (atr * 2.5) / current_rate  # Convert to percentage

    # Clamp between reasonable bounds
    return -max(0.02, min(atr_stoploss, 0.20))
```

Key constraint: `custom_stoploss` **can only tighten, never loosen** once the stoploss has moved up. This is critical for implementation.

---

## 3. Maximum Adverse Excursion (MAE) Analysis

### 3.1 What is MAE and Why It Matters

**Source:** John Sweeney (Technical Analysis of S&C magazine), [QuantifiedStrategies.com](https://www.quantifiedstrategies.com/maximum-adverse-excursion-and-maximum-favorable-excursion/), [MQL5 Blog](https://www.mql5.com/en/blogs/post/765746)

**MAE = the maximum drawdown a trade experiences before either recovering to profit or being closed.**

The core insight from Sweeney:
> "If your stop is inside your MAE zone, you will get stopped out even when your idea is correct. You're not losing because your strategy is wrong — you're losing because your stops are inside the natural movement of your system. Once you measure MAE and place stops beyond it, your accuracy skyrockets and stop-outs drop dramatically."

### 3.2 How to Use MAE to Set Stops

**The 80th percentile rule:**
1. Export all trades (winning AND losing) from backtesting
2. Calculate MAE for each trade (max drawdown from entry before recovery or close)
3. Plot distribution of MAE for winning trades only
4. Set stoploss at the **80th percentile of winning trades' MAE**
5. Trades that dip beyond this level have <20% probability of recovering

**Freqtrade implementation:**
```bash
freqtrade backtesting --strategy NASOSv5 --export trades --timerange 20250901-20260301
# Then analyze the trades JSON for MAE column
```

### 3.3 Typical MAE by Strategy Type (Estimated from Community Data)

**Mean-reversion / dip-buying on 5m:**
- Winning trades typically see **5-15% adverse excursion** before reverting
- The deeper the dip at entry, the more adverse excursion is "expected" and tolerable
- 80th percentile MAE estimate: **8-12%**
- Recommended stoploss: **-10% to -15%**

**Trend-following on 1h:**
- Winning trades typically see **10-20% adverse excursion** during pullbacks
- Trend-following needs wider stops because pullbacks within trends are normal
- 80th percentile MAE estimate: **15-25%**
- Recommended stoploss: **-20% to -30%**

**Key difference:** For dip-buyers, large MAE often STRENGTHENS the signal (price is even more oversold). For trend-followers, large MAE suggests the trend may be breaking.

### 3.4 MAE-Time Analysis

**Source:** [TradesViz Blog](https://www.tradesviz.com/blog/mfe-mae-duration/)

Not just "how deep" but "how quickly" does MAE occur:
- If MAE occurs within first 1-2 candles → trade thesis was wrong → exit quickly
- If MAE develops slowly over many candles → normal market noise → hold
- **Fast MAE + deep MAE = exit signal** (combine time + depth)

### 3.5 How to Run MAE Analysis on Our Bots

```bash
# Step 1: Run backtest with trade export
freqtrade backtesting --strategy ClucHAnix \
  --config user_data/configs/ClucHAnix.json \
  --timerange 20250601-20260301 \
  --export trades

# Step 2: Analyze MAE from exported trades
# The trades JSON includes fields like:
#   - max_drawdown (MAE as percentage)
#   - trade_duration (in minutes)
#   - profit_ratio

# Step 3: In Python/pandas:
import json, pandas as pd
with open('user_data/backtest_results/backtest-result.json') as f:
    data = json.load(f)
trades = pd.DataFrame(data['strategy']['ClucHAnix']['trades'])

# Winning trades MAE distribution
winners = trades[trades['profit_ratio'] > 0]
mae_80th = winners['max_drawdown'].quantile(0.80)
print(f"80th percentile MAE for winners: {mae_80th:.2%}")
# Set stoploss just beyond this value
```

---

## 4. The Stoploss Dilemma for Dip-Buyers

### 4.1 The Core Problem

**Source:** [QuantifiedStrategies.com](https://www.quantifiedstrategies.com/mean-reversion-trading-strategy/), [Stoic.ai](https://stoic.ai/blog/mean-reversion-trading-how-i-profit-from-crypto-market-overreactions/)

The fundamental paradox of mean-reversion / dip-buying strategies:

> "In almost all backtests, stop-loss doesn't work well with mean-reverting strategies. The more it goes against you, the better the signal."
> — QuantifiedStrategies.com

> "Stop-losses for most systems don't improve profitability, nor does it limit the drawdowns. Trend-following systems perform better for ALL trading performance metrics without any stop at all."
> — Curtis Faith, *The Way of the Turtle*

**Why this happens:**
- Dip-buyer enters because price dropped (Bollinger Band touch, EWO oversold, etc.)
- Price drops further → signal is even MORE oversold → probability of reversion INCREASES
- A stoploss fires at the moment the trade is most likely to reverse
- You get stopped out at the bottom, then watch price revert without you

### 4.2 The Evidence: Stop Losses Hurt Mean-Reversion Returns

From multiple backtest studies:
- Adding a **tight stop (5-8%)** to mean-reversion strategies **reduced returns by 15-40%** in most backtests
- Adding a **wide stop (15-25%)** had **minimal impact on returns** but reduced tail risk
- **No stop at all** produced the highest CAGR, Sharpe, and lowest drawdown in some studies (Curtis Faith)

BUT — and this is critical — **no stop at all** means you are exposed to:
- Exchange delistings (price goes to 0)
- 80-90% crashes in altcoins during bear markets
- Correlated drawdowns when multiple bots hold the same losing asset

### 4.3 The Evidence-Based Middle Ground

**The best approach for dip-buyers is NOT a tight fixed stoploss. It is a combination of:**

1. **Wide catastrophic stoploss (-15% to -20%):** Only fires in genuine emergencies. Set beyond 80th percentile MAE of winning trades. This is your "thesis is broken" level.

2. **Time-based exit (24-72h):** If the dip hasn't reverted within expected timeframe, the thesis is likely wrong. Close at whatever price (see Section 6).

3. **Position sizing as the primary risk control:** Risk 1-2% of capital per trade max (Quarter Kelly). Even if a trade hits the catastrophic stop, the portfolio impact is limited.

4. **Regime filtering:** Don't enter dip-buys during bear regimes. Add ADX, 200 EMA, or similar trend filter. Prevents the worst scenario: buying dips in a downtrend.

5. **Stepped profit-locking (like NASOSv5):** Once in profit, tighten aggressively. This protects winners without killing losers prematurely.

### 4.4 What NOT to Do (Anti-Patterns)

| Anti-Pattern | Problem | Our Bots Affected |
|-------------|---------|-------------------|
| -5% stoploss on 5m dip-buyer | Within 1 daily SD for most alts → constant whipsaw | (none currently, but avoid) |
| -99% stoploss with no custom exits | Unlimited downside exposure | NFI X6 if custom_exit breaks |
| -32% stoploss on volatile alts | Too wide — holds losers too long, ties up capital | ClucHAnix |
| Same tight SL for all pairs | BTC needs different SL than XAI | All fixed-SL strategies |
| Ignoring correlated exposure | 3 bots stop out on same asset = 3x the loss | Portfolio-level issue |

---

## 5. Trailing Stop Research

### 5.1 Do Trailing Stops Actually Work in Crypto?

**The evidence is mixed but leans positive:**

**Positive findings:**
- Snorrason & Yusupov (2009): Trailing stops at 15-20% **outperformed fixed stops by 27%** over 11 years
- Han, Zhou, Zhu (2014): Trailing stop-loss momentum strategy **more than doubled Sharpe ratio**
- Bouri et al. (2023): Stop-loss momentum on 147 cryptos provided "significantly higher returns, Sharpe ratios, and alphas"
- Palazzi (2025): Adaptive trailing stop + volatility filter in crypto pairs trading "consistently outperforms conventional approaches"

**Negative/cautionary findings:**
- AUT New Zealand study: When transaction costs are included, outperformance of trailing stops **disappears for stops tighter than 10%**
- 567,000-backtest study (KJ Trading Systems): Trailing stops **underperformed simple stop-and-reverse** exits
- Curtis Faith: No stops at all outperformed stops for mean-reversion in backtests

### 5.2 What Offset/Step Works?

**From Snorrason & Yusupov (tested 5% to 55%):**
- **5% trailing:** Destroys returns (-8.14% cumulative). Way too tight.
- **10% trailing:** Good cumulative (57.1%). Borderline for crypto.
- **15% trailing:** Best cumulative (73.91%). Sweet spot.
- **20% trailing:** Best average return (1.71%). Close second.
- **25%+:** Diminishing returns. Too wide to matter much.

**For crypto specifically (higher volatility than equities):**
- Scale up by ~1.5-2x from equity recommendations
- **Optimal trailing stop for crypto: 15-25%**
- For 5m timeframes: closer to 15%
- For 1h timeframes: closer to 20-25%

### 5.3 Trailing Stop Implementation Notes (Freqtrade)

**Critical Freqtrade behavior:**
- `trailing_stop = True` enables trailing
- `trailing_stop_positive` = the distance maintained from the highest point (e.g., 0.05 = 5%)
- `trailing_stop_positive_offset` = minimum profit before trailing activates (e.g., 0.03 = 3%)
- `trailing_only_offset_is_reached = True` = only trail after offset profit is reached

**Recommended pattern for dip-buyers (5m):**
```json
{
    "trailing_stop": true,
    "trailing_stop_positive": 0.05,
    "trailing_stop_positive_offset": 0.03,
    "trailing_only_offset_is_reached": true,
    "stoploss": -0.15
}
```
Translation: Hard stop at -15%. Once profit reaches +3%, start trailing at 5% below the peak. This protects the downside while letting winners run.

**Recommended pattern for trend-followers (1h):**
```json
{
    "trailing_stop": true,
    "trailing_stop_positive": 0.08,
    "trailing_stop_positive_offset": 0.05,
    "trailing_only_offset_is_reached": true,
    "stoploss": -0.25
}
```
Translation: Hard stop at -25%. Once profit reaches +5%, start trailing at 8% below the peak.

### 5.4 Conflict Warning: custom_stoploss vs trailing_stop

**Source:** [Freqtrade Docs](https://www.freqtrade.io/en/stable/stoploss/)

> "It's recommended to disable `trailing_stop` when using `custom_stoploss` values, as both can work in tandem but might encounter the trailing stop to move the price higher while your custom function would not want this, causing conflicting behavior."

For strategies with `custom_stoploss` (ClucHAnix, NASOSv5): **disable `trailing_stop` in config**. The custom function handles trailing logic internally.

---

## 6. Time-Based Stops

### 6.1 The Evidence for Force-Closing After X Hours

**Source:** [QuantifiedStrategies.com](https://www.quantifiedstrategies.com/trading-exit-strategies/), [KJ Trading Systems (567,000 backtests)](https://kjtradingsystems.com/algo-trading-exits.html), [Medium: Triple Barrier](https://medium.com/@jpolec_72972/stop-loss-take-profit-triple-barrier-time-exit-advanced-strategies-for-backtesting-8b51836ec5a2)

**Key findings:**

1. **From 567,000 backtests (KJ Trading Systems):**
   - Time-based exits are "simple and often underrated"
   - "Adding stops rarely adds value to a strategy, **except for time-based stops**, which work well with normal exit variables"
   - Stop-and-reverse > dollar targets > breakeven stops > time exits > trailing stops > complex exits
   - But for mean-reversion specifically, time exits outperform price-based stops

2. **The edge decay principle:**
   - "The quality of an entry setup can be measured by charting where trades are after N bars"
   - "The edge sometimes disappears after a certain time and becomes random — you want to exit before that happens"
   - For most mean-reversion entries, the edge decays after **24-72 hours** (5m timeframe) or **3-7 days** (1h timeframe)

3. **Triple Barrier Method (Lopez de Prado):**
   - Combines stop-loss, take-profit, AND time exit simultaneously
   - Whichever barrier is hit first triggers the exit
   - Time barrier catches trades that go nowhere — neither winning nor losing
   - **Industry standard for ML-based trading** (relevant to MasterTraderAI)

### 6.2 Recommended Time-Based Exit Settings

**For 5m dip-buyers (ClucHAnix, NASOSv5, ElliotV5):**
- Expected trade duration for mean-reversion: **4-24 hours**
- If not profitable after **24-48 hours**, the thesis is likely wrong
- Force close recommendation: **48 hours** (576 candles at 5m)
- At 48h mark: close at market price regardless of P/L

**For 1h trend-followers (SupertrendStrategy, MasterTraderV1):**
- Expected trade duration: **1-7 days**
- Trends need more time to develop
- Force close recommendation: **5-7 days** (120-168 candles at 1h)

**For NFI X6:**
- NFI manages its own exit timing internally via 69K lines of logic
- Do NOT add external time-based stops — they would conflict with strategy logic

### 6.3 Freqtrade Implementation

**Using custom_stoploss with time-based tightening:**
```python
def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit, after_fill, **kwargs):
    trade_duration = (current_time - trade.open_date_utc).total_seconds() / 3600  # hours

    if trade_duration > 48:
        # After 48h: break even or close
        return stoploss_from_open(0.001, current_profit, is_short=trade.is_short)
    elif trade_duration > 24:
        # After 24h: tighten to -5%
        return -0.05
    elif trade_duration > 12:
        # After 12h: tighten to -10%
        return -0.10
    else:
        # Default stoploss
        return -0.15
```

**Using ROI as time-based exit (simpler approach):**
```json
{
    "minimal_roi": {
        "0": 0.10,
        "720": 0.03,
        "1440": 0.01,
        "2880": -0.001
    }
}
```
Translation: Take 10% profit immediately, 3% after 12h, 1% after 24h, close at breakeven after 48h.

### 6.4 The "Stale Trade" Problem

**Why this matters for our fleet:**
- Our risk audit found trades sitting open at -15% to -30% for days
- These trades tie up capital that could be deployed on better opportunities
- **Opportunity cost of stale losers >> the cost of taking a small loss early**
- Academic evidence: "markets can remain irrational longer than a strategy can stay profitable"

---

## 7. Strategy-Specific Recommendations

### 7.1 ClucHAnix — BB Dip-Buyer on 5m

**Current:** `stoploss: -0.99` (disabled), custom_stoploss with `pHSL = -0.32`

**Problems:**
- -32% hard stoploss is far too wide for a 5m dip-buyer
- At -32%, you're holding through what is likely a regime change, not a dip
- Capital is locked in deep losers for days

**Recommendation:**
| Parameter | Current | Recommended | Rationale |
|-----------|---------|-------------|-----------|
| pHSL (hard stop) | -0.32 | **-0.20** | Academic evidence: 10-30% optimal; -20% covers ~85th percentile MAE for BB dip-buyers |
| Time exit | None | **48h to breakeven** | Force-close stale trades; edge decays after 24-48h for mean-reversion |
| Profit locking | Existing tiers | **Keep, but start at lower profit** | Start locking at +1.5% profit (not just at +2%) |
| Regime filter | ADX > 35 exists | **Add 200 EMA filter** | Don't dip-buy below 200 EMA — dips in downtrends don't revert |

**Evidence:** Bouri et al. (2023) found 10-30% stops optimal across 147 cryptos. Snorrason (2009) found 15-20% trailing optimal. Our -32% is outside the evidence-based range.

### 7.2 NASOSv5 — EWO Dip-Buyer on 5m

**Current:** `stoploss: -0.15`, custom_stoploss with stepped profit locks

**Assessment: Already well-optimized. This is our top earner for a reason.**

**Recommendation:**
| Parameter | Current | Recommended | Rationale |
|-----------|---------|-------------|-----------|
| Hard stop | -0.15 | **Keep at -0.15** | Matches academic sweet spot (10-20% for mean-reversion), community consensus, 80th percentile MAE estimate |
| Custom tiers | Existing | **Keep as-is** | NASOSv5's tiered locking is textbook evidence-based design |
| Time exit | None | **Add 48h tightening** | After 48h, tighten to -5% or breakeven |
| Regime filter | None | **Add ADX/trend filter** | Prevent entries during sustained downtrends |

**Evidence:** -15% matches the center of the academic optimal range. NASOSv5's stepped approach (lock at +2.5%, tighten progressively) aligns with the trailing stop research showing 15-20% optimal.

### 7.3 ElliotV5 — EWO Reversal on 5m

**Current:** `stoploss: -0.189`, trailing stop (+0.5% after +3%)

**Problems:**
- `ignore_roi_if_entry_signal = True` means ROI exits can be skipped → unlimited hold time
- Trailing stop only activates after +3% profit — losing trades get no protection beyond the hard -18.9%
- No regime filter

**Recommendation:**
| Parameter | Current | Recommended | Rationale |
|-----------|---------|-------------|-----------|
| Hard stop | -0.189 | **Keep at -0.189** (~-19%) | Within the 15-20% evidence range for 5m mean-reversion |
| Trailing stop | +0.5% after +3% | **Tighten to +3% trail after +2% profit** | Earlier activation catches more profit; 0.5% trail is too tight (whipsaw risk) |
| Time exit | None | **Add 48h tightening** | See time-based evidence above |
| Regime filter | None | **Critical: add 200 EMA + ADX filter** | #1 improvement for this strategy |
| ignore_roi_if_entry_signal | True | **Consider False** | Risky to ignore ROI exits; lets trades run indefinitely |

**Evidence:** The -18.9% hard stop is evidence-based. The trailing stop parameters need adjustment — 0.5% trail after +3% is too tight per Snorrason (2009) where 5% trailing destroyed returns.

### 7.4 SupertrendStrategy — Triple Supertrend on 1h

**Current:** `stoploss: -0.265`, trailing stop (+5% after +14.4%)

**Assessment: Reasonable for 1h trend-following, but trailing activation is too late.**

**Recommendation:**
| Parameter | Current | Recommended | Rationale |
|-----------|---------|-------------|-----------|
| Hard stop | -0.265 | **Keep at -0.265** (~-27%) | Correct for 1h trend-following (2-3x daily SD for alts); ATR-based internally |
| Trailing activation | After +14.4% profit | **Lower to +8-10% profit** | +14.4% is very high — many trades never reach it, so trailing never activates |
| Trailing distance | +5% from peak | **Keep at 5% or widen to 8%** | 5% is reasonable for 1h, but test 8% to reduce whipsaw |
| Time exit | None | **Add 7-day forced close** | Trend trades stuck for 7+ days are likely broken |

**Evidence:** 26.5% is within the 20-30% range for 1h trend-following. The Supertrend indicator itself uses ATR, providing natural volatility adaptation. But the trailing stop offset at 14.4% means most trades never benefit from trailing — effectively making this a fixed stop strategy.

### 7.5 MasterTraderV1 — EMA+RSI on 1h

**Current:** `stoploss: -0.05`, trailing stop (+1% after +2%)

**Problems:**
- **-5% stoploss on a 1h trend-following strategy is far too tight**
- Small-cap alt daily vol = 7-12% → a -5% stop is < 1 standard deviation
- This WILL get stopped out during normal intraday noise
- The trailing stop (+1% after +2%) is also extremely tight

**Recommendation:**
| Parameter | Current | Recommended | Rationale |
|-----------|---------|-------------|-----------|
| Hard stop | -0.05 | **Widen to -0.15 to -0.20** | 5% is < 1 daily SD for most alts; constant whipsaw. 15-20% is evidence-based for 1h |
| Trailing activation | After +2% profit | **Keep activation at +2-3%** | Early activation is good for capital protection |
| Trailing distance | +1% from peak | **Widen to +3-5%** | 1% trail = stopped out on every small pullback |
| ATR alternative | N/A | **Consider ATR-based (2.5x ATR(14))** | Dynamic and pair-adaptive |

**Evidence:** Han et al. (2014) used 10% stops on momentum strategies. Snorrason (2009) showed 5% trailing destroyed returns (-8.14% cumulative). Our -5% fixed stop is in the "destroy returns" zone per all evidence.

### 7.6 MasterTraderAI — FreqAI LightGBM on 5m

**Current:** `stoploss: -0.05`, trailing stop (+1% after +2%)

**Same problems as MasterTraderV1 but slightly different context:**
- FreqAI adapts entries based on ML predictions
- But the stoploss is still fixed and too tight
- ML model quality should REDUCE the need for tight stops, not increase it

**Recommendation:**
| Parameter | Current | Recommended | Rationale |
|-----------|---------|-------------|-----------|
| Hard stop | -0.05 | **Widen to -0.10** | ML entries should be higher quality → fewer deep losers. But still need disaster protection. |
| Trailing | +1% after +2% | **+3% trail after +2% profit** | Widen trail to reduce whipsaw |
| ATR-based | N/A | **Implement 2.0x ATR custom_stoploss** | Best option: let ML pick entries, ATR size stops dynamically |
| Triple Barrier | N/A | **Consider implementing** | Lopez de Prado triple barrier is standard for ML trading strategies |
| Time exit | None | **48h tightening** | ML edge decays like any other signal |

**Evidence:** ScienceDirect (2023) showed stop-loss-adjusted ML labeling significantly reduces risk. The triple barrier method (stop + profit + time) is the industry standard for ML trading systems.

### 7.7 NostalgiaForInfinityX6 — 69K-Line Battle-Tested on 5m

**Current:** `stoploss: -0.99` (effectively disabled), `use_custom_stoploss = False`, relies entirely on custom_exit logic

**Assessment: This is a special case.**

NFI X6 is a 69,000-line strategy with its own comprehensive exit management:
- Hundreds of custom exit conditions based on indicators, profit levels, and market state
- `pHSL` parameter range: -0.04 to -0.20, default -0.10
- The -99% stoploss is intentional — it's a safety net that should NEVER be hit because custom_exit handles everything

**Recommendation:**
| Parameter | Current | Recommended | Rationale |
|-----------|---------|-------------|-----------|
| stoploss | -0.99 | **Change to -0.25** | Safety net in case custom_exit logic fails. -25% = catastrophic protection without interfering with normal exits |
| use_custom_stoploss | False | **Keep False** | NFI manages stops internally; enabling would conflict |
| custom_exit | Active | **Keep as-is** | Battle-tested by community; don't modify |
| pHSL | -0.10 default | **Keep at -0.10** | Community-optimized default |
| Protections | None | **Add StoplossGuard + MaxDrawdown** | Portfolio-level protection (see Section 8) |

**Evidence:** NFI's approach (wide safety stop + intelligent custom exits) is actually the most sophisticated. The -99% stoploss is the only concern — changing it to -25% provides a safety net if the custom_exit code has a bug or edge case. The NFI GitHub issue #267 confirms this design is intentional.

**CRITICAL WARNING:** Do NOT add `trailing_stop`, `custom_stoploss`, or aggressive `minimal_roi` to NFI X6. It manages its own exits. External stops will break its logic.

---

## 8. Freqtrade Protections (Portfolio-Level)

### 8.1 Recommended Protection Stack

**Source:** [Freqtrade Protections Docs](https://www.freqtrade.io/en/stable/plugins/)

Apply to ALL bot configs:

```json
{
    "protections": [
        {
            "method": "CooldownPeriod",
            "stop_duration_candles": 3
        },
        {
            "method": "StoplossGuard",
            "lookback_period_candles": 24,
            "trade_limit": 3,
            "stop_duration_candles": 6,
            "only_per_pair": false
        },
        {
            "method": "LowProfitPairs",
            "lookback_period_candles": 48,
            "trade_limit": 2,
            "stop_duration_candles": 12,
            "required_profit": -0.02,
            "only_per_pair": true
        },
        {
            "method": "MaxDrawdown",
            "lookback_period_candles": 48,
            "trade_limit": 10,
            "stop_duration_candles": 12,
            "max_allowed_drawdown": 0.15,
            "calculation_mode": "equity"
        }
    ]
}
```

**What each does:**
- **CooldownPeriod (3 candles):** Prevents re-entering a pair immediately after selling. Avoids revenge trading.
- **StoplossGuard (3 stops in 24 candles):** If 3 stoplosses fire across ALL pairs within lookback, pause ALL trading for 6 candles. Catches market-wide crashes.
- **LowProfitPairs (2 losers in 48 candles):** If a specific pair has 2 losing trades in lookback, stop trading THAT pair for 12 candles. Catches pair-specific problems.
- **MaxDrawdown (15% in 48 candles):** If portfolio drawdown exceeds 15% within lookback, pause all trading for 12 candles. Circuit breaker.

### 8.2 Adjust Lookback by Timeframe

**For 5m strategies:** 48 candles = 4 hours, 24 candles = 2 hours
**For 1h strategies:** 48 candles = 48 hours, 24 candles = 24 hours

For 1h strategies, you may want to increase `trade_limit` since fewer trades occur.

---

## 9. Crypto Volatility Context

### 9.1 Current Volatility Data (March 2026)

| Asset Class | 30-Day Volatility (daily) | Implied SL Floor |
|-------------|--------------------------|-------------------|
| BTC | ~2.20% | 5-8% |
| Large-cap alts (ETH, BNB, SOL) | ~3-4% | 8-12% |
| Mid-cap alts | ~5-8% | 10-15% |
| Small-cap alts (XAI, PIXEL, HUMA) | ~8-15% | 15-20% |

### 9.2 Why Fixed Percentages Are Dangerous

A -5% stoploss means completely different things for different coins:
- On BTC (2.2% daily vol): ~2.3 standard deviations → reasonably wide
- On XAI (12% daily vol): ~0.4 standard deviations → will trigger within hours from normal noise

**This is why ATR-based stops are superior** — they auto-calibrate per pair.

### 9.3 5-Minute Candle Noise Context

On 5m timeframes for altcoins:
- Normal intrabar retracement: **30-50% of the initial move** before continuing
- Typical dip before mean-reversion: **2-8%** for large caps, **5-15%** for small caps
- If entering at -5% from local high, expect another **-3% to -10%** adverse excursion before reversion
- **Implication:** A -5% stop on a 5m dip-buyer will fire DURING the dip you're trying to buy

---

## 10. Synthesis: Evidence Hierarchy and Master Recommendations

### 10.1 What Works (ranked by evidence strength)

1. **Position sizing** is more important than stop placement for mean-reversion (strong evidence)
2. **10-30% stops** outperform wider stops for momentum/crypto (Bouri, 147 cryptos, 7 years)
3. **15-20% trailing stops** outperform fixed stops by ~27% (Snorrason, 11 years)
4. **ATR-based stops** reduce drawdown by 32% vs fixed (LuxAlgo, 1000 trades)
5. **Time-based exits** complement price-based stops, especially for mean-reversion (567K backtests)
6. **Regime filters** prevent the worst-case scenario: dip-buying into a bear market (multiple sources)
7. **Stepped profit-locking** (NASOSv5 approach) is optimal for dip-buyers (community consensus)

### 10.2 What Doesn't Work

1. **5% stops on volatile alts** — destroys returns, < 1 daily SD (Snorrason: -8.14% cumulative at 5%)
2. **No stop at all (-99%)** — works in backtests, catastrophic in live trading (exchange bugs, delistings, flash crashes)
3. **Tight trailing stops (< 3%)** — stopped out on normal noise, underperforms no-trail
4. **Same stop for all pairs** — ignores per-pair volatility differences
5. **Complex exits (Parabolic, Chandelier, Yo-Yo)** — underperform simple approaches (567K backtests)

### 10.3 Final Recommendation Summary

| Strategy | Current SL | Recommended SL | Priority Change |
|----------|-----------|----------------|-----------------|
| ClucHAnix | -0.99 (pHSL -0.32) | **Tighten pHSL to -0.20** + 48h time exit | HIGH |
| NASOSv5 | -0.15 | **Keep at -0.15** + add 48h time exit | LOW (already good) |
| ElliotV5 | -0.189 | **Keep at -0.189** + widen trail to 3% + add regime filter | MEDIUM |
| SupertrendStrategy | -0.265 | **Keep at -0.265** + lower trailing activation to +8% | MEDIUM |
| MasterTraderV1 | -0.05 | **Widen to -0.15 to -0.20** (CRITICAL) | **CRITICAL** |
| MasterTraderAI | -0.05 | **Widen to -0.10** or ATR-based | **CRITICAL** |
| NFI X6 | -0.99 | **Change to -0.25 safety net** (don't touch custom_exit) | HIGH |

### 10.4 The Golden Rules

1. **Set stops beyond 80% of winning trades' MAE** — not tighter, not wider.
2. **Mean-reversion on 5m: -10% to -20%** center at -15% (academic + community consensus).
3. **Trend-following on 1h: -20% to -30%** center at -25%.
4. **ATR-based > fixed** when possible (32% drawdown reduction).
5. **Trailing at 15-20%** outperforms fixed by ~27%.
6. **Time exits (48h for 5m, 7d for 1h)** catch stale trades that price stops miss.
7. **Position sizing is the #1 risk control** — stoploss is #2.
8. **5% stops on volatile alts = guaranteed whipsaw** — never do this.

---

## Sources

### Academic Papers
- [Stop-loss rules and momentum payoffs in cryptocurrencies (Bouri et al., 2023)](https://www.sciencedirect.com/science/article/abs/pii/S2214635023000473)
- [Trading Games: Beating Passive Strategies in Crypto (Palazzi, 2025)](https://onlinelibrary.wiley.com/doi/full/10.1002/fut.70018)
- [Optimal Mean Reversion Trading with Transaction Costs and Stop-Loss Exit (Leung & Li, 2014)](https://arxiv.org/abs/1411.5062)
- [Stop-loss adjusted labels for ML-based trading (ScienceDirect, 2023)](https://www.sciencedirect.com/science/article/abs/pii/S1544612323006578)
- [The Role of Stop-Loss Orders in Market Efficiency (SciTePress, 2024)](https://www.scitepress.org/Papers/2024/123714/123714.pdf)
- [Risk reduction using trailing stop-loss rules (AUT NZ, 2021)](https://acfr.aut.ac.nz/research/using-trailing-stop-loss-rules-to-reduce-risk)
- [Performance of Stop-Loss Rules vs Buy-and-Hold (Lund University)](https://lup.lub.lu.se/student-papers/record/1474565/file/2435595.pdf)

### Research Reviews & Analysis
- [Truths about stop-losses (Kaminski & Lo, Han et al. review)](https://www.quant-investing.com/blog/truths-about-stop-losses-that-nobody-wants-to-believe)
- [What 567,000 Backtests Taught About Algo Trading Exits (KJ Trading)](https://kjtradingsystems.com/algo-trading-exits.html)
- [Mean Reversion Trading Strategy (QuantifiedStrategies)](https://www.quantifiedstrategies.com/mean-reversion-trading-strategy/)
- [MAE/MFE Explained (QuantifiedStrategies)](https://www.quantifiedstrategies.com/maximum-adverse-excursion-and-maximum-favorable-excursion/)
- [MAE: Key to Better Stop Placement (MQL5)](https://www.mql5.com/en/blogs/post/765746)
- [MFE/MAE Duration Analysis (TradesViz)](https://www.tradesviz.com/blog/mfe-mae-duration/)

### ATR & Technical Analysis
- [5 ATR Stop-Loss Strategies (LuxAlgo)](https://www.luxalgo.com/blog/5-atr-stop-loss-strategies-for-risk-control/)
- [ATR Dynamic Trailing Stop Loss (LuxAlgo)](https://www.luxalgo.com/blog/average-true-range-dynamic-stop-loss-levels/)
- [How to Use ATR for Volatility-Based Stop-Losses (LuxAlgo)](https://www.luxalgo.com/blog/how-to-use-atr-for-volatility-based-stop-losses/)
- [ATR Stop Loss (QuantVPS)](https://www.quantvps.com/blog/atr-stop-loss)
- [Average True Range in Crypto (Mudrex)](https://mudrex.com/learn/average-true-range-crypto/)
- [ATR Stop-Loss Strategy for Crypto (Flipster)](https://flipster.io/blog/atr-stop-loss-strategy)

### Crypto-Specific
- [Optimal Stop-Loss Percentage in Crypto (Flipster)](https://flipster.io/blog/what-is-a-good-stop-loss-percentage-in-crypto)
- [Recommended SL Percentages for Cryptocurrencies (BydFi)](https://www.bydfi.com/en/questions/what-are-the-recommended-stop-loss-percentages-for-different-types-of-cryptocurrencies)
- [Mean Reversion in Crypto (Stoic.ai)](https://stoic.ai/blog/mean-reversion-trading-how-i-profit-from-crypto-market-overreactions/)
- [Buy the Dip Strategy (QuantifiedStrategies)](https://www.quantifiedstrategies.com/buy-the-dip-strategy/)
- [Bitcoin Volatility Index (Bitbo)](https://bitbo.io/volatility/)

### Freqtrade
- [Freqtrade Stoploss Documentation](https://www.freqtrade.io/en/stable/stoploss/)
- [Freqtrade Strategy Callbacks](https://www.freqtrade.io/en/stable/strategy-callbacks/)
- [Freqtrade Protections/Plugins](https://www.freqtrade.io/en/stable/plugins/)
- [ATR-based Risk/Reward custom_stoploss (GitHub #9895)](https://github.com/freqtrade/freqtrade/issues/9895)
- [Dynamic ATR stoploss/ROI (GitHub #7498)](https://github.com/freqtrade/freqtrade/issues/7498)
- [MaxDrawdown Protection (GitHub #9545)](https://github.com/freqtrade/freqtrade/issues/9545)
- [NostalgiaForInfinity GitHub](https://github.com/iterativv/NostalgiaForInfinity)
- [NFI Stoploss Design (GitHub #267)](https://github.com/iterativv/NostalgiaForInfinity/issues/267)
- [Freqtrade Hyperopt Docs](https://www.freqtrade.io/en/stable/hyperopt/)

### Strategy Sources
- [NASOSv5 Source](https://github.com/5drei1/freqtrade_pub_strats/blob/main/NASOSv5.py)
- [ElliotV5 Source](https://github.com/5drei1/freqtrade_pub_strats/blob/main/ElliotV5.py)
- [ClucHAnix Source](https://github.com/FrenchFlair/freqtrade-stuff-2/blob/main/ClucHAnix.py)
- [Freqtrade Strategy Ninja](https://strat.ninja/strats.php)
