"""Tests for AI trade autopsy automation."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

AUTOPSY_PATH = Path(__file__).parent.parent / "ft_userdata" / "ai_trade_autopsy.py"

def _load_module():
    spec = importlib.util.spec_from_file_location("ai_trade_autopsy", AUTOPSY_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("requests", MagicMock())
    sys.modules.setdefault("requests.auth", MagicMock())
    spec.loader.exec_module(mod)
    return mod

class TestAutopsyFormat:
    def test_module_exists(self):
        assert AUTOPSY_PATH.exists()

    def test_format_trade_autopsy_exists(self):
        mod = _load_module()
        assert hasattr(mod, 'format_trade_autopsy')

    def test_format_trade_autopsy_output(self):
        mod = _load_module()
        trade = {
            "pair": "ETH/USDT", "open_date": "2026-04-01 10:00:00",
            "close_date": "2026-04-01 14:00:00", "open_rate": 1800.0,
            "close_rate": 1850.0, "profit_abs": 2.5, "profit_ratio": 0.028,
            "exit_reason": "trailing_stop_loss", "enter_tag": "enter_long",
            "stake_amount": 88.0, "trade_duration": 240,
        }
        rules = {"entry": "test entry", "exit": "test exit", "stoploss": "-5%", "trailing": "N-bar"}
        result = mod.format_trade_autopsy(trade, "SupertrendStrategy", rules)
        assert "ETH/USDT" in result
        assert "SupertrendStrategy" in result
        assert "trailing_stop_loss" in result

    def test_generate_autopsy_prompt_exists(self):
        mod = _load_module()
        assert hasattr(mod, 'generate_autopsy_prompt')

    def test_generate_autopsy_prompt_output(self):
        mod = _load_module()
        autopsies = ["Trade 1: won", "Trade 2: lost"]
        prompt = mod.generate_autopsy_prompt(autopsies)
        assert "most important" in prompt.lower()
        assert "pattern" in prompt.lower()
