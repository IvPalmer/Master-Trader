"""
Shared API utility for Freqtrade bot HTTP calls.

Provides retry logic with exponential backoff so scripts don't fail
silently when a bot is restarting or temporarily unavailable.

Also includes provider fallback pattern (inspired by Claude Code) and
deferred persistence for safe state writes.
"""

import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar

import requests
from requests.auth import HTTPBasicAuth

# Mixed-cred fleet: live bots use rotated FREQTRADE__API_SERVER__* creds.
# We try the rotated creds first (covers all live bots) and, only when
# explicitly permitted, fall back to the legacy freqtrader/mastertrader
# defaults for a dry-run bot that never migrated.
_ROTATED_USER = os.environ.get("FREQTRADE__API_SERVER__USERNAME")
_ROTATED_PASS = os.environ.get("FREQTRADE__API_SERVER__PASSWORD")
_LEGACY_USER = "freqtrader"
_LEGACY_PASS = "mastertrader"

# freqtrade's documented defaults are public knowledge, so a client that
# always retries with them turns any reachable bot into a guessable target and
# silently papers over a bot running without its env override. Off by default;
# set FT_ALLOW_LEGACY_API_CREDS=true only to unblock a legacy dry-run bot.
ALLOW_LEGACY_CREDS = os.environ.get(
    "FT_ALLOW_LEGACY_API_CREDS", "false"
).strip().lower() in ("true", "1", "yes")

# Per-bot credentials, when the operator has issued them. Keyed by the compose
# service name so one leaked bot credential cannot drive the rest of the fleet.
# Unset per-bot vars fall through to the shared pair, so adopting this is
# incremental — a bot at a time — and a fleet with none set behaves exactly as
# it did before. The slug set is locked to the compose file and the dashboard
# by tests/test_fleet_hardening_2026_08_30.py.
# Both the compose service name and the container_name are valid DNS names on
# the network and different callers use different ones (the exporter passes the
# service, the dashboard the container), so both are keys here.
SERVICE_API_SLUGS = {
    "keltnerbouncev1": "KELTNER",
    "ft-keltner-bounce": "KELTNER",
    "fundingfadev1": "FUNDINGFADE",
    "ft-funding-fade": "FUNDINGFADE",
    "oi-trend-pullback": "OITREND",
    "ft-oi-trend-pullback": "OITREND",
    "ft-killers-scalp": "KILLERS",
    "ft-insiders-scalp": "INSIDERS",
    "ft-short-keltner-hl-live": "SHORTKELTNER",
}


# Host-side callers (the daily health report cron) reach each bot on a
# published loopback port, not by service name, so there is no hostname to
# derive a slug from. Ports come from docker-compose.prod.yml.
PORT_API_SLUGS = {
    8095: "KELTNER",
    8096: "FUNDINGFADE",
    8102: "OITREND",
    8099: "KILLERS",
    8098: "INSIDERS",
    8103: "SHORTKELTNER",
}

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _shared_candidates() -> tuple:
    if _ROTATED_USER and _ROTATED_PASS:
        return (HTTPBasicAuth(_ROTATED_USER, _ROTATED_PASS),)
    if ALLOW_LEGACY_CREDS:
        return (HTTPBasicAuth(_LEGACY_USER, _LEGACY_PASS),)
    # No credentials configured and legacy explicitly disallowed: return
    # nothing rather than silently trying freqtrade's published defaults. The
    # flag has to mean what it says, otherwise a credential-less cron would
    # still authenticate against any bot left on the defaults.
    return ()


def auth_candidates_for(service: str | None = None, port: int | None = None) -> tuple:
    """Credentials to try for one bot, most specific first.

    `service` is the compose service or container name (callers on the docker
    network); `port` is the published loopback port (callers on the host).
    Either resolves the same per-bot slug.
    """
    slug = SERVICE_API_SLUGS.get(service or "")
    if not slug and port is not None:
        slug = PORT_API_SLUGS.get(port)
    shared = _shared_candidates()
    if not slug:
        return shared
    user = os.environ.get(f"FT_API_USER_{slug}")
    password = os.environ.get(f"FT_API_PASS_{slug}")
    if user and password:
        return (HTTPBasicAuth(user, password), *shared)
    if user or password:
        # Half-configured is the dangerous state: the bot's own compose entry
        # resolves username and password independently, so it can come up on
        # a dedicated user with the shared password while every client here
        # falls back to the shared pair and gets 401. Say so loudly.
        log.error(
            "FT_API_USER_%s / FT_API_PASS_%s are half-configured — set both or "
            "neither; falling back to the shared credentials, which will not "
            "match what that bot actually started with.", slug, slug,
        )
    return shared


