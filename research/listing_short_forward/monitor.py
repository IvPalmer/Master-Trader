#!/usr/bin/env python3
"""listing-short-forward-2026-07 PAPER monitor. Single long-running host-side process.

Prereg listing-short-forward-2026-07 (frozen). Polls Binance CMS 'New Cryptocurrency
Listing' announcements (catalog 48, page 1, pageSize 20) every 60s. On a NEW article whose
title matches a futures/perpetual launch pattern, extracts token symbol(s); for each token
that is available as a Hyperliquid perp it opens a PAPER SHORT:

  entry  = t+60s after release (best BID, crossing, taker 4.5bps), $1000 notional
  snaps  = every 5min until t+4h, then hourly until t+24h
  exits  = paper buy-back at best ASK (taker) at t+4h and t+24h -> net short return

All schedules persist in state.json so a restart resumes pending positions. Failures are
logged and skipped; the loop never crashes. An exit that errors (e.g. HTTP 429 after the
in-call retries) is retried each tick for up to EXIT_RETRY_WINDOW past its due time, so a
rate limit no longer makes a horizon permanently incomplete (#127); the exit row records
both its due time and the actual time. Stdlib only (urllib/json/gzip).

Run modes:
  (default)     long-running monitor (systemd)
  --simulate    inject one fake announcement for an existing HL coin, run the full
                entry/snapshot/exit pipeline synchronously (compressed clock), write
                clearly-marked simulated=true rows, print a trace, exit.
"""
import gzip
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

LS = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(LS, "data")
STATE = os.path.join(LS, "state.json")
EVENTS = os.path.join(DATA, "events.jsonl")
LOG = os.path.join(LS, "monitor.log")

# --- endpoints (VERIFIED working from this VPS) ---
CMS_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
CMS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json",
    "lang": "en",
}
CATALOG_ID = 48
PAGE_SIZE = 20
HL_INFO = "https://api.hyperliquid.xyz/info"
BN_BOOK = "https://api.binance.com/api/v3/ticker/bookTicker"

TIMEOUT = 15
POLL_S = 60
TICK_S = 5                 # scheduler wake cadence
HL_META_TTL = 3600         # cache HL perp universe 1h
RETENTION_DAYS = 120
FEE = 0.00045              # taker, 4.5 bps
NOTIONAL = 1000.0

# --- horizon schedule (seconds, relative to release_ts) ---
ENTRY_OFFSET = 60          # t+60s
SNAP_5M = 300
H4 = 4 * 3600
H24 = 24 * 3600
EXIT_RETRY_WINDOW = 15 * 60  # #127: retry an erroring exit for 15 min past due, then skip


# =====================================================================================
# logging
# =====================================================================================
def log(msg):
    ts = datetime.now(timezone.utc).isoformat()
    line = "%s [listing-monitor] %s" % (ts, msg)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


# =====================================================================================
# http
# =====================================================================================
def _http(url, data=None, headers=None, retries=4):
    backoff = 2.0
    for attempt in range(retries):
        try:
            if data is None:
                req = urllib.request.Request(url, headers=headers or {})
            else:
                h = {"Content-Type": "application/json"}
                if headers:
                    h.update(headers)
                req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=h)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(backoff); backoff *= 2; continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < retries - 1:
                time.sleep(backoff); backoff *= 2; continue
            raise
    raise RuntimeError("unreachable")


def hl_post(body):
    return _http(HL_INFO, data=body)


# =====================================================================================
# announcements (catalog 48, page 1)
# =====================================================================================
def fetch_announcements():
    """Return list of {id, code, title, releaseDate} for page 1 (pageSize 20)."""
    params = urllib.parse.urlencode(
        {"type": 1, "pageNo": 1, "pageSize": PAGE_SIZE, "catalogId": CATALOG_ID})
    j = _http(CMS_URL + "?" + params, headers=CMS_HEADERS)
    if not j or not j.get("success"):
        raise RuntimeError("CMS bad response")
    arts = []
    for c in j.get("data", {}).get("catalogs", []):
        arts.extend(c.get("articles", []) or [])
    return [{"id": a["id"], "code": a.get("code"), "title": a["title"],
             "releaseDate": int(a["releaseDate"])} for a in arts]


