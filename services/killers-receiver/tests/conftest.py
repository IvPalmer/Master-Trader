"""Shared test setup for the receiver suite.

`Config()` now refuses to construct without KILLERS_INGRESS_TOKEN — the
receiver must never come up with an unauthenticated trading ingress. Every
test that builds a Config or a TestClient would otherwise fail on that guard,
so provide a token here rather than in a dozen fixtures.

`setdefault` (not `[...] =`) so a caller can still export a different token to
exercise a mismatch.
"""
import os

TEST_INGRESS_TOKEN = "test-ingress-token-not-a-real-secret"

os.environ.setdefault("KILLERS_INGRESS_TOKEN", TEST_INGRESS_TOKEN)


def auth_headers(token: str | None = None) -> dict[str, str]:
    """Bearer header for the receiver's authenticated routes."""
    return {"Authorization": f"Bearer {token or os.environ['KILLERS_INGRESS_TOKEN']}"}
