"""FundingFadeV1 Viability wrapper — see feedback_viability_wrapper_mandatory."""
import json
import logging
from pathlib import Path

from FundingFadeV1 import FundingFadeV1
from dynamic_pairlist_mixin import DynamicPairlistMixin

logger = logging.getLogger(__name__)
FNG_CACHE_FILE = Path("/freqtrade/user_data/fear_greed_history.json")


class FundingFadeV1Viability(DynamicPairlistMixin, FundingFadeV1):
    PAIRLIST_VOLUME_MIN = 5_000_000
    PAIRLIST_VOLUME_TOP_N = 40
    PAIRLIST_VOLATILITY_MIN = 0.03
    PAIRLIST_VOLATILITY_MAX = 0.75
    PAIRLIST_RANGE_MIN = 0.03
    PAIRLIST_RANGE_MAX = 0.50

    _fng_data: dict = {}

    def bot_start(self, **kwargs):
        super().bot_start(**kwargs)
        if FNG_CACHE_FILE.exists():
            try:
                with open(FNG_CACHE_FILE) as f:
                    self._fng_data = json.load(f)
            except Exception:
                pass

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                            current_time, entry_tag, side, **kwargs):
        if not self.passes_dynamic_pairlist(pair, current_time):
            return False
        return True

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate,
                           time_in_force, exit_reason, current_time, **kwargs):
        return True
