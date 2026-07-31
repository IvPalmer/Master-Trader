"""FundingFadeV1 PER-PAIR funding staleness fail-closed test (guard F2).

Companion to test_ff_funding_staleness.py, which pins the BTC *macro* feather.
This one pins the *per-pair* signal feather — the input that actually produces
the entry, and the one that was still fail-OPEN.

Before F2 the two paths disagreed. A dead ft-funding-refresh made the macro gate
fail closed (NaN → macro_inputs_ok False → entries blocked), but the per-pair
path only emitted a WARNING and kept forward-filling the last known funding rate
into every new bar forever. The strategy therefore evaluated
`funding_below_mean` against a frozen number and could open a position on
funding that no longer existed — the fault class behind the 2026-07-11 ADA
stop-loss (10h-stale funding at signal time; the hourly :10 refresh, commit
177cdd1, addressed the cadence, not the missing guard).

Contract pinned here: bars more than FundingFadeV1._STALE_FUNDING_HOURS beyond
the pair's last funding event come back NaN, so `funding_rate < roll_mean -
roll_std` is False and `funding_below_mean` is 0 → no entry for that pair.

NOTE on threshold intent: 12h is a *pipeline-death* detector, not a tightening
of signal freshness. Binance posts funding every 8h and the refresh runs hourly
at :10, so healthy staleness at signal time is ≤ ~9.2h. 12h leaves ~2.8h of
margin (2-3 missed cron runs) before blocking. It is deliberately NOT set below
the ADA trade's 10h — that trade is prevented by the hourly refresh, and a
threshold under the healthy ceiling would block entries during normal operation.

Runs inside any freqtrade container (has freqtrade + pandas + pyarrow):

    docker exec -i ft-funding-fade python3 - < tests/test_ff_per_pair_funding_staleness.py

On a machine without freqtrade installed the test skips (import guard).
"""

import sys
import tempfile
from pathlib import Path

try:
    import numpy as np
    import pandas as pd
    import freqtrade  # noqa: F401 — availability probe only
except ImportError:
    # Bare sys.exit() here would abort pytest's whole collection pass with an
    # INTERNALERROR, not skip this file. Skip properly under pytest; exit
    # cleanly when run as a standalone script inside a container.
    if __name__ == "__main__":
        print("SKIP: freqtrade not installed (run inside a freqtrade container)")
        sys.exit(0)
    import pytest

    pytest.skip("freqtrade not installed", allow_module_level=True)

# FF_STRATEGY_DIR lets this run against a CANDIDATE strategy file before it is
# deployed — the container's own strategies dir holds the currently-live code,
# which is exactly what a pre-deploy check must not import.
import os  # noqa: E402

for p in (
    os.environ.get("FF_STRATEGY_DIR"),
    "/freqtrade/user_data/strategies",
    "ft_userdata/user_data/strategies",
):
    if p and Path(p).is_dir():
        sys.path.insert(0, p)
        break

import FundingFadeV1 as ff_module  # noqa: E402


PAIR = "ADA/USDT"


def _fresh_strategy(tmp, last_event, rate=0.0001, periods=100):
    """Strategy instance backed by a synthetic feather ending at last_event."""
    events = pd.date_range(end=last_event, periods=periods, freq="8h", tz="UTC")
    pd.DataFrame({"date": events, "funding_rate": rate}).to_feather(
        Path(tmp) / f"{PAIR.replace('/', '_')}-funding.feather"
    )
    ff_module.FUNDING_DIR = Path(tmp)
    # Class-level caches are shared state — other tests or a prior import must
    # not leak a populated cache into this run.
    ff_module.FundingFadeV1._funding_cache = {}
    ff_module.FundingFadeV1._missing_funding_last_warn = {}
    return ff_module.FundingFadeV1.__new__(ff_module.FundingFadeV1)


def _bars(last_event, before_h=48, after_h=48):
    return pd.DataFrame({
        "date": pd.date_range(
            start=last_event - pd.Timedelta(hours=before_h),
            end=last_event + pd.Timedelta(hours=after_h),
            freq="1h",
            tz="UTC",
        )
    })


