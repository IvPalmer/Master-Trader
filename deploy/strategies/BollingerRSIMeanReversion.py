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

    minimal_roi = {
        "0": 0.04,
        "30": 0.025,
        "60": 0.015,
        "120": 0.005
    }

    stoploss = -0.06
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True

    timeframe = '15m'
    process_only_new_candles = True
    startup_candle_count = 50

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 3},
            {"method": "StoplossGuard", "lookback_period_candles": 48, "trade_limit": 3, "stop_duration_candles": 24, "only_per_pair": True},
            {"method": "LowProfitPairs", "lookback_period_candles": 144, "trade_limit": 2, "stop_duration_candles": 48, "required_profit": -0.02},
            {"method": "MaxDrawdown", "lookback_period_candles": 288, "max_allowed_drawdown": 0.20, "stop_duration_candles": 48, "trade_limit": 1},
        ]

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

        # Regime detection
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
        dataframe['regime_atr_14'] = ta.ATR(dataframe, timeperiod=14)
        dataframe['regime_atr_sma_50'] = dataframe['regime_atr_14'].rolling(50).mean()
        dataframe['regime_volatile'] = (dataframe['regime_atr_14'] > 2.0 * dataframe['regime_atr_sma_50']).astype(int)

        # Volume SMA
        dataframe['volume_sma'] = ta.SMA(dataframe['volume'], timeperiod=20)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe['close'] < dataframe['bb_lowerband']) &
                (dataframe['rsi'] < 30) &
                (dataframe['adx'] < 30) &  # Only ranging markets
                (dataframe['regime_volatile'] == 0) &  # No high volatility
                (dataframe['bb_width'] > 0.02) &  # Avoid low-vol squeezes
                (dataframe['volume'] > dataframe['volume_sma']) &
                (dataframe['volume'] > 0)
            ),
            'enter_long'] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe['close'] > dataframe['bb_middleband']) |
                (dataframe['rsi'] > 65)
            ) |
            (dataframe['regime_atr_14'] > 2.5 * dataframe['regime_atr_sma_50']),  # Exit on volatility spike
            'exit_long'] = 1
        return dataframe
