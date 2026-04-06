"""
BearCrashShortV1 - Bear Regime Short-Only Strategy + Bounce-Long Mode
======================================================================

PRIMARY: Short-only during confirmed bear regimes.
SECONDARY: Rare bounce-long on bear-to-bull regime transitions (SMB Capital 5/5 track record).

Entry pattern (short): "Failed Rally Short" - trend-following shorts on dead cat bounces
- BTC must be in confirmed bear regime (below SMA200, ADX>25, RSI<45) for 4-of-6 candles
- Pair: -DI > +DI, ADX > 25, RSI 40-70 (bear "overbought"), below SMA200
- Anti-squeeze: RSI > 40 (entry signal), BTC RSI > 20, F&G > 10 (confirm_trade_entry)

Entry pattern (bounce-long): Post-bear recovery bet
- BTC was in confirmed bear regime on previous candle, now flipped bullish
- Pair: +DI > -DI, RSI 40-70, volume >= 1.5x 20-period average

Exit: RSI < 25, 2-candle +DI > -DI confirmation, BTC flips bullish, volatility spike, or time-based
Risk: -5% stoploss on exchange, 2% trail at 3%, 48h hard exit, $22 stake, 2x leverage
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from freqtrade.strategy import IStrategy, informative
from pandas import DataFrame
import talib.abstract as ta

from market_intelligence import FearGreedIndex, PositionTracker, MAX_BOTS_PER_PAIR

logger = logging.getLogger(__name__)

KILL_SWITCH_FILE = Path("/freqtrade/user_data/kill_switch_BearCrashShortV1.json")
DAILY_LOSS_LIMIT = 0.10  # 10% of wallet (with 2x leverage, a -5% SL = ~10% of stake)
CONSECUTIVE_LOSS_LIMIT = 3


class BearCrashShortV1(IStrategy):
    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "1h"

    # Tighter ROI for shorts - crypto crashes are fast, take profits early
    minimal_roi = {
        "0": 0.08,     # 8% - grab big moves immediately
        "720": 0.05,   # 5% after 12h
        "1440": 0.03,  # 3% after 24h
        "2160": 0.01,  # 1% after 36h
        "2880": 0.0,   # Break-even at 48h - hard exit
    }

    stoploss = -0.05  # -5% hard stop (tighter than longs due to squeeze risk)

    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    startup_candle_count = 200  # BTC SMA200

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 3},
            {"method": "StoplossGuard", "lookback_period_candles": 48,
             "trade_limit": 2, "stop_duration_candles": 24, "only_per_pair": True},
            {"method": "MaxDrawdown", "lookback_period_candles": 48,
             "max_allowed_drawdown": 0.15, "stop_duration_candles": 24, "trade_limit": 1},
        ]

    # -- BTC informative pair -------------------------------------------------

    @informative("1h", "BTC/{stake}:{stake}")
    def populate_indicators_btc_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["sma200"] = ta.SMA(dataframe["close"], timeperiod=200)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["plus_di"] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe["minus_di"] = ta.MINUS_DI(dataframe, timeperiod=14)
        return dataframe

    # -- Indicators ------------------------------------------------------------

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # DMI / ADX
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["plus_di"] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe["minus_di"] = ta.MINUS_DI(dataframe, timeperiod=14)

        # RSI
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # MACD
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]

        # SMA 200 for pair-level trend
        dataframe["sma200"] = ta.SMA(dataframe["close"], timeperiod=200)

        # ATR for volatility spike exits
        dataframe["atr_14"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_sma_50"] = dataframe["atr_14"].rolling(50).mean()

        # -- BTC Bear Regime Detection (4-of-6 rolling window) --
        btc_bear_single = (
            (dataframe["btc_usdt_close_1h"] < dataframe["btc_usdt_sma200_1h"])
            & (dataframe["btc_usdt_adx_1h"] > 25)
            & (dataframe["btc_usdt_rsi_1h"] < 45)
        ).astype(int)

        # BTC must also be declining (not just sitting below SMA200)
        btc_declining = (
            dataframe["btc_usdt_close_1h"] < dataframe["btc_usdt_close_1h"].shift(6)
        )

        # Require 4 out of 6 candles bearish AND BTC actively declining
        # (tolerates 1-2 candle flicker without losing regime signal)
        dataframe["btc_bear_confirmed"] = (
            (btc_bear_single.rolling(6).sum() >= 4)
            & btc_declining
        ).astype(int)

        # -- Regime Flip Detection (bear → bull transition) --
        # Previous candle was confirmed bear, current candle shows bullish flip
        dataframe["btc_was_bear"] = dataframe["btc_bear_confirmed"].shift(1).fillna(0)
        dataframe["btc_now_bull"] = (
            (dataframe["btc_usdt_close_1h"] > dataframe["btc_usdt_sma200_1h"])
            & (dataframe["btc_usdt_rsi_1h"] > 45)
        ).astype(int)
        dataframe["bear_to_bull"] = (
            (dataframe["btc_was_bear"] == 1)
            & (dataframe["btc_now_bull"] == 1)
        ).astype(int)

        # Volume ratio for bounce confirmation
        dataframe["volume_sma_20"] = dataframe["volume"].rolling(window=20).mean()
        dataframe["volume_ratio"] = dataframe["volume"] / (dataframe["volume_sma_20"] + 1e-10)

        return dataframe

    # -- Kill Switch -----------------------------------------------------------

    def _read_kill_switch(self) -> dict:
        try:
            if KILL_SWITCH_FILE.exists():
                return json.loads(KILL_SWITCH_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
        return {
            "daily_loss": 0.0,
            "daily_loss_date": datetime.now().strftime("%Y-%m-%d"),
            "consecutive_losses": 0,
            "killed": False,
        }

    def _write_kill_switch(self, data: dict):
        try:
            KILL_SWITCH_FILE.parent.mkdir(parents=True, exist_ok=True)
            KILL_SWITCH_FILE.write_text(json.dumps(data, indent=2))
        except OSError as e:
            logger.warning("Kill switch write failed: %s", e)

    def _is_killed(self) -> bool:
        ks = self._read_kill_switch()
        today = datetime.now().strftime("%Y-%m-%d")
        if ks.get("daily_loss_date") != today:
            ks["daily_loss"] = 0.0
            ks["daily_loss_date"] = today
            ks["killed"] = False
            ks["consecutive_losses"] = 0
            self._write_kill_switch(ks)
            return False
        return ks.get("killed", False)

    def _record_trade_result(self, profit_ratio: float):
        ks = self._read_kill_switch()
        today = datetime.now().strftime("%Y-%m-%d")
        if ks.get("daily_loss_date") != today:
            ks = {"daily_loss": 0.0, "daily_loss_date": today,
                  "consecutive_losses": 0, "killed": False}

        if profit_ratio < 0:
            ks["daily_loss"] = ks.get("daily_loss", 0.0) + abs(profit_ratio)
            ks["consecutive_losses"] = ks.get("consecutive_losses", 0) + 1
        else:
            ks["consecutive_losses"] = 0

        if ks["daily_loss"] >= DAILY_LOSS_LIMIT:
            ks["killed"] = True
            logger.warning("KILL SWITCH: Daily loss %.1f%% >= %.1f%% limit",
                           ks["daily_loss"] * 100, DAILY_LOSS_LIMIT * 100)
        if ks["consecutive_losses"] >= CONSECUTIVE_LOSS_LIMIT:
            ks["killed"] = True
            logger.warning("KILL SWITCH: %d consecutive losses", ks["consecutive_losses"])

        self._write_kill_switch(ks)

    # -- Entry Gate ------------------------------------------------------------

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag: str | None, side: str, **kwargs) -> bool:
        is_live = self.dp and self.dp.runmode.value in ("live", "dry_run")

        if is_live:
            if self._is_killed():
                logger.info("BLOCKED %s: Kill switch active", pair)
                return False

            bot_name = self.config.get("bot_name", "BearCrashShort")

            other_bots = PositionTracker.count_bots_holding(pair, exclude_bot=bot_name)
            if other_bots >= MAX_BOTS_PER_PAIR:
                logger.info("BLOCKED %s: %d other bots already hold this pair", pair, other_bots)
                return False

            # Anti-squeeze: block during deep capitulation (F&G <= 10)
            fg = FearGreedIndex.get()["value"]
            if fg <= 10:
                logger.info("BLOCKED %s: F&G capitulation (%d) - squeeze risk", pair, fg)
                return False

            PositionTracker.register(bot_name, pair, amount * rate)

        return True

    def confirm_trade_exit(self, pair: str, trade, order_type: str, amount: float,
                           rate: float, time_in_force: str, exit_reason: str,
                           current_time: datetime, **kwargs) -> bool:
        is_live = self.dp and self.dp.runmode.value in ("live", "dry_run")

        if is_live:
            bot_name = self.config.get("bot_name", "BearCrashShort")
            PositionTracker.unregister(bot_name, pair)

            if trade.close_profit is not None:
                self._record_trade_result(trade.close_profit)

        return True

    # -- Entry Signal ----------------------------------------------------------

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # -- BTC REGIME GATE (persistent bear) --
                (dataframe["btc_bear_confirmed"] == 1)

                # -- PAIR-LEVEL SIGNALS --
                & (dataframe["minus_di"] > dataframe["plus_di"])  # Bears dominating
                & (dataframe["adx"] > 25)                         # Confirmed trend
                & (dataframe["rsi"] > 40) & (dataframe["rsi"] < 70)  # Bear "overbought" zone
                & (dataframe["close"] < dataframe["sma200"])      # Below SMA200

                # -- ANTI-SQUEEZE FILTERS --
                & (dataframe["btc_usdt_rsi_1h"] > 20)            # BTC not at floor

                # -- VOLUME --
                & (dataframe["volume"] > 0)
            ),
            "enter_short",
        ] = 1

        # === BOUNCE LONG: Post-bear recovery (SMB Capital 5/5 track record) ===
        # Rare signal: only fires on the candle where bear regime flips to bullish
        dataframe.loc[
            (
                (dataframe["bear_to_bull"] == 1)
                & (dataframe["rsi"] > 40) & (dataframe["rsi"] < 70)
                & (dataframe["plus_di"] > dataframe["minus_di"])
                & (dataframe["volume_ratio"] >= 1.5)
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1

        return dataframe

    # -- Exit Signal -----------------------------------------------------------

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Bear regime ending
                (dataframe["btc_usdt_close_1h"] > dataframe["btc_usdt_sma200_1h"])
                # OR bulls taking over pair (2-candle confirmation to avoid DI flicker)
                | (
                    (dataframe["plus_di"] > dataframe["minus_di"])
                    & (dataframe["plus_di"].shift(1) > dataframe["minus_di"].shift(1))
                )
                # OR extremely oversold (bounce imminent)
                | (dataframe["rsi"] < 25)
                # OR volatility spike
                | (dataframe["atr_14"] > 2.5 * dataframe["atr_sma_50"])
            )
            & (dataframe["volume"] > 0),
            "exit_short",
        ] = 1

        return dataframe

    # -- Time-Based Exit -------------------------------------------------------

    def custom_exit(self, pair: str, trade, current_time, current_rate,
                    current_profit, **kwargs):
        if not trade.is_short:
            return None

        hours = (current_time - trade.open_date_utc).total_seconds() / 3600

        if hours >= 48:
            return "time_exit_48h"

        if hours >= 24 and current_profit > 0.02:
            return "time_profit_24h"

        if hours >= 36 and current_profit > 0:
            return "time_breakeven_36h"

        return None

    # -- Leverage --------------------------------------------------------------

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str | None,
                 side: str, **kwargs) -> float:
        return 2.0
