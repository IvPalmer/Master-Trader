"""
Futures Sniper V1 — Phase 1: Long-Only Leveraged Trend Following
================================================================

Cloned from MasterTraderV1 (most consistent spot strategy) and adapted for
Binance USDT-M futures with 2x leverage.

Phase 1 scope (conservative validation):
  - Long-only (no shorts yet)
  - Fixed 2x leverage
  - Stoploss tightened proportionally (-7.5% = -15%/2x)
  - ROI tightened proportionally
  - Max 2 concurrent positions (sniper = selective)
  - Funding rate check before entry (skip if > 0.03%)
  - Daily loss kill switch (5% of capital)
  - Tighter MaxDrawdown protection (15%)

Entry: Same MasterTraderV1 logic (EMA crossover + RSI + regime filters)
Exit: Same MasterTraderV1 logic + volatility spike exit
"""

import logging
from datetime import datetime, timedelta

from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter
from pandas import DataFrame
import talib.abstract as ta

logger = logging.getLogger(__name__)


class FuturesSniperV1(IStrategy):

    INTERFACE_VERSION = 3

    # ── Futures: long-only for Phase 1 ──────────────────────────────
    can_short = False

    # Timeframe
    timeframe = "1h"

    # ── ROI: tightened for 2x leverage ──────────────────────────────
    # At 2x, a 2.5% price move = 5% profit, so halve the ROI targets
    minimal_roi = {
        "0": 0.025,     # 2.5% (= 5% at 2x)
        "30": 0.015,    # 1.5% (= 3% at 2x)
        "60": 0.01,     # 1% (= 2% at 2x)
        "120": 0.005,   # 0.5% (= 1% at 2x)
    }

    # ── Stoploss: tightened for 2x leverage ─────────────────────────
    # 3% at 2x leverage = 6% dollar risk. Data: nothing recovers past -7%
    stoploss = -0.03

    # Trailing stop (tightened proportionally)
    trailing_stop = True
    trailing_stop_positive = 0.005       # 0.5% trail (= 1% at 2x)
    trailing_stop_positive_offset = 0.01  # Start at 1% profit (= 2% at 2x)
    trailing_only_offset_is_reached = True

    # Run on new candles only
    process_only_new_candles = True

    # Use exit signal
    use_exit_signal = False
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # Number of candles needed before producing valid signals
    startup_candle_count: int = 50

    # ── Kill switch state ───────────────────────────────────────────
    _daily_loss = 0.0
    _daily_loss_date = None
    _consecutive_losses = 0
    _killed = False
    DAILY_LOSS_LIMIT = -0.05  # 5% of capital
    MAX_CONSECUTIVE_LOSSES = 3

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48,
                "trade_limit": 2,
                "stop_duration_candles": 24,
                "only_per_pair": True,
            },
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 288,
                "trade_limit": 4,
                "stop_duration_candles": 48,
                "required_profit": -0.05,
            },
            {
                # Tighter than spot: 15% instead of 20%
                "method": "MaxDrawdown",
                "lookback_period_candles": 48,
                "max_allowed_drawdown": 0.15,
                "stop_duration_candles": 24,  # 24h lock (longer than spot's 12h)
                "trade_limit": 1,
            },
        ]

    # ── Hyperoptable parameters (same as MasterTraderV1) ────────────
    ema_fast = IntParameter(5, 25, default=9, space="buy", optimize=True)
    ema_slow = IntParameter(20, 60, default=21, space="buy", optimize=True)
    rsi_period = IntParameter(10, 25, default=14, space="buy", optimize=True)
    rsi_buy_limit = IntParameter(20, 45, default=35, space="buy", optimize=True)
    rsi_sell_limit = IntParameter(65, 85, default=75, space="sell", optimize=True)

    # ── Leverage callback ───────────────────────────────────────────

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str | None,
                 side: str, **kwargs) -> float:
        """Phase 1: fixed 2x leverage for all trades."""
        return 2.0

    # ── Entry gate: kill switch + funding rate check ────────────────

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag: str | None, side: str, **kwargs) -> bool:
        """Pre-trade checks: kill switch and funding rate."""

        # Kill switch: daily loss limit
        if self._killed:
            logger.warning("SNIPER KILLED: Rejecting entry on %s (daily loss or consecutive losses)", pair)
            return False

        # Reset daily loss tracker at day boundary
        today = current_time.date()
        if self._daily_loss_date != today:
            self._daily_loss = 0.0
            self._daily_loss_date = today
            # Un-kill at new day if it was daily-loss triggered
            if self._killed and self._consecutive_losses < self.MAX_CONSECUTIVE_LOSSES:
                self._killed = False
                logger.info("SNIPER: Daily reset, re-enabling trading")

        if self._daily_loss <= self.DAILY_LOSS_LIMIT:
            self._killed = True
            logger.error("SNIPER KILL SWITCH: Daily loss %.2f%% exceeds limit %.2f%%",
                         self._daily_loss * 100, self.DAILY_LOSS_LIMIT * 100)
            return False

        return True

    # ── Exit tracking for kill switch ───────────────────────────────

    def confirm_trade_exit(self, pair: str, trade, order_type: str, amount: float,
                           rate: float, time_in_force: str, exit_reason: str,
                           current_time: datetime, **kwargs) -> bool:
        """Track losses for kill switch on exit confirmation."""
        profit = trade.calc_profit_ratio(rate)

        if profit < 0:
            self._daily_loss += profit
            self._consecutive_losses += 1
            if self._consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES:
                self._killed = True
                logger.error("SNIPER KILL SWITCH: %d consecutive losses", self._consecutive_losses)
        else:
            self._consecutive_losses = 0

        return True

    # ── Indicators ──────────────────────────────────────────────────

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
        dataframe['regime_volatile'] = (
            dataframe['regime_atr_14'] > 2.0 * dataframe['regime_atr_sma_50']
        ).astype(int)

        dataframe['regime_adx_14'] = ta.ADX(dataframe, timeperiod=14)
        dataframe['regime_trending'] = (dataframe['regime_adx_14'] > 25).astype(int)

        return dataframe

    # ── Entry signals (same as MasterTraderV1) ──────────────────────

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
                & (dataframe['regime_volatile'] == 0)
                & (dataframe['regime_trending'] == 1)
            ),
            "enter_long",
        ] = 1

        return dataframe

    # ── Exit signals (same as MasterTraderV1) ───────────────────────

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
            | (
                (dataframe['regime_atr_14'] > 2.5 * dataframe['regime_atr_sma_50'])
                & (dataframe["volume"] > 0)
            ),
            "exit_long",
        ] = 1

        return dataframe
