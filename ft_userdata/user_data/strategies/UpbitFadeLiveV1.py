"""UpbitFadeLiveV1 — live pilot of the Upbit KRW listing fade on Hyperliquid (#252).

The strategy generates no signals. Every entry comes from the host trigger
(research/upbit_fade_live/live_trigger.py) through Freqtrade's REST
`/forceenter`: one short per comparable event of the paper monitor
(research/upbit_fade_forward/, prereg upbit-krw-fade-forward-2026-11), at the
paper entry, t0 + 5 min. Live pilot prereg: upbit-krw-fade-live-pilot-2026-11.

Exits are Freqtrade's own, so they hold without the trigger running:

- **24 h time exit:** `minimal_roi` {"0": 100, "1440": -1}. Freqtrade 2026.7
  `IStrategy.min_roi_reached` takes the largest key <= the trade's age in
  minutes and exits when profit > that value. Before 1440 min the bar is
  +10000%; from 1440 min any profit above -100% exits at market. ROI is
  evaluated on every loop for every open trade (`should_exit`), with or
  without exit signals, so no `custom_exit` is involved (the fleet once ran a
  dead `custom_exit`, see the 2026-08-24 review).
- **Emergency stop:** -0.60, i.e. +60% adverse for a short at 1x, above the
  worst adverse move observed in Part C (+48.7%), so it does not change the
  tested 24 h rule. Exchange-resident when live (`stoploss_on_exchange` is
  switched on by the compose entrypoint only in live mode).
"""
from datetime import datetime
from typing import Optional

from freqtrade.strategy import IStrategy
from pandas import DataFrame


class UpbitFadeLiveV1(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "5m"        # arbitrary; no indicator is read
    can_short = True
    process_only_new_candles = True

    minimal_roi = {"0": 100, "1440": -1}
    stoploss = -0.60
    trailing_stop = False
    use_custom_stoploss = False
    use_exit_signal = False
    exit_profit_only = False
    position_adjustment_enable = False

    startup_candle_count = 10

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        return df

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["enter_long"] = 0
        df["enter_short"] = 0
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["exit_long"] = 0
        df["exit_short"] = 0
        return df

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        side: str,
        entry_tag: Optional[str] = None,
        **kwargs,
    ) -> float:
        """Always 1x. The trigger also sends leverage 1.0 on /forceenter, which
        Freqtrade uses instead of this callback when present."""
        return 1.0
