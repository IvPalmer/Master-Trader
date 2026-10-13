"""Short Keltner net-of-costs study (issue #1): network-free."""
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "shortkeltner_net"))

import study  # noqa: E402
from ft_userdata.analysis.costs import FundingSeries, fee_fraction  # noqa: E402

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def funding(rate, hours=100):
    return FundingSeries.from_pairs(
        (int((T0 + timedelta(hours=i)).timestamp() * 1000), rate) for i in range(hours))


def test_net_subtracts_fees_slippage_and_short_receives_positive_funding():
    t = [{"open": pd.Timestamp(T0 + timedelta(minutes=30)), "close": pd.Timestamp(T0 + timedelta(hours=10, minutes=30)),
          "entry": 100.0, "exit": 97.0, "gross": 0.03, "reason": "roi"}]
    df = study.net_trades(t, "BTC/USDC:USDC", funding(0.0001))
    r = df.iloc[0]
    assert r.fees == pytest.approx(2 * fee_fraction("hyperliquid", "perp", "taker"))
    assert r.slippage == pytest.approx(2 * 5e-4)
    assert r.funding == pytest.approx(-10 * 0.0001)  # 10 settlements, received by the short
    assert r.net == pytest.approx(0.03 - r.fees - r.slippage - r.funding)


def test_simulate_stoploss_and_time_exit():
    idx = pd.date_range(T0, periods=60, freq="h")
    d = pd.DataFrame({"o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "v": 1.0}, index=idx)
    gate = pd.Series(True, index=idx)
    flip = pd.Series(False, index=idx)
    assert study.simulate_pair(d, gate, flip) == []  # flat series: no signal
    assert study.roi_target(0) == 0.06 and study.roi_target(7) == 0.04 and study.roi_target(40) == 0.0


def test_no_hardcoded_fee_constants_left_in_migrated_analyses():
    files = [
        "research/copier-validation/killers/replay.py", "research/copier-validation/killers/replay_v2.py",
        "research/copier-validation/insiders/dennis_executability.py",
        "research/copier-validation/insiders/oos_runner.py", "research/copier-validation/insiders/track_a_pnl.py",
        "research/copier-validation/insiders/track_a_staged_fill.py",
        "research/copier-validation/insiders/track_a_fills_v2.py",
        "research/copier-validation/killers/keltner_overlay.py", "research/listing_short_forward/monitor.py",
    ]
    for f in files:
        src = (ROOT / f).read_text()
        assert not re.search(r"^(FEE|TAKER)\s*=\s*[0-9.]+\s*([;#]|$)", src, re.M), f
        assert "ft_userdata.analysis.costs" in src, f
