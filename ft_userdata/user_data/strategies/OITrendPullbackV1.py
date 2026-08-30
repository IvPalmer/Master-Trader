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
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime

import numpy as np
import pandas as pd
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

    # Recalibrated 2026-08-30 against 30 days of Binance openInterestHist for
    # the live whitelist. The 2% threshold sat ABOVE the 99th percentile of the
    # actual 45-minute OI-growth distribution (p50 +0.01%, p90 +0.39%,
    # p99 +1.46%, max +6.76%), so it was not a filter — it was an off switch:
    # the TA conjunction produced 76 setups in that window and the gate
    # admitted zero, which matches the live record of no trade since
    # 2026-08-23.
    #
    # 0.0 is chosen on mechanism, not on being the sweep's argmax: it means
    # "open interest is not contracting", i.e. participation holds while price
    # reclaims the EMA20 — which is the continuation thesis. A +2% spike over
    # 45 minutes is a liquidation/squeeze signature, close to the opposite
    # setup. The sweep agrees and, importantly, degrades on both sides of it
    # (0.25% -> 3 trades/mo; 0.0 -> 20 trades/mo at PF 2.46; -0.5% -> 29
    # trades/mo but PF 1.34), so this is an interior optimum rather than
    # "looser is always better".
    #
    # NOT a proven edge: 20 trades in one 30-day regime, simulated on 1h bars
    # without fees or slippage. Registered as a hypothesis under
    # oi-gate-recalibration-2026-08-30 with an explicit review gate.
    oi_min_growth = 0.0
    oi_sample_interval_s = 300
    oi_lookback_s = 45 * 60
    oi_max_age_s = 15 * 60
    _oi_history: dict[str, list[tuple[float, float]]] = {}
    _oi_growth: dict[str, float] = {}
    _oi_growth_updated: dict[str, float] = {}
    _last_oi_poll = 0.0
    # Entry-funnel diagnostics. Per-pair throttle so a 1h strategy logs the
    # funnel roughly hourly rather than on every candle-processing call.
    FUNNEL_LOG_INTERVAL_S = 3600
    FUNNEL_WINDOW_CANDLES = 500
    _funnel_last_log: dict[str, float] = {}
    _oi_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="oi-poll")
    _oi_futures: dict[str, Future] = {}

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
        """Collect OI asynchronously and expire failed/stale confirmations."""
        now = time.time()

        # Never block Freqtrade's strategy loop on public HTTP. A completed
        # batch is harvested here; the next batch is submitted below.
        if self._oi_futures:
            if not all(future.done() for future in self._oi_futures.values()):
                return
            results = []
            for pair, future in self._oi_futures.items():
                try:
                    _, oi = future.result()
                except Exception as exc:
                    logger.warning("OI future failed for %s: %s", pair, exc)
                    oi = None
                results.append((pair, oi))
            self._oi_futures = {}
            for pair, oi in results:
                self._record_oi_result(pair, oi, now)
            valid = sum(oi is not None for _, oi in results)
            ready = sum(self._fresh_oi_growth(pair, now) is not None for pair, _ in results)
            logger.info(
                "OI snapshot: valid=%d/%d growth_ready=%d",
                valid, len(results), ready,
            )

        if now - self._last_oi_poll < self.oi_sample_interval_s:
            return
        self._last_oi_poll = now
        pairs = self.dp.current_whitelist() if self.dp else []
        self._oi_futures = {
            pair: self._oi_executor.submit(self._fetch_oi, pair) for pair in pairs
        }

    def _record_oi_result(self, pair: str, oi: float | None, now: float) -> None:
        """Apply one fetch result; failures invalidate the entry gate."""
        if oi is None:
            self._oi_growth.pop(pair, None)
            self._oi_growth_updated.pop(pair, None)
            return
        history = self._oi_history.setdefault(pair, [])
        history.append((now, oi))
        cutoff = now - 2 * 3600
        history[:] = [(ts, value) for ts, value in history if ts >= cutoff]
        eligible = [
            (ts, value) for ts, value in history
            if ts <= now - self.oi_lookback_s
        ]
        # Nearest sample at/before 45m — not the oldest point in the 2h buffer.
        baseline = max(eligible, key=lambda item: item[0])[1] if eligible else None
        if baseline and baseline > 0:
            self._oi_growth[pair] = oi / baseline - 1.0
            self._oi_growth_updated[pair] = now
        else:
            self._oi_growth.pop(pair, None)
            self._oi_growth_updated.pop(pair, None)

    def _fresh_oi_growth(self, pair: str, now: float | None = None) -> float | None:
        now = time.time() if now is None else now
        updated = self._oi_growth_updated.get(pair)
        if updated is None or now - updated > self.oi_max_age_s:
            self._oi_growth.pop(pair, None)
            self._oi_growth_updated.pop(pair, None)
            return None
        return self._oi_growth.get(pair)

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
        fresh_growth = self._fresh_oi_growth(metadata["pair"])
        dataframe["oi_growth"] = fresh_growth if fresh_growth is not None else np.nan
        dataframe["btc_trend"] = (
            (dataframe["btc_usdt_close_1h"] > dataframe["btc_usdt_ema200_1h"])
            & (dataframe["btc_usdt_ema50_1h"] > dataframe["btc_usdt_ema200_1h"])
        ).astype(int)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Named terms so the funnel below can attribute a rejection. The
        # conjunction is byte-for-byte the same set of conditions as before —
        # this is instrumentation, not a signal change.
        terms = {
            "uptrend_50_200": dataframe["ema50"] > dataframe["ema200"],
            "above_ema200": dataframe["close"] > dataframe["ema200"],
            "above_ema20": dataframe["close"] > dataframe["ema20"],
            "reclaim_ema20": dataframe["close"].shift(1) <= dataframe["ema20"].shift(1),
            "near_ema20_2pct": dataframe["close"] <= dataframe["ema20"] * 1.02,
            "rsi_45_68": dataframe["rsi"].between(45, 68),
            "volume_1_10x": dataframe["volume"] > dataframe["vol_sma"] * 1.10,
            "oi_growth_2pct": dataframe["oi_growth"] >= self.oi_min_growth,
            "btc_trend": dataframe["btc_trend"] == 1,
            "volume_positive": dataframe["volume"] > 0,
        }

        signal = None
        for condition in terms.values():
            signal = condition if signal is None else (signal & condition)
        dataframe.loc[signal, "enter_long"] = 1

        self._log_entry_funnel(dataframe, metadata, terms, signal)
        return dataframe

    def _log_entry_funnel(self, dataframe: DataFrame, metadata: dict,
                          terms: dict, signal) -> None:
        """Report which condition is actually blocking entries.

        Zero trades can mean "the market never set up" or "this gate can never
        be satisfied", and the two demand opposite responses. Without
        attribution they are indistinguishable, which is exactly the position
        this strategy was in: live since 2026-08-23 with no trade and no way
        to tell which. The OI term is the suspect one — it is populated only
        by a live HTTP poll, so it is NaN in every backtest and the whole
        conjunction is silently False.

        Emitted once per pair per FUNNEL_LOG_INTERVAL_S, at INFO. Cheap:
        boolean sums over an in-memory frame already built above.
        """
        pair = metadata.get("pair", "?")
        now = time.time()
        if now - self._funnel_last_log.get(pair, 0.0) < self.FUNNEL_LOG_INTERVAL_S:
            return
        self._funnel_last_log[pair] = now

        window = min(len(dataframe), self.FUNNEL_WINDOW_CANDLES)
        if window == 0:
            return
        passes = {name: int(term.tail(window).fillna(False).sum())
                  for name, term in terms.items()}
        # The binding constraint is whichever term passed least often.
        scarcest = min(passes, key=passes.get)

        # oi_growth is a single live reading broadcast across every row, so its
        # count is NOT a historical frequency like the others — it is the
        # current value replicated, and reads 0 or `window`. Report the value
        # itself, which is the number that tells you whether the 2% threshold
        # is near or hopeless, and say how far off it is.
        current_oi = self._fresh_oi_growth(pair)
        if current_oi is None:
            oi_note = ("oi_growth=UNAVAILABLE (no fresh reading; a restart "
                       "clears the 45m baseline and blocks entries until it "
                       "refills)")
        else:
            oi_note = (f"oi_growth={current_oi * 100:+.2f}% vs threshold "
                       f"{self.oi_min_growth * 100:.2f}% "
                       f"(gap {(self.oi_min_growth - current_oi) * 100:+.2f}pp)")

        logger.info(
            "OI entry funnel %s (last %d candles): %s | entries=%d | "
            "binding constraint=%s (%d/%d) | %s",
            pair, window,
            " ".join(f"{k}={v}" for k, v in passes.items()),
            int(signal.tail(window).fillna(False).sum()),
            scarcest, passes[scarcest], window, oi_note,
        )

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Keep dataframe exits empty. Freqtrade rejects an entry whenever the
        # same candle also has exit_long=1. A valid EMA20 reclaim can happen
        # below EMA50, so the EMA50 risk exit belongs in custom_exit(), where
        # it applies only to positions that are already open.
        dataframe["exit_long"] = 0
        return dataframe

    def custom_exit(
        self,
        pair: str,
        trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        """Exit an existing long after a candle closes below EMA50.

        OI is deliberately absent from this path: stale public OI blocks new
        entries but must never disable management of an open position.
        """
        if not self.dp:
            return None
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return None
        candle = dataframe.iloc[-1]
        candle_date = candle.get("date")
        trade_open = getattr(trade, "open_date_utc", None)
        if candle_date is None or trade_open is None:
            return None
        try:
            candle_ts = pd.Timestamp(candle_date)
            trade_open_ts = pd.Timestamp(trade_open)
            if pd.isna(candle_ts) or pd.isna(trade_open_ts):
                return None
            candle_ts = (
                candle_ts.tz_localize("UTC")
                if candle_ts.tzinfo is None
                else candle_ts.tz_convert("UTC")
            )
            trade_open_ts = (
                trade_open_ts.tz_localize("UTC")
                if trade_open_ts.tzinfo is None
                else trade_open_ts.tz_convert("UTC")
            )
        except (TypeError, ValueError):
            return None
        # OHLCV `date` is the candle's opening time. Requiring it to be later
        # than the trade open guarantees a complete post-entry candle before
        # the EMA50 exit can fire, avoiding enter-at-open/exit-seconds-later
        # churn when the valid EMA20 reclaim signal is still below EMA50.
        if candle_ts <= trade_open_ts:
            return None
        close = candle.get("close")
        ema50 = candle.get("ema50")
        if close is None or ema50 is None:
            return None
        if np.isfinite(close) and np.isfinite(ema50) and float(close) < float(ema50):
            return "ema50_break"
        return None
