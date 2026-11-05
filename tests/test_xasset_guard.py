"""Cross-asset risk-off guard study (#254): network-free tests of the trigger, block and
statistics code, and of the preregistration freezing the constants the code runs on.

    python3 -m pytest tests/test_xasset_guard.py -q
"""
import json
import random
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "xasset_guard_2026-11"))

import xasset_guard as xg  # noqa: E402

PREREG = ROOT / "ft_userdata" / "preregistrations.json"
H = 3600


def entry():
    reg = json.loads(PREREG.read_text(encoding="utf-8"))["preregistrations"]
    hits = [e for e in reg if e.get("id") == xg.PREREG_ID]
    assert len(hits) == 1
    return hits[0]


def t(iso_z):
    return xg.utc_s(iso_z)


def trade(entry_iso, pnl, short=False, ratio=None):
    return dict(pair="X/USDT", entry_s=t(entry_iso), ratio=pnl / 10 if ratio is None else ratio,
                abs=pnl, is_short=short)


# ---- preregistration ---------------------------------------------------------------------

def test_entry_is_open_research_only_and_unresolved():
    e = entry()
    assert e["status"] == "open" and e["bot"] is None and e["resolution"] is None
    assert e["issue"] == "#254" and e["triggers"] == [] and e["amendments"] == []
    assert e["frozen"]["places_orders"] is False
    assert "allocation" in " ".join(e["rules"])


def test_frozen_block_matches_the_code():
    fr = entry()["frozen"]
    assert float(fr["es_drop"]) == xg.ES_DROP and float(fr["vix_rise"]) == xg.VIX_RISE
    assert float(fr["vixd_rise"]) == xg.VIXD_RISE
    assert fr["bar_s"] == xg.BAR_S and fr["latency_s"] == xg.LATENCY_S
    assert fr["vix_close_et"] == "%02d:%02d" % xg.VIX_CLOSE_ET
    assert tuple(fr["hours"]) == xg.HOURS and tuple(fr["vixd_hours"]) == xg.VIXD_HOURS
    assert set(fr["guards"]) == set(xg.INTRADAY_GUARDS) | {"VIXD"}
    assert fr["n_variants"] == xg.N_VARIANTS == 10
    p = fr["primary"]
    assert (p["guard"], p["hours"], p["list"]) == xg.PRIMARY
    assert tuple(fr["window_intraday_utc"]) == xg.WINDOW_INTRADAY
    assert tuple(fr["window_daily_utc"]) == xg.WINDOW_DAILY
    assert fr["bootstrap_resamples"] == xg.BOOT_N and fr["bootstrap_seed"] == xg.SEED
    assert float(fr["ci_level"]) == xg.CI_LEVEL
    assert fr["placebo_draws"] == xg.N_PLACEBO and fr["placebo_max_days"] == xg.PLACEBO_MAX_DAYS
    assert fr["min_blocked_for_pass"] == xg.MIN_BLOCKED_FOR_PASS
    assert float(fr["secondary_placebo_pctile"]) == pytest.approx(xg.SECONDARY_PLACEBO_PCTILE)
    assert fr["raw_sha256"] == xg.RAW and fr["fetched_at_utc"] == xg.FETCHED_AT
    assert set(fr["longs_only_sensitivity"]) == xg.SHORT_LISTS


def test_frozen_trade_lists_match_the_code():
    lists = entry()["frozen"]["trade_lists"]
    code = {}
    for label, rel, strat, _, unit, h in xg.STRATS:
        code.setdefault(label, []).append((rel[5:] if rel.startswith("live:") else rel, strat, h))
    assert set(lists) == set(code)
    for label, rows in code.items():
        fr = lists[label]
        files = fr["file"] if isinstance(fr["file"], list) else [fr["file"]]
        shas = fr["sha256"] if isinstance(fr["sha256"], list) else [fr["sha256"]]
        assert files == [r[0] for r in rows] and shas == [r[2] for r in rows]
        if "strategy" in fr:
            assert [fr["strategy"]] * len(rows) == [r[1] for r in rows]


# ---- inputs ------------------------------------------------------------------------------

def test_parse_yahoo_drops_null_misaligned_and_partial_bars():
    base = t("2026-11-05T10:00:00Z")
    obj = {"chart": {"result": [{"timestamp": [base, base + H, base + 2 * H, base + 2 * H + 1260,
                                               base + 3 * H],
                                 "indicators": {"quote": [{"high": [2, None, 4, 5, 6],
                                                           "close": [1, 2, 3, 4, 5]}]}}]}}
    bars = xg.parse_yahoo(obj, fetched_s=base + 3 * H + 1800)   # last bar still open
    assert bars == [(base, 2.0, 1.0), (base + 2 * H, 4.0, 3.0)]


