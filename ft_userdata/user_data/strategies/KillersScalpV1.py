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
import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Optional

from freqtrade.strategy import IStrategy, stoploss_from_absolute
from pandas import DataFrame


logger = logging.getLogger(__name__)
RECEIVER_URL = os.getenv("SIGNAL_RECEIVER_URL", "http://killers-receiver:8089")


class KillersScalpV1(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "5m"        # arbitrary; we never read indicators from it
    can_short = True        # futures: shorts allowed
    process_only_new_candles = True

    # Channel exits still drive normal closes. V2 adds a catastrophe floor
    # plus the receiver's per-signal posted stop as an exchange-managed stop.
    minimal_roi = {"0": 100}        # 100x profit before ROI exit (never hit)
    stoploss = -0.07
    trailing_stop = False
    use_custom_stoploss = True
    use_exit_signal = False         # explicit: REST drives all exits
    exit_profit_only = False

    # Default leverage. Receiver may override per-trade via force_enter.
    leverage_amount = 3.0

    startup_candle_count = 10
    _sl_cache: dict = {}

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
        """Honor receiver-requested leverage while enforcing the V2 cap."""
        return min(max(1.0, proposed_leverage), self.leverage_amount, max_leverage)

    def custom_stoploss(
        self, pair, trade, current_time, current_rate, current_profit, **kwargs
    ):
        """Pull the signal's posted SL from the receiver with a short cache."""
        now = time.time()
        cached = self._sl_cache.get(trade.id)
        if cached and now - cached[0] < 30:
            return cached[1]
        try:
            request = urllib.request.Request(
                f"{RECEIVER_URL}/position/by_ft_id/{trade.id}",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=0.5) as response:
                payload = json.load(response)
            sl_price = payload.get("current_sl")
            if not isinstance(sl_price, (int, float)) or sl_price <= 0:
                return None
            sl_price = float(sl_price)
            if (not trade.is_short and sl_price >= current_rate) or (
                trade.is_short and sl_price <= current_rate
            ):
                logger.warning(
                    "Ignoring wrong-side receiver SL %s at rate %s for trade %s",
                    sl_price, current_rate, trade.id,
                )
                return None
            relative = stoploss_from_absolute(
                stop_rate=sl_price,
                current_rate=current_rate,
                is_short=trade.is_short,
                leverage=trade.leverage or 1.0,
            )
            if relative is not None:
                self._sl_cache[trade.id] = (now, relative)
            return relative
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                logger.warning("Receiver SL HTTP %s for trade %s", exc.code, trade.id)
            return None
        except Exception as exc:
            logger.info("Receiver SL fallback for trade %s: %s", trade.id, exc)
            return None
