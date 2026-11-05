"""Sources of the PIT news archive (#229 spec §4.2; market-wide feeds and cross-asset
snapshots #254): fetch specs and pure parsers.

Each parser takes the raw response body and returns a list of na_store.Item. A payload
that is not what the source normally sends (an HTML error page, success=false, an API
error code) raises, so the scheduler records a failed poll rather than an empty one.
Nothing here touches the network.
"""
import hashlib
import json
import math
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from na_store import Item, iso

UA = "master-trader-news-archive/1.0"
# Binance CMS needs a browser UA; the same one listing_short_forward/monitor.py uses.
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
JSON_HEADERS = {"User-Agent": UA, "Accept": "application/json"}
FEED_HEADERS = {"User-Agent": UA,
                "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.1"}
BINANCE_HEADERS = {"User-Agent": BROWSER_UA, "Accept": "application/json", "lang": "en"}

KST = timezone(timedelta(hours=9))
US_EASTERN = ZoneInfo("America/New_York")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
SANE_MIN = datetime(2000, 1, 1, tzinfo=timezone.utc)
SANE_MAX = datetime(2100, 1, 1, tzinfo=timezone.utc)
MS_THRESHOLD = 10 ** 11   # epoch values at or above this are milliseconds (1e11 s is year 5138)

BINANCE_REQUEST_GAP_S = 180


@dataclass(frozen=True)
class SourceSpec:
    key: str
    method: str
    url: str
    body: Optional[bytes]
    headers: dict
    interval_s: int
    list_feed: bool
    binance: bool
    parse: Callable
    backfill: Optional[Callable] = None
    min_gap_s: float = 0.0   # spacing between requests inside one poll (backfill pages)


# ---- timestamps ------------------------------------------------------------------------

