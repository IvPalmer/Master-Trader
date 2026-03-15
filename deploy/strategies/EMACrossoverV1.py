import logging
from freqtrade.strategy import IStrategy
from pandas import DataFrame
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib

logger = logging.getLogger(__name__)


class EMACrossoverV1(IStrategy):
    """
    EMA crossover with dual-EMA confirmation, RSI filter, and volume confirmation.

    Entry: Price crosses above EMA200 AND EMA50 > EMA200 (golden cross confirmed)
           AND RSI(14) between 40-70 AND volume > SMA(volume, 20) AND ADX > 25
    Exit:  Price crosses below EMA200 - 2.5% threshold (trend ended, with buffer)

    Changes from original:
    - EMA800 → EMA200 (startup 820 → 220 candles, ~9 days vs ~34 days)
    - Added EMA50 for golden cross confirmation (reduces false entries)
    - Added RSI 40-70 filter (avoids overbought entries and weak momentum)
    - Added volume > SMA(vol,20) confirmation (ensures conviction behind moves)
    - Exit threshold widened from 1% to 2.5% (less whipsaw in crypto volatility)
    - ADX filter raised from 20 to 25 (stronger trend requirement)
    """
    INTERFACE_VERSION: int = 3

    timeframe = '1h'
    startup_candle_count = 220  # EMA200 + buffer

    minimal_roi = {
        "0": 0.05, "360": 0.03, "720": 0.02, "1440": 0.01
    }

    stoploss = -0.05  # Data: 0% of trades recover past -7%, 92% of winners never dip past -3%
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
        # Dual EMA system
        dataframe['ema200'] = ta.EMA(dataframe, timeperiod=200)
        dataframe['ema50'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['ema_threshold'] = dataframe['ema200'] * 0.975  # 2.5% below EMA200

        # RSI momentum filter
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)

        # ADX regime filter — only enter in trending markets
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)

        # Volume confirmation
        dataframe['volume_sma'] = dataframe['volume'].rolling(20).mean()

        # Volatility filter
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)
        dataframe['atr_sma'] = dataframe['atr'].rolling(50).mean()
        dataframe['volatile'] = (dataframe['atr'] > 2.0 * dataframe['atr_sma']).astype(int)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (qtpylib.crossed_above(dataframe['close'], dataframe['ema200'])) &
                (dataframe['ema50'] > dataframe['ema200']) &  # Golden cross confirmed
                (dataframe['rsi'] > 40) &                     # Not too weak
                (dataframe['rsi'] < 70) &                     # Not overbought
                (dataframe['adx'] > 25) &                     # Strong trend required
                (dataframe['volume'] > dataframe['volume_sma']) &  # Volume confirmation
                (dataframe['volatile'] == 0) &                # Not extreme volatility
                (dataframe['volume'] > 0)
            ),
            'enter_long'] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (qtpylib.crossed_below(dataframe['close'], dataframe['ema_threshold']))
            ) &
            (dataframe['volume'] > 0),
            'exit_long'] = 1
        return dataframe
