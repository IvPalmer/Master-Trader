"""Backtest-only exit-stack variants of KeltnerBounceV1 (GH #28). NOT for live/dry.

Entry terms, universe, protections and BTC gate are inherited unchanged; each
variant changes only the exit stack, so differences are attributable to exits.
All variants are declared in the preregistration before any run and ALL are reported.

  KeltnerExitV2   - the deployed stack (control; must reproduce KeltnerBounceV1).
  KeltnerExitV1   - pre-2026-08-23 floor: stoploss -7%.
  KeltnerExitNoTrail - trailing off, same ROI table and -6% stop.
  KeltnerExitNoStale - without the 120h underwater stale-bounce exit.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from KeltnerBounceV1 import KeltnerBounceV1  # noqa: E402


class _BacktestOnly(KeltnerBounceV1):
    def populate_indicators(self, dataframe, metadata):
        if self.dp is not None and self.dp.runmode.value in ("live", "dry_run"):
            raise RuntimeError(f"{type(self).__name__} is a research backtest variant; never run live/dry")
        return super().populate_indicators(dataframe, metadata)


class KeltnerExitV2(_BacktestOnly):
    pass


class KeltnerExitV1(_BacktestOnly):
    stoploss = -0.07


class KeltnerExitNoTrail(_BacktestOnly):
    trailing_stop = False


class KeltnerExitNoStale(_BacktestOnly):
    def custom_exit(self, *args, **kwargs):
        return None
