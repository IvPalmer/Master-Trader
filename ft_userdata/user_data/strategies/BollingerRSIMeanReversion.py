import logging
from datetime import datetime

from freqtrade.strategy import IStrategy, informative
from pandas import DataFrame
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib

from market_intelligence import FearGreedIndex, PositionTracker, MAX_BOTS_PER_PAIR

logger = logging.getLogger(__name__)


class BollingerRSIMeanReversion(IStrategy):
    """
    15m Bollinger Bands + RSI Mean Reversion Strategy

    Buys when price dips below lower BB with RSI oversold, in ranging markets only.
    Exits on reversion to the mean (middle BB) or RSI recovery.
    ADX filter prevents entries during strong trends.

    BTC guard: softer than trend-followers — only blocks during BTC freefall
    (RSI < 25), since mean-reversion thrives in mild bear/ranging markets.
    """

    INTERFACE_VERSION: int = 3

    minimal_roi = {
        "0": 0.04,
        "30": 0.025,
        "60": 0.015,
        "120": 0.005
    }

    stoploss = -0.05  # Data: 0% of trades recover past -7%, 92% of winners never dip past -3%
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True

    timeframe = '15m'
    process_only_new_candles = True
    startup_candle_count = 200  # BTC SMA200 needs 200 1h candles (Freqtrade auto-adjusts)

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

    # ── BTC Market Guard (informative pair on 1h) ────────────────

    @informative('1h', 'BTC/{stake}')
    def populate_indicators_btc_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['sma200'] = ta.SMA(dataframe['close'], timeperiod=200)
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
        return dataframe

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

        # --- BTC guard: softer for mean-reversion ---
        # Only block during BTC freefall, not mild weakness
        dataframe['btc_not_crashing'] = (
            dataframe['btc_usdt_rsi_1h'] > 25
        ).astype(int)

        return dataframe

    # ── Entry gate: cross-bot + sentiment checks ─────────────────

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag: str | None, side: str, **kwargs) -> bool:
        bot_name = self.config.get('bot_name', 'BollingerRSI MR')

        # Cross-bot position check
        other_bots = PositionTracker.count_bots_holding(pair, exclude_bot=bot_name)
        if other_bots >= MAX_BOTS_PER_PAIR:
            logger.info("BLOCKED %s: %d other bots already hold this pair", pair, other_bots)
            return False

        # Fear & Greed: block during extreme greed (even mean-reversion gets wrecked in blowoffs)
        if FearGreedIndex.is_extreme_greed():
            logger.info("BLOCKED %s: Fear & Greed in extreme greed (%d)",
                         pair, FearGreedIndex.get()["value"])
            return False

        PositionTracker.register(bot_name, pair, amount * rate)
        return True

    def confirm_trade_exit(self, pair: str, trade, order_type: str, amount: float,
                           rate: float, time_in_force: str, exit_reason: str,
                           current_time: datetime, **kwargs) -> bool:
        bot_name = self.config.get('bot_name', 'BollingerRSI MR')
        PositionTracker.unregister(bot_name, pair)
        return True

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe['close'] < dataframe['bb_lowerband']) &
                (dataframe['rsi'] < 30) &
                (dataframe['adx'] < 30) &  # Only ranging markets
                (dataframe['regime_volatile'] == 0) &  # No high volatility
                (dataframe['bb_width'] > 0.02) &  # Avoid low-vol squeezes
                (dataframe['volume'] > dataframe['volume_sma']) &
                (dataframe['volume'] > 0) &
                # BTC guard: only block during freefall (RSI < 25)
                (dataframe['btc_not_crashing'] == 1)
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
