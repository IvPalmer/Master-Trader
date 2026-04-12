"""
Viability wrapper — applies dynamic pairlist + F&G for full-year backtest accuracy.

Viability asks: is this strategy profitable over a full market cycle?
Must simulate runtime filters to get realistic results.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from MasterTraderV1 import MasterTraderV1
from dynamic_pairlist_mixin import DynamicPairlistMixin

logger = logging.getLogger(__name__)
FNG_CACHE_FILE = Path("/freqtrade/user_data/fear_greed_history.json")


class MasterTraderV1Viability(DynamicPairlistMixin, MasterTraderV1):

    # Match live pairlist config
    PAIRLIST_VOLUME_MIN = 5_000_000
    PAIRLIST_VOLUME_TOP_N = 40
    PAIRLIST_VOLATILITY_MIN = 0.02
    PAIRLIST_VOLATILITY_MAX = 0.60
    PAIRLIST_RANGE_MIN = 0.02
    PAIRLIST_RANGE_MAX = 0.45

    _fng_data: dict = {}

    def bot_start(self, **kwargs):
        super().bot_start(**kwargs)
        if FNG_CACHE_FILE.exists():
            try:
                with open(FNG_CACHE_FILE) as f:
                    self._fng_data = json.load(f)
                logger.info("F&G: %d days loaded", len(self._fng_data))
            except Exception:
                pass

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                            current_time, entry_tag, side, **kwargs):
        if self._fng_data:
            fng = self._fng_data.get(current_time.strftime("%Y-%m-%d"), 50)
            if fng >= 80:
                return False

        if not self.passes_dynamic_pairlist(pair, current_time):
            return False

        return True

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate,
                           time_in_force, exit_reason, current_time, **kwargs):
        return True
