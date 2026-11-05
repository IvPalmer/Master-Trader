"""Venue reads and pure pricing for the forward monitor (#229). It places no orders, holds no keys.

Hyperliquid: the nes_venues.HlClient (reused by import) paced at one info request per second,
with a 429 backoff. Binance 1m klines for the pre-t0 market and leak test, and Upbit's market
list for the audit, go through na_fetch (bounded HTTP). Prices are Decimal from the venue strings;
records store them as strings.
"""
import hashlib
import json
import time
from decimal import ROUND_HALF_EVEN, Decimal

import uff_common as uc
import na_fetch
import na_sources
import nes_returns as nr
import nes_util as nu
import nes_venues as nv

FETCH_DEADLINE_S = 20
BINANCE_KLINES = {"um": "https://fapi.binance.com/fapi/v1/klines",
                  "spot": "https://api.binance.com/api/v3/klines"}
BINANCE_INVALID_SYMBOL = -1121
BINANCE_GAP_S = 0.25
UPBIT_MARKETS_URL = "https://api.upbit.com/v1/market/all?is_details=true"


def bounded_fetch(req):
    return na_fetch.fetch(req, timeout_s=10, deadline=time.monotonic() + FETCH_DEADLINE_S)


# --- Hyperliquid -----------------------------------------------------------------------

class Hyperliquid(nv.HlClient):
    """nes_venues.HlClient at one request per `gap_s`. A 429 opens an exponential backoff during
    which requests fail fast (no request is sent); the scheduler retries on a later tick, so a
    429 never blocks the loop. `wall` is in seconds, as in HlClient."""

    def __init__(self, fetcher, sleep, wall, gap_s=uc.HL_GAP_S):
        super().__init__(fetcher, sleep, wall)
        self.gap_s, self.backoff_until, self.n429 = gap_s, None, 0

    def _send(self, req):
        if self.backoff_until is not None and self.wall() < self.backoff_until:
            return None
        if self.last_request is not None:
            wait = self.gap_s - (self.wall() - self.last_request)
            if wait > 0:
                self.sleep(wait)
        self.last_request = self.wall()
        try:
            resp = self.fetcher(req)
        except na_fetch.FetchError:
            return None
        if resp.status == 429:
            self.n429 += 1
            self.backoff_until = self.wall() + min(uc.HL_BACKOFF_MAX_S,
                                                   uc.HL_BACKOFF_S * 2 ** (self.n429 - 1))
            return None
        self.n429, self.backoff_until = 0, None
        return resp

    def now_ms(self):
        return int(self.wall() * 1000)

    def info(self, body, accept):
        """POST /info; `accept(json)` returns a value or raises. ValueError after the attempts."""
        req = nu.Req("POST", nv.HL_INFO_URL, json.dumps(body).encode(), nv.HL_HEADERS)

        def ok(resp):
            if resp.status != 200:
                raise ValueError(resp.status)
            try:
                return accept(json.loads(resp.body))
            except (KeyError, TypeError, IndexError, AttributeError, ArithmeticError) as e:
                raise ValueError("malformed answer: %s" % e) from e
        return self._attempts(req, ok)

    def book(self, coin):
        return self.info({"type": "l2Book", "coin": coin},
                         lambda j: {**parse_book(j), "recv_ms": self.now_ms()})

    def oracle_prices(self, coins):
        """{coin: oraclePx} from metaAndAssetCtxs, and the receipt time."""
        def accept(j):
            meta, ctxs = j
            names = [u["name"] for u in meta["universe"]]
            px = {n: c.get("oraclePx") for n, c in zip(names, ctxs) if n in coins}
            return {k: v for k, v in px.items() if v is not None}, self.now_ms()
        return self.info({"type": "metaAndAssetCtxs"}, accept)

    def funding_history(self, coin, start_ms, end_ms):
        def accept(j):
            if not isinstance(j, list):
                raise ValueError("fundingHistory answer is not a list")
            return [(int(r["time"]), str(r["fundingRate"])) for r in j]
        return self.info({"type": "fundingHistory", "coin": coin, "startTime": int(start_ms),
                          "endTime": int(end_ms)}, accept)

    def candles(self, coin, start_ms, end_ms):
        def accept(j):
            if not isinstance(j, list):
                raise ValueError("candleSnapshot answer is not a list")
            return {int(c["t"]): [c["o"], c["h"], c["l"], c["c"]] for c in j}
        return self.info({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1m",
                                                            "startTime": int(start_ms),
                                                            "endTime": int(end_ms)}}, accept)


def parse_book(j):
    bids, asks = j["levels"]
    side = lambda levels: [(Decimal(l["px"]), Decimal(l["sz"])) for l in levels]   # noqa: E731
    return {"time": int(j["time"]), "bids": side(bids), "asks": side(asks)}


def sz_decimals(meta_body, coin):
    for u in json.loads(meta_body)["universe"]:
        if u.get("name") == coin:
            return int(u["szDecimals"])
    return None


# --- book walk (pure) ------------------------------------------------------------------

