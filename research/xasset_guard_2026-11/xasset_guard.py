#!/usr/bin/env python3
"""Cross-asset risk-off entry guard on existing trade lists (#254, prereg xasset-riskoff-guard-2026-11).

Question: would blocking NEW entries for N hours after a price-based cross-asset risk-off signal
have raised the first-order net P&L of the FF, Keltner and Killers closed-trade lists?

Guards (all frozen in ft_userdata/preregistrations.json before any trigger met a trade)
  ES60  : two consecutive non-null ES=F hourly bars (starts exactly 3600 s apart) with
          close / previous close - 1 <= -1.0 %. Hourly stand-in for "ES -1 % in 30 min":
          no free keyless sub-hour ES history covers the trade windows.
  VIX20 : the first ^VIX hourly bar of an ET date whose close >= 1.20 x the CBOE close of the
          most recent earlier CBOE date (close, not high: VIX opening prints are erratic). At most
          one per ET date.
  OR    : the union of ES60 and VIX20.
  VIXD  : (secondary, full window) CBOE daily close >= 1.20 x the previous CBOE close.
An hourly trigger takes effect at bar start + 3600 s + 300 s (bar close plus one 5-min
snapshot of latency); VIXD at 16:15 ET + 300 s. A guard blocks every new entry with
trigger <= entry < trigger + N h, for N in HOURS (VIXD: VIXD_HOURS).

Per trade list x variant: n, n blocked, net P&L without / with the guard (first order: freed
slots are not refilled), month-block bootstrap CIs, a date-shift placebo, and the frozen verdict
on the primary cell. Stdlib only; reads inputs in place and verifies their sha256 first.

Amendments before any result (Codex review rounds 1-2): triggers are taken only inside the
variant's window (A1); a verdict needs blocked trades in >= 3 calendar months (A1); secondary
cells are descriptive only (A1). The verdict's placebo is the full group of whole-day circular
rotations of the real guard mask (merged, clipped to the window; a piece crossing the window
end wraps to its start), with an exact one-sided rank p (A2). The +/-1..30-day rotations are
kept as a descriptive local placebo (A2).
"""
import argparse
import bisect
import collections
import csv
import datetime as dt
import hashlib
import json
import os
import random
import sqlite3
import sys
import zipfile
from zoneinfo import ZoneInfo

PREREG_ID = "xasset-riskoff-guard-2026-11"
ET = ZoneInfo("America/New_York")
UTC = dt.timezone.utc

ES_DROP = 0.010
VIX_RISE = 0.20
VIXD_RISE = 0.20
BAR_S = 3600
LATENCY_S = 300
VIX_CLOSE_ET = (16, 15)
HOURS = (4, 12, 24)
VIXD_HOURS = (24,)
INTRADAY_GUARDS = ("ES60", "VIX20", "OR")
PRIMARY = ("OR", 12, "FF_V2_current")
WINDOW_INTRADAY = ("2024-06-15T00:00:00Z", "2026-11-01T00:00:00Z")
WINDOW_DAILY = ("2023-01-01T00:00:00Z", "2026-11-01T00:00:00Z")
BOOT_N = 10000
SEED = 2291105
PLACEBO_MAX_DAYS = 30
CI_LEVEL = 0.95
MIN_BLOCKED_FOR_PASS = 10
N_VARIANTS = len(INTRADAY_GUARDS) * len(HOURS) + len(VIXD_HOURS)
LOCAL_OFFSETS = tuple(sign * d * 86400 for d in range(1, PLACEBO_MAX_DAYS + 1)
                      for sign in (1, -1))     # A2: descriptive local placebo, 60 rotations
N_LOCAL = len(LOCAL_OFFSETS)
P_MAX = 0.05
MIN_BLOCKED_MONTHS = 3                          # A1

R = "/home/ubuntu/master-trader/research"
HERE = os.path.dirname(os.path.abspath(__file__))

