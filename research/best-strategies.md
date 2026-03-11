# Best Open-Source Freqtrade Strategies

Research date: 2026-03-10

## Overview

This document catalogs the best-performing open-source Freqtrade strategies found across GitHub, strat.ninja rankings, and community forums. Each strategy includes full source code for backtesting.

**Important caveats:**
- Backtest results do NOT guarantee live performance
- Slippage, fees, and market conditions will reduce real profits
- All strategies should be paper-traded before risking real capital
- Strategies may need hyperopt tuning for current market conditions

---

## Strategy Rankings (strat.ninja - March 2026)

Top strategies by "Ninja Score" (composite of profit, win rate, drawdown, Sharpe/Sortino ratios):

| Rank | Strategy | Score | Profit % | Win % | Drawdown % | Avg Profit | TF |
|------|----------|-------|----------|-------|------------|------------|-----|
| 1 | newstrategy5_1 | 69 | 1.53 | 100.00 | 0.00 | 2.82 | 5m |
| 2 | newstrategy53 | 66 | 1.41 | 95.67 | 0.30 | 3.05 | 5m |
| 3 | jhoravi | 63 | 5.83 | 88.67 | 3.20 | 0.71 | 5m |
| 4 | ElliotV5_SMA | 62 | 2.73 | 75.67 | 4.47 | 0.58 | 5m |
| 5 | jhoravi_03 | 62 | 6.41 | 77.00 | 2.43 | 1.32 | 5m |
| 6 | NASOSv5ho | 57 | 5.62 | 78.00 | 5.97 | 0.76 | 5m |

Source: https://strat.ninja/ranking.php

---

## Strategy 1: NASOSv5 (Not Another SMA Offset Strategy)

**Source:** https://github.com/5drei1/freqtrade_pub_strats/blob/main/NASOSv5.py
**Authors:** @Rallipanos, @pluxury, with help from @stash86 and @Perkmeister
**Timeframe:** 5m (uses 15m informative)
**Stoploss:** -15% (with custom dynamic stoploss)
**Ninja Score:** 57 | Win Rate: 78% | Drawdown: ~6%

### What makes it good
- Uses Elliott Wave Oscillator (EWO) for momentum detection
- Multiple buy conditions (bullish EWO, bearish EWO, and deep dip)
- Dynamic custom stoploss that tightens as profit increases
- Anti-slippage protection on sell
- Lookback protection to avoid buying when recent highs are too close
- Well-tested by community, multiple mods exist (v5_mod1, mod2, mod3)

### Indicators
- EMA (multiple periods: 8-20 for MA buy/sell bands)
- Hull Moving Average (HMA 50)
- EMA 100
- SMA 9
- Elliott Wave Oscillator (EWO - using EMA 50 vs EMA 200)
- RSI (14, 4-period fast, 20-period slow)

### Full Source Code

