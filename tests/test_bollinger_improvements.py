"""Tests for BollingerBounceV1 volume capitulation filter."""
from pathlib import Path

STRATEGY_PATH = Path(__file__).parent.parent / "ft_userdata" / "user_data" / "strategies" / "BollingerBounceV1.py"


class TestVolumeCapitulationFilter:
    def test_volume_sma_calculated(self):
        source = STRATEGY_PATH.read_text()
        assert "volume_sma" in source, "Must calculate volume SMA"

    def test_volume_ratio_calculated(self):
        source = STRATEGY_PATH.read_text()
        assert "volume_ratio" in source, "Must calculate volume ratio"

    def test_entry_uses_volume_capitulation(self):
        source = STRATEGY_PATH.read_text()
        entry_section = source.split("populate_entry_trend")[1][:800]
        assert "volume_ratio" in entry_section, "Entry must use volume_ratio"
