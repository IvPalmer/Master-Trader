"""
MasterTrader V1 - EMA Crossover + RSI Filter
Simple trend-following strategy for dry-run validation.

Entry: Fast EMA crosses above slow EMA, RSI confirms (not overbought)
Exit: Fast EMA crosses below slow EMA, or RSI overbought, or stoploss/ROI
"""

from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter
from pandas import DataFrame
import talib.abstract as ta


class MasterTraderV1(IStrategy):

    INTERFACE_VERSION = 3

    # Timeframe
    timeframe = "1h"

    # ROI table - take profit at these levels
    minimal_roi = {
        "0": 0.05,      # 5% profit immediately
        "30": 0.03,     # 3% after 30 min
        "60": 0.02,     # 2% after 1h
        "120": 0.01,    # 1% after 2h
    }

    # Stoploss
    stoploss = -0.15  # 15% — evidence: 5% < 1 daily SD for alts, causes whipsaws on 1h

    # Trailing stop
    trailing_stop = True
    trailing_stop_positive = 0.01       # Activate trailing at 1% profit
    trailing_stop_positive_offset = 0.02  # Start trailing at 2% profit
    trailing_only_offset_is_reached = True

    # Run on new candles only
    process_only_new_candles = True

    # Use exit signal
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # Number of candles needed before producing valid signals
    startup_candle_count: int = 50

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {"method": "StoplossGuard", "lookback_period_candles": 48, "trade_limit": 2, "stop_duration_candles": 24, "only_per_pair": False},
            {"method": "LowProfitPairs", "lookback_period_candles": 288, "trade_limit": 4, "stop_duration_candles": 48, "required_profit": -0.05},
            {"method": "MaxDrawdown", "lookback_period_candles": 48, "max_allowed_drawdown": 0.20, "stop_duration_candles": 12, "trade_limit": 1},
        ]

    # Hyperoptable parameters
    ema_fast = IntParameter(5, 25, default=9, space="buy", optimize=True)
    ema_slow = IntParameter(20, 60, default=21, space="buy", optimize=True)
    rsi_period = IntParameter(10, 25, default=14, space="buy", optimize=True)
    rsi_buy_limit = IntParameter(20, 45, default=35, space="buy", optimize=True)
    rsi_sell_limit = IntParameter(65, 85, default=75, space="sell", optimize=True)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # EMAs
        for val in range(5, 61):
            dataframe[f"ema_{val}"] = ta.EMA(dataframe, timeperiod=val)

        # RSI
        for val in range(10, 26):
            dataframe[f"rsi_{val}"] = ta.RSI(dataframe, timeperiod=val)

        # Volume SMA for volume filter
        dataframe["volume_sma_20"] = ta.SMA(dataframe["volume"], timeperiod=20)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ema_f = f"ema_{self.ema_fast.value}"
        ema_s = f"ema_{self.ema_slow.value}"
        rsi_col = f"rsi_{self.rsi_period.value}"

        dataframe.loc[
            (
                # EMA crossover (fast crosses above slow)
                (dataframe[ema_f] > dataframe[ema_s])
                & (dataframe[ema_f].shift(1) <= dataframe[ema_s].shift(1))
                # RSI not overbought and above minimum
                & (dataframe[rsi_col] > self.rsi_buy_limit.value)
                & (dataframe[rsi_col] < 70)
                # Volume above average
                & (dataframe["volume"] > dataframe["volume_sma_20"])
                # Non-zero volume
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ema_f = f"ema_{self.ema_fast.value}"
        ema_s = f"ema_{self.ema_slow.value}"
        rsi_col = f"rsi_{self.rsi_period.value}"

        dataframe.loc[
            (
                # EMA crossunder (fast crosses below slow)
                (
                    (dataframe[ema_f] < dataframe[ema_s])
                    & (dataframe[ema_f].shift(1) >= dataframe[ema_s].shift(1))
                )
                # OR RSI overbought
                | (dataframe[rsi_col] > self.rsi_sell_limit.value)
            )
            & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1

        return dataframe
