"""
MasterTrader V1 - EMA Crossover + RSI Filter + Market Intelligence
Simple trend-following strategy for dry-run validation.

Entry: Fast EMA crosses above slow EMA, RSI confirms (not overbought)
       + BTC must be healthy (above 200 SMA, RSI > 35)
       + Fear & Greed not in extreme greed
       + Cross-bot position limit not exceeded
Exit: Fast EMA crosses below slow EMA, or RSI overbought, or stoploss/ROI
"""

import logging
from datetime import datetime

from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter, informative
from pandas import DataFrame
import talib.abstract as ta

from market_intelligence import FearGreedIndex, PositionTracker, MAX_BOTS_PER_PAIR

logger = logging.getLogger(__name__)


class MasterTraderV1(IStrategy):

    INTERFACE_VERSION = 3

    # Keeping 1h: EMA 9/21 crossover generates only 8 trades/6mo on 4h (too restrictive)
    # 4H migration would need longer EMAs (21/55) — revisit after current evaluation period
    timeframe = "1h"

    # ROI table - widened to let winners run (trend-following)
    # Old: 5%/3%/2%/1% — was cutting winners too short
    minimal_roi = {
        "0": 0.15,      # 15% profit immediately
        "720": 0.10,    # 10% after 12h
        "1440": 0.07,   # 7% after 24h
        "2880": 0.03,   # 3% after 48h
    }

    # Stoploss
    stoploss = -0.05  # Data: 0% of trades recover past -7%, 92% of winners never dip past -3%

    # Trailing stop - widened to let trends develop
    trailing_stop = True
    trailing_stop_positive = 0.02       # Trail by 2% once offset is reached
    trailing_stop_positive_offset = 0.04  # Start trailing at 4% profit (was 2%)
    trailing_only_offset_is_reached = True

    # Run on new candles only
    process_only_new_candles = True

    # Use exit signal
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # Number of candles needed before producing valid signals
    startup_candle_count: int = 200  # BTC SMA200 needs 200 candles

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {"method": "StoplossGuard", "lookback_period_candles": 48, "trade_limit": 2, "stop_duration_candles": 24, "only_per_pair": True},
            {"method": "LowProfitPairs", "lookback_period_candles": 288, "trade_limit": 4, "stop_duration_candles": 48, "required_profit": -0.05},
            {"method": "MaxDrawdown", "lookback_period_candles": 48, "max_allowed_drawdown": 0.20, "stop_duration_candles": 12, "trade_limit": 1},
        ]

    # Hyperoptable parameters
    ema_fast = IntParameter(5, 25, default=9, space="buy", optimize=True)
    ema_slow = IntParameter(20, 60, default=21, space="buy", optimize=True)
    rsi_period = IntParameter(10, 25, default=14, space="buy", optimize=True)
    rsi_buy_limit = IntParameter(20, 45, default=35, space="buy", optimize=True)
    rsi_sell_limit = IntParameter(65, 85, default=75, space="sell", optimize=True)

    # ── BTC Market Guard (informative pair) ───────────────────────

    @informative('1h', 'BTC/{stake}')
    def populate_indicators_btc_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['sma200'] = ta.SMA(dataframe['close'], timeperiod=200)
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # EMAs
        for val in range(5, 61):
            dataframe[f"ema_{val}"] = ta.EMA(dataframe, timeperiod=val)

        # RSI
        for val in range(10, 26):
            dataframe[f"rsi_{val}"] = ta.RSI(dataframe, timeperiod=val)

        # Volume SMA for volume filter
        dataframe["volume_sma_20"] = ta.SMA(dataframe["volume"], timeperiod=20)

        # --- Regime Detection ---
        dataframe['regime_atr_14'] = ta.ATR(dataframe, timeperiod=14)
        dataframe['regime_atr_sma_50'] = dataframe['regime_atr_14'].rolling(50).mean()
        dataframe['regime_volatile'] = (dataframe['regime_atr_14'] > 2.0 * dataframe['regime_atr_sma_50']).astype(int)

        dataframe['regime_adx_14'] = ta.ADX(dataframe, timeperiod=14)
        dataframe['regime_trending'] = (dataframe['regime_adx_14'] > 25).astype(int)

        # --- BTC Market Guard composite ---
        dataframe['btc_bullish'] = (
            (dataframe['btc_usdt_close_1h'] > dataframe['btc_usdt_sma200_1h'])
            & (dataframe['btc_usdt_rsi_1h'] > 35)
        ).astype(int)

        return dataframe

    # ── Entry gate: cross-bot + sentiment checks ─────────────────

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag: str | None, side: str, **kwargs) -> bool:
        bot_name = self.config.get('bot_name', 'MasterTraderV1')

        # Cross-bot position check
        other_bots = PositionTracker.count_bots_holding(pair, exclude_bot=bot_name)
        if other_bots >= MAX_BOTS_PER_PAIR:
            logger.info("BLOCKED %s: %d other bots already hold this pair", pair, other_bots)
            return False

        # Fear & Greed: reduce exposure during extreme greed
        if FearGreedIndex.is_extreme_greed():
            logger.info("BLOCKED %s: Fear & Greed in extreme greed (%d)",
                         pair, FearGreedIndex.get()["value"])
            return False

        # Register position
        PositionTracker.register(bot_name, pair, amount * rate)
        return True

    def confirm_trade_exit(self, pair: str, trade, order_type: str, amount: float,
                           rate: float, time_in_force: str, exit_reason: str,
                           current_time: datetime, **kwargs) -> bool:
        bot_name = self.config.get('bot_name', 'MasterTraderV1')
        PositionTracker.unregister(bot_name, pair)
        return True

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
                # Regime filters
                & (dataframe['regime_volatile'] == 0)  # Don't enter during high volatility
                & (dataframe['regime_trending'] == 1)  # Trend following: only enter in trending markets
                # BTC market guard
                & (dataframe['btc_bullish'] == 1)
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
            & (dataframe["volume"] > 0)
            | ((dataframe['regime_atr_14'] > 2.5 * dataframe['regime_atr_sma_50']) & (dataframe["volume"] > 0)),  # Exit on volatility spike
            "exit_long",
        ] = 1

        return dataframe
