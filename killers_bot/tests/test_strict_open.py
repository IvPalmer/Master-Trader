"""Tests for killers_bot.strict_open — the rule-based fast-path parser
that lets the observer skip the 7.6s Claude CLI hop on clean OPEN signals.

The parser MUST reject management messages, partial info, malformed
fields, and anything ambiguous — false fast-path = wrong trade.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from killers_bot.strict_open import is_strict_killers_open  # noqa: E402


# ── Real signals from production ──────────────────────────────────────────


HYPE_2144 = """📍SIGNAL ID: #2144📍
COIN: $HYPE/USDT (2-5x)
Direction: LONG
➖➖➖➖➖➖➖
ENTRY: 56.80 - 57.00

TARGETS: 59.50 - 62.00 - 65.00 - 68.00 -72.00 - 77.00 - 83.00 - 90.00

STOP LOSS: 52.00

4H resistance flip at entry with a fresh untouched FVG acting as confluence directly below.
➖➖➖➖➖➖➖
- Binance Killers®"""


POL_2143 = """📍SIGNAL ID: #2143📍
COIN: $POL/USDT (2-5x)
Direction: LONG
➖➖➖➖➖➖➖
ENTRY: 0.0894 - 0.0900

TARGETS: 0.0945 - 0.0990 - 0.1050 - 0.1125 - 0.1200 - 0.1300 - 0.1400 - 0.1500

STOP LOSS: 0.0810

4H FVG sitting directly on a key horizontal support level at entry.
➖➖➖➖➖➖➖
- Binance Killers®"""


def test_hype_2144_full_signal():
    out = is_strict_killers_open(HYPE_2144, msg_id=3468)
    assert out is not None
    assert out["kind"] == "open"
    assert out["signal_id"] == 2144
    assert out["symbol"] == "HYPE"
    assert out["direction"] == "long"
    assert out["entry"] is None
    assert out["entry_range"] == [56.80, 57.00]
    assert out["sl"] == 52.00
    assert out["confidence"] == 1.0


def test_pol_2143_full_signal():
    out = is_strict_killers_open(POL_2143, msg_id=3463)
    assert out is not None
    assert out["symbol"] == "POL"
    assert out["direction"] == "long"
    assert out["entry_range"] == [0.0894, 0.0900]
    assert out["sl"] == 0.0810


def test_synthetic_short_signal():
    """Channel hasn't sent shorts in captured data but format should be the same."""
    text = """📍SIGNAL ID: #9999📍
COIN: $BTC/USDT (3-5x)
Direction: SHORT
ENTRY: 100000 - 102000
TARGETS: 98000 - 95000 - 90000
STOP LOSS: 105000
"""
    out = is_strict_killers_open(text, msg_id=999)
    assert out is not None
    assert out["direction"] == "short"
    assert out["entry_range"] == [100000.0, 102000.0]
    assert out["sl"] == 105000.0


def test_single_entry_value():
    text = """📍SIGNAL ID: #1111📍
COIN: $ETH/USDT (5x)
Direction: LONG
ENTRY: 2500
STOP LOSS: 2400
"""
    out = is_strict_killers_open(text, msg_id=111)
    assert out is not None
    assert out["entry"] == 2500.0
    assert out["entry_range"] is None


# ── Rejection paths ───────────────────────────────────────────────────────


def test_reject_close_partial_target_hit():
    """Management message — `Target 1: X✅` is a mgmt marker."""
    text = """📍SIGNAL ID: #2142📍
COIN: $XLM/USDT (2-5x)
Direction: LONG
Target 1: 0.1515✅
Target 2: 0.1580✅
🔥44.8% Profit (5x)🔥
"""
    assert is_strict_killers_open(text, msg_id=3470) is None


def test_reject_stop_loss_hit_close():
    text = """📍SIGNAL ID: #2000📍
COIN: $BTC/USDT (3x)
Direction: LONG
Stop Loss Hit at 95000
"""
    assert is_strict_killers_open(text, msg_id=300) is None


def test_reject_move_sl_message():
    text = """📍SIGNAL ID: #2001📍
Move SL to breakeven on $BTC/USDT
Direction: LONG
ENTRY: 95000 - 96000
STOP LOSS: 94000
"""
    # Has Move SL marker → fall through to Claude
    assert is_strict_killers_open(text, msg_id=301) is None


def test_reject_increase_message():
    text = """📍SIGNAL ID: #2002📍
COIN: $BTC/USDT (3x)
Direction: LONG
Increase position size on retest
ENTRY: 95000
STOP LOSS: 94000
"""
    assert is_strict_killers_open(text, msg_id=302) is None


