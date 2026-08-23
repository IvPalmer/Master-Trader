"""OITrendPullbackV1 — spot trend continuation confirmed by futures OI.

The bot buys a liquid alt only after a pullback reclaims the 20h EMA inside a
larger 50/200h uptrend and Binance USDT-M open interest has expanded by at
least 2% over roughly one hour.  OI is public market data; failures fail
closed and never block exit management.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import numpy as np
import talib.abstract as ta
from freqtrade.strategy import IStrategy, informative
from pandas import DataFrame

logger = logging.getLogger(__name__)


class OITrendPullbackV1(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1h"
    process_only_new_candles = True
    startup_candle_count = 240

    minimal_roi = {"0": 0.06, "360": 0.04, "720": 0.025, "1440": 0.01}
    stoploss = -0.05
    trailing_stop = True
    trailing_stop_positive = 0.025
    trailing_stop_positive_offset = 0.04
    trailing_only_offset_is_reached = True
    use_exit_signal = True
    exit_profit_only = False

    oi_min_growth = 0.02
    oi_sample_interval_s = 300
    oi_lookback_s = 45 * 60
    _oi_history: dict[str, list[tuple[float, float]]] = {}
    _oi_growth: dict[str, float] = {}
    _last_oi_poll = 0.0

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 3},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 72,
                "trade_limit": 2,
                "stop_duration_candles": 24,
                "only_per_pair": False,
            },
        ]

    @informative("1h", "BTC/{stake}")
    def populate_indicators_btc_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        return dataframe

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        """Collect one public OI snapshot per whitelisted pair every 5m."""
        now = time.time()
        if now - self._last_oi_poll < self.oi_sample_interval_s:
            return
        self._last_oi_poll = now
        pairs = self.dp.current_whitelist() if self.dp else []
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(self._fetch_oi, pairs))
        for pair, oi in results:
            if oi is None:
                continue
            history = self._oi_history.setdefault(pair, [])
            history.append((now, oi))
            cutoff = now - 2 * 3600
            history[:] = [(ts, value) for ts, value in history if ts >= cutoff]
            baseline = next(
                (value for ts, value in history if ts <= now - self.oi_lookback_s),
                None,
            )
            if baseline and baseline > 0:
                self._oi_growth[pair] = oi / baseline - 1.0
        valid = sum(oi is not None for _, oi in results)
        ready = sum(pair in self._oi_growth for pair in pairs)
        logger.info(
            "OI snapshot: valid=%d/%d growth_ready=%d (entries fail-closed until ready)",
            valid, len(pairs), ready,
        )

    @staticmethod
    def _fetch_oi(pair: str) -> tuple[str, float | None]:
        symbol = pair.split("/")[0].replace("1000", "1000") + "USDT"
        url = "https://fapi.binance.com/fapi/v1/openInterest?" + urllib.parse.urlencode(
            {"symbol": symbol}
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "master-trader/1"})
            with urllib.request.urlopen(req, timeout=2.0) as response:
                payload = json.load(response)
            value = float(payload["openInterest"])
            return pair, value if value > 0 else None
        except Exception as exc:
            logger.warning("OI fetch failed for %s: %s", pair, exc)
            return pair, None

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["vol_sma"] = dataframe["volume"].rolling(20).mean()
        dataframe["oi_growth"] = self._oi_growth.get(metadata["pair"], np.nan)
        dataframe["btc_trend"] = (
            (dataframe["btc_usdt_close_1h"] > dataframe["btc_usdt_ema200_1h"])
            & (dataframe["btc_usdt_ema50_1h"] > dataframe["btc_usdt_ema200_1h"])
        ).astype(int)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["ema50"] > dataframe["ema200"])
                & (dataframe["close"] > dataframe["ema200"])
                & (dataframe["close"] > dataframe["ema20"])
                & (dataframe["close"].shift(1) <= dataframe["ema20"].shift(1))
                & (dataframe["close"] <= dataframe["ema20"] * 1.02)
                & (dataframe["rsi"].between(45, 68))
                & (dataframe["volume"] > dataframe["vol_sma"] * 1.10)
                & (dataframe["oi_growth"] >= self.oi_min_growth)
                & (dataframe["btc_trend"] == 1)
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] < dataframe["ema50"])
            & (dataframe["oi_growth"].notna())
            & (dataframe["oi_growth"] < 0),
            "exit_long",
        ] = 1
        return dataframe
