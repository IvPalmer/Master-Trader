"""V2 stop-risk sizing and receiver stop side-channel."""

from types import SimpleNamespace

import pytest

from app.main import compute_stake


CFG = SimpleNamespace(
    stake_usd=10.0,
    leverage=2.0,
    risk_usd=1.0,
    min_margin_usd=5.0,
    max_margin_usd=10.0,
    max_leverage=3.0,
)


@pytest.mark.parametrize(
    "stop, expected_leverage",
    [(90.0, 1.0), (95.0, 2.0), (98.0, 3.0)],
)
def test_sizing_targets_one_dollar_and_caps_leverage(stop, expected_leverage):
    stake, leverage, distance = compute_stake(
        {"entry": 100.0, "sl": stop}, CFG
    )
    assert 5.0 <= stake <= 10.0
    assert leverage == expected_leverage
    assert stake * leverage * distance <= 1.0001


def test_sizing_without_stop_returns_legacy_values_but_marks_distance_missing():
    stake, leverage, distance = compute_stake({"entry": 100.0}, CFG)
    assert (stake, leverage, distance) == (10.0, 2.0, None)
