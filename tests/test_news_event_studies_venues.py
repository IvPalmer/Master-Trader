"""Part C venue evidence (#229): Hyperliquid funding records and Binance file existence (O5-O7).

    python3 -m pytest tests/test_news_event_studies_venues.py -q
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research" / "news_event_studies"))

import nes_util  # noqa: E402,F401  (puts research/news_archive on sys.path)
import na_fetch  # noqa: E402
import nes_venues as nv  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "news_event_studies"
T0 = 1709294430000  # 2024-03-01T12:00:30Z
H, D = 3_600_000, 86_400_000


def resp(status, body=b"[]"):
    return na_fetch.Response(status, body if isinstance(body, bytes) else json.dumps(body).encode(), {})


class Clock:
    def __init__(self):
        self.now, self.sleeps = 1000.0, []

    def wall(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


class FakeHl:
    """Answers HL POSTs from a script keyed by (type, coin); records every request."""

    def __init__(self, script):
        self.script, self.requests = {k: list(v) for k, v in script.items()}, []

    def __call__(self, req):
        body = json.loads(req.body)
        self.requests.append((req, body))
        key = (body["type"], body.get("coin"))
        out = self.script[key].pop(0) if len(self.script[key]) > 1 else self.script[key][0]
        if isinstance(out, Exception):
            raise out
        return out


def client(script):
    clock = Clock()
    fake = FakeHl(script)
    return nv.HlClient(fake, clock.sleep, clock.wall), fake, clock


def funding(*times):
    return resp(200, [{"coin": "X", "fundingRate": "0", "premium": "0", "time": t} for t in times])


def index():
    return nv.hl_meta_index((FIX / "hl_meta.json").read_bytes())


def test_hl_status_rule():
    assert nv.hl_status([T0 - 1_800_000, T0 - 18_000_000], T0) == "eligible"
    assert nv.hl_status([T0 - 10_800_000], T0) == "ineligible"      # nothing in the last hour
    assert nv.hl_status([T0 + 60_000], T0) == "ineligible"          # after t0 is ignored
    assert nv.hl_status([], T0) == "ineligible"
    assert nv.hl_status(None, T0) == "unknown"


def test_hl_status_half_open_boundaries():
    assert nv.hl_status([T0 - H], T0) == "eligible"                  # t0-1h is in the last hour
    assert nv.hl_status([T0 - D, T0 - 1], T0) == "eligible"
    assert nv.hl_status([T0], T0) == "ineligible"                    # t0 itself is not before t0
    assert nv.hl_status([T0 - D - 1, T0], T0) == "ineligible"


def test_hl_request_never_reaches_t0():
    req = nv.hl_evidence_request("OLD", T0)
    body = json.loads(req.body)
    assert (req.method, req.url) == ("POST", "https://api.hyperliquid.xyz/info")
    assert body == {"type": "fundingHistory", "coin": "OLD", "startTime": T0 - D, "endTime": T0 - 1}
    assert req.headers["Content-Type"] == "application/json"


def test_hl_names_k_prefix_and_skips_hip3():
    idx = index()
    assert set(idx) == {"BTC", "KPEPE", "OLD"}
    assert idx["OLD"] == {"name": "OLD", "delisted": True}
    assert nv.hl_names("PEPE", idx) == ["kPEPE"]
    assert nv.hl_names("OLD", idx) == ["OLD"]
    assert nv.hl_names("ABC", idx) == []


def test_evidence_times_drop_prices():
    times = nv.hl_evidence_times((FIX / "hl_funding.json").read_bytes())
    assert times == [1709292630000, 1709276430000]
    assert all(type(t) is int for t in times)
    with pytest.raises(ValueError):
        nv.hl_evidence_times(b'{"error": "x"}')
    with pytest.raises(ValueError):
        nv.hl_evidence_times(b'[{"time": "1"}]')


def test_in_meta_name_is_evaluated():
    c, fake, _ = client({("fundingHistory", "OLD"): [funding(T0 - 1_800_000, T0 - 5 * H)]})
    assert nv.hl_facts("OLD", T0, index(), c) == {"status": "eligible", "coin": "OLD",
                                                  "reason": "funding_records"}
    c, _, _ = client({("fundingHistory", "OLD"): [funding(T0 - 5 * H)]})
    assert nv.hl_facts("OLD", T0, index(), c)["status"] == "ineligible"


def test_not_in_meta_queries_by_name_then_never_in_meta():
    c, fake, _ = client({("fundingHistory", "GONE"): [resp(500, b"null")]})
    assert nv.hl_facts("GONE", T0, index(), c) == {"status": "ineligible", "coin": "GONE",
                                                   "reason": "never_in_meta"}
    assert [b["coin"] for _, b in fake.requests] == ["GONE"]


def test_not_in_meta_with_records_is_evaluated():
    c, _, _ = client({("fundingHistory", "GONE"): [funding(T0 - 1_800_000)]})
    assert nv.hl_facts("GONE", T0, index(), c) == {"status": "eligible", "coin": "GONE",
                                                   "reason": "funding_records"}


def test_not_in_meta_other_failure_stops_the_build():
    c, _, _ = client({("fundingHistory", "GONE"): [resp(502, b"bad gateway")]})
    with pytest.raises(nv.VenueAborted):
        nv.hl_facts("GONE", T0, index(), c)


def test_500_null_for_a_name_in_meta_is_not_absence():
    c, _, _ = client({("fundingHistory", "OLD"): [resp(500, b"null")]})
    assert nv.hl_facts("OLD", T0, index(), c) == {"status": "unknown", "coin": "OLD",
                                                  "reason": "fetch_failed"}


def test_first_eligible_name_wins_else_unknown_beats_ineligible():
    idx = {"T": {"name": "T", "delisted": False}, "KT": {"name": "kT", "delisted": False}}
    c, _, _ = client({("fundingHistory", "T"): [funding(T0 - 5 * H)],
                      ("fundingHistory", "kT"): [funding(T0 - 60_000)]})
    assert nv.hl_facts("T", T0, idx, c)["coin"] == "kT"
    c, _, _ = client({("fundingHistory", "T"): [resp(503, b"")],
                      ("fundingHistory", "kT"): [funding(T0 - 5 * H)]})
    assert nv.hl_facts("T", T0, idx, c)["status"] == "unknown"


def test_hl_429_pauses_once_then_aborts():
    c, fake, clock = client({("fundingHistory", "OLD"): [resp(429, b""), funding(T0 - 60_000),
                                                         resp(429, b"")]})
    assert nv.hl_facts("OLD", T0, index(), c)["status"] == "eligible"
    assert nv.HL_429_PAUSE_S in clock.sleeps
    with pytest.raises(nv.VenueAborted):
        nv.hl_facts("OLD", T0, index(), c)


def test_hl_requests_are_paced():
    c, fake, clock = client({("fundingHistory", "OLD"): [funding(T0 - 60_000)]})
    nv.hl_facts("OLD", T0, index(), c)
    nv.hl_facts("OLD", T0, index(), c)
    assert clock.sleeps == [nv.HL_GAP_S]


def test_meta_failure_aborts():
    c, _, _ = client({("meta", None): [resp(503, b"")]})
    with pytest.raises(nv.VenueAborted):
        c.meta()


def test_binance_candidates_order_and_kline_url():
    assert nv.binance_candidates("PEPE", T0) == [
        ("um", "PEPEUSDT"), ("um", "1000PEPEUSDT"), ("um", "1000000PEPEUSDT"), ("um", "1MPEPEUSDT"),
        ("spot", "PEPEUSDT"), ("spot", "1000PEPEUSDT"), ("spot", "1MPEPEUSDT")]
    assert nv.kline_url("um", "ABCUSDT", "2024-03-01") == \
        "https://data.binance.vision/data/futures/um/daily/klines/ABCUSDT/1m/ABCUSDT-1m-2024-03-01.zip"
    assert nv.kline_url("spot", "ABCUSDT", "2024-03-01") == \
        "https://data.binance.vision/data/spot/daily/klines/ABCUSDT/1m/ABCUSDT-1m-2024-03-01.zip"


class FakeFiles:
    def __init__(self, present, script=None):
        self.present, self.script, self.requests = set(present), dict(script or {}), []

    def __call__(self, req):
        self.requests.append(req)
        if req.url in self.script:
            out = self.script[req.url].pop(0)
            if isinstance(out, Exception):
                raise out
            return out
        return resp(200 if req.url in self.present else 404, b"")


def url(market, sym, date):
    return nv.kline_url(market, sym, date)


def test_file_probe_sends_head_only_and_caches():
    fake, clock = FakeFiles({url("um", "AUSDT", "2024-03-01")}), Clock()
    probe = nv.FileProbe(fake, clock.sleep)
    assert probe.exists(url("um", "AUSDT", "2024-03-01")) is True
    assert probe.exists(url("um", "AUSDT", "2024-03-01")) is True
    assert probe.exists(url("um", "AUSDT", "2024-03-02")) is False
    assert [r.method for r in fake.requests] == ["HEAD", "HEAD"]
    assert all(r.body is None for r in fake.requests)
    assert clock.sleeps.count(nv.PROBE_GAP_S) == 2


def test_transient_error_is_not_absence():
    u = url("um", "AUSDT", "2024-03-01")
    fake = FakeFiles(set(), {u: [resp(503, b""), na_fetch.FetchError("timeout"), resp(503, b"")]})
    probe = nv.FileProbe(fake, Clock().sleep)
    with pytest.raises(nv.ProbeError):
        probe.exists(u)
    fake = FakeFiles(set(), {u: [resp(503, b""), resp(403, b"")]})
    assert nv.FileProbe(fake, Clock().sleep).exists(u) is False


DATES = ("2024-02-29", "2024-03-01", "2024-03-02", "2024-03-03")


def test_binance_facts_prefers_um_then_spot_and_needs_every_date():
    present = {url("um", "AUSDT", d) for d in DATES[:3]} | {url("spot", "AUSDT", d) for d in DATES}
    facts = nv.binance_facts("A", T0, nv.FileProbe(FakeFiles(present), Clock().sleep))
    assert facts == {"on_binance_pre_t0": True, "spot_symbol_pre_t0": "AUSDT",
                     "proxy": {"market": "spot", "symbol": "AUSDT", "tier": "full"}}
    present = {url("um", "AUSDT", d) for d in DATES} | {url("spot", "AUSDT", d) for d in DATES}
    facts = nv.binance_facts("A", T0, nv.FileProbe(FakeFiles(present), Clock().sleep))
    assert facts["proxy"] == {"market": "um", "symbol": "AUSDT", "tier": "full"}


def test_binance_facts_falls_back_to_entry_tier_then_none():
    present = {url("um", "1000AUSDT", d) for d in DATES[:2]} | {url("spot", "AUSDT", DATES[0])}
    facts = nv.binance_facts("A", T0, nv.FileProbe(FakeFiles(present), Clock().sleep))
    assert facts["proxy"] == {"market": "um", "symbol": "1000AUSDT", "tier": "entry"}
    present = {url("spot", "AUSDT", DATES[0])}
    facts = nv.binance_facts("A", T0, nv.FileProbe(FakeFiles(present), Clock().sleep))
    assert facts == {"on_binance_pre_t0": True, "spot_symbol_pre_t0": "AUSDT", "proxy": None}


def test_on_binance_pre_t0_uses_previous_utc_date():
    present = {url("um", "AUSDT", d) for d in DATES[1:]} | {url("spot", "AUSDT", d) for d in DATES[1:]}
    facts = nv.binance_facts("A", T0, nv.FileProbe(FakeFiles(present), Clock().sleep))
    assert facts == {"on_binance_pre_t0": False, "spot_symbol_pre_t0": None, "proxy": None}


def test_hl_evidence_constant_matches_prereg():
    reg = json.loads((ROOT / "ft_userdata" / "preregistrations.json").read_text(encoding="utf-8"))
    ids = ("binance-delisting-reaction-2026-11", "upbit-krw-listing-reaction-2026-11",
           "upbit-krw-listing-fade-2026-11")
    frozen = [e["frozen"] for e in reg["preregistrations"] if e.get("id") in ids]
    assert len(frozen) == 3
    assert {f["hl_evidence"] for f in frozen} == {nv.HL_EVIDENCE}
    assert {tuple(f["hl_eligibility_window_s"]) for f in frozen} == {(nv.HL_LOOKBACK_MS // 1000,
                                                                       nv.HL_LAST_MS // 1000)}
