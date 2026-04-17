"""
KeltnerBounceV1 Viability wrapper — applies dynamic pairlist + F&G history
for backtest accuracy matching live bot behavior.

Without these filters, backtest can include stablecoin pairs (U, USD1, XUSD)
and low-volume pairs that live's VolumePairList + VolatilityFilter would exclude.
This produces misleading results — see MT calibration: raw backtest +0.81% vs
Viability wrapper +3.60% vs live +4.20% on Mar 11-Apr 11 window.

Use this wrapper for:
  - Calibration (compare live vs backtest)
  - Viability screening (3.3yr edge test)
  - Walk-forward validation
  - Any backtest where pairlist/F&G filters matter

Run live deployments with the raw KeltnerBounceV1 class — live uses real
VolumePairList/VolatilityFilter which don't need simulation.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from KeltnerBounceV1 import KeltnerBounceV1
from dynamic_pairlist_mixin import DynamicPairlistMixin

logger = logging.getLogger(__name__)
FNG_CACHE_FILE = Path("/freqtrade/user_data/fear_greed_history.json")


class KeltnerBounceV1Viability(DynamicPairlistMixin, KeltnerBounceV1):

    # Match live pairlist config exactly (from ft_userdata/user_data/configs/KeltnerBounceV1.json)
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
                logger.info("F&G history loaded: %d days", len(self._fng_data))
            except Exception:
                pass

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                            current_time, entry_tag, side, **kwargs):
        # F&G gate — KeltnerBounce doesn't use F&G directly but live config's
        # VolumePairList filters respond to market regime. Keep as a sanity check.
        # (Not blocking — pure pass-through here since Keltner logic is self-contained)

        # Dynamic pairlist gate — mirrors live VolumePairList + VolatilityFilter
        if not self.passes_dynamic_pairlist(pair, current_time):
            return False

        return True

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate,
                           time_in_force, exit_reason, current_time, **kwargs):
        return True