# =====================================================================================
# classification (ported from listing_reaction_2026-07/parse_symbols.py — futures branch)
# =====================================================================================
QUOTES = {"USDT", "USDC", "USD", "FDUSD", "TRY", "EUR", "JPY", "BTC", "BNB", "TUSD",
          "BRL", "USD1", "USDⓈ"}
NOISE = QUOTES | {
    "MULTIPLE", "TRADFI", "CONTRACT", "CONTRACTS", "PERPETUAL", "PERP", "WITH", "UP", "TO",
    "LEVERAGE", "AND", "COIN", "COINM", "USDSM", "USDS", "M", "MARGINED", "QUARTERLY",
    "BIQUARTERLY", "NEW", "AI", "VIP", "THE", "A",
}


def futures_syms(t):
    m = re.search(r"(USD[ⓈS]-?M(?:argined)?|COIN-?M)(.*?)(Perp|Perpetual|Quarterly|Contract|Futures)",
                  t, re.I)
    region = m.group(2) if m else t
    syms = []
    for mm in re.finditer(r"\b([A-Z0-9]{2,15})(USDT|USDC|USD)\b", region):
        b = mm.group(1)
        if b.upper() not in NOISE:
            syms.append(b)
    for tok in re.split(r"[,\s]+|and", region):
        tok = tok.strip()
        if re.fullmatch(r"[A-Z0-9]{2,15}", tok) and tok.upper() not in NOISE:
            for q in ("USDT", "USDC", "USD"):
                if tok.endswith(q) and len(tok) > len(q) + 1:
                    tok = tok[: -len(q)]
            syms.append(tok)
    return list(dict.fromkeys(syms))


def is_futures_listing(title):
    """True + symbols for a futures/perpetual LAUNCH title; else False, []."""
    t = title
    # exclude secondary / non-listing announcements
    if re.search(r"HODLer|Launchpool|Super Earn|Simple Earn|Copy Trading|Trading Bots|"
                 r"New Trading Pairs|Options|Convert & Margin|on Earn|Buy Crypto|"
                 r"Tokenized Securities|bStocks|Collateral|Seed Tag Applied.*Earn|"
                 r"Margin (Will Add|Adds)|JPY Spot|Delist|Will Convert|Redenomination", t):
        return False, []
    if re.search(r"Futures.*(Will Launch|Will List)", t) or ("Perpetual" in t and "Futures" in t):
        return True, futures_syms(t)
    return False, []


# =====================================================================================
# HL perp universe (1h cache in state) + symbol alias matching
# =====================================================================================
def hl_meta_names(state):
    now = time.time()
    cache = state.get("hl_meta", {})
    if cache and (now - cache.get("fetched_at", 0)) < HL_META_TTL and cache.get("names"):
        return {n.upper(): n for n in cache["names"]}
    d = hl_post({"type": "meta"})
    names = [u["name"] for u in d["universe"]]
    state["hl_meta"] = {"fetched_at": now, "names": names}
    return {n.upper(): n for n in names}


def hl_aliases(sym):
    """Candidate HL names for a Binance symbol (handles 1000x/1M scaled listings)."""
    s = sym.upper()
    cands = [s]
    stripped = s
    for pre in ("1000", "1M", "1B"):
        if s.startswith(pre):
            stripped = s[len(pre):]
    cands += ["K" + s, "K" + stripped, stripped]
    out = []
    for c in cands:
        if c not in out:
            out.append(c)
    return out


def resolve_hl(sym, names_upper):
    for al in hl_aliases(sym):
        if al in names_upper:
            return names_upper[al]
    return None


# =====================================================================================
# market snapshots
# =====================================================================================
def hl_bbo(coin):
    """(bid, bid_sz, ask, ask_sz) top-of-book, or (None,...) on failure."""
    d = hl_post({"type": "l2Book", "coin": coin})
    levels = d["levels"]
    bids, asks = levels[0], levels[1]
    bid = float(bids[0]["px"]) if bids else None
    bid_sz = float(bids[0]["sz"]) if bids else None
    ask = float(asks[0]["px"]) if asks else None
    ask_sz = float(asks[0]["sz"]) if asks else None
    return bid, bid_sz, ask, ask_sz


