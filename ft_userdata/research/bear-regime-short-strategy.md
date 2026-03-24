# Bear-Regime Short Strategy Research
## Deep Research for a Crash-Only Freqtrade Short Strategy

**Date**: 2026-03-23
**Purpose**: Design a Freqtrade strategy that ONLY activates during confirmed bearish regimes to profit from crypto crashes, while staying completely flat during bull/neutral markets.

---

## Table of Contents
1. [Best Indicators for Short Entries](#1-best-indicators-for-short-entries-in-crypto-bear-markets)
2. [Bear-Market-Only Strategy Patterns](#2-bear-market-only-strategy-patterns)
3. [Risk Management for Shorts](#3-risk-management-for-shorts)
4. [Freqtrade Short/Futures Implementation](#4-freqtrade-shortfutures-implementation)
5. [Regime-Switching Approaches](#5-regime-switching-approaches)
6. [Crypto-Specific Short Dynamics](#6-crypto-specific-short-dynamics)
7. [Mean Reversion vs Trend-Following for Shorts](#7-mean-reversion-vs-trend-following-for-shorts)
8. [Position Sizing for Shorts](#8-position-sizing-for-shorts)
9. [Time-Based Exits for Shorts](#9-time-based-exits-for-shorts)
10. [Backtesting Pitfalls](#10-backtesting-pitfalls-for-short-strategies)
11. [Actionable Strategy Blueprint](#11-actionable-strategy-blueprint)

---

## 1. Best Indicators for Short Entries in Crypto Bear Markets

### What Actually Works (Not Just Inverted Longs)

The critical insight from research: **short entries require different indicators than inverted long signals**. Crypto crashes have distinct characteristics — they are faster, more volatile, and driven by liquidation cascades rather than gradual selling.

### Tier 1: Primary Short Entry Indicators

**ADX + DMI (Directional Movement Index)** — STRONGEST EVIDENCE
- When -DI crosses above +DI AND ADX > 25, it signals strong bearish trend
- The wider the -DI/+DI separation, the stronger the bearish conviction
- ADX above 25 confirms the move is genuine trend, not noise
- A rising ADX during a downtrend specifically signals panic selling
- **Recommended**: Enter short when -DI > +DI AND ADX > 30 (stricter than 25 for shorts)

**MACD Histogram Divergence** — TIMING PRECISION
- Bearish divergence: price makes higher highs but MACD makes lower highs
- This signals momentum exhaustion BEFORE the crash starts
- MACD histogram crossing below zero confirms bearish momentum shift
- **Recommended**: Use for entry timing after regime is confirmed bearish

**EMA 200 Death Cross** — REGIME CONFIRMATION
- When 50-day MA falls below 200-day MA = "death cross"
- In March 2018, BTC death cross preceded drop from $9,000 to $4,000
- **Recommended**: Use as regime filter, not entry signal (too laggy for entries)

### Tier 2: Confirmation Indicators

**On-Balance Volume (OBV)** — VOLUME CONFIRMATION
- Falling OBV confirming price decline = strong bearish conviction
- OBV divergence (price flat, OBV falling) = distribution phase before crash
- **Recommended**: OBV slope negative as entry confirmation

**RSI in Bear Context** — DIFFERENT INTERPRETATION
- In bear markets, RSI oscillates between 20-60 (not 30-70 like bull markets)
- RSI hitting 50-60 in a bear market = "overbought" = short entry zone
- RSI below 20 = potential short squeeze territory, avoid new shorts
- **Recommended**: Enter shorts when RSI bounces to 50-60 during bear regime

**Bollinger Bands + VWAP** — MEAN REVERSION SHORTS
- Price rallying to upper BB during confirmed downtrend = short entry
- Price below VWAP = bearish bias confirmed
- Combined with RSI, creates multiple confirmation for high-probability shorts
- Best on 1h-4h timeframes

### Tier 3: Crypto-Specific Indicators

**Funding Rate** — SENTIMENT GAUGE
- Extremely negative funding = market overcrowded on short side (avoid)
- Positive funding during price decline = longs still hopeful (good short)
- Neutral-to-slightly-positive funding = ideal short environment
- **Recommended**: Avoid shorts when funding rate < -0.05%

**Open Interest Changes** — LIQUIDATION PREDICTOR
- Rising OI + falling price = shorts winning, more downside likely
- Falling OI + falling price = long liquidation cascade, explosive but ending
- **Recommended**: Track OI direction as position management signal

---

## 2. Bear-Market-Only Strategy Patterns

### The "Regime-Gated Short" Architecture

The key design principle: **the strategy should have ZERO exposure during non-bear regimes**. This is fundamentally different from a dual-direction strategy.

### Pattern 1: Failed Rally Short (HIGHEST WIN RATE)

```
Regime: Confirmed bear (BTC below SMA200, ADX > 25, RSI < 50)
Entry:  Price bounces 3-5% from local low, then stalls
        RSI reaches 50-60 zone (bear market "overbought")
        -DI still > +DI (bears still in control)
Signal: Enter short on the failed rally
Exit:   New local low OR RSI < 30 OR 24h time limit
```

**Why it works**: In bear markets, rallies are short-covering events, not real buying. They exhaust quickly and reverse. This pattern has the highest win rate because you're trading WITH the dominant trend.

### Pattern 2: Breakdown Continuation

```
Regime: Confirmed bear
Entry:  Price breaks below key support level
        Volume spike confirms breakdown (> 2x average)
        OBV making new lows
Signal: Enter short on the breakdown candle close
Exit:   -10% profit target OR support becomes resistance test
```

### Pattern 3: Bearish Divergence Setup

```
Regime: Confirmed bear or transitioning to bear
Entry:  Price makes equal/higher high
        RSI and MACD make lower high (bearish divergence)
        Volume declining on the rally
Signal: Enter short when price reverses from the divergent high
Exit:   Previous swing low OR divergence invalidated
```

### Pattern 4: Liquidation Cascade Rider (ADVANCED)

```
Regime: Bear market with high open interest
Entry:  Large cluster of long liquidation levels below current price
        Price approaches liquidation zone
Signal: Enter short just before liquidation cascade triggers
Exit:   Quick profit taking (2-4 hours), very tight timeframe
```

**Warning**: This is the highest risk/reward pattern. Requires exchange liquidation data.

---

## 3. Risk Management for Shorts

### How Shorts Differ From Longs

| Aspect | Long Trade | Short Trade |
|--------|-----------|-------------|
| Max loss | -100% (price goes to zero) | **Unlimited** (price can go to infinity) |
| Typical crash speed | Slow grind down | **Fast, violent squeezes up** |
| Funding cost | Usually pay (positive funding) | Usually receive (but variable) |
| Liquidation risk | Gradual | **Sudden, cascading** |
| Recovery pattern | V-shaped bounces common | Dead cat bounces common |
| Time decay | None | Funding rate costs |

### Critical Risk Rules for Crypto Shorts

1. **ALWAYS use hard stop-loss on exchange** (stoploss_on_exchange = True)
   - Crypto short squeezes can move 20-30% in minutes
   - Bot-side stoploss can miss candles entirely on 1h timeframe
   - Exchange-side stop is the ONLY reliable protection

2. **Maximum stoploss: -5% for shorts** (vs -10% acceptable for longs)
   - Short squeezes are faster and more violent than dumps
   - A -5% stop on a short with 2x leverage = -10% account impact

3. **Time-based exit is MANDATORY**
   - Crypto crashes are fast: 70% of the move happens in first 24-48 hours
   - Holding shorts longer invites short squeeze risk
   - Maximum hold: 48 hours for 1h timeframe, 7 days for 1d timeframe

4. **Never fight funding rates**
   - If funding rate turns deeply negative (< -0.05%), close short
   - This means the market is overcrowded on the short side
   - Short squeezes are most violent when funding is deeply negative

5. **Reduce leverage for shorts**
   - Our research says 25% position size for shorts (vs 100% for longs)
   - Maximum 2x leverage (vs potentially higher for longs)
   - This is because unlimited loss potential requires wider safety margins

6. **Circuit breaker specific to shorts**
   - Kill switch: 3% portfolio loss from short trades in 24h = stop all shorts
   - Don't wait for the general 10% circuit breaker
   - Separate tracking from long portfolio performance

### Short Squeeze Protection Checklist

- [ ] Monitor funding rate every 8 hours
- [ ] Check open interest direction (falling OI = closing positions)
- [ ] RSI below 20 = extreme oversold, close all shorts immediately
- [ ] Sudden volume spike with green candle = potential squeeze start
- [ ] stoploss_on_exchange = True (NON-NEGOTIABLE)

---

## 4. Freqtrade Short/Futures Implementation

### Configuration Requirements

```json
{
    "trading_mode": "futures",
    "margin_mode": "isolated",
    "exchange": {
        "name": "binance"
    }
}
```

### Strategy Class Setup

```python
class BearRegimeShort(IStrategy):
    can_short = True  # REQUIRED - without this, enter_short signals are ignored

    # Timeframe
    timeframe = '1h'

    # Tighter stoploss for shorts
    stoploss = -0.05  # -5% hard stop

    # Trailing stop (asymmetric for shorts)
    trailing_stop = True
    trailing_stop_positive = 0.02  # 2% trail
    trailing_stop_positive_offset = 0.03  # Activate at 3% profit
    trailing_only_offset_is_reached = True

    # Force exit after 24 candles (24 hours on 1h)
    # Use custom_exit or unfilledtimeout
```

### Entry Signal Implementation

```python
def populate_entry_trend(self, dataframe, metadata):
    # REGIME GATE: Only enter shorts during confirmed bear market
    # This is the key differentiator from FuturesSniperV1

    dataframe.loc[
        (
            # ── REGIME FILTER (BTC-level) ──
            (dataframe['btc_close'] < dataframe['btc_sma200']) &  # BTC below SMA200
            (dataframe['btc_adx'] > 25) &                         # Strong trend
            (dataframe['btc_rsi'] < 50) &                          # Bearish momentum

            # ── PAIR-LEVEL ENTRY SIGNALS ──
            (dataframe['adx'] > 30) &                    # Strong trend on pair
            (dataframe['minus_di'] > dataframe['plus_di']) &  # Bears dominating
            (dataframe['rsi'] > 45) & (dataframe['rsi'] < 65) &  # "Bear overbought"
            (dataframe['close'] < dataframe['sma200']) &  # Below SMA200
            (dataframe['macd'] < dataframe['macdsignal']) &  # MACD bearish

            # ── VOLUME CONFIRMATION ──
            (dataframe['volume'] > 0)
        ),
        'enter_short'
    ] = 1

    # CRITICAL: No long entries in this strategy
    # This is a SHORT-ONLY strategy

    return dataframe
```

### Exit Signal Implementation

```python
def populate_exit_trend(self, dataframe, metadata):
    # Exit short when bear regime weakens
    dataframe.loc[
        (
            (dataframe['rsi'] < 25) |  # Extremely oversold = bounce coming
            (dataframe['btc_close'] > dataframe['btc_sma200']) |  # BTC flipped bullish
            (dataframe['plus_di'] > dataframe['minus_di'])  # Bulls took over
        ),
        'exit_short'
    ] = 1

    return dataframe
```

### Known Freqtrade Short Issues (from GitHub)

1. **Issue #8700**: "Adding Short trading to working strategy kills trading"
   - Mixing long and short signals in one strategy degrades both
   - **Solution**: Our approach of SHORT-ONLY avoids this entirely

2. **Issue #6995**: "Futures strategy does not enter short on Binance futures"
   - Requires `can_short = True` in strategy class AND `trading_mode: futures` in config
   - Both must be set or signals are silently ignored

3. **Issue #8414**: "How to set up a strategy to long spot and short futures"
   - Freqtrade does not support mixed spot+futures in one instance
   - Must run separate bot instances (which is what we do)

---

## 5. Regime-Switching Approaches

### How Quant Funds Handle Long-to-Short Switching

**The Three-State Model** (most common in institutional crypto):

```
State 1: BULL   → Long-only strategies active, shorts disabled
State 2: NEUTRAL → Reduced position sizing, no new entries
State 3: BEAR   → Short-only strategies active, longs disabled
```

**Transition Rules** (based on research):

| From → To | Signal | Confirmation Period |
|-----------|--------|-------------------|
| Bull → Neutral | BTC crosses below SMA200 | 3 consecutive daily closes |
| Neutral → Bear | ADX > 25 + RSI < 40 + below SMA200 | 2 consecutive daily closes |
| Bear → Neutral | RSI > 50 OR price recovers above SMA100 | 5 consecutive daily closes |
| Neutral → Bull | BTC crosses above SMA200 + ADX > 20 | 3 consecutive daily closes |

**Key Insight**: The transition from Neutral → Bear requires MORE confirmation than Bear → Neutral. This asymmetry protects against premature short entries (which are more dangerous than premature long exits).

### Our Existing Infrastructure

We already have `classify_btc_regime()` in `market_intelligence.py` returning:
- `strong_bull`, `bull`, `neutral`, `bear`, `strong_bear`

**The bear short strategy should ONLY activate when regime is `bear` or `strong_bear`.**

### Regime Detection Enhancement Recommendations

The current regime classifier uses single-candle values. For a short strategy, we need **persistence**:

```python
def is_confirmed_bear(btc_dataframe, lookback=3):
    """
    Bear regime must persist for N candles to be confirmed.
    This prevents entering shorts on brief dips during bull markets.
    """
    recent = btc_dataframe.tail(lookback)
    bear_candles = (
        (recent['close'] < recent['sma200']) &
        (recent['adx'] > 25) &
        (recent['rsi'] < 50)
    ).sum()
    return bear_candles >= lookback  # ALL recent candles must be bearish
```

### Academic Foundation

Springer research on "Regime switching forecasting for cryptocurrencies" (2024) found that ARMA-GARCH models can identify crypto regimes, but simpler approaches using moving averages and ADX perform nearly as well with much less complexity. The key is the persistence requirement — single-candle signals generate too many false positives.

---

## 6. Crypto-Specific Short Dynamics

### Funding Rates — The Hidden Cost/Benefit of Shorts

**How Funding Works**:
- Perpetual futures use funding rates to keep futures price aligned with spot
- Positive funding: longs pay shorts (bullish sentiment) → GOOD for shorts
- Negative funding: shorts pay longs (bearish sentiment) → BAD for shorts
- Collected every 8 hours on Binance

**Funding Rate as a Trading Signal**:
| Funding Rate | Meaning | Short Action |
|-------------|---------|-------------|
| > +0.05% | Longs very crowded | Favorable to short (longs will unwind) |
| +0.01% to +0.05% | Normal bull lean | Neutral, safe to short |
| -0.01% to 0% | Slight bear lean | OK to short but watch closely |
| < -0.05% | Shorts very crowded | **DO NOT SHORT** — squeeze risk extreme |
| < -0.1% | Panic shorting | **CLOSE ALL SHORTS** — squeeze imminent |

**Revenue from Funding**: In confirmed bear markets with positive funding, shorts can earn ~$60/day per $100K position purely from funding. This is a free bonus on top of directional gains.

### Liquidation Cascades — The Crypto Short Seller's Best Friend

Liquidation cascades are unique to crypto and create the most profitable short opportunities:

1. Price drops toward a cluster of long liquidation levels
2. First liquidations trigger forced selling
3. Forced selling pushes price lower
4. Lower price triggers MORE liquidations
5. **Cascade effect**: Can drop price 10-20% in minutes

**Key Data Point**: In October 2025, $19.2 billion was liquidated in 24 hours during a cascade event.

**How to Exploit**:
- Monitor open interest levels (rising OI + falling price = cascade setup)
- Track long/short ratio on exchanges
- CoinGlass provides liquidation heatmaps

**Warning**: Cascading liquidations CAN also happen on the short side. If price suddenly reverses with thin liquidity, short squeezes follow the same cascade mechanics in reverse.

### Exchange Mechanics for Shorts

**Binance Futures Specifics**:
- Isolated margin mode: only the margin assigned to a position is at risk
- Cross margin mode: entire account balance can be liquidated (NEVER USE)
- Maintenance margin: ~0.5% for BTC, ~1% for alts
- Liquidation happens when margin falls below maintenance margin
- Insurance fund covers shortfalls (no socialized losses usually)

**Recommendation**: Always use `isolated` margin mode. This limits worst-case loss to the position's allocated margin, not the entire account.

---

## 7. Mean Reversion vs Trend-Following for Shorts

### The Evidence

| Approach | Best For | Win Rate | R:R | In Bear Markets |
|----------|---------|----------|-----|----------------|
| Trend Following | Sustained downtrends | ~40-50% | 2:1+ | **Preferred** |
| Mean Reversion | Ranging/choppy markets | ~60-80% | 0.5:1 | Riskier |

### Research Findings

**QuantPedia Study on Bitcoin**:
- At local minima, BTC tends to MEAN REVERT (bounce back)
- At local maxima during bear markets, BTC tends to TREND (continue down)
- **Implication**: Short entries should be on failed rallies (trend-following), NOT on breakdown lows (mean-reversion shorts into oversold conditions are dangerous)

**Medium Backtest (2026)**:
- Trend following: +3.0R
- Mean reversion: +1.45R
- Trend following was 2x more profitable overall

**Time Horizon Matters**:
- 2 minutes to 30 minutes: Mean reversion works best
- 1 hour to 2 years: Trend following works best
- **For our 1h timeframe: trend following is clearly superior**

### Recommendation for Our Strategy

**Use TREND-FOLLOWING for shorts on 1h timeframe.**

Specifically: "Failed Rally Short" pattern (Pattern 1 from Section 2).

Do NOT use mean-reversion shorts (buying breakdowns and shorting bounces) because:
1. Crypto bounces from lows are violent and unpredictable
2. Mean reversion shorts have poor R:R in crypto
3. Getting caught in a short squeeze from an oversold level is the #1 way to blow up

The ONE exception: On the daily timeframe (1d bots), mean reversion shorts from upper Bollinger Band during bear markets can work because the signal is more reliable at longer timeframes.

---

## 8. Position Sizing for Shorts

### Should Shorts Be Smaller Than Longs? YES.

**The Asymmetric Risk Argument**:
- Long max loss: -100% (asset goes to zero) — practically limited to stoploss
- Short max loss: **unlimited** (asset can go up 1000%)
- Short squeezes are faster and more violent than dumps
- Therefore: shorts MUST have smaller position sizes

### Recommended Position Sizing

**Conservative Approach (Recommended for us)**:

| Parameter | Long Trades | Short Trades | Ratio |
|-----------|------------|-------------|-------|
| Position size | 100% of per-trade allocation | **25-50%** of per-trade allocation | 0.25-0.50x |
| Leverage | 1x (spot) | **1x-2x** (futures) | — |
| Effective exposure | 100% | **25-100%** (with leverage) | — |
| Risk per trade | 1-2% of portfolio | **0.5-1%** of portfolio | 0.5x |
| Max concurrent | 3 positions | **2 positions** | 0.67x |

**Kelly Criterion Consideration**:
- Full Kelly sizing can produce 50%+ drawdowns even with an edge
- Professional traders use Half-Kelly or Quarter-Kelly
- For shorts (higher risk): use **Quarter-Kelly** at most
- Given our $88 USDT wallet: max ~$22 per short position with 2x leverage = $44 effective exposure

### Implementation in Freqtrade

```json
{
    "stake_amount": "22",
    "max_open_trades": 2,
    "tradable_balance_ratio": 0.5
}
```

Or use dynamic position sizing:

```python
def custom_stake_amount(self, current_time, current_rate, proposed_stake,
                       min_stake, max_stake, leverage, entry_tag, side, **kwargs):
    if side == "short":
        return proposed_stake * 0.5  # Half size for shorts
    return proposed_stake
```

---

## 9. Time-Based Exits for Shorts

### Crypto Crashes Are FAST

Historical data on crypto crash duration:

| Event | Drop % | Duration to Bottom | Recovery Start |
|-------|--------|-------------------|----------------|
| March 2020 COVID | -50% | 2 days | Day 3 |
| May 2021 China Ban | -55% | 12 days | Week 3 |
| Luna/UST May 2022 | -60% | 7 days | Week 4 |
| FTX Nov 2022 | -25% | 3 days | Day 5 |
| Oct 2025 Cascade | -18% | 1 day | Day 2 |

**Pattern**: 70%+ of the move happens in the first 24-48 hours. After that, risk of short squeeze increases dramatically.

### Recommended Time-Based Exit Rules

**For 1h Timeframe Strategy**:

```python
def custom_exit(self, pair, trade, current_time, current_rate,
               current_profit, **kwargs):
    # Time-based exits for shorts
    if trade.is_short:
        trade_duration_hours = (current_time - trade.open_date_utc).total_seconds() / 3600

        # Hard exit after 48 hours regardless of P/L
        if trade_duration_hours >= 48:
            return "time_exit_48h"

        # Take profit faster on shorts
        if trade_duration_hours >= 24 and current_profit > 0.02:
            return "time_profit_24h"  # Take 2%+ profit after 24h

        # Break-even exit after 36 hours
        if trade_duration_hours >= 36 and current_profit > 0:
            return "time_breakeven_36h"

    return None
```

**For 1d Timeframe Strategy**:
- Max hold: 7 days
- Take profit at 5%+ after 3 days
- Break-even exit after 5 days

### ROI Table for Shorts (1h Timeframe)

```python
minimal_roi = {
    "0": 0.08,    # 8% — take it immediately if available
    "12": 0.05,   # 5% after 12 hours
    "24": 0.03,   # 3% after 24 hours
    "36": 0.01,   # 1% after 36 hours — just get out with something
    "48": 0.0     # Break-even at 48 hours — hard exit
}
```

These are tighter than long ROI tables because:
1. Shorts have higher holding costs (potential funding)
2. Mean reversion risk increases with time
3. Short squeeze probability increases with duration

---

## 10. Backtesting Pitfalls for Short Strategies

### Critical Issues Specific to Short Backtests

**1. Survivorship Bias (SEVERE for crypto)**
- Backtests include coins that later got delisted or went to zero
- These coins would have been GREAT shorts, inflating backtest returns
- Example: Luna/UST would show massive short profits, but was un-shortable for retail during the crash
- **Mitigation**: Only backtest on top-20 market cap coins that existed throughout the entire test period

**2. Borrow Rate / Funding Rate Not Modeled**
- Freqtrade does NOT model historical funding rates in backtests
- During extreme bear markets, funding rates can swing wildly
- A strategy that looks profitable might lose money after funding costs
- **Mitigation**: Subtract 0.03% per 8-hour period from backtest profits as conservative estimate

**3. Liquidation Not Accurately Simulated**
- Freqtrade backtester uses candle OHLC, not tick-by-tick data
- A wick that touches your liquidation price then reverses shows as "liquidated" in real life but might show as "survived" in backtest
- **Mitigation**: Use `--timeframe-detail 5m` or lower for more accurate simulation

**4. Slippage on Shorts During Cascades**
- During liquidation cascades, order books thin out dramatically
- Market orders to close shorts during a squeeze can slip 2-5%
- Backtests assume perfect fills
- **Mitigation**: Add 0.5% slippage assumption to all short exits

**5. Short Squeeze Events Are Underrepresented**
- Most backtests cover a specific time window
- Short squeezes are tail events that happen 2-3 times per year
- A backtest might miss these events entirely
- **Mitigation**: Ensure backtest period includes at least one major squeeze event

**6. Timeframe-Detail for Shorts is Non-Negotiable**
- On 1h candles, a short can be opened at the open, hit stoploss at the high, AND close profitably at the close — all in one candle
- Without sub-candle simulation, the backtest doesn't know which happened first
- **Mitigation**: Always use `--timeframe-detail 5m` for 1h strategies

### Backtest Validation Checklist

- [ ] Test period includes at least 1 bull market (should have ZERO trades)
- [ ] Test period includes at least 2 bear market phases
- [ ] Verify zero long entries (strategy should NEVER go long)
- [ ] Check max drawdown during bull market (should be 0%)
- [ ] Manually verify 5 random trades against charts
- [ ] Run with `--timeframe-detail 5m` for realistic fills
- [ ] Subtract estimated funding costs from total profit
- [ ] Ensure no trades on delisted coins
- [ ] Walk-forward validate: optimize on period 1, test on period 2

---

## 11. Actionable Strategy Blueprint

### Strategy Name: `BearCrashShortV1`

### Core Architecture

```
┌─────────────────────────────────────────┐
│           REGIME GATE (BTC-Level)        │
│  BTC below SMA200 + ADX>25 + RSI<50    │
│  Must persist for 3+ consecutive 1h     │
│  candles before activation              │
│                                          │
│  If NOT in bear regime → NO TRADES      │
└──────────────┬──────────────────────────┘
               │ Bear regime confirmed
               ▼
┌─────────────────────────────────────────┐
│         ENTRY SIGNAL (Pair-Level)        │
│                                          │
│  Pattern: Failed Rally Short             │
│  1. Price below SMA200                   │
│  2. -DI > +DI (bears dominating)        │
│  3. ADX > 30 (strong trend)             │
│  4. RSI 50-60 (bear "overbought")       │
│  5. MACD < Signal (bearish momentum)     │
│  6. Volume confirmation                  │
│                                          │
│  Anti-Squeeze Filters:                   │
│  - Skip if RSI < 25 (oversold)          │
│  - Skip if extreme fear (F&G < 10)       │
│  - Skip if funding < -0.05%             │
└──────────────┬──────────────────────────┘
               │ Entry triggered
               ▼
┌─────────────────────────────────────────┐
│         POSITION MANAGEMENT              │
│                                          │
│  Size: 25% of normal ($22 USDT)         │
│  Leverage: 2x isolated                   │
│  Stoploss: -5% on exchange               │
│  Trailing: 2% trail at 3% offset        │
│  Max trades: 2 concurrent                │
│                                          │
│  Time exits:                             │
│  - 24h: take 2%+ profit                 │
│  - 36h: take breakeven+                  │
│  - 48h: hard exit regardless             │
│                                          │
│  Emergency exits:                        │
│  - BTC flips above SMA200               │
│  - RSI drops below 20 (squeeze risk)    │
│  - Funding rate < -0.05%                │
│  - Portfolio down 3% from shorts today   │
└─────────────────────────────────────────┘
```

### What We Already Have (Reusable)

From `market_intelligence.py`:
- `classify_btc_regime()` — returns `bear` / `strong_bear` / etc.
- `FearGreedIndex.is_extreme_fear()` — anti-squeeze filter
- `PositionTracker` — cross-bot coordination

From existing strategy infrastructure:
- BTC informative pair setup (already on all strategies)
- ADX, RSI, SMA200 calculations (already in SupertrendStrategy)
- Docker compose for futures bots (already proven with FuturesSniperV1)

### What Needs to Be Built

1. **New strategy file**: `BearCrashShortV1.py`
2. **New config**: `BearCrashShortV1.json`
3. **Enhanced regime detection**: Persistence-based (3-candle confirmation)
4. **Funding rate integration**: Via Binance API or freqtrade's built-in
5. **Short-specific kill switch**: 3% daily loss limit for shorts
6. **Time-based exit logic**: In `custom_exit()`

### Expected Performance Characteristics

Based on research:
- **Active time**: ~20-30% of the year (only during bear regimes)
- **Expected trades**: 5-15 per month during active periods
- **Win rate**: 50-60% (trend-following in confirmed bear)
- **Average win**: 3-5% per trade
- **Average loss**: 2-3% per trade (tight stoploss)
- **Profit factor target**: > 1.5x (lower bar than long strategies because shorts are harder)
- **Maximum drawdown**: < 5% (due to small position sizing)

### Key Differences From Failed FuturesSniperV1

| Aspect | FuturesSniperV1 (FAILED) | BearCrashShortV1 (PROPOSED) |
|--------|-------------------------|---------------------------|
| Direction | Mixed longs + shorts | **SHORT ONLY** |
| Regime gate | Loose BTC gate | **3-candle persistent bear confirmation** |
| Indicators | Same for both directions | **Short-specific indicators** |
| Position size | Full size both ways | **25% for shorts** |
| Time exit | None | **48h hard exit** |
| Kill switch | In-memory (lost on restart) | **File-persisted** |
| Anti-squeeze | None | **Funding rate + RSI floor + F&G** |
| Stoploss | -7% | **-5% on exchange** |

### Risk Assessment

**Best case**: Strategy earns 2-5% per month during bear markets, stays flat during bulls. Adds portfolio diversification by profiting when everything else loses.

**Worst case**: Bear regime detection is too slow, enters shorts just as market reverses. Maximum loss limited to ~5% of short allocation ($4.40 on $88 wallet) due to position sizing.

**Most likely case**: Strategy has 3-4 profitable months per year during corrections, breaks even during sideways, and generates small income during confirmed bears. Not a huge earner, but valuable as a hedge.

---

## Sources

### Bear Market Indicators & Analysis
- [5 Charts Confirm Crypto Bear Market - BeInCrypto](https://beincrypto.com/bear-market-bitcoin-price-analysis-2026/)
- [Bitcoin Flashes 5 Bear Market Signals - BeInCrypto](https://beincrypto.com/bitcoin-bear-market-indicators-2026/)
- [Crypto Bear Market Profits: Strategic Short-Selling - AInvest](https://www.ainvest.com/news/crypto-bear-market-profits-strategic-short-selling-insights-2601/)
- [10 Bearish Crypto Trading Indicators - Crypto.com](https://crypto.com/en/university/bearish-trading-indicators-to-know)
- [How to Trade Crypto in Bear Market - Phemex](https://phemex.com/blogs/how-to-trade-crypto-in-a-bear-market)

### Freqtrade Implementation
- [Freqtrade Short/Leverage Documentation](https://www.freqtrade.io/en/stable/leverage/)
- [Freqtrade Strategy Customization](https://www.freqtrade.io/en/stable/strategy-customization/)
- [Freqtrade Issue #8700 - Adding Shorts Kills Trading](https://github.com/freqtrade/freqtrade/issues/8700)
- [Freqtrade Issue #6995 - Futures Short Not Entering](https://github.com/freqtrade/freqtrade/issues/6995)
- [Freqtrade Issue #56 - Bear Market Strategies](https://github.com/freqtrade/freqtrade-strategies/issues/56)
- [Awesome Freqtrade Resources](https://github.com/just-nilux/awesome-freqtrade)

### Risk Management & Position Sizing
- [Shorting Crypto: Insider's Guide - CoinMetro](https://www.coinmetro.com/learning-lab/shorting-cryptocurrencies-insiders-guide-to-profit)
- [Short Squeeze Detection - Bitunix](https://blog.bitunix.com/en/crypto-short-squeeze-detect-defend-profit/)
- [Kelly Criterion for Crypto - OSL](https://www.osl.com/hk-en/academy/article/what-is-the-kelly-bet-size-criterion-and-how-to-use-it-in-crypto-trading)
- [Position Sizing Strategies - QuantifiedStrategies](https://www.quantifiedstrategies.com/position-sizing-strategies/)
- [How to Short Bitcoin - XBTFX](https://xbtfx.com/article/how-to-short-bitcoin-a-complete-guide-for-traders)

### Funding Rates & Exchange Mechanics
- [Understanding Funding Rates - Coinbase](https://www.coinbase.com/learn/perpetual-futures/understanding-funding-rates-in-perpetual-futures)
- [Funding Rate Explained - BingX](https://bingx.com/en/learn/article/what-is-funding-rate-and-how-use-it-in-crypto-trading)
- [Perpetual Futures Explained - Bits About Money](https://www.bitsaboutmoney.com/archive/perpetual-futures-explained/)
- [Funding Rate Arbitrage - CoinGlass](https://www.coinglass.com/learn/what-is-funding-rate-arbitrage)

### Regime Switching & Quant Approaches
- [Regime Switching Forecasting for Crypto - Springer](https://link.springer.com/article/10.1007/s42521-024-00123-2)
- [Building Quant Strategy for Crypto - WunderTrading](https://wundertrading.com/journal/en/learn/article/quant-strategy-crypto-market-guide)
- [Top 10 Algo Trading Strategies 2025 - LuxAlgo](https://www.luxalgo.com/blog/top-10-algo-trading-strategies-for-2025/)

### Mean Reversion vs Trend Following
- [Trend Following and Mean Reversion in Bitcoin - QuantPedia](https://quantpedia.com/trend-following-and-mean-reversion-in-bitcoin/)
- [Revisiting Trend/Mean Reversion in Bitcoin - QuantPedia](https://quantpedia.com/revisiting-trend-following-and-mean-reversion-strategies-in-bitcoin/)
- [Trend Following vs Mean Reversion Backtest - Medium](https://medium.com/@tapu0531/trend-following-vs-mean-reversion-the-winner-is-clear-week-1-backtest-53e5309b74af)
- [Mean Reversion Strategies Backtested - QuantifiedStrategies](https://www.quantifiedstrategies.com/mean-reversion-strategies/)

### Liquidation Cascades
- [Liquidation Cascades in Crypto - Yield App](https://yield.app/blog/what-are-liquidation-cascades-in-crypto)
- [Short Squeeze & Liquidations - BingX](https://bingx.com/en/learn/article/what-is-short-squeeze-in-crypto-how-liquidations-trigger-price-surge)
- [Predicting Bitcoin Crashes via Liquidation Analysis - BeInCrypto](https://beincrypto.com/liquidation-cascade-onchain-technical-analysis/)
- [Anticipating Volatile Moves via Liquidations - Amberdata](https://blog.amberdata.io/liquidations-in-crypto-how-to-anticipate-volatile-market-moves)

### ADX/DMI for Short Selling
- [ADX/DMI Trading Lesson - Interactive Brokers](https://www.interactivebrokers.com/campus/trading-lessons/adx-dmi/)
- [DMI and ADX for Crypto Trends - Phemex](https://phemex.com/academy/how-to-trade-crypto-using-dmi-adx)
- [ADX Indicator Strategies - AvaTrade](https://www.avatrade.com/education/technical-analysis-indicators-strategies/adx-indicator-trading-strategies)
- [DMI and ADX Indicators - Gate.com](https://www.gate.com/crypto-wiki/article/dmi-and-adx-indicators-how-to-trade-using-trend-indicators-20260114)

### Backtesting
- [Backtesting Pitfalls - StarQube](https://starqube.com/backtesting-investment-strategies/)
- [Backtesting Traps - LuxAlgo](https://www.luxalgo.com/blog/backtesting-traps-common-errors-to-avoid/)
- [Freqtrade Backtesting Documentation](https://www.freqtrade.io/en/stable/backtesting/)
- [Backtest with Real Market Data - CoinAPI](https://www.coinapi.io/blog/backtest-crypto-strategies-with-real-market-data)

### Short Selling Guides
- [Short Selling Crypto in Bear Market - CoinBureau](https://coinbureau.com/education/shorting-crypto/)
- [Bear Market Trading Strategies - Arkham](https://info.arkm.com/research/trading-strategies-for-a-bear-market)
- [How to Short Crypto - dYdX](https://www.dydx.xyz/crypto-learning/how-to-short-crypto)
- [Crypto Shorting Guide - Bitget](https://www.bitget.com/academy/crypto-shorting-guide)

### Fund Performance Data
- [2023 Institutional Crypto Hedge Fund Report - Galaxy](https://assets.ctfassets.net/yksdf0mjii3y/3eCgzh5bw0rFWveA57KuOF/54f57fd73eca69404a781916e94e4ff1/GLXY_2023_Whitepaper_VisionTrack.pdf)
- [Top Crypto Hedge Funds by Performance - Crypto Fund Research](https://cryptofundresearch.com/top-crypto-hedge-funds-by-performance-2024/)
- [Michael Ionita on Automation and Risk Management - Fast Track](https://fasttrack.life/episodes/85-mastering-crypto-trading-michael-ionita-on-automation-and-risk-management/)
