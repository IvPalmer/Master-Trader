"""Network-free fakes for the Upbit fade forward monitor tests (#229).

The archive is a real na_store schema in a temp dir with its writer connection open, as on
the VPS. Hyperliquid, Binance and Upbit answer from in-memory scripts; the clock is fake, and
sleeping advances it.
"""
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research" / "upbit_fade_forward"))

import uff_common as uc  # noqa: E402  (puts the Part A and Part C modules on sys.path)
import uff_monitor as um  # noqa: E402
import uff_venues as uv  # noqa: E402
import na_fetch  # noqa: E402
import na_sources  # noqa: E402
import na_store  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "upbit_fade_forward"
MIN, H, D = uc.MINUTE_MS, uc.HOUR_MS, uc.DAY_MS
CARDS_URL = "https://upbit.com/service_center/notice?id=1793858584730"
CARDS_TITLE = "콜렉터크립트(CARDS) 신규 거래지원 안내 (KRW, BTC, USDT 마켓)"
ENJ_TITLE = "엔진코인(ENJ) 입출금 일시 중단 안내 (11/09 20:00 ~)"
MAINT_TITLE = "서버 점검 안내 (11/09 02:00 ~)"
# 2026-11-10T06:03:04.912Z: the real CARDS notice time moved five days on.
T0 = 1793858584912 + 5 * D