def bn_bookticker(symbol):
    """Binance spot bookTicker for SYMBOLUSDT, or None if not spot-listed."""
    try:
        r = _http(BN_BOOK + "?symbol=" + urllib.parse.quote(symbol))
        if isinstance(r, dict) and "bidPrice" in r:
            return {"bid": float(r["bidPrice"]), "bid_sz": float(r["bidQty"]),
                    "ask": float(r["askPrice"]), "ask_sz": float(r["askQty"])}
    except urllib.error.HTTPError as e:
        if e.code in (400, 451):
            return None
        log("bn_bookticker %s http %s" % (symbol, e.code))
    except Exception as e:
        log("bn_bookticker %s err %r" % (symbol, e))
    return None


# =====================================================================================
# state / data io
# =====================================================================================
def load_state():
    if os.path.exists(STATE):
        try:
            with open(STATE) as f:
                s = json.load(f)
        except Exception as e:
            log("state load failed (%r), starting fresh" % e)
            s = {}
    else:
        s = {}
    s.setdefault("seen_ids", [])
    s.setdefault("pending", [])       # list of position dicts
    s.setdefault("hl_meta", {})
    s.setdefault("pos_seq", 0)
    s.setdefault("bootstrapped", False)
    return s


def save_state(state):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, STATE)


def ticks_path(dt):
    return os.path.join(DATA, "ticks_%s.jsonl" % dt.strftime("%Y%m%d"))


def append_jsonl(path, obj):
    with open(path, "a") as f:
        f.write(json.dumps(obj) + "\n")


def write_tick(obj, simulated=False):
    obj = dict(obj)
    obj["simulated"] = simulated
    append_jsonl(ticks_path(datetime.now(timezone.utc)), obj)


# =====================================================================================
# position lifecycle
# =====================================================================================
def build_schedule(release_ts, entry_ts, compressed=False):
    """List of {due_ts, kind, horizon} sorted. compressed=True -> simulate (seconds)."""
    tasks = [{"due_ts": entry_ts, "kind": "entry", "horizon": "entry"}]
    if compressed:
        # squeeze the whole 24h into ~12s so --simulate proves the pipeline live
        base = entry_ts
        tasks.append({"due_ts": base + 2, "kind": "snapshot", "horizon": "s1"})
        tasks.append({"due_ts": base + 4, "kind": "snapshot", "horizon": "s2"})
        tasks.append({"due_ts": base + 6, "kind": "exit", "horizon": "h4"})
        tasks.append({"due_ts": base + 8, "kind": "snapshot", "horizon": "s3"})
        tasks.append({"due_ts": base + 10, "kind": "exit", "horizon": "h24"})
    else:
        # every 5min until t+4h
        t = release_ts + ENTRY_OFFSET
        while t < release_ts + H4:
            if t != entry_ts:
                tasks.append({"due_ts": t, "kind": "snapshot", "horizon": "5m"})
            t += SNAP_5M
        tasks.append({"due_ts": release_ts + H4, "kind": "exit", "horizon": "h4"})
        # hourly until t+24h
        t = release_ts + H4 + 3600
        while t < release_ts + H24:
            tasks.append({"due_ts": t, "kind": "snapshot", "horizon": "1h"})
            t += 3600
        tasks.append({"due_ts": release_ts + H24, "kind": "exit", "horizon": "h24"})
    tasks.sort(key=lambda x: (x["due_ts"], 0 if x["kind"] == "entry" else 1))
    return tasks


