"""
BearCrashShortV1 strategy validation tests.

Run with: pytest tests/test_bear_crash_short.py -v
"""

import ast
import json
import re
from pathlib import Path

import pytest

FT_DIR = Path(__file__).parent.parent / "ft_userdata"
STRATEGY_FILE = FT_DIR / "user_data" / "strategies" / "BearCrashShortV1.py"
CONFIG_FILE = FT_DIR / "user_data" / "configs" / "BearCrashShortV1.json"
BACKTEST_CONFIG = FT_DIR / "user_data" / "configs" / "backtest-BearCrashShortV1.json"


class TestStrategyFile:
    """Validate strategy Python file structure."""

    @pytest.fixture
    def source(self):
        return STRATEGY_FILE.read_text()

    @pytest.fixture
    def tree(self, source):
        return ast.parse(source)

    def test_file_exists(self):
        assert STRATEGY_FILE.exists(), "BearCrashShortV1.py not found"

    def test_parses_as_valid_python(self, tree):
        assert tree is not None

    def test_class_exists(self, tree):
        classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        assert "BearCrashShortV1" in classes

    def test_interface_version_3(self, source):
        assert "INTERFACE_VERSION = 3" in source

    def test_can_short_enabled(self, source):
        assert "can_short = True" in source

    def test_timeframe_declared(self, source):
        assert re.search(r'timeframe\s*=\s*["\']1h["\']', source)

    def test_has_required_methods(self, tree):
        methods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                methods.add(node.name)
        required = {
            "populate_indicators",
            "populate_entry_trend",
            "populate_exit_trend",
            "confirm_trade_entry",
            "confirm_trade_exit",
            "custom_exit",
            "leverage",
        }
        missing = required - methods
        assert not missing, f"Missing methods: {missing}"

    def test_no_enter_long_signal(self, source):
        """Short-only strategy must NEVER set enter_long."""
        assert "enter_long" not in source, "Short-only strategy must not have enter_long signals"

    def test_stoploss_not_worse_than_minus_5_pct(self, source):
        match = re.search(r'stoploss\s*=\s*(-[\d.]+)', source)
        assert match, "stoploss not found"
        sl = float(match.group(1))
        assert sl >= -0.05, f"Stoploss {sl} is worse than -5% - too risky for shorts"

    def test_no_stoploss_negative_099_bug(self, source):
        assert "-0.99" not in source, "Contains -0.99 stoploss bug pattern"

    def test_kill_switch_file_persisted(self, source):
        assert "kill_switch" in source.lower()
        assert "KILL_SWITCH_FILE" in source

    def test_leverage_returns_2(self, source):
        assert "return 2.0" in source

    def test_anti_squeeze_filters(self, source):
        assert "FearGreedIndex" in source, "Missing Fear & Greed anti-squeeze filter"
        assert "fg <= 10" in source or "fg<=10" in source, "F&G capitulation guard should block at <= 10"

    def test_time_exit_48h(self, source):
        assert "time_exit_48h" in source, "Missing 48h time exit"

    def test_bear_regime_persistence(self, source):
        """Must require multi-candle bear confirmation, not single-candle."""
        assert "btc_bear_confirmed" in source
        assert "rolling(6)" in source, "Regime detection should use 4-of-6 rolling window"


class TestLiveConfig:
    """Validate live trading config."""

    @pytest.fixture
    def config(self):
        return json.loads(CONFIG_FILE.read_text())

    def test_file_exists(self):
        assert CONFIG_FILE.exists()

    def test_futures_mode(self, config):
        assert config["trading_mode"] == "futures"

    def test_isolated_margin(self, config):
        assert config["margin_mode"] == "isolated"

    def test_dry_run(self, config):
        assert config["dry_run"] is True

    def test_wallet_size(self, config):
        assert config["dry_run_wallet"] == 22

    def test_max_open_trades(self, config):
        assert config["max_open_trades"] == 2

    def test_stoploss_on_exchange(self, config):
        assert config["order_types"]["stoploss_on_exchange"] is True

    def test_bot_name_set(self, config):
        assert config["bot_name"] == "BearCrashShort"

    def test_no_api_keys(self, config):
        assert config["exchange"]["key"] == ""
        assert config["exchange"]["secret"] == ""


class TestBacktestConfig:
    """Validate backtest config."""

    @pytest.fixture
    def config(self):
        return json.loads(BACKTEST_CONFIG.read_text())

    def test_file_exists(self):
        assert BACKTEST_CONFIG.exists()

    def test_static_pairlist(self, config):
        methods = [p["method"] for p in config["pairlists"]]
        assert "StaticPairList" in methods

    def test_futures_pairs_format(self, config):
        pairs = config["exchange"]["pair_whitelist"]
        for pair in pairs:
            assert pair.endswith(":USDT"), f"Futures pair {pair} missing :USDT suffix"

    def test_futures_mode(self, config):
        assert config["trading_mode"] == "futures"


class TestBotsConfig:
    """Validate bots_config.json registration."""

    @pytest.fixture
    def config(self):
        return json.loads((FT_DIR / "bots_config.json").read_text())

    def test_bot_registered(self, config):
        assert "BearCrashShortV1" in config["bots"]

    def test_port_8093(self, config):
        assert config["bots"]["BearCrashShortV1"]["port"] == 8093

    def test_marked_active(self, config):
        assert config["bots"]["BearCrashShortV1"]["active"] is True

    def test_futures_mode(self, config):
        assert config["bots"]["BearCrashShortV1"]["trading_mode"] == "futures"
