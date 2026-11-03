"""PIT news archive bounded fetch and shared Binance limiter (issue #229): network-free."""
import io
import json
import sys
import urllib.error
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
    a, b = BinanceLimiter(state), BinanceLimiter(state)
    assert a.try_acquire(0.0) is True
    assert b.try_acquire(10.0) is False
    assert a.try_acquire(179.0) is False
    assert b.try_acquire(181.0) is True
    assert json.loads(Path(state).read_text())["last_request"] == 181.0


def test_suspension_persists_across_instances(tmp_path):
    state = str(tmp_path / "binance_cms_state.json")
    BinanceLimiter(state).suspend(0.0)
    fresh = BinanceLimiter(state)
    assert fresh.suspended_until(3600.0) == 6 * 3600.0
    assert fresh.try_acquire(3600.0) is False
    assert fresh.try_acquire(6 * 3600 + 1.0) is True
    assert fresh.suspended_until(6 * 3600 + 2.0) is None


def test_corrupt_state_file_fails_closed(tmp_path):
    state = tmp_path / "binance_cms_state.json"
    state.write_text("{not json")
    lim = BinanceLimiter(str(state))
    assert lim.try_acquire(1000.0) is False      # unknown history: wait one full gap
    assert lim.try_acquire(1181.0) is True


def test_clock_moving_backwards_does_not_lock_out_for_long(tmp_path):
    lim = BinanceLimiter(str(tmp_path / "s.json"))
    assert lim.try_acquire(100_000.0) is True
    assert lim.try_acquire(50_000.0) is False    # wall clock jumped back
    assert lim.try_acquire(50_181.0) is True     # one gap from the jump, not 50,000 s