def open_position(state, article, symbol, hl_name, release_ts, detected_ts,
                  simulated=False, compressed=False):
    late = (detected_ts - release_ts) > ENTRY_OFFSET
    entry_ts = detected_ts if late else (release_ts + ENTRY_OFFSET)
    state["pos_seq"] += 1
    pid = "P%05d" % state["pos_seq"]
    pos = {
        "position_id": pid,
        "article_id": article["id"],
        "symbol": symbol,
        "hl_name": hl_name,
        "release_ts": release_ts,
        "detected_ts": detected_ts,
        "entry_ts": entry_ts,
        "late_detection": late,
        "simulated": simulated,
        "notional": NOTIONAL,
        "entry_done": False,
        "entry_price": None,
        "size": None,
        "schedule": build_schedule(release_ts, entry_ts, compressed=compressed),
    }
    state["pending"].append(pos)
    log("OPEN %s %s (hl=%s) release=%s detected=%s entry=%s late=%s%s"
        % (pid, symbol, hl_name, release_ts, detected_ts, entry_ts, late,
           " SIMULATED" if simulated else ""))
    return pos


def do_entry(pos):
    bid, bid_sz, ask, ask_sz = hl_bbo(pos["hl_name"])
    if bid is None or bid <= 0:
        log("ENTRY %s %s no bid -> cannot enter, will retry next tick"
            % (pos["position_id"], pos["symbol"]))
        return False
    pos["entry_price"] = bid
    pos["size"] = NOTIONAL / bid
    pos["entry_done"] = True
    bn = bn_bookticker(pos["symbol"] + "USDT")
    write_tick({
        "kind": "entry", "position_id": pos["position_id"], "article_id": pos["article_id"],
        "symbol": pos["symbol"], "hl_name": pos["hl_name"], "ts": int(time.time()),
        "release_ts": pos["release_ts"], "detected_ts": pos["detected_ts"],
        "late_detection": pos["late_detection"], "side": "short", "notional": NOTIONAL,
        "fee": FEE, "hl_bid": bid, "hl_bid_sz": bid_sz, "hl_ask": ask, "hl_ask_sz": ask_sz,
        "entry_price": bid, "size": pos["size"], "bn_spot": bn,
    }, simulated=pos["simulated"])
    log("ENTRY %s %s SHORT @ bid=%s size=%.6f (bn_spot=%s)"
        % (pos["position_id"], pos["symbol"], bid, pos["size"], "yes" if bn else "no"))
    return True


def do_snapshot(pos, horizon):
    bid, bid_sz, ask, ask_sz = hl_bbo(pos["hl_name"])
    bn = bn_bookticker(pos["symbol"] + "USDT")
    unreal = None
    if pos["entry_done"] and ask and ask > 0:
        unreal = (1 - FEE) - (ask / pos["entry_price"]) * (1 + FEE)
    write_tick({
        "kind": "snapshot", "horizon": horizon, "position_id": pos["position_id"],
        "article_id": pos["article_id"], "symbol": pos["symbol"], "hl_name": pos["hl_name"],
        "ts": int(time.time()), "release_ts": pos["release_ts"],
        "hl_bid": bid, "hl_bid_sz": bid_sz, "hl_ask": ask, "hl_ask_sz": ask_sz,
        "entry_price": pos["entry_price"], "unreal_net_return": unreal, "bn_spot": bn,
    }, simulated=pos["simulated"])
    log("SNAP %s %s [%s] bid=%s ask=%s unreal=%s"
        % (pos["position_id"], pos["symbol"], horizon, bid, ask,
           ("%.4f" % unreal) if unreal is not None else "n/a"))


def do_exit(pos, horizon, due_ts=None):
    bid, bid_sz, ask, ask_sz = hl_bbo(pos["hl_name"])
    if not pos["entry_done"]:
        log("EXIT %s %s [%s] skipped (never entered)"
            % (pos["position_id"], pos["symbol"], horizon))
        return
    net = gross = pnl = None
    if ask and ask > 0:
        gross = 1.0 - ask / pos["entry_price"]
        net = (1 - FEE) - (ask / pos["entry_price"]) * (1 + FEE)
        pnl = net * NOTIONAL
    bn = bn_bookticker(pos["symbol"] + "USDT")
    write_tick({
        "kind": "exit", "horizon": horizon, "position_id": pos["position_id"],
        "article_id": pos["article_id"], "symbol": pos["symbol"], "hl_name": pos["hl_name"],
        "ts": int(time.time()), "due_ts": due_ts, "release_ts": pos["release_ts"],
        "side": "buy_to_close",
        "entry_price": pos["entry_price"], "exit_ask": ask, "fee": FEE,
        "gross_short_return": gross, "net_short_return": net, "pnl_usd": pnl,
        "notional": NOTIONAL, "bn_spot": bn,
    }, simulated=pos["simulated"])
    log("EXIT %s %s [%s] buy@ask=%s net_return=%s pnl=%s"
        % (pos["position_id"], pos["symbol"], horizon, ask,
           ("%.4f" % net) if net is not None else "n/a",
           ("%.2f" % pnl) if pnl is not None else "n/a"))


