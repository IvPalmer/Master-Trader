"""
GaussianChannel V1 - Trend-Following on Daily Timeframe
========================================================

Based on Michael Ionita's Gaussian Channel strategy.
Backtest: +1,895% since 2018, PF 3.2, 30% max DD on daily BTC.
Live 10-month: +51.7%, 8.57% max DD, 44% win rate.

Logic:
  - Buy when close > upper Gaussian channel band
  - Sell when close < upper Gaussian channel band
  - Daily timeframe, signal-based exits
  - Long-only, one trade at a time

The Gaussian Channel is implemented as a smoothed midline with upper/lower
bands based on a true range filter. Uses a multi-pole Gaussian filter
(Ehlers-style) for smoother trend detection.
"""

import logging
from datetime import datetime

import numpy as np
import talib.abstract as ta
from freqtrade.strategy import IStrategy, informative
from pandas import DataFrame

from market_intelligence import FearGreedIndex, PositionTracker, MAX_BOTS_PER_PAIR

logger = logging.getLogger(__name__)


def gaussian_filter(series, poles: int = 4, sampling_period: int = 144):
    """
    Multi-pole Gaussian filter (Ehlers-style).
    Attempt to replicate TradingView's Gaussian Channel indicator logic.
    """
    import math

    beta = (1.0 - math.cos(2.0 * math.pi / sampling_period)) / (
        math.pow(2.0, 1.0 / poles) - 1.0
    )
    alpha = -beta + math.sqrt(beta * beta + 2.0 * beta)

    result = series.copy().astype(float)
    vals = result.values.copy()

    # Apply the filter poles times for smoother result
    for _ in range(poles):
        filtered = np.full_like(vals, np.nan)
        filtered[0] = vals[0] if not np.isnan(vals[0]) else 0.0
        for i in range(1, len(vals)):
            if np.isnan(vals[i]):
                filtered[i] = filtered[i - 1]
            else:
                prev = filtered[i - 1] if not np.isnan(filtered[i - 1]) else vals[i]
                filtered[i] = alpha * vals[i] + (1.0 - alpha) * prev
        vals = filtered.copy()

    return vals


class GaussianChannelV1(IStrategy):

    INTERFACE_VERSION = 3

    timeframe = "1d"

    # Wide ROI — trend-following should let winners run
    minimal_roi = {
        "0": 0.50,       # 50% — very wide, let trends play out
        "30": 0.30,      # 30% after 30 days
        "60": 0.15,      # 15% after 60 days
        "90": 0.05,      # 5% after 90 days
    }

    # No tight stoploss — exits are signal-based (close < upper band)
    # Use a wide safety net stoploss only for catastrophic moves
    stoploss = -0.15

    # Trailing stop to protect large gains
    trailing_stop = True
    trailing_stop_positive = 0.03     # Trail by 3%
    trailing_stop_positive_offset = 0.08  # Start trailing at +8%
    trailing_only_offset_is_reached = True

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = True  # Don't exit if signal says hold

    startup_candle_count: int = 300  # Need enough data for Gaussian filter warmup

    # Gaussian Channel parameters
    # Daily (default): close, poles=4, sampling=144, multiplier=1.0
    # 4H variant: HL2, poles=4, sampling=144, multiplier=2.0
    GAUSSIAN_POLES = 4
    GAUSSIAN_SAMPLING = 144
    FILTER_MULTIPLIER = 1.0

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 1},
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 60,
                "max_allowed_drawdown": 0.25,
                "stop_duration_candles": 10,
                "trade_limit": 1,
            },
        ]

    # ── BTC Market Guard ────────────────────────────────────────────

    @informative('1d', 'BTC/{stake}')
    def populate_indicators_btc_1d(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['sma200'] = ta.SMA(dataframe['close'], timeperiod=200)
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Gaussian filter on close price
        src = dataframe['close'].copy()
        filtered = gaussian_filter(src, poles=self.GAUSSIAN_POLES,
                                   sampling_period=self.GAUSSIAN_SAMPLING)
        dataframe['gaussian_mid'] = filtered

        # True Range filter for channel width
        tr = ta.TRANGE(dataframe)
        tr_filtered = gaussian_filter(tr, poles=self.GAUSSIAN_POLES,
                                      sampling_period=self.GAUSSIAN_SAMPLING)
        dataframe['gaussian_upper'] = dataframe['gaussian_mid'] + tr_filtered * self.FILTER_MULTIPLIER
        dataframe['gaussian_lower'] = dataframe['gaussian_mid'] - tr_filtered * self.FILTER_MULTIPLIER

        # Trend direction: close vs upper band
        dataframe['above_upper'] = (dataframe['close'] > dataframe['gaussian_upper']).astype(int)
        dataframe['below_upper'] = (dataframe['close'] < dataframe['gaussian_upper']).astype(int)

        # Crossover/crossunder detection
        dataframe['cross_above'] = (
            (dataframe['above_upper'] == 1) &
            (dataframe['above_upper'].shift(1) == 0)
        ).astype(int)
        dataframe['cross_below'] = (
            (dataframe['below_upper'] == 1) &
            (dataframe['below_upper'].shift(1) == 0)
        ).astype(int)

        # BTC Market Guard
        dataframe['btc_bullish'] = (
            (dataframe['btc_usdt_close_1d'] > dataframe['btc_usdt_sma200_1d'])
            & (dataframe['btc_usdt_rsi_1d'] > 35)
        ).astype(int)

        return dataframe

    # ── Entry gate ──────────────────────────────────────────────────

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag: str | None, side: str, **kwargs) -> bool:
        bot_name = self.config.get('bot_name', 'GaussianChannel')

        other_bots = PositionTracker.count_bots_holding(pair, exclude_bot=bot_name)
        if other_bots >= MAX_BOTS_PER_PAIR:
            logger.info("BLOCKED %s: %d other bots already hold this pair", pair, other_bots)
            return False

        if FearGreedIndex.is_extreme_greed():
            logger.info("BLOCKED %s: Fear & Greed in extreme greed", pair)
            return False

        PositionTracker.register(bot_name, pair, amount * rate)
        return True

    def confirm_trade_exit(self, pair: str, trade, order_type: str, amount: float,
                           rate: float, time_in_force: str, exit_reason: str,
                           current_time: datetime, **kwargs) -> bool:
        bot_name = self.config.get('bot_name', 'GaussianChannel')
        PositionTracker.unregister(bot_name, pair)
        return True

    # ── Entry / Exit ────────────────────────────────────────────────

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe['cross_above'] == 1)
                & (dataframe['btc_bullish'] == 1)
            ),
            ['enter_long', 'enter_tag']
        ] = (1, 'gaussian_cross_above')
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe['cross_below'] == 1),
            ['exit_long', 'exit_tag']
        ] = (1, 'gaussian_cross_below')
        return dataframe
