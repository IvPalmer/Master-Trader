"""Bounded HTTP and the shared Binance CMS limiter for the PIT news archive (#229).

fetch() is the only function in the archive that touches the network: one attempt,
no retry, no redirects (a 3xx comes back as a Response; urllib would otherwise issue the
follow-up request outside the Binance limiter and drain its body unbounded), a 10 s
socket timeout, a 5 MB read cap and an optional absolute deadline checked while the body
is read. HTTP error statuses come back as a Response so the caller can read Retry-After;
transport failures, oversize bodies and a passed deadline raise FetchError, which keeps
the HTTP status when one was received.

BinanceLimiter enforces spec §4.2's budget for every new Binance CMS caller (the service,
`once`, the Part C harvester): at most one request every 180 s and a 6 h suspension on a
block signal, both persisted in one JSON state file under an exclusive flock.
"""
import fcntl
import http.client
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

BLOCK_STATUSES = {403, 418, 429}
CHUNK = 65536
SUSPEND_HOURS = 6


class FetchError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None   # urllib then raises HTTPError(3xx), which fetch() returns as a Response


def make_opener(*handlers):
    return urllib.request.build_opener(_NoRedirect, *handlers)


_OPENER = make_opener()


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict


def _headers(msg):
    return {k: v for k, v in msg.items()} if msg is not None else {}


def _read(fp, status, max_bytes, deadline, mono):
    chunks, n = [], 0
    while n <= max_bytes:
        if deadline is not None and mono() > deadline:
            raise FetchError("poll deadline exceeded while reading the body", status)
        b = fp.read(min(CHUNK, max_bytes + 1 - n))
        if not b:
            break
        chunks.append(b)
        n += len(b)
    if n > max_bytes:
        raise FetchError("response larger than %d bytes" % max_bytes, status)
    return b"".join(chunks)


def fetch(spec, timeout_s=10, max_bytes=5_000_000, opener=None, deadline=None,
          mono=time.monotonic):
    req = urllib.request.Request(spec.url, data=spec.body, headers=dict(spec.headers),
                                 method=spec.method)
    opener = opener or _OPENER.open
    status = None
    try:
        try:
            with opener(req, timeout=timeout_s) as resp:
                status = int(getattr(resp, "status", None) or resp.getcode())
                headers = _headers(resp.headers)
                body = _read(resp, status, max_bytes, deadline, mono)
        except urllib.error.HTTPError as e:
            status, headers = int(e.code), _headers(e.headers)
            try:
                body = _read(e, status, max_bytes, deadline, mono)
            except (OSError, http.client.HTTPException, ValueError, AttributeError):
                body = b""
    except FetchError:
        raise
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
        raise FetchError("%s: %s" % (type(e).__name__, e), status) from e
    return Response(status, body, headers)


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
    """State lives in `state_path`, replaced atomically (tmp + rename) under an flock on
    `state_path + ".lock"`, so a reader never sees a half-written file. A state file that
    exists but cannot be parsed fails closed: a fresh 6 h suspension."""

    def __init__(self, state_path, gap_s=180.0):
        self.path = state_path
        self.gap_s = float(gap_s)

    def _load(self, now):
        try:
            with open(self.path) as f:
                text = f.read()
        except FileNotFoundError:
            return {"last_request": None, "suspended_until": None}, False
        try:
            state = json.loads(text)
            if not isinstance(state, dict):
                raise ValueError("state is not an object")
            for k in ("last_request", "suspended_until"):
                v = state.get(k)
                if v is not None and not isinstance(v, (int, float)):
                    raise ValueError("bad %s" % k)
            return {"last_request": state.get("last_request"),
                    "suspended_until": state.get("suspended_until")}, False
        except ValueError:
            return {"last_request": now,
                    "suspended_until": now + SUSPEND_HOURS * 3600.0}, True

    def _write(self, state):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            f.write(json.dumps(state))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def _update(self, now, fn):
        """Run fn(state) -> (result, new_state | None) under an exclusive flock."""
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(self.path + ".lock", "a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state, dirty = self._load(now)
            result, new_state = fn(state)
            if new_state is not None or dirty:
                self._write(new_state if new_state is not None else state)
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

    def suspend(self, now, hours=SUSPEND_HOURS):
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