def run_task(pos, task, now_ts=None):
    """Execute one due schedule task; return True if it should be marked done."""
    kind = task["kind"]
    try:
        if kind == "entry":
            return do_entry(pos)          # False -> retry next tick (not done)
        elif kind == "snapshot":
            do_snapshot(pos, task["horizon"])
        elif kind == "exit":
            do_exit(pos, task["horizon"], task["due_ts"])
    except Exception as e:
        now_ts = int(time.time()) if now_ts is None else now_ts
        if kind == "exit" and now_ts - task["due_ts"] <= EXIT_RETRY_WINDOW:
            log("task %s %s [%s] error: %r (retry next tick)"
                % (pos["position_id"], kind, task.get("horizon"), e))
            return False
        log("task %s %s [%s] error: %r (skip)"
            % (pos["position_id"], kind, task.get("horizon"), e))
    return True


def process_pending(state, now_ts):
    """Fire all due tasks; drop positions whose schedule is exhausted."""
    changed = False
    still = []
    for pos in state["pending"]:
        remaining = []
        for task in sorted(pos["schedule"], key=lambda x: x["due_ts"]):
            if task["due_ts"] <= now_ts:
                done = run_task(pos, task, now_ts)
                changed = True
                if not done:
                    remaining.append(task)   # entry or erroring-exit retry
            else:
                remaining.append(task)
        pos["schedule"] = remaining
        if remaining:
            still.append(pos)
        else:
            log("CLOSED %s %s (schedule exhausted)" % (pos["position_id"], pos["symbol"]))
            changed = True
    state["pending"] = still
    return changed


