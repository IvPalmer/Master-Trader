"""Part C Phase 2 CLI, reports and resolution (#229).

    python3 -m pytest tests/test_news_event_studies_report.py -q
"""
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research" / "news_event_studies"))

import nes_util as nu  # noqa: E402
import na_fetch  # noqa: E402
import nes_manifest as nm  # noqa: E402
import nes_report as rp  # noqa: E402
import nes_venues as nv  # noqa: E402

DEL, LONG, FADE = nm.STUDIES
MIN, H, D = 60_000, 3_600_000, 86_400_000
T1 = 1709294430000                 # 2024-03-01T12:00:30Z
T2 = T1 + 3 * D
LATER = lambda: 1893456000.0       # noqa: E731  2030-01-01, long after every file is published


def _floor(ms):
    return ms - ms % MIN


class Market:
    """Serves daily zips: every minute closes "100" unless overridden per (symbol, open ms)."""

    def __init__(self, overrides=None, missing=()):
        self.overrides, self.missing, self.urls = overrides or {}, set(missing), []

    def __call__(self, req):
        self.urls.append(req.url)
        parts = req.url.split("/")
        symbol, date = parts[-3], req.url[-14:-4]
        if (symbol, date) in self.missing:
            return na_fetch.Response(404, b"", {})
        start = nu.ms_from_iso(date + "T00:00:00+00:00")
        lines = []
        for k in range(1440):
            o = start + k * MIN
            c = self.overrides.get((symbol, o), "100")
            lines.append("%d,%s,%s,%s,%s,1,%d,1,1,1,1,0" % (o, c, c, c, c, o + MIN - 1))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("%s-1m-%s.csv" % (symbol, date), "\n".join(lines) + "\n")
        return na_fetch.Response(200, buf.getvalue(), {})


def ev(aid, t0, token, kind="full_delist", hl="eligible", spot=None, proxy_symbol=None):
    return {"announcement_id": aid, "t0_ms": t0, "t0": nu.iso_ms(t0), "title": "t", "kind": kind,
            "token": token, "exclusion": None, "exclusion_ref": None,
            "trading_start_ms": t0 + H if kind == "krw_addition" else None,
            "hl": {"status": hl, "coin": token, "reason": "x"},
            "binance": {"on_binance_pre_t0": True, "spot_symbol_pre_t0": spot,
                        "proxy": {"market": "um", "symbol": proxy_symbol or token + "USDT", "tier": "full"}}}


def manifest(studies, events):
    return {"manifest_version": 1, "studies": studies, "window_utc": nm.WINDOW_UTC,
            "code_commit": "p1commit", "hl_evidence": "fundingHistory", "inputs": {},
            "harvest_complete": True, "harvest_shortfall": 0, "events": events}


def write(tmp_path, m, name="m.json"):
    body = nu.canonical_bytes(m)
    p = tmp_path / name
    p.write_bytes(body)
    return p, nu.sha256_bytes(body)


def exit4h(t0):
    return _floor(t0 + 300_000 + 4 * H)


def run(tmp_path, m, market, **kw):
    p, sha = write(tmp_path, m)
    return rp.compute(p, sha, tmp_path / "out", market, tmp_path / "work", lambda: True,
                      code_commit="p2commit", wall=LATER, sleep=lambda s: None, **kw)


def test_compute_refuses_sha_mismatch(tmp_path):
    p, _ = write(tmp_path, manifest([DEL], [ev("binance:1", T1, "AAA")]))
    market = Market()
    with pytest.raises(ValueError):
        rp.compute(p, "0" * 64, tmp_path / "out", market, tmp_path / "work", lambda: True,
                   code_commit="x", wall=LATER)
    assert market.urls == [] and not (tmp_path / "out").exists()
    rc = rp.main(["compute", "--manifest", str(p), "--expect-sha256", "0" * 64,
                  "--out", str(tmp_path / "out"), "--code-commit", "x"], fetcher=market)
    assert rc == 2 and market.urls == []


def test_compute_refuses_before_files_are_published(tmp_path):
    t_late = nu.ms_from_iso("2026-10-31T20:00:00+00:00")
    p, sha = write(tmp_path, manifest([DEL], [ev("binance:1", t_late, "AAA")]))
    market = Market()
    early = lambda: nu.ms_from_iso("2026-11-06T12:00:00+00:00") / 1000   # noqa: E731
    with pytest.raises(rp.TooEarly):
        rp.compute(p, sha, tmp_path / "out", market, tmp_path / "work", lambda: True,
                   code_commit="x", wall=early)
    assert market.urls == []
    ok = lambda: nu.ms_from_iso("2026-11-07T00:00:00+00:00") / 1000   # noqa: E731
    with pytest.raises(rp.TooEarly):          # BTC file for the last needed day not published
        rp.compute(p, sha, tmp_path / "out", Market(missing={("BTCUSDT", "2026-11-05")}),
                   tmp_path / "work", lambda: True, code_commit="x", wall=ok, sleep=lambda s: None)
    rp.compute(p, sha, tmp_path / "out", market, tmp_path / "work", lambda: True,
               code_commit="x", wall=ok, sleep=lambda s: None)


