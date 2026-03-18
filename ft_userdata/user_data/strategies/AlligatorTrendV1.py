"""
AlligatorTrend V1 - Williams Alligator + ATR Dynamic Stoploss
=============================================================

Based on Michael Ionita's free PineScript strategy (Google Doc).
Results: 2,200% on BTC, works across BTC/ETH/SOL/XRP.

Logic:
  - Entry: Lips (5-period SMMA) crosses above Jaw (13-period SMMA)
  - Exit: Lips crosses below Jaw, or ATR-based dynamic stoploss hit
  - Daily timeframe, long-only
  - SMMA (Smoothed Moving Average) applied to HL2 (high+low)/2

The Alligator indicator represents market states:
  - Mouth open (lines diverging) = trending
  - Mouth closed (lines converging) = ranging/sleeping
  - Lines crossing = trend change
"""

import logging
from datetime import datetime

import numpy as np
import talib.abstract as ta
from freqtrade.strategy import IStrategy, informative
from pandas import DataFrame

from market_intelligence import FearGreedIndex, PositionTracker, MAX_BOTS_PER_PAIR

logger = logging.getLogger(__name__)


def smma(series, length: int):
    """
    Smoothed Moving Average (SMMA) — also known as Modified Moving Average.
    SMMA = (prev_SMMA * (length - 1) + current) / length
    """
    result = np.full(len(series), np.nan)
    vals = series.values.astype(float)

    # Initialize with SMA
    first_valid = 0
    for i in range(len(vals)):
        if not np.isnan(vals[i]):
            first_valid = i
            break

    if first_valid + length > len(vals):
        return result

    initial_sma = np.nanmean(vals[first_valid:first_valid + length])
    result[first_valid + length - 1] = initial_sma

    for i in range(first_valid + length, len(vals)):
        if np.isnan(vals[i]):
            result[i] = result[i - 1]
        else:
            result[i] = (result[i - 1] * (length - 1) + vals[i]) / length

    return result


class AlligatorTrendV1(IStrategy):

    INTERFACE_VERSION = 3

    timeframe = "1d"

    # Wide ROI — trend-following, let winners run
    minimal_roi = {
        "0": 0.50,       # 50% — very wide
        "30": 0.30,      # 30% after 30 days
        "60": 0.15,      # 15% after 60 days
        "90": 0.05,      # 5% after 90 days
    }

    # Stoploss managed dynamically via custom_stoploss (ATR-based)
    stoploss = -0.10  # Safety net only
    use_custom_stoploss = True

    # Trailing stop for protecting large gains
    trailing_stop = True
    trailing_stop_positive = 0.03     # Trail by 3%
    trailing_stop_positive_offset = 0.08  # Start trailing at +8%
    trailing_only_offset_is_reached = True

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = True  # Don't exit if trend continues

    startup_candle_count: int = 200

    # Alligator parameters (matching PineScript)
    JAW_LENGTH = 13
    TEETH_LENGTH = 8
    LIPS_LENGTH = 5

    # ATR stoploss parameters
    ATR_PERIOD = 14
    ATR_MULTIPLIER = 2.0

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
        # HL2 source (same as PineScript)
        hl2 = (dataframe['high'] + dataframe['low']) / 2.0

        # Alligator lines (SMMA on HL2)
        dataframe['jaw'] = smma(hl2, self.JAW_LENGTH)
        dataframe['teeth'] = smma(hl2, self.TEETH_LENGTH)
        dataframe['lips'] = smma(hl2, self.LIPS_LENGTH)

        # ATR for dynamic stoploss
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=self.ATR_PERIOD)

        # Crossover detection: Lips crosses above/below Jaw
        dataframe['lips_above_jaw'] = (dataframe['lips'] > dataframe['jaw']).astype(int)
        dataframe['cross_above'] = (
            (dataframe['lips_above_jaw'] == 1) &
            (dataframe['lips_above_jaw'].shift(1) == 0)
        ).astype(int)
        dataframe['cross_below'] = (
            (dataframe['lips_above_jaw'] == 0) &
            (dataframe['lips_above_jaw'].shift(1) == 1)
        ).astype(int)

        # BTC Market Guard
        dataframe['btc_bullish'] = (
            (dataframe['btc_usdt_close_1d'] > dataframe['btc_usdt_sma200_1d'])
            & (dataframe['btc_usdt_rsi_1d'] > 35)
        ).astype(int)

        return dataframe

    # ── ATR-based dynamic stoploss ──────────────────────────────────

    def custom_stoploss(self, pair: str, trade, current_time: datetime,
                        current_rate: float, current_profit: float,
                        after_fill: bool, **kwargs) -> float:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return self.stoploss

        last = dataframe.iloc[-2]  # Use last COMPLETED candle, not potentially incomplete current one
        atr = last.get('atr', 0)
        if atr <= 0:
            return self.stoploss

        # Dynamic stoploss: entry price - ATR * multiplier
        atr_stop_price = trade.open_rate - (atr * self.ATR_MULTIPLIER)
        atr_stop_pct = (atr_stop_price - current_rate) / current_rate

        # Only tighten, never loosen
        return max(atr_stop_pct, self.stoploss)

    # ── Entry gate ──────────────────────────────────────────────────

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag: str | None, side: str, **kwargs) -> bool:
        bot_name = self.config.get('bot_name', 'AlligatorTrend')

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
        bot_name = self.config.get('bot_name', 'AlligatorTrend')
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
        ] = (1, 'alligator_lips_cross_jaw')
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe['cross_below'] == 1),
            ['exit_long', 'exit_tag']
        ] = (1, 'alligator_lips_cross_jaw_down')
        return dataframe
