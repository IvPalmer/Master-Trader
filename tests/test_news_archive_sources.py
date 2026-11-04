"""PIT news archive source parsers (issue #229, Part A): network-free, fixture-based."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "news_archive"))

import na_sources  # noqa: E402
from na_sources import SOURCES, diff_universe, to_utc  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "news_archive"


def load(name):
    return (FIX / name).read_bytes()


@pytest.mark.parametrize("key,fixture,n", [
    ("tree", "tree.json", 2),
    ("binance_listing", "binance_cms_48.json", 2),
    ("binance_delisting", "binance_cms_161.json", 2),
    ("upbit", "upbit.json", 2),
    ("okx_listings", "okx_listings.json", 2),
    ("okx_delistings", "okx_listings.json", 2),
    ("rss_coindesk", "rss_coindesk.xml", 2),
    ("rss_blockworks", "atom_sample.xml", 2),
    ("ff_calendar", "ff_calendar.json", 2),
    ("fear_greed", "fear_greed.json", 1),
    ("hyperliquid_universe", "hl_meta_a.json", 1),
])
def test_parser_yields_items_with_ids_and_utc(key, fixture, n):
    items = SOURCES[key].parse(load(fixture))
    assert len(items) == n
    for it in items:
        assert it.source_item_id
        assert it.published_at is None or it.published_at.endswith("+00:00")
        json.dumps(it.raw)  # raw must be JSON-serializable


def test_sources_cover_spec_table_and_flags():
    expected = {"tree", "binance_listing", "binance_delisting", "upbit", "okx_listings",
                "okx_delistings", "hyperliquid_universe", "rss_coindesk", "rss_theblock",
                "rss_decrypt", "rss_blockworks", "rss_cointelegraph", "rss_fed",
                "ff_calendar", "fear_greed"}
    assert set(SOURCES) == expected
    assert {k for k, s in SOURCES.items() if s.binance} == {"binance_listing", "binance_delisting"}
    assert {k for k, s in SOURCES.items() if not s.list_feed} == {
        "hyperliquid_universe", "ff_calendar", "fear_greed"}
    assert SOURCES["tree"].interval_s == 60 and SOURCES["upbit"].interval_s == 120
    assert SOURCES["ff_calendar"].interval_s == 6 * 3600
    assert SOURCES["fear_greed"].interval_s == 3600
    assert "catalogId=161" in SOURCES["binance_delisting"].url
    assert SOURCES["hyperliquid_universe"].method == "POST"
    assert json.loads(SOURCES["hyperliquid_universe"].body) == {"type": "meta"}
    for s in SOURCES.values():
        assert s.headers["User-Agent"]
        assert (s.backfill is None) == (s.binance or not s.list_feed or s.key.startswith("rss_"))


def test_tree_backfill_uses_limit_2000_and_list_feeds_page_up_to_3():
    [tb] = SOURCES["tree"].backfill()
    assert "limit=2000" in tb.url
    for key in ("upbit", "okx_listings", "okx_delistings"):
        pages = SOURCES[key].backfill()
        assert len(pages) == 3
        assert all(p.parse is SOURCES[key].parse for p in pages)
        assert len({p.url for p in pages} | {SOURCES[key].url}) == 4


def test_upbit_kst_converted_to_utc():
    items = {i.source_item_id: i for i in SOURCES["upbit"].parse(load("upbit.json"))}
    assert items["6714"].published_at == "2026-10-27T07:30:00.000000+00:00"
    # publish time is first_listed_at; listed_at moves when the notice is edited
    assert items["6687"].published_at == "2026-10-21T11:00:00.000000+00:00"
    assert to_utc("2026-10-27T16:30:00+09:00", "kst") == "2026-10-27T07:30:00.000000+00:00"
    assert to_utc("2026-10-27T16:30:00", "kst") == "2026-10-27T07:30:00.000000+00:00"


def test_rss_and_atom_ids_use_guid_else_link():
    rss = SOURCES["rss_coindesk"].parse(load("rss_coindesk.xml"))
    assert rss[0].source_item_id == "045b3be7-30bf-444a-bc6f-49fcd6ae5538"
    assert rss[1].source_item_id == rss[1].url and rss[1].url.startswith("https://www.coindesk.com/")
    assert rss[0].published_at == "2026-11-03T23:19:44.000000+00:00"
    atom = SOURCES["rss_blockworks"].parse(load("atom_sample.xml"))
    assert atom[0].source_item_id == "https://blockworks.com/news/venezuelas-sanctions-stablecoins"
    assert atom[1].source_item_id == "https://blockworks.com/news/strategy-playbook-2026"
    assert atom[0].published_at == "2026-01-07T14:00:00.000000+00:00"
    assert atom[1].published_at == "2026-01-06T17:36:33.000000+00:00"  # <updated> fallback


def test_tree_symbols_come_from_suggestions():
    raw = json.loads(load("tree.json"))
    items = SOURCES["tree"].parse(load("tree.json"))
    assert [i.symbols for i in items] == [r["suggestions"] for r in raw]
    assert items[0].published_at == "2026-11-03T23:30:00.698000+00:00"


def test_ff_calendar_id_is_sha1_title_country_date():
    raw = json.loads(load("ff_calendar.json"))
    items = SOURCES["ff_calendar"].parse(load("ff_calendar.json"))
    r = raw[0]
    assert items[0].source_item_id == hashlib.sha1(
        f"{r['title']}|{r['country']}|{r['date']}".encode()).hexdigest()
    assert items[0].published_at == "2026-11-03T03:30:00.000000+00:00"


def test_fear_greed_drops_volatile_countdown():
    [it] = SOURCES["fear_greed"].parse(load("fear_greed.json"))
    assert it.source_item_id == "1793664000"
    assert "time_until_update" not in it.raw
    assert it.published_at == "2026-11-03T00:00:00.000000+00:00"


def test_okx_id_is_locale_free_url():
    items = SOURCES["okx_listings"].parse(load("okx_listings.json"))
    assert items[0].source_item_id.startswith("https://www.okx.com/help/")
    assert "/pt-br/" in items[0].url


def test_hyperliquid_universe_names_and_delisted():
    [a] = SOURCES["hyperliquid_universe"].parse(load("hl_meta_a.json"))
    [b] = SOURCES["hyperliquid_universe"].parse(load("hl_meta_b.json"))
    assert na_sources.universe_names(a) == ({"BTC", "ETH", "ATOM"}, {"MATIC"})
    names_b, delisted_b = na_sources.universe_names(b)
    assert names_b == {"BTC", "NEWCOIN"}
    ids = [i.source_item_id for i in diff_universe({"BTC", "ETH", "ATOM"}, names_b, 2,
                                                   delisted=delisted_b)]
    assert sorted(ids) == ["add:NEWCOIN:2", "delisted:ETH:2", "remove:ATOM:2"]


def test_diff_universe_relisting_gets_new_ids():
    a, b = {"BTC", "ETH"}, {"BTC"}
    assert diff_universe(None, a, 1) == []
    seen = []
    for seq, (prev, cur) in enumerate([(a, b), (b, a), (a, b)], start=2):
        ids = [i.source_item_id for i in diff_universe(prev, cur, seq)]
        assert ids == [("remove" if seq % 2 == 0 else "add") + f":ETH:{seq}"]
        seen += ids
    assert seen == ["remove:ETH:2", "add:ETH:3", "remove:ETH:4"]
    assert len(set(seen)) == 3


@pytest.mark.parametrize("value,kind,expected", [
    (None, "ms", None),
    ("", "ms", None),
    ("", "iso", None),
    (True, "ms", None),
    ("not-a-number", "ms", None),
    (-5, "ms", None),
    (float("nan"), "s", None),
    (10 ** 30, "ms", None),
    (1730000000000, "ms", "2024-10-27T03:33:20.000000+00:00"),
    (1730000000, "ms", "2024-10-27T03:33:20.000000+00:00"),     # seconds where ms expected
    ("1730000000", "s", "2024-10-27T03:33:20.000000+00:00"),
    (1730000000000, "s", "2024-10-27T03:33:20.000000+00:00"),   # ms where seconds expected
    ("2026-11-03T20:15:53", "iso", None),                       # naive: ambiguous
    ("2026-11-03T20:15:53Z", "iso", "2026-11-03T20:15:53.000000+00:00"),
    ("2026-11-03T17:15:53-03:00", "iso", "2026-11-03T20:15:53.000000+00:00"),
    ("Tue, 03 Nov 2026 23:19:44 +0000", "rfc822", "2026-11-03T23:19:44.000000+00:00"),
    ("Thu, 29 Oct 2026 20:30:00 GMT", "rfc822", "2026-10-29T20:30:00.000000+00:00"),
    ("Tue, 03 Nov 2026 20:19:44 -0300", "rfc822", "2026-11-03T23:19:44.000000+00:00"),
    ("2026-11-03T23:19:44Z", "rfc822", "2026-11-03T23:19:44.000000+00:00"),  # ISO in pubDate
    ("garbage date", "rfc822", None),
    ({"a": 1}, "iso", None),
    ("2026-13-45T00:00:00+09:00", "kst", None),
])
def test_timestamp_edge_cases(value, kind, expected):
    assert to_utc(value, kind) == expected


@pytest.mark.parametrize("key,payload", [
    ("tree", b"<html>captcha</html>"),
    ("binance_listing", b'{"code":"000000","success":false,"data":null}'),
    ("upbit", b'{"success":false}'),
    ("okx_listings", b'{"code":"50011","msg":"Too Many Requests","data":[]}'),
    ("rss_coindesk", b"<html><body>Just a moment...</body></html>"),
    ("fear_greed", b'{"data":[],"metadata":{"error":"down"}}'),
])
def test_error_payloads_raise_not_return_empty(key, payload):
    with pytest.raises(Exception):
        SOURCES[key].parse(payload)