```python
# --- Do not remove these libs ---
from logging import FATAL
from freqtrade.strategy.interface import IStrategy
from typing import Dict, List
from functools import reduce
from pandas import DataFrame
import talib.abstract as ta
import numpy as np
import freqtrade.vendor.qtpylib.indicators as qtpylib
import datetime
from technical.util import resample_to_interval, resampled_merge
from datetime import datetime, timedelta
from freqtrade.persistence import Trade
from freqtrade.strategy import stoploss_from_open, merge_informative_pair, DecimalParameter, IntParameter, CategoricalParameter
import technical.indicators as ftt

# @Rallipanos
# @pluxury
# with help from @stash86 and @Perkmeister

# Buy hyperspace params:
buy_params = {
    "low_offset": 0.981,
    "base_nb_candles_buy": 8,
    "ewo_high": 3.553,
    "ewo_high_2": -5.585,
    "ewo_low": -14.378,
    "lookback_candles": 32,
    "low_offset_2": 0.942,
    "profit_threshold": 1.037,
    "rsi_buy": 78,
    "rsi_fast_buy": 37,
}

# Sell hyperspace params:
sell_params = {
    "base_nb_candles_sell": 16,
    "high_offset": 1.097,
    "high_offset_2": 1.472,
}


def EWO(dataframe, ema_length=5, ema2_length=35):
    df = dataframe.copy()
    ema1 = ta.EMA(df, timeperiod=ema_length)
    ema2 = ta.EMA(df, timeperiod=ema2_length)
    emadif = (ema1 - ema2) / df['low'] * 100
    return emadif


class NASOSv5(IStrategy):
    INTERFACE_VERSION = 2

    minimal_roi = {
        "360": 0
    }

    stoploss = -0.15

    # SMAOffset
    base_nb_candles_buy = IntParameter(
        2, 20, default=buy_params['base_nb_candles_buy'], space='buy', optimize=False)
    base_nb_candles_sell = IntParameter(
        2, 25, default=sell_params['base_nb_candles_sell'], space='sell', optimize=False)
    low_offset = DecimalParameter(
        0.9, 0.99, default=buy_params['low_offset'], space='buy', optimize=True)
    low_offset_2 = DecimalParameter(
        0.9, 0.99, default=buy_params['low_offset_2'], space='buy', optimize=False)
    high_offset = DecimalParameter(
        0.95, 1.1, default=sell_params['high_offset'], space='sell', optimize=True)
    high_offset_2 = DecimalParameter(
        0.99, 1.5, default=sell_params['high_offset_2'], space='sell', optimize=False)

    # Protection
    fast_ewo = 50
    slow_ewo = 200

    lookback_candles = IntParameter(
        1, 36, default=buy_params['lookback_candles'], space='buy', optimize=False)
    profit_threshold = DecimalParameter(0.99, 1.05,
                                        default=buy_params['profit_threshold'], space='buy', optimize=False)
    ewo_low = DecimalParameter(-20.0, -8.0,
                               default=buy_params['ewo_low'], space='buy', optimize=False)
    ewo_high = DecimalParameter(
        2.0, 12.0, default=buy_params['ewo_high'], space='buy', optimize=False)
    ewo_high_2 = DecimalParameter(
        -6.0, 12.0, default=buy_params['ewo_high_2'], space='buy', optimize=False)
    rsi_buy = IntParameter(10, 80, default=buy_params['rsi_buy'], space='buy', optimize=False)
    rsi_fast_buy = IntParameter(
        10, 50, default=buy_params['rsi_fast_buy'], space='buy', optimize=False)

    # Trailing stop:
    trailing_stop = False
    trailing_stop_positive = 0.001
    trailing_stop_positive_offset = 0.016
    trailing_only_offset_is_reached = True

    # Sell signal
    use_sell_signal = True
    sell_profit_only = False
    sell_profit_offset = 0.01
    ignore_roi_if_buy_signal = False

    order_time_in_force = {
        'buy': 'gtc',
        'sell': 'ioc'
    }

    timeframe = '5m'
    inf_15m = '15m'
    inf_1h = '1h'

    process_only_new_candles = True
    startup_candle_count = 200
    use_custom_stoploss = True

    slippage_protection = {
        'retries': 3,
        'max_slippage': -0.02
    }

    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        if (current_profit > 0.3):
            return 0.05
        elif (current_profit > 0.1):
            return 0.03
        elif (current_profit > 0.06):
            return 0.02
        elif (current_profit > 0.04):
            return 0.01
        elif (current_profit > 0.025):
            return 0.005
        elif (current_profit > 0.018):
            return 0.005
        return 0.15

    def confirm_trade_exit(self, pair: str, trade: Trade, order_type: str, amount: float,
                           rate: float, time_in_force: str, sell_reason: str,
                           current_time: datetime, **kwargs) -> bool:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        last_candle = dataframe.iloc[-1]

        if (last_candle is not None):
            if (sell_reason in ['sell_signal']):
                if (last_candle['hma_50']*1.149 > last_candle['ema_100']) and (last_candle['close'] < last_candle['ema_100']*0.951):
                    return False

        # slippage protection
        try:
            state = self.slippage_protection['__pair_retries']
        except KeyError:
            state = self.slippage_protection['__pair_retries'] = {}

        candle = dataframe.iloc[-1].squeeze()
        slippage = (rate / candle['close']) - 1
        if slippage < self.slippage_protection['max_slippage']:
            pair_retries = state.get(pair, 0)
            if pair_retries < self.slippage_protection['retries']:
                state[pair] = pair_retries + 1
                return False
        state[pair] = 0
        return True

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        informative_pairs = [(pair, '15m') for pair in pairs]
        return informative_pairs

    def informative_15m_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        assert self.dp, "DataProvider is required for multiple timeframes."
        informative_15m = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe=self.inf_15m)
        return informative_15m

    def normal_tf_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        for val in self.base_nb_candles_buy.range:
            dataframe[f'ma_buy_{val}'] = ta.EMA(dataframe, timeperiod=val)
        for val in self.base_nb_candles_sell.range:
            dataframe[f'ma_sell_{val}'] = ta.EMA(dataframe, timeperiod=val)

        dataframe['hma_50'] = qtpylib.hull_moving_average(dataframe['close'], window=50)
        dataframe['ema_100'] = ta.EMA(dataframe, timeperiod=100)
        dataframe['sma_9'] = ta.SMA(dataframe, timeperiod=9)
        dataframe['EWO'] = EWO(dataframe, self.fast_ewo, self.slow_ewo)
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['rsi_fast'] = ta.RSI(dataframe, timeperiod=4)
        dataframe['rsi_slow'] = ta.RSI(dataframe, timeperiod=20)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        informative_15m = self.informative_15m_indicators(dataframe, metadata)
        dataframe = merge_informative_pair(
            dataframe, informative_15m, self.timeframe, self.inf_15m, ffill=True)
        dataframe = self.normal_tf_indicators(dataframe, metadata)
        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dont_buy_conditions = []
        dont_buy_conditions.append(
            (
                (dataframe['close_15m'].rolling(self.lookback_candles.value).max()
                 < (dataframe['close'] * self.profit_threshold.value))
            )
        )

        dataframe.loc[
            (
                (dataframe['rsi_fast'] < self.rsi_fast_buy.value) &
                (dataframe['close'] < (dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] * self.low_offset.value)) &
                (dataframe['EWO'] > self.ewo_high.value) &
                (dataframe['rsi'] < self.rsi_buy.value) &
                (dataframe['volume'] > 0) &
                (dataframe['close'] < (
                    dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value))
            ),
            ['buy', 'buy_tag']] = (1, 'ewo1')

        dataframe.loc[
            (
                (dataframe['rsi_fast'] < self.rsi_fast_buy.value) &
                (dataframe['close'] < (dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] * self.low_offset_2.value)) &
                (dataframe['EWO'] > self.ewo_high_2.value) &
                (dataframe['rsi'] < self.rsi_buy.value) &
                (dataframe['volume'] > 0) &
                (dataframe['close'] < (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value)) &
                (dataframe['rsi'] < 25)
            ),
            ['buy', 'buy_tag']] = (1, 'ewo2')

        dataframe.loc[
            (
                (dataframe['rsi_fast'] < self.rsi_fast_buy.value) &
                (dataframe['close'] < (dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] * self.low_offset.value)) &
                (dataframe['EWO'] < self.ewo_low.value) &
                (dataframe['volume'] > 0) &
                (dataframe['close'] < (
                    dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value))
            ),
            ['buy', 'buy_tag']] = (1, 'ewolow')

        if dont_buy_conditions:
            for condition in dont_buy_conditions:
                dataframe.loc[condition, 'buy'] = 0

        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []
        conditions.append(
            ((dataframe['close'] > dataframe['sma_9']) &
                (dataframe['close'] > (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset_2.value)) &
                (dataframe['rsi'] > 50) &
                (dataframe['volume'] > 0) &
                (dataframe['rsi_fast'] > dataframe['rsi_slow'])
             )
            |
            (
                (dataframe['close'] < dataframe['hma_50']) &
                (dataframe['close'] > (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value)) &
                (dataframe['volume'] > 0) &
                (dataframe['rsi_fast'] > dataframe['rsi_slow'])
            )
        )

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x | y, conditions),
                'sell'
            ]=1
        return dataframe
```

