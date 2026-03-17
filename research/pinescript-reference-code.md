# Free PineScript Reference Code from Michael Ionita's Channel

Source: https://youtube.com/@michaelionita
Fetched: 2026-03-17

---

## 1. Williams Alligator Strategy with ATR Stop-Loss (FREE)
Source: https://docs.google.com/document/d/1tMPQoYqsPax7PncShmiXNoEerMpKPcHmO_5zK-YBd1c
Video: "All Steps to Creating a GREAT Trading Strategy with AI"
Results: 2,200% BTC, works across BTC/ETH/SOL/XRP

```pinescript
//@version=6
strategy("AI - Williams Alligator Strategy (ATR Stop-Loss)", overlay=true, calc_on_every_tick=false, initial_capital=1000, default_qty_type=strategy.percent_of_equity, default_qty_value=100, commission_type=strategy.commission.percent, commission_value=0.1, slippage=3, pyramiding=1, margin_long=0, margin_short=0, fill_orders_on_standard_ohlc=true)

startDate = input.time(timestamp("1 Jan 2018 00:00 +0000"), "Start Date")
endDate   = input.time(timestamp("31 Dec 2069 23:59 +0000"), "End Date")
timeOK    = time >= startDate and time <= endDate

smma(src, length) =>
    var float s = na
    s := na(s[1]) ? ta.sma(src, length) : (s[1] * (length - 1) + src) / length
    s

jawLength   = input.int(13, minval=1, title="Jaw Length")
teethLength = input.int(8,  minval=1, title="Teeth Length")
lipsLength  = input.int(5,  minval=1, title="Lips Length")
jawOffset   = input.int(0,  title="Jaw Offset")
teethOffset = input.int(0,  title="Teeth Offset")
lipsOffset  = input.int(0,  title="Lips Offset")

atrPeriod   = input.int(14,  title="ATR Period for Stop-Loss")
atrMult     = input.float(2.0, title="ATR Multiplier for Stop-Loss", step=0.1, minval=0.1)
atrValue    = ta.atr(atrPeriod)

jaw   = smma(hl2, jawLength)
teeth = smma(hl2, teethLength)
lips  = smma(hl2, lipsLength)

plot(jaw,   title="Jaw",   color=#2962FF, offset=0)
plot(teeth, title="Teeth", color=#E91E63, offset=0)
plot(lips,  title="Lips",  color=#66BB6A, offset=0)

longCondition = timeOK and ta.crossover(lips, jaw)
exitCondition = timeOK and (ta.crossunder(lips, jaw))

if longCondition
    strategy.entry("Long", strategy.long)

if strategy.position_size > 0
    stopPrice = strategy.position_avg_price - atrMult * atrValue
    strategy.exit("ATR SL", "Long", stop=stopPrice)

if exitCondition
    strategy.close("Long")
```

---

## 2. MA Strategy - Simple 200 SMA Market Timing (FREE)
Source: https://docs.google.com/document/d/1WsYr45NKv93pwGp23fCa36ePvuOS8dhWxAaUTaSYwe0
Video: "How to Time the Crypto Market with These Strategies"

```pinescript
//@version=5
strategy("Demo - MA Strategy", overlay=true, calc_on_every_tick=false, initial_capital=10000, default_qty_type=strategy.percent_of_equity, default_qty_value=100, commission_type=strategy.commission.percent, commission_value=0.1, pyramiding=0, fill_orders_on_standard_ohlc=true)

startDate = input.time(title="Date Start", defval=timestamp("1 Jan 2018 00:00 +0000"), group="Dates")
endDate = input.time(title="Date End", defval=timestamp("31 Dec 2060 23:59 +0000"), group="Dates")
timeCondition = time >= startDate and time <= endDate

useEma = input.bool(defval = false, title = "Use EMA")
smaLength = input.int(defval = 200, title = "SMA Length", minval = 1)

myMa = ta.sma(close, smaLength)
if useEma
    myMa := ta.ema(close, smaLength)
else
    myMa := ta.sma(close, smaLength)

plot(myMa, title="SMA", color = color.black)

longCondition = ta.crossover(close, myMa) and timeCondition
if (longCondition)
    strategy.entry("long", strategy.long)

shortCondition = ta.crossunder(close, myMa) and timeCondition
if (shortCondition)
    strategy.close_all()
```

---

## 3. MACD Cross Strategy - Market Timing (FREE)
Source: same doc as #2

```pinescript
//@version=5
strategy("Demo - MACD Cross Strategy", overlay=true, calc_on_every_tick=false, initial_capital=10000, default_qty_type=strategy.percent_of_equity, default_qty_value=100, commission_type=strategy.commission.percent, commission_value=0.1, pyramiding=0, fill_orders_on_standard_ohlc=true)

startDate = input.time(title="Date Start", defval=timestamp("1 Jan 2018 00:00 +0000"), group="Dates")
endDate = input.time(title="Date End", defval=timestamp("31 Dec 2069 23:59 +0000"), group="Dates")
timeCondition = time >= startDate and time <= endDate

[macdLine, signalLine, histLine] = ta.macd(close, 12, 26, 9)

goLongCondition = ta.crossover(macdLine, signalLine) and timeCondition
goFlatCondition = ta.crossunder(macdLine, signalLine) and timeCondition

if goLongCondition
    strategy.entry(id="long", direction=strategy.long)

if goFlatCondition
    strategy.close_all()
```

---

## 4. AI Strategy Development Prompts (FREE)
Source: https://docs.google.com/document/d/18btb8yAINCzxA2jDfUpzdmqniJxR-5RuavJFf3krcgc

### Backtest prompt:
"With backtest_engine_v21.0, backtest this strategy supertrend_v1.pine, on the BTCUSD 1D chart and give me the results."

### Improve strategy prompt:
"Enhance the supertrend.pine strategy by: achieving higher profit while maintaining or reducing maximum drawdown, analyzing losing trades to eliminate them, identifying and capturing missed trading opportunities, filtering out sideways market conditions, optimizing position sizing, testing improvements and ranking by performance."

### Rank strategies prompt:
"Develop a comprehensive ranking system that: creates a Risk vs. Reward Score (higher scores are preferable), applies industry best practices to scoring methodology, avoids metric redundancy to prevent over-weighting risk or reward factors, balances profitability with appropriate risk levels, incorporates data from all available assets to prevent curve fitting, associates each strategy with its designated timeframe, executes backtests across all strategies and assets, documents scores in an Excel file sorted by ranking."

---

## 5. Gaussian Channel Strategy Notes
The Gaussian Channel strategy code is NOT free — it's behind the Signum platform (signum.money) or the paid AutoTrading Masterclass (autotrading.vip). However, the indicator itself is available on TradingView as "Gaussian Channel" by DonovanWall. The strategy logic is simple:
- Buy when close > upper Gaussian channel band
- Sell when close < upper Gaussian channel band
- Daily timeframe, default parameters
- 4H variant: source=HL2, poles=4, sampling_period=144, filter_range_multiplier=2