def _epoch(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        value = int(value) if value.isdigit() else float(value)
    if isinstance(value, int):
        if value <= 0:
            return None
        return EPOCH + (timedelta(milliseconds=value) if value >= MS_THRESHOLD
                        else timedelta(seconds=value))
    if isinstance(value, float):
        if not math.isfinite(value) or value <= 0:
            return None
        return datetime.fromtimestamp(value / 1000 if value >= MS_THRESHOLD else value,
                                      tz=timezone.utc)
    return None


def _iso(value, naive_tz):
    if not isinstance(value, str) or not value.strip():
        return None
    dt = datetime.fromisoformat(value.strip())
    if dt.tzinfo is None:
        if naive_tz is None:
            return None
        dt = dt.replace(tzinfo=naive_tz)
    return dt


def _rfc822(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError, IndexError):
        dt = None
    if dt is None:
        return _iso(value, None)
    if dt.tzinfo is None:  # RFC 2822 "-0000": UTC, local zone unknown
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def to_utc(value, kind):
    """Normalize a source timestamp to ISO-8601 UTC with microseconds, or None.

    kind: "ms" / "s" (epoch numbers or digit strings; the magnitude decides between the
    two, so seconds sent where ms were expected still convert correctly), "kst"
    (ISO, naive means KST), "et" (ISO, naive means America/New_York; in the repeated
    fall-back hour the first, EDT, reading is taken), "iso" (ISO with an offset; naive is
    ambiguous -> None), "rfc822" (RSS pubDate, with an ISO fallback). Never raises.
    """
    try:
        if kind in ("ms", "s"):
            dt = _epoch(value)
        elif kind == "kst":
            dt = _iso(value, KST)
        elif kind == "et":
            dt = _iso(value, US_EASTERN)
        elif kind == "iso":
            dt = _iso(value, None)
        elif kind == "rfc822":
            dt = _rfc822(value)
        else:
            return None
    except (ValueError, TypeError, OverflowError, OSError, AttributeError):
        return None
    if dt is None or not (SANE_MIN <= dt < SANE_MAX):
        return None
    return iso(dt)


# ---- parsers ---------------------------------------------------------------------------

def _text(value):
    return value if isinstance(value, str) and value != "" else None


def _id(value):
    if value is None or isinstance(value, bool):
        return None
    s = str(value).strip()
    return s or None


def parse_tree(body):
    data = json.loads(body)
    if not isinstance(data, list):
        raise ValueError("tree: expected a JSON list")
    out = []
    for x in data:
        if not isinstance(x, dict) or not _id(x.get("_id")):
            continue
        sug = x.get("suggestions")
        out.append(Item(_id(x["_id"]), to_utc(x.get("time"), "ms"), _text(x.get("title")),
                        _text(x.get("body")), _text(x.get("url") or x.get("link")),
                        sug if isinstance(sug, list) else None, x))
    return out


def parse_binance(body):
    j = json.loads(body)
    if not isinstance(j, dict) or j.get("success") is not True:
        raise ValueError("binance cms: success is not true (code=%r)" % (
            j.get("code") if isinstance(j, dict) else None))
    out = []
    for cat in (j.get("data") or {}).get("catalogs") or []:
        for a in cat.get("articles") or []:
            if not isinstance(a, dict) or not _id(a.get("id")):
                continue
            code = _text(a.get("code"))
            url = "https://www.binance.com/en/support/announcement/%s" % code if code else None
            out.append(Item(_id(a["id"]), to_utc(a.get("releaseDate"), "ms"),
                            _text(a.get("title")), None, url, None, a))
    return out


def parse_upbit(body):
    j = json.loads(body)
    if not isinstance(j, dict) or j.get("success") is not True:
        raise ValueError("upbit: success is not true")
    out = []
    for n in j["data"]["notices"]:
        if not isinstance(n, dict) or not _id(n.get("id")):
            continue
        # first_listed_at is the original publish time; listed_at moves on each edit.
        published = to_utc(n.get("first_listed_at") or n.get("listed_at"), "kst")
        out.append(Item(_id(n["id"]), published, _text(n.get("title")), None,
                        "https://upbit.com/service_center/notice?id=%s" % _id(n["id"]),
                        None, n))
    return out


_LOCALE = re.compile(r"^[a-z]{2}(-[a-z]{2,4})?$")


def okx_item_id(url):
    """The announcement URL without its locale segment (/pt-br/help/x -> /help/x)."""
    parts = urllib.parse.urlsplit(url.strip())
    segs = [s for s in parts.path.split("/") if s]
    if len(segs) >= 2 and _LOCALE.match(segs[0]) and segs[1] == "help":
        segs = segs[1:]
    return "%s://%s/%s" % (parts.scheme, parts.netloc, "/".join(segs))


def parse_okx(body):
    j = json.loads(body)
    if not isinstance(j, dict) or str(j.get("code")) != "0":
        raise ValueError("okx: code=%r msg=%r" % (
            j.get("code") if isinstance(j, dict) else None,
            j.get("msg") if isinstance(j, dict) else None))
    out = []
    for d in j["data"]:
        for x in d.get("details") or []:
            url = _text(x.get("url")) if isinstance(x, dict) else None
            if not url:
                continue
            out.append(Item(okx_item_id(url), to_utc(x.get("pTime"), "ms"),
                            _text(x.get("title")), None, url, None, x))
    return out


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _elem(e):
    """XML element -> JSON-able value: text, or a dict of attributes/text/children."""
    text = (e.text or "").strip()
    children = list(e)
    if not children and not e.attrib:
        return text
    d = {}
    if e.attrib:
        d["@"] = dict(sorted(e.attrib.items()))
    if text:
        d["#text"] = text
    for c in children:
        v = _elem(c)
        if c.tag in d:
            if not isinstance(d[c.tag], list):
                d[c.tag] = [d[c.tag]]
            d[c.tag].append(v)
        else:
            d[c.tag] = v
    return d


ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"


def _atom_link(entry):
    for link in entry.findall(ATOM + "link"):
        if link.get("rel") in (None, "alternate") and link.get("href"):
            return link.get("href").strip()
    return None


def parse_feed(body):
    """RSS 2.0 or Atom. Item id: guid (RSS) / id (Atom), else the link."""
    root = ET.fromstring(body)
    kind = _local(root.tag)
    out = []
    if kind == "rss":
        channel = root.find("channel")
        if channel is None:
            raise ValueError("rss: no channel")
        for it in channel.findall("item"):
            link = (it.findtext("link") or "").strip() or None
            iid = (it.findtext("guid") or "").strip() or link
            if not iid:
                continue
            published = (to_utc(it.findtext("pubDate"), "rfc822")
                         or to_utc(it.findtext(DC + "date"), "iso"))
            out.append(Item(iid, published, _text((it.findtext("title") or "").strip()),
                            _text((it.findtext("description") or "").strip()), link, None,
                            _elem(it)))
    elif root.tag == ATOM + "feed":
        for e in root.findall(ATOM + "entry"):
            link = _atom_link(e)
            iid = (e.findtext(ATOM + "id") or "").strip() or link
            if not iid:
                continue
            published = (to_utc(e.findtext(ATOM + "published"), "iso")
                         or to_utc(e.findtext(ATOM + "updated"), "iso"))
            summary = e.findtext(ATOM + "summary") or e.findtext(ATOM + "content") or ""
            out.append(Item(iid, published, _text((e.findtext(ATOM + "title") or "").strip()),
                            _text(summary.strip()), link, None, _elem(e)))
    else:
        raise ValueError("feed: root element is %r, not rss/feed" % kind)
    return out


def parse_ff_calendar(body):
    data = json.loads(body)
    if not isinstance(data, list):
        raise ValueError("ff_calendar: expected a JSON list")
    out = []
    for x in data:
        if not isinstance(x, dict):
            continue
        key = "%s|%s|%s" % (x.get("title"), x.get("country"), x.get("date"))
        out.append(Item(hashlib.sha1(key.encode("utf-8")).hexdigest(),
                        to_utc(x.get("date"), "iso"), _text(x.get("title")), None, None,
                        None, x))
    return out


def parse_fear_greed(body):
    j = json.loads(body)
    if not isinstance(j, dict):
        raise ValueError("fear_greed: expected an object")
    err = (j.get("metadata") or {}).get("error")
    if err:
        raise ValueError("fear_greed: %s" % err)
    out = []
    for x in j.get("data") or []:
        if not isinstance(x, dict) or not _id(x.get("timestamp")):
            continue
        # time_until_update is a countdown that changes on every poll, not content.
        raw = {k: v for k, v in x.items() if k != "time_until_update"}
        title = "%s (%s)" % (x.get("value_classification"), x.get("value"))
        out.append(Item(_id(x["timestamp"]), to_utc(x.get("timestamp"), "s"), title, None,
                        None, None, raw))
    if not out:
        raise ValueError("fear_greed: no data")
    return out


YAHOO_BARS_KEPT = 35   # enough 1m bars for a 30-min change at every 5-min snapshot


def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _pct_title(symbol, price, prev):
    if _num(prev) and prev:
        return "%s %.6g (%+.2f%% vs prev close %.6g)" % (symbol, price, 100 * (price / prev - 1), prev)
    return "%s %.6g" % (symbol, price)


def parse_yahoo_chart(body):
    """Yahoo chart API (interval=1m, range=1d): one snapshot per last-trade time.

    Item id "<symbol>:<regularMarketTime>"; published_at = regularMarketTime. raw = the meta
    block plus the last YAHOO_BARS_KEPT 1m bars with a close, as [t, o, h, l, c, v] rows, so a
    reader can compute a 30-min change point-in-time from any one snapshot.
    """
    j = json.loads(body)
    chart = j.get("chart") if isinstance(j, dict) else None
    if not isinstance(chart, dict) or chart.get("error"):
        raise ValueError("yahoo chart: error=%r" % (
            chart.get("error") if isinstance(chart, dict) else None))
    res = chart.get("result")
    if not isinstance(res, list) or not res or not isinstance(res[0], dict):
        raise ValueError("yahoo chart: no result")
    r = res[0]
    meta = r.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("yahoo chart: no meta")
    symbol, t, price = _text(meta.get("symbol")), meta.get("regularMarketTime"), \
        meta.get("regularMarketPrice")
    if not symbol or not isinstance(t, int) or isinstance(t, bool) or not _num(price):
        raise ValueError("yahoo chart: meta lacks symbol, regularMarketTime or price")
    ts = r.get("timestamp") or []
    quote = ((r.get("indicators") or {}).get("quote") or [{}])[0] or {}
    cols = [quote.get(k) or [] for k in ("open", "high", "low", "close", "volume")]
    rows = []
    for i, ti in enumerate(ts):
        vals = [c[i] if i < len(c) else None for c in cols]
        if vals[3] is not None:
            rows.append([ti] + vals)
    prev = meta.get("previousClose", meta.get("chartPreviousClose"))
    raw = {"meta": meta, "bars_1m": rows[-YAHOO_BARS_KEPT:]}
    return [Item("%s:%d" % (symbol, t), to_utc(t, "s"), _pct_title(symbol, price, prev), None,
                 None, None, raw)]


def parse_cboe_quote(body):
    """CBOE delayed quote: one snapshot per last_trade_time (naive values are US Eastern).

    The top-level `timestamp` (server time, new on every request) is not content and is
    dropped; raw is the `data` block.
    """
    j = json.loads(body)
    d = j.get("data") if isinstance(j, dict) else None
    if not isinstance(d, dict):
        raise ValueError("cboe quote: no data block")
    symbol, price, ltt = _text(d.get("symbol")), d.get("current_price"), \
        _text(d.get("last_trade_time"))
    if not symbol or not _num(price) or not ltt:
        raise ValueError("cboe quote: data lacks symbol, current_price or last_trade_time")
    return [Item("%s:%s" % (symbol, ltt), to_utc(ltt, "et"),
                 _pct_title(symbol, price, d.get("prev_day_close")), None, None, None, d)]


def parse_hl_meta(body):
    """One snapshot item; the scheduler numbers it universe:<seq> and diffs it."""
    j = json.loads(body)
    universe = j["universe"]
    if not isinstance(universe, list):
        raise ValueError("hyperliquid meta: universe is not a list")
    return [Item("universe", None, None, None, None, None, {"universe": universe})]


def universe_names(item):
    """(active names, delisted names) of a universe snapshot item."""
    active, delisted = set(), set()
    for a in item.raw.get("universe") or []:
        name = a.get("name") if isinstance(a, dict) else None
        if name:
            (delisted if a.get("isDelisted") else active).add(name)
    return active, delisted


def _event(kind, name, seq):
    return Item("%s:%s:%d" % (kind, name, seq), None, "%s %s" % (kind, name), None, None,
                [name], {"event": kind, "name": name, "seq": seq})


def diff_universe(prev, cur, seq, delisted=frozenset()):
    """Synthetic transition items between two universe snapshots; [] for the first."""
    if prev is None:
        return []
    out = [_event("add", n, seq) for n in sorted(cur - prev)]
    out += [_event("delisted" if n in delisted else "remove", n, seq)
            for n in sorted(prev - cur)]
    return out


# ---- the source table --------------------------------------------------------------------

CMS_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
# Monitoring-tag notices are published in catalog 161 (Delisting); see README.
BINANCE_CATALOGS = {"binance_listing": 48, "binance_delisting": 161}
# Each catalog's turn in the one-request-per-180 s rotation.
BINANCE_INTERVAL_S = BINANCE_REQUEST_GAP_S * len(BINANCE_CATALOGS)

TREE_URL = "https://news.treeofalpha.com/api/news?limit=%d"
UPBIT_URL = ("https://api-manager.upbit.com/api/v1/announcements"
             "?os=web&page=%d&per_page=20&category=trade")
OKX_URL = "https://www.okx.com/api/v5/support/announcements?annType=%s"
CNBC_URL = "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=%d"
RSS_FEEDS = {
    "rss_coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss",
    "rss_theblock": "https://www.theblock.co/rss.xml",
    "rss_decrypt": "https://decrypt.co/feed",
    "rss_blockworks": "https://blockworks.com/feed",
    "rss_cointelegraph": "https://cointelegraph.com/rss",
    "rss_fed": "https://www.federalreserve.gov/feeds/press_all.xml",
    # market-wide headlines (#254); final URLs, since redirects are never followed
    "rss_cnbc_top": CNBC_URL % 100003114,
    "rss_cnbc_economy": CNBC_URL % 20910258,
    "rss_cnbc_finance": CNBC_URL % 10000664,
    "rss_mw_topstories": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "rss_mw_bulletins": "https://feeds.content.dowjones.io/public/rss/mw_bulletins",
    "rss_wsj_markets": "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain",
    "rss_ft_markets": "https://www.ft.com/markets?format=rss",
    "rss_ft_world": "https://www.ft.com/world?format=rss",
    "rss_bloomberg_markets": "https://www.bloomberg.com/feeds/markets/news.rss",
}
# Cross-asset price snapshots (#254), every 5 min. Yahoo for the CME futures and ICE's dollar
# index; CBOE for the indices it computes (VIX, TNX = 10 x the 10-year yield).
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=1m&range=1d"
YAHOO_SNAPSHOTS = {"px_es": "ES%3DF", "px_nq": "NQ%3DF", "px_dxy": "DX-Y.NYB"}
CBOE_QUOTE_URL = "https://cdn-api.cboe.com/api/global/delayed_quotes/quotes/%s.json"
CBOE_SNAPSHOTS = {"px_vix": "_VIX", "px_tnx": "_TNX"}
PX_INTERVAL_S = 300


def _spec(key, url, interval_s, parse, list_feed=True, binance=False, method="GET",
          body=None, headers=JSON_HEADERS, backfill=None, min_gap_s=0.0):
    return SourceSpec(key, method, url, body, dict(headers), interval_s, list_feed, binance,
                      parse, backfill, min_gap_s)


def _pages(key, urls, interval_s, parse, min_gap_s=0.0):
    return lambda: [_spec(key, u, interval_s, parse, min_gap_s=min_gap_s) for u in urls]


def _build():
    s = {}
    s["tree"] = _spec("tree", TREE_URL % 200, 60, parse_tree,
                      backfill=_pages("tree", [TREE_URL % 2000], 60, parse_tree))
    for key, cat in BINANCE_CATALOGS.items():
        s[key] = _spec(key, "%s?type=1&pageNo=1&pageSize=20&catalogId=%d" % (CMS_URL, cat),
                       BINANCE_INTERVAL_S, parse_binance, binance=True,
                       headers=BINANCE_HEADERS)
    s["upbit"] = _spec("upbit", UPBIT_URL % 1, 120, parse_upbit, min_gap_s=8.0,
                       backfill=_pages("upbit", [UPBIT_URL % p for p in (2, 3, 4)], 120,
                                       parse_upbit, min_gap_s=8.0))
    for key, ann in (("okx_listings", "announcements-new-listings"),
                     ("okx_delistings", "announcements-delistings")):
        url = OKX_URL % ann
        s[key] = _spec(key, url, 300, parse_okx, backfill=_pages(
            key, ["%s&page=%d" % (url, p) for p in (2, 3, 4)], 300, parse_okx))
    s["hyperliquid_universe"] = _spec(
        "hyperliquid_universe", "https://api.hyperliquid.xyz/info", 300, parse_hl_meta,
        list_feed=False, method="POST", body=b'{"type":"meta"}',
        headers={**JSON_HEADERS, "Content-Type": "application/json"})
    for key, url in RSS_FEEDS.items():
        s[key] = _spec(key, url, 300, parse_feed, headers=FEED_HEADERS)
    s["ff_calendar"] = _spec("ff_calendar",
                             "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                             6 * 3600, parse_ff_calendar, list_feed=False)
    s["fear_greed"] = _spec("fear_greed", "https://api.alternative.me/fng/?limit=1", 3600,
                            parse_fear_greed, list_feed=False)
    for key, sym in YAHOO_SNAPSHOTS.items():
        s[key] = _spec(key, YAHOO_CHART_URL % sym, PX_INTERVAL_S, parse_yahoo_chart,
                       list_feed=False)
    for key, sym in CBOE_SNAPSHOTS.items():
        s[key] = _spec(key, CBOE_QUOTE_URL % sym, PX_INTERVAL_S, parse_cboe_quote,
                       list_feed=False)
    return s


SOURCES = _build()
