"""
FundingFadeV1 — Funding rate divergence entry with TA confirmation + macro gate v2.

Signal:
  - Entry: Funding rate drops 1+ std below its 500-period rolling mean
    (crowded-short sentiment → reversion setup)
  - Confirm: ADX > 25 (trending market filter)
    AND Volume > 1.5x 20-period SMA (liquidity confirmation)
  - Macro gate (v2 — see below): BTC > SMA50 AND > SMA200 (both 1h)
    AND BTC SMA50 slope > 0 over last 24 bars
    AND NOT (BTC 30d return < 0 AND BTC 30d funding-rate mean > 0)
  - Exit: ROI-only profile (trailing removed — confirmed trailing noise in 1m)

Macro gate v2 (added 2026-05-19 after 5-SL streak May 10-16 paused live bot):
  Codex-reviewed protocol — see project_funding_fade_gate_v2_2026-05-19.md.
  Combined filter (slope + regime halt) dominates baseline in walk-forward,
  bootstrap, and drop-year adversarial tests:
    - 3.3yr backtest: +19.05% (vs baseline +14.01%), MaxDD 2.40% (vs 3.91%),
      WR 68.6% (vs 64.5%), PF 1.54 (vs 1.21), 293 trades (vs 488)
    - P(MaxDD < baseline) = 92.5% (block-bootstrap, 1000 iter, 30d blocks)
    - Wins difficult quarters: 2025-Q1, 2025-Q4, 2026-Q1
    - Drop-2024 test: still best (+13.80% / 1.90% DD vs baseline +5.56% / 4.22%)
  Honest caveats: combined was meta-selected after seeing slope+regime singly
  (≈4 effective dof). Headline +5pp uplift may be wiped by live execution noise.
  Deploy reason is risk reduction, not return uplift.

Original signal (lab-validated 3.3yr 1m-detail before gate v2):
  - 431 trades, WR 65.7%, PF 1.29, +60.66% over $88, max DD 19.6%
  - 2024 PF 1.80 (best regime), 2026 PF 0.74 (current bear-start regime)
  - Known weakness in 2026: bear-start + positive funding (gate v2 addresses)

Edge hypothesis:
  Funding rate reflects crowded positioning. When funding drops unusually low
  (shorts paying longs heavily), it signals over-shorted conditions — shorts
  get squeezed, price mean-reverts. The new macro gate ensures the
  mean-reversion has room to play out by skipping (a) markets where BTC's own
  trend has flattened/turned and (b) the specific regime (bear + positive
  funding) where the crowded-short setup is empirically absent.

Generated 2026-04-17. Macro gate v2 added 2026-05-19.

Operational dependencies (gate v2):
  - BTC informative 1h history (Freqtrade fetches via @informative decorator
    using `startup_candle_count = 720`). Partial data → `btc_history_ok` False
    → all entries BLOCKED for affected bars.
  - BTC_USDT-funding.feather refreshed daily by ft-funding-refresh service
    (cron in docker-compose.prod.yml). Missing or stale → fail-closed
    (all entries blocked, ERROR log every 4h).
  - Per-pair funding feathers used by the original signal (unchanged behavior).

Alerting:
  - Log line "MISSING BTC funding feather — macro gate v2 FAIL-CLOSED" → page
  - Log line "STALE BTC funding feather" + "FAIL-CLOSED" → page (feather exists
    but last funding event is >24h behind the bar being evaluated)
  - Log line "BTC funding load failed" → investigate
  - Log line "BTC 30d funding mean loaded" → normal startup
  - Cron freshness: ft-funding-refresh runs every 4h; if last log >8h old,
    investigate.
"""

