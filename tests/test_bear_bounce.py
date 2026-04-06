"""Tests for BearCrashShortV1 bounce-long mode."""
from pathlib import Path

STRATEGY_PATH = Path(__file__).parent.parent / "ft_userdata" / "user_data" / "strategies" / "BearCrashShortV1.py"


class TestBounceLongMode:
    def test_bounce_long_signal_exists(self):
        source = STRATEGY_PATH.read_text()
        assert "enter_long" in source, "Must have enter_long for bounce mode"

    def test_bounce_requires_regime_flip(self):
        source = STRATEGY_PATH.read_text()
        assert "bear_to_bull" in source, "Must detect regime transition"

    def test_bounce_has_volume_confirmation(self):
        source = STRATEGY_PATH.read_text()
        long_idx = source.index("enter_long")
        nearby = source[max(0, long_idx - 500):long_idx + 500]
        assert "volume" in nearby.lower(), "Bounce long must confirm with volume"