def test_parse_cboe_dates_are_iso_and_sorted():
    rows = xg.parse_cboe("DATE,OPEN,HIGH,LOW,CLOSE\n11/04/2026,1,2,0.5,16.61\n01/02/1990,1,1,1,17.24\n")
    assert rows == [("1990-01-02", 17.24), ("2026-11-04", 16.61)]


def test_naive_dates_are_utc_not_host_local():
    assert xg.naive_utc_s("2026-09-17 20:00:02.686795") == pytest.approx(
        t("2026-09-17T20:00:02Z") + 0.686795)
    assert xg.naive_utc_s("2024-04-15T06:58:32+00:00") == t("2024-04-15T06:58:32Z")


def test_load_sqlite_reads_closed_trades_only(tmp_path):
    db = tmp_path / "t.sqlite"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE trades (pair, open_date, close_profit, close_profit_abs, is_short,"
              " is_open)")
    c.executemany("INSERT INTO trades VALUES (?,?,?,?,?,?)", [
        ("A/USDT", "2026-09-01 10:00:00", 0.02, 0.3, 0, 0),
        ("B/USDT", "2026-09-02 10:00:00", None, None, 1, 1)])
    c.commit()
    c.close()
    [row] = xg.load_sqlite(str(db))
    assert row == dict(pair="A/USDT", entry_s=t("2026-09-01T10:00:00Z"), ratio=0.02, abs=0.3,
                       is_short=False)


# ---- triggers ----------------------------------------------------------------------------

def test_es60_needs_consecutive_bars_and_a_full_percent():
    b = t("2025-03-10T14:00:00Z")
    bars = [(b, 0, 100.0), (b + H, 0, 98.9),          # -1.1 %: fires
            (b + 3 * H, 0, 90.0),                     # 2 h gap: never compared
            (b + 4 * H, 0, 89.2),                     # -0.89 %: no
            (b + 5 * H, 0, 88.0)]                     # -1.35 %: fires
    trig = xg.es_triggers(bars)
    assert [x[0] for x in trig] == [b + 2 * H + 300, b + 6 * H + 300]
    assert all(x[1] == "ES60" for x in trig)


def test_vix20_uses_the_previous_cboe_close_once_per_et_date():
    closes = [("2025-04-02", 20.0), ("2025-04-03", 30.0)]
    d3 = t("2025-04-03T13:00:00Z")                    # 09:00 ET on 04-03
    bars = [(d3, 99.0, 23.9),                         # close +19.5 % vs 04-02 (high ignored)
            (d3 + H, 24.5, 24.0),                     # close +20 %: fires
            (d3 + 2 * H, 30.0, 29.0),                 # same ET date: no second trigger
            (t("2025-04-04T03:00:00Z"), 37.0, 36.0),  # 23:00 ET on 04-03: still 04-03
            (t("2025-04-04T13:00:00Z"), 40.0, 35.9),  # 04-04 vs 04-03 close 30: +19.7 %
            (t("2025-04-04T14:00:00Z"), 36.5, 36.0)]  # +20 %: fires
    trig = xg.vix_triggers(bars, closes)
    assert [x[0] for x in trig] == [d3 + 2 * H + 300, t("2025-04-04T15:00:00Z") + 300]


def test_vix20_without_an_earlier_close_is_silent():
    assert xg.vix_triggers([(t("2025-04-02T14:00:00Z"), 99.0, 99.0)],
                           [("2025-04-02", 10.0)]) == []


def test_vixd_fires_at_the_1615_et_close_dst_aware():
    closes = [("2026-01-02", 10.0), ("2026-01-05", 12.0), ("2026-07-01", 10.0),
              ("2026-07-02", 12.5), ("2026-07-06", 14.0)]
    trig = xg.vixd_triggers(closes)
    assert [x[0] for x in trig] == [t("2026-01-05T21:15:00Z") + 300,
                                    t("2026-07-02T20:15:00Z") + 300]


def test_intervals_merge_and_blocks_are_half_open():
    ivs = xg.intervals([100, 100 + 2 * H, 100 + 10 * H], hours=4)
    assert ivs == [(100, 100 + 6 * H), (100 + 10 * H, 100 + 14 * H)]
    assert xg.blocked(100, ivs) and xg.blocked(100 + 6 * H - 1, ivs)
    assert not xg.blocked(99, ivs) and not xg.blocked(100 + 6 * H, ivs)
    assert xg.intervals([100], 4, shift=86400) == [(86500, 86500 + 4 * H)]
    assert xg.guarded_share(ivs, 100, 100 + 20 * H) == pytest.approx(10 / 20)


