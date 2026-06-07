"""Unit tests for the executor's payload builders + sizing.

The builders are the pure-function core of the Freqtrade REST plumbing —
they encode the contract codex P0 #1+#2 fixed (flat field names, market
orders, base-currency partial-exit math).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.executor import (  # noqa: E402
    SizingConfig, build_forceenter_body, build_forceexit_body,
    sanity_check_entry, size_position,
)


# ── force_enter payload ───────────────────────────────────────────────────


def test_forceenter_body_market_long():
    body = build_forceenter_body("BTC/USDT:USDT", "long", 12.34, 5.0)
    assert body["pair"] == "BTC/USDT:USDT"
    assert body["side"] == "long"
    assert body["stakeamount"] == 12.34         # FLAT field name, not stake_amount
    assert body["leverage"] == 5.0
    assert body["ordertype"] == "market"        # FLAT field name, not order_type
    assert body["entry_tag"] == "insiders"
    # CRITICAL: must NOT carry `price` (would make it a LIMIT order)
    assert "price" not in body
    assert "stake_amount" not in body
    assert "order_type" not in body


def test_forceenter_body_market_short():
    body = build_forceenter_body("ETH/USDT:USDT", "short", 8.0, 10.0)
    assert body["side"] == "short"
    assert body["stakeamount"] == 8.0
    assert body["ordertype"] == "market"


def test_forceenter_body_stake_rounded_to_cents():
    body = build_forceenter_body("SOL/USDT:USDT", "long", 12.3456789, 3.0)
    assert body["stakeamount"] == 12.35


# ── force_exit payload ────────────────────────────────────────────────────


def test_forceexit_body_full_exit_omits_amount():
    body = build_forceexit_body(42, amount_pct=None, current_amount=None)
    assert body == {"tradeid": "42", "ordertype": "market"}
    assert "amount" not in body


def test_forceexit_body_amount_pct_100_treats_as_full():
    body = build_forceexit_body(42, amount_pct=100, current_amount=0.5)
    assert "amount" not in body  # 100% == full exit, omit amount


def test_forceexit_body_partial_uses_base_amount():
    """The whole P0 #2 fix in one assertion: amount_pct=50 with
    current_amount=0.5 BTC must yield amount=0.25 (base coins), NOT 0.5."""
    body = build_forceexit_body(42, amount_pct=50, current_amount=0.5)
    assert body["amount"] == 0.25
    assert body["tradeid"] == "42"


def test_forceexit_body_partial_30pct_small_position():
    body = build_forceexit_body(42, amount_pct=30, current_amount=120.0)  # 120 SOL
    assert body["amount"] == 36.0  # 120 * 0.30


def test_forceexit_body_partial_with_missing_amount_omits():
    """If we have a pct but somehow no current_amount, fall back to
    full-exit body — better than sending bogus amount."""
    body = build_forceexit_body(42, amount_pct=50, current_amount=None)
    assert "amount" not in body


def test_forceexit_body_partial_with_zero_amount_omits():
    body = build_forceexit_body(42, amount_pct=50, current_amount=0)
    assert "amount" not in body


def test_forceexit_body_rounding_8dp():
    body = build_forceexit_body(42, amount_pct=33.3333, current_amount=1.0)
    # 0.333333 -> rounds to 8dp
    assert body["amount"] == 0.333333


# ── Sizing ────────────────────────────────────────────────────────────────


def test_size_position_basic():
    cfg = SizingConfig(risk_usd=2.0, margin_usd=10.0, max_leverage=30.0)
    # 1% SL distance → stake = $2 / 0.01 = $200, leverage = 20x
    stake, lev = size_position(entry=100.0, sl=99.0, cfg=cfg)
    assert stake == 200.0
    assert lev == 20.0


def test_size_position_caps_at_max_leverage():
    cfg = SizingConfig(risk_usd=2.0, margin_usd=10.0, max_leverage=30.0)
    # 0.1% SL → would be 2000 stake / 200x leverage → cap at 30x
    stake, lev = size_position(entry=1000.0, sl=999.0, cfg=cfg)
    assert lev == 30.0
    assert stake == 300.0  # 30 * 10


def test_size_position_rejects_equal_entry_sl():
    cfg = SizingConfig()
    import pytest
    try:
        size_position(entry=100.0, sl=100.0, cfg=cfg)
    except ValueError:
        return
    raise AssertionError("expected ValueError for entry == sl")


# ── Sanity check ──────────────────────────────────────────────────────────


def test_sanity_skip_list_short_circuits():
    ok, reason = sanity_check_entry("MNT", 1.0, 1.0)
    assert not ok
    assert "skip-list" in reason


def test_sanity_within_band():
    ok, _ = sanity_check_entry("BTC", 80000.0, 80100.0)
    assert ok


def test_sanity_outside_band():
    ok, reason = sanity_check_entry("ETH", 77100.0, 2400.0)
    assert not ok
    assert "deviation" in reason


def test_sanity_mark_none_fails_closed():
    ok, reason = sanity_check_entry("BTC", 80000.0, None)
    assert not ok


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
