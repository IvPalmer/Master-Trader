"""Part C venue evidence (#229): Hyperliquid funding records (O5) and Binance files (O6, O7).

Only timestamps and file existence are read here. Funding rates and prices are discarded.
"""
import json

import nes_util as nu
import na_fetch
import na_sources

HL_EVIDENCE = "fundingHistory"          # frozen in all three entries (C1 option A)
HL_INFO_URL = "https://api.hyperliquid.xyz/info"
HL_HEADERS = {**na_sources.JSON_HEADERS, "Content-Type": "application/json"}
HL_LOOKBACK_MS = 86_400_000
HL_LAST_MS = 3_600_000
HL_GAP_S = 20.0
HL_429_PAUSE_S = 600.0
HL_ATTEMPTS = 3

PROBE_GAP_S = 0.5                       # at most 2 requests/s
PROBE_RETRY_S = 5.0
PROBE_ATTEMPTS = 3

UM_PREFIXES = ("", "1000", "1000000", "1M")
SPOT_PREFIXES = ("", "1000", "1M")

# token -> {"binance": base | None, "hl": coin | None, "from": "YYYY-MM-DD", "source": notice id}
ALIASES = {}


class VenueAborted(Exception):
    pass


class ProbeError(Exception):
    pass


# --- Hyperliquid ---------------------------------------------------------------

def hl_meta_index(body):
    universe = json.loads(body)["universe"]
    return {u["name"].upper(): {"name": u["name"], "delisted": bool(u.get("isDelisted", False))}
            for u in universe if ":" not in u["name"]}


def hl_names(token, index):
    names = [index[n]["name"] for n in (token.upper(), ("k" + token).upper()) if n in index]
    alias = ALIASES.get(token, {}).get("hl")
    if alias and alias not in names:
        names.append(alias)
    return names


def hl_evidence_request(coin, t0_ms):
    body = {"type": HL_EVIDENCE, "coin": coin, "startTime": t0_ms - HL_LOOKBACK_MS,
            "endTime": t0_ms - 1}
    return nu.Req("POST", HL_INFO_URL, json.dumps(body).encode(), HL_HEADERS)


def hl_evidence_times(body):
    records = json.loads(body)
    if not isinstance(records, list):
        raise ValueError("fundingHistory answer is not a list")
    times = []
    for r in records:
        t = r.get("time") if isinstance(r, dict) else None
        if type(t) is not int:
            raise ValueError("record without an integer time")
        times.append(t)
    return times


def hl_status(times, t0_ms):
    if times is None:
        return "unknown"
    window = [t for t in times if t0_ms - HL_LOOKBACK_MS <= t < t0_ms]
    if window and any(t >= t0_ms - HL_LAST_MS for t in window):
        return "eligible"
    return "ineligible"


class HlClient:
    """Paced Hyperliquid info client: one request per HL_GAP_S; one 429 pause per run."""

    def __init__(self, fetcher, sleep, wall):
        self.fetcher, self.sleep, self.wall = fetcher, sleep, wall
        self.last_request = None
        self.paused_429 = False

    def _send(self, req):
        if self.last_request is not None:
            wait = HL_GAP_S - (self.wall() - self.last_request)
            if wait > 0:
                self.sleep(wait)
        self.last_request = self.wall()
        try:
            return self.fetcher(req)
        except na_fetch.FetchError:
            return None

    def _attempts(self, req, accept):
        """`accept(resp)` returns a value, or raises ValueError for a failed answer."""
        for _ in range(HL_ATTEMPTS):
            resp = self._send(req)
            if resp is not None and resp.status == 429:
                if self.paused_429:
                    raise VenueAborted("Hyperliquid answered 429 twice")
                self.paused_429 = True
                self.sleep(HL_429_PAUSE_S)
                resp = self._send(req)
                if resp is not None and resp.status == 429:
                    raise VenueAborted("Hyperliquid answered 429 twice")
            if resp is None:
                continue
            try:
                return accept(resp)
            except ValueError:
                continue
        raise ValueError("no usable answer after %d attempts" % HL_ATTEMPTS)

    def meta(self):
        req = nu.Req("POST", HL_INFO_URL, json.dumps({"type": "meta"}).encode(), HL_HEADERS)

        def accept(resp):
            if resp.status != 200:
                raise ValueError(resp.status)
            hl_meta_index(resp.body)
            return resp.body
        try:
            return self._attempts(req, accept)
        except (ValueError, KeyError, TypeError) as e:
            raise VenueAborted("Hyperliquid meta unavailable: %s" % e) from e

    def evidence(self, coin, t0_ms, absent_from_meta=False):
        """Evidence times for `coin`, or None when they cannot be fetched (O5).

        For a name absent from today's meta, HTTP 500 with body `null` means no records,
        and any other failure stops the build.
        """
        def accept(resp):
            if absent_from_meta and resp.status == 500 and resp.body.strip() == b"null":
                return []
            if resp.status != 200:
                raise ValueError(resp.status)
            return hl_evidence_times(resp.body)
        try:
            return self._attempts(hl_evidence_request(coin, t0_ms), accept)
        except ValueError as e:
            if absent_from_meta:
                raise VenueAborted("Hyperliquid %s for %s failed: %s" % (HL_EVIDENCE, coin, e)) from e
            return None


