"""
Shared API utility for Freqtrade bot HTTP calls.

Provides retry logic with exponential backoff so scripts don't fail
silently when a bot is restarting or temporarily unavailable.

Also includes provider fallback pattern (inspired by Claude Code) and
deferred persistence for safe state writes.
"""

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar

import requests
from requests.auth import HTTPBasicAuth

API_USER = "freqtrader"
API_PASS = "mastertrader"
AUTH = HTTPBasicAuth(API_USER, API_PASS)

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

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, auth=AUTH, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            if attempt < retries:
                log.warning(
                    "Retry %d/%d for %s: %s (backoff %ds)",
                    attempt, retries, url, exc, backoff,
                )
                time.sleep(backoff)
                backoff *= 2
            else:
                log.error(
                    "Failed after %d attempts for %s: %s",
                    retries, url, exc,
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
