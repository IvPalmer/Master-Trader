"""
FundingShortV1 Viability wrapper — applies dynamic pairlist + F&G history
for backtest accuracy matching live bot behavior.

FundingShort is a futures SHORT strategy, so the pairlist filters operate on
futures pairs (BTC/USDT:USDT etc.). The DynamicPairlistMixin is pair-format
agnostic — it queries `self.dp.current_whitelist()` which already contains
the correct futures suffixes.

Live config (configs/FundingShortV1.json):
  - VolumePairList: 20 assets, min_value=20M, lookback=3d 1d candles
  - VolatilityFilter: 14d, min=0.02, max=0.5
  - RangeStabilityFilter: 10d, min=0.02, max=0.4

These filter settings are LOOSER than FundingFade/Keltner (which use 5M min,
0.03/0.75/0.03/0.50). We match live config exactly below.

See feedback_viability_wrapper_mandatory.md for full rationale.
"""
import json
import logging
from pathlib import Path

from FundingShortV1 import FundingShortV1
from dynamic_pairlist_mixin import DynamicPairlistMixin

logger = logging.getLogger(__name__)
FNG_CACHE_FILE = Path("/freqtrade/user_data/fear_greed_history.json")


class FundingShortV1Viability(DynamicPairlistMixin, FundingShortV1):

    # Match live pairlist config exactly (configs/FundingShortV1.json)
    PAIRLIST_VOLUME_MIN = 20_000_000      # Live: min_value=20M
    PAIRLIST_VOLUME_TOP_N = 20            # Live: number_assets=20
    PAIRLIST_VOLATILITY_MIN = 0.02        # Live: min_volatility=0.02
    PAIRLIST_VOLATILITY_MAX = 0.50        # Live: max_volatility=0.5
    PAIRLIST_RANGE_MIN = 0.02             # Live: min_rate_of_change=0.02
    PAIRLIST_RANGE_MAX = 0.40             # Live: max_rate_of_change=0.4

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

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                            current_time, entry_tag, side, **kwargs):
        # Dynamic pairlist gate — mirrors live VolumePairList + VolatilityFilter + RangeStabilityFilter
        if not self.passes_dynamic_pairlist(pair, current_time):
            return False
        return True

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate,
                           time_in_force, exit_reason, current_time, **kwargs):
        return True