def hl_facts(token, t0_ms, index, client):
    names = hl_names(token, index)
    if not names:
        times = client.evidence(token, t0_ms, absent_from_meta=True)
        if not times:
            return {"status": "ineligible", "coin": token, "reason": "never_in_meta"}
        return _facts(token, hl_status(times, t0_ms))
    results = [(name, hl_status(client.evidence(name, t0_ms), t0_ms)) for name in names]
    for name, status in results:
        if status == "eligible":
            return _facts(name, status)
    for name, status in results:
        if status == "unknown":
            return _facts(name, status)
    return _facts(names[0], "ineligible")


def _facts(coin, status):
    reason = {"eligible": "funding_records", "ineligible": "no_recent_funding",
              "unknown": "fetch_failed"}[status]
    return {"status": status, "coin": coin, "reason": reason}


# --- Binance -------------------------------------------------------------------

def _base(token, t0_ms):
    alias = ALIASES.get(token)
    if alias and alias.get("binance") and nu.utc_date(t0_ms) >= alias["from"]:
        return alias["binance"]
    return token


def binance_candidates(token, t0_ms):
    base = _base(token, t0_ms)
    return ([("um", p + base + "USDT") for p in UM_PREFIXES]
            + [("spot", p + base + "USDT") for p in SPOT_PREFIXES])


def kline_url(market, symbol, date):
    root = {"um": "futures/um", "spot": "spot"}[market]
    return ("https://data.binance.vision/data/%s/daily/klines/%s/1m/%s-1m-%s.zip"
            % (root, symbol, symbol, date))


class FileProbe:
    """HEAD-only existence checks on data.binance.vision, cached per URL."""

    def __init__(self, fetcher, sleep):
        self.fetcher, self.sleep, self.cache = fetcher, sleep, {}

    def exists(self, url):
        if url in self.cache:
            return self.cache[url]
        last = None
        for attempt in range(PROBE_ATTEMPTS):
            if attempt:
                self.sleep(PROBE_RETRY_S)
            self.sleep(PROBE_GAP_S)
            try:
                resp = self.fetcher(nu.Req("HEAD", url, None, {"User-Agent": na_sources.UA}))
            except na_fetch.FetchError as e:
                last = e
                continue
            if resp.status == 200:
                self.cache[url] = True
                return True
            if resp.status in (403, 404):
                self.cache[url] = False
                return False
            last = resp.status
        raise ProbeError("%s: no answer after %d attempts (%s)" % (url, PROBE_ATTEMPTS, last))


def binance_facts(token, t0_ms, probe):
    day = lambda k: nu.utc_date(t0_ms + k * nu.DAY_MS)   # noqa: E731
    pre, full = day(-1), [day(k) for k in range(-1, 3)]
    candidates = binance_candidates(token, t0_ms)
    has = lambda c, d: probe.exists(kline_url(c[0], c[1], d))   # noqa: E731
    present_pre = [c for c in candidates if has(c, pre)]
    spot = next((c[1] for c in present_pre if c[0] == "spot"), None)
    proxy = next(({"market": c[0], "symbol": c[1], "tier": "full"} for c in present_pre
                  if all(has(c, d) for d in full)), None)
    if proxy is None:
        proxy = next(({"market": c[0], "symbol": c[1], "tier": "entry"} for c in present_pre
                      if has(c, day(0))), None)
    return {"on_binance_pre_t0": bool(present_pre), "spot_symbol_pre_t0": spot, "proxy": proxy}
