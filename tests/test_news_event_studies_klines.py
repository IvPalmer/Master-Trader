"""Part C Phase 2 kline layer (#229): data.binance.vision daily 1m files.

    python3 -m pytest tests/test_news_event_studies_klines.py -q
"""
import io
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research" / "news_event_studies"))

import nes_util as nu  # noqa: E402,F401
import na_fetch  # noqa: E402
import nes_klines as nk  # noqa: E402
import nes_venues as nv  # noqa: E402

T0 = 1709294430000          # 2024-03-01T12:00:30Z
MIN = 60_000


def row(open_ms, close="100", high=None, low=None):
    high, low = high or close, low or close
    return "%d,%s,%s,%s,%s,1,%d,1,1,1,1,0" % (open_ms, close, high, low, close, open_ms + MIN - 1)


def zbytes(name, lines, header=False):
    buf = io.BytesIO()
    text = ("open_time,open,high,low,close,volume,close_time,quote_volume,count,"
            "taker_buy_volume,taker_buy_quote_volume,ignore\n" if header else "") + "\n".join(lines) + "\n"
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    return buf.getvalue()


class Files:
    def __init__(self, by_date=None, status=None):
        self.by_date, self.status, self.requests = by_date or {}, status or {}, []

    def __call__(self, req):
        self.requests.append(req)
        date = req.url[-14:-4]
        if date in self.status:
            return na_fetch.Response(self.status[date], b"", {})
        if date in self.by_date:
            return na_fetch.Response(200, self.by_date[date], {})
        return na_fetch.Response(404, b"", {})


def test_ms_and_us_open_times_normalize():
    rows = nk.parse_kline_csv("1704067200000,1,2,0.5,1.5,9,1704067259999,1,1,1,1,0\n"
                              "1735689600000000,3,4,2,3.5,9,1735689659999999,1,1,1,1,0\n")
    assert rows == {1704067200000: ["1", "2", "0.5", "1.5"], 1735689600000: ["3", "4", "2", "3.5"]}


def test_header_row_skipped():
    text = "open_time,open,high,low,close,volume\n1704067200000,1,2,0.5,1.5,9\n"
    assert list(nk.parse_kline_csv(text)) == [1704067200000]


def test_download_dates_and_span():
    assert nk.download_dates(T0) == ["2024-02-29", "2024-03-01", "2024-03-02", "2024-03-03",
                                     "2024-03-04", "2024-03-05", "2024-03-06"]
    assert nk.span(T0) == (T0 - 15 * MIN, T0 + 5 * MIN + 24 * 60 * MIN + 72 * 60 * MIN + MIN)


def test_kline_url_matches_venues():
    assert nk.kline_url is nv.kline_url


def test_rows_limited_to_span_and_zip_deleted(tmp_path):
    lo, hi = nk.span(T0)
    first = T0 - T0 % MIN
    day1 = [row(first - 20 * MIN), row(first - 15 * MIN + 30_000 - 30_000), row(first), row(first + MIN)]
    files = Files({"2024-03-01": zbytes("AUSDT-1m-2024-03-01.csv", day1, header=True)})
    s = nk.fetch_series("um", "AUSDT", T0, files, tmp_path, lambda: True, sleep=lambda s: None)
    assert all(lo <= k < hi for k in s["rows"])
    assert first in s["rows"] and first + MIN in s["rows"] and first - 20 * MIN not in s["rows"]
    assert s["absent_dates"] == ["2024-02-29", "2024-03-02", "2024-03-03", "2024-03-04",
                                 "2024-03-05", "2024-03-06"]
    assert list(tmp_path.iterdir()) == []
    assert [r.url for r in files.requests] == [nv.kline_url("um", "AUSDT", d) for d in nk.download_dates(T0)]
    assert all(r.method == "GET" for r in files.requests)


def test_404_day_is_absent_not_error(tmp_path):
    s = nk.fetch_series("spot", "AUSDT", T0, Files(), tmp_path, lambda: True, sleep=lambda s: None)
    assert s == {"rows": {}, "absent_dates": nk.download_dates(T0)}


def test_403_is_not_absence(tmp_path):
    files = Files(status={"2024-03-01": 403})
    with pytest.raises(nk.KlineError):
        nk.fetch_series("um", "AUSDT", T0, files, tmp_path, lambda: True, sleep=lambda s: None)


def test_disk_guard_raises_before_any_download(tmp_path):
    files = Files()
    with pytest.raises(nk.DiskGuard):
        nk.fetch_series("um", "AUSDT", T0, files, tmp_path, lambda: False, sleep=lambda s: None)
    assert files.requests == []


def test_server_error_retries_then_raises(tmp_path):
    files = Files(status={"2024-02-29": 500})
    with pytest.raises(nk.KlineError):
        nk.fetch_series("um", "AUSDT", T0, files, tmp_path, lambda: True, sleep=lambda s: None)
    assert len(files.requests) == 3


def test_corrupt_zip_raises(tmp_path):
    files = Files({"2024-02-29": b"not a zip"})
    with pytest.raises(nk.KlineError):
        nk.fetch_series("um", "AUSDT", T0, files, tmp_path, lambda: True, sleep=lambda s: None)


def test_store_and_load_round_trip(tmp_path):
    series = {"rows": {T0 - T0 % MIN: ["1", "2", "0.5", "1.5"]}, "absent_dates": ["2024-03-02"]}
    nk.store_series(tmp_path / "s.json", series)
    assert nk.load_series(tmp_path / "s.json") == series
    assert (tmp_path / "s.json").read_bytes() == nu.canonical_bytes(
        {"rows": {str(k): v for k, v in series["rows"].items()}, "absent_dates": ["2024-03-02"]})
