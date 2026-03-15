"""
Shared API utility for Freqtrade bot HTTP calls.

Provides retry logic with exponential backoff so scripts don't fail
silently when a bot is restarting or temporarily unavailable.
"""

import logging
import time
from typing import Any, Optional

import requests
from requests.auth import HTTPBasicAuth

API_USER = "freqtrader"
API_PASS = "mastertrader"
AUTH = HTTPBasicAuth(API_USER, API_PASS)

log = logging.getLogger("api-utils")


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