def test_reject_missing_signal_id():
    text = """COIN: $BTC/USDT (3x)
Direction: LONG
ENTRY: 95000 - 96000
STOP LOSS: 94000
"""
    assert is_strict_killers_open(text, msg_id=400) is None


def test_reject_missing_direction():
    text = """📍SIGNAL ID: #999📍
COIN: $BTC/USDT (3x)
ENTRY: 95000
STOP LOSS: 94000
"""
    assert is_strict_killers_open(text, msg_id=401) is None


def test_reject_missing_entry():
    text = """📍SIGNAL ID: #999📍
COIN: $BTC/USDT (3x)
Direction: LONG
STOP LOSS: 94000
"""
    assert is_strict_killers_open(text, msg_id=402) is None


def test_reject_missing_sl():
    text = """📍SIGNAL ID: #999📍
COIN: $BTC/USDT (3x)
Direction: LONG
ENTRY: 95000
"""
    assert is_strict_killers_open(text, msg_id=403) is None


def test_reject_long_with_sl_above_entry():
    """LONG with SL above entry is a malformed signal — refuse."""
    text = """📍SIGNAL ID: #999📍
COIN: $BTC/USDT (3x)
Direction: LONG
ENTRY: 95000
STOP LOSS: 99000
"""
    assert is_strict_killers_open(text, msg_id=404) is None


def test_reject_short_with_sl_below_entry():
    text = """📍SIGNAL ID: #999📍
COIN: $BTC/USDT (3x)
Direction: SHORT
ENTRY: 95000
STOP LOSS: 90000
"""
    assert is_strict_killers_open(text, msg_id=405) is None


def test_reject_empty_text():
    assert is_strict_killers_open("", msg_id=1) is None
    assert is_strict_killers_open(None, msg_id=1) is None  # type: ignore


def test_reject_non_string():
    assert is_strict_killers_open(12345, msg_id=1) is None  # type: ignore


def test_reject_chat_message():
    text = "GM team, BTC looking strong today."
    assert is_strict_killers_open(text, msg_id=500) is None


def test_reject_three_entry_values():
    """3+ numbers on entry line is unexpected → fall through."""
    text = """📍SIGNAL ID: #999📍
COIN: $BTC/USDT (3x)
Direction: LONG
ENTRY: 95000 - 96000 - 97000
STOP LOSS: 94000
"""
    assert is_strict_killers_open(text, msg_id=406) is None


# ── Range parsing tolerance ───────────────────────────────────────────────


def test_entry_range_no_space_before_dash():
    """Real-world: `56.80 -57.00` (no space). Unsigned tokenizer catches both."""
    text = """📍SIGNAL ID: #999📍
COIN: $HYPE/USDT (3x)
Direction: LONG
ENTRY: 56.80 -57.00
STOP LOSS: 52.00
"""
    out = is_strict_killers_open(text, msg_id=407)
    assert out is not None
    assert out["entry_range"] == [56.80, 57.00]


def test_entry_range_unsorted_input():
    """If channel writes hi-then-lo, we sort defensively."""
    text = """📍SIGNAL ID: #999📍
COIN: $HYPE/USDT (3x)
Direction: LONG
ENTRY: 57.00 - 56.80
STOP LOSS: 52.00
"""
    out = is_strict_killers_open(text, msg_id=408)
    assert out is not None
    assert out["entry_range"] == [56.80, 57.00]


def test_comma_decimal():
    text = """📍SIGNAL ID: #999📍
COIN: $HYPE/USDT (3x)
Direction: LONG
ENTRY: 56,80 - 57,00
STOP LOSS: 52,00
"""
    out = is_strict_killers_open(text, msg_id=409)
    assert out is not None
    assert out["entry_range"] == [56.80, 57.00]
    assert out["sl"] == 52.0


# ── Direction case-insensitivity ──────────────────────────────────────────


def test_lowercase_direction():
    text = """📍SIGNAL ID: #999📍
COIN: $BTC/USDT (3x)
Direction: long
ENTRY: 95000
STOP LOSS: 94000
"""
    out = is_strict_killers_open(text, msg_id=410)
    assert out is not None
    assert out["direction"] == "long"


if __name__ == "__main__":
    funcs = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    failed = []
    for f in funcs:
        try:
            f()
            print(f"PASS  {f.__name__}")
        except Exception as e:
            failed.append((f.__name__, e))
            print(f"FAIL  {f.__name__}: {e}")
    if failed:
        sys.exit(1)
    print(f"\n{len(funcs)} tests passed")
