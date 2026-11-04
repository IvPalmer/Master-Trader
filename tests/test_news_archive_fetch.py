"""PIT news archive bounded fetch and shared Binance limiter (issue #229): network-free."""
import io
import json
import sys
import urllib.error
import urllib.request
import urllib.response
from email.message import Message
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "news_archive"))

import na_fetch  # noqa: E402
from na_fetch import BinanceLimiter, FetchError, Response, fetch, is_block_signal  # noqa: E402
from na_sources import SOURCES  # noqa: E402


class FakeResp(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = Message()
        for k, v in (headers or {}).items():
            self.headers[k] = v


def opener_returning(body, status=200, headers=None, seen=None):
    def opener(req, timeout):
        if seen is not None:
            seen.append((req, timeout))
        return FakeResp(body, status, headers)
    return opener


def test_oversize_body_raises():
    with pytest.raises(FetchError):
        fetch(SOURCES["tree"], opener=opener_returning(b"x" * 5_000_001))
    resp = fetch(SOURCES["tree"], opener=opener_returning(b"x" * 5_000_000))
    assert len(resp.body) == 5_000_000


def test_request_carries_spec_method_body_headers_and_timeout():
    seen = []
    fetch(SOURCES["hyperliquid_universe"], opener=opener_returning(b"{}", seen=seen))
    req, timeout = seen[0]
    assert req.get_method() == "POST" and req.data == b'{"type":"meta"}'
    assert req.get_header("Content-type") == "application/json"
    assert timeout == 10


def test_http_error_comes_back_as_response_with_headers():
    hdrs = Message()
    hdrs["Retry-After"] = "120"

    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", hdrs, io.BytesIO(b"slow down"))
    resp = fetch(SOURCES["upbit"], opener=opener)
    assert resp.status == 429 and resp.body == b"slow down"
    assert resp.headers["Retry-After"] == "120"


def test_transport_failure_raises_fetch_error():
    def opener(req, timeout):
        raise urllib.error.URLError("connection refused")
    with pytest.raises(FetchError):
        fetch(SOURCES["tree"], opener=opener)

    def timeout_opener(req, timeout):
        raise TimeoutError("timed out")
    with pytest.raises(FetchError):
        fetch(SOURCES["tree"], opener=timeout_opener)


def test_html_body_is_block_signal():
    assert is_block_signal(Response(200, b"<html>captcha</html>", {})) is True
    assert is_block_signal(Response(200, b"", {})) is True
    for status in (403, 418, 429):
        assert is_block_signal(Response(status, b'{"code":"0"}', {})) is True
    assert is_block_signal(Response(200, json.dumps({"success": False}).encode(), {})) is False
    assert is_block_signal(Response(200, b'{"success":true,"data":{}}', {})) is False


def test_limiter_one_request_per_180s_across_instances(tmp_path):
    state = str(tmp_path / "data" / "binance_cms_state.json")
    a, b = BinanceLimiter(state, boot_id=None), BinanceLimiter(state, boot_id=None)
    assert a.try_acquire(0.0) is True
    assert b.try_acquire(10.0) is False
    assert a.try_acquire(179.0) is False
    assert b.try_acquire(181.0) is True
    assert json.loads(Path(state).read_text())["last_request"] == 181.0


def test_suspension_persists_across_instances(tmp_path):
    state = str(tmp_path / "binance_cms_state.json")
    BinanceLimiter(state, boot_id=None).suspend(0.0)
    fresh = BinanceLimiter(state, boot_id=None)
    assert fresh.suspended_until(3600.0) == 6 * 3600.0
    assert fresh.try_acquire(3600.0) is False
    assert fresh.try_acquire(6 * 3600 + 1.0) is True
    assert fresh.suspended_until(6 * 3600 + 2.0) is None


def test_corrupt_or_empty_state_file_fails_closed_for_6h(tmp_path):
    for text in ("{not json", ""):
        state = tmp_path / ("s%d.json" % len(text))
        state.write_text(text)
        lim = BinanceLimiter(str(state), boot_id=None)
        assert lim.try_acquire(1000.0) is False   # unknown history: assume suspended
        assert lim.suspended_until(1000.0) == 1000.0 + 6 * 3600
        assert lim.try_acquire(1000.0 + 6 * 3600 + 1) is True


def test_state_is_replaced_atomically_under_a_separate_lock(tmp_path):
    state = tmp_path / "binance_cms_state.json"
    lim = BinanceLimiter(str(state), boot_id=None)
    ino = None
    for t in (0.0, 200.0):
        assert lim.try_acquire(t) is True
        json.loads(state.read_text())             # always a complete document
        assert ino != state.stat().st_ino         # written by rename, not in place
        ino = state.stat().st_ino
    assert (tmp_path / "binance_cms_state.json.lock").exists()


class FakeHTTPS(urllib.request.HTTPSHandler):
    def __init__(self, responses):
        super().__init__()
        self.responses, self.opened = list(responses), []

    def https_open(self, req):
        self.opened.append(req.full_url)
        status, headers, body = self.responses.pop(0)
        msg = Message()
        for k, v in headers.items():
            msg[k] = v
        r = urllib.response.addinfourl(io.BytesIO(body), msg, req.full_url, status)
        r.msg = "fake"   # HTTPErrorProcessor reads response.msg
        return r


def test_redirects_are_not_followed():
    fake = FakeHTTPS([(302, {"Location": "https://www.binance.com/elsewhere"}, b"moved"),
                      (200, {}, b"{}")])
    resp = fetch(SOURCES["binance_listing"], opener=na_fetch.make_opener(fake).open)
    assert resp.status == 302 and len(fake.opened) == 1
    assert is_block_signal(resp) is True


def test_oversized_error_body_keeps_its_status():
    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", Message(),
                                     io.BytesIO(b"x" * 5_000_001))
    with pytest.raises(FetchError) as e:
        fetch(SOURCES["binance_listing"], opener=opener)
    assert e.value.status == 403


