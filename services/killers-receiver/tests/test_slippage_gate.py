"""Slippage-gate logic test.

The gate itself runs inside `_process_event` and depends on FastAPI app
state, a populated DB, and a live Binance fetch — too much glue for a
unit test. We exercise the pure math here: given (entry_lo, entry_hi,
mark, direction, max_pct), what would the gate decide?
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def slippage_pct(entry_lo: float, entry_hi: float, mark: float, direction: str):
    """Mirror of the inline math in main._process_event slippage gate."""
    if direction == "long":
        return (mark - entry_hi) / entry_hi * 100.0
    return (entry_lo - mark) / entry_lo * 100.0


def breach(entry_lo, entry_hi, mark, direction, max_pct):
    return slippage_pct(entry_lo, entry_hi, mark, direction) > max_pct


# ── LONG cases ────────────────────────────────────────────────────────────


def test_long_at_entry_high_no_breach():
    """Mark exactly at entry_hi → 0% slippage, no breach."""
    assert not breach(56.80, 57.00, 57.00, "long", 3.0)


def test_long_within_entry_range_no_breach():
    """Mark below entry_hi → negative slippage, no breach."""
    assert not breach(56.80, 57.00, 56.90, "long", 3.0)


def test_long_2pct_above_no_breach():
    """2% above entry_hi with 3% cap → no breach."""
    assert not breach(56.80, 57.00, 57.00 * 1.02, "long", 3.0)


def test_long_just_under_cap_no_breach():
    """2.99% slippage with 3% cap → no breach. (Exact 3% boundary has
    float-drift issues — receiver uses strict `>` comparison so a value
    1e-12 above 3.0 trips. That's acceptable in production; pin the test
    safely under to avoid fp noise.)"""
    mark = 57.00 * 1.0299
    s = slippage_pct(56.80, 57.00, mark, "long")
    assert s < 3.0
    assert not breach(56.80, 57.00, mark, "long", 3.0)


def test_long_above_cap_breach():
    """HYPE #2144 case: mark 60.862, entry_hi 57.00 → ~6.78% slippage."""
    s = slippage_pct(56.80, 57.00, 60.862, "long")
    assert abs(s - 6.776) < 0.01
    assert breach(56.80, 57.00, 60.862, "long", 3.0)


def test_long_well_above_cap_breach():
    """Mark 70 vs entry_hi 57 → ~22.8% slippage, hard breach."""
    assert breach(56.80, 57.00, 70.0, "long", 3.0)


# ── SHORT cases ───────────────────────────────────────────────────────────


def test_short_at_entry_low_no_breach():
    """Mark at entry_lo → 0% slippage."""
    assert not breach(57.00, 58.00, 57.00, "short", 3.0)


def test_short_within_entry_range_no_breach():
    """Mark above entry_lo (favorable for SHORT) → negative slippage."""
    assert not breach(57.00, 58.00, 57.50, "short", 3.0)


def test_short_2pct_below_no_breach():
    assert not breach(57.00, 58.00, 57.00 * 0.98, "short", 3.0)


def test_short_above_cap_breach():
    """SHORT example: entry_lo 57, mark 53 → 7% slippage below entry."""
    s = slippage_pct(57.00, 58.00, 53.00, "short")
    assert abs(s - 7.0175) < 0.01
    assert breach(57.00, 58.00, 53.00, "short", 3.0)


# ── Configurability ──────────────────────────────────────────────────────


def test_max_pct_zero_disables_breach():
    """Cap of 0 means 'any positive slippage trips' — set to 0 to disable
    via the boolean check in the receiver (`max_entry_slippage_pct > 0`).
    Math here just shows 0% with positive mark trips."""
    assert breach(56.80, 57.00, 60.862, "long", 0.0)


def test_max_pct_tight():
    """Tight cap (0.5%) — even small overrun trips."""
    assert breach(56.80, 57.00, 57.00 * 1.01, "long", 0.5)


def test_max_pct_loose():
    """Loose cap (10%) — HYPE wouldn't trip."""
    assert not breach(56.80, 57.00, 60.862, "long", 10.0)


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