def fixture(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def resp(status, body):
    if not isinstance(body, bytes):
        body = json.dumps(body).encode()
    return na_fetch.Response(status, body, {})


class Clock:
    def __init__(self, ms):
        self.ms = int(ms)
        self.sleeps = []

    def wall_ms(self):
        return self.ms

    def wall_s(self):
        return self.ms / 1000

    def sleep(self, s):
        self.sleeps.append(s)
        self.ms += int(round(s * 1000))

    def to(self, ms):
        self.ms = max(self.ms, int(ms))


class Archive:
    def __init__(self, path):
        self.path = Path(path)
        self.conn = na_store.connect(str(self.path))

    def tree(self, items, received_ms, after_gap=False):
        parsed = na_sources.parse_tree(json.dumps(items, ensure_ascii=False).encode())
        return na_store.upsert_items(self.conn, "tree", parsed, uc.iso(received_ms), after_gap)

    def binance(self, sid, title, published_ms, received_ms):
        item = na_store.Item(str(sid), uc.iso(published_ms), title, None,
                             "https://www.binance.com/en/support/announcement/x%s" % sid, None,
                             {"id": sid, "title": title, "releaseDate": published_ms})
        return na_store.upsert_items(self.conn, "binance_listing", [item], uc.iso(received_ms), False)

    def other(self, items, received_ms):
        """A non-Upbit Tree record (a tweet)."""
        return self.tree(items, received_ms)


def tree_item(_id, title, url=CARDS_URL, time_ms=T0, body=None):
    x = {"_id": _id, "title": title, "source": "Upbit", "url": url, "time": time_ms,
         "symbols": [], "kind": "listing", "venue": "upbit"}
    if body is not None:
        x["body"] = body
    return x


def book(coin, now_ms, mid="1.0", step="0.001", sizes=(60, 60, 60, 60, 60), age_ms=0):
    """Symmetric book around `mid`; level i sits i+1 steps from it."""
    m, s = Decimal(mid), Decimal(step)
    bids = [{"px": str(m - s * (i + 1)), "sz": str(z), "n": 1} for i, z in enumerate(sizes)]
    asks = [{"px": str(m + s * (i + 1)), "sz": str(z), "n": 1} for i, z in enumerate(sizes)]
    return {"coin": coin, "time": now_ms - age_ms, "levels": [bids, asks]}


class FakeHl:
    """Hyperliquid /info. `funding[coin]` = [(time ms, rate)], hourly records a few ms past the
    hour; a coin absent from it answers HTTP 500 `null`, as Hyperliquid does."""

    def __init__(self, clock):
        self.clock = clock
        self.universe = [{"name": "BTC", "szDecimals": 5}, {"name": "CARDS", "szDecimals": 0}]
        self.funding = {}
        self.mid = {"CARDS": "1.0", "BTC": "80000"}
        self.oracle = {"CARDS": "1.0", "BTC": "80000"}
        self.book_fn = None            # (coin, now_ms) -> book json, overrides `mid`
        self.candle_keep = None        # (open ms) -> bool: drop candles from candleSnapshot
        self.fail = set()              # request types answered HTTP 500
        self.n429 = 0
        self.requests = []

    def __call__(self, req):
        body = json.loads(req.body)
        self.requests.append((self.clock.ms, body))
        kind = body["type"]
        if self.n429:
            self.n429 -= 1
            return resp(429, b"")
        if kind in self.fail:
            return resp(500, b"error")
        if kind == "meta":
            return resp(200, {"universe": self.universe})
        if kind == "fundingHistory":
            coin = body["coin"]
            if coin not in self.funding:
                return resp(500, b"null")
            return resp(200, [{"coin": coin, "fundingRate": r, "premium": "0", "time": t}
                              for t, r in self.funding[coin]
                              if body["startTime"] <= t <= body["endTime"]])
        if kind == "l2Book":
            coin = body["coin"]
            if self.book_fn is not None:
                return resp(200, self.book_fn(coin, self.clock.ms))
            return resp(200, book(coin, self.clock.ms, mid=self.mid[coin]))
        if kind == "metaAndAssetCtxs":
            return resp(200, [{"universe": self.universe},
                              [{"oraclePx": self.oracle.get(u["name"], "1.0"), "funding": "0"}
                               for u in self.universe]])
        if kind == "candleSnapshot":
            r = body["req"]
            start = r["startTime"] - r["startTime"] % MIN
            out = []
            for t in range(start, r["endTime"] + 1, MIN):
                if self.candle_keep is not None and not self.candle_keep(t):
                    continue
                px = Decimal(self.mid.get(r["coin"], "1.0"))
                out.append({"t": t, "T": t + MIN - 1, "s": r["coin"], "i": "1m", "o": str(px),
                            "c": str(px), "h": str(px * Decimal("1.05")),
                            "l": str(px * Decimal("0.9")), "v": "1", "n": 1})
            return resp(200, out)
        raise AssertionError("unexpected Hyperliquid request %r" % body)

    def hourly(self, coin, start_ms, end_ms, rate="0.0000125"):
        h = start_ms - start_ms % H
        self.funding[coin] = [(t + 7, rate) for t in range(h, end_ms + 1, H)]

    def count(self, kind):
        return sum(1 for _, b in self.requests if b["type"] == kind)


def klines(start_ms, end_ms, close_fn):
    """Binance 1m kline arrays with open in [start, end]."""
    out = []
    t = start_ms - start_ms % MIN
    while t <= end_ms:
        c = close_fn(t)
        out.append([t, c, c, c, c, "10", t + MIN - 1, "10", 5, "5", "5", "0"])
        t += MIN
    return out


class FakeHttp:
    """Binance klines and Upbit market/all. `klines[(market, symbol)]` = close_fn(open ms), a
    status int, or absent (invalid symbol). `listed_from[symbol]` (or `[(market, symbol)]`) =
    first kline open ms."""

    def __init__(self, clock):
        self.clock = clock
        self.markets_fn = lambda now: ["KRW-BTC", "KRW-ETH", "BTC-BTT"]
        self.klines = {}
        self.listed_from = {}
        self.upbit_status = 200
        self.requests = []

    def __call__(self, req):
        url = req.url
        self.requests.append((self.clock.ms, url))
        if "market/all" in url:
            if self.upbit_status != 200:
                return resp(self.upbit_status, b"")
            return resp(200, [{"market": m, "korean_name": "x", "english_name": "x"}
                              for m in self.markets_fn(self.clock.ms)])
        market = "um" if "fapi.binance.com" in url else "spot"
        q = dict(p.split("=") for p in url.split("?", 1)[1].split("&"))
        script = self.klines.get((market, q["symbol"]))
        if script is None:
            return resp(400, {"code": -1121, "msg": "Invalid symbol."})
        if isinstance(script, int):
            return resp(script, b"")
        listed = self.listed_from.get((market, q["symbol"]), self.listed_from.get(q["symbol"], 0))
        start = max(int(q["startTime"]), listed)
        return resp(200, klines(start, int(q["endTime"]), script))

    def count(self, needle):
        return sum(1 for _, u in self.requests if needle in u)


def flat(px="1.0"):
    return lambda t: px


class Scenario:
    """One CARDS listing: the monitor starts an hour before t0, polls Upbit every 5 min, and
    Tree relays the notice 39 s after t0. Knobs are plain attributes."""

    def __init__(self, tmp, t0=T0, body=None, title=CARDS_TITLE):
        self.tmp = Path(tmp)
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.t0 = t0
        self.clock = Clock(t0 - H)
        self.archive = Archive(self.tmp / "archive.sqlite")
        self.archive.other([{"_id": "tw1", "title": "a tweet", "url": "https://x.com/a/1",
                             "time": t0 - 2 * H, "source": "Twitter"}], t0 - 2 * H)
        self.hl = FakeHl(self.clock)
        self.hl.hourly("CARDS", t0 - 2 * D, t0 + 3 * D)
        self.http = FakeHttp(self.clock)
        self.http.klines[("um", "CARDSUSDT")] = flat("1.0")
        self.body, self.title = body, title
        self.data = self.tmp / "data"
        self.mon = self.new_monitor()

    def new_monitor(self):
        client = uv.Hyperliquid(self.hl, self.clock.sleep, self.clock.wall_s)
        self.mon = um.Monitor(self.data, self.archive.path, client, self.http, self.clock.wall_ms,
                              self.clock.sleep)
        return self.mon

    def publish(self, received_ms=None, published_ms=None, _id="1793858584912CKBU", url=CARDS_URL):
        """Tree relays the notice: the archive stores it at `received_ms` (the clock moves there)."""
        received = self.t0 + 39_000 if received_ms is None else received_ms
        self.clock.to(received)
        self.archive.tree([tree_item(_id, self.title, url=url, body=self.body,
                                     time_ms=self.t0 if published_ms is None else published_ms)],
                          received)

    def run(self, until_ms, every_ms=30_000):
        while self.clock.ms < until_ms:
            self.mon.tick()
            self.clock.to(min(until_ms, self.clock.ms + every_ms))
        self.mon.tick()

    def eid(self, token="CARDS"):
        return "upbit:1793858584730:%s" % token

    def rec(self, prefix, token="CARDS"):
        return self.mon.ledger.get("%s:%s" % (prefix, self.eid(token)))