RAW = {  # data/raw/<file>: sha256, fetched 2026-11-05T19:36Z on the VPS
    "yahoo_1h_ES_F.json": "fb1848c1dc37dbf943588a7b4e28b3109d5cd40336844bdf4e8fb5210a826426",
    "yahoo_1h__VIX.json": "60b146a805331f42d32c42b874be28e12c7777a8aa8985c48c8a49b83ce1e06d",
    "cboe_VIX_History.csv": "50731d77d6723344b67789e2fafe65c32bf005710d5918e693da5f1f62e231e8",
}
FETCHED_AT = "2026-11-05T19:36:00Z"   # the hourly files; bars ending after this are partial

# (label, path relative to R or data/live, strategy key, loader, unit, sha256)
STRATS = [
    ("FF_V2_current",
     "ff_roi_2026-09-30/user_data/backtest_results/backtest-result-2026-09-30_23-45-13.zip",
     "FFX_V0_current", "zip", "USDT",
     "22f8ad2f72dcdf61a92abcfaca0cb4a958cc12feb6c540b35bd4f40011f4ac54"),
    ("FF_PreV2_sens",
     "ff_entry_ablation_2026-10-01/user_data/backtest_results/backtest-result-2026-10-01_03-28-54.zip",
     "FFA_PreV2", "zip", "USDT",
     "00203e8b90fc60bb44b897c34da6479756f1fd943e034645a331bc6107d22a67"),
    ("Keltner_R4_live18", "oos_retest_2026-07/results/R4.zip", "KeltnerBounceV1", "zip", "USDT",
     "7dcf76de167b4bc86d9954c59deacba0ddba47d6f5c171bcd7d19445435346f5"),
    ("Keltner_R5_wl60", "oos_retest_2026-07/results/R5.zip", "KeltnerBounceV1", "zip", "USDT",
     "b1fe233a730d2a850175fc7e3482b121e7a37c04e9ed86b3056c851e2a75ee37"),
    ("Killers_channel", "copier-validation/killers/killers_signals.json", None, "kchan",
     "margin units", "b384b724b721d89424b9a3ea10782a5cabef80770fefbf843338b0bffc594d79"),
    ("Killers_dry", "tg_bots_audit_2026-07/killers_trades_full.json", None, "kdry", "USDT",
     "901f0ad3841abe644223bb807cbf26eccd3be2b56a5c885a654c31cbabc78000"),
    ("FF_live", "live:tradesv3.live.FundingFadeV1.sqlite", None, "sqlite", "USDT",
     "11d2961b81a408fc338b149c93fbdaed06f0f0624860a1c2b4e0ae1d6fe44329"),
    ("FF_live", "live:tradesv3.live.FundingFadeV1.v2.sqlite", None, "sqlite", "USDT",
     "629ee69f451dd0e5accbcf02243b7aa1a1d680ec2a76211e26542bf94ee2b229"),
    ("Keltner_live", "live:tradesv3.live.KeltnerBounceV1.sqlite", None, "sqlite", "USDT",
     "12d79033b5f1642c016dbcf916d5faee1f0d83a4bd825bdb05972e765416cf86"),
    ("Killers_live", "live:tradesv3.live.KillersScalpV1.hyperliquid.sqlite", None, "sqlite",
     "USDC", "e44060bad68dede35db57032a3b68fc378f79a707b2b5573a98140a9e0cbd7c0"),
]
LIVE_LISTS = {"FF_live", "Keltner_live", "Killers_live"}
SHORT_LISTS = {"Killers_channel", "Killers_dry", "Killers_live"}


# ---- time helpers --------------------------------------------------------------------------

def utc_s(iso_z):
    return int(dt.datetime.fromisoformat(iso_z.replace("Z", "+00:00")).timestamp())


def iso(s):
    return dt.datetime.fromtimestamp(s, UTC).strftime("%Y-%m-%d %H:%M")


