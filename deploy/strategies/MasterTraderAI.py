"""
MasterTrader AI - FreqAI Adaptive Trading Strategy
LightGBM regression with regime detection for spot crypto trading.

Uses FreqAI to predict mean price change over the next N candles,
combined with ATR/ADX regime filters to avoid unfavorable conditions.

Designed for Freqtrade 2026.2 with FreqAI enabled.
"""

from freqtrade.strategy import IStrategy, DecimalParameter
from pandas import DataFrame
import talib.abstract as ta
import numpy as np


class MasterTraderAI(IStrategy):

    INTERFACE_VERSION = 3

    # --- Timeframe & general settings ---
    timeframe = "5m"
    can_short = False
    process_only_new_candles = True
    use_exit_signal = True
    startup_candle_count = 100

    # --- ROI table (conservative) ---
    minimal_roi = {
        "0": 0.03,
        "30": 0.02,
        "60": 0.01,
        "120": 0.005,
    }

    # --- Stoploss ---
    stoploss = -0.10  # Widened from -0.05: FreqAI adapts, but 5% too tight for alt volatility

    # --- Trailing stop ---
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 5},
            {"method": "StoplossGuard", "lookback_period_candles": 48, "trade_limit": 4, "stop_duration_candles": 12, "only_per_pair": False},
            {"method": "LowProfitPairs", "lookback_period_candles": 288, "trade_limit": 4, "stop_duration_candles": 48, "required_profit": -0.05},
            {"method": "MaxDrawdown", "lookback_period_candles": 576, "max_allowed_drawdown": 0.10, "stop_duration_candles": 288, "trade_limit": 1},
        ]

    # --- Max open trades ---
    max_open_trades = 5

    # --- FreqAI signal thresholds (hyperoptable) ---
    entry_threshold = DecimalParameter(
        0.0005, 0.01, default=0.003, decimals=4, space="buy", optimize=True
    )
    exit_threshold = DecimalParameter(
        -0.01, 0.0, default=-0.001, decimals=4, space="sell", optimize=True
    )

    # ------------------------------------------------------------------ #
    #                       FreqAI Feature Engineering                     #
    # ------------------------------------------------------------------ #

    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs
    ) -> DataFrame:
        """
        Features expanded across ALL config dimensions:
        timeframes, indicator_periods_candles, corr pairs, shifted candles.

        The `-period` suffix is auto-replaced with each value from
        indicator_periods_candles in the FreqAI config.
        """
        # Momentum / trend strength
        dataframe["%-rsi-period"] = ta.RSI(dataframe, timeperiod=period)
        dataframe["%-mfi-period"] = ta.MFI(dataframe, timeperiod=period)
        dataframe["%-adx-period"] = ta.ADX(dataframe, timeperiod=period)

        # Trend direction
        dataframe["%-sma-period"] = ta.SMA(dataframe, timeperiod=period)
        dataframe["%-ema-period"] = ta.EMA(dataframe, timeperiod=period)

        # Rate of change
        dataframe["%-roc-period"] = ta.ROC(dataframe, timeperiod=period)

        # Volatility - Bollinger Band width
        bollinger = ta.BBANDS(dataframe, timeperiod=period, nbdevup=2.0, nbdevdn=2.0)
        dataframe["%-bb_width-period"] = (
            (bollinger["upperband"] - bollinger["lowerband"])
            / bollinger["middleband"]
        )

        # Relative volume
        dataframe["%-relative_volume-period"] = (
            dataframe["volume"]
            / dataframe["volume"].rolling(window=period).mean()
        )

        return dataframe

    def feature_engineering_expand_basic(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        """
        Features expanded across timeframes, corr pairs, and shifted candles,
        but NOT across indicator_periods_candles.
        """
        dataframe["%-pct-change"] = dataframe["close"].pct_change()
        dataframe["%-raw_volume"] = dataframe["volume"]

        return dataframe

    def feature_engineering_standard(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        """
        Standard features with no expansion -- base timeframe only.
        Calendar features to capture intraday/weekly seasonality.
        """
        dataframe["%-day_of_week"] = dataframe["date"].dt.dayofweek / 6.0
        dataframe["%-hour_of_day"] = dataframe["date"].dt.hour / 23.0

        return dataframe

    # ------------------------------------------------------------------ #
    #                          FreqAI Targets                              #
    # ------------------------------------------------------------------ #

    def set_freqai_targets(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        """
        Target: mean percentage price change over the next
        `label_period_candles` candles.
        """
        label_period = self.freqai_info["feature_parameters"]["label_period_candles"]

        dataframe["&-s_close"] = (
            dataframe["close"]
            .shift(-label_period)
            .rolling(window=label_period)
            .mean()
            / dataframe["close"]
            - 1
        )

        return dataframe

    # ------------------------------------------------------------------ #
    #                        Indicator Population                          #
    # ------------------------------------------------------------------ #

    def populate_indicators(
        self, dataframe: DataFrame, metadata: dict
    ) -> DataFrame:
        """
        Trigger FreqAI training/prediction, then add regime-detection
        indicators that the strategy (not the model) uses for filtering.
        """
        # --- FreqAI: train models & generate predictions ---
        dataframe = self.freqai.start(dataframe, metadata, self)

        # --- Regime detection (used in entry/exit filters, NOT as ML features) ---

        # ATR regime: detect volatility spikes / crash conditions
        dataframe["atr"] = ta.ATR(
            dataframe, timeperiod=14
        )
        dataframe["atr_sma"] = (
            dataframe["atr"].rolling(window=50).mean()
        )

        # ADX: trend strength (trending vs ranging market)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

        return dataframe

    # ------------------------------------------------------------------ #
    #                          Entry Signal                                #
    # ------------------------------------------------------------------ #

    def populate_entry_trend(
        self, dataframe: DataFrame, metadata: dict
    ) -> DataFrame:
        """
        Enter long when:
        1. FreqAI predicts upside above threshold
        2. FreqAI model is confident (do_predict == 1)
        3. Market is not in a crash regime (ATR < 2x its SMA)
        4. Some directional trend exists (ADX > 20)
        5. Volume is non-zero
        """
        dataframe.loc[
            (
                (dataframe["&-s_close"] > self.entry_threshold.value)
                & (dataframe["do_predict"] == 1)
                & (dataframe["atr"] < 2.0 * dataframe["atr_sma"])
                & (dataframe["adx"] > 20)
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1

        return dataframe

    # ------------------------------------------------------------------ #
    #                           Exit Signal                                #
    # ------------------------------------------------------------------ #

    def populate_exit_trend(
        self, dataframe: DataFrame, metadata: dict
    ) -> DataFrame:
        """
        Exit long when:
        - FreqAI predicts downside below threshold
        - OR a volatility spike occurs (ATR > 2.5x its SMA)
        Always require non-zero volume.
        """
        dataframe.loc[
            (
                (dataframe["&-s_close"] < self.exit_threshold.value)
                | (dataframe["atr"] > 2.5 * dataframe["atr_sma"])
            )
            & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1

        return dataframe
