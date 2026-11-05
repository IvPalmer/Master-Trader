"""Upbit fade forward monitor (#229): book walks, fees, funding and excursion (pure), and the
paced Hyperliquid client.

    python3 -m pytest tests/test_upbit_fade_forward_book.py -q
"""
from decimal import Decimal as D

import pytest

import uff_fakes as f
import uff_common as uc
import uff_venues as uv


def real_book(recv_lag_ms=200):
    j = f.fixture("hl_l2book_ena.json")
    return {**uv.parse_book(j), "recv_ms": j["time"] + recv_lag_ms}


def mk(bids, asks, time_ms=1000, recv_ms=1200):
    side = lambda lv: [(D(p), D(s)) for p, s in lv]   # noqa: E731
    return {"time": time_ms, "recv_ms": recv_ms, "bids": side(bids), "asks": side(asks)}


# --- book walk -----------------------------------------------------------------------------

def test_sell_about_100_usdc_into_the_real_book_and_freeze_q():
    b = real_book()
    rec, why = uv.fill(b, "sell", notional=uc.NOTIONAL_USDC, decimals=0)   # ENA szDecimals 0
    assert why is None
    assert rec["q"] == "622"                     # 100 / 0.16067 = 622.39 -> 622
    assert D(rec["vwap"]) == D("0.16067") and rec["levels_used"] == 1
    assert D(rec["notional"]) == D("622") * D("0.16067")
    assert rec["best_bid"] == "0.16067" and rec["best_ask"] == "0.16068"
    assert D(rec["mid"]) == (D("0.16067") + D("0.16068")) / 2
    assert rec["book_ms"] == b["time"] and rec["book_age_ms"] == 200


def test_buy_back_the_frozen_q_from_the_real_asks():
    rec, why = uv.fill(real_book(), "buy", q=D("622"), decimals=0)
    assert why is None and rec["side"] == "buy"
    assert D(rec["vwap"]) == D("0.16068") and rec["q"] == "622"


def test_multi_level_vwap_both_sides():
    b = mk(bids=[("1.00", "30"), ("0.99", "30"), ("0.98", "100")],
           asks=[("1.01", "10"), ("1.02", "10"), ("1.05", "100")])
    sell, _ = uv.fill(b, "sell", notional=D("60"), decimals=2)
    # 30 + 29.7 USDC from two levels, 0.3 / 0.98 = 0.306 more: q = 60.306 -> 60.31
    assert sell["q"] == "60.31" and sell["levels_used"] == 3
    assert D(sell["vwap"]) == (D("30") + D("29.7") + D("0.31") * D("0.98")) / D("60.31")
    buy, _ = uv.fill(b, "buy", q=D("25"), decimals=2)
    assert D(buy["vwap"]) == (D("10.1") + D("10.2") + D("5") * D("1.05")) / 25
    assert buy["levels"] == [["1.01", "10"], ["1.02", "10"], ["1.05", "5"]]


def test_thin_book_is_rejected():
    thin = mk(bids=[("1.0", "40"), ("0.9", "40")], asks=[("1.1", "40"), ("1.2", "10")])
    assert uv.fill(thin, "sell", notional=D("100"), decimals=0) == (None, "thin_book")   # 76 USDC
    assert uv.fill(thin, "buy", q=D("60"), decimals=0) == (None, "thin_book")          # 50 deep
    assert uv.fill(mk([], [("1", "1")]), "buy", q=D("1"), decimals=0) == (None, "empty_side")


def test_stale_book_is_rejected():
    b = mk([("1", "500")], [("1.01", "500")], time_ms=1000, recv_ms=6001)
    assert uv.fill(b, "sell", notional=D("100"), decimals=0) == (None, "stale_book")
    b["recv_ms"] = 6000                          # exactly 5 s old is accepted
    assert uv.fill(b, "sell", notional=D("100"), decimals=0)[1] is None


