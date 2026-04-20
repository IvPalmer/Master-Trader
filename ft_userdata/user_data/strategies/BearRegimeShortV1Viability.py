"""
BearRegimeShortV1 Viability wrapper — dynamic pairlist + F&G for calibration.

Mirrors FundingShortV1Viability (also futures + 2x leverage).
See feedback_viability_wrapper_mandatory.md.
"""
import json
import logging
from pathlib import Path

from BearRegimeShortV1 import BearRegimeShortV1
from dynamic_pairlist_mixin import DynamicPairlistMixin

logger = logging.getLogger(__name__)
FNG_CACHE_FILE = Path("/freqtrade/user_data/fear_greed_history.json")


class BearRegimeShortV1Viability(DynamicPairlistMixin, BearRegimeShortV1):

    # Match FundingShort live config (looser for futures universe)
    PAIRLIST_VOLUME_MIN = 20_000_000
    PAIRLIST_VOLUME_TOP_N = 20
    PAIRLIST_VOLATILITY_MIN = 0.02
    PAIRLIST_VOLATILITY_MAX = 0.50
    PAIRLIST_RANGE_MIN = 0.02
    PAIRLIST_RANGE_MAX = 0.40

    _fng_data: dict = {}

    def bot_start(self, **kwargs):
        super().bot_start(**kwargs)
        if FNG_CACHE_FILE.exists():
            try:
                with open(FNG_CACHE_FILE) as f:
                    self._fng_data = json.load(f)
                logger.info("F&G history loaded: %d days", len(self._fng_data))
            except Exception:
                pass

    def _fng_at(self, current_time):
        if not self._fng_data:
            return 50
        key = current_time.strftime("%Y-%m-%d")
        return int(self._fng_data.get(key, {}).get("value", 50))

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                            current_time, entry_tag, side, **kwargs):
        # Dynamic pairlist gate
        if not self.passes_dynamic_pairlist(pair, current_time):
            return False
        # Anti-squeeze F&G gate — skip during max-fear capitulation
        fng = self._fng_at(current_time)
        if fng < 15:
            return False
        return True

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate,
                           time_in_force, exit_reason, current_time, **kwargs):
        return True
