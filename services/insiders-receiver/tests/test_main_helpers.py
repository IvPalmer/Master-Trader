"""Unit tests for receiver-side helper logic that doesn't need the
FastAPI/Freqtrade roundtrip — specifically the _ft_response_ok guard
that prevents graph mutation on FT failure (P0 #3).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import (  # noqa: E402
    _ft_response_kind, _ft_response_ok, validate_open_payload,
)


def test_ok_on_2xx_no_error():
    assert _ft_response_ok({"_http_status": 200, "trade_id": 1})


def test_ok_on_2xx_boundary():
    assert _ft_response_ok({"_http_status": 200})
    assert _ft_response_ok({"_http_status": 299})


def test_not_ok_on_3xx():
    assert not _ft_response_ok({"_http_status": 301})


def test_not_ok_on_4xx():
    assert not _ft_response_ok({"_http_status": 400, "error": "bad"})


def test_not_ok_on_5xx():
    assert not _ft_response_ok({"_http_status": 500})


def test_not_ok_when_error_key_present_even_on_2xx():
    """If the FT response carries an `error` key, treat as failure even if
    the HTTP code looks fine — caller's exception-handler sets {error: ...}."""
    assert not _ft_response_ok({"_http_status": 200, "error": "timeout"})


def test_not_ok_on_missing_status():
    assert not _ft_response_ok({})


def test_not_ok_on_non_dict():
    assert not _ft_response_ok("oops")
    assert not _ft_response_ok(None)
    assert not _ft_response_ok([])


# ── validate_open_payload — cold-path defensive validator (P1 #E) ─────────


def _ok_open(**overrides):
    base = {
        "kind": "open",
        "symbol": "BTC",
        "direction": "long",
        "entry": 80000.0,
        "sl": 78000.0,
    }
    base.update(overrides)
    return base


def test_validate_ok_minimal():
    ok, _ = validate_open_payload(_ok_open())
    assert ok


def test_validate_ok_with_entry_range():
    cls = _ok_open()
    del cls["entry"]
    cls["entry_range"] = [79000, 80000]
    ok, _ = validate_open_payload(cls)
    assert ok


def test_validate_ok_market_entry_no_range():
    cls = _ok_open()
    cls["entry"] = "market"
    ok, _ = validate_open_payload(cls)
    assert ok  # market entry resolved via mark price downstream


def test_validate_ok_entry_none_falls_back_to_mark():
    cls = _ok_open()
    cls["entry"] = None
    ok, _ = validate_open_payload(cls)
    assert ok


def test_validate_rejects_non_string_symbol():
    ok, reason = validate_open_payload(_ok_open(symbol=123))
    assert not ok
    assert "symbol" in reason


def test_validate_rejects_empty_symbol():
    ok, _ = validate_open_payload(_ok_open(symbol=""))
    assert not ok


def test_validate_rejects_garbage_direction():
    ok, reason = validate_open_payload(_ok_open(direction="up"))
    assert not ok
    assert "direction" in reason


def test_validate_rejects_none_sl():
    cls = _ok_open(); cls["sl"] = None
    ok, _ = validate_open_payload(cls)
    assert not ok


def test_validate_rejects_string_sl():
    ok, _ = validate_open_payload(_ok_open(sl="foo"))
    assert not ok


def test_validate_rejects_zero_sl():
    ok, _ = validate_open_payload(_ok_open(sl=0))
    assert not ok


def test_validate_rejects_negative_entry():
    ok, _ = validate_open_payload(_ok_open(entry=-100))
    assert not ok


def test_validate_rejects_bad_entry_range():
    cls = _ok_open()
    del cls["entry"]
    cls["entry_range"] = [80000]  # wrong length
    ok, _ = validate_open_payload(cls)
    assert not ok


def test_validate_rejects_bad_tp():
    ok, _ = validate_open_payload(_ok_open(tp="high"))
    assert not ok


def test_validate_accepts_missing_tp():
    cls = _ok_open()  # no tp set
    ok, _ = validate_open_payload(cls)
    assert ok


# ── _ft_response_kind — 3-state classifier (round-3) ──────────────────────


def test_kind_accepted_on_2xx_no_error():
    assert _ft_response_kind({"_http_status": 200, "trade_id": 1}) == "accepted"
    assert _ft_response_kind({"_http_status": 201}) == "accepted"


def test_kind_rejected_on_4xx():
    assert _ft_response_kind({"_http_status": 400}) == "rejected"
    assert _ft_response_kind({"_http_status": 422, "error": "bad"}) == "rejected"


def test_kind_rejected_on_2xx_with_error():
    """FT can return 2xx with an explicit error message — that's a definite
    application-level rejection, no exposure created."""
    assert _ft_response_kind({"_http_status": 200, "error": "Insufficient funds"}) == "rejected"


def test_kind_uncertain_on_5xx():
    """5xx means FT crashed mid-request — order may or may not have been
    submitted to the exchange. Reconciler must heal."""
    assert _ft_response_kind({"_http_status": 500}) == "uncertain"
    assert _ft_response_kind({"_http_status": 502}) == "uncertain"
    assert _ft_response_kind({"_http_status": 503, "error": "down"}) == "uncertain"


def test_kind_uncertain_on_exception_wrapped():
    """Exception path wraps as {_http_status: 0, error: "..."}. Must be
    uncertain so reconciler can heal."""
    assert _ft_response_kind({"_http_status": 0, "error": "timeout"}) == "uncertain"


def test_kind_uncertain_on_missing_status():
    assert _ft_response_kind({}) == "uncertain"


def test_kind_uncertain_on_non_dict():
    assert _ft_response_kind(None) == "uncertain"
    assert _ft_response_kind("oops") == "uncertain"


def test_ok_helper_only_true_on_accepted():
    """_ft_response_ok now delegates to _ft_response_kind == 'accepted'."""
    assert _ft_response_ok({"_http_status": 200})
    assert not _ft_response_ok({"_http_status": 500})  # uncertain → not ok
    assert not _ft_response_ok({"_http_status": 400})  # rejected → not ok


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