def test_compute_end_to_end_fixture(tmp_path):
    m = manifest([DEL], [ev("binance:1", T1, "AAA"), ev("binance:1", T1, "BBB"),
                         ev("binance:2", T2, "CCC"),
                         {**ev("binance:3", T2, "DDD"), "hl": {"status": "ineligible", "coin": "DDD",
                                                               "reason": "x"}}])
    market = Market({("AAAUSDT", exit4h(T1)): "98", ("BBBUSDT", exit4h(T1)): "101"})
    out = run(tmp_path, m, market)[DEL]
    nets = {e["token"]: e["horizons"]["4h"]["net"] for e in out["events"]}
    assert nets == {"AAA": pytest.approx(0.0171), "BBB": pytest.approx(-0.0129),
                    "CCC": pytest.approx(-0.0029)}
    assert out["verdict"] == "INCONCLUSIVE-by-data"
    assert any("n 2 < 20" in r for r in out["reasons"])
    assert out["primary"]["4h"]["median"] == pytest.approx((0.0021 - 0.0029) / 2)
    allowed = {nv.kline_url("um", s, d) for s in ("AAAUSDT", "BBBUSDT", "CCCUSDT", "BTCUSDT")
               for d in [nu.utc_date(t + k * D) for t in (T1, T2) for k in range(-1, 6)]}
    assert set(market.urls) <= allowed and not any("DDD" in u for u in market.urls)
    assert (tmp_path / "out" / ("results-%s.json" % DEL)).exists()
    assert (tmp_path / "out" / ("report-%s.md" % DEL)).exists()


def test_stored_break_even_results_resolve_exactly(tmp_path):
    toks = ["T%02d" % i for i in range(20)]
    m = manifest([DEL], [ev("binance:%d" % i, T1, t) for i, t in enumerate(toks)])
    out = run(tmp_path, m, Market({(t + "USDT", exit4h(T1)): "99.71" for t in toks}))[DEL]
    assert out["verdict"] == "FAIL" and out["primary"]["4h"]["median"] == 0.0
    stored = json.loads((tmp_path / "out" / ("results-%s.json" % DEL)).read_text(encoding="utf-8"))
    assert {e["horizons"]["4h"]["net"] for e in stored["events"]} == {"0"}
    assert {e["horizons"]["30m"]["net"] for e in stored["events"]} == {"-29/10000"}
    assert isinstance(stored["primary"]["4h"]["median"], float) and isinstance(stored["coverage"], float)
    assert stored["verdict"] == "FAIL" and rp.resolution(stored)["verdict"] == "FAIL"


def test_upbit_manifest_yields_long_and_fade_from_same_rows(tmp_path):
    m = manifest([LONG, FADE], [ev("upbit:1", T1, "TST", kind="krw_addition", spot="TSTUSDT"),
                                ev("upbit:2", T2, "SPT", kind="krw_addition", hl="ineligible",
                                   spot="SPTUSDT")])
    market = Market({("TSTUSDT", exit4h(T1)): "110"})
    out = run(tmp_path, m, market)
    long = {e["token"]: e for e in out[LONG]["events"]}
    fade = {e["token"]: e for e in out[FADE]["events"]}
    assert set(long) == {"TST", "SPT"} and set(fade) == {"TST"}
    assert long["SPT"]["venue"] == "binance_spot"
    assert fade["TST"]["horizons"]["4h"]["net"] == pytest.approx(
        -long["TST"]["horizons"]["4h"]["gross"] - 0.0029)
    assert len(market.urls) == len(set(market.urls))        # each series downloaded once


def test_report_says_proxy_result_and_mae_only_for_shorts(tmp_path):
    m = manifest([LONG, FADE], [ev("upbit:1", T1, "TST", kind="krw_addition", spot="TSTUSDT")])
    run(tmp_path, m, Market())
    long_md = (tmp_path / "out" / ("report-%s.md" % LONG)).read_text(encoding="utf-8")
    fade_md = (tmp_path / "out" / ("report-%s.md" % FADE)).read_text(encoding="utf-8")
    for md in (long_md, fade_md):
        assert "proxy result" in md and "one finding" in md and "Limitations" in md
    assert "MAE" in fade_md and "MAE" not in long_md


def test_resolution_from_results_only_and_verify_detects_edit(tmp_path):
    m = manifest([DEL], [ev("binance:1", T1, "AAA")])
    out = run(tmp_path, m, Market())[DEL]
    res = rp.resolution(out)
    assert res["verdict"] == out["verdict"] and res["label"] == "proxy result"
    assert res["code_commit"] == "p2commit" and res["manifest_sha256"] == out["manifest_sha256"]
    assert set(res["primary_4h"]) == {"n", "median", "half_medians", "top_decile_share"}
    prereg = json.loads((ROOT / "ft_userdata" / "preregistrations.json").read_text(encoding="utf-8"))
    for e in prereg["preregistrations"]:
        if e.get("id") == DEL:
            e["resolution"] = res
    pp = tmp_path / "prereg.json"
    pp.write_text(json.dumps(prereg, ensure_ascii=False), encoding="utf-8")
    assert rp.verify_resolution(pp, tmp_path / "out") == []
    for e in prereg["preregistrations"]:
        if e.get("id") == DEL:
            e["resolution"] = {**res, "verdict": "PASS"}
    pp.write_text(json.dumps(prereg, ensure_ascii=False), encoding="utf-8")
    assert rp.verify_resolution(pp, tmp_path / "out")
    assert rp.main(["verify-resolution", "--prereg", str(pp), "--results", str(tmp_path / "out")]) == 1
