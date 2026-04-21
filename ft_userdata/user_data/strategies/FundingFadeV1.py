"""
FundingFadeV1 — Funding rate divergence entry with TA confirmation.

Discovered via Strategy Lab expanded sweep on 3.3 years of 1m-detail data.
First non-TA-based strategy validated. Orthogonal edge to Keltner/EMA systems.

Signal:
  - Entry: Funding rate drops 1+ std below its 500-period rolling mean
    (crowded-short sentiment → reversion setup)
  - Confirm: ADX > 25 (trending market filter)
    AND Volume > 1.5x 20-period SMA (liquidity confirmation)
  - Gate: BTC above 50 AND 200 SMA (macro trend alignment)
  - Exit: ROI-only profile (trailing removed — confirmed trailing noise in 1m)

Lab-validated metrics (3.3yr 1m-detail):
  - 431 trades, WR 65.7%, PF 1.29, +60.66%, max DD 19.6%
  - Walk-forward: 6/6 rolling windows profitable
  - Year-by-year: 2023 PF 1.22, 2024 PF 1.80, 2025 PF 1.25, 2026 PF 0.74 (partial)
  - 2024-H2 choppy regime: +20.85% (where Keltner/TA strategies struggle)
  - Monte Carlo: 0% ruin probability, median max DD 11.5%

Edge hypothesis:
  Funding rate reflects crowded positioning. When funding drops unusually low
  (shorts paying longs heavily), it signals over-shorted conditions — shorts
  get squeezed, price mean-reverts. ADX confirms market is trending (not pure
  chop), volume confirms real participation. BTC 50+200 SMA filter ensures
  macro bullish bias to avoid fighting the tape.

Known weakness:
  - 2026 YTD -9.70% (current regime = bear start, funding mostly positive)
  - Higher DD than Keltner (19.6% vs 9%) — needs larger psychological tolerance

Generated 2026-04-17.
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import talib.abstract as ta
from freqtrade.strategy import IStrategy, informative
from pandas import DataFrame

logger = logging.getLogger(__name__)

FUNDING_DIR = Path("/freqtrade/user_data/data/binance/funding")


class FundingFadeV1(IStrategy):
    INTERFACE_VERSION: int = 3

    # ── Exit: roi_only profile (lab finding: trailing subtracts value) ──
    minimal_roi = {
        "0":    0.08,
        "360":  0.05,
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

    startup_candle_count = 200  # BTC SMA200 needs 200 candles

    # Strategy params
    funding_lookback = 500       # Rolling window for funding mean/std
    adx_threshold = 25
    vol_multiplier = 1.5
    vol_sma_period = 20
    btc_sma50_period = 50
    btc_sma200_period = 200

    # Funding data cache: pair -> (mtime_ns, funding_df)
    # Reloaded whenever the underlying feather file mtime changes, so a live
    # refresh via `download_funding_rates.py` propagates into a running bot.
    _funding_cache: dict = {}

    @informative("1h", "BTC/{stake}")
    def populate_indicators_btc_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["sma50"] = dataframe["close"].rolling(self.btc_sma50_period).mean()
        dataframe["sma200"] = dataframe["close"].rolling(self.btc_sma200_period).mean()
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]

        # Funding rate alignment
        funding_series = self._get_aligned_funding(pair, dataframe)
        dataframe["funding_rate"] = funding_series
        self._warn_if_funding_stale(pair, dataframe)

        roll_mean = dataframe["funding_rate"].rolling(self.funding_lookback, min_periods=50).mean()
        roll_std = dataframe["funding_rate"].rolling(self.funding_lookback, min_periods=50).std()
        dataframe["funding_below_mean"] = (
            dataframe["funding_rate"] < (roll_mean - roll_std)
        ).astype(int)

        # ADX
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

        # Volume SMA
        dataframe["vol_sma"] = dataframe["volume"].rolling(self.vol_sma_period).mean()

        # BTC gate: sma50 AND sma200
        dataframe["btc_gate"] = (
            (dataframe["btc_usdt_close_1h"] > dataframe["btc_usdt_sma50_1h"])
            & (dataframe["btc_usdt_close_1h"] > dataframe["btc_usdt_sma200_1h"])
        ).astype(int)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["funding_below_mean"] == 1)
                & (dataframe["adx"] > self.adx_threshold)
                & (dataframe["volume"] > self.vol_multiplier * dataframe["vol_sma"])
                & (dataframe["btc_gate"] == 1)
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Exits handled entirely by ROI + stoploss
        return dataframe

    # ── Funding rate loader ──────────────────────────────────

    def _get_aligned_funding(self, pair: str, dataframe: DataFrame) -> pd.Series:
        """Load historical funding feather, reloading when the file is refreshed.

        Live deployment: Binance publishes new funding every 8h. A cron runs
        `download_funding_rates.py` daily to refresh the feather files. This
        method invalidates the in-memory cache whenever the file mtime changes,
        so the running bot picks up new data without a restart.
        """
        pair_file = pair.replace("/", "_")
        path = FUNDING_DIR / f"{pair_file}-funding.feather"

        if not path.exists():
            if self._funding_cache.get(pair) != (None, None):
                logger.warning("No funding data for %s — signal will never fire", pair)
                self._funding_cache[pair] = (None, None)
            return pd.Series(np.nan, index=dataframe.index)

        mtime_ns = path.stat().st_mtime_ns
        cached = self._funding_cache.get(pair)
        if cached and cached[0] == mtime_ns and cached[1] is not None:
            return self._align_to_dataframe(cached[1], dataframe)

        try:
            fdf = pd.read_feather(path)
            fdf["ts"] = fdf["date"].apply(lambda x: x.timestamp())
            fdf = fdf.sort_values("ts").reset_index(drop=True)
            self._funding_cache[pair] = (mtime_ns, fdf)
            latest = pd.to_datetime(fdf["ts"].iloc[-1], unit="s", utc=True) if len(fdf) else None
            logger.info(
                "Funding data loaded for %s: %d rows, latest %s (mtime %d)",
                pair, len(fdf), latest, mtime_ns,
            )
            return self._align_to_dataframe(fdf, dataframe)
        except Exception as e:
            # Do NOT cache the failure. Next call retries the read so a transient
            # filesystem hiccup (mid-write, NFS glitch) doesn't poison signals.
            logger.warning("Funding load failed for %s: %s — will retry next bar", pair, e)
            return pd.Series(np.nan, index=dataframe.index)

    # Binance publishes every 8h (00/08/16 UTC). With a 4h incremental cron,
    # healthy staleness-at-signal-time ≤ 5h (4h cron + 1h candle). A threshold of
    # 12h catches (a) a missed cron run, (b) a silent download failure, (c) the
    # end-time/day-boundary bug in the downloader, well before 24h stale.
    _STALE_FUNDING_HOURS = 12

    def _warn_if_funding_stale(self, pair: str, dataframe: DataFrame) -> None:
        cached = self._funding_cache.get(pair)
        if not cached or cached[1] is None or cached[1].empty:
            return
        if dataframe.empty:
            return
        latest_bar = dataframe["date"].iloc[-1]
        latest_funding = cached[1]["date"].iloc[-1]
        if pd.Timestamp(latest_bar).tz_convert("UTC") - pd.Timestamp(latest_funding).tz_convert("UTC") \
                > pd.Timedelta(hours=self._STALE_FUNDING_HOURS):
            logger.warning(
                "Funding data for %s is stale: latest funding %s vs latest bar %s. "
                "Check `download_funding_rates.py` cron.",
                pair, latest_funding, latest_bar,
            )

    def _align_to_dataframe(self, funding_df, dataframe) -> pd.Series:
        if funding_df is None or funding_df.empty:
            return pd.Series(np.nan, index=dataframe.index)
        pair_ts = dataframe["date"].apply(lambda x: x.timestamp()).values
        funding_ts = funding_df["ts"].values
        funding_rates = funding_df["funding_rate"].values
        idx = np.searchsorted(funding_ts, pair_ts, side="right") - 1
        idx = np.clip(idx, 0, len(funding_rates) - 1)
        return pd.Series(funding_rates[idx], index=dataframe.index)