def quantize(q, decimals):
    """An exchange-valid size: rounded half-even to szDecimals, as Python's round() in the SDK."""
    return q.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_EVEN)


def size_for_notional(levels, notional, decimals):
    """The size whose sale into `levels` (best first) raises `notional`, rounded to szDecimals;
    None when the side holds less than `notional`."""
    acc_n = acc_q = Decimal(0)
    for px, sz in levels:
        if acc_n + px * sz >= notional:
            return quantize(acc_q + (notional - acc_n) / px, decimals)
        acc_n += px * sz
        acc_q += sz
    return None


def walk(levels, q):
    """(VWAP, [[px, size taken], ...]) of taking `q` from `levels`; None when depth < q."""
    left, cost, used = q, Decimal(0), []
    for px, sz in levels:
        if left <= 0:
            break
        take = min(sz, left)
        cost += take * px
        left -= take
        used.append([str(px), str(take)])
    if left > 0:
        return None
    return cost / q, used


def fill(book, side, q=None, notional=None, decimals=None):
    """One book walk at the book's receipt time: `sell` takes the bids, `buy` the asks.

    With `notional` it sizes the sale first and freezes q; with `q` it trades q. Returns
    (record, None), or (None, reason) for a rejected attempt: stale_book (older than 5 s),
    empty_side, thin_book (depth below q) or zero_size."""
    age = book["recv_ms"] - book["time"]
    if age > uc.BOOK_MAX_AGE_MS:
        return None, "stale_book"
    if not book["bids"] or not book["asks"]:
        return None, "empty_side"
    levels = book["bids"] if side == "sell" else book["asks"]
    if q is None:
        q = size_for_notional(levels, notional, decimals)
        if q is None:
            return None, "thin_book"
    if q <= 0:
        return None, "zero_size"
    walked = walk(levels, q)
    if walked is None:
        return None, "thin_book"
    vwap, used = walked
    best_bid, best_ask = book["bids"][0][0], book["asks"][0][0]
    notional_done = q * vwap
    return {"side": side, "q": str(q), "vwap": str(vwap), "notional": str(notional_done),
            "fee": str(fee(notional_done)), "mid": str((best_bid + best_ask) / 2),
            "best_bid": str(best_bid), "best_ask": str(best_ask), "levels_used": len(used),
            "levels": used, "book_ms": book["time"], "obs_ms": book["recv_ms"],
            "book_age_ms": age}, None


def fee(notional):
    return notional * uc.FEE_BPS / 10_000


# --- funding (pure) --------------------------------------------------------------------

