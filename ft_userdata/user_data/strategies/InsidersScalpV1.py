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

from freqtrade.strategy import IStrategy

logger = logging.getLogger(__name__)

RECEIVER_URL = os.getenv(
    "INSIDERS_RECEIVER_URL", "http://insiders-receiver:8089"
)
SL_CACHE_TTL_SEC = 30


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

    _sl_cache: dict = {}  # trade_id → (fetched_at_unix, current_sl_pct)

    def custom_stoploss(self, pair, trade, current_time, current_rate,
                        current_profit, **kwargs):
        """Fetch the live SL from the receiver's position graph and return
        it as a fractional offset from open_rate. Caches per trade_id for
        SL_CACHE_TTL_SEC to avoid hammering the receiver each candle.

        Returns None on any error (Freqtrade falls back to the static
        stoploss). This is fail-open in the sense that the position keeps
        its previous SL; the exchange-side SL placed at entry still
        protects against worst case.
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
            with urllib.request.urlopen(req, timeout=3) as resp:
                body = resp.read()
            data = json.loads(body)
            sl_price = data.get("current_sl")
            open_entry = data.get("open_entry")
            direction = (data.get("direction") or "").lower()
            if sl_price is None or open_entry is None or not direction:
                return None
            # Convert absolute SL price to fractional offset.
            # Freqtrade custom_stoploss expects a NEGATIVE float for any
            # stop (loss side). For long: (sl - entry) / entry (negative
            # if sl < entry). For short: (entry - sl) / entry.
            if direction == "long":
                sl_frac = (sl_price - open_entry) / open_entry
            else:
                sl_frac = (open_entry - sl_price) / open_entry
            # Sanity: must be negative (it's a STOP-loss)
            if sl_frac >= 0:
                logger.warning(
                    "custom_stoploss got non-negative SL for trade %s: sl=%s entry=%s dir=%s",
                    trade_id, sl_price, open_entry, direction,
                )
                return None
            self._sl_cache[trade_id] = (now, sl_frac)
            return sl_frac
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Position not in receiver graph (rare — could be a manual
                # trade or graph mismatch). Fall back to static SL.
                return None
            logger.warning("custom_stoploss receiver HTTP %d for trade %s", e.code, trade_id)
            return None
        except Exception as e:
            logger.warning("custom_stoploss error for trade %s: %s", trade_id, e)
            return None
