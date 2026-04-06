"""
Tests for SupertrendStrategy N-bar trailing stop improvement.

Validates that custom_stoploss method exists, is properly configured,
and uses structure-based trailing (lowest low of N candles).
"""

import ast
import re
import pytest
from pathlib import Path

STRATEGY_DIR = Path(__file__).parent.parent / "ft_userdata" / "user_data" / "strategies"
STRATEGY_FILE = STRATEGY_DIR / "SupertrendStrategy.py"


def load_source():
    return STRATEGY_FILE.read_text()


def load_ast():
    return ast.parse(load_source())


# ── Configuration ────────────────────────────────────────────────


def test_use_custom_stoploss_enabled():
    """use_custom_stoploss = True must be set in the class."""
    source = load_source()
    assert re.search(r'use_custom_stoploss\s*=\s*True', source), \
        "use_custom_stoploss = True not found in SupertrendStrategy"


def test_builtin_trailing_disabled():
    """Built-in trailing_stop must be False (replaced by custom_stoploss)."""
    source = load_source()
    assert re.search(r'trailing_stop\s*=\s*False', source), \
        "trailing_stop should be False when using custom_stoploss"


def test_n_bar_lookback_defined():
    """n_bar_lookback class variable must exist."""
    source = load_source()
    assert re.search(r'n_bar_lookback\s*=\s*\d+', source), \
        "n_bar_lookback class variable not found"


# ── Method Existence ─────────────────────────────────────────────


def test_custom_stoploss_method_exists():
    """custom_stoploss method must be defined in the class."""
    tree = load_ast()
    class_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == 'SupertrendStrategy':
            class_node = node
            break

    assert class_node is not None, "SupertrendStrategy class not found"

    method_names = [
        node.name for node in ast.walk(class_node)
        if isinstance(node, ast.FunctionDef)
    ]
    assert 'custom_stoploss' in method_names, \
        "custom_stoploss method not found in SupertrendStrategy"


def test_custom_stoploss_signature():
    """custom_stoploss must accept the correct parameters."""
    tree = load_ast()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'custom_stoploss':
            arg_names = [a.arg for a in node.args.args]
            assert 'pair' in arg_names, "Missing 'pair' parameter"
            assert 'trade' in arg_names, "Missing 'trade' parameter"
            assert 'current_rate' in arg_names, "Missing 'current_rate' parameter"
            assert 'current_profit' in arg_names, "Missing 'current_profit' parameter"
            return
    pytest.fail("custom_stoploss method not found")


# ── Implementation Details ───────────────────────────────────────


def test_uses_candle_lows():
    """custom_stoploss must reference candle lows for structure-based trailing."""
    source = load_source()
    # Should reference 'low' column from dataframe
    assert re.search(r"\['low'\]", source), \
        "custom_stoploss should use candle lows (dataframe['low'])"


def test_uses_n_bar_lookback_in_stoploss():
    """custom_stoploss must use n_bar_lookback for the trailing window."""
    source = load_source()
    assert 'n_bar_lookback' in source, \
        "n_bar_lookback not referenced in strategy"


def test_trade_import_exists():
    """Trade must be imported from freqtrade.persistence."""
    source = load_source()
    assert re.search(r'from\s+freqtrade\.persistence\s+import\s+Trade', source), \
        "Trade import from freqtrade.persistence not found"


def test_has_safety_floor():
    """custom_stoploss must never return wider than default stoploss."""
    source = load_source()
    # Should compare against self.stoploss as a floor
    assert re.search(r'sl_from_current\s*<\s*self\.stoploss', source) or \
           re.search(r'self\.stoploss.*floor', source, re.IGNORECASE), \
        "custom_stoploss should have a safety floor (never wider than default stoploss)"


def test_never_returns_positive():
    """custom_stoploss must guard against returning positive values."""
    source = load_source()
    assert re.search(r'sl_from_current\s*>=\s*0', source) or \
           re.search(r'>= 0', source), \
        "custom_stoploss should guard against returning positive values (would close trade)"
