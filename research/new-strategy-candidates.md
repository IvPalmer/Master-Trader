# New Strategy Candidates for Port 8089

**Date:** 2026-03-12
**Goal:** Fill the empty bot slot (port 8089, currently running NFI with 0 trades) with a strategy that diversifies the portfolio.

## Current Portfolio Analysis

| Bot | Strategy | Timeframe | Type | Status |
|-----|----------|-----------|------|--------|
| 8080 | ClucHAnix | 5m | Dip-buyer | Running |
| 8082 | NASOSv5 | 5m | Dip-buyer | Running |
| 8083 | ElliotV5 | 5m | Dip-buyer | Running |
| 8084 | SupertrendStrategy | 1h | Trend-follower (ATR/ADX) | Running |
| 8086 | MasterTraderV1 | 1h | Hybrid | Running |
| 8087 | MasterTraderAI | 1h | FreqAI (LightGBM) | Running |
| 8089 | NostalgiaForInfinityX6 | 5m | Multi-signal | **0 trades** |

**Gaps identified:**
- No 15m or 4h timeframe strategies
- No pure mean-reversion strategy
- No volume-based / breakout strategy
- Heavy correlation: three 5m dip-buyers will all enter/exit together in drawdowns

## Candidate 1: BollingerRSI MeanReversion (15m) -- RECOMMENDED

### Strategy Logic
Classic mean-reversion approach enhanced with regime filtering to avoid trending markets:

1. **Entry:** Price closes below lower Bollinger Band (20, 2.0) AND RSI(14) < 30 AND ADX(14) < 30 (ranging market filter)
2. **Exit:** Price crosses above middle Bollinger Band OR RSI > 65
3. **Regime filter:** ADX > 30 = trending market = no new entries (avoids "walking the band" losses)
4. **Timeframe:** 15m -- fills the gap, uncorrelated with both 5m scalpers and 1h trend-followers

### Why It Diversifies
- **Different timeframe** (15m) from everything else in portfolio
- **Mean-reversion** is anti-correlated with trend-following (Supertrend) -- when trends fail and chop, this profits
- **ADX regime filter** prevents trading during strong trends where dip-buyers also struggle
- **Different signal source** -- BB width + RSI vs. the EMA/MACD/Supertrend signals used elsewhere

### Expected Characteristics
- Trade frequency: ~5-15 trades/week depending on market volatility
- Win rate: ~55-65% (mean-reversion has higher win rate, smaller wins)
- Best in: Ranging/sideways markets (exactly when trend-followers bleed)
- Worst in: Strong trending markets (but ADX filter mitigates this)