### Binance Spot Suitability
Excellent. This is one of the most battle-tested strategies in the community. Works with any USDT pairs on Binance spot. Recommended 4-6 max open trades.

---

## Strategy 2: CombinedBinHAndCluc

**Source:** https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/berlinguyinca/CombinedBinHAndCluc.py
**Author:** berlinguyinca (official Freqtrade strategies repo)
**Timeframe:** 5m
**Stoploss:** -5%
**ROI:** 5% target

### What makes it good
- Combines two proven sub-strategies: BinHV45 and ClucMay72018
- BinHV45 detects Bollinger Band delta squeezes
- ClucMay72018 looks for deep dips below lower Bollinger Band with slow EMA filter
- Tight stoploss (-5%) with 5% ROI target = good risk/reward
- Simple, clean code - easy to understand and modify
- From the official Freqtrade strategies repository

### Indicators
- Custom Bollinger Bands (40-period, 2 std)
- Standard Bollinger Bands (20-period, 2 std on typical price)
- EMA 50 (slow trend filter)
- Volume (30-period mean)
- BB delta, close delta, tail measurements

### Full Source Code

```python
import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
import talib.abstract as ta
from freqtrade.strategy import IStrategy
from pandas import DataFrame


def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)


class CombinedBinHAndCluc(IStrategy):
    # Best with max_open_trades = 2
    INTERFACE_VERSION: int = 3
    minimal_roi = {
        "0": 0.05
    }
    stoploss = -0.05
    timeframe = '5m'

    use_exit_signal = True
    exit_profit_only = True
    ignore_roi_if_entry_signal = False

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # strategy BinHV45
        mid, lower = bollinger_bands(dataframe['close'], window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['close'] - dataframe['close'].shift()).abs()
        dataframe['tail'] = (dataframe['close'] - dataframe['low']).abs()
        # strategy ClucMay72018
        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe['bb_lowerband'] = bollinger['lower']
        dataframe['bb_middleband'] = bollinger['mid']
        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (  # strategy BinHV45
                    dataframe['lower'].shift().gt(0) &
                    dataframe['bbdelta'].gt(dataframe['close'] * 0.008) &
                    dataframe['closedelta'].gt(dataframe['close'] * 0.0175) &
                    dataframe['tail'].lt(dataframe['bbdelta'] * 0.25) &
                    dataframe['close'].lt(dataframe['lower'].shift()) &
                    dataframe['close'].le(dataframe['close'].shift())
            ) |
            (  # strategy ClucMay72018
                    (dataframe['close'] < dataframe['ema_slow']) &
                    (dataframe['close'] < 0.985 * dataframe['bb_lowerband']) &
                    (dataframe['volume'] < (dataframe['volume_mean_slow'].shift(1) * 20))
            ),
            'enter_long'
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe['close'] > dataframe['bb_middleband']),
            'exit_long'
        ] = 1
        return dataframe
```

### Binance Spot Suitability
Excellent. Uses INTERFACE_VERSION 3 (modern). Best with max_open_trades=2 and higher stake amounts. Very conservative entry conditions make it selective.

---