def test_stale_per_pair_funding_fails_closed():
    last_event = pd.Timestamp("2026-07-11 00:00:00", tz="UTC")
    max_age_h = ff_module.FundingFadeV1._STALE_FUNDING_HOURS

    with tempfile.TemporaryDirectory() as tmp:
        strategy = _fresh_strategy(tmp, last_event)
        df = _bars(last_event)

        result = strategy._get_aligned_funding(PAIR, df)
        cutoff = last_event + pd.Timedelta(hours=max_age_h)

        fresh = result[df["date"] <= cutoff]
        stale = result[df["date"] > cutoff]

        assert len(stale) > 0, "test setup broken: no bars beyond cutoff"
        assert fresh.notna().all(), (
            f"REGRESSION: {int(fresh.isna().sum())} bars within max-age came back "
            "NaN — fresh bars must keep their funding values"
        )
        assert stale.isna().all(), (
            f"FAIL-OPEN: {int(stale.notna().sum())}/{len(stale)} bars beyond "
            f"last_event+{max_age_h}h still carry forward-filled funding — "
            "a dead refresh cron can still produce entries on frozen funding"
        )
        print(
            f"PASS fail-closed: {int(fresh.notna().sum())} fresh bars kept values, "
            f"{len(stale)} stale bars masked NaN (max age {max_age_h}h)"
        )


def test_stale_bars_produce_no_entry_signal():
    """End-to-end: the masked NaN must actually suppress `funding_below_mean`.

    The positive control matters more than the negative one here. `roll_mean`
    and `roll_std` use min_periods=50, so a dataframe shorter than 50 bars
    makes `funding_below_mean` 0 everywhere no matter what the guard does — a
    test built that way passes against a completely absent guard. So this first
    asserts the frozen-but-still-fresh bars DO signal 1, proving the fixture can
    fire at all, and only then asserts the stale ones are 0.
    """
    last_event = pd.Timestamp("2026-07-11 00:00:00", tz="UTC")
    max_age_h = ff_module.FundingFadeV1._STALE_FUNDING_HOURS

    with tempfile.TemporaryDirectory() as tmp:
        # Deeply negative funding on the final event: on frozen data every bar
        # after it looks like a screaming crowded-short entry.
        events = pd.date_range(end=last_event, periods=600, freq="8h", tz="UTC")
        rates = np.full(len(events), 0.0001)
        rates[-1] = -0.01  # >>1 std below the rolling mean
        pd.DataFrame({"date": events, "funding_rate": rates}).to_feather(
            Path(tmp) / f"{PAIR.replace('/', '_')}-funding.feather"
        )
        ff_module.FUNDING_DIR = Path(tmp)
        ff_module.FundingFadeV1._funding_cache = {}
        ff_module.FundingFadeV1._missing_funding_last_warn = {}
        strategy = ff_module.FundingFadeV1.__new__(ff_module.FundingFadeV1)

        # 200h of history so the rolling window is populated well before the
        # cutoff, then 48h past the last event.
        df = _bars(last_event, before_h=200, after_h=48)
        funding = strategy._get_aligned_funding(PAIR, df)

        roll_mean = funding.rolling(strategy.funding_lookback, min_periods=50).mean()
        roll_std = funding.rolling(strategy.funding_lookback, min_periods=50).std()
        below = (funding < (roll_mean - roll_std)).astype(int)

        cutoff = last_event + pd.Timedelta(hours=max_age_h)
        live_idx = df.index[(df["date"] >= last_event) & (df["date"] <= cutoff)]
        stale_idx = df.index[df["date"] > cutoff]

        assert len(live_idx) > 0 and len(stale_idx) > 0, "test setup broken"
        assert below.loc[live_idx].sum() > 0, (
            "POSITIVE CONTROL FAILED: not one bar inside the freshness window "
            "signals funding_below_mean=1, so this fixture could never "
            "distinguish a working guard from a missing one"
        )
        assert (below.loc[stale_idx] == 0).all(), (
            f"{int(below.loc[stale_idx].sum())} stale bars still flag "
            "funding_below_mean=1 — the guard does not reach the entry signal"
        )
        print(
            f"PASS no-entry: {int(below.loc[live_idx].sum())} fresh bars signal 1, "
            f"all {len(stale_idx)} stale bars signal 0 on the same frozen -1% funding"
        )


