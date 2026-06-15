import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import compute_booked_pct


def test_partial_exit_booked_pct():
    assert compute_booked_pct(0.143, 0.488) == 70.7  # TAO live: ~71%

def test_single_exit_is_zero():
    assert compute_booked_pct(1.0, 1.0) == 0.0

def test_missing_denominator_is_none():
    assert compute_booked_pct(1.0, None) is None
    assert compute_booked_pct(1.0, 0) is None

def test_pending_entry_amount_zero_is_none():
    assert compute_booked_pct(0, 1.0) is None

def test_string_numerics_coerced():
    assert compute_booked_pct("0.143", "0.488") == 70.7

def test_fee_dust_floored_to_zero():
    assert compute_booked_pct(0.999, 1.0) == 0.0  # 0.1% shrink < dust threshold

def test_amount_exceeds_requested_clamps_zero():
    assert compute_booked_pct(1.2, 1.0) == 0.0

def test_garbage_is_none():
    assert compute_booked_pct("x", "y") is None