## Strategy 3: ClucHAnix (Cluc + Heikin-Ashi + Nix)

**Source:** https://github.com/phuchust/freqtrade_strategy/blob/main/ClucHAnix.py
**Timeframe:** 1m (can be adapted to 5m)
**Stoploss:** Custom dynamic stoploss (interpolated between -32% hard stop and trailing)
**Reported:** Strong community following, multiple fork variants

### What makes it good
- Combines Bollinger Bands with Heikin-Ashi candles for smoother signals
- Sophisticated custom stoploss with linear interpolation between profit levels
- Uses 1h informative timeframe for trend confirmation (ROCR)
- Includes pre-optimized subclasses for ETH, BTC, and USD pairs
- Anti-noise: Heikin-Ashi smoothing reduces false signals

### Indicators
- Heikin-Ashi candles (open, close, high, low)
- Custom Bollinger Bands on HA typical price (40-period, 2 std)
- EMA fast (3-period on HA close)
- EMA slow (50-period on HA close)
- Volume mean slow (30-period)
- ROCR (Rate of Change Ratio, 28-period)
- RSI and Fisher Transform
- 1h ROCR (168-period) for trend confirmation

### Full Source Code

```python
import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
import talib.abstract as ta
from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import merge_informative_pair, DecimalParameter, stoploss_from_open, RealParameter
from pandas import DataFrame, Series
from datetime import datetime

def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)

def ha_typical_price(bars):
    res = (bars['ha_high'] + bars['ha_low'] + bars['ha_close']) / 3.
    return Series(index=bars.index, data=res)

class ClucHAnix(IStrategy):
    buy_params = {
        'bbdelta_close': 0.01965,
        'bbdelta_tail': 0.95089,
        'close_bblower': 0.00799,
        'closedelta_close': 0.00556,
        'rocr_1h': 0.54904
    }

    sell_params = {
        "pHSL": -0.32,
        "pPF_1": 0.02,
        "pPF_2": 0.047,
        "pSL_1": 0.02,
        "pSL_2": 0.046,
        'sell-fisher': 0.38414,
        'sell-bbmiddle-close': 1.07634
    }

    minimal_roi = {
        "70": 0
    }

    stoploss = -0.99  # uses custom stoploss
    trailing_stop = False
    timeframe = '1m'
    use_sell_signal = True
    sell_profit_only = False
    ignore_roi_if_buy_signal = False
    use_custom_stoploss = True
    process_only_new_candles = True
    startup_candle_count = 168

    order_types = {
        'buy': 'market',
        'sell': 'market',
        'emergencysell': 'market',
        'forcebuy': "market",
        'forcesell': 'market',
        'stoploss': 'market',
        'stoploss_on_exchange': False,
        'stoploss_on_exchange_interval': 60,
        'stoploss_on_exchange_limit_ratio': 0.99
    }

    # buy params
    rocr_1h = RealParameter(0.5, 1.0, default=0.54904, space='buy', optimize=True)
    bbdelta_close = RealParameter(0.0005, 0.02, default=0.01965, space='buy', optimize=True)
    closedelta_close = RealParameter(0.0005, 0.02, default=0.00556, space='buy', optimize=True)
    bbdelta_tail = RealParameter(0.7, 1.0, default=0.95089, space='buy', optimize=True)
    close_bblower = RealParameter(0.0005, 0.02, default=0.00799, space='buy', optimize=True)

    # custom stoploss params
    pHSL = DecimalParameter(-0.500, -0.040, default=-0.08, decimals=3, space='sell', load=True)
    pPF_1 = DecimalParameter(0.008, 0.020, default=0.016, decimals=3, space='sell', load=True)
    pSL_1 = DecimalParameter(0.008, 0.020, default=0.011, decimals=3, space='sell', load=True)
    pPF_2 = DecimalParameter(0.040, 0.100, default=0.080, decimals=3, space='sell', load=True)
    pSL_2 = DecimalParameter(0.020, 0.070, default=0.040, decimals=3, space='sell', load=True)

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        informative_pairs = [(pair, '1h') for pair in pairs]
        return informative_pairs

    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        HSL = self.pHSL.value
        PF_1 = self.pPF_1.value
        SL_1 = self.pSL_1.value
        PF_2 = self.pPF_2.value
        SL_2 = self.pSL_2.value

        if (current_profit > PF_2):
            sl_profit = SL_2 + (current_profit - PF_2)
        elif (current_profit > PF_1):
            sl_profit = SL_1 + ((current_profit - PF_1) * (SL_2 - SL_1) / (PF_2 - PF_1))
        else:
            sl_profit = HSL

        if (sl_profit >= current_profit):
            return -0.99
        return stoploss_from_open(sl_profit, current_profit)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        heikinashi = qtpylib.heikinashi(dataframe)
        dataframe['ha_open'] = heikinashi['open']
        dataframe['ha_close'] = heikinashi['close']
        dataframe['ha_high'] = heikinashi['high']
        dataframe['ha_low'] = heikinashi['low']

        mid, lower = bollinger_bands(ha_typical_price(dataframe), window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['mid'] = mid
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['ha_close'] - dataframe['ha_close'].shift()).abs()
        dataframe['tail'] = (dataframe['ha_close'] - dataframe['ha_low']).abs()
        dataframe['bb_lowerband'] = dataframe['lower']
        dataframe['bb_middleband'] = dataframe['mid']

        dataframe['ema_fast'] = ta.EMA(dataframe['ha_close'], timeperiod=3)
        dataframe['ema_slow'] = ta.EMA(dataframe['ha_close'], timeperiod=50)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()
        dataframe['rocr'] = ta.ROCR(dataframe['ha_close'], timeperiod=28)

        rsi = ta.RSI(dataframe)
        dataframe["rsi"] = rsi
        rsi = 0.1 * (rsi - 50)
        dataframe["fisher"] = (np.exp(2 * rsi) - 1) / (np.exp(2 * rsi) + 1)

        inf_tf = '1h'
        informative = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe=inf_tf)
        inf_heikinashi = qtpylib.heikinashi(informative)
        informative['ha_close'] = inf_heikinashi['close']
        informative['rocr'] = ta.ROCR(informative['ha_close'], timeperiod=168)
        dataframe = merge_informative_pair(dataframe, informative, self.timeframe, inf_tf, ffill=True)
        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                dataframe['rocr_1h'].gt(self.rocr_1h.value)
            ) &
            ((
                    (dataframe['lower'].shift().gt(0)) &
                    (dataframe['bbdelta'].gt(dataframe['ha_close'] * self.bbdelta_close.value)) &
                    (dataframe['closedelta'].gt(dataframe['ha_close'] * self.closedelta_close.value)) &
                    (dataframe['tail'].lt(dataframe['bbdelta'] * self.bbdelta_tail.value)) &
                    (dataframe['ha_close'].lt(dataframe['lower'].shift())) &
                    (dataframe['ha_close'].le(dataframe['ha_close'].shift()))
            ) |
            (
                    (dataframe['ha_close'] < dataframe['ema_slow']) &
                    (dataframe['ha_close'] < self.close_bblower.value * dataframe['bb_lowerband'])
            )),
            'buy'
        ] = 1
        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe['fisher'] > self.sell_params['sell-fisher']) &
            (dataframe['ha_high'].le(dataframe['ha_high'].shift(1))) &
            (dataframe['ha_high'].shift(1).le(dataframe['ha_high'].shift(2))) &
            (dataframe['ha_close'].le(dataframe['ha_close'].shift(1))) &
            (dataframe['ema_fast'] > dataframe['ha_close']) &
            ((dataframe['ha_close'] * self.sell_params['sell-bbmiddle-close']) > dataframe['bb_middleband']) &
            (dataframe['volume'] > 0),
            'sell'
        ] = 1
        return dataframe
```

