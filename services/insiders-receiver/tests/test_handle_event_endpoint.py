"""TestClient-based endpoint smoke for insiders-receiver.

Mirrors the regression test added to killers-receiver after the
2026-05-27 asyncio NameError incident. Goal: catch handler-only
runtime dependency bugs (names referenced inside FastAPI handlers but
only bound in lifespan/function scopes) that unit tests for
`_process_event` bypass entirely.
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
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    os.environ["INSIDERS_DB"] = tf.name
    os.environ["INSIDERS_INSTANCE_ID"] = "test"
    # Disable Claude classifier in tests (we POST the classification directly,
    # so the classifier dispatcher isn't invoked from this path).
    from importlib import reload
    import app.main as m
    reload(m)
    from fastapi.testclient import TestClient
    with TestClient(m.app) as c:
        yield c, m


def test_health_endpoint():
    """Smoke: lifespan + module imports + basic handler all work."""
    with _client() as (client, _m):
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "instance" in body


def test_system_endpoint():
    with _client() as (client, _m):
        r = client.get("/system")
    assert r.status_code == 200
    body = r.json()
    assert body["entries_paused"] is False
    assert body["requested_orphans_count"] == 0


def test_positions_empty():
    with _client() as (client, _m):
        r = client.get("/positions")
    assert r.status_code == 200
    assert r.json() == []


def test_positions_requested_empty():
    with _client() as (client, _m):
        r = client.get("/positions/requested")
    assert r.status_code == 200
    assert r.json() == []


def test_post_event_chat_message():
    """Chat messages early-return without touching FT or DB. Smoke that the
    /event route resolves all module names cleanly."""
    with _client() as (client, m):
        # Patch classifier to return chat directly — avoids needing claude CLI
        async def fake_classify(*args, **kwargs):
            return type("R", (), {
                "classification": {"kind": "chat"},
                "classifier_used": "test-stub",
                "elapsed_ms": 0.0,
                "rule_classification": None,
                "claude_classification": None,
                "disagreement": False,
            })()
        with patch.object(m, "classify", side_effect=fake_classify):
            r = client.post("/event", json={
                "msg_id": 99999,
                "text": "gm",
                "posted_at": "2026-05-27T20:00:00+00:00",
            })
    assert r.status_code == 200, f"got {r.status_code}: {r.text}"
    body = r.json()
    assert body["status"] == "chat"


def test_post_event_duplicate_msg_id():
    """Idempotency: same msg_id posted twice returns 'duplicate' on the
    second hit. Verifies claim_msg flow at the handler level."""
    with _client() as (client, m):
        async def fake_classify(*args, **kwargs):
            return type("R", (), {
                "classification": {"kind": "chat"},
                "classifier_used": "test-stub",
                "elapsed_ms": 0.0,
                "rule_classification": None,
                "claude_classification": None,
                "disagreement": False,
            })()
        with patch.object(m, "classify", side_effect=fake_classify):
            r1 = client.post("/event", json={
                "msg_id": 12321, "text": "first hit",
                "posted_at": "2026-05-27T20:00:00+00:00",
            })
            r2 = client.post("/event", json={
                "msg_id": 12321, "text": "redelivery",
                "posted_at": "2026-05-27T20:00:01+00:00",
            })
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"


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