# =====================================================================================
# announcement polling
# =====================================================================================
def poll_once(state):
    """Fetch page 1, act on new futures-listing articles. Returns True if state changed."""
    arts = fetch_announcements()
    # First-ever start: seed the current page as seen WITHOUT acting, so we only trade
    # genuinely new listings going forward (avoids backdated positions on already-released
    # announcements sitting on page 1).
    if not state["bootstrapped"]:
        state["seen_ids"] = [a["id"] for a in arts][-500:]
        state["bootstrapped"] = True
        log("bootstrap: seeded %d current article ids as seen (no positions opened)"
            % len(arts))
        return True
    seen = set(state["seen_ids"])
    changed = False
    new_ids = []
    names_upper = None
    for a in arts:
        aid = a["id"]
        if aid in seen:
            continue
        new_ids.append(aid)
        is_fut, syms = is_futures_listing(a["title"])
        if not is_fut or not syms:
            continue
        if names_upper is None:
            names_upper = hl_meta_names(state)
        hl_hits = []
        for sym in syms:
            hl_name = resolve_hl(sym, names_upper)
            if hl_name:
                hl_hits.append({"symbol": sym, "hl_name": hl_name})
        detected_ts = int(time.time())
        append_jsonl(EVENTS, {
            "kind": "event", "article_id": aid, "title": a["title"], "symbols": syms,
            "hl_available": hl_hits, "release_ts": a["releaseDate"] // 1000,
            "detected_ts": detected_ts, "simulated": False,
        })
        log("EVENT article=%s syms=%s hl=%s :: %s"
            % (aid, syms, [h["hl_name"] for h in hl_hits], a["title"][:80]))
        for h in hl_hits:
            open_position(state, a, h["symbol"], h["hl_name"],
                          a["releaseDate"] // 1000, detected_ts)
        changed = True
    if new_ids:
        # keep seen_ids bounded (page-1 window is small; retain last 500)
        state["seen_ids"] = (state["seen_ids"] + new_ids)[-500:]
        changed = True
    return changed


# =====================================================================================
# daily rotation
# =====================================================================================
def rollover_and_prune(prev_dt):
    src = ticks_path(prev_dt)
    if os.path.exists(src):
        dst = src + ".gz"
        try:
            with open(src, "rb") as fi, gzip.open(dst, "wb") as fo:
                fo.writelines(fi)
            os.remove(src)
            log("gzipped %s" % os.path.basename(src))
        except Exception as e:
            log("gzip failed for %s: %r" % (src, e))
    cutoff = time.time() - RETENTION_DAYS * 86400
    for fn in os.listdir(DATA):
        if fn.startswith("ticks_") and fn.endswith(".jsonl.gz"):
            fp = os.path.join(DATA, fn)
            try:
                if os.path.getmtime(fp) < cutoff:
                    os.remove(fp); log("pruned %s" % fn)
            except Exception:
                pass


# =====================================================================================
# simulate
# =====================================================================================
def simulate():
    os.makedirs(DATA, exist_ok=True)
    state = load_state()
    names_upper = hl_meta_names(state)
    coin = "BTC" if "BTC" in names_upper else sorted(names_upper.values())[0]
    now = int(time.time())
    # backdate release by ENTRY_OFFSET so the compressed pipeline enters immediately
    rel = now - ENTRY_OFFSET
    fake = {"id": "SIM-%d" % now, "code": "sim", "title":
            "Binance Futures Will Launch USDⓈ-Margined %sUSDT Perpetual Contract (SIMULATED)" % coin,
            "releaseDate": rel * 1000}
    log("=== SIMULATE start (coin=%s) ===" % coin)
    append_jsonl(EVENTS, {
        "kind": "event", "article_id": fake["id"], "title": fake["title"],
        "symbols": [coin], "hl_available": [{"symbol": coin, "hl_name": names_upper[coin]}],
        "release_ts": rel, "detected_ts": now, "simulated": True,
    })
    pos = open_position(state, fake, coin, names_upper[coin], rel, now,
                        simulated=True, compressed=True)
    save_state(state)
    deadline = time.time() + 40
    while pos["schedule"] and time.time() < deadline:
        process_pending(state, int(time.time()))
        save_state(state)
        if pos["schedule"]:
            time.sleep(1)
    # ensure the simulated position is not left pending
    state["pending"] = [p for p in state["pending"] if p is not pos]
    save_state(state)
    log("=== SIMULATE done (position %s) ===" % pos["position_id"])
    print("\nSIMULATE complete: position %s exercised entry+snapshots+exits (simulated=true)."
          % pos["position_id"])


# =====================================================================================
# main loop
# =====================================================================================
def main():
    os.makedirs(DATA, exist_ok=True)

    if "--simulate" in sys.argv:
        simulate()
        return

    state = load_state()
    log("monitor start (pending=%d, seen=%d)" % (len(state["pending"]), len(state["seen_ids"])))
    last_poll = 0.0
    last_date = datetime.now(timezone.utc).date()

    while True:
        now_dt = datetime.now(timezone.utc)

        # daily rollover
        if now_dt.date() != last_date:
            try:
                rollover_and_prune(now_dt - timedelta(days=1))
            except Exception as e:
                log("rollover error: %r" % e)
            last_date = now_dt.date()

        # poll announcements every POLL_S
        now = time.time()
        if now - last_poll >= POLL_S:
            try:
                if poll_once(state):
                    save_state(state)
                log("poll ok (pending=%d)" % len(state["pending"]))
            except Exception as e:
                log("poll error: %r (skip)" % e)
            last_poll = now

        # fire due schedule tasks
        try:
            if process_pending(state, int(time.time())):
                save_state(state)
        except Exception as e:
            log("process_pending error: %r (skip)" % e)

        time.sleep(TICK_S)


if __name__ == "__main__":
    main()