### Binance Spot Suitability
Good. Includes pre-optimized subclasses for different stake currencies (ETH, BTC, USD). The 1m timeframe requires a lot of data but can be changed to 5m with parameter re-optimization.

---

## Strategy 4: Supertrend (Triple Confirmation)

**Source:** https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/Supertrend.py
**Author:** Official Freqtrade strategies repo
**Timeframe:** 1h
**Stoploss:** -26.5% (with trailing stop)
**ROI:** 8.7% initial, decaying over time

### What makes it good
- Uses THREE Supertrend indicators with different multiplier/period settings
- All three must agree for entry/exit = high-confidence signals
- 1h timeframe = less noise, lower trading frequency, lower fees
- Hyperopt-optimized parameters included
- Trailing stop at 5% after 14.4% offset reached
- Clean INTERFACE_VERSION 3 implementation
- Built-in Supertrend calculation (no external dependency)

### Indicators
- 3x Supertrend (with different multiplier/period combinations)
- ATR-based trend detection
- Volume filter

### Full Source Code

```python
import logging
from numpy.lib import math
from freqtrade.strategy import IStrategy, IntParameter
from pandas import DataFrame
import talib.abstract as ta
import numpy as np
import pandas as pd

class Supertrend(IStrategy):
    INTERFACE_VERSION: int = 3

    buy_params = {
        "buy_m1": 4, "buy_m2": 7, "buy_m3": 1,
        "buy_p1": 8, "buy_p2": 9, "buy_p3": 8,
    }
    sell_params = {
        "sell_m1": 1, "sell_m2": 3, "sell_m3": 6,
        "sell_p1": 16, "sell_p2": 18, "sell_p3": 18,
    }

    minimal_roi = {
        "0": 0.087, "372": 0.058, "861": 0.029, "2221": 0
    }

    stoploss = -0.265
    trailing_stop = True
    trailing_stop_positive = 0.05
    trailing_stop_positive_offset = 0.144
    trailing_only_offset_is_reached = False
    timeframe = '1h'
    startup_candle_count = 199

    buy_m1 = IntParameter(1, 7, default=4)
    buy_m2 = IntParameter(1, 7, default=4)
    buy_m3 = IntParameter(1, 7, default=4)
    buy_p1 = IntParameter(7, 21, default=14)
    buy_p2 = IntParameter(7, 21, default=14)
    buy_p3 = IntParameter(7, 21, default=14)
    sell_m1 = IntParameter(1, 7, default=4)
    sell_m2 = IntParameter(1, 7, default=4)
    sell_m3 = IntParameter(1, 7, default=4)
    sell_p1 = IntParameter(7, 21, default=14)
    sell_p2 = IntParameter(7, 21, default=14)
    sell_p3 = IntParameter(7, 21, default=14)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        new_cols = []
        for multiplier in self.buy_m1.range:
            for period in self.buy_p1.range:
                st = self.supertrend(dataframe, multiplier, period)[['STX']].rename(
                    columns={'STX': f'supertrend_1_buy_{multiplier}_{period}'})
                new_cols.append(st)
        for multiplier in self.buy_m2.range:
            for period in self.buy_p2.range:
                st = self.supertrend(dataframe, multiplier, period)[['STX']].rename(
                    columns={'STX': f'supertrend_2_buy_{multiplier}_{period}'})
                new_cols.append(st)
        for multiplier in self.buy_m3.range:
            for period in self.buy_p3.range:
                st = self.supertrend(dataframe, multiplier, period)[['STX']].rename(
                    columns={'STX': f'supertrend_3_buy_{multiplier}_{period}'})
                new_cols.append(st)
        for multiplier in self.sell_m1.range:
            for period in self.sell_p1.range:
                st = self.supertrend(dataframe, multiplier, period)[['STX']].rename(
                    columns={'STX': f'supertrend_1_sell_{multiplier}_{period}'})
                new_cols.append(st)
        for multiplier in self.sell_m2.range:
            for period in self.sell_p2.range:
                st = self.supertrend(dataframe, multiplier, period)[['STX']].rename(
                    columns={'STX': f'supertrend_2_sell_{multiplier}_{period}'})
                new_cols.append(st)
        for multiplier in self.sell_m3.range:
            for period in self.sell_p3.range:
                st = self.supertrend(dataframe, multiplier, period)[['STX']].rename(
                    columns={'STX': f'supertrend_3_sell_{multiplier}_{period}'})
                new_cols.append(st)
        if new_cols:
            dataframe = pd.concat([dataframe] + new_cols, axis=1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
               (dataframe[f'supertrend_1_buy_{self.buy_m1.value}_{self.buy_p1.value}'] == 'up') &
               (dataframe[f'supertrend_2_buy_{self.buy_m2.value}_{self.buy_p2.value}'] == 'up') &
               (dataframe[f'supertrend_3_buy_{self.buy_m3.value}_{self.buy_p3.value}'] == 'up') &
               (dataframe['volume'] > 0)
            ),
            'enter_long'] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
               (dataframe[f'supertrend_1_sell_{self.sell_m1.value}_{self.sell_p1.value}'] == 'down') &
               (dataframe[f'supertrend_2_sell_{self.sell_m2.value}_{self.sell_p2.value}'] == 'down') &
               (dataframe[f'supertrend_3_sell_{self.sell_m3.value}_{self.sell_p3.value}'] == 'down') &
               (dataframe['volume'] > 0)
            ),
            'exit_long'] = 1
        return dataframe

    def supertrend(self, dataframe: pd.DataFrame, multiplier, period):
        df = dataframe.copy()
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        length = len(df)

        tr = ta.TRANGE(df['high'], df['low'], df['close'])
        atr = pd.Series(tr).rolling(period).mean().to_numpy()

        basic_ub = (high + low) / 2 + multiplier * atr
        basic_lb = (high + low) / 2 - multiplier * atr

        final_ub = np.zeros(length)
        final_lb = np.zeros(length)
        for i in range(period, length):
            final_ub[i] = basic_ub[i] if basic_ub[i] < final_ub[i-1] or close[i-1] > final_ub[i-1] else final_ub[i-1]
            final_lb[i] = basic_lb[i] if basic_lb[i] > final_lb[i-1] or close[i-1] < final_lb[i-1] else final_lb[i-1]

        st = np.zeros(length)
        for i in range(period, length):
            if st[i-1] == final_ub[i-1]:
                st[i] = final_ub[i] if close[i] <= final_ub[i] else final_lb[i]
            elif st[i-1] == final_lb[i-1]:
                st[i] = final_lb[i] if close[i] >= final_lb[i] else final_ub[i]

        stx = np.where(st > 0, np.where(close < st, 'down', 'up'), None)
        result = pd.DataFrame({'ST': st, 'STX': stx}, index=df.index)
        result.fillna(0, inplace=True)
        return result
```

