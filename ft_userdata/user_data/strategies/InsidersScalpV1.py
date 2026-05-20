"""InsidersScalpV1 — pure pass-through strategy for the Insiders Scalp copy
trader.

Has NO own entry signals. Has NO ROI table (ceiling-disabled). Has NO own
stoploss logic (signals come from the receiver via custom_stoploss reads).
Every position is opened via Freqtrade REST `forceenter` and closed via
`forceexit` calls from the insiders-receiver service.

This file exists because Freqtrade requires *some* strategy. We use the
INTERFACE_VERSION 3 minimum surface area + a `custom_stoploss` that reads
the live SL from the receiver's position graph (queried via REST when
present, falling back to a sane initial value).

Live trade ownership is fully external — receiver places it, receiver
moves SL, receiver closes it. Freqtrade is dumb execution.
"""
import logging
from pandas import DataFrame

from freqtrade.strategy import IStrategy

logger = logging.getLogger(__name__)


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

    def custom_stoploss(self, pair, trade, current_time, current_rate,
                        current_profit, **kwargs):
        """Pull live SL from the receiver's position graph if available,
        else fall back to the safety stoploss.

        TODO (not blocking initial dry-run): query receiver REST at startup
        and cache per (pair, trade.id). For now, returns None (use static
        stoploss) so the bot still runs.
        """
        return None
