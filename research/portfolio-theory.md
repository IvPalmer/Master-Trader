# Portfolio Theory for Multi-Bot Crypto Trading

> Quantitative frameworks with formulas and numbers for the Master Trader system.
> Research date: 2026-03-11 (updated with web research)

---

## 1. Kelly Criterion for Crypto Position Sizing

### 1.1 The Formula

The Kelly Criterion determines the optimal fraction of capital to risk on each trade to maximize long-term geometric growth:

```
f* = (p * b - q) / b
```

Where:
- `f*` = optimal fraction of capital to risk
- `p` = probability of winning (win rate)
- `q` = probability of losing (1 - p)
- `b` = ratio of average win to average loss (payoff ratio)

**Alternative form** (more intuitive):
```
f* = W - (1 - W) / R
```
Where W = win rate, R = win/loss ratio (avg gain / avg loss).

### 1.2 Worked Examples for Our Bots

**NASOSv5 (top earner):**
- Win rate: 85% (p = 0.85), Avg win: 2.5%, Avg loss: 3.0%
- b = 2.5/3.0 = 0.833

```
f* = (0.85 * 0.833 - 0.15) / 0.833
f* = (0.708 - 0.15) / 0.833
f* = 0.67 (67% of capital per trade!)
```

**ClucHAnix (dip-buyer):**
- Win rate: 70% (p = 0.70), Avg win: 1.8%, Avg loss: 5.0%
- b = 1.8/5.0 = 0.36

```
f* = (0.70 * 0.36 - 0.30) / 0.36
f* = (0.252 - 0.30) / 0.36
f* = -0.133 (NEGATIVE -- strategy has negative edge at current stoploss!)
```

**SupertrendStrategy (trend-follower):**
- Win rate: 55% (p = 0.55), Avg win: 4.0%, Avg loss: 2.5%
- b = 4.0/2.5 = 1.6

```
f* = (0.55 * 1.6 - 0.45) / 1.6
f* = (0.88 - 0.45) / 1.6
f* = 0.269 (26.9%)
```

**Key insight:** A strategy with high win rate but poor payoff ratio (ClucHAnix with -32% stoploss) can produce a NEGATIVE Kelly, meaning it destroys capital over time. This is mathematical proof the stoploss needs tightening.

### 1.3 Fractional Kelly -- Why Full Kelly Is Suicide in Crypto

Full Kelly maximizes long-term geometric growth but produces **extreme volatility**. A full-Kelly bettor experiences a 50% drawdown roughly once every few years even with a strong edge (Gehm, 1983). In crypto, with fat-tailed distributions and sudden crashes, full Kelly is catastrophic.

**Fractional Kelly reduces volatility disproportionately to growth sacrifice:**

| Fraction | Volatility Reduction | Growth Sacrifice | Recommendation |
|----------|---------------------|-----------------|----------------|
| Full Kelly (1.0x) | Baseline | Baseline | NEVER for crypto |
| Half Kelly (0.5x) | ~50% less vol | ~25% less growth | Aggressive |
| Quarter Kelly (0.25x) | ~75% less vol | ~44% less growth | **Recommended for crypto** |
| Tenth Kelly (0.1x) | ~90% less vol | ~65% less growth | Ultra-conservative startup |

Half Kelly preserves approximately 75% of full Kelly's growth rate while cutting volatility in half. This is the classic recommendation in quant finance (Thorp, 2006). For crypto specifically, quarter Kelly is safer because:

1. **Win rate estimates are unreliable** -- crypto regime changes invalidate historical stats
2. **Fat tails** -- crypto returns are not normally distributed; 10-sigma events happen monthly
3. **Correlation spikes** -- multiple bots hit simultaneously during crashes
4. **Small sample sizes** -- most bots have < 200 trades of live data

**Practical rule:** Calculate full Kelly, use 1/4 of that. Never risk less than 1% (not worth the trade) or more than 5% (ruin territory). Require 50-100 historical trades minimum before trusting the Kelly calculation (CoinMarketCap Academy).

### 1.4 Quarter Kelly for Our System

| Strategy | Full Kelly | Quarter Kelly | Practical Cap |
|----------|-----------|---------------|---------------|
| NASOSv5 | 67% | 16.7% | **5%** (cap applied) |
| SupertrendStrategy | 26.9% | 6.7% | **5%** (cap applied) |
| MasterTraderAI | ~30% | ~7.5% | **5%** (cap applied) |
| ElliotV5 | ~20% | ~5% | 5% |
| ClucHAnix | NEGATIVE | 0% | **Fix stoploss first** |

Even quarter Kelly often exceeds our 5% max-per-trade cap. This is fine -- the cap is a safety override. A strategy whose quarter Kelly falls below 1% should be questioned.

---

## 2. Maximum Drawdown Theory

### 2.1 The Asymmetry Problem

**Formula:** `Required Gain = 1/(1 - Drawdown%) - 1`

