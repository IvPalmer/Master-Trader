"""Unit tests for the SL-side validation logic in InsidersScalpV1.custom_stoploss.

We can't import the Freqtrade strategy directly (requires the full Freqtrade
runtime), so this test mirrors the validation logic and asserts behavior.
"""


def validate_sl_side(sl_price: float, current_rate: float, is_short: bool) -> bool:
    """Mirror of the side-check in InsidersScalpV1.custom_stoploss.

    Returns True if the SL is on the correct side (stop will only fire on
    adverse move). False = wrong-side, must reject.
    """
    if not is_short and sl_price >= current_rate:
        return False
    if is_short and sl_price <= current_rate:
        return False
    return True


def test_long_valid_sl_below_current():
    # BTC long at $80k, SL at $78k → valid
    assert validate_sl_side(sl_price=78000, current_rate=80000, is_short=False)


def test_long_wrong_side_sl_at_current_rejected():
    # SL at exact current → would trigger immediately
    assert not validate_sl_side(sl_price=80000, current_rate=80000, is_short=False)


def test_long_wrong_side_sl_above_current_rejected():
    # BTC long, SL at $82k (above current $80k) — would trigger immediately
    assert not validate_sl_side(sl_price=82000, current_rate=80000, is_short=False)


def test_short_valid_sl_above_current():
    # BTC short at $80k, SL at $82k → valid
    assert validate_sl_side(sl_price=82000, current_rate=80000, is_short=True)


def test_short_wrong_side_sl_at_current_rejected():
    assert not validate_sl_side(sl_price=80000, current_rate=80000, is_short=True)


def test_short_wrong_side_sl_below_current_rejected():
    # BTC short, SL at $78k (below current $80k) — would trigger immediately
    assert not validate_sl_side(sl_price=78000, current_rate=80000, is_short=True)


def test_long_sl_just_below_current_accepted():
    # Tight stop just below current — valid
    assert validate_sl_side(sl_price=79999, current_rate=80000, is_short=False)


def test_short_sl_just_above_current_accepted():
    assert validate_sl_side(sl_price=80001, current_rate=80000, is_short=True)


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
