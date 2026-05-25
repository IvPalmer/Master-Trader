"""KillersScalpV1 — pure REST-driven copy-trader strategy.

This strategy does NOT generate its own signals. All entries and exits
come from the killers-receiver service via Freqtrade's REST API
(`/forceenter`, `/forceexit`). The strategy methods below are minimal
pass-throughs that prevent automatic trading decisions.

The bot's only job is to:
  1. Maintain OHLCV data subscriptions for the pair_whitelist (so when
     a force_enter arrives, current price + history is available).
  2. Execute REST-issued orders against the dry-run wallet.
  3. Track positions, fire webhook events on entry/exit/cancel.

Why pass-through?  This bot mirrors a Telegram-channel signaler. The
classifier + receiver own all signal logic. The Freqtrade layer is
pure execution + bookkeeping. Same pattern as the insiders-scalp
template (services/insiders-receiver/).
"""
from datetime import datetime
from typing import Optional

from freqtrade.strategy import IStrategy
from pandas import DataFrame


class KillersScalpV1(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "5m"        # arbitrary; we never read indicators from it
    can_short = True        # futures: shorts allowed
    process_only_new_candles = True

    # ROI / stoploss are unused (closes driven by REST), but Freqtrade
    # requires both. Set permissive so we never auto-close.
    minimal_roi = {"0": 100}        # 100x profit before ROI exit (never hit)
    stoploss = -0.99                # -99% stoploss (never hit)
    trailing_stop = False
    use_custom_stoploss = False
    use_exit_signal = False         # explicit: REST drives all exits
    exit_profit_only = False

    # Default leverage. Receiver may override per-trade via force_enter.
    leverage_amount = 5.0

    startup_candle_count = 10

    # ── pass-through indicators / signals ──────────────────────────────

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        return df

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        # No automatic entries — everything driven by REST /forceenter.
        df["enter_long"] = 0
        df["enter_short"] = 0
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        # No automatic exits — everything driven by REST /forceexit.
        df["exit_long"] = 0
        df["exit_short"] = 0
        return df

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        side: str,
        entry_tag: Optional[str] = None,
        **kwargs,
    ) -> float:
        """Cap leverage at the configured default."""
        return min(self.leverage_amount, max_leverage)