def et_date(s):
    return dt.datetime.fromtimestamp(s, ET).date().isoformat()


def et_s(date_iso, hh, mm):
    y, m, d = map(int, date_iso.split("-"))
    return int(dt.datetime(y, m, d, hh, mm, tzinfo=ET).timestamp())


def naive_utc_s(value):
    """Freqtrade sqlite / JSON dates: naive means UTC (never the host's local zone)."""
    d = dt.datetime.fromisoformat(value)
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.timestamp()


# ---- inputs --------------------------------------------------------------------------------

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(path, expected):
    got = sha256(path)
    if got != expected:
        raise SystemExit("sha256 mismatch for %s: %s != %s" % (path, got, expected))


def parse_yahoo(obj, fetched_s):
    """Yahoo chart JSON -> sorted [(start_s, high, close)]: non-null, half-hour aligned, complete."""
    r = obj["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = []
    for t, h, c in zip(r["timestamp"], q["high"], q["close"]):
        if h is None or c is None or t % 1800 or t + BAR_S > fetched_s:
            continue
        out.append((int(t), float(h), float(c)))
    out.sort()
    return out


def parse_cboe(text):
    """CBOE VIX_History.csv (DATE MM/DD/YYYY, ..., CLOSE) -> sorted [(iso_date, close)]."""
    rows = []
    for row in csv.DictReader(text.splitlines()):
        m, d, y = row["DATE"].split("/")
        rows.append(("%s-%s-%s" % (y, m, d), float(row["CLOSE"])))
    rows.sort()
    return rows


# ---- triggers ------------------------------------------------------------------------------

def es_triggers(bars, drop=ES_DROP):
    out = []
    for (t0, _, c0), (t1, _, c1) in zip(bars, bars[1:]):
        if t1 - t0 != BAR_S:
            continue
        ret = c1 / c0 - 1
        if ret <= -drop:
            out.append((t1 + BAR_S + LATENCY_S, "ES60", "%+.2f%% bar %s" % (100 * ret, iso(t1))))
    return out


def vix_triggers(bars, closes, rise=VIX_RISE):
    dates = [d for d, _ in closes]
    out, done = [], set()
    for t, _, close in bars:
        d = et_date(t)
        if d in done:
            continue
        i = bisect.bisect_left(dates, d) - 1
        if i < 0:
            continue
        prev = closes[i][1]
        if close >= (1 + rise) * prev:
            done.add(d)
            out.append((t + BAR_S + LATENCY_S, "VIX20", "close %.2f vs %s close %.2f (%+.1f%%)" % (
                close, closes[i][0], prev, 100 * (close / prev - 1))))
    return out


def vixd_triggers(closes, rise=VIXD_RISE):
    out = []
    for (d0, c0), (d1, c1) in zip(closes, closes[1:]):
        if c1 >= (1 + rise) * c0:
            out.append((et_s(d1, *VIX_CLOSE_ET) + LATENCY_S, "VIXD",
                        "close %.2f vs %s %.2f (%+.1f%%)" % (c1, d0, c0, 100 * (c1 / c0 - 1))))
    return out


def in_window(times, window):
    lo, hi = window
    return [t for t in times if lo <= t < hi]


def full_offsets(window):
    """A2: every nonzero whole-day circular rotation of a whole-day window."""
    lo, hi = window
    days, rem = divmod(hi - lo, 86400)
    assert rem == 0, "window must be whole days"
    return tuple(d * 86400 for d in range(1, days))


def merge(ivs):
    out = []
    for a, b in sorted(ivs):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [tuple(iv) for iv in out]


def clip(ivs, window):
    lo, hi = window
    return [(max(a, lo), min(b, hi)) for a, b in ivs if b > lo and a < hi]


def rotate(mask, shift, window):
    """A2: rotate a clipped guard mask circularly inside [lo, hi); a piece crossing hi is split
    and continues at lo, so the guarded time is identical under every rotation. Whole-day
    rotations of a whole-day window keep the hour of day."""
    lo, hi = window
    span = hi - lo
    out = []
    for a, b in mask:
        a2 = lo + (a - lo + shift) % span
        b2 = a2 + (b - a)
        if b2 <= hi:
            out.append((a2, b2))
        else:
            out += [(a2, hi), (lo, lo + b2 - hi)]
    return merge(out)


def intervals(times, hours, shift=0):
    """Merged [start, end) guard intervals."""
    span = hours * 3600
    out = []
    for t in sorted(x + shift for x in times):
        if out and t <= out[-1][1]:
            out[-1][1] = max(out[-1][1], t + span)
        else:
            out.append([t, t + span])
    return [tuple(iv) for iv in out]


def blocked(entry_s, ivs, starts=None):
    starts = starts if starts is not None else [a for a, _ in ivs]
    i = bisect.bisect_right(starts, entry_s) - 1
    return i >= 0 and entry_s < ivs[i][1]


def guarded_share(ivs, lo, hi):
    on = sum(max(0, min(b, hi) - max(a, lo)) for a, b in ivs)
    return on / (hi - lo)


# ---- trade loaders: dicts(token, pair, entry_s, ratio, abs, is_short) -----------------------

def load_ft_zip(path, strat):
    with zipfile.ZipFile(path) as z:
        name = [n for n in z.namelist() if n.endswith(".json") and "_config" not in n
                and "market_change" not in n][0]
        data = json.loads(z.read(name))
    return [dict(pair=t["pair"], entry_s=int(t["open_timestamp"]) / 1000,
                 ratio=float(t["profit_ratio"]), abs=float(t["profit_abs"]),
                 is_short=bool(t.get("is_short"))) for t in data["strategy"][strat]["trades"]]


def load_killers_channel(path):
    """Channel-reported outcome (killers_bot/simulator.py rule), margin units, no costs."""
    out = []
    for s in json.load(open(path)):
        pct = s["channel_final_pct"] if s["channel_final_pct"] is not None else (s["max_pct"] or 0.0)
        out.append(dict(pair=s["symbol"], entry_s=naive_utc_s(s["open_date"]), ratio=pct / 100.0,
                        abs=pct / 100.0, is_short=s["direction"] == "short"))
    return out


def load_killers_dry(path):
    return [dict(pair=t["pair"], entry_s=int(t["open_timestamp"]) / 1000,
                 ratio=float(t["profit_ratio"]), abs=float(t["profit_abs"]),
                 is_short=bool(t.get("is_short"))) for t in json.load(open(path))["trades"]]


def load_sqlite(path):
    """Closed trades of a Freqtrade DB copy, read-only. close_profit_abs includes partial exits."""
    conn = sqlite3.connect("file:%s?mode=ro&immutable=1" % path, uri=True)
    try:
        rows = conn.execute("SELECT pair, open_date, close_profit, close_profit_abs, is_short"
                            " FROM trades WHERE is_open = 0 ORDER BY open_date").fetchall()
    finally:
        conn.close()
    return [dict(pair=p, entry_s=naive_utc_s(o), ratio=float(r), abs=float(a),
                 is_short=bool(s)) for p, o, r, a, s in rows]


# ---- statistics ----------------------------------------------------------------------------

def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def month(s):
    return iso(s)[:7]


def summarize(trades, flags):
    v = [t for t, f in zip(trades, flags) if f]
    k = [t for t, f in zip(trades, flags) if not f]

    def s(g):
        return dict(n=len(g), mean_ratio=mean([t["ratio"] for t in g]),
                    sum_abs=sum(t["abs"] for t in g),
                    win=(sum(1 for t in g if t["ratio"] > 0) / len(g)) if g else None)
    return s(v), s(k)


def block_bootstrap(trades, flags, rng, n_boot=BOOT_N, level=CI_LEVEL):
    """Calendar-month block bootstrap of net P&L without / with the guard, the change, and the
    blocked-minus-kept mean ratio (draws with an empty group are skipped and counted)."""
    # per month: [sum abs, sum abs blocked, n blocked, sum ratio blocked, n kept, sum ratio kept]
    by_m = collections.defaultdict(lambda: [0.0, 0.0, 0, 0.0, 0, 0.0])
    for t, f in zip(trades, flags):
        m = by_m[month(t["entry_s"])]
        m[0] += t["abs"]
        if f:
            m[1] += t["abs"]
            m[2] += 1
            m[3] += t["ratio"]
        else:
            m[4] += 1
            m[5] += t["ratio"]
    keys = sorted(by_m)
    lo_q, hi_q = (1 - level) / 2, 1 - (1 - level) / 2
    if not keys:
        return None
    w, k, d, diff, skipped = [], [], [], [], 0
    for _ in range(n_boot):
        s = [0.0, 0.0, 0, 0.0, 0, 0.0]
        for _ in keys:
            m = by_m[rng.choice(keys)]
            for i in range(6):
                s[i] += m[i]
        w.append(s[0])
        k.append(s[0] - s[1])
        d.append(-s[1])
        if s[2] and s[4]:
            diff.append(s[3] / s[2] - s[5] / s[4])
        else:
            skipped += 1
    ci = lambda xs: dict(lo=pct(xs, lo_q), hi=pct(xs, hi_q)) if xs else None  # noqa: E731
    return dict(months=len(keys), net_without=ci(w), net_with=ci(k), delta=ci(d),
                diff_mean=ci(diff), diff_skipped=skipped)


def placebo(trades, mask, window, real_delta, offsets, longs_only=False):
    """Rank test of the real guard mask against its rotations. With `offsets` = the full group
    (full_offsets), p_helps = (1 + #placebo >= real) / (1 + N) and p_hurts = (1 + #placebo <=
    real) / (1 + N) are exact under a random-phase null; ties count against the real guard."""
    deltas = []
    for off in offsets:
        ivs = rotate(mask, off, window)
        st = [a for a, _ in ivs]
        deltas.append(-sum(t["abs"] for t in trades
                           if not (longs_only and t["is_short"]) and blocked(t["entry_s"], ivs, st)))
    n = len(deltas)
    below = sum(1 for x in deltas if x < real_delta)
    ties = sum(1 for x in deltas if x == real_delta)
    above = n - below - ties
    return dict(n=n, pctile=100.0 * (below + 0.5 * ties) / n,
                p_helps=(1 + above + ties) / (1 + n), p_hurts=(1 + below + ties) / (1 + n),
                mean=mean(deltas), p05=pct(deltas, 0.05), p95=pct(deltas, 0.95),
                share_nonzero=sum(1 for x in deltas if x != 0) / n)


def verdict(cell):
    """Frozen decision rule as amended by A1 (primary cell only)."""
    d, ci, pl, nb = cell["delta"], cell["boot"]["delta"], cell["placebo"], cell["n_blocked"]
    enough = nb >= MIN_BLOCKED_FOR_PASS and cell["blocked_months"] >= MIN_BLOCKED_MONTHS
    if enough and d > 0 and ci and ci["lo"] > 0 and pl["p_helps"] <= P_MAX:
        return "helps"
    if enough and d < 0 and ci and ci["hi"] < 0 and pl["p_hurts"] <= P_MAX:
        return "hurts"
    return "inconclusive"


def evaluate(trades, times, hours, window, rng, longs_only=False):
    lo, hi = window
    tr = [t for t in trades if lo <= t["entry_s"] < hi]
    times = in_window(times, window)
    ivs = clip(intervals(times, hours), window)
    st = [a for a, _ in ivs]
    flags = [not (longs_only and t["is_short"]) and blocked(t["entry_s"], ivs, st) for t in tr]
    sv, sk = summarize(tr, flags)
    net_without = sum(t["abs"] for t in tr)
    delta = -sv["sum_abs"]
    return dict(n=len(tr), n_blocked=sv["n"], net_without=net_without, net_with=net_without + delta,
                delta=delta, blocked=sv, kept=sk, n_triggers=len(times),
                blocked_months=len({month(t["entry_s"]) for t, f in zip(tr, flags) if f}),
                boot=block_bootstrap(tr, flags, rng) if tr else None,
                placebo=placebo(tr, ivs, window, delta, full_offsets(window), longs_only)
                if tr else None,
                placebo_local=placebo(tr, ivs, window, delta, LOCAL_OFFSETS, longs_only)
                if tr else None,
                guarded_share=guarded_share(ivs, lo, hi),
                blocked_rows=[t for t, f in zip(tr, flags) if f])


# ---- descriptive: 2026-11-05 timeline (not a test) -----------------------------------------

TIMELINE = {  # data/raw/<file>: sha256, fetched 2026-11-05T19:4xZ on the VPS
    "yahoo_1m_5d_ES_F.json": "a6a6e3b5be0aaf88f3e275d904c2db9707470663cd714a66be696d4836b425f7",
    "yahoo_1m_5d_NQ_F.json": "87fc6c37e2c561d40783d154839044f92d19d5c898df21f78dd2bd98b9a9ea65",
    "yahoo_1m_5d__VIX.json": "b6a5a05cf66dffec0f8aa0b9453c8ca97962cc1683f586cd98298a4b081e7d49",
    "binance_spot_BTCUSDT_1m_20261105.json":
        "82a99b52495b598b3c1fa75eda151eced28b821677f4e82d2a7e5f77d4458484",
    "binance_spot_BTCUSDT_1m_20261105b.json":
        "b93ffc9b4f3467d93750d71a79ba2c11caef8cf797da7425419512adba72dfc8",
}
TIMELINE_DAY = "2026-11-05"
TIMELINE_REF_UTC = "2026-11-05T12:00:00Z"
WIN30_S = 1800


def minute_closes_yahoo(obj):
    r = obj["chart"]["result"][0]
    return {int(t): float(c) for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"])
            if c is not None and t % 60 == 0}


def minute_closes_binance(rows):
    return {int(k[0]) // 1000: float(k[4]) for k in rows}


def first_drop_30m(closes, lo, hi, drop=ES_DROP):
    """First minute t in [lo, hi) with close(t) / close(t - 30 min) - 1 <= -drop (known at t+60)."""
    for t in sorted(closes):
        if lo <= t < hi and (t - WIN30_S) in closes and closes[t] / closes[t - WIN30_S] - 1 <= -drop:
            return t + 60, closes[t] / closes[t - WIN30_S] - 1
    return None, None


def first_below_ref(closes, ref_t, lo, hi, drop=ES_DROP):
    ref = closes.get(ref_t)
    if ref is None:
        return None, None
    for t in sorted(closes):
        if lo <= t < hi and closes[t] / ref - 1 <= -drop:
            return t + 60, closes[t] / ref - 1
    return None, None


def timeline(data, es_bars, vix_bars, closes):
    """Descriptive: when would each rule have fired on 2026-11-05, versus BTC?"""
    for name, h in TIMELINE.items():
        verify(os.path.join(data, "raw", name), h)
    raw = lambda n: json.load(open(os.path.join(data, "raw", n)))  # noqa: E731
    lo = utc_s(TIMELINE_DAY + "T00:00:00Z")
    hi, ref = lo + 86400, utc_s(TIMELINE_REF_UTC)
    series = {"ES=F": minute_closes_yahoo(raw("yahoo_1m_5d_ES_F.json")),
              "NQ=F": minute_closes_yahoo(raw("yahoo_1m_5d_NQ_F.json")),
              "BTCUSDT": minute_closes_binance(raw("binance_spot_BTCUSDT_1m_20261105.json")
                                               + raw("binance_spot_BTCUSDT_1m_20261105b.json"))}
    out = {}
    for k, c in series.items():
        t30, r30 = first_drop_30m(c, lo, hi)
        tr, rr = first_below_ref(c, ref, lo, hi)
        out[k] = dict(first_30m_drop_1pct=iso(t30) if t30 else None, ret_30m=r30,
                      first_1pct_below_12utc=iso(tr) if tr else None, ret_vs_12utc=rr)
    vix1m = minute_closes_yahoo(raw("yahoo_1m_5d__VIX.json"))
    prev = [c for d, c in closes if d < TIMELINE_DAY][-1]
    cross = next((t for t in sorted(vix1m) if lo <= t < hi and vix1m[t] >= (1 + VIX_RISE) * prev), None)
    out["^VIX"] = dict(prior_close=prev, first_1m_close_ge_120pct=iso(cross + 60) if cross else None)
    out["hourly_rules"] = [dict(guard=g, effective_utc=iso(t), detail=d)
                           for t, g, d in es_triggers(es_bars) + vix_triggers(vix_bars, closes)
                           if lo <= t < hi + 2 * BAR_S]
    return out


# ---- main ----------------------------------------------------------------------------------

def load_inputs(root, data):
    for name, h in RAW.items():
        verify(os.path.join(data, "raw", name), h)
    fetched = utc_s(FETCHED_AT)
    es = parse_yahoo(json.load(open(os.path.join(data, "raw", "yahoo_1h_ES_F.json"))), fetched)
    vix = parse_yahoo(json.load(open(os.path.join(data, "raw", "yahoo_1h__VIX.json"))), fetched)
    closes = parse_cboe(open(os.path.join(data, "raw", "cboe_VIX_History.csv")).read())
    lists = collections.OrderedDict()
    for label, rel, strat, kind, unit, h in STRATS:
        path = (os.path.join(data, "live", rel[5:]) if rel.startswith("live:")
                else os.path.join(root, rel))
        verify(path, h)
        trades = {"zip": lambda: load_ft_zip(path, strat), "kchan": lambda: load_killers_channel(path),
                  "kdry": lambda: load_killers_dry(path), "sqlite": lambda: load_sqlite(path)}[kind]()
        lists.setdefault(label, dict(unit=unit, files=[], trades=[]))
        lists[label]["files"].append(rel)
        lists[label]["trades"].extend(trades)
    return es, vix, closes, lists


def variants(es, vix, closes):
    es_t, vix_t, vixd_t = es_triggers(es), vix_triggers(vix, closes), vixd_triggers(closes)
    trig = {"ES60": es_t, "VIX20": vix_t, "OR": sorted(es_t + vix_t), "VIXD": vixd_t}
    win_i = tuple(utc_s(x) for x in WINDOW_INTRADAY)
    win_d = tuple(utc_s(x) for x in WINDOW_DAILY)
    out = [(g, h, win_i) for g in INTRADAY_GUARDS for h in HOURS]
    out += [("VIXD", h, win_d) for h in VIXD_HOURS]
    return trig, out


def run(root, data, out_dir):
    es, vix, closes, lists = load_inputs(root, data)
    trig, var = variants(es, vix, closes)
    rng = random.Random(SEED)
    results, blocked_rows = [], []
    for label, L in lists.items():
        modes = [False, True] if label in SHORT_LISTS else [False]
        for g, h, win in var:
            times = [t for t, _, _ in trig[g]]
            for longs_only in modes:
                cell = evaluate(L["trades"], times, h, win, rng, longs_only)
                rows = cell.pop("blocked_rows")
                cell.update(list=label, guard=g, hours=h, unit=L["unit"], longs_only=longs_only,
                            window=[iso(win[0]), iso(win[1])])
                if (g, h, label) == PRIMARY and not longs_only:
                    cell["verdict"] = verdict(cell)
                results.append(cell)
                if label not in LIVE_LISTS and not longs_only:
                    for t in rows:
                        blocked_rows.append(dict(list=label, guard=g, hours=h, pair=t["pair"],
                                                 entry_utc=iso(t["entry_s"]), ratio=t["ratio"],
                                                 abs=t["abs"], short=t["is_short"]))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "triggers.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["guard", "effective_utc", "detail"])
        for g in ("ES60", "VIX20", "VIXD"):
            for t, _, detail in trig[g]:
                w.writerow([g, iso(t), detail])
    inputs = [dict(list=k, unit=v["unit"], files=v["files"], n=len(v["trades"]),
                   first=iso(min(t["entry_s"] for t in v["trades"])),
                   last=iso(max(t["entry_s"] for t in v["trades"]))) for k, v in lists.items()]
    summary = dict(prereg=PREREG_ID, inputs=inputs, results=results,
                   n_triggers={g: len(v) for g, v in trig.items()},
                   es_bars=[iso(es[0][0]), iso(es[-1][0]), len(es)],
                   vix_bars=[iso(vix[0][0]), iso(vix[-1][0]), len(vix)],
                   seed=SEED, n_local_placebo=N_LOCAL, n_boot=BOOT_N,
                   timeline_2026_11_05=timeline(data, es, vix, closes))
    json.dump(summary, open(os.path.join(out_dir, "guard_results.json"), "w"), indent=1)
    json.dump(blocked_rows, open(os.path.join(out_dir, "blocked_backtest_trades.json"), "w"),
              indent=1)
    md = tables(summary)
    open(os.path.join(out_dir, "tables.md"), "w").write(md)
    print(md)
    return summary


def _p(x):
    return "-" if x is None else "%+.2f%%" % (100 * x)


def _ci(c, fmt="%+.2f"):
    return "-" if not c else "[%s, %s]" % (fmt % c["lo"], fmt % c["hi"])


def tables(summary):
    L = ["| list | guard | N h | longs only | n | blocked (months) | net without | net with | "
         "change (95% CI) | blocked mean / kept mean | rotation pct | p helps / p hurts | "
         "local pct (+/-30 d) | guarded time |",
         "|---|---|---:|---|---:|---:|---:|---:|---|---|---:|---|---:|---:|"]
    for r in summary["results"]:
        b, pl, loc = r["boot"] or {}, r["placebo"], r["placebo_local"]
        L.append("| %s | %s | %d | %s | %d | %d (%d) | %+.2f | %+.2f | %+.2f %s | %s / %s | %s | %s "
                 "| %s | %.1f%% |%s" % (
                     r["list"], r["guard"], r["hours"], "yes" if r["longs_only"] else "no", r["n"],
                     r["n_blocked"], r["blocked_months"], r["net_without"], r["net_with"],
                     r["delta"], _ci(b.get("delta")), _p(r["blocked"]["mean_ratio"]),
                     _p(r["kept"]["mean_ratio"]), "-" if not pl else "%.0f" % pl["pctile"],
                     "-" if not pl else "%.3f / %.3f" % (pl["p_helps"], pl["p_hurts"]),
                     "-" if not loc else "%.0f" % loc["pctile"], 100 * r["guarded_share"], " **%s**" % r["verdict"] if "verdict" in r else ""))
    L += ["", "Triggers: %s" % json.dumps(summary["n_triggers"]), "",
          "2026-11-05 timeline (descriptive):", "```",
          json.dumps(summary["timeline_2026_11_05"], indent=1), "```"]
    return "\n".join(L) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--root", default=R)
    p.add_argument("--data", default=os.path.join(R, "xasset_guard_2026-11", "data"))
    p.add_argument("--out", default=os.path.join(R, "xasset_guard_2026-11", "results"))
    a = p.parse_args(argv)
    run(a.root, a.data, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
