"""
Dynamic Pairlist Mixin — Simulates live pairlist filters in backtest.

Replicates VolumePairList + VolatilityFilter + RangeStabilityFilter
using candle data from the dataprovider. Refreshes every 4h to match
live refresh_period behavior.

Usage in calibration wrappers:
    class MyStrategyCal(DynamicPairlistMixin, MyStrategy):
        PAIRLIST_VOLUME_TOP_N = 40
        PAIRLIST_VOLATILITY_MIN = 0.02
        ...
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class DynamicPairlistMixin:
    """
    Mixin that gates entries on dynamic pairlist simulation.

    Subclass must set these class attributes to match live config:
        PAIRLIST_VOLUME_MIN        (default: 5_000_000)
        PAIRLIST_VOLUME_TOP_N      (default: 40)
        PAIRLIST_VOLATILITY_MIN    (default: 0.02)
        PAIRLIST_VOLATILITY_MAX    (default: 0.60)
        PAIRLIST_RANGE_MIN         (default: 0.02)
        PAIRLIST_RANGE_MAX         (default: 0.45)
    """

    # Defaults — override in subclass to match live config
    PAIRLIST_VOLUME_MIN: float = 5_000_000
    PAIRLIST_VOLUME_TOP_N: int = 40
    PAIRLIST_VOLATILITY_MIN: float = 0.02
    PAIRLIST_VOLATILITY_MAX: float = 0.60
    PAIRLIST_RANGE_MIN: float = 0.02
    PAIRLIST_RANGE_MAX: float = 0.45

    _pl_cache: dict = {}

    def passes_dynamic_pairlist(self, pair: str, current_time: datetime) -> bool:
        """Check if pair would be in the dynamic pairlist at this time."""
        # Cache key: 4h blocks (matches live refresh_period=14400)
        cache_key = current_time.strftime("%Y-%m-%d") + f"_{current_time.hour // 4}"

        if cache_key not in self._pl_cache:
            self._rebuild_pl_cache(current_time, cache_key)

        return pair in self._pl_cache.get(cache_key, set())

    def _rebuild_pl_cache(self, current_time: datetime, cache_key: str):
        """Evaluate all pairs through pairlist filters at a point in time."""
        pairlist = self.dp.current_whitelist()
        tf = self.timeframe
        qualifying = []

        for p in pairlist:
            try:
                df = self.dp.get_pair_dataframe(p, tf)
                if df is None or len(df) < 72:
                    continue

                # Normalize timezone: make both naive for comparison
                if len(df) > 0:
                    df = df.copy()
                    if hasattr(df["date"].dt, "tz") and df["date"].dt.tz is not None:
                        df["date"] = df["date"].dt.tz_localize(None)

                ct = current_time
                if hasattr(ct, "tzinfo") and ct.tzinfo is not None:
                    ct = ct.replace(tzinfo=None)

                # Only use candles up to current_time (no lookahead)
                df = df[df["date"] <= ct]
                if len(df) < 72:
                    continue

                # --- VolumePairList: 3-day quoteVolume ---
                last_3d = df.tail(24 * 3)
                quote_vol = (last_3d["close"] * last_3d["volume"]).sum()
                if quote_vol < self.PAIRLIST_VOLUME_MIN:
                    continue

                # --- VolatilityFilter: up to 14-day mean daily range ---
                # Freqtrade formula: mean of (high-low)/close per daily candle
                last_14d = df.tail(min(24 * 14, len(df)))
                if len(last_14d) >= 24:
                    # Resample hourly to daily
                    daily = last_14d.set_index("date").resample("1D").agg(
                        {"high": "max", "low": "min", "close": "last"}
                    ).dropna()
                    if len(daily) >= 3:
                        pct_ranges = (daily["high"] - daily["low"]) / daily["close"]
                        volatility = pct_ranges.mean()
                        if volatility < self.PAIRLIST_VOLATILITY_MIN or volatility > self.PAIRLIST_VOLATILITY_MAX:
                            continue

                # --- RangeStabilityFilter: up to 10-day rate of change ---
                # Freqtrade formula: (max_high - min_low) / last_close
                last_10d = df.tail(min(24 * 10, len(df)))
                if len(last_10d) >= 24:
                    daily_10 = last_10d.set_index("date").resample("1D").agg(
                        {"high": "max", "low": "min", "close": "last"}
                    ).dropna()
                    if len(daily_10) >= 3:
                        high = daily_10["high"].max()
                        low = daily_10["low"].min()
                        close = daily_10["close"].iloc[-1]
                        if close > 0:
                            roc = (high - low) / close
                            if roc < self.PAIRLIST_RANGE_MIN or roc > self.PAIRLIST_RANGE_MAX:
                                continue

                qualifying.append((p, quote_vol))

            except Exception:
                continue

        # Sort by volume descending, keep top N
        qualifying.sort(key=lambda x: x[1], reverse=True)
        top_pairs = set(p for p, _ in qualifying[:self.PAIRLIST_VOLUME_TOP_N])

        self._pl_cache[cache_key] = top_pairs

        # Log every ~24h (6 cache keys per day)
        if len(self._pl_cache) % 6 == 1:
            logger.info("Pairlist at %s: %d/%d qualify",
                        current_time.strftime("%Y-%m-%d %H:%M"),
                        len(top_pairs), len(pairlist))