_AUTH_CANDIDATES = _shared_candidates()

# Preserve the pre-existing AUTH / API_USER / API_PASS symbols for callers that
# import them directly. They are a single best-guess credential, not the
# resolution chain — new code should call auth_candidates_for(). When nothing
# is configured these keep the legacy literals so an import cannot fail; the
# request path (_shared_candidates) is what actually enforces the flag.
AUTH = _AUTH_CANDIDATES[0] if _AUTH_CANDIDATES else HTTPBasicAuth(
    _LEGACY_USER, _LEGACY_PASS
)
API_USER = AUTH.username
API_PASS = AUTH.password

log = logging.getLogger("api-utils")

T = TypeVar("T")


def api_get(
    port: int,
    endpoint: str,
    timeout: int = 10,
    retries: int = 3,
    base_host: str = "127.0.0.1",
) -> Optional[Any]:
    """GET JSON from a Freqtrade bot API with retry and exponential backoff.

    Args:
        port: Bot API port (e.g. 8080).
        endpoint: API path without leading slash (e.g. "profit", "status").
        timeout: HTTP request timeout in seconds.
        retries: Number of attempts before giving up.
        base_host: Hostname or IP to connect to.

    Returns:
        Parsed JSON (dict or list) on success, None on final failure.
    """
    url = f"http://{base_host}:{port}/api/v1/{endpoint}"
    backoff = 1  # seconds — doubles each retry (1, 2, 4, ...)
    # Callers inside the compose network pass the service name as base_host;
    # host-side callers use a loopback address and the published port. Both
    # resolve the same per-bot slug.
    candidates = auth_candidates_for(
        base_host, port=port if base_host in _LOOPBACK_HOSTS else None
    )
    if not candidates:
        log.error(
            "No credentials available for %s — set FREQTRADE__API_SERVER__"
            "USERNAME/PASSWORD, or the per-bot pair, or "
            "FT_ALLOW_LEGACY_API_CREDS=true to permit freqtrade's defaults.",
            url,
        )
        return None

    for attempt in range(1, retries + 1):
        last_exc: Optional[Exception] = None
        # Try each cred set in order; on 401 move to the next candidate without
        # counting it as a retry. Other HTTP errors fall through to the backoff.
        for auth in candidates:
            try:
                resp = requests.get(url, auth=auth, timeout=timeout)
                if resp.status_code == 401:
                    last_exc = Exception(f"401 Unauthorized with user={auth.username}")
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                last_exc = exc
                break  # non-auth error — stop trying creds, apply backoff
        if attempt < retries:
            log.warning(
                "Retry %d/%d for %s: %s (backoff %ds)",
                attempt, retries, url, last_exc, backoff,
            )
            time.sleep(backoff)
            backoff *= 2
        else:
            log.error(
                "Failed after %d attempts for %s: %s",
                retries, url, last_exc,
            )
    return None


# ---------------------------------------------------------------------------
# Provider fallback pattern
# ---------------------------------------------------------------------------


def execute_with_fallback(
    primary_fn: Callable[[], T],
    fallback_fn: Callable[[], T],
    context: str = "",
) -> Optional[T]:
    """Execute primary function, fall back to secondary on transient failure.

    Inspired by Claude Code's provider fallback pattern for resilient
    external service calls.

    Args:
        primary_fn: Primary callable (e.g. fetch from live API).
        fallback_fn: Fallback callable (e.g. fetch from cache/alternate).
        context: Description for logging.

    Returns:
        Result from primary or fallback, None if both fail.
    """
    try:
        return primary_fn()
    except (ConnectionError, TimeoutError, requests.RequestException) as exc:
        log.warning(
            "Primary failed for %s: %s — trying fallback", context, exc
        )
        try:
            return fallback_fn()
        except Exception as fallback_exc:
            log.error(
                "Fallback also failed for %s: %s", context, fallback_exc
            )
            return None


# ---------------------------------------------------------------------------
# Deferred persistence
# ---------------------------------------------------------------------------