### Community Track Record
- BbandRsi is one of the oldest strategies in the [official freqtrade-strategies repo](https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/berlinguyinca/BbandRsi.py)
- [FreqST backtest](https://www.freqst.com/strategy/e50c36ee0dd5e7da43ccd6b6fa7a090fa798e565f595d737c9ecbe079364fbfff4341c985ae44/) showed 60% win rate on 15m
- Our version adds ADX regime filter + tighter risk management

### Implementation

```python
# --- Do not remove these libs ---
from freqtrade.strategy import IStrategy
from pandas import DataFrame
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib

class BollingerRSIMeanReversion(IStrategy):
    """
    15m Bollinger Bands + RSI Mean Reversion Strategy

    Buys when price dips below lower BB with RSI oversold, in ranging markets only.
    Exits on reversion to the mean (middle BB) or RSI recovery.
    ADX filter prevents entries during strong trends.

    Designed to complement a portfolio of 5m dip-buyers and 1h trend-followers.
    """

    INTERFACE_VERSION: int = 3

    # ROI: take profits as price reverts to mean
    minimal_roi = {
        "0": 0.04,    # 4% immediate
        "30": 0.025,  # 2.5% after 30 min
        "60": 0.015,  # 1.5% after 1h
        "120": 0.005  # 0.5% after 2h (close marginal winners)
    }

    stoploss = -0.06  # 6% hard stop -- mean-reversion uses tighter stops

    # Trailing stop to lock in profits on strong reversions
    trailing_stop = True
    trailing_stop_positive = 0.01      # 1% trail
    trailing_stop_positive_offset = 0.02  # activate at 2% profit
    trailing_only_offset_is_reached = True

    timeframe = '15m'

    # Only process new candles for efficiency
    process_only_new_candles = True
    startup_candle_count = 30

    # Protections
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # RSI
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)

        # Bollinger Bands (20, 2.0)
        bollinger = qtpylib.bollinger_bands(
            qtpylib.typical_price(dataframe), window=20, stds=2
        )
        dataframe['bb_lowerband'] = bollinger['lower']
        dataframe['bb_middleband'] = bollinger['mid']
        dataframe['bb_upperband'] = bollinger['upper']
        dataframe['bb_width'] = (
            (dataframe['bb_upperband'] - dataframe['bb_lowerband']) / dataframe['bb_middleband']
        )

        # ADX for regime detection
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)

        # ATR for volatility context
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)

        # Volume SMA for volume confirmation
        dataframe['volume_sma'] = ta.SMA(dataframe['volume'], timeperiod=20)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Mean-reversion signal
                (dataframe['close'] < dataframe['bb_lowerband']) &
                (dataframe['rsi'] < 30) &

                # Regime filter: only trade in ranging markets
                (dataframe['adx'] < 30) &

                # Bollinger bandwidth not too narrow (avoid low-vol squeezes)
                (dataframe['bb_width'] > 0.02) &

                # Volume confirmation: above average
                (dataframe['volume'] > dataframe['volume_sma']) &
                (dataframe['volume'] > 0)
            ),
            'enter_long'] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Price reverted to the mean
                (dataframe['close'] > dataframe['bb_middleband']) |
                # RSI recovered
                (dataframe['rsi'] > 65)
            ),
            'exit_long'] = 1

        return dataframe
```

---

## Candidate 2: VWAP Momentum Breakout (15m)

### Strategy Logic
Volume-weighted breakout strategy that enters on strong volume surges above VWAP:

1. **Entry:** Close > VWAP AND CCI(20) > 100 AND RSI(14) > 55 AND volume > 2x SMA(20)
2. **Exit:** Close < VWAP OR CCI < -50 OR RSI < 45
3. **Regime filter:** ADX > 25 (only trade when trending -- opposite of mean-reversion)
4. **Timeframe:** 15m

### Why It Diversifies
- Volume-driven entries are fundamentally different from indicator-based dip-buying
- Performs best in breakout/trending conditions
- If paired with Candidate 1, they cover both ranging AND trending regimes

### Expected Characteristics
- Trade frequency: ~3-8 trades/week (selective on volume spikes)
- Win rate: ~40-50% (breakouts have lower win rate but larger winners)
- Best in: Volatile breakout markets
- Worst in: Low-volume choppy periods

### Community Track Record
- VWAP strategies are well-documented in the [PeetCrypto freqtrade-stuff repo](https://github.com/PeetCrypto/freqtrade-stuff/blob/main/VWAP.py)
- [FreqST has VWAP performance data](http://freqst.com/strategy/5a4ea90b84c97db71533077401e10d7d1f6205b59bba3efd92fc780ee252f0c67854de31936fa/)
- CCI + VWAP combination has logical basis in volume profile theory

### Implementation (pseudo-code)

```python
class VWAPMomentumBreakout(IStrategy):
    INTERFACE_VERSION: int = 3
    timeframe = '15m'
    stoploss = -0.08
    minimal_roi = {"0": 0.06, "45": 0.03, "90": 0.01}
    trailing_stop = True
    trailing_stop_positive = 0.015
    trailing_stop_positive_offset = 0.03

    def populate_indicators(self, dataframe, metadata):
        # VWAP (reset daily) -- use ta-lib or manual calc
        dataframe['vwap'] = (
            (dataframe['volume'] * dataframe['close']).cumsum() /
            dataframe['volume'].cumsum()
        )
        dataframe['cci'] = ta.CCI(dataframe, timeperiod=20)
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
        dataframe['volume_sma'] = ta.SMA(dataframe['volume'], timeperiod=20)
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe.loc[
            (dataframe['close'] > dataframe['vwap']) &
            (dataframe['cci'] > 100) &
            (dataframe['rsi'] > 55) &
            (dataframe['adx'] > 25) &
            (dataframe['volume'] > 2 * dataframe['volume_sma']),
            'enter_long'] = 1
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe.loc[
            (dataframe['close'] < dataframe['vwap']) |
            (dataframe['cci'] < -50),
            'exit_long'] = 1
        return dataframe
```

**Note:** VWAP calculation above is simplified. For proper daily-reset VWAP in Freqtrade, you need `informative_pairs()` with a 1d timeframe or manual date-boundary resets. This adds complexity.

---

## Candidate 3: Keltner Channel + Stochastic RSI (4h)

### Strategy Logic
Higher-timeframe mean-reversion using Keltner Channels (ATR-based bands) with Stochastic RSI confirmation:

1. **Entry:** Close < lower Keltner Channel (EMA 20, 1.5 ATR) AND StochRSI K < 20 AND ADX < 35
2. **Exit:** Close > Keltner mid-line OR StochRSI K > 80
3. **Timeframe:** 4h -- the only 4h strategy in the portfolio

### Why It Diversifies
- **4h timeframe** is completely uncorrelated with 5m and 1h bots
- Keltner Channels use ATR (volatility-adaptive) instead of standard deviation (Bollinger)
- Very low trade frequency reduces portfolio churn
- Longer holding periods capture bigger mean-reversion swings

### Expected Characteristics
- Trade frequency: ~1-4 trades/week (very selective)
- Win rate: ~50-60%
- Hold time: 12-48 hours typically
- Best in: Multi-day ranging markets
- Worst in: Strong multi-day trends

### Community Track Record
- [FreqST Keltner Channel results](https://www.freqst.com/strategy/cb6d1158fc7d7c26e9e863bb53bfdfea62e00eafc561c4206253f90450bf2d1f71a615067d2af/) available
- Keltner + StochRSI is a well-known combination in traditional markets
- Less common in crypto Freqtrade community (more novel)

### Implementation (pseudo-code)

```python
class KeltnerStochRSI(IStrategy):
    INTERFACE_VERSION: int = 3
    timeframe = '4h'
    stoploss = -0.08
    minimal_roi = {"0": 0.05, "240": 0.03, "720": 0.01}
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.035

    def populate_indicators(self, dataframe, metadata):
        dataframe['ema20'] = ta.EMA(dataframe, timeperiod=20)
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)
        dataframe['kc_upper'] = dataframe['ema20'] + 1.5 * dataframe['atr']
        dataframe['kc_lower'] = dataframe['ema20'] - 1.5 * dataframe['atr']
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
        stoch_rsi = ta.STOCHRSI(dataframe, timeperiod=14)
        dataframe['stochrsi_k'] = stoch_rsi['fastk']
        dataframe['stochrsi_d'] = stoch_rsi['fastd']
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe.loc[
            (dataframe['close'] < dataframe['kc_lower']) &
            (dataframe['stochrsi_k'] < 20) &
            (dataframe['adx'] < 35),
            'enter_long'] = 1
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe.loc[
            (dataframe['close'] > dataframe['ema20']) |
            (dataframe['stochrsi_k'] > 80),
            'exit_long'] = 1
        return dataframe
```

---

## Recommendation Matrix

| Criteria | Candidate 1: BollingerRSI | Candidate 2: VWAP Breakout | Candidate 3: Keltner 4h |
|----------|---------------------------|---------------------------|------------------------|
| Diversification | **A** (15m, mean-rev) | **A** (15m, volume) | **A+** (4h, unique TF) |
| Implementation ease | **A** (simple, proven) | **B** (VWAP calc tricky) | **A** (straightforward) |
| Community track record | **A** (official repo) | **B** (less tested) | **B-** (novel combo) |
| Regime awareness | **A** (ADX filter) | **A** (ADX + volume) | **A** (ADX filter) |
| Anti-correlation w/ portfolio | **A+** (profits in chop) | **B** (overlaps trend) | **A** (different TF) |
| Expected robustness | **A** (classic, well-understood) | **B** (volume spikes noisy) | **B+** (less data on 4h) |

## Final Recommendation

**Deploy Candidate 1: BollingerRSI MeanReversion on port 8089.**

Reasons:
1. **Strongest anti-correlation** -- profits in ranging markets where all three dip-buyers and the trend-follower lose
2. **15m timeframe** fills a gap without going too slow (4h would produce very few trades to evaluate in dry-run)
3. **Simplest implementation** -- fully production-ready code above, uses only standard TA-Lib/qtpylib indicators
4. **Best community evidence** -- based on the official BbandRsi strategy with proven logic, enhanced with ADX regime filter
5. **Quick to validate** -- enough trades per week to evaluate within 2-3 weeks of dry-run

### Deployment Steps
1. Save the Candidate 1 code as `~/ft_userdata/user_data/strategies/BollingerRSIMeanReversion.py`
2. Create config at `~/ft_userdata/user_data/configs/BollingerRSIMeanReversion.json`
3. Update `docker-compose.yml` to replace NFI on port 8089
4. Backtest first: `docker compose run --rm freqtrade backtesting --strategy BollingerRSIMeanReversion --timerange 20260101-20260312 --config user_data/configs/BollingerRSIMeanReversion.json`
5. If backtest passes gate (drawdown < 20%, win rate > 45%), start dry-run
6. Monitor for 2-3 weeks, then run hyperopt with `--disable-param-export`

### Future Consideration
If Candidate 1 proves successful, consider adding Candidate 3 (Keltner 4h) as a 7th bot for even more timeframe diversification.

---

## Sources
- [Official freqtrade-strategies repo](https://github.com/freqtrade/freqtrade-strategies)
- [BbandRsi source code](https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/berlinguyinca/BbandRsi.py)
- [FreqST BbandRsi performance](https://www.freqst.com/strategy/e50c36ee0dd5e7da43ccd6b6fa7a090fa798e565f595d737c9ecbe079364fbfff4341c985ae44/)
- [FreqST Keltner Channel results](https://www.freqst.com/strategy/cb6d1158fc7d7c26e9e863bb53bfdfea62e00eafc561c4206253f90450bf2d1f71a615067d2af/)
- [PeetCrypto VWAP strategy](https://github.com/PeetCrypto/freqtrade-stuff/blob/main/VWAP.py)
- [Freqtrade Strategy Customization docs](https://www.freqtrade.io/en/stable/strategy-customization/)
- [Mean Reversion Trading Strategies (EzAlgo)](https://www.ezalgo.ai/blog/mean-reverting-trading-strategies)