### Binance Spot Suitability
Very good. 1h timeframe means lower trading frequency and fewer fees. The triple-confirmation approach reduces false signals significantly. Self-contained Supertrend calculation with no external library dependencies.

---

## Strategy 5: DoubleEMACrossoverWithTrend

**Source:** https://github.com/paulcpk/freqtrade-strategies-that-work/blob/main/DoubleEMACrossoverWithTrend.py
**Author:** Paul Csapak
**Timeframe:** 1h
**Stoploss:** -20%
**Reported Performance:** 122.50% total profit over 2 years (2018-2020), 655 trades, 0.56% avg profit

### What makes it good
- Simple and robust - hard to overfit
- Classic EMA crossover (9/21) with trend filter (EMA 200)
- 1h timeframe reduces noise
- Trailing stop for profit protection
- Strong backtest results over 2-year period across 8 pairs
- Easy to understand, modify, and extend

### Indicators
- EMA 9 (fast)
- EMA 21 (slow)
- EMA 200 (trend filter)

### Full Source Code

```python
from freqtrade.strategy import IStrategy, merge_informative_pair
from pandas import DataFrame
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy


class DoubleEMACrossoverWithTrend(IStrategy):
    """
    DoubleEMACrossoverWithTrend
    author@: Paul Csapak
    github@: https://github.com/paulcpk/freqtrade-strategies-that-work
    """

    stoploss = -0.2
    timeframe = '1h'
    trailing_stop = False
    trailing_stop_positive = 0.03
    trailing_stop_positive_offset = 0.04

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['ema9'] = ta.EMA(dataframe, timeperiod=9)
        dataframe['ema21'] = ta.EMA(dataframe, timeperiod=21)
        dataframe['ema200'] = ta.EMA(dataframe, timeperiod=200)
        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (qtpylib.crossed_above(dataframe['ema9'], dataframe['ema21'])) &
                (dataframe['low'] > dataframe['ema200']) &
                (dataframe['volume'] > 0)
            ),
            'buy'] = 1
        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (qtpylib.crossed_below(dataframe['ema9'], dataframe['ema21'])) |
                (dataframe['low'] < dataframe['ema200'])
            ),
            'sell'] = 1
        return dataframe
```

