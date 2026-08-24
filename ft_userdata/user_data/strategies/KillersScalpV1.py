"""KillersScalpV1 — pure REST-driven copy-trader strategy.

This strategy does NOT generate its own signals. All entries and exits
come from the killers-receiver service via Freqtrade's REST API
(`/forceenter`, `/forceexit`). The strategy methods below are minimal
pass-throughs that prevent automatic trading decisions.

The bot's only job is to:
  1. Maintain OHLCV data subscriptions for the pair_whitelist (so when
     a force_enter arrives, current price + history is available).
  2. Execute REST-issued orders against the configured live/dry wallet.
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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
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

    # Channel exits still drive normal closes. The receiver embeds the posted
    # stop in entry_tag; custom_stoploss turns it into Freqtrade's native
    # exchange-resident stop while the receiver remains a second exit path.
    minimal_roi = {"0": 100}        # 100x profit before ROI exit (never hit)
    stoploss = -0.07
    trailing_stop = False
    use_custom_stoploss = True
    use_exit_signal = False         # explicit: REST drives all exits
    exit_profit_only = False

    # Default leverage. Receiver may override per-trade via force_enter.
    leverage_amount = 3.0

    startup_candle_count = 10
    _sl_cache: dict[int, float] = {}
    _sl_cache_updated: dict[int, float] = {}
    _sl_refreshing: set[int] = set()
    _sl_lock = Lock()
    _sl_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="killers-sl")
    _sl_refresh_ttl_sec = 30.0
    _sl_cache_max_entries = 128

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

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        """Reject an entry Freqtrade would otherwise round above its risk cap.

        The receiver has already sized the order from the effective entry and
        adverse stop-limit fill. Returning zero here is the final fail-closed
        backstop when the venue minimum is larger than that approved margin.
        """
        if min_stake is not None and proposed_stake < min_stake:
            logger.warning(
                "Rejecting %s %s stake %.4f below venue minimum %.4f",
                pair, side, proposed_stake, min_stake,
            )
            return 0.0
        return min(proposed_stake, max_stake)

    @staticmethod
    def _tagged_stop(trade) -> Optional[float]:
        """Read the immutable posted stop embedded by the receiver at entry."""
        tag = getattr(trade, "enter_tag", None) or getattr(trade, "entry_tag", None)
        if not isinstance(tag, str):
            return None
        for part in tag.split("|"):
            if not part.startswith("sl:"):
                continue
            try:
                value = float(part[3:])
            except (TypeError, ValueError):
                return None
            return value if value > 0 else None
        return None

    @staticmethod
    def _fetch_receiver_stop(trade_id: int) -> Optional[float]:
        """Fetch the latest absolute stop; always called off the bot loop."""
        try:
            request = urllib.request.Request(
                f"{RECEIVER_URL}/position/by_ft_id/{trade_id}",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=0.5) as response:
                payload = json.load(response)
            sl_price = payload.get("current_sl")
            if not isinstance(sl_price, (int, float)) or sl_price <= 0:
                return None
            return float(sl_price)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                logger.warning("Receiver SL HTTP %s for trade %s", exc.code, trade_id)
            return None
        except Exception as exc:
            logger.info("Receiver SL fallback for trade %s: %s", trade_id, exc)
            return None

    def _schedule_stop_refresh(self, trade_id: int) -> None:
        """Refresh receiver state asynchronously without delaying trading."""
        now = time.monotonic()
        with self._sl_lock:
            updated = self._sl_cache_updated.get(trade_id, 0.0)
            if updated and now - updated < self._sl_refresh_ttl_sec:
                return
            if trade_id in self._sl_refreshing:
                return
            self._sl_refreshing.add(trade_id)
        future = self._sl_executor.submit(self._fetch_receiver_stop, trade_id)

        def done(completed) -> None:
            try:
                sl_price = completed.result()
                if sl_price is not None:
                    with self._sl_lock:
                        self._sl_cache[trade_id] = sl_price
                        self._sl_cache_updated[trade_id] = time.monotonic()
                        if len(self._sl_cache) > self._sl_cache_max_entries:
                            oldest = min(
                                self._sl_cache,
                                key=lambda key: self._sl_cache_updated.get(key, 0.0),
                            )
                            self._sl_cache.pop(oldest, None)
                            self._sl_cache_updated.pop(oldest, None)
            except Exception as exc:
                logger.info("Receiver SL refresh failed for trade %s: %s", trade_id, exc)
            finally:
                with self._sl_lock:
                    self._sl_refreshing.discard(trade_id)

        future.add_done_callback(done)

    def custom_stoploss(
        self,
        pair,
        trade,
        current_time,
        current_rate,
        current_profit,
        after_fill: bool,
        **kwargs,
    ):
        """Maintain the signal's absolute posted SL without accidental trailing.

        ``after_fill`` is explicit because Freqtrade only permits widening the
        initial -7% catastrophe floor to the posted stop in that callback. The
        entry tag makes this deterministic before the receiver lookup finishes.
        """
        trade_id = int(trade.id)
        with self._sl_lock:
            sl_price = self._sl_cache.get(trade_id)
        if sl_price is None:
            sl_price = self._tagged_stop(trade)
            if sl_price is not None:
                with self._sl_lock:
                    self._sl_cache[trade_id] = sl_price
                    # A tag is an immediate deterministic fallback, but it is
                    # not proof the receiver has no newer moved stop. Leave it
                    # due for one asynchronous refresh.
                    self._sl_cache_updated[trade_id] = 0.0
        self._schedule_stop_refresh(trade_id)
        if sl_price is None:
            return None
        if (not trade.is_short and sl_price >= current_rate) or (
            trade.is_short and sl_price <= current_rate
        ):
            logger.warning(
                "Posted SL %s already breached at rate %s for trade %s",
                sl_price, current_rate, trade_id,
            )
            return None
        # Recompute from the SAME absolute price on every tick. Caching the
        # relative value would silently turn a fixed stop into a trailing stop.
        return stoploss_from_absolute(
            stop_rate=sl_price,
            current_rate=current_rate,
            is_short=trade.is_short,
            leverage=trade.leverage or 1.0,
        )
