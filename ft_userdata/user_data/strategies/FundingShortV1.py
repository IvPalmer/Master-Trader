"""
FundingShortV1 — Funding rate crowded-long fade (SHORT side).

Mirror of FundingFadeV1 for bear coverage. When perpetual futures funding rate
rises to extreme positive (crowded longs paying shorts heavily), open SHORT position
expecting mean-reversion squeeze of over-leveraged longs.

Signal:
  - Entry: Funding rate > (rolling_mean + 1 std) over 500 periods
  - Confirm: ADX > 25 (trending market) AND Volume > 1.5x SMA20
  - Gate: BTC BELOW SMA50 OR BTC RSI < 40 (bearish/weak regime)
  - Exit: ROI-only (no trailing); -5% stoploss

Trading mode: futures (required for shorts)
Leverage: 2x (conservative)

Thesis: funding is a real-money signal of crowded positioning. Extreme positive
= longs paying shorts heavily = late-cycle euphoria = short squeeze setup.
Mirror of FundingFadeV1 which captured the LONG side of this mean-reversion.

Requires proper 3.3yr backtest with futures 1m data before production. 1h-only
validation is preliminary.

Generated 2026-04-17.
"""
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import talib.abstract as ta
from freqtrade.strategy import IStrategy, informative
from pandas import DataFrame

logger = logging.getLogger(__name__)
FUNDING_DIR = Path("/freqtrade/user_data/data/binance/funding")


class FundingShortV1(IStrategy):
    INTERFACE_VERSION: int = 3

    # Futures short config
    can_short = True
    trading_mode = "futures"

    minimal_roi = {
        "0":    0.06,
        "360":  0.04,
        "720":  0.03,
        "1440": 0.02,
    }

    stoploss = -0.05
    trailing_stop = False
    use_custom_stoploss = False

    timeframe = "1h"
    process_only_new_candles = True
    use_exit_signal = False
    exit_profit_only = True
    exit_profit_offset = 0.01

    startup_candle_count = 200

    funding_lookback = 500
    adx_threshold = 25
    vol_multiplier = 1.5
    btc_sma_period = 50
    btc_rsi_weak_threshold = 40

    _funding_cache: dict = {}

    def leverage(self, pair, current_time, current_rate, proposed_leverage,
                 max_leverage, entry_tag, side, **kwargs):
        return min(2.0, max_leverage)  # 2x leverage

    @informative("1h", "BTC/USDT:USDT")
    def populate_indicators_btc_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["sma50"] = dataframe["close"].rolling(self.btc_sma_period).mean()
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]

        funding = self._get_aligned_funding(pair, dataframe)
        dataframe["funding_rate"] = funding

        roll_mean = dataframe["funding_rate"].rolling(self.funding_lookback, min_periods=50).mean()
        roll_std = dataframe["funding_rate"].rolling(self.funding_lookback, min_periods=50).std()
        dataframe["funding_above_mean"] = (
            dataframe["funding_rate"] > (roll_mean + roll_std)
        ).astype(int)

        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["vol_sma"] = dataframe["volume"].rolling(20).mean()

        # Bearish or weak BTC regime
        btc_close_col = "btc_usdt_close_1h"
        btc_sma_col = "btc_usdt_sma50_1h"
        btc_rsi_col = "btc_usdt_rsi_1h"
        dataframe["btc_weak"] = (
            (dataframe[btc_close_col] < dataframe[btc_sma_col])
            | (dataframe[btc_rsi_col] < self.btc_rsi_weak_threshold)
        ).astype(int)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["funding_above_mean"] == 1)
                & (dataframe["adx"] > self.adx_threshold)
                & (dataframe["volume"] > self.vol_multiplier * dataframe["vol_sma"])
                & (dataframe["btc_weak"] == 1)
                & (dataframe["volume"] > 0)
            ),
            "enter_short",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    # ── Funding loader (shared pattern w/ FundingFadeV1) ──

    def _get_aligned_funding(self, pair: str, dataframe: DataFrame) -> pd.Series:
        # Strip futures suffix from pair for funding lookup (BTC/USDT:USDT → BTC/USDT)
        lookup_pair = pair.split(":")[0]
        if lookup_pair in self._funding_cache:
            return self._align_to_dataframe(self._funding_cache[lookup_pair], dataframe)

        pair_file = lookup_pair.replace("/", "_")
        path = FUNDING_DIR / f"{pair_file}-funding.feather"
        if not path.exists():
            logger.warning("No funding data for %s (lookup %s)", pair, lookup_pair)
            self._funding_cache[lookup_pair] = None
            return pd.Series(np.nan, index=dataframe.index)

        try:
            fdf = pd.read_feather(path)
            fdf["ts"] = fdf["date"].apply(lambda x: x.timestamp())
            fdf = fdf.sort_values("ts").reset_index(drop=True)
            self._funding_cache[lookup_pair] = fdf
            return self._align_to_dataframe(fdf, dataframe)
        except Exception as e:
            logger.warning("Funding load failed for %s: %s", pair, e)
            return pd.Series(np.nan, index=dataframe.index)

    def _align_to_dataframe(self, funding_df, dataframe) -> pd.Series:
        if funding_df is None or funding_df.empty:
            return pd.Series(np.nan, index=dataframe.index)
        pair_ts = dataframe["date"].apply(lambda x: x.timestamp()).values
        funding_ts = funding_df["ts"].values
        funding_rates = funding_df["funding_rate"].values
        idx = np.searchsorted(funding_ts, pair_ts, side="right") - 1
        idx = np.clip(idx, 0, len(funding_rates) - 1)
        return pd.Series(funding_rates[idx], index=dataframe.index)