def boundaries(entry_ms, exit_ms):
    """The hourly settlements a position held over (entry, exit] pays or receives."""
    h = (entry_ms // uc.HOUR_MS + 1) * uc.HOUR_MS
    out = []
    while h <= exit_ms:
        out.append(h)
        h += uc.HOUR_MS
    return out


def rates_by_hour(records):
    """fundingHistory (time, rate) -> {settlement hour: rate}; record times sit a few ms past it."""
    return {(t + uc.HOUR_MS // 2) // uc.HOUR_MS * uc.HOUR_MS: rate for t, rate in records}


def funding(q, entry_ms, exit_ms, rates, oracle):
    """Estimated funding cashflow of a short of `q`: q x oraclePx x rate per settlement, positive
    when funding is positive (longs pay shorts). `oracle` = {hour: (obs_ms, px)}; an observation
    more than 60 s from its hour does not count. Any boundary without a rate or an observation
    makes the event's funding `missing`."""
    rows, missing, total = [], [], Decimal(0)
    for h in boundaries(entry_ms, exit_ms):
        rate, obs = rates.get(h), oracle.get(h)
        if obs is not None and abs(obs[0] - h) > uc.ORACLE_TOL_MS:
            obs = None
        if rate is None or obs is None:
            missing.append({"hour_ms": h, "rate": rate is not None, "oracle": obs is not None})
            continue
        cash = q * Decimal(obs[1]) * Decimal(rate)
        total += cash
        rows.append({"hour_ms": h, "rate": rate, "oracle_px": obs[1], "oracle_obs_ms": obs[0],
                     "cashflow": str(cash)})
    return {"status": "missing" if missing else "complete", "estimated": True,
            "boundaries": rows, "missing": missing, "n_boundaries": len(rows) + len(missing),
            "cashflow": None if missing else str(total), "partial_cashflow": str(total)}


# --- outcome and excursion (pure) ------------------------------------------------------

def net(entry, exit_, funding_rec):
    """Short P&L of one event in USDC and as a return on the entry notional."""
    q, e, x = Decimal(entry["q"]), Decimal(entry["vwap"]), Decimal(exit_["vwap"])
    entry_n, exit_n = q * e, q * x
    gross = q * (e - x)
    fees = fee(entry_n) + fee(exit_n)
    fund = None
    if funding_rec is not None and funding_rec.get("status") == "complete":
        fund = Decimal(funding_rec["cashflow"])
    net_pnl = None if fund is None else gross - fees + fund
    return {"entry_notional": str(entry_n), "exit_notional": str(exit_n), "gross_pnl": str(gross),
            "fees": str(fees), "funding": None if fund is None else str(fund),
            "net_pnl": None if net_pnl is None else str(net_pnl),
            "gross_return": str(gross / entry_n),
            "net_ex_funding_return": str((gross - fees) / entry_n),
            "net_return": None if net_pnl is None else str(net_pnl / entry_n)}


def mark_return(entry, mark):
    """A checkpoint mark of q, net of both legs' fees, funding excluded (descriptive)."""
    q, e, m = Decimal(entry["q"]), Decimal(entry["vwap"]), Decimal(mark["vwap"])
    return str((q * (e - m) - fee(q * e) - fee(q * m)) / (q * e))


def excursion(rows, entry_ms, exit_ms, entry_vwap):
    """Descriptive price excursion of a short from 1m candles lying wholly inside the hold:
    MAE = max high / entry - 1, MFE = 1 - min low / entry (both floored at 0)."""
    first = -(-entry_ms // uc.MINUTE_MS) * uc.MINUTE_MS
    keys = [k for k in sorted(rows) if k >= first and k + uc.MINUTE_MS <= exit_ms]
    expected = max(0, (exit_ms - first) // uc.MINUTE_MS)
    if not keys:
        return {"status": "missing", "candles": 0, "expected": expected}
    e = Decimal(entry_vwap)
    high = max(Decimal(rows[k][1]) for k in keys)
    low = min(Decimal(rows[k][2]) for k in keys)
    return {"status": "ok", "descriptive": True, "candles": len(keys), "expected": expected,
            "max_high": str(high), "min_low": str(low),
            "mae": str(max(Decimal(0), high / e - 1)), "mfe": str(max(Decimal(0), 1 - low / e))}


# --- Binance klines --------------------------------------------------------------------

def kline_req(market, symbol, start_ms, end_ms):
    url = "%s?symbol=%s&interval=1m&startTime=%d&endTime=%d" % (BINANCE_KLINES[market], symbol,
                                                                 start_ms, end_ms)
    return nu.Req("GET", url, None, dict(na_sources.JSON_HEADERS))


def parse_klines(body):
    data = json.loads(body)
    if not isinstance(data, list):
        raise ValueError("klines answer is not a list")
    return {int(k[0]): [str(k[1]), str(k[2]), str(k[3]), str(k[4])] for k in data}


def _invalid_symbol(resp):
    if resp.status != 400:
        return False
    try:
        return json.loads(resp.body).get("code") == BINANCE_INVALID_SYMBOL
    except (ValueError, AttributeError):
        return False


def binance_facts(token, t0_ms, fetcher, sleep):
    """The first Part C proxy candidate (USDⓈ-M, then spot; nes_venues.binance_candidates) whose
    1m klines show trading in [t0 - 10 min, t0), and the Part C leak test on those closes
    (nes_returns.leaked: |close(t0-2m) / close(t0-10m) - 1| > 2%). None when a read fails before
    a candidate answers, so a failed USDⓈ-M read never falls through to spot."""
    start, end = uc.floor_minute(t0_ms - uc.MARKET_WINDOW_MS), t0_ms - 1
    tried = []
    for market, symbol in nv.binance_candidates(token, t0_ms):
        sleep(BINANCE_GAP_S)
        try:
            resp = fetcher(kline_req(market, symbol, start, end))
        except na_fetch.FetchError:
            return None
        if _invalid_symbol(resp):
            tried.append([market, symbol, "invalid_symbol"])
            continue
        if resp.status != 200:
            return None
        try:
            rows = {k: v for k, v in parse_klines(resp.body).items() if start <= k < t0_ms}
        except (ValueError, IndexError, TypeError):
            return None
        if not rows:
            tried.append([market, symbol, "no_klines"])
            continue
        return {"market_pre_t0": True, "market": market, "symbol": symbol, "candles": len(rows),
                "leaked": nr.leaked(rows, t0_ms),
                "close_t0_10m": nr.price_at(rows, t0_ms + nr.LEAK_FROM_MS),
                "close_t0_2m": nr.price_at(rows, t0_ms + nr.LEAK_TO_MS), "tried": tried}
    return {"market_pre_t0": False, "market": None, "symbol": None, "leaked": None, "tried": tried}


# --- Upbit market list -----------------------------------------------------------------

def upbit_req():
    return nu.Req("GET", UPBIT_MARKETS_URL, None, dict(na_sources.JSON_HEADERS))


def parse_markets(body):
    data = json.loads(body)
    if not isinstance(data, list) or not data:
        raise ValueError("market/all answer is not a non-empty list")
    return sorted({m["market"] for m in data if isinstance(m, dict) and isinstance(m.get("market"), str)})


def markets_sha(markets):
    return hashlib.sha256("\n".join(markets).encode("utf-8")).hexdigest()


def krw_tokens(markets):
    return {m[4:] for m in markets if m.startswith("KRW-")}