| Drawdown | Required Gain to Recover | Time at 2% Monthly | Time at 5% Monthly |
|----------|--------------------------|--------------------|--------------------|
| 5% | 5.3% | 2.6 months | 1.1 months |
| 10% | 11.1% | 5.3 months | 2.1 months |
| 15% | 17.6% | 8.2 months | 3.3 months |
| 20% | 25.0% | 11.3 months | 4.5 months |
| 30% | 42.9% | 18.0 months | 7.2 months |
| 40% | 66.7% | 25.8 months | 10.3 months |
| 50% | 100.0% | 35.0 months | 14.0 months |

**Triple Penance Rule** (Bailey & Lopez de Prado, 2014): Recovery time typically exceeds the drawdown duration by a factor of 2-3x. If it took 2 weeks to draw down 15%, expect 4-6 weeks to recover.

### 2.2 Historical Crypto Drawdowns -- Setting Realistic Expectations

Bitcoin's worst drawdowns by cycle show a pattern of diminishing severity as the market matures:

| Year | Event | BTC Max Drawdown | Altcoin Drawdowns |
|------|-------|-----------------|-------------------|
| 2011 | Mt. Gox hack | -93% | N/A (no alts) |
| 2014-15 | Mt. Gox collapse | -86% | -90% to -99% |
| 2018 | ICO bubble burst | -84% | -90% to -99% |
| 2020 | COVID crash (March) | -62% (to $3,850) | -70% to -90% |
| 2022 | LUNA/FTX collapse | -77% (to ~$15,500) | -80% to -99% |

**Critical observation:** Altcoins consistently draw down 10-20% MORE than Bitcoin during crashes. Small-cap altcoins (the kind our dip-buyers target) can lose 90-99% and never recover. This is why position limits per coin are non-negotiable.

**COVID flash crash specifics:** Bitcoin dropped nearly 40% on March 12, 2020 alone ("Black Thursday"), hitting $3,850 before doubling in six weeks. This single-day move would wipe out any bot without a stoploss.

### 2.3 Calmar Ratio

**Formula:** `Calmar = CAGR (3yr) / Max Drawdown (3yr)`

The Calmar ratio directly measures whether returns justify the drawdowns experienced.

| Calmar Ratio | Assessment | Benchmark |
|--------------|-----------|-----------|
| < 0.5 | Poor | Unacceptable for systematic trading |
| 0.5 - 1.0 | Acceptable | Retail trader minimum; typical balanced 60/40 crypto portfolio |
| 1.0 - 2.0 | Good | **Our target** |
| 2.0 - 5.0 | Excellent | Top quantitative funds |
| > 5.0 | Exceptional | Likely overfitted or very short track record |

For crypto specifically, a Calmar ratio from 0 to 1.0 indicates profit does not exceed maximum drawdown. Above 3.0 means profit significantly exceeds drawdown -- an indicator of sound risk management (FasterCapital). **Target: Calmar >= 1.5 for each bot individually and for the portfolio.**

### 2.4 Ulcer Index

The Ulcer Index measures downside risk accounting for both **depth and duration** of drawdowns:

```
UI = sqrt(mean(D_i^2))
```

Where D_i = percentage drawdown from the most recent high on day i.

Unlike standard deviation, the Ulcer Index only penalizes downside movements and weights prolonged drawdowns more heavily. A strategy that drops 10% and stays there for 30 days has a higher Ulcer Index than one that drops 10% and recovers in 3 days. **Lower is better.**

Use the **UPI (Ulcer Performance Index)** = Excess Return / Ulcer Index as a risk-adjusted metric. It is superior to the Sharpe ratio for our use case because it ignores upside volatility (which is desirable in crypto).

### 2.5 Circuit Breaker Thresholds

Based on prop firm standards (FTMO: 5% daily / 10% total), hedge fund practices, and the historical crypto drawdown data above:

| Level | Trigger | Action | Duration |
|-------|---------|--------|----------|
| **Yellow** | -3% daily portfolio P&L | Reduce position sizes by 50% | Until next day |
| **Orange** | -5% daily portfolio P&L | Stop all new entries | 24 hours |
| **Red** | -10% weekly portfolio P&L | Pause all bots | 72 hours + manual review |
| **Black** | -15% total portfolio drawdown | Stop all bots | Indefinite, full strategy review |

**Per-bot circuit breakers:**

| Trigger | Action |
|---------|--------|
| -5% bot drawdown in 24h | Pause bot for 24h |
| -8% bot drawdown in 7 days | Pause bot for 72h |
| 3+ consecutive stop losses | Pause bot, review market regime |

**Why -15% as the hard stop?** At -15%, recovery requires +17.6% (roughly 3-4 months at typical crypto strategy returns). Beyond -20%, recovery becomes impractical for systematic strategies. The -15% threshold balances false alarms against permanent capital impairment.

### 2.6 Recovery Factor

**Formula:** `Recovery Factor = Total Net Profit / Max Drawdown`

| Recovery Factor | Assessment |
|----------------|-----------|
| < 1.0 | Strategy not worth trading |
| 1.0 - 2.0 | Marginal |
| 2.0 - 5.0 | **Good (our minimum target)** |
| 5.0 - 10.0 | Excellent |
| > 10.0 | Exceptional or likely overfitted |

---

## 3. Correlation Risk in Multi-Strategy Portfolios

### 3.1 The Core Problem

