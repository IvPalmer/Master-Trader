"""Integration test for the /event FastAPI endpoint via TestClient.

Regression test for the 2026-05-27 19:38 bug: `asyncio` was imported
inside `lifespan` (function scope) but referenced at module scope
inside `handle_event` (`asyncio.create_task(...)`). Every POST /event
returned 500 NameError. The unit tests for `_process_event` passed
because they imported asyncio at the test-file level — they never
exercised the FastAPI handler.

This test goes through the full /event → handler → _process_event →
_format_event_summary → asyncio.create_task(_notify_telegram(...))
path, which would fail on a bare NameError without the top-level
import.
"""
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@contextmanager
def _client():
    """Spin up a TestClient against the real FastAPI app inside a
    lifespan-active context (`with TestClient(app)` triggers startup).
    Each test gets its own SQLite DB."""
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    os.environ["KILLERS_DB"] = tf.name
    os.environ["KILLERS_ACTIVE_TP_LIMITS"] = "true"
    os.environ["KILLERS_NOTIFY_URL"] = ""  # disable notify in tests
    from importlib import reload
    import app.main as m
    reload(m)
    from fastapi.testclient import TestClient
    with TestClient(m.app) as c:
        yield c, m


def test_close_partial_no_active_position_returns_200_not_500():
    """The exact 19:38:14 bug: close_partial for a signal_id we never
    opened. Receiver should return 200 with action=skipped + reason=
    no_active_position. Pre-fix this 500'd with NameError on asyncio."""
    with _client() as (client, _m):
        payload = {
            "msg": {
                "id": 3471,
                "date": "2026-05-27T19:38:14+00:00",
                "text": "📍SIGNAL ID: #2142📍\nCOIN: $XLM/USDT\n"
                        "Direction: LONG\nTarget 1: 0.1515✅\n"
                        "Target 2: 0.1580✅\nTarget 3: 0.1650✅",
            },
            "classification": {
                "id": 3471, "kind": "close_partial",
                "signal_id": 2142, "symbol": "XLM",
                "direction": "long", "pct": None,
                "entry": None, "entry_range": None, "sl": None, "tp": None,
                "confidence": 0.95, "notes": "3 targets hit",
            },
        }
        r = client.post("/event", json=payload)
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["action"] == "skipped"
    assert "no_active_position" in body["reason"]


def test_chat_message_returns_200():
    """Chat kind hits the early return path. Still must traverse
    handle_event cleanly (no NameError on asyncio)."""
    with _client() as (client, _m):
        payload = {
            "msg": {"id": 99001, "date": "2026-05-27T20:00:00+00:00",
                    "text": "GM team"},
            "classification": {"id": 99001, "kind": "chat", "signal_id": None,
                                "symbol": None, "direction": None,
                                "confidence": 0.99, "notes": "greeting"},
        }
        r = client.post("/event", json=payload)
    assert r.status_code == 200
    assert r.json()["action"] == "ignored"


def test_open_event_full_handler_flow_no_500():
    """Open event exercises the longest path through handle_event:
    sizing → mark fetch → slippage gate → force_enter → finalize →
    Phase 2 limit placement → notify task. If anything along that path
    references an unbound module name, this catches it."""
    with _client() as (client, m):
        async def fake_mark(*args, **kwargs):
            return 100500.0

        async def fake_force_enter(*args, **kwargs):
            return {"status": 200,
                    "body": '{"trade_id":777,"amount":0.001}'}

        async def fake_force_exit_limit(*args, **kwargs):
            return {"status": 200, "body": '{"orders":[]}'}

        payload = {
            "msg": {"id": 99002, "date": "2026-05-27T20:00:00+00:00",
                    "text": "📍SIGNAL ID: #555📍\nCOIN: $BTC/USDT\n"
                            "Direction: LONG\nENTRY: 100000 - 101000\n"
                            "TARGETS: 102000 - 105000 - 110000\n"
                            "STOP LOSS: 99000"},
            "classification": {"id": 99002, "kind": "open", "signal_id": 555,
                                "symbol": "BTC", "direction": "long",
                                "entry": None, "entry_range": [100000, 101000],
                                "sl": 99000, "tp": None, "pct": None,
                                "confidence": 0.9, "notes": ""},
        }

        with patch.object(m, "get_binance_mark_price", side_effect=fake_mark), \
             patch.object(m, "ft_force_enter", side_effect=fake_force_enter), \
             patch.object(m, "ft_force_exit_limit",
                          side_effect=fake_force_exit_limit):
            r = client.post("/event", json=payload)

    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["action"] == "force_enter"


def test_healthz_endpoint():
    """Smoke that the app comes up at all (catches startup crashes)."""
    with _client() as (client, _m):
        r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_system_endpoint():
    with _client() as (client, _m):
        r = client.get("/system")
    assert r.status_code == 200
    body = r.json()
    assert body["instance"] == "killers"
    assert body["active_positions_count"] == 0


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
        import sys
        sys.exit(1)
    print(f"\n{len(funcs)} tests passed")