# ---- evaluation --------------------------------------------------------------------------

def test_evaluate_first_order_change_window_and_longs_only():
    trig = [t("2025-01-10T15:05:00Z")]
    win = (t("2025-01-01T00:00:00Z"), t("2025-02-01T00:00:00Z"))
    trades = [trade("2025-01-10T15:05:00Z", -3.0),               # at the trigger: blocked
              trade("2025-01-10T20:00:00Z", -1.0, short=True),   # blocked unless longs only
              trade("2025-01-11T03:05:00Z", 5.0),                # 12 h later: kept
              trade("2025-01-20T00:00:00Z", 2.0),
              trade("2025-03-01T00:00:00Z", 100.0)]              # outside the window
    rng = random.Random(1)
    offs = xg.placebo_offsets(rng, n=50)
    c = xg.evaluate(trades, trig, 12, win, offs, rng)
    assert (c["n"], c["n_blocked"]) == (4, 2)
    assert c["net_without"] == 3.0 and c["delta"] == 4.0 and c["net_with"] == 7.0
    assert c["blocked"]["sum_abs"] == -4.0 and c["kept"]["n"] == 2
    lo = xg.evaluate(trades, trig, 12, win, offs, rng, longs_only=True)
    assert lo["n_blocked"] == 1 and lo["delta"] == 3.0


def test_bootstrap_one_month_is_degenerate_at_the_actual_values():
    trades = [trade("2025-01-0%dT00:00:00Z" % d, p) for d, p in ((1, 1.0), (2, -2.0), (3, 4.0))]
    flags = [False, True, False]
    b = xg.block_bootstrap(trades, flags, random.Random(3), n_boot=200)
    assert b["months"] == 1
    assert b["net_without"] == {"lo": 3.0, "hi": 3.0}
    assert b["net_with"] == {"lo": 5.0, "hi": 5.0} and b["delta"] == {"lo": 2.0, "hi": 2.0}
    assert b["diff_mean"]["lo"] == pytest.approx(-0.2 - 0.25) and b["diff_skipped"] == 0


def test_bootstrap_counts_draws_without_blocked_trades():
    trades = [trade("2025-01-01T00:00:00Z", 1.0), trade("2025-02-01T00:00:00Z", -1.0)]
    b = xg.block_bootstrap(trades, [False, True], random.Random(5), n_boot=400)
    assert 0 < b["diff_skipped"] < 400
    assert b["delta"]["lo"] == 0.0 and b["delta"]["hi"] == 2.0


def test_placebo_percentile_counts_ties_half():
    trades = [trade("2025-01-10T12:00:00Z", -2.0)]
    real = 2.0   # the real guard blocks the loser
    p = xg.placebo(trades, [t("2025-01-10T11:00:00Z")], 4, [86400, -86400, 0], real)
    # shifted draws block nothing (change 0 < 2); the zero shift ties
    assert p["pctile"] == pytest.approx(100 * (2 + 0.5) / 3)
    assert p["share_nonzero"] == pytest.approx(1 / 3)


