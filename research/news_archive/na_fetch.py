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
        # read1: one socket read per call, so the deadline is checked at least once per
        # socket timeout (HTTPResponse.read(n) loops until n bytes arrive)
        b = getattr(fp, "read1", fp.read)(min(CHUNK, max_bytes + 1 - n))
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


STATE_KEYS = ("last_request", "suspended_until", "boot_id", "last_request_mono",
              "suspended_until_mono")


def _boot_id():
    try:
        with open("/proc/sys/kernel/random/boot_id") as f:
            return f.read().strip() or None
    except OSError:
        return None


class BinanceLimiter:
    """State lives in `state_path`, replaced atomically (tmp + rename) under an flock on
    `state_path + ".lock"`, so a reader never sees a half-written file. A state file that
    exists but cannot be parsed fails closed: a fresh 6 h suspension.

    Deadlines are kept in wall time and, within one boot, also in monotonic time, so a
    forward wall-clock step cannot shorten the 180 s gap or a suspension. Across a
    reboot (a different boot_id) only the wall-time rules apply."""

    def __init__(self, state_path, gap_s=180.0, mono=time.monotonic, boot_id="auto"):
        self.path = state_path
        self.gap_s = float(gap_s)
        self.mono = mono
        self.boot_id = _boot_id() if boot_id == "auto" else boot_id

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
            for k in ("last_request", "suspended_until", "last_request_mono",
                      "suspended_until_mono"):
                v = state.get(k)
                if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
                    raise ValueError("bad %s" % k)
            return {k: state.get(k) for k in STATE_KEYS}, False
        except ValueError:
            return {"last_request": now, "suspended_until": now + SUSPEND_HOURS * 3600.0,
                    **self._mono_fields(None, SUSPEND_HOURS * 3600.0)}, True

    def _mono_fields(self, gap_mono, suspend_s):
        """Monotonic stamps for this boot (None when the boot is unknown)."""
        if self.boot_id is None:
            return {"boot_id": None, "last_request_mono": None, "suspended_until_mono": None}
        m = self.mono()
        return {"boot_id": self.boot_id, "last_request_mono": m if gap_mono else None,
                "suspended_until_mono": m + suspend_s if suspend_s else None}

    def _same_boot(self, s):
        return self.boot_id is not None and s.get("boot_id") == self.boot_id

    def _mono_suspended(self, s):
        until = s.get("suspended_until_mono")
        return self._same_boot(s) and until is not None and self.mono() < until

    def _mono_too_soon(self, s):
        last = s.get("last_request_mono")
        if not self._same_boot(s) or last is None:
            return False
        elapsed = self.mono() - last
        return 0 <= elapsed < self.gap_s   # negative: inconsistent stamp, wall rules apply

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
            if (until is not None and now < until) or self._mono_suspended(s):
                return False, None
            last = s["last_request"]
            if last is not None:
                if now < last:                       # wall clock moved backwards
                    return False, {**s, "last_request": now}
                if now - last < self.gap_s:
                    return False, None
            if self._mono_too_soon(s):
                return False, None
            keep = s.get("suspended_until_mono") if self._same_boot(s) else None
            return True, {**s, "last_request": now, **self._mono_fields(True, 0),
                          "suspended_until_mono": keep}
        return self._update(now, fn)

    def suspend(self, now, hours=SUSPEND_HOURS):
        def fn(s):
            until = now + hours * 3600.0
            if s["suspended_until"] is not None:
                until = max(until, s["suspended_until"])
            stamps = self._mono_fields(False, hours * 3600.0)
            if self._same_boot(s):
                stamps["last_request_mono"] = s.get("last_request_mono")
                if s.get("suspended_until_mono") is not None and stamps["suspended_until_mono"]:
                    stamps["suspended_until_mono"] = max(stamps["suspended_until_mono"],
                                                         s["suspended_until_mono"])
            return None, {**s, "suspended_until": until, **stamps}
        self._update(now, fn)

    def suspended_until(self, now):
        def fn(s):
            until = s["suspended_until"]
            wall = until if until is not None and until > now else None
            if self._mono_suspended(s):
                mono_until = now + (s["suspended_until_mono"] - self.mono())
                wall = max(wall or mono_until, mono_until)
            return wall, None
        return self._update(now, fn)
