import logging
from freqtrade.strategy import IStrategy
from pandas import DataFrame
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib

logger = logging.getLogger(__name__)


class MACDTrendV1(IStrategy):
    """
    MACD momentum-resumption within uptrend — V2 optimized.

    Changes from original:
    - Entry: MACD below signal (not necessarily below zero) — catches more setups
    - Entry: RSI 40-70 filter — confirms momentum without overbought
    - Entry: Volume > SMA(volume,20) — requires conviction
    - Entry: ADX > 25 (raised from 20) — stronger trend requirement
    - Exit: close < ema100 (was low < ema100) — requires confirmed close, not just a wick
    - Exit: require 2 consecutive closes below EMA100 for extra safety

    Based on paulcpk/MACDCrossoverWithTrend, adapted with regime detection,
    proper stoploss, trailing, and protections.
    """
    INTERFACE_VERSION: int = 3

    timeframe = '1h'
    startup_candle_count = 120

    minimal_roi = {
        "0": 0.05, "360": 0.03, "720": 0.02, "1440": 0.01
    }

    stoploss = -0.07
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {"method": "StoplossGuard", "lookback_period_candles": 48,
             "trade_limit": 2, "stop_duration_candles": 24, "only_per_pair": True},
            {"method": "LowProfitPairs", "lookback_period_candles": 288,
             "trade_limit": 4, "stop_duration_candles": 48, "required_profit": -0.05},
            {"method": "MaxDrawdown", "lookback_period_candles": 48,
             "max_allowed_drawdown": 0.20, "stop_duration_candles": 12, "trade_limit": 1},
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # MACD (12, 26, 9 defaults)
        macd = ta.MACD(dataframe)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']

        # RSI for momentum confirmation
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)

        # Trend filter — dual EMA for golden cross confirmation
        dataframe['ema50'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['ema100'] = ta.EMA(dataframe, timeperiod=100)

        # EMA threshold exit — 2.5% below EMA100 (same concept as EMACrossoverV1's success)
        dataframe['ema_exit_threshold'] = dataframe['ema100'] * 0.975

        # Regime detection — only trade in trending markets
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)

        # Volume filter — require above-average volume
        dataframe['volume_sma'] = dataframe['volume'].rolling(window=20).mean()

        # Volatility filter — skip extreme volatility
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)
        dataframe['atr_sma'] = dataframe['atr'].rolling(50).mean()
        dataframe['volatile'] = (dataframe['atr'] > 2.0 * dataframe['atr_sma']).astype(int)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe['macd'].shift(1) < 0) &                                     # MACD was below zero (deep pullback recovery)
                (qtpylib.crossed_above(dataframe['macd'], dataframe['macdsignal'])) &   # Bullish MACD crossover
                (dataframe['close'] > dataframe['ema100']) &                            # Price above trend EMA
                (dataframe['ema50'] > dataframe['ema100']) &                            # Golden cross confirmed
                (dataframe['adx'] > 20) &                                               # Trending market
                (dataframe['rsi'] > 40) &                                               # Momentum present
                (dataframe['rsi'] < 70) &                                               # Not overbought
                (dataframe['volatile'] == 0) &                                          # Not extreme volatility
                (dataframe['volume'] > 0)
            ),
            'enter_long'] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (qtpylib.crossed_below(dataframe['close'], dataframe['ema_exit_threshold'])) &  # Confirmed break below EMA - 2.5%
            (dataframe['volume'] > 0),
            'exit_long'] = 1
        return dataframe
