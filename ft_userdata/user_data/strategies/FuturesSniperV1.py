"""
Futures Sniper V1 — Bear Market Revenue Engine
===============================================

Strategic role: When spot bots freeze (BTC below SMA200), this bot becomes
the PRIMARY profit center by actively shorting the downtrend.

Three short entry types (not just crossovers):
  1. INITIATION: EMA death cross / MACD turn (catches trend start)
  2. CONTINUATION: pullback into EMA21 rejection during downtrend (the workhorse)
  3. BREAKDOWN: new swing low on volume surge (momentum continuation)

When BTC is bullish, this bot also takes longs (same logic as spot bots).

Fixed 2x leverage, isolated margin. Kill switch at -5% daily.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter, informative
from freqtrade.persistence import Trade
from pandas import DataFrame
import talib.abstract as ta
import numpy as np

from market_intelligence import (
    FearGreedIndex, PositionTracker, MAX_BOTS_PER_PAIR
)

logger = logging.getLogger(__name__)


class FuturesSniperV1(IStrategy):

    INTERFACE_VERSION = 3

    can_short = True
    # Keeping 1h: EMA 9/21 crossover + regime filters = only 6 trades/6mo on 4h
    # Supertrend-based strategies work on 4h; EMA crossover needs more frequent data
    timeframe = "1h"

    # ── ROI: widened to let winners run at 2x leverage ─────────────
    # Old: 2.5%/1.5%/1%/0.5% — cutting winners too early
    # At 2x leverage, 5% ROI = 10% dollar gain. Let trends develop.
    minimal_roi = {
        "0": 0.075,     # 7.5% (= 15% at 2x)
        "360": 0.05,    # 5% after 6h (= 10% at 2x)
        "720": 0.035,   # 3.5% after 12h (= 7% at 2x)
        "1440": 0.015,  # 1.5% after 24h (= 3% at 2x)
    }

    # -3% stoploss at 2x = -6% dollar risk (was -2%, too tight — 1% price move is noise)
    stoploss = -0.03

    # Trailing stop — 1.5% trail after 3% profit (widened from 1%/2%)
    trailing_stop = True
    trailing_stop_positive = 0.015
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    startup_candle_count: int = 200

    # ── Kill switch state (persisted to file) ────────────────────
    KILL_SWITCH_FILE = "/freqtrade/user_data/kill_switch_FuturesSniperV1.json"
    DAILY_LOSS_LIMIT = -0.05
    MAX_CONSECUTIVE_LOSSES = 3
    SHORT_MAX_HOLD_HOURS = 48

    def _load_kill_state(self):
        """Load kill switch state from file, or initialize defaults."""
        try:
            if os.path.exists(self.KILL_SWITCH_FILE):
                with open(self.KILL_SWITCH_FILE, 'r') as f:
                    state = json.load(f)
                self._daily_loss = state.get('daily_loss', 0.0)
                self._daily_loss_date = state.get('daily_loss_date', None)
                self._consecutive_losses = state.get('consecutive_losses', 0)
                self._killed = state.get('killed', False)
                logger.info("SNIPER: Loaded kill state from file — killed=%s, consec_losses=%d, daily_loss=%.4f",
                            self._killed, self._consecutive_losses, self._daily_loss)
                return
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("SNIPER: Failed to load kill state: %s — resetting", e)
        self._daily_loss = 0.0
        self._daily_loss_date = None
        self._consecutive_losses = 0
        self._killed = False

    def _save_kill_state(self):
        """Persist kill switch state to file."""
        state = {
            'daily_loss': self._daily_loss,
            'daily_loss_date': self._daily_loss_date,
            'consecutive_losses': self._consecutive_losses,
            'killed': self._killed,
        }
        try:
            Path(self.KILL_SWITCH_FILE).parent.mkdir(parents=True, exist_ok=True)
            with open(self.KILL_SWITCH_FILE, 'w') as f:
                json.dump(state, f)
        except IOError as e:
            logger.error("SNIPER: Failed to save kill state: %s", e)

    def bot_start(self, **kwargs) -> None:
        """Called once when the bot starts — load persisted kill switch state."""
        self._load_kill_state()

    # ── Short position sizing: 25% of normal stake ───────────────
    # Data: short trades are net negative even in profitable systems.
    # Adding shorts increased drawdown by 11% (Michael Ionita research).
    # Reduce short exposure to 25% of long position size.
    SHORT_STAKE_MULTIPLIER = 0.25

    def custom_stake_amount(self, current_time, current_rate, proposed_stake,
                            min_stake, max_stake, leverage, entry_tag, side,
                            **kwargs) -> float:
        if side == "short":
            reduced = proposed_stake * self.SHORT_STAKE_MULTIPLIER
            logger.info(f"Short trade: reducing stake from {proposed_stake:.2f} to {reduced:.2f} (25%)")
            return max(reduced, min_stake) if min_stake else reduced
        return proposed_stake

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48, "trade_limit": 2,
                "stop_duration_candles": 24, "only_per_pair": True,
            },
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 288, "trade_limit": 4,
                "stop_duration_candles": 48, "required_profit": -0.05,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 48, "max_allowed_drawdown": 0.10,
                "stop_duration_candles": 24, "trade_limit": 1,
            },
        ]

    # ── Hyperoptable parameters ───────────────────────────────────
    ema_fast = IntParameter(5, 25, default=9, space="buy", optimize=True)
    ema_slow = IntParameter(20, 60, default=21, space="buy", optimize=True)
    rsi_period = IntParameter(10, 25, default=14, space="buy", optimize=True)
    rsi_buy_limit = IntParameter(20, 45, default=35, space="buy", optimize=True)
    rsi_sell_limit = IntParameter(65, 85, default=75, space="sell", optimize=True)

    # ── BTC Market Guard (informative pair) ───────────────────────

    @informative('1h', 'BTC/{stake}:{stake}')
    def populate_indicators_btc_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['sma200'] = ta.SMA(dataframe['close'], timeperiod=200)
        dataframe['ema50'] = ta.EMA(dataframe['close'], timeperiod=50)
        dataframe['ema200'] = ta.EMA(dataframe['close'], timeperiod=200)
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
        return dataframe

    # ── Leverage callback ─────────────────────────────────────────

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str | None,
                 side: str, **kwargs) -> float:
        return 2.0

    # ── Time-based exit for shorts ────────────────────────────────

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs):
        if trade.is_short:
            trade_duration = (current_time - trade.open_date_utc).total_seconds() / 3600
            if trade_duration >= self.SHORT_MAX_HOLD_HOURS:
                logger.info("SNIPER: Time-exit short %s after %.0fh (profit: %.2f%%)",
                            pair, trade_duration, current_profit * 100)
                return "short_time_exit"
        return None

    # ── Entry gate ────────────────────────────────────────────────

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag: str | None, side: str, **kwargs) -> bool:

        if self._killed:
            logger.warning("SNIPER KILLED: Rejecting %s entry on %s", side, pair)
            return False

        today = str(current_time.date())
        if self._daily_loss_date != today:
            self._daily_loss = 0.0
            self._daily_loss_date = today
            if self._killed and self._consecutive_losses < self.MAX_CONSECUTIVE_LOSSES:
                self._killed = False
                logger.info("SNIPER: Daily reset, re-enabling trading")
            self._save_kill_state()

        if self._daily_loss <= self.DAILY_LOSS_LIMIT:
            self._killed = True
            self._save_kill_state()
            logger.error("SNIPER KILL SWITCH: Daily loss %.2f%% exceeds limit",
                         self._daily_loss * 100)
            return False

        bot_name = self.config.get('bot_name', 'FuturesSniperV1')

        other_bots = PositionTracker.count_bots_holding(pair, exclude_bot=bot_name)
        if other_bots >= MAX_BOTS_PER_PAIR:
            logger.info("SNIPER BLOCKED %s: %d other bots already hold", pair, other_bots)
            return False

        if side == "long" and FearGreedIndex.is_extreme_greed():
            logger.info("SNIPER BLOCKED long %s: extreme greed", pair)
            return False

        PositionTracker.register(bot_name, pair, amount * rate)
        return True

    # ── Exit tracking ─────────────────────────────────────────────

    def confirm_trade_exit(self, pair: str, trade, order_type: str, amount: float,
                           rate: float, time_in_force: str, exit_reason: str,
                           current_time: datetime, **kwargs) -> bool:
        profit = trade.calc_profit_ratio(rate)

        if profit < 0:
            self._daily_loss += profit
            self._consecutive_losses += 1
            if self._consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES:
                self._killed = True
                logger.error("SNIPER KILL SWITCH: %d consecutive losses", self._consecutive_losses)
        else:
            self._consecutive_losses = max(0, self._consecutive_losses - 1)

        self._save_kill_state()

        bot_name = self.config.get('bot_name', 'FuturesSniperV1')
        PositionTracker.unregister(bot_name, pair)
        return True

    # ── Indicators ────────────────────────────────────────────────

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # EMAs
        for val in range(5, 61):
            dataframe[f"ema_{val}"] = ta.EMA(dataframe, timeperiod=val)

        # RSI
        for val in range(10, 26):
            dataframe[f"rsi_{val}"] = ta.RSI(dataframe, timeperiod=val)

        # MACD
        dataframe['macd'], dataframe['macd_signal'], dataframe['macd_hist'] = ta.MACD(
            dataframe['close'], fastperiod=12, slowperiod=26, signalperiod=9
        )

        # Volume
        dataframe["volume_sma_20"] = ta.SMA(dataframe["volume"], timeperiod=20)

        # --- Per-pair regime ---
        dataframe['regime_atr_14'] = ta.ATR(dataframe, timeperiod=14)
        dataframe['regime_atr_sma_50'] = dataframe['regime_atr_14'].rolling(50).mean()
        dataframe['regime_volatile'] = (
            dataframe['regime_atr_14'] > 2.0 * dataframe['regime_atr_sma_50']
        ).astype(int)

        dataframe['regime_adx_14'] = ta.ADX(dataframe, timeperiod=14)
        dataframe['regime_trending'] = (dataframe['regime_adx_14'] > 25).astype(int)
        dataframe['regime_trending_loose'] = (dataframe['regime_adx_14'] > 20).astype(int)

        # --- Swing low detection (for breakdown entries) ---
        dataframe['swing_low'] = dataframe['low'].rolling(10).min()
        dataframe['new_swing_low'] = (
            (dataframe['close'] < dataframe['swing_low'].shift(1))
        ).astype(int)

        # --- Multi-tier BTC regime ---
        btc_above_sma200 = dataframe['btc_usdt_close_1h'] > dataframe['btc_usdt_sma200_1h']
        btc_ema_bullish = dataframe['btc_usdt_ema50_1h'] > dataframe['btc_usdt_ema200_1h']
        btc_sma200_declining = dataframe['btc_usdt_sma200_1h'] < dataframe['btc_usdt_sma200_1h'].shift(3)

        # BTC crash detection: block longs if BTC dropped >3% in last 6 candles
        dataframe['btc_crash'] = (
            (dataframe['btc_usdt_close_1h'] < dataframe['btc_usdt_close_1h'].shift(6) * 0.97)
        ).astype(int)

        # Rapid deterioration: BTC dropped >3% in 6 candles AND RSI < 35
        btc_rapid_bear = (
            (dataframe['btc_usdt_close_1h'] < dataframe['btc_usdt_close_1h'].shift(6) * 0.97)
            & (dataframe['btc_usdt_rsi_1h'] < 35)
        )

        dataframe['btc_bullish'] = (
            btc_above_sma200
            & btc_ema_bullish
            & (dataframe['btc_usdt_rsi_1h'] > 35)
        ).astype(int)

        # Neutral: BTC above SMA200 but not fully bullish — still safe for longs
        # Closes the dead zone where neither bullish nor bearish was true
        # Also blocks longs during crashes (>3% drop in 6 candles)
        dataframe['btc_long_ok'] = (
            (btc_above_sma200 | (btc_ema_bullish & (dataframe['btc_usdt_rsi_1h'] > 40)))
            & (dataframe['btc_crash'] == 0)
        ).astype(int)

        # Bear mode: BTC below SMA200 with declining slope, OR rapid deterioration
        dataframe['btc_bearish'] = (
            (~btc_above_sma200 & btc_sma200_declining)
            | (~btc_ema_bullish & btc_sma200_declining & (dataframe['btc_usdt_adx_1h'] > 20))
            | btc_rapid_bear
        ).astype(int)

        # --- Per-pair trend state ---
        ema_f = f"ema_{self.ema_fast.value}"
        ema_s = f"ema_{self.ema_slow.value}"
        dataframe['in_uptrend'] = (dataframe[ema_f] > dataframe[ema_s]).astype(int)
        dataframe['in_downtrend'] = (dataframe[ema_f] < dataframe[ema_s]).astype(int)

        return dataframe

    # ── Entry signals ─────────────────────────────────────────────

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ema_f = f"ema_{self.ema_fast.value}"
        ema_s = f"ema_{self.ema_slow.value}"
        rsi_col = f"rsi_{self.rsi_period.value}"

        # ── LONG entries: three types, BTC must be at least neutral ──
        # Old logic required crossover event + full BTC bullish → 1 trade in 3 days
        # New: ride trends (Ionita approach), don't just catch crosses

        long_base = (
            (dataframe["volume"] > 0)
            & (dataframe['regime_volatile'] == 0)
            & (dataframe['btc_long_ok'] == 1)
        )

        # Type 1: INITIATION — fresh EMA golden cross (original logic, relaxed)
        long_initiation = (
            (
                (dataframe[ema_f] > dataframe[ema_s])
                & (dataframe[ema_f].shift(1) <= dataframe[ema_s].shift(1))
            )
            & (dataframe[rsi_col] > self.rsi_buy_limit.value)
            & (dataframe[rsi_col] < 70)
            & (dataframe["volume"] > dataframe["volume_sma_20"])
        )

        # Type 2: CONTINUATION — pullback buy in established uptrend
        # Price dips toward EMA slow then bounces — the workhorse entry
        long_continuation = (
            (dataframe['in_uptrend'] == 1)
            # Price pulled back DOWN toward EMA slow (within 1%)
            & (dataframe['close'] > dataframe[ema_s] * 0.99)
            & (dataframe['close'] < dataframe[ema_s] * 1.01)
            # Candle closed green (bounce)
            & (dataframe['close'] > dataframe['open'])
            # RSI dipped but recovering
            & (dataframe[rsi_col] > 35)
            & (dataframe[rsi_col] < 60)
            # MACD still positive (trend intact)
            & (dataframe['macd_hist'] > 0)
        )

        # Type 3: BREAKOUT — new swing high on volume (momentum continuation)
        long_breakout = (
            (dataframe['close'] > dataframe['high'].rolling(10).max().shift(1))
            & (dataframe[rsi_col] > 50)
            & (dataframe[rsi_col] < 75)
            & (dataframe["volume"] > dataframe["volume_sma_20"] * 1.5)
            & (dataframe['in_uptrend'] == 1)
            & (dataframe['regime_trending'] == 1)
        )

        dataframe.loc[
            long_base & (long_initiation | long_continuation | long_breakout),
            "enter_long",
        ] = 1

        # ── SHORT entries: three types, all require BTC bearish ───

        # Common filters for all short types
        short_base = (
            (dataframe["volume"] > 0)
            & (dataframe['regime_volatile'] == 0)
            & (dataframe['btc_bearish'] == 1)
        )

        # Type 1: INITIATION — catch trend start
        # EMA death cross or MACD histogram turns negative
        short_initiation = (
            (
                # Fresh EMA death cross
                (
                    (dataframe[ema_f] < dataframe[ema_s])
                    & (dataframe[ema_f].shift(1) >= dataframe[ema_s].shift(1))
                )
                # OR MACD histogram flips negative (1-3 candles earlier)
                | (
                    (dataframe['macd_hist'] < 0)
                    & (dataframe['macd_hist'].shift(1) >= 0)
                )
            )
            & (dataframe[rsi_col] < 50)
            & (dataframe["volume"] > dataframe["volume_sma_20"])
            & (dataframe['regime_trending_loose'] == 1)
        )

        # Type 2: CONTINUATION — the workhorse during sustained downtrends
        # Price is already in downtrend, pulls back toward EMA21, then rejected
        # This is where most trades happen in a bear market
        short_continuation = (
            # Already in downtrend (EMA fast < slow)
            (dataframe['in_downtrend'] == 1)
            # Price pulled back UP toward EMA slow (within 0.5%)
            & (dataframe['close'] > dataframe[ema_s] * 0.995)
            & (dataframe['close'] < dataframe[ema_s] * 1.005)
            # But candle closed red (rejection)
            & (dataframe['close'] < dataframe['open'])
            # RSI came up from oversold but still bearish
            & (dataframe[rsi_col] > 30)
            & (dataframe[rsi_col] < 55)
            # MACD still negative (trend intact)
            & (dataframe['macd_hist'] < 0)
        )

        # Type 3: BREAKDOWN — new swing low on volume surge
        # Price breaks below 10-candle low = momentum continuation
        short_breakdown = (
            (dataframe['new_swing_low'] == 1)
            & (dataframe[rsi_col] < 45)
            # Volume surge (breakdown on conviction)
            & (dataframe["volume"] > dataframe["volume_sma_20"] * 1.5)
            # Already trending down
            & (dataframe['in_downtrend'] == 1)
            & (dataframe['regime_trending_loose'] == 1)
        )

        dataframe.loc[
            short_base & (short_initiation | short_continuation | short_breakdown),
            "enter_short",
        ] = 1

        return dataframe

    # ── Exit signals ──────────────────────────────────────────────

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ema_f = f"ema_{self.ema_fast.value}"
        ema_s = f"ema_{self.ema_slow.value}"
        rsi_col = f"rsi_{self.rsi_period.value}"

        # Long exits
        dataframe.loc[
            (
                (
                    (dataframe[ema_f] < dataframe[ema_s])
                    & (dataframe[ema_f].shift(1) >= dataframe[ema_s].shift(1))
                )
                | (dataframe[rsi_col] > self.rsi_sell_limit.value)
            )
            & (dataframe["volume"] > 0)
            | (
                (dataframe['regime_atr_14'] > 2.5 * dataframe['regime_atr_sma_50'])
                & (dataframe["volume"] > 0)
            ),
            "exit_long",
        ] = 1

        # Short exits: momentum reversal signals
        dataframe.loc[
            (
                # EMA golden cross (trend reversed)
                (
                    (dataframe[ema_f] > dataframe[ema_s])
                    & (dataframe[ema_f].shift(1) <= dataframe[ema_s].shift(1))
                )
                # OR MACD flips positive
                | (
                    (dataframe['macd_hist'] > 0)
                    & (dataframe['macd_hist'].shift(1) <= 0)
                )
                # OR RSI bouncing off bottom (reversal confirmed)
                | (
                    (dataframe[rsi_col] < 25)
                    & (dataframe[rsi_col] > dataframe[rsi_col].shift(1))
                )
                # OR BTC turns bullish
                | (dataframe['btc_bullish'] == 1)
            )
            & (dataframe["volume"] > 0)
            | (
                (dataframe['regime_atr_14'] > 2.5 * dataframe['regime_atr_sma_50'])
                & (dataframe["volume"] > 0)
            ),
            "exit_short",
        ] = 1

        return dataframe
