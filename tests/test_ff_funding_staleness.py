"""FundingFadeV1 BTC-funding staleness fail-closed test.

The macro gate v2 docstring promises: BTC funding feather "missing or stale →
fail-closed". The missing case was always handled; this test pins the STALE
case — a feather that exists but stopped updating must NOT forward-fill into
live bars forever. Bars more than FundingFadeV1._BTC_FUNDING_MAX_AGE_H beyond
the last funding event must come back NaN so `macro_inputs_ok` blocks entries.

Runs inside any freqtrade container (has freqtrade + pandas + pyarrow):

    docker exec -i ft-funding-fade python3 - < tests/test_ff_funding_staleness.py

On a machine without freqtrade installed the test skips (import guard).
"""

import sys
import tempfile
from pathlib import Path

try:
    import pandas as pd
    import freqtrade  # noqa: F401 — availability probe only
except ImportError:
    print("SKIP: freqtrade not installed (run inside a freqtrade container)")
    sys.exit(0)

for p in ("/freqtrade/user_data/strategies", "ft_userdata/user_data/strategies"):
    if Path(p).is_dir():
        sys.path.insert(0, p)
        break

import FundingFadeV1 as ff_module  # noqa: E402


def test_stale_btc_funding_fails_closed():
    last_event = pd.Timestamp("2026-06-01 00:00:00", tz="UTC")
    max_age_h = getattr(ff_module.FundingFadeV1, "_BTC_FUNDING_MAX_AGE_H", 24)

    with tempfile.TemporaryDirectory() as tmp:
        # Synthetic feather: 100 funding events every 8h, ending at last_event.
        events = pd.date_range(end=last_event, periods=100, freq="8h", tz="UTC")
        feather = pd.DataFrame({"date": events, "funding_rate": 0.0001})
        ff_module.FUNDING_DIR = Path(tmp)
        feather.to_feather(Path(tmp) / "BTC_USDT-funding.feather")

        # Fresh class-level cache (other tests / prior imports must not leak in).
        ff_module.FundingFadeV1._btc_funding_30d_series = None
        ff_module.FundingFadeV1._btc_funding_30d_mtime_ns = 0
        ff_module.FundingFadeV1._missing_funding_last_warn = {}

        strategy = ff_module.FundingFadeV1.__new__(ff_module.FundingFadeV1)

        # 1h bars from 48h before to 48h after the last funding event.
        bars = pd.date_range(
            start=last_event - pd.Timedelta(hours=48),
            end=last_event + pd.Timedelta(hours=48),
            freq="1h",
            tz="UTC",
        )
        df = pd.DataFrame({"date": bars})

        result = strategy._get_btc_funding_30d_mean(df)
        cutoff = last_event + pd.Timedelta(hours=max_age_h)

        fresh = result[df["date"] <= cutoff]
        stale = result[df["date"] > cutoff]

        assert len(stale) > 0, "test setup broken: no bars beyond cutoff"
        assert fresh.notna().all(), (
            f"REGRESSION: {int(fresh.isna().sum())} bars within max-age came back "
            "NaN — historical/fresh bars must keep funding values"
        )
        assert stale.isna().all(), (
            f"FAIL-OPEN: {int(stale.notna().sum())}/{len(stale)} bars beyond "
            f"last_event+{max_age_h}h still carry forward-filled funding — "
            "stale feather does not fail closed"
        )
        print(
            f"PASS: {int(fresh.notna().sum())} fresh bars kept values, "
            f"{len(stale)} stale bars masked NaN (max age {max_age_h}h)"
        )


if __name__ == "__main__":
    test_stale_btc_funding_fails_closed()
