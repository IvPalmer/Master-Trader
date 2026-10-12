"""Backtest-only variants of FundingFadeV1 for the GH #28 causal-funding control.
NOT for live/dry use: each refuses to run outside backtesting.

Each variant inherits the deployed strategy unchanged and replaces only the
``funding_below_mean`` column that populate_entry_trend reads. Exits, ROI,
stop, protections, macro gate, ADX/volume/price-reversal terms are identical.

  FundingFadeV1PriceOnly  - funding term always passes.
  FundingFadeV1LaggedFunding - real term on funding delayed 21 days.
  FundingFadeV1Placebo01..20 - seeded coin flip at the real term's pass rate.

Copy next to the deployed FundingFadeV1.py in a research user_data/strategies dir
(together with ff_controls.py) and run with the live-matched config.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from FundingFadeV1 import FundingFadeV1  # noqa: E402
from ff_controls import lagged_funding_term, placebo_term, price_only_term  # noqa: E402


class _BacktestOnly(FundingFadeV1):
    def _replace(self, dataframe, pair):
        raise NotImplementedError

    def populate_indicators(self, dataframe, metadata):
        if self.dp is not None and self.dp.runmode.value in ("live", "dry_run"):
            raise RuntimeError(f"{type(self).__name__} is a research backtest variant; never run live/dry")
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe["funding_below_mean"] = self._replace(dataframe, metadata["pair"]).to_numpy()
        return dataframe


class FundingFadeV1PriceOnly(_BacktestOnly):
    def _replace(self, dataframe, pair):
        return price_only_term(dataframe.index)


class FundingFadeV1LaggedFunding(_BacktestOnly):
    def _replace(self, dataframe, pair):
        return lagged_funding_term(dataframe["funding_rate"])


def _make_placebo(seed):
    class _P(_BacktestOnly):
        def _replace(self, dataframe, pair):
            return placebo_term(dataframe["funding_below_mean"], pair, seed)
    _P.__name__ = f"FundingFadeV1Placebo{seed:02d}"
    return _P


for _seed in range(1, 21):
    _cls = _make_placebo(_seed)
    globals()[_cls.__name__] = _cls
