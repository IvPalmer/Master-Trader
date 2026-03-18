"""
Strategy code validation tests.

Catches: syntax errors, missing required methods, dangerous patterns,
stoploss_from_open bugs, import errors.
"""

import ast
import re
import pytest
from pathlib import Path

STRATEGY_DIR = Path(__file__).parent.parent / "ft_userdata" / "user_data" / "strategies"

def _load_active_bots() -> list:
    """Load active bot names from shared config, fall back to hardcoded defaults."""
    config_path = Path(__file__).parent.parent / "ft_userdata" / "bots_config.json"
    import json as _json
    try:
        with open(config_path) as f:
            data = _json.load(f)
        return [name for name, info in data["bots"].items() if info.get("active", True)]
    except (FileNotFoundError, _json.JSONDecodeError, KeyError):
        return [
            "SupertrendStrategy",
            "MasterTraderV1",
            "BollingerRSIMeanReversion",
            "FuturesSniperV1",
            "AlligatorTrendV1",
            "GaussianChannelV1",
        ]

ACTIVE_BOTS = _load_active_bots()


def load_source(name):
    return (STRATEGY_DIR / f"{name}.py").read_text()


# ── Syntax & Structure ────────────────────────────────────────────


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_strategy_parses(bot):
    """Strategy must be valid Python (no syntax errors)."""
    source = load_source(bot)
    try:
        ast.parse(source)
    except SyntaxError as e:
        pytest.fail(f"{bot}: syntax error at line {e.lineno}: {e.msg}")


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_has_required_methods(bot):
    """Strategy must implement the required Freqtrade interface methods."""
    source = load_source(bot)
    required = ["populate_indicators", "populate_entry_trend", "populate_exit_trend"]
    for method in required:
        assert f"def {method}" in source, f"{bot}: missing required method {method}"


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_interface_version_3(bot):
    """All strategies must use INTERFACE_VERSION 3."""
    source = load_source(bot)
    assert re.search(r"INTERFACE_VERSION\s*(?::\s*int\s*)?=\s*3", source), (
        f"{bot}: must set INTERFACE_VERSION = 3"
    )


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_has_timeframe(bot):
    """Strategy must declare a timeframe."""
    source = load_source(bot)
    assert re.search(r"timeframe\s*=\s*['\"]", source), f"{bot}: missing timeframe declaration"


# ── Stoploss safety patterns ─────────────────────────────────────


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_no_stoploss_from_open_bug(bot):
    """
    CRITICAL BUG (found 2026-03-12): stoploss_from_open() returns -0.99
    when trade is at/past target, which effectively disables the stoploss.

    If a strategy uses stoploss_from_open, it MUST handle the -0.99 case.
    """
    source = load_source(bot)
    if "stoploss_from_open" not in source:
        pytest.skip(f"{bot} doesn't use stoploss_from_open")

    # Must have protection against -0.99 return value
    has_protection = any([
        "-0.99" in source,
        "safety" in source.lower() and "stoploss" in source.lower(),
        re.search(r"if\s+.*stoploss.*<\s*-0\.9", source),
        "max(" in source and "stoploss" in source,
    ])
    assert has_protection, (
        f"{bot}: uses stoploss_from_open but doesn't guard against -0.99 bug. "
        f"See memory/feedback_stoploss_bugs.md"
    )


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_custom_stoploss_has_safety_net(bot):
    """If using custom_stoploss, the base stoploss must still be reasonable."""
    source = load_source(bot)
    if "use_custom_stoploss = True" not in source:
        pytest.skip(f"{bot} doesn't use custom_stoploss")

    match = re.search(r"^\s*stoploss\s*=\s*(-?[\d.]+)", source, re.MULTILINE)
    assert match, f"{bot}: has custom_stoploss but no base stoploss defined"
    sl = float(match.group(1))
    assert sl >= -0.10, (
        f"{bot}: base stoploss {sl} too wide for safety net (custom_stoploss can fail on restart)"
    )


# ── Dangerous patterns ───────────────────────────────────────────


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_no_hardcoded_pairs(bot):
    """Strategies shouldn't hardcode pair names (fragile, pairlist handles this)."""
    source = load_source(bot)
    # Allow in comments and strings for documentation
    code_lines = [
        line for line in source.split("\n")
        if not line.strip().startswith("#") and not line.strip().startswith('"""')
    ]
    code = "\n".join(code_lines)
    hardcoded = re.findall(r"['\"](?:BTC|ETH|SOL|DOGE|XRP)/USDT['\"]", code)
    assert not hardcoded, (
        f"{bot}: hardcoded pairs found: {hardcoded}. Use pairlist config instead."
    )


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_no_print_statements(bot):
    """Use logger, not print (print breaks Freqtrade output)."""
    source = load_source(bot)
    tree = ast.parse(source)
    prints = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]
    assert not prints, f"{bot}: print() at lines {prints}. Use logger.info() instead."


# ── Trailing stop consistency ─────────────────────────────────────


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_trailing_stop_offset_above_positive(bot):
    """
    trailing_stop_positive_offset must be > trailing_stop_positive,
    otherwise the trailing stop activates immediately and never trails.
    """
    source = load_source(bot)
    pos_match = re.search(r"trailing_stop_positive\s*=\s*([\d.]+)", source)
    off_match = re.search(r"trailing_stop_positive_offset\s*=\s*([\d.]+)", source)

    if not pos_match or not off_match:
        pytest.skip(f"{bot}: no trailing stop params found")

    positive = float(pos_match.group(1))
    offset = float(off_match.group(1))
    assert offset > positive, (
        f"{bot}: trailing_stop_positive_offset ({offset}) must be > "
        f"trailing_stop_positive ({positive})"
    )


# ── ROI table validation ─────────────────────────────────────────


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_roi_table_exists_and_valid(bot):
    """ROI table must exist and have decreasing values over time."""
    source = load_source(bot)
    roi_match = re.search(r"minimal_roi\s*=\s*\{([^}]+)\}", source, re.DOTALL)
    assert roi_match, f"{bot}: no minimal_roi table found"

    roi_str = roi_match.group(1)
    # Extract key-value pairs
    pairs = re.findall(r"['\"]?(\d+)['\"]?\s*:\s*([\d.]+)", roi_str)
    assert len(pairs) >= 2, f"{bot}: ROI table needs at least 2 entries"

    # Values should generally decrease over time (take less profit as trade ages)
    values = [float(v) for _, v in sorted(pairs, key=lambda x: int(x[0]))]
    for i in range(1, len(values)):
        assert values[i] <= values[i - 1], (
            f"{bot}: ROI values should decrease over time, got {values}"
        )