### Binance Spot Suitability
Excellent. The simplest strategy here but also one of the most robust. Works on any Binance USDT pair. The EMA 200 trend filter ensures you only buy in uptrends, which is critical for spot trading.

---

## Strategy 6 (Bonus): ElliotV5

**Source:** https://github.com/5drei1/freqtrade_pub_strats/blob/main/ElliotV5.py
**Timeframe:** 5m
**Stoploss:** -18.9%
**Ninja Score:** 62 (ranked #4 on strat.ninja)

### What makes it good
- Uses Elliott Wave Oscillator (EWO) with SMA offset bands
- Two entry conditions: bullish EWO momentum and bearish EWO reversal
- Hyperopt-ready with all parameters exposed
- Trailing stop at 0.5% after 3% offset
- Tight ROI table with gradual profit-taking

### Indicators
- EMA (multiple periods for buy/sell MA bands)
- Elliott Wave Oscillator (EMA 50 vs EMA 200)
- RSI 14

### Full Source Code

```python
from freqtrade.strategy.interface import IStrategy
from typing import Dict, List
from functools import reduce
from pandas import DataFrame
import talib.abstract as ta
import numpy as np
import freqtrade.vendor.qtpylib.indicators as qtpylib
import datetime
from technical.util import resample_to_interval, resampled_merge
from datetime import datetime, timedelta
from freqtrade.persistence import Trade
from freqtrade.strategy import stoploss_from_open, merge_informative_pair, DecimalParameter, IntParameter, CategoricalParameter
import technical.indicators as ftt

buy_params = {
    "base_nb_candles_buy": 17,
    "ewo_high": 3.34,
    "ewo_low": -17.457,
    "low_offset": 0.978,
    "rsi_buy": 60
}

sell_params = {
    "base_nb_candles_sell": 39,
    "high_offset": 1.011
}

def EWO(dataframe, ema_length=5, ema2_length=35):
    df = dataframe.copy()
    ema1 = ta.EMA(df, timeperiod=ema_length)
    ema2 = ta.EMA(df, timeperiod=ema2_length)
    emadif = (ema1 - ema2) / df['close'] * 100
    return emadif


class ElliotV5(IStrategy):
    INTERFACE_VERSION = 2

    minimal_roi = {
        "0": 0.215, "40": 0.132, "87": 0.086, "201": 0.03
    }

    stoploss = -0.189

    base_nb_candles_buy = IntParameter(
        5, 80, default=buy_params['base_nb_candles_buy'], space='buy', optimize=True)
    base_nb_candles_sell = IntParameter(
        5, 80, default=sell_params['base_nb_candles_sell'], space='sell', optimize=True)
    low_offset = DecimalParameter(
        0.9, 0.99, default=buy_params['low_offset'], space='buy', optimize=True)
    high_offset = DecimalParameter(
        0.99, 1.1, default=sell_params['high_offset'], space='sell', optimize=True)

    fast_ewo = 50
    slow_ewo = 200
    ewo_low = DecimalParameter(-20.0, -8.0,
                               default=buy_params['ewo_low'], space='buy', optimize=True)
    ewo_high = DecimalParameter(
        2.0, 12.0, default=buy_params['ewo_high'], space='buy', optimize=True)
    rsi_buy = IntParameter(30, 70, default=buy_params['rsi_buy'], space='buy', optimize=True)

    trailing_stop = True
    trailing_stop_positive = 0.005
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    use_sell_signal = True
    sell_profit_only = False
    sell_profit_offset = 0.01
    ignore_roi_if_buy_signal = True

    order_time_in_force = {
        'buy': 'gtc',
        'sell': 'ioc'
    }

    timeframe = '5m'
    informative_timeframe = '1h'
    process_only_new_candles = True
    startup_candle_count = 79
    use_custom_stoploss = False

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        informative_pairs = [(pair, self.informative_timeframe) for pair in pairs]
        return informative_pairs

    def get_informative_indicators(self, metadata: dict):
        dataframe = self.dp.get_pair_dataframe(
            pair=metadata['pair'], timeframe=self.informative_timeframe)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        for val in self.base_nb_candles_buy.range:
            dataframe[f'ma_buy_{val}'] = ta.EMA(dataframe, timeperiod=val)
        for val in self.base_nb_candles_sell.range:
            dataframe[f'ma_sell_{val}'] = ta.EMA(dataframe, timeperiod=val)
        dataframe['EWO'] = EWO(dataframe, self.fast_ewo, self.slow_ewo)
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []
        conditions.append(
            (
                (dataframe['close'] < (dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] * self.low_offset.value)) &
                (dataframe['EWO'] > self.ewo_high.value) &
                (dataframe['rsi'] < self.rsi_buy.value) &
                (dataframe['volume'] > 0)
            )
        )
        conditions.append(
            (
                (dataframe['close'] < (dataframe[f'ma_buy_{self.base_nb_candles_buy.value}'] * self.low_offset.value)) &
                (dataframe['EWO'] < self.ewo_low.value) &
                (dataframe['volume'] > 0)
            )
        )
        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x | y, conditions),
                'buy'
            ]=1
        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []
        conditions.append(
            (
                (dataframe['close'] > (dataframe[f'ma_sell_{self.base_nb_candles_sell.value}'] * self.high_offset.value)) &
                (dataframe['volume'] > 0)
            )
        )
        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x | y, conditions),
                'sell'
            ]=1
        return dataframe
```

### Binance Spot Suitability
Good. Fully hyperopt-ready with exposed parameters. The dual-condition buy (bullish momentum + bearish reversal) gives it flexibility across market conditions.

---

## NostalgiaForInfinity (Reference - NOT included as code)

**Source:** https://github.com/iterativv/NostalgiaForInfinity
**Stars:** 2,900+ (most starred Freqtrade strategy)
**License:** GPL-3.0
**Last Update:** February 2026 (v17.3.920)
**Timeframe:** 5m (requires 5m, 15m, 1h, 1d data)

NostalgiaForInfinity (NFIX) is the most popular Freqtrade strategy, but its code is extremely complex (thousands of lines with hundreds of buy/sell conditions). It is NOT included here because:
1. The file is too large to be practically useful as a starting point
2. It is heavily optimized and frequently updated - use the live repo directly
3. It requires 4 timeframes of data to backtest

**Recommendation:** Clone the repo directly and use as-is:
```bash
git clone https://github.com/iterativv/NostalgiaForInfinity.git
```

---

## Comparison Summary

| Strategy | TF | Complexity | Drawdown | Best For | API Version |
|----------|-----|-----------|----------|----------|-------------|
| NASOSv5 | 5m | High | ~6% | Active trading, multiple conditions | v2 |
| CombinedBinHAndCluc | 5m | Low | ~5% | Conservative dip buying | v3 |
| ClucHAnix | 1m | Medium | Variable | Scalping with HA smoothing | v2 |
| Supertrend | 1h | Medium | ~14% | Trend following, less trades | v3 |
| DoubleEMACrossoverWithTrend | 1h | Very Low | ~20% | Simple trend following | v2 |
| ElliotV5 | 5m | Medium | ~10% | EWO momentum/reversal | v2 |

---

## Recommendations for Backtesting

1. **Start with CombinedBinHAndCluc** - simplest, modern API (v3), tight risk management
2. **Then NASOSv5** - community proven, sophisticated custom stoploss
3. **Then Supertrend** - 1h timeframe, fewer trades, good for comparison
4. **Use hyperopt** to re-optimize parameters for current market conditions
5. **Download sufficient data:** `freqtrade download-data --timeframes 5m 15m 1h 1d --timerange=20240101-`

### Note on INTERFACE_VERSION
- Strategies using `populate_buy_trend`/`populate_sell_trend` (v2) need updating to `populate_entry_trend`/`populate_exit_trend` for Freqtrade 2024+
- CombinedBinHAndCluc and Supertrend already use v3 API
- For v2 strategies, change `buy` -> `enter_long` and `sell` -> `exit_long`

---

## Sources

- [Freqtrade Official Strategies](https://github.com/freqtrade/freqtrade-strategies)
- [NostalgiaForInfinity](https://github.com/iterativv/NostalgiaForInfinity)
- [Freqtrade Strategies That Work](https://github.com/paulcpk/freqtrade-strategies-that-work)
- [5drei1 Public Strategies](https://github.com/5drei1/freqtrade_pub_strats)
- [phuchust Strategy Collection](https://github.com/phuchust/freqtrade_strategy)
- [Strat.Ninja Rankings](https://strat.ninja/ranking.php)
- [FreqST Strategy Database](https://freqst.com/)