def test_internal_outage_gap_is_masked_not_just_the_tail():
    """A gap in the MIDDLE of a feather must fail closed too.

    Anchoring staleness on the feather's final event would wave this through:
    the feed died, recovered, and the file now ends fresh, so a "beyond last
    event" rule sees nothing wrong while every bar inside the outage still
    carries funding hours or days out of date. Backtests and the OOS
    calibration runs read exactly those historical gaps.
    """
    gap_start = pd.Timestamp("2026-05-01 00:00:00", tz="UTC")
    resume = gap_start + pd.Timedelta(days=3)
    max_age_h = ff_module.FundingFadeV1._STALE_FUNDING_HOURS

    with tempfile.TemporaryDirectory() as tmp:
        before = pd.date_range(end=gap_start, periods=90, freq="8h", tz="UTC")
        after = pd.date_range(start=resume, periods=90, freq="8h", tz="UTC")
        events = before.append(after)
        pd.DataFrame({"date": events, "funding_rate": 0.0001}).to_feather(
            Path(tmp) / f"{PAIR.replace('/', '_')}-funding.feather"
        )
        ff_module.FUNDING_DIR = Path(tmp)
        ff_module.FundingFadeV1._funding_cache = {}
        ff_module.FundingFadeV1._missing_funding_last_warn = {}
        strategy = ff_module.FundingFadeV1.__new__(ff_module.FundingFadeV1)

        df = pd.DataFrame({
            "date": pd.date_range(
                start=gap_start - pd.Timedelta(hours=24),
                end=after[-1],
                freq="1h",
                tz="UTC",
            )
        })
        result = strategy._get_aligned_funding(PAIR, df)

        in_gap_stale = df.index[
            (df["date"] > gap_start + pd.Timedelta(hours=max_age_h))
            & (df["date"] < resume)
        ]
        after_resume = df.index[df["date"] >= resume]

        assert len(in_gap_stale) > 0, "test setup broken: no stale bars in gap"
        assert result.loc[in_gap_stale].isna().all(), (
            f"FAIL-OPEN inside outage: {int(result.loc[in_gap_stale].notna().sum())}"
            f"/{len(in_gap_stale)} bars in the 3-day gap still carry frozen "
            "funding — staleness is being measured from the feather's last "
            "event instead of each bar's own resolved event"
        )
        assert result.loc[after_resume].notna().all(), (
            "bars after the feed recovered came back NaN — guard over-blocks"
        )
        print(
            f"PASS internal gap: {len(in_gap_stale)} bars inside the 3-day "
            f"outage masked, all {len(after_resume)} post-recovery bars kept"
        )


def test_fresh_feather_is_untouched():
    """A healthy pair must be completely unaffected by the guard.

    The failure mode this pins is a guard that silently kills live signals —
    far worse than the fail-open it replaces.
    """
    last_event = pd.Timestamp("2026-07-11 00:00:00", tz="UTC")

    with tempfile.TemporaryDirectory() as tmp:
        strategy = _fresh_strategy(tmp, last_event)
        # Every bar sits at or before the last funding event: nothing is stale.
        df = _bars(last_event, before_h=72, after_h=0)

        result = strategy._get_aligned_funding(PAIR, df)

        assert result.notna().all(), (
            f"{int(result.isna().sum())}/{len(result)} bars on a fully fresh "
            "feather came back NaN — guard is over-blocking"
        )
        print(f"PASS no-op on fresh: all {len(result)} bars kept funding values")


if __name__ == "__main__":
    test_stale_per_pair_funding_fails_closed()
    test_stale_bars_produce_no_entry_signal()
    test_internal_outage_gap_is_masked_not_just_the_tail()
    test_fresh_feather_is_untouched()