def test_q_is_rounded_half_even_to_sz_decimals():
    assert uv.quantize(D("2.5"), 0) == D("2") and uv.quantize(D("3.5"), 0) == D("4")
    assert uv.quantize(D("1.23456"), 3) == D("1.235")
    b = mk([("150", "10")], [("151", "10")])
    rec, _ = uv.fill(b, "sell", notional=D("100"), decimals=0)    # 0.667 -> 1 unit at 150
    assert rec["q"] == "1" and D(rec["notional"]) == D("150")
    assert uv.fill(mk([("500", "10")], [("501", "10")]), "sell", notional=D("100"),
                   decimals=0) == (None, "zero_size")              # 0.2 rounds to 0


# --- fee and net ---------------------------------------------------------------------------

def test_fee_is_4_5_bps_of_each_legs_actual_notional():
    rec, _ = uv.fill(real_book(), "sell", notional=uc.NOTIONAL_USDC, decimals=0)
    assert D(rec["fee"]) == D("622") * D("0.16067") * D("0.00045")    # not 100 x 4.5 bps
    entry = {"q": "100", "vwap": "1.00"}
    exit_ = {"q": "100", "vwap": "0.90"}
    n = uv.net(entry, exit_, {"status": "complete", "cashflow": "0.25"})
    assert D(n["fees"]) == D("100") * D("0.00045") + D("90") * D("0.00045")
    assert D(n["gross_pnl"]) == D("10")
    assert D(n["net_pnl"]) == D("10") - D("0.0855") + D("0.25")
    assert D(n["net_return"]) == D(n["net_pnl"]) / 100
    assert D(n["net_ex_funding_return"]) == (D("10") - D("0.0855")) / 100


def test_net_is_incomplete_without_complete_funding():
    n = uv.net({"q": "100", "vwap": "1"}, {"q": "100", "vwap": "0.9"},
               {"status": "missing", "cashflow": None})
    assert n["net_return"] is None and n["funding"] is None
    assert n["net_ex_funding_return"] is not None


# --- funding -------------------------------------------------------------------------------

def test_boundaries_cover_the_hold():
    e = 1_800_000_000_000 + 8 * f.MIN               # 8 min past an hour
    assert len(uv.boundaries(e, e + f.D)) == 24
    assert uv.boundaries(e, e + f.D)[0] == e - 8 * f.MIN + f.H
    late = e + 50 * f.MIN                           # 58 min past; exit filled 5 min late
    assert len(uv.boundaries(late, late + f.D + 5 * f.MIN)) == 25


def test_rates_map_real_records_to_their_hour():
    recs = [(r["time"], r["fundingRate"]) for r in f.fixture("hl_funding_ena.json")]
    rates = uv.rates_by_hour(recs)
    assert sorted(rates) == [t - t % f.H for t, _ in recs]
    assert rates[1793894400000] == "0.0000077649"


def _hold():
    e = 1_800_000_000_000 + 8 * f.MIN
    hours = uv.boundaries(e, e + 3 * f.H)
    return e, e + 3 * f.H, hours


def test_positive_funding_pays_the_short():
    e, x, hours = _hold()
    oracle = {h: (h + 2_000, "2.0") for h in hours}
    up = uv.funding(D("100"), e, x, {h: "0.0001" for h in hours}, oracle)
    assert up["status"] == "complete" and up["estimated"] is True
    assert D(up["cashflow"]) == 3 * D("100") * D("2.0") * D("0.0001")     # +0.06 received
    down = uv.funding(D("100"), e, x, {h: "-0.0001" for h in hours}, oracle)
    assert D(down["cashflow"]) == -D("0.06")                              # a short pays


def test_missing_rate_or_observation_makes_funding_missing():
    e, x, hours = _hold()
    rates = {h: "0.0001" for h in hours}
    oracle = {h: (h, "2.0") for h in hours}
    no_rate = uv.funding(D("100"), e, x, {h: r for h, r in rates.items() if h != hours[1]},
                         oracle)
    assert no_rate["status"] == "missing" and no_rate["cashflow"] is None
    assert no_rate["missing"] == [{"hour_ms": hours[1], "rate": False, "oracle": True}]
    far = {**oracle, hours[2]: (hours[2] - 60_001, "2.0")}               # 60.001 s early
    assert uv.funding(D("100"), e, x, rates, far)["status"] == "missing"
    edge = {**oracle, hours[2]: (hours[2] + 60_000, "2.0")}              # exactly 60 s
    assert uv.funding(D("100"), e, x, rates, edge)["status"] == "complete"


