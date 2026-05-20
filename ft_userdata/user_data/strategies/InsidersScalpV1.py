"""InsidersScalpV1 — pure pass-through strategy for the Insiders Scalp copy
trader.

Has NO own entry signals. Has NO ROI table (ceiling-disabled). Has NO own
stoploss logic — `custom_stoploss` pulls the live per-trade SL from the
insiders-receiver's position graph via HTTP GET. Receiver maintains the
authoritative SL; this strategy is dumb execution.

Live trade ownership is fully external — receiver places it (forceenter),
receiver moves SL (custom_stoploss reads receiver), receiver closes it
(forceexit). Freqtrade just translates that into exchange orders.

Env vars (set in docker-compose):
  INSIDERS_RECEIVER_URL — receiver base URL (default http://insiders-receiver:8089)
"""
import logging
import os
import time
import urllib.error
import urllib.request
import json

from pandas import DataFrame

from freqtrade.strategy import IStrategy, stoploss_from_absolute

logger = logging.getLogger(__name__)

RECEIVER_URL = os.getenv(
    "INSIDERS_RECEIVER_URL", "http://insiders-receiver:8089"
)
# Aggressive cache so receiver isn't hit every candle. The receiver pushes
# SL changes within ~1s of the message, so 60s of staleness is acceptable
# (worst case: bot's SL is up to 60s behind the receiver's view).
SL_CACHE_TTL_SEC = 60
# Hard receiver timeout — must NOT stall Freqtrade's tick loop. If receiver
# is slow/down, fall back to static stoploss until next candle.
SL_HTTP_TIMEOUT_SEC = 0.5


class InsidersScalpV1(IStrategy):
    INTERFACE_VERSION: int = 3

    # No ROI ceiling — exits are entirely receiver-driven via forceexit.
    minimal_roi = {"0": 100.0}    # effectively disabled

    # Initial stoploss; the receiver moves it per signal via /custom_stoploss
    # hook (TODO: implement live SL push from receiver to strategy).
    stoploss = -0.10              # safety net only — actual SL is per-trade

    trailing_stop = False
    use_custom_stoploss = True
    use_exit_signal = False
    can_short = True              # FUTURES mode — required for shorts

    timeframe = "5m"              # arbitrary; we don't generate signals
    process_only_new_candles = True

    startup_candle_count = 50

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # No own entries — receiver uses /forceenter
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # No own exits — receiver uses /forceexit
        return dataframe

    _sl_cache: dict = {}  # trade_id → (fetched_at_unix, sl_relative_pct)

    def custom_stoploss(self, pair, trade, current_time, current_rate,
                        current_profit, **kwargs):
        """Fetch the live SL from the receiver and convert to Freqtrade's
        expected form (a POSITIVE fractional offset relative to current_rate;
        Freqtrade internally applies abs() and the side via is_short).

        Per Freqtrade docs (strategy-callbacks): use stoploss_from_absolute()
        to convert an absolute SL price; it handles is_short + leverage.

        We additionally validate that sl_price is on the CORRECT SIDE of
        current_rate before conversion. A wrong-side stop (e.g. signal SL
        above entry on a short) would convert to a value that triggers
        immediately on the next tick. Fail-safe: return None and let the
        static -10% safety stoploss + exchange-side SL handle protection.

        Hard 500ms timeout. Cache for 60s. Failures return None → Freqtrade
        uses static stoploss; exchange-side SL at entry still protects.
        """
        trade_id = trade.id
        cached = self._sl_cache.get(trade_id)
        now = time.time()
        if cached and now - cached[0] < SL_CACHE_TTL_SEC:
            return cached[1]

        try:
            req = urllib.request.Request(
                f"{RECEIVER_URL}/position/by_ft_id/{trade_id}",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=SL_HTTP_TIMEOUT_SEC) as resp:
                body = resp.read()
            data = json.loads(body)
            sl_price = data.get("current_sl")
            if sl_price is None or not isinstance(sl_price, (int, float)):
                return None
            sl_price = float(sl_price)

            # Validate the SL is on the correct side of current_rate BEFORE
            # conversion. If the receiver pushed a logically-invalid SL (e.g.
            # signaled SL ABOVE entry on a short) the conversion would yield
            # a stop that triggers immediately. Fail-safe: keep static SL.
            #
            # Per Freqtrade docs, custom_stoploss returns a POSITIVE value
            # (Freqtrade takes abs(return) internally). stoploss_from_absolute
            # handles the is_short + leverage math; we just hand it the price.
            if not trade.is_short and sl_price >= current_rate:
                logger.warning(
                    "custom_stoploss long-side SL price %s >= current %s for trade %s — keeping static SL",
                    sl_price, current_rate, trade_id,
                )
                return None
            if trade.is_short and sl_price <= current_rate:
                logger.warning(
                    "custom_stoploss short-side SL price %s <= current %s for trade %s — keeping static SL",
                    sl_price, current_rate, trade_id,
                )
                return None

            sl_rel = stoploss_from_absolute(
                stop_rate=sl_price,
                current_rate=current_rate,
                is_short=trade.is_short,
                leverage=trade.leverage or 1.0,
            )
            if sl_rel is None:
                return None
            self._sl_cache[trade_id] = (now, sl_rel)
            return sl_rel
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Position not in receiver graph (rare — manual trade or
                # graph mismatch). Fall back to static SL.
                return None
            logger.warning("custom_stoploss receiver HTTP %d for trade %s", e.code, trade_id)
            return None
        except Exception as e:
            # Includes timeouts. Don't spam logs — INFO once per cache TTL.
            logger.info("custom_stoploss fallback (trade %s): %s", trade_id, e)
            return None