def test_body_read_stops_at_the_deadline():
    clock = iter([0.0, 5.0, 25.0, 30.0, 35.0])
    with pytest.raises(FetchError, match="deadline"):
        fetch(SOURCES["tree"], opener=opener_returning(b"x" * 300_000), deadline=20.0,
              mono=lambda: next(clock))
    resp = fetch(SOURCES["tree"], opener=opener_returning(b"{}"), deadline=20.0,
                 mono=lambda: 1.0)
    assert resp.body == b"{}"


def test_clock_moving_backwards_does_not_lock_out_for_long(tmp_path):
    lim = BinanceLimiter(str(tmp_path / "s.json"), boot_id=None)
    assert lim.try_acquire(100_000.0) is True
    assert lim.try_acquire(50_000.0) is False    # wall clock jumped back
    assert lim.try_acquire(50_181.0) is True     # one gap from the jump, not 50,000 s


def test_forward_wall_step_cannot_end_a_suspension_or_gap_within_one_boot(tmp_path):
    clock = {"m": 1000.0}
    state = str(tmp_path / "s.json")
    mk = lambda: BinanceLimiter(state, mono=lambda: clock["m"], boot_id="boot-1")  # noqa: E731
    assert mk().try_acquire(0.0) is True
    clock["m"] += 1
    assert mk().try_acquire(500.0) is False          # wall stepped +499 s, 1 s really passed
    mk().suspend(500.0)
    clock["m"] += 200
    assert mk().try_acquire(500.0 + 7 * 3600) is False   # +7 h wall step, 200 s really passed
    assert mk().suspended_until(500.0 + 7 * 3600) is not None
    clock["m"] += 6 * 3600
    assert mk().try_acquire(500.0 + 14 * 3600) is True
    # another boot: monotonic values are not comparable, wall rules alone apply
    other = BinanceLimiter(state, mono=lambda: 5.0, boot_id="boot-2")
    assert other.try_acquire(500.0 + 14 * 3600 + 181) is True


class DripResp(FakeResp):
    """Like http.client: read(n) loops until n bytes, read1(n) does one socket read."""
    def __init__(self, clock):
        super().__init__(b"x" * 1000)
        self.clock = clock

    def read(self, n=-1):
        self.clock["t"] += 1000.0                    # read(n) would gather 1000 one-byte reads
        return super().read(n)

    def read1(self, n=-1):
        self.clock["t"] += 1.0
        return super().read(1)


def test_body_reads_use_single_socket_reads():
    clock = {"t": 0.0}
    with pytest.raises(FetchError, match="deadline"):
        fetch(SOURCES["tree"], opener=lambda req, timeout: DripResp(clock), deadline=20.0,
              mono=lambda: clock["t"])
    assert clock["t"] <= 22.0