# --- excursion -----------------------------------------------------------------------------

def test_excursion_uses_candles_wholly_inside_the_hold():
    rows = {c["t"]: [c["o"], c["h"], c["l"], c["c"]] for c in f.fixture("hl_candles_ena.json")}
    first = min(rows)
    e, x = first + 30_000, first + 4 * f.MIN + 1      # candles 2..4 lie wholly inside
    inside = sorted(rows)[1:4]
    rec = uv.excursion(rows, e, x, "0.1605")
    assert rec["status"] == "ok" and rec["candles"] == 3 and rec["descriptive"] is True
    hi = max(D(rows[k][1]) for k in inside)
    lo = min(D(rows[k][2]) for k in inside)
    assert D(rec["mae"]) == max(D(0), hi / D("0.1605") - 1)
    assert D(rec["mfe"]) == max(D(0), 1 - lo / D("0.1605"))
    assert uv.excursion({}, e, x, "0.1605")["status"] == "missing"


# --- Binance klines and Upbit markets --------------------------------------------------------

def test_real_klines_and_invalid_symbol_parse():
    rows = uv.parse_klines(f.json.dumps(f.fixture("binance_fapi_klines_ena.json")).encode())
    assert all(len(v) == 4 for v in rows.values()) and min(rows) % f.MIN == 0
    bad = f.resp(400, f.fixture("binance_invalid_symbol.json"))
    assert uv._invalid_symbol(bad) and not uv._invalid_symbol(f.resp(400, {"code": -1100}))


def test_real_upbit_market_list_parses_to_sorted_codes():
    markets = uv.parse_markets(f.json.dumps(f.fixture("upbit_markets.json")).encode())
    assert markets == sorted(markets) and "KRW-CARDS" in markets
    assert uv.krw_tokens(markets) >= {"CARDS", "BTC"} and "CARDS" in uv.krw_tokens(markets)
    with pytest.raises(ValueError):
        uv.parse_markets(b"[]")


# --- Hyperliquid client ----------------------------------------------------------------------

def test_client_paces_one_request_per_second_and_backs_off_on_429():
    clock = f.Clock(1_800_000_000_000)
    hl = f.FakeHl(clock)
    client = uv.Hyperliquid(hl, clock.sleep, clock.wall_s)
    client.meta()
    client.meta()
    assert clock.sleeps == [pytest.approx(1.0)]
    hl.n429 = 1
    with pytest.raises(ValueError):
        client.book("CARDS")                      # 429, then two attempts inside the backoff
    assert hl.count("l2Book") == 1                # nothing is sent while backing off
    clock.to(clock.ms + int(uc.HL_BACKOFF_S * 1000))
    assert client.book("CARDS")["bids"]
    assert client.n429 == 0 and client.backoff_until is None


def test_client_reads_real_shapes():
    clock = f.Clock(1_800_000_000_000)
    real = {"l2Book": f.fixture("hl_l2book_ena.json"),
            "metaAndAssetCtxs": f.fixture("hl_meta_and_asset_ctxs.json"),
            "candleSnapshot": f.fixture("hl_candles_ena.json"),
            "fundingHistory": f.fixture("hl_funding_ena.json"),
            "meta": f.fixture("hl_meta.json")}
    client = uv.Hyperliquid(lambda req: f.resp(200, real[f.json.loads(req.body)["type"]]),
                            clock.sleep, clock.wall_s)
    b = client.book("ENA")
    assert b["time"] == real["l2Book"]["time"] and b["recv_ms"] == clock.ms and len(b["bids"]) == 20
    px, obs = client.oracle_prices({"ENA"})
    assert px == {"ENA": "0.1607"} and obs == clock.ms
    assert len(client.funding_history("ENA", 0, 1)) == 4
    assert len(client.candles("ENA", 0, 1)) == len(real["candleSnapshot"]) == 6
    assert uv.sz_decimals(client.meta(), "ENA") == 0 and uv.sz_decimals(client.meta(), "X") is None