def test_placebo_offsets_are_whole_days_within_30():
    offs = xg.placebo_offsets(random.Random(xg.SEED))
    assert len(offs) == xg.N_PLACEBO
    assert all(o % 86400 == 0 and 1 <= abs(o) // 86400 <= 30 for o in offs)
    assert {o > 0 for o in offs} == {True, False}


@pytest.mark.parametrize("nb,delta,ci,pl,expected", [
    (12, 5.0, (0.5, 9.0), 97, "helps"),
    (12, 5.0, (-0.5, 9.0), 97, "inconclusive"),
    (12, 5.0, (0.5, 9.0), 94, "inconclusive"),
    (9, 5.0, (0.5, 9.0), 99, "inconclusive"),
    (12, -5.0, (-9.0, -0.5), 3, "hurts"),
    (12, -5.0, (-9.0, 0.5), 3, "inconclusive"),
])
def test_verdict_is_the_frozen_rule(nb, delta, ci, pl, expected):
    cell = dict(n_blocked=nb, delta=delta, boot=dict(delta=dict(lo=ci[0], hi=ci[1])),
                placebo=dict(pctile=pl))
    assert xg.verdict(cell) == expected


# ---- descriptive timeline ----------------------------------------------------------------

def test_first_drop_30m_is_known_at_the_bar_close():
    b = t("2026-11-05T14:00:00Z")
    closes = {b + 60 * i: 100.0 for i in range(31)}
    closes[b + 60 * 30] = 98.9
    when, ret = xg.first_drop_30m(closes, b, b + 86400)
    assert when == b + 60 * 31 and ret == pytest.approx(-0.011)
    assert xg.first_drop_30m({b: 100.0, b + 60: 50.0}, b, b + 86400) == (None, None)


# ---- end to end on synthetic inputs ------------------------------------------------------

def _yahoo(rows):
    return {"chart": {"result": [{"timestamp": [r[0] for r in rows], "indicators": {"quote": [
        {"high": [r[1] for r in rows], "close": [r[2] for r in rows]}]}}]}}


def test_run_end_to_end_on_synthetic_inputs(tmp_path, monkeypatch):
    data, root, out = tmp_path / "data", tmp_path / "root", tmp_path / "out"
    (data / "raw").mkdir(parents=True)
    (data / "live").mkdir()
    root.mkdir()
    b = t("2025-03-10T13:00:00Z")
    es = [(b + i * H, 0, 100.0) for i in range(5)] + [(b + 5 * H, 0, 98.0)]   # ES60 at 19:05Z
    vix = [(b, 15.0, 15.0), (b + H, 19.0, 18.5)]                               # VIX20 at 15:05Z
    files = {
        "yahoo_1h_ES_F.json": json.dumps(_yahoo(es)),
        "yahoo_1h__VIX.json": json.dumps(_yahoo(vix)),
        "cboe_VIX_History.csv": "DATE,OPEN,HIGH,LOW,CLOSE\n03/07/2025,1,1,1,15.0\n"
                                "03/10/2025,1,1,1,18.5\n",
        "yahoo_1m_5d_ES_F.json": json.dumps(_yahoo([(t("2026-11-05T12:00:00Z"), 1, 100.0)])),
        "yahoo_1m_5d_NQ_F.json": json.dumps(_yahoo([(t("2026-11-05T12:00:00Z"), 1, 100.0)])),
        "yahoo_1m_5d__VIX.json": json.dumps(_yahoo([(t("2026-11-05T12:00:00Z"), 1, 21.0)])),
        "binance_spot_BTCUSDT_1m_20261105.json": json.dumps([[t("2026-11-05T12:00:00Z") * 1000,
                                                              0, 0, 0, "100.0"]]),
        "binance_spot_BTCUSDT_1m_20261105b.json": "[]",
    }
    for name, body in files.items():
        (data / "raw" / name).write_text(body)
    sha = lambda p: xg.sha256(str(p))  # noqa: E731
    monkeypatch.setattr(xg, "RAW", {n: sha(data / "raw" / n) for n in xg.RAW})
    monkeypatch.setattr(xg, "TIMELINE", {n: sha(data / "raw" / n) for n in xg.TIMELINE})
    trades = {"trades": [
        {"pair": "A/USDT", "open_timestamp": (b + 3 * H) * 1000, "profit_ratio": -0.05,
         "profit_abs": -0.75, "is_short": False},                     # in the VIX20 window
        {"pair": "B/USDT", "open_timestamp": (b + 30 * H) * 1000, "profit_ratio": 0.04,
         "profit_abs": 0.6, "is_short": True}]}
    (root / "kd.json").write_text(json.dumps(trades))
    monkeypatch.setattr(xg, "STRATS", [("Killers_dry", "kd.json", None, "kdry", "USDT",
                                        sha(root / "kd.json"))])
    monkeypatch.setattr(xg, "PRIMARY", ("OR", 12, "Killers_dry"))
    monkeypatch.setattr(xg, "BOOT_N", 50)
    monkeypatch.setattr(xg, "N_PLACEBO", 20)
    s = xg.run(str(root), str(data), str(out))
    assert s["n_triggers"] == {"ES60": 1, "VIX20": 1, "OR": 2, "VIXD": 1}
    cells = {(r["guard"], r["hours"], r["longs_only"]): r for r in s["results"]}
    assert len(cells) == xg.N_VARIANTS * 2
    assert cells[("VIX20", 4, False)]["n_blocked"] == 1
    assert cells[("VIX20", 4, False)]["delta"] == pytest.approx(0.75)
    assert cells[("ES60", 4, False)]["n_blocked"] == 0
    assert cells[("OR", 12, False)]["verdict"] == "inconclusive"     # fewer than 10 blocked
    assert (out / "tables.md").exists() and (out / "triggers.csv").exists()
    assert json.loads((out / "blocked_backtest_trades.json").read_text())


def test_sha256_mismatch_aborts(tmp_path):
    p = tmp_path / "f"
    p.write_text("x")
    with pytest.raises(SystemExit):
        xg.verify(str(p), "0" * 64)
