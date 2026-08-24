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


def test_wide_stop_skips_instead_of_raising_risk_to_exchange_minimum():
    stake, leverage, distance = compute_stake(
        {"entry": 100.0, "sl": 70.0}, CFG
    )
    assert stake == 0.0
    assert leverage == 1.0
    assert distance == pytest.approx(0.30)


@pytest.mark.parametrize(
    ("direction", "sl", "effective_entry"),
    [("long", 95.0, 103.0), ("short", 105.0, 97.0)],
)
def test_sizing_uses_effective_entry_and_adverse_stop_limit_fill(
    direction, sl, effective_entry
):
    stake, leverage, distance = compute_stake(
        {"direction": direction, "entry": 100.0, "sl": sl},
        CFG,
        effective_entry=effective_entry,
        stop_limit_ratio=0.98,
    )

    assert stake * leverage * distance <= CFG.risk_usd + 1e-6
    trigger_only_distance = abs(effective_entry - sl) / effective_entry
    assert distance > trigger_only_distance


def test_effective_entry_can_make_previously_valid_stake_fail_minimum():
    stake, leverage, distance = compute_stake(
        {"direction": "long", "entry": 100.0, "sl": 95.0},
        CFG,
        effective_entry=103.0,
        stop_limit_ratio=0.98,
    )

    assert distance == pytest.approx((103.0 - 95.0 * 0.98) / 103.0)
    assert stake >= CFG.min_margin_usd
    assert stake * leverage * distance <= CFG.risk_usd + 1e-6