import logging
import time
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

    startup_candle_count = 720  # 30 days at 1h — needed for BTC 30d return regime check

    # Strategy params
    funding_lookback = 500       # Rolling window for funding mean/std
    adx_threshold = 25
    vol_multiplier = 1.5
    vol_sma_period = 20
    btc_sma50_period = 50
    btc_sma200_period = 200

    # Macro gate v2 params (frozen 2026-05-19)
    btc_sma50_slope_lookback_bars = 24       # 24 × 1h = 1 day
    btc_regime_return_lookback_bars = 30 * 24  # 30d on 1h frame
    btc_regime_funding_lookback_events = 30 * 3  # 30d × 3 funding-events/day

    # Funding data cache: pair -> (mtime_ns, funding_df)
    # Reloaded whenever the underlying feather file mtime changes, so a live
    # refresh via `download_funding_rates.py` propagates into a running bot.
    _funding_cache: dict = {}

    # Tracks last warn timestamp per pair when funding file is MISSING. Earlier
    # versions logged once and went silent forever — a never-existed file
    # produced zero entries with no further alert. Re-warn every 4h to keep
    # the failure visible in container logs.
    _missing_funding_last_warn: dict = {}
    _MISSING_REWARN_INTERVAL_S = 4 * 3600

    # Cached 30d BTC funding rate rolling-mean series (computed once globally;
    # same value for every pair, no need to re-read per call).
    _btc_funding_30d_series = None
    _btc_funding_30d_mtime_ns = 0

    # Max age of the BTC funding feather before the regime gate fail-closes.
    # Funding posts every 8h and ft-funding-refresh runs every 4h, so 24h stale
    # means ≥3 missed funding events / ≥6 missed cron runs — the file is dead,
    # not late. Per-pair staleness warns at 12h (_STALE_FUNDING_HOURS) without
    # blocking; the macro gate is a risk control and must not run on dead data.
    _BTC_FUNDING_MAX_AGE_H = 24

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

        # Macro gate v2 (added 2026-05-19): base gate + slope_positive AND
        # not_regime_halt AND btc_history_ok. Fail-closed on missing dependencies.
        btc_close = dataframe["btc_usdt_close_1h"]
        btc_sma50 = dataframe["btc_usdt_sma50_1h"]
        btc_sma200 = dataframe["btc_usdt_sma200_1h"]

        base_gate = (btc_close > btc_sma50) & (btc_close > btc_sma200)

        # SMA50 slope positive over last 24 1h bars (catches macro exhaustion
        # before BTC actually breaks down — fragile-bull regime filter).
        sma50_slope = btc_sma50 - btc_sma50.shift(self.btc_sma50_slope_lookback_bars)
        slope_ok = sma50_slope > 0

        # Regime halt: bear (BTC 30d < 0) AND positive funding (no crowded-short)
        # — the exact regime where the strategy's edge is empirically absent.
        btc_return_30d = btc_close.pct_change(self.btc_regime_return_lookback_bars)
        btc_funding_30d = self._get_btc_funding_30d_mean(dataframe)

        # Fail-closed: require all macro inputs valid before allowing entries.
        # Partial BTC informative data or missing funding feather → block entries.
        btc_history_ok = btc_close.shift(self.btc_regime_return_lookback_bars).notna()
        btc_funding_ok = btc_funding_30d.notna()
        macro_inputs_ok = btc_history_ok & btc_funding_ok

        # regime_halt is True only when both conditions are valid AND triggered.
        # If either input is NaN, the comparison is False, so halt = False — but
        # macro_inputs_ok will be False, blocking entry via btc_gate AND below.
        regime_halt = (btc_return_30d < 0) & (btc_funding_30d > 0)

        dataframe["btc_gate"] = (
            base_gate & slope_ok & ~regime_halt & macro_inputs_ok
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

    # ── BTC 30d funding rate (for regime halt) ────────────────────────────

    def _get_btc_funding_30d_mean(self, dataframe: DataFrame) -> pd.Series:
        """30-day rolling mean of BTC funding rate, aligned to 1h dataframe.

        Cached at class level — same for every pair, mtime-invalidated so live
        refresh via download_funding_rates.py propagates without restart.

        Fail-closed: returns Series of NaN on missing feather, load failure,
        or staleness (bars more than _BTC_FUNDING_MAX_AGE_H beyond the last
        funding event — see staleness mask below). Caller's gate logic must
        include `.notna()` check; with NaN here, the regime gate's
        `macro_inputs_ok` becomes False and ALL entries are blocked until BTC
        funding is restored. This is intentional — the new risk-control
        feature should not be silently neutered by its own dependency
        disappearing or going stale.
        """
        path = FUNDING_DIR / "BTC_USDT-funding.feather"
        if not path.exists():
            now = time.time()
            last = self._missing_funding_last_warn.get("__BTC_REGIME__", 0.0)
            if now - last >= self._MISSING_REWARN_INTERVAL_S:
                logger.error(
                    "MISSING BTC funding feather — macro gate v2 FAIL-CLOSED. "
                    "All FundingFade entries BLOCKED until BTC funding restored. "
                    "Check ft-funding-refresh service."
                )
                self._missing_funding_last_warn["__BTC_REGIME__"] = now
            return pd.Series(float("nan"), index=dataframe.index)

        mtime_ns = path.stat().st_mtime_ns
        cls = type(self)
        if cls._btc_funding_30d_series is None or cls._btc_funding_30d_mtime_ns != mtime_ns:
            try:
                fdf = pd.read_feather(path).sort_values("date").reset_index(drop=True)
                fdf["date"] = pd.to_datetime(fdf["date"], utc=True)
                roll = fdf["funding_rate"].rolling(
                    self.btc_regime_funding_lookback_events, min_periods=10
                ).mean()
                cls._btc_funding_30d_series = pd.Series(roll.values, index=fdf["date"])
                cls._btc_funding_30d_mtime_ns = mtime_ns
                logger.info(
                    "BTC 30d funding mean loaded: %d funding events, latest %s",
                    len(fdf), fdf["date"].iloc[-1] if len(fdf) else None,
                )
            except Exception as e:
                logger.warning("BTC funding load failed for regime gate: %s — FAIL-CLOSED this bar", e)
                return pd.Series(float("nan"), index=dataframe.index)

        # Reindex onto the dataframe's 1h dates with forward-fill
        # (funding posts every 8h, so any 1h bar inherits the most recent value).
        dates = pd.to_datetime(dataframe["date"], utc=True) if "date" in dataframe.columns else dataframe.index
        aligned = cls._btc_funding_30d_series.reindex(dates, method="ffill")

        # Staleness mask: ffill must not extend past the feather's last funding
        # event forever. Bars beyond last_event + _BTC_FUNDING_MAX_AGE_H get NaN
        # → btc_funding_ok False → entries blocked. Without this, a dead
        # ft-funding-refresh leaves the regime gate running on frozen data
        # indefinitely (fail-open) while the contract above promises fail-closed.
        if len(cls._btc_funding_30d_series.index) == 0:
            return pd.Series(float("nan"), index=dataframe.index)
        last_event = cls._btc_funding_30d_series.index[-1]
        cutoff = last_event + pd.Timedelta(hours=self._BTC_FUNDING_MAX_AGE_H)
        stale_mask = pd.DatetimeIndex(dates) > cutoff
        values = aligned.values
        if stale_mask.any():
            values = values.copy()
            values[stale_mask] = float("nan")
            now = time.time()
            last_warn = self._missing_funding_last_warn.get("__BTC_REGIME_STALE__", 0.0)
            if now - last_warn >= self._MISSING_REWARN_INTERVAL_S:
                logger.error(
                    "STALE BTC funding feather (last event %s, max age %dh) — macro "
                    "gate v2 FAIL-CLOSED for %d bar(s). Check ft-funding-refresh.",
                    last_event, self._BTC_FUNDING_MAX_AGE_H, int(stale_mask.sum()),
                )
                self._missing_funding_last_warn["__BTC_REGIME_STALE__"] = now
        return pd.Series(values, index=dataframe.index)

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
            now = time.time()
            last_warn = self._missing_funding_last_warn.get(pair, 0.0)
            first_time = self._funding_cache.get(pair) != (None, None)
            if first_time:
                logger.error(
                    "MISSING funding feather for %s at %s — entries DISABLED for this pair "
                    "until the file is restored. Check ft-funding-refresh logs.",
                    pair, path,
                )
                self._funding_cache[pair] = (None, None)
                self._missing_funding_last_warn[pair] = now
            elif now - last_warn >= self._MISSING_REWARN_INTERVAL_S:
                logger.error(
                    "MISSING funding feather still absent for %s after %.0fh — "
                    "this pair has been silently producing zero entries.",
                    pair, (now - last_warn) / 3600,
                )
                self._missing_funding_last_warn[pair] = now
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
        # searchsorted-right - 1 finds the last funding event at-or-before each
        # bar. For bars predating any funding (idx == -1) we must return NaN —
        # the prior implementation clipped to 0 and assigned the first funding
        # value, creating lookahead at the start of backtests.
        idx = np.searchsorted(funding_ts, pair_ts, side="right") - 1
        result = np.where(idx >= 0, funding_rates[np.clip(idx, 0, len(funding_rates) - 1)], np.nan)
        return pd.Series(result, index=dataframe.index)
