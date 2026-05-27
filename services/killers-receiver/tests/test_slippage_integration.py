"""Integration test for the slippage gate routed through `_process_event`
with a fast-path-shaped classification.

The pure-math test in test_slippage_gate.py mirrors the inline formula,
but a future refactor could break the receiver wiring (e.g. the
entry_range fallback when entry_lo/entry_hi are NULL) while leaving the
math tests passing. This test exercises the actual code path.
"""
import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import main as receiver_main  # noqa: E402


class _FakeAppState:
    """Mimics FastAPI app.state for _process_event's getattr() lookups."""
    def __init__(self, conn, cfg):
        self.conn = conn
        self.cfg = cfg
        self.ft_session = None
        self.public_session = None
        self.notify_tasks = set()


def _setup(conn_path, *, max_slip=3.0):
    """Stage app.state + Config so _process_event runs without FastAPI."""
    import os
    # Point Config at the temp DB; cap from the test param.
    os.environ["KILLERS_DB"] = conn_path
    os.environ["KILLERS_MAX_ENTRY_SLIPPAGE_PCT"] = str(max_slip)
    cfg = receiver_main.Config()
    conn = receiver_main.init_db(cfg.db_path)
    state = _FakeAppState(conn, cfg)
    receiver_main.app.state = state
    return state


def _hype_fast_path_payload(msg_id: int = 999999):
    """Mirrors the rule fast-path output shape — entry_range present, no
    entry_lo/entry_hi keys, raw msg text carries the TARGETS line."""
    msg = {
        "id": msg_id,
        "date": "2026-05-27T15:00:00+00:00",
        "text": (
            "📍SIGNAL ID: #2144📍\n"
            "COIN: $HYPE/USDT (2-5x)\n"
            "Direction: LONG\n"
            "ENTRY: 56.80 - 57.00\n\n"
            "TARGETS: 59.50 - 62.00 - 65.00 - 68.00 - 72.00 - 77.00 - 83.00 - 90.00\n\n"
            "STOP LOSS: 52.00\n"
        ),
    }
    classification = {
        "id": msg_id,
        "kind": "open",
        "signal_id": 2144,
        "symbol": "HYPE",
        "direction": "long",
        "entry": None,
        "entry_range": [56.80, 57.00],
        "sl": 52.00,
        "tp": None,
        "pct": None,
        "applies_to": None,
        "confidence": 1.0,
        "notes": "rule-fast-path",
    }
    return receiver_main.EventPayload(msg=msg, classification=classification)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_fast_path_payload_hits_slippage_gate():
    """HYPE #2144 shape with mark=60.862 must skip with entry_slippage_exceeded."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        _setup(tf.name, max_slip=3.0)
    payload = _hype_fast_path_payload(msg_id=999001)

    async def fake_mark(*args, **kwargs):
        return 60.862

    with patch.object(receiver_main, "get_binance_mark_price",
                      side_effect=fake_mark):
        result = _run(receiver_main._process_event(payload))

    assert result["action"] == "skipped"
    assert result["reason"] == "entry_slippage_exceeded"
    assert abs(result["slippage_pct"] - 6.78) < 0.01
    assert result["entry_lo"] == 56.80
    assert result["entry_hi"] == 57.00


def test_fast_path_payload_within_cap_proceeds():
    """Same payload, mark within 3% of entry_hi → slippage gate passes.
    Position still gets blocked at force_enter (FT not running), but the
    skip reason must NOT be entry_slippage_exceeded."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        _setup(tf.name, max_slip=3.0)
    payload = _hype_fast_path_payload(msg_id=999002)

    async def fake_mark(*args, **kwargs):
        return 58.0  # +1.75% above entry_hi → under 3% cap

    async def fake_force_enter(*args, **kwargs):
        return {"status": 503, "body": "ft unavailable"}

    with patch.object(receiver_main, "get_binance_mark_price",
                      side_effect=fake_mark), \
         patch.object(receiver_main, "ft_force_enter",
                      side_effect=fake_force_enter):
        result = _run(receiver_main._process_event(payload))

    # Slippage gate passed (no entry_slippage_exceeded). Could be force_enter
    # action with ft failed, OR target-guard skip — but NOT slippage-related.
    assert result.get("reason") != "entry_slippage_exceeded"


def test_entry_bounds_missing_fails_closed():
    """Classification with all entry fields null but cap enabled → must
    skip with entry_bounds_missing (NOT proceed)."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        _setup(tf.name, max_slip=3.0)
    msg = {"id": 999003,
           "date": "2026-05-27T15:00:00+00:00",
           "text": "📍SIGNAL ID: #999📍\nCOIN: $BTC/USDT\nDirection: LONG\nSTOP LOSS: 90000\n"}
    classification = {
        "id": 999003, "kind": "open", "signal_id": 999,
        "symbol": "BTC", "direction": "long",
        "entry": None, "entry_range": None, "entry_lo": None, "entry_hi": None,
        "sl": 90000, "tp": None, "pct": None, "applies_to": None,
        "confidence": 0.8, "notes": "claude path, malformed",
    }
    payload = receiver_main.EventPayload(msg=msg, classification=classification)

    async def fake_mark(*args, **kwargs):
        return 100000.0

    with patch.object(receiver_main, "get_binance_mark_price",
                      side_effect=fake_mark):
        result = _run(receiver_main._process_event(payload))
    assert result["action"] == "skipped"
    assert result["reason"] == "entry_bounds_missing"


def test_short_fast_path_slippage_gate():
    """SHORT with mark below entry_lo → skip with entry_slippage_exceeded."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        _setup(tf.name, max_slip=3.0)
    msg = {"id": 999004,
           "date": "2026-05-27T15:00:00+00:00",
           "text": "📍SIGNAL ID: #888📍\nCOIN: $BTC/USDT (3x)\nDirection: SHORT\nENTRY: 100000 - 102000\nTARGETS: 98000 - 95000\nSTOP LOSS: 105000\n"}
    classification = {
        "id": 999004, "kind": "open", "signal_id": 888,
        "symbol": "BTC", "direction": "short",
        "entry": None, "entry_range": [100000, 102000],
        "sl": 105000, "tp": None, "pct": None, "applies_to": None,
        "confidence": 1.0, "notes": "fast-path",
    }
    payload = receiver_main.EventPayload(msg=msg, classification=classification)

    async def fake_mark(*args, **kwargs):
        return 95000.0  # 5% below entry_lo → breach

    with patch.object(receiver_main, "get_binance_mark_price",
                      side_effect=fake_mark):
        result = _run(receiver_main._process_event(payload))
    assert result["action"] == "skipped"
    assert result["reason"] == "entry_slippage_exceeded"
    assert abs(result["slippage_pct"] - 5.0) < 0.01


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