Our system runs 7 bots that share the same Binance account and largely trade the same altcoin universe. When BTC dumps, altcoins dump harder, and ALL our dip-buying bots enter simultaneously on the same coins. This is not diversification -- it is correlated concentration.

**Real-world data on crypto correlations:**
- 77% of top cryptocurrencies correlate above 0.60 with Bitcoin
- Major altcoins (ETH, XRP, EOS) correlate 0.87-0.92 with BTC during bull markets
- During crashes, correlations **increase asymmetrically** -- a BTC drop has a greater impact on altcoins than a BTC rise
- Small-cap altcoins that appear uncorrelated in calm markets spike to 0.80-0.95 correlation during selloffs

**Correlation convergence in crisis:** Strategy correlations that appear low (0.2-0.4) during normal markets frequently surge to 0.7-0.9 during crisis periods. This transforms seemingly diversified portfolios into highly concentrated risk exposures. Breaking Alpha's research shows crisis-period correlations are often **50-100% higher** than normal-period correlations.

### 3.2 Measuring Correlation Between Our Bots

**What to correlate:** Daily P&L returns (not equity curves) for each bot over a rolling window.

**Pearson correlation coefficient:**
```
r(A,B) = Cov(R_A, R_B) / (sigma_A * sigma_B)
```

**Spearman rank correlation** (more robust for crypto's fat tails):
- Rank each strategy's daily returns, then compute Pearson on the ranks

**Practical implementation:**
1. Export daily P&L from each bot via Freqtrade API (`/api/v1/profit`)
2. Compute rolling 30-day and 90-day correlation matrices (7x7)
3. Use EWMA with decay factor lambda = 0.94-0.97 for daily returns

**Action thresholds** (from Breaking Alpha):
- Pairwise correlation > 0.70: Warrants scrutiny and potential position reduction
- Average portfolio correlation > 0.50: Requires immediate attention and deleveraging
- Effective number of strategies < 50% of nominal count: Portfolio is dangerously concentrated

### 3.3 Our Portfolio's Correlation Structure

| Strategy Group | Type | Expected Intra-Group Correlation | Expected Correlation with BTC |
|----------------|------|--------------------------------|------------------------------|
| ClucHAnix, NASOSv5, ElliotV5 | Dip-buyers (5m) | 0.5 - 0.8 (HIGH) | 0.4 - 0.7 |
| NFI X6 | Mixed signals (5m) | 0.3 - 0.6 with dip-buyers | 0.4 - 0.7 |
| SupertrendStrategy | Trend-following (1h) | 0.0 - 0.3 with dip-buyers | 0.3 - 0.5 |
| MasterTraderV1 | EMA+RSI (1h) | 0.2 - 0.4 with dip-buyers | 0.3 - 0.5 |
| MasterTraderAI | ML-adaptive (5m) | 0.2 - 0.5 with dip-buyers | 0.3 - 0.6 |

**Effective independent bets: likely ~3-4** despite running 7 bots. The 3 dip-buyers act as approximately 1.5 independent strategies during normal markets and ~1 strategy during crashes.

### 3.4 Position Limits Per Asset -- The Theory

The maximum allocation to any single asset should be bounded by:

1. **Naive bound:** 1/N where N = number of assets in the universe. With 20-60 pairs, this is 1.7-5% per coin.
2. **Risk contribution bound:** No single asset should contribute more than 2x its proportional risk share (i.e., max 2/N of total portfolio risk).
3. **Liquidity bound:** Position should not exceed 1% of the coin's 24h trading volume (to ensure exit capability).
4. **Correlation-adjusted bound:** If two assets have correlation > 0.7, their combined allocation should not exceed the single-asset limit.

**For our system:** With 7 bots each potentially buying the same coin, the portfolio-level cap per coin should be **10% of total capital** (absolute maximum). This means if 3 bots want to buy XAI, the third bot must be blocked.

---

## 4. Risk of Ruin Calculations

### 4.1 The Formula (Balsara)

**Classic formula (equal win/loss sizes):**
```
Risk of Ruin = ((1 - Edge) / (1 + Edge))^N
```

Where:
- `Edge = (Win% * Avg_Win) - (Loss% * Avg_Loss)` (as fraction of risk per unit)
- `N = Capital Units` (account size / risk per trade)

**For unequal win/loss sizes (more realistic):**
There is no exact closed-form solution (Balsara, 1992). Use Monte Carlo simulation or the approximation:
```
RoR = ((1 - Edge) / (1 + Edge))^U
```
Where U = account size / risk per trade (number of "units" you can lose before ruin).

### 4.2 Risk of Ruin Reference Tables

**Risk of hitting 30% drawdown across 2,000 trades** (from BacktestBase):

| Strategy Profile | 0.5% Risk/Trade | 1% Risk/Trade | 2% Risk/Trade | 5% Risk/Trade |
|---|---|---|---|---|
| 40% WR, 2:1 R/R | 0.0% | 0.1% | 4.1% | 32.6% |
| 50% WR, 1:1 R/R | 12.5% | 48.5% | 80.4% | 97.3% |
| 50% WR, 2:1 R/R | 0.0% | 0.0% | 0.0% | 4.0% |
| 55% WR, 1:1 R/R | 0.0% | 0.1% | 3.6% | 33.0% |
| 60% WR, 1:1 R/R | 0.0% | 0.0% | 0.1% | 7.3% |

**Critical insight: Doubling position size doesn't double risk of ruin -- it increases it EXPONENTIALLY.** A trader with 55% win rate and 1.5:1 payoff has ~7% ruin probability at 2% risk but ~30% at 4% risk. This is why the 2% per-trade rule exists.

### 4.3 Risk of Ruin for Our System

**NASOSv5 (independent):**
- Win rate: 85%, Payoff ratio: 0.833, Risk per trade: 2%
- Expectancy: (0.85 * 2.5%) - (0.15 * 3.0%) = +1.675% per trade
- N = 50% / 2% = 25 units to ruin
- RoR for 50% drawdown: < 0.1% (negligible)

**But independence is a fantasy.** Here's what happens with correlation:

### 4.4 How Correlation Multiplies Risk of Ruin

**Effective portfolio risk with correlation:**
```
sigma_portfolio = sqrt(N * sigma_i^2 + N*(N-1) * rho * sigma_i^2)
```

For N=3 correlated dip-buyers (rho=0.7), each with sigma=10%:
```
sigma_portfolio = sqrt(3*100 + 3*2*0.7*100) = sqrt(300 + 420) = sqrt(720) = 26.8%
```

vs N=3 uncorrelated bots (rho=0):
```
sigma_portfolio = sqrt(300 + 0) = 17.3%
```

**Correlation increases portfolio risk by 55% in this example.** For the extreme case of our observed problem (3 bots on XAI, 2 on PIXEL = 30% of capital on 2 coins), the effective risk is:

```
If XAI drops 20%: 3 bots * ~$140 each = $420 loss = 6% of total portfolio from ONE coin
If PIXEL drops 20% simultaneously: 2 bots * ~$140 = $280 = 4% loss
Combined: 10% portfolio loss from 2 coins in a single move
```

This is how a -20% altcoin day (routine in crypto) creates a -10% portfolio drawdown. With proper position limits (10% max per coin), the same event would cause only -2% portfolio loss.

### 4.5 Professional Standards

- **Retail traders:** Target risk of ruin below 5%
- **Institutional funds:** Typically require below 1%
- **Balsara's threshold:** Position sizing above 3-5% per trade creates significant ruin probability even with positive expectancy
- **Our target:** Risk of ruin (defined as 50% drawdown) < 0.1%, verified by Monte Carlo simulation

### 4.6 Monte Carlo Simulation Framework

**How to run Monte Carlo for our multi-bot portfolio:**

1. **Collect:** Daily P&L for all 7 bots (minimum 90 days, ideally 1 year)
2. **Sample:** Randomly resample daily portfolio returns WITH correlation structure preserved (block bootstrap, block size = 5-10 days)
3. **Simulate:** Run 10,000+ paths of 1-year forward performance
4. **Measure:**
   - P(drawdown > 15%) = target < 5%
   - P(drawdown > 25%) = target < 1%
   - P(positive return at 12 months) = target > 90%
   - Expected max drawdown (95th percentile)

**Key parameters to stress-test:**
- Win rate: degrade by 5-10% from backtest (overfitting buffer)
- Correlations: increase by +0.2 from measured (crisis convergence)
- Avg win/loss: degrade by 10-20% from backtest
- Slippage and fees: add 0.1% per trade if not already included

---

## 5. Diversification Benefit

### 5.1 Markowitz Framework Applied to Crypto

Research shows mixed results for Markowitz mean-variance optimization in crypto:

- **DeMiguel et al. (2009):** The naive 1/N (equal-weight) portfolio outperforms most optimized portfolios out-of-sample when N < 25 assets and estimation windows are short. **This applies to us** -- with 7 bots and limited data, equal-weight is hard to beat.

- **Brauneis & Mestel (2019):** In crypto specifically, the naively diversified 1/N portfolio outperforms all analyzed portfolio strategies in terms of Sharpe ratio and certainty equivalent returns.

- **Jeleskovic (2024):** GARCH-Copula models within Markowitz framework improve results by modeling time-varying volatility and non-linear dependencies in crypto returns.

### 5.2 Optimal Number of Uncorrelated Strategies

Research findings on diminishing diversification returns:

- **Greatest volatility reduction:** Achieved within the first **5 assets/strategies** added to the portfolio. Beyond that, marginal benefit drops sharply.
- **Truly uncorrelated strategies:** Benefits continue growing past 25 strategies (but achieving true uncorrelation in crypto is nearly impossible).
- **Partially correlated (realistic for crypto):** Diminishing returns at **5-7 strategies**, plateau by **10 strategies**.
- **Highly correlated:** Benefits stop at **3-5 strategies**.

**Our assessment:** With 7 bots but only ~3-4 effective independent bets, we are near the practical limit of diversification within crypto-only strategies. The marginal benefit of adding an 8th or 9th correlated dip-buyer is near zero. Better to diversify across:
- **Strategy archetype:** Dip-buying + trend-following + ML + market-neutral
- **Timeframe:** 5m + 1h + 4h (different mean-reversion cycles)
- **Asset class:** Add BTC-only strategies (lower correlation with altcoins during crashes)

### 5.3 Black-Litterman as an Alternative

Black-Litterman optimization yields better results than pure Markowitz for crypto because it:
- Starts from equilibrium weights (less sensitive to estimation error)
- Allows incorporating views (e.g., "I believe trend-following will outperform in the next month")
- Produces fewer extreme allocations
- Bears less risk with higher diversity among asset classes

For a multi-bot system, Black-Litterman could be used to dynamically adjust capital allocation based on market regime detection (risk-off = more weight to trend-following, risk-on = more weight to dip-buying).

---

## 6. Portfolio-Level Position Limits

### 6.1 Evidence-Based Maximum Allocations

**Institutional research on optimal crypto allocation in broader portfolios:**

| Source | Recommended Max Crypto Allocation | Context |
|--------|----------------------------------|---------|
| VanEck (2025) | Up to 6% | In a 60/40 portfolio |
| Grayscale Research | ~5% | Risk-adjusted return optimization |
| CoinShares | 4-7.5% | Bitcoin-specific in multi-asset |
| Morgan Stanley | 2-4% | Conservative to aggressive |

**Within a crypto-only portfolio (our case), per-asset limits:**

The research consensus is that no single position should dominate. Applying the institutional principle to our crypto-only portfolio:

| Limit Type | Maximum | Rationale |
|-----------|---------|-----------|
| Single coin, single bot | 100% of bot's capital (current default) | Freqtrade handles this |
| Single coin, all bots combined | **10% of total portfolio** | Prevents XAI-type concentration |
| Single sector/narrative | **20% of total portfolio** | Prevents "all AI coins" concentration |
| Correlated group (correlation > 0.7) | **15% of total portfolio** | Treats highly correlated coins as one |
| Any single bot's total exposure | **25% of total portfolio** | Even the best performer gets capped |

### 6.2 Why 10% Max Per Coin?

With $7,000 total portfolio (7 bots x $1,000):
- 10% = $700 maximum in any single coin across all bots
- If a coin drops 30% (routine for altcoins): loss = $210 = 3% of portfolio (survivable)
- If a coin drops 50% (severe but not rare): loss = $350 = 5% of portfolio (painful but recoverable)
- Without the limit: 3 bots x $140 average trade = $420 in one coin. A 50% drop = $210 = 3%. But if all 3 bots also DCA'd, exposure could reach $1,200+ (17%) and a 50% drop = $600 = 8.6% (dangerous)

### 6.3 Implementation in Freqtrade

Freqtrade does not natively support cross-bot position limits. Options:

1. **Diversified pairlists:** Give each bot a different (non-overlapping) pairlist. Simplest but reduces each bot's opportunity set.
2. **Shared position tracker:** External service that tracks all bots' positions and blocks new entries via webhook/API when a coin exceeds the portfolio limit. This is the Phase 4 plan in `risk-implementation-plan.md`.
3. **Correlation-aware pairlist filter:** Custom `IPairlistFilter` that removes pairs already held by other bots. Requires inter-bot communication.

---

## 7. Dynamic Position Sizing

### 7.1 Anti-Martingale (Recommended)

Anti-martingale means **increasing position size after wins and decreasing after losses.** This aligns with positive expectancy systems:

| Aspect | Martingale (Double Down) | Anti-Martingale (Pyramid Up) |
|--------|-------------------------|------------------------------|
| After a loss | Double position size | Halve position size |
| After a win | Reset to base | Increase position size |
| Risk profile | Catastrophic (requires infinite capital) | Sustainable (preserves capital) |
| Math proof | Negative EV with finite capital | Positive EV with edge |
| Use in crypto | **NEVER** -- black swan wipes you out | **Recommended** |

**Statistical evidence supports Anti-Martingale's long-term superiority.** The approach assumes gains from winning trades outweigh losses, making it effective in trending markets. It naturally compounds returns during winning streaks while preserving capital during drawdowns.

### 7.2 Fixed Percentage (Simplest Anti-Martingale)

Using a fixed percentage of current account balance is inherently anti-martingale:
- Account grows from $1,000 to $1,100: 2% risk = $22 (larger than initial $20)
- Account shrinks from $1,000 to $900: 2% risk = $18 (smaller than initial $20)

This is what Freqtrade does with `stake_amount = "unlimited"` and `max_open_trades` -- it splits the current balance equally.

### 7.3 Volatility-Adjusted Position Sizing (ATR-Based)

**Formula:**
```
Position Size = (Account * Risk%) / (N * ATR)
```

Where:
- N = ATR multiplier for stoploss distance (typically 2-3)
- ATR = Average True Range over 14 periods

**Advantage:** Automatically reduces position size in volatile markets (when risk is highest) and increases it in calm markets. This is superior to fixed-percentage sizing for crypto because it adapts to regime changes.

### 7.4 Drawdown-Scaled Sizing

Reduce position size proportionally to drawdown depth:

```
Adjusted Size = Base Size * (1 - DD / Max_DD_Threshold)
```

Example with 15% max drawdown threshold:
- At 0% DD: trade at 100% of base size
- At 5% DD: trade at 67% of base size
- At 10% DD: trade at 33% of base size
- At 15% DD: trade at 0% (circuit breaker triggers)

**Breaking Alpha recommends** drawdown-triggered deleveraging as a primary risk management approach, recognizing that drawdown periods coincide with adverse correlation regime transitions.

### 7.5 For Freqtrade DCA Specifically

- Use **fixed DCA** (same size each safety order) or **mild scaling** (1.2-1.5x multiplier, NOT 2x)
- Max 3 safety orders per trade (diminishing returns after that)
- Total position after all DCA fills should not exceed 2% portfolio risk
- DCA with 2x or 3x multipliers is **martingale in disguise** -- avoid

---

## 8. Practical Recommendations for Our 7-Bot Setup

### 8.1 Max Exposure Per Coin Across All Bots

**Recommended: 10% of total portfolio ($700 of $7,000)**

Rationale:
- A 30% crash in one coin (common in altcoins) = 3% portfolio loss (survivable)
- A 50% crash = 5% portfolio loss (painful but recoverable)
- Prevents the XAI/PIXEL problem (currently 30% in 2 coins)

**Implementation:** Shared position tracker service that queries all 7 bots' open positions every 60 seconds. When a coin's total exposure across all bots exceeds 10%, block new entries on that coin via the Freqtrade API's `/api/v1/locks` endpoint.

### 8.2 Max Total Open Positions

**Recommended: 15-20 positions across all 7 bots**

Rationale:
- With $7,000 total capital, each position averaging $140: 20 positions = $2,800 deployed (40% of capital)
- Keeps 60% in reserve for DCA opportunities and new entries
- With 7 bots, this averages ~2-3 open trades per bot
- Current Freqtrade configs may allow up to 5-8 per bot = 35-56 total (way too many)

**Per-bot limits:**

| Bot | Current max_open_trades | Recommended | Rationale |
|-----|------------------------|-------------|-----------|
| ClucHAnix | 8 | 3 | Dip-buyer, needs room for DCA |
| NASOSv5 | 8 | 3 | Top earner, but correlated with other dip-buyers |
| ElliotV5 | 8 | 3 | Same archetype, limit overlap |
| SupertrendStrategy | 5 | 3 | Trend-follower, fewer but larger positions |
| MasterTraderV1 | 5 | 2 | Hourly, fewer opportunities |
| MasterTraderAI | 5 | 3 | ML can be more selective |
| NFI X6 | 8 | 4 | Largest pairlist, most selective entry |

### 8.3 Portfolio Drawdown Circuit Breaker Threshold

**Recommended: 15% total portfolio drawdown = hard stop**

Based on:
- Recovery math: -15% requires +17.6% to recover (3-4 months at best)
- Historical crypto: drawdowns of 60-80% destroy retail accounts
- Prop firm standard: 10% total is the industry norm; 15% gives crypto more room
- Our expectancy: at 2% monthly returns, a 15% drawdown takes ~8 months to recover

**Graduated response:**

```
Daily P&L < -3%:   Halve all position sizes for 24h
Daily P&L < -5%:   No new entries for 24h
Weekly P&L < -10%: Pause all bots for 72h
Total DD > -15%:   Full stop. Review everything.
```

### 8.4 Position Sizing Formula

**Recommended: Fixed 2% risk per trade, adjusted by volatility**

```
Position_Size = (Bot_Balance * 0.02) / (Stoploss_Distance%)
```

Example:
- Bot balance: $1,000
- Stoploss distance: 5%
- Position size: ($1,000 * 0.02) / 0.05 = $400

With a 10% stoploss (like ClucHAnix pre-fix):
- Position size: ($1,000 * 0.02) / 0.10 = $200

**Portfolio-level constraint layered on top:**
```
IF total_exposure(coin) > 10% of portfolio_total: BLOCK
IF total_open_positions > 20: BLOCK new entries (except DCA)
IF portfolio_DD > threshold: apply graduated response above
```

### 8.5 Summary Table

| Parameter | Value | Source |
|-----------|-------|--------|
| **Position Sizing** | | |
| Method | Quarter Kelly or Fixed 2% | Kelly Criterion / Balsara |
| Max risk per trade | 2% of total portfolio | Industry standard, RoR tables |
| Max risk per bot | 5% of total portfolio | Conservative multi-bot |
| Max exposure per coin (all bots) | 10% of total portfolio | Correlation risk mitigation |
| Max total open positions | 15-20 across all bots | Capital preservation |
| **Drawdown Limits** | | |
| Max daily portfolio DD | -3% (warning) / -5% (stop entries) | Prop firm standards |
| Max weekly portfolio DD | -10% (pause all) | Scaled from daily |
| Max total portfolio DD | -15% (hard stop all bots) | Recovery math + practical |
| Max per-bot DD | -5% (pause bot 24h) | Per-strategy isolation |
| **Performance Targets** | | |
| Target Calmar ratio | >= 1.5 | Institutional crypto standard |
| Target Recovery Factor | >= 3.0 | Conservative target |
| Target Risk of Ruin (50% DD) | < 0.1% | Balsara framework |
| **Correlation Management** | | |
| Max pairwise bot correlation alert | 0.70 | Breaking Alpha research |
| Max average portfolio correlation | 0.50 | Portfolio concentration warning |
| DCA multiplier | 1.0-1.5x (NOT 2x) | Anti-Martingale evidence |

---

## 9. Modern Portfolio Theory (MPT) for Multi-Strategy Allocation

### 9.1 Equal Weight (Naive 1/N)

- Allocate equally: $1,000 per bot (current setup)
- Surprisingly robust -- DeMiguel et al. (2009) showed 1/N outperforms most optimized portfolios out-of-sample for N < 25 assets
- Brauneis & Mestel (2019) confirmed this holds specifically for crypto portfolios
- **Best for: when you have < 2 years of backtest data per strategy (our situation)**

### 9.2 Risk Parity (Recommended Once We Have Data)

**Goal:** Each strategy contributes equally to total portfolio risk.

**Simplified inverse-volatility approach:**
```
w_i = (1 / sigma_i) / sum(1 / sigma_j) for all j
```

Where `sigma_i` = annualized volatility of strategy i's returns.

**Example allocation:**

| Strategy | Monthly Vol | 1/Vol | Weight |
|----------|------------|-------|--------|
| NASOSv5 (top earner) | 8% | 12.5 | 18% |
| ClucHAnix | 10% | 10.0 | 14% |
| ElliotV5 | 12% | 8.3 | 12% |
| SupertrendStrategy | 15% | 6.7 | 10% |
| MasterTraderV1 | 14% | 7.1 | 10% |
| MasterTraderAI | 11% | 9.1 | 13% |
| NFI X6 | 13% | 7.7 | 11% |

*(Volatilities are illustrative -- compute from actual dry-run data after 90+ days)*

**Full Equal Risk Contribution (ERC):** Accounts for correlations, not just individual volatility. Requires iterative optimization. Use this once we have a correlation matrix from real trading data.

### 9.3 Regime-Conditional Allocation

Maintain separate portfolio specifications for different market regimes:

| Regime | Detection | Allocation Shift |
|--------|-----------|-----------------|
| **Bull/trending** | BTC above 50-day MA, ADX > 25 | More weight to trend-following (Supertrend, MasterTraderV1) |
| **Range-bound** | BTC between support/resistance, ADX < 20 | More weight to dip-buyers (NASOSv5, ClucHAnix) |
| **Crash/high-vol** | BTC below 200-day MA, VIX-crypto spike | Reduce all positions by 50%, ML-only |
| **Recovery** | BTC crossing above 50-day MA from below | Gradually re-enable all bots |

---

## 10. Freqtrade Protection Settings (Evidence-Based)

### 10.1 Recommended Complete Config (5m bots)

```json
"protections": [
    {
        "method": "CooldownPeriod",
        "stop_duration_candles": 5
    },
    {
        "method": "StoplossGuard",
        "lookback_period_candles": 24,
        "trade_limit": 3,
        "stop_duration_candles": 12,
        "only_per_pair": false
    },
    {
        "method": "LowProfitPairs",
        "lookback_period_candles": 72,
        "trade_limit": 2,
        "stop_duration_candles": 120,
        "required_profit": -0.02
    },
    {
        "method": "MaxDrawdown",
        "lookback_period_candles": 576,
        "max_allowed_drawdown": 0.10,
        "stop_duration_candles": 288,
        "trade_limit": 1
    }
]
```

### 10.2 Settings Rationale

**CooldownPeriod (5 candles = 25 min on 5m):**
Mean-reversion cycle for BTC on 5m: ~15-30 minutes (3-6 candles). Prevents whipsaw re-entry.

**StoplossGuard (3 stops in 24 candles):**
With 85% win rate, 3 consecutive losses has 0.3% probability (0.15^3). If it happens, it's a regime change, not bad luck. Global stop (not per-pair) is safer.

**LowProfitPairs (-2% threshold in 72 candles):**
If 2+ trades on a pair lost > 2% combined in 6 hours (5m), the pair is in a regime where the strategy doesn't work. Lock it for 10 hours.

**MaxDrawdown (10% in 576 candles = 48 hours):**
Acts as the bot-level circuit breaker. If a single bot draws down 10% in 48 hours, pause for 24 hours.

### 10.3 Per-Bot Adjustments

| Bot Type | CooldownPeriod | StoplossGuard (trade_limit/lookback) | MaxDrawdown |
|----------|---------------|-------------------------------------|-------------|
| Dip-buyers (5m) | 5 candles | 3 / 24 candles | 10% / 576 candles |
| Trend-following (1h) | 2 candles | 2 / 48 candles | 10% / 48 candles |
| ML-Adaptive (5m) | 5 candles | 4 / 48 candles | 10% / 576 candles |
| NFI X6 (5m) | 5 candles | 3 / 36 candles | 10% / 576 candles |

---

## Sources

### Academic & Institutional
- [Cryptocurrency-portfolios in a mean-variance framework - Brauneis & Mestel (2019)](https://www.sciencedirect.com/science/article/abs/pii/S1544612318300990)
- [GARCH-Copula Crypto Portfolio Optimization - Jeleskovic (2024)](https://onlinelibrary.wiley.com/doi/10.1002/jcaf.22721)
- [Simple and Effective Portfolio Construction with Crypto Assets (2024)](https://arxiv.org/html/2412.02654v1)
- [Quantifying Crypto Portfolio Risk: Simulation-Based Framework (2025)](https://arxiv.org/html/2507.08915v1)
- [Network-based strategy of price correlations for optimal crypto portfolios](https://www.sciencedirect.com/science/article/abs/pii/S1544612323008759)
- [Analysis of Maximum Drawdown Risk Measure - Magdon-Ismail](https://www.cs.rpi.edu/~magdon/ps/journal/drawdown_RISK04.pdf)
- [Calmar Ratio - Wikipedia](https://en.wikipedia.org/wiki/Calmar_ratio)
- [Kelly Criterion - Wikipedia](https://en.wikipedia.org/wiki/Kelly_criterion)
- [Risk of Ruin - Wikipedia](https://en.wikipedia.org/wiki/Risk_of_ruin)

### Quantitative Trading Resources
- [Correlation Risk Management Across Multiple Algorithms - Breaking Alpha](https://breakingalpha.io/insights/correlation-risk-management-multiple-algorithms)
- [Kelly Criterion for Crypto - CoinMarketCap Academy](https://coinmarketcap.com/academy/article/what-is-the-kelly-bet-size-criterion-and-how-to-use-it-in-crypto-trading)
- [Kelly Criterion for Crypto Traders - Medium (2026)](https://medium.com/@tmapendembe_28659/kelly-criterion-for-crypto-traders-a-modern-approach-to-volatile-markets-a0cda654caa9)
- [Applying Kelly Criterion to Trading - QuantStrategy.io](https://quantstrategy.io/blog/applying-the-kelly-criterion-to-trading-maximizing-growth/)
- [Risk of Ruin Calculator and Formula - BacktestBase](https://www.backtestbase.com/education/risk-of-ruin-calculator-trading)
- [Risk of Ruin in Trading - Quantified Strategies](https://www.quantifiedstrategies.com/risk-of-ruin-in-trading/)
- [Risk of Ruin Calculator - KJ Trading Systems](https://kjtradingsystems.com/risk-of-ruin.html)
- [Dynamic Position Sizing - Altrady](https://www.altrady.com/blog/crypto-paper-trading/risk-management-seven-tips)
- [ATR-Based Position Sizing - QuantStrategy.io](https://quantstrategy.io/blog/using-atr-to-adjust-position-size-volatility-based-risk/)

### Crypto Market Data & Analysis
- [Risk Analysis of Crypto Assets - Two Sigma](https://www.twosigma.com/articles/risk-analysis-of-crypto-assets/)
- [Sharpe, Sortino & Calmar for Crypto - XBTO](https://www.xbto.com/resources/sharpe-sortino-and-calmar-a-practical-guide-to-risk-adjusted-return-metrics-for-crypto-investors)
- [Bitcoin Volatility Trends - iShares/BlackRock](https://www.ishares.com/us/insights/bitcoin-volatility-trends)
- [Crypto Correlation for Risk Management - CoinTelegraph](https://cointelegraph.com/news/how-to-use-crypto-correlation-for-better-risk-management)
- [Altcoin Correlation with Bitcoin - CryptoQuant](https://cryptoquant.com/insights/quicktake/66cf4eb08e55b539742a3e2e-Analysis-of-Altcoins-Correlation-with-Bitcoin)
- [3 Biggest Bitcoin Crashes - Bankrate](https://www.bankrate.com/investing/biggest-bitcoin-crashes-in-history/)

### Portfolio Allocation
- [Optimal Crypto Allocation for Portfolios - VanEck](https://www.vaneck.com/us/en/blogs/digital-assets/matthew-sigel-optimal-crypto-allocation-for-portfolios/)
- [Crypto Portfolio Allocation 2026 - XBTO](https://www.xbto.com/resources/crypto-portfolio-allocation-2026-institutional-strategy-guide)
- [Role of Crypto in a Portfolio - Grayscale](https://research.grayscale.com/reports/the-role-of-crypto-in-a-portfolio)
- [Modern Portfolio Theory and Crypto - CoinBureau](https://coinbureau.com/education/modern-portfolio-theory-crypto/)
- [Markowitz Portfolio Theory for Crypto - Sperax](https://sperax.io/blog/markowitz-portfolio-theory-crypto-yield-strategies)

### Freqtrade Documentation
- [Freqtrade Protections Plugin Documentation](https://www.freqtrade.io/en/stable/plugins/)
- [Freqtrade Strategy Callbacks](https://www.freqtrade.io/en/stable/strategy-callbacks/)
- [Freqtrade Edge Positioning](https://www.freqtrade.io/en/2020.3/edge/)
- [Freqtrade Configuration](https://www.freqtrade.io/en/stable/configuration/)

### Trading Strategy Resources
- [Martingale and Anti-Martingale Strategies - FXOpen](https://fxopen.com/blog/en/martingale-and-anti-martingale-strategies-in-trading/)
- [Anti-Martingale Transform Trading - TradersMasterMind](https://www.tradersmastermind.com/could-anti-martingale-transform-your-trading/)
- [Kelly Criterion Calculator - TradesViz](https://www.tradesviz.com/glossary/kelly-criterion/)
