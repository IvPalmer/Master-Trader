"""Unit tests for classifier_dispatcher.is_strict_open.

The fast-path bypass to Claude must reject any classification whose
actionable fields aren't strictly well-formed — a malformed open must
NEVER reach sizing or order placement.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.classifier_dispatcher import is_strict_open  # noqa: E402


def _base_open(**overrides):
    """A minimally-valid strict-open. Tests override one field at a time."""
    base = {
        "kind": "open",
        "symbol": "BTC",
        "direction": "long",
        "entry": 80000.0,
        "sl": 78000.0,
    }
    base.update(overrides)
    return base


# ── Happy path ────────────────────────────────────────────────────────────


def test_strict_open_long_with_entry():
    assert is_strict_open(_base_open())


def test_strict_open_short_with_entry():
    assert is_strict_open(_base_open(direction="short", entry=80000, sl=82000))


def test_strict_open_with_entry_range():
    cls = _base_open()
    del cls["entry"]
    cls["entry_range"] = [79000, 80000]
    assert is_strict_open(cls)


def test_strict_open_uppercase_direction():
    assert is_strict_open(_base_open(direction="LONG"))


# ── Kind / forbidden flag rejection ───────────────────────────────────────


def test_reject_non_open_kind():
    assert not is_strict_open(_base_open(kind="close_full"))


def test_reject_applies_to_present():
    assert not is_strict_open(_base_open(applies_to=["BTC", "ETH"]))


# ── Symbol rejection ──────────────────────────────────────────────────────


def test_reject_missing_symbol():
    cls = _base_open()
    del cls["symbol"]
    assert not is_strict_open(cls)


def test_reject_empty_symbol():
    assert not is_strict_open(_base_open(symbol=""))


def test_reject_classifier_bug_symbol_CLOSE():
    assert not is_strict_open(_base_open(symbol="CLOSE"))


def test_reject_non_binance_MNT():
    assert not is_strict_open(_base_open(symbol="MNT"))


def test_reject_non_string_symbol():
    assert not is_strict_open(_base_open(symbol=123))


# ── Direction rejection ───────────────────────────────────────────────────


def test_reject_missing_direction():
    cls = _base_open()
    del cls["direction"]
    assert not is_strict_open(cls)


def test_reject_garbage_direction():
    assert not is_strict_open(_base_open(direction="up"))


def test_reject_none_direction():
    assert not is_strict_open(_base_open(direction=None))


# ── SL type/value rejection ───────────────────────────────────────────────


def test_reject_missing_sl():
    cls = _base_open()
    del cls["sl"]
    assert not is_strict_open(cls)


def test_reject_string_sl():
    assert not is_strict_open(_base_open(sl="foo"))


def test_reject_zero_sl():
    assert not is_strict_open(_base_open(sl=0))


def test_reject_negative_sl():
    assert not is_strict_open(_base_open(sl=-100))


def test_reject_bool_sl():
    # bool is technically int — must be excluded explicitly
    assert not is_strict_open(_base_open(sl=True))


# ── Entry type/value rejection ────────────────────────────────────────────


def test_reject_missing_entry_and_range():
    cls = _base_open()
    del cls["entry"]
    assert not is_strict_open(cls)


def test_reject_zero_entry():
    assert not is_strict_open(_base_open(entry=0))


def test_reject_string_entry():
    assert not is_strict_open(_base_open(entry="market"))


def test_reject_bool_entry():
    assert not is_strict_open(_base_open(entry=True))


def test_reject_entry_range_wrong_length():
    cls = _base_open()
    del cls["entry"]
    cls["entry_range"] = [80000]
    assert not is_strict_open(cls)


def test_reject_entry_range_with_string():
    cls = _base_open()
    del cls["entry"]
    cls["entry_range"] = [80000, "high"]
    assert not is_strict_open(cls)


# ── Wrong-side SL rejection (the ETH SHORT entry=77100 class of bug) ──────


def test_reject_long_with_sl_above_entry():
    # LONG, sl ABOVE entry — would trigger immediately
    assert not is_strict_open(_base_open(direction="long", entry=2400, sl=2500))


def test_reject_long_with_sl_equal_entry():
    assert not is_strict_open(_base_open(direction="long", entry=2400, sl=2400))


def test_reject_short_with_sl_below_entry():
    # SHORT, sl BELOW entry — would trigger immediately
    assert not is_strict_open(_base_open(direction="short", entry=2400, sl=2300))


def test_reject_short_with_sl_equal_entry():
    assert not is_strict_open(_base_open(direction="short", entry=2400, sl=2400))


def test_reject_eth_short_classifier_bug_shape():
    """The exact bug from classifier benchmark: ETH SHORT with entry that
    looks like BTC price (77100). entry_range midpoint > sl on SHORT → reject."""
    cls = {
        "kind": "open",
        "symbol": "ETH",
        "direction": "short",
        "entry": 77100,
        "sl": 78000,
    }
    # SHORT with sl above entry IS valid side; this catches different bug.
    # The actual rule bug had sl missing OR sl on wrong side. Verify both
    # variants: missing sl rejects, wrong-side rejects.
    cls_no_sl = dict(cls); del cls_no_sl["sl"]
    assert not is_strict_open(cls_no_sl)
    cls_bad_side = dict(cls); cls_bad_side["sl"] = 76000  # short with sl below entry
    assert not is_strict_open(cls_bad_side)


if __name__ == "__main__":
    import sys
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
