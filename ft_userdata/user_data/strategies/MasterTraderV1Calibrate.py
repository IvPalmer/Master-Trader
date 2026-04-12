"""
Calibration wrapper — replays historical Fear & Greed in backtest.

What's kept:
  - BTC SMA200 guard (already in populate_entry_trend, works natively)
  - Fear & Greed extreme greed block (replayed from historical API data)

What's bypassed:
  - PositionTracker (cross-bot state doesn't exist in backtest — correct to skip)
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from MasterTraderV1 import MasterTraderV1

logger = logging.getLogger(__name__)

# Historical Fear & Greed data file
FNG_CACHE_FILE = Path("/freqtrade/user_data/fear_greed_history.json")


class MasterTraderV1Calibrate(MasterTraderV1):

    _fng_data: dict = {}  # date_str -> value

    def bot_start(self, **kwargs):
        """Load historical Fear & Greed data on startup."""
        super().bot_start(**kwargs)
        self._load_fng_history()

    def _load_fng_history(self):
        """Load or download Fear & Greed historical data."""
        if FNG_CACHE_FILE.exists():
            try:
                with open(FNG_CACHE_FILE) as f:
                    self._fng_data = json.load(f)
                logger.info("Loaded %d days of F&G history from cache", len(self._fng_data))
                return
            except Exception:
                pass

        # Download from API
        try:
            import requests
            r = requests.get(
                "https://api.alternative.me/fng/?limit=0&format=json",
                timeout=30,
            )
            raw = r.json()["data"]
            self._fng_data = {}
            for entry in raw:
                ts = datetime.fromtimestamp(int(entry["timestamp"]))
                self._fng_data[ts.strftime("%Y-%m-%d")] = int(entry["value"])

            # Cache to disk
            with open(FNG_CACHE_FILE, "w") as f:
                json.dump(self._fng_data, f)
            logger.info("Downloaded and cached %d days of F&G history", len(self._fng_data))
        except Exception as e:
            logger.warning("Failed to load F&G history: %s — F&G gate disabled", e)

    def _get_fng_value(self, dt: datetime) -> int:
        """Get Fear & Greed value for a given date. Returns 50 (neutral) if unknown."""
        date_str = dt.strftime("%Y-%m-%d")
        return self._fng_data.get(date_str, 50)

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                            current_time, entry_tag, side, **kwargs):
        # Replay historical Fear & Greed gate
        if self._fng_data:
            fng_value = self._get_fng_value(current_time)
            if fng_value >= 80:
                logger.info("BLOCKED %s: Historical F&G=%d (extreme greed) on %s",
                            pair, fng_value, current_time.strftime("%Y-%m-%d"))
                return False

        # PositionTracker skipped — no cross-bot state in backtest
        return True

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate,
                           time_in_force, exit_reason, current_time, **kwargs):
        return True