class DeferredStateWriter:
    """Write state only after confirmation, preventing inconsistent records.

    Inspired by Claude Code's deferred persistence pattern — wait for
    the authoritative response before committing state to disk.

    Usage:
        writer = DeferredStateWriter(Path("state.json"))
        writer.stage({"key": "pending_value"})
        # ... wait for confirmation ...
        writer.commit()  # Only now writes to disk
        # Or: writer.discard() to throw away staged changes
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._staged: Optional[Any] = None

    def stage(self, data: Any) -> None:
        """Stage data for writing (does not write to disk)."""
        self._staged = data

    def commit(self) -> bool:
        """Write staged data to disk. Returns True on success."""
        if self._staged is None:
            log.warning("Nothing staged for %s", self.path)
            return False
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._staged, indent=2, default=str),
                encoding="utf-8",
            )
            tmp.rename(self.path)
            self._staged = None
            return True
        except Exception as exc:
            log.error("Failed to commit state to %s: %s", self.path, exc)
            return False

    def discard(self) -> None:
        """Discard staged data without writing."""
        self._staged = None

    @property
    def has_staged(self) -> bool:
        return self._staged is not None


# ---------------------------------------------------------------------------
# Per-trade-type rate limiting
# ---------------------------------------------------------------------------

# Default limits per trade type per hour
TRADE_TYPE_LIMITS: Dict[str, Dict[str, int]] = {
    "scalp": {"max_per_hour": 20, "max_concurrent": 5},
    "swing": {"max_per_hour": 5, "max_concurrent": 10},
    "trend-follower": {"max_per_hour": 5, "max_concurrent": 10},
    "mean-reversion": {"max_per_hour": 10, "max_concurrent": 5},
    "hybrid": {"max_per_hour": 8, "max_concurrent": 8},
    "bear-short": {"max_per_hour": 5, "max_concurrent": 3},
}


class TradeTypeRateLimiter:
    """Per-trade-type rate limiting for risk management.

    Inspired by Claude Code's operation-level rate limiting.
    Different trade types (scalp, swing, trend) have different
    hourly limits and max concurrent positions.
    """

    def __init__(
        self, limits: Optional[Dict[str, Dict[str, int]]] = None
    ) -> None:
        self.limits = limits or TRADE_TYPE_LIMITS
        self._hourly_counts: Dict[str, List[float]] = defaultdict(list)

    def check(
        self,
        trade_type: str,
        current_open_trades: int = 0,
    ) -> tuple[bool, str]:
        """Check if a new trade of this type is allowed.

        Args:
            trade_type: Type of trade (scalp, swing, trend-follower, etc.)
            current_open_trades: Number of currently open trades for this type.

        Returns:
            (allowed, reason) tuple.
        """
        if trade_type not in self.limits:
            return True, "ok"

        config = self.limits[trade_type]
        now = time.time()
        one_hour_ago = now - 3600

        # Clean old entries
        self._hourly_counts[trade_type] = [
            t for t in self._hourly_counts[trade_type] if t > one_hour_ago
        ]

        # Check hourly limit
        hourly_count = len(self._hourly_counts[trade_type])
        max_per_hour = config.get("max_per_hour", 999)
        if hourly_count >= max_per_hour:
            return False, (
                f"Hourly limit reached for {trade_type}: "
                f"{hourly_count}/{max_per_hour}"
            )

        # Check concurrent limit
        max_concurrent = config.get("max_concurrent", 999)
        if current_open_trades >= max_concurrent:
            return False, (
                f"Concurrent limit reached for {trade_type}: "
                f"{current_open_trades}/{max_concurrent}"
            )

        return True, "ok"

    def record_trade(self, trade_type: str) -> None:
        """Record that a trade was opened."""
        self._hourly_counts[trade_type].append(time.time())

    def get_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get current rate limit stats per trade type."""
        now = time.time()
        one_hour_ago = now - 3600
        stats = {}
        for trade_type, config in self.limits.items():
            recent = [
                t for t in self._hourly_counts.get(trade_type, [])
                if t > one_hour_ago
            ]
            stats[trade_type] = {
                "trades_this_hour": len(recent),
                "max_per_hour": config.get("max_per_hour", 999),
                "max_concurrent": config.get("max_concurrent", 999),
            }
        return stats
