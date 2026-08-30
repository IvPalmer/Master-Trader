"""Ingress authentication for the receiver's trading control plane.

Context (2026-08-30 audit): both receivers sit on the shared external
`dokploy-network` alongside ~25 unrelated application containers, and every
route was unauthenticated. `POST /event` sizes a signal and calls Freqtrade
`/forceenter` with the receiver's stored credentials, so anything on that
network could open a leveraged position on a funded Hyperliquid account.

These tests pin the two properties that fix depends on:
  1. the process refuses to start without a token (no silent fall-open), and
  2. every route except the liveness probe rejects an unauthenticated caller.

The route sweep is deliberately derived from the live router rather than a
hardcoded list, so a future endpoint added without auth fails here.
"""
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.conftest import TEST_INGRESS_TOKEN, auth_headers  # noqa: E402


@contextmanager
def _module(**env):
    """Reload app.main under a temporary environment."""
    saved = {k: os.environ.get(k) for k in env}
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    saved["KILLERS_DB"] = os.environ.get("KILLERS_DB")
    saved["KILLERS_NOTIFY_URL"] = os.environ.get("KILLERS_NOTIFY_URL")
    os.environ["KILLERS_DB"] = tf.name
    os.environ["KILLERS_NOTIFY_URL"] = ""
    for key, value in env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        from importlib import reload
        import app.main as m
        reload(m)
        yield m
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        from importlib import reload
        import app.main as m
        reload(m)


@contextmanager
def _client(**env):
    from fastapi.testclient import TestClient
    with _module(**env) as m:
        with TestClient(m.app) as client:
            yield client, m


# ── Startup guard ─────────────────────────────────────────────────────────


def test_config_refuses_to_build_without_a_token():
    """No token → RuntimeError at Config(), so the container dies loudly."""
    with _module(KILLERS_INGRESS_TOKEN=None) as m:
        with pytest.raises(RuntimeError, match="KILLERS_INGRESS_TOKEN is required"):
            m.Config()


def test_config_rejects_a_short_token():
    """A guessable token is refused rather than quietly accepted."""
    with _module(KILLERS_INGRESS_TOKEN="short") as m:
        with pytest.raises(RuntimeError, match="at least"):
            m.Config()


def test_config_strips_surrounding_whitespace():
    """A trailing newline from a .env file must not become part of the secret."""
    token = f"  {TEST_INGRESS_TOKEN}\n"
    with _module(KILLERS_INGRESS_TOKEN=token) as m:
        assert m.Config().ingress_token == TEST_INGRESS_TOKEN


# ── Route protection ──────────────────────────────────────────────────────


def test_healthz_is_the_only_unauthenticated_route():
    """Liveness is open (Docker healthcheck); everything else is not.

    Derived from the live router so a new unauthenticated endpoint fails here
    instead of shipping.
    """
    with _client() as (client, m):
        # FastAPI's generated docs routes ignore app-level dependencies, so they
        # answered 200 without a token and published every route and schema.
        # They are disabled outright rather than exempted.
        for path in ("/openapi.json", "/docs", "/redoc"):
            assert client.get(path).status_code == 404, (
                f"{path} must not be served — app dependencies do not protect it"
            )

        for route in m.app.routes:
            path = getattr(route, "path", "")
            methods = getattr(route, "methods", set()) or set()
            if not path.startswith("/"):
                continue
            # Fill path params with a value that cannot match a real row, so a
            # 401 can never be confused with a 404 for a missing record.
            concrete = path.replace("{ft_trade_id}", "999999").replace(
                "{event_id}", "999999"
            )
            method = "POST" if "POST" in methods else "GET"
            response = client.request(method, concrete)
            if path == "/healthz":
                assert response.status_code == 200, path
            else:
                assert response.status_code == 401, (
                    f"{method} {path} answered {response.status_code} "
                    f"without a token — it must be 401"
                )


def test_event_rejects_missing_wrong_and_malformed_tokens():
    """POST /event is the route that can move money. Cover the near misses."""
    payload = {"msg": {"id": 1, "text": "x"}, "classification": {"kind": "chat"}}
    with _client() as (client, _m):
        assert client.post("/event", json=payload).status_code == 401
        assert client.post(
            "/event", json=payload,
            headers={"Authorization": f"Bearer {TEST_INGRESS_TOKEN}-wrong"},
        ).status_code == 401
        # Right secret, wrong scheme.
        assert client.post(
            "/event", json=payload,
            headers={"Authorization": f"Basic {TEST_INGRESS_TOKEN}"},
        ).status_code == 401
        # Bare token with no scheme.
        assert client.post(
            "/event", json=payload,
            headers={"Authorization": TEST_INGRESS_TOKEN},
        ).status_code == 401
        # Non-ASCII bytes must be rejected, not raise inside compare_digest
        # (str compare_digest raises TypeError on non-ASCII, and the header is
        # attacker-controlled). Sent as raw bytes because httpx will not
        # ASCII-encode a str header for us.
        assert client.post(
            "/event", json=payload,
            headers={"Authorization": "Bearer ✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓".encode("utf-8")},
        ).status_code == 401
        # And the real token still works.
        assert client.post(
            "/event", json=payload, headers=auth_headers()
        ).status_code == 200


def test_two_receivers_do_not_share_a_token():
    """The insiders instance must not accept the killers token.

    Both containers run this same image; only the env differs. A token issued
    for one funded account must be useless against the other.
    """
    other = "insiders-ingress-token-not-a-real-secret"
    payload = {"msg": {"id": 2, "text": "x"}, "classification": {"kind": "chat"}}
    with _client(KILLERS_INGRESS_TOKEN=other) as (client, _m):
        assert client.post(
            "/event", json=payload, headers=auth_headers(TEST_INGRESS_TOKEN)
        ).status_code == 401
        assert client.post(
            "/event", json=payload, headers=auth_headers(other)
        ).status_code == 200
