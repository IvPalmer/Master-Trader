"""Bounded HTTP and the shared Binance CMS limiter for the PIT news archive (#229).

fetch() is the only function in the archive that touches the network: one attempt,
no retry, a 10 s socket timeout and a 5 MB read cap. HTTP error statuses come back as a
Response so the caller can read Retry-After; transport failures raise FetchError.

BinanceLimiter enforces spec §4.2's budget for every new Binance CMS caller (the service,
`once`, the Part C harvester): at most one request every 180 s and a 6 h suspension on a
block signal, both persisted in one JSON state file under an exclusive flock.
"""
import fcntl
import http.client
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

BLOCK_STATUSES = {403, 418, 429}


class FetchError(Exception):
    pass


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict


def _headers(msg):
    return {k: v for k, v in msg.items()} if msg is not None else {}


def fetch(spec, timeout_s=10, max_bytes=5_000_000, opener=urllib.request.urlopen):
    req = urllib.request.Request(spec.url, data=spec.body, headers=dict(spec.headers),
                                 method=spec.method)
    try:
        try:
            with opener(req, timeout=timeout_s) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                headers = _headers(resp.headers)
                body = resp.read(max_bytes + 1)
        except urllib.error.HTTPError as e:
            status, headers = e.code, _headers(e.headers)
            try:
                body = e.read(max_bytes + 1) or b""
            except (OSError, http.client.HTTPException, ValueError):
                body = b""
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
        raise FetchError("%s: %s" % (type(e).__name__, e)) from e
    if len(body) > max_bytes:
        raise FetchError("response larger than %d bytes" % max_bytes)
    return Response(int(status), body, headers)


def is_block_signal(resp):
    """Binance block: HTTP 403/418/429, or a body that is not JSON (HTML, captcha, empty)."""
    if resp.status in BLOCK_STATUSES:
        return True
    try:
        json.loads(resp.body)
    except ValueError:
        return True
    return False


class BinanceLimiter:
    def __init__(self, state_path, gap_s=180.0):
        self.path = state_path
        self.gap_s = float(gap_s)

    def _update(self, now, fn):
        """Run fn(state) -> (result, new_state | None) under an exclusive flock."""
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        with os.fdopen(fd, "r+") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            text = f.read()
            dirty = False
            try:
                state = json.loads(text) if text.strip() else {}
                if not isinstance(state, dict):
                    raise ValueError("state is not an object")
            except ValueError:
                # Unknown history: fail closed by treating now as the last request.
                state, dirty = {"last_request": now, "suspended_until": None}, True
            state.setdefault("last_request", None)
            state.setdefault("suspended_until", None)
            result, new_state = fn(state)
            if new_state is not None or dirty:
                f.seek(0)
                f.truncate()
                f.write(json.dumps(new_state if new_state is not None else state))
                f.flush()
                os.fsync(f.fileno())
            return result

    def try_acquire(self, now):
        def fn(s):
            until = s["suspended_until"]
            if until is not None and now < until:
                return False, None
            last = s["last_request"]
            if last is not None:
                if now < last:                       # wall clock moved backwards
                    return False, {**s, "last_request": now}
                if now - last < self.gap_s:
                    return False, None
            return True, {**s, "last_request": now}
        return self._update(now, fn)

    def suspend(self, now, hours=6):
        def fn(s):
            until = now + hours * 3600.0
            if s["suspended_until"] is not None:
                until = max(until, s["suspended_until"])
            return None, {**s, "suspended_until": until}
        self._update(now, fn)

    def suspended_until(self, now):
        def fn(s):
            until = s["suspended_until"]
            return (until if until is not None and until > now else None), None
        return self._update(now, fn)
