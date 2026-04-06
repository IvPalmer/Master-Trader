"""Tests for crypto sector/theme detection helper."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

MI_PATH = Path(__file__).parent.parent / "ft_userdata" / "user_data" / "strategies" / "market_intelligence.py"

def _load_module():
    spec = importlib.util.spec_from_file_location("market_intelligence", MI_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("requests", MagicMock())
    sys.modules.setdefault("requests.auth", MagicMock())
    spec.loader.exec_module(mod)
    return mod

class TestThemeDetection:
    def test_sector_map_exists(self):
        mod = _load_module()
        assert hasattr(mod, 'SECTOR_MAP')

    def test_sector_map_has_categories(self):
        mod = _load_module()
        assert "ai" in mod.SECTOR_MAP
        assert "l2" in mod.SECTOR_MAP
        assert "defi" in mod.SECTOR_MAP
        assert "meme" in mod.SECTOR_MAP
        assert "infra" in mod.SECTOR_MAP

    def test_classify_pair_sector(self):
        mod = _load_module()
        assert hasattr(mod, 'classify_pair_sector')
        assert mod.classify_pair_sector("FET/USDT") == "ai"
        assert mod.classify_pair_sector("RENDER/USDT") == "ai"
        assert mod.classify_pair_sector("ARB/USDT") == "l2"
        assert mod.classify_pair_sector("DOGE/USDT") == "meme"
        assert mod.classify_pair_sector("UNKNOWN/USDT") == "other"

    def test_score_sector_momentum(self):
        mod = _load_module()
        assert hasattr(mod, 'score_sector_momentum')
        result = mod.score_sector_momentum({"FET/USDT": 1000000, "ARB/USDT": 500000})
        assert "ai" in result
        assert result["ai"]["pairs"] == 1
        assert result["ai"]["total_volume"] == 1000000
