"""How far down the published TP ladder does price ACTUALLY get?

For each signal, walk real candles (conservative: SL fills before a TP on a
tie) and record the deepest target reached before SL/horizon. This shows
whether 'following the TPs' as the channel suggests actually happens.
"""
import json, glob, os
from datetime import datetime, timezone, timedelta

DIR = "/home/ubuntu/killers_backtest"
ALIASES = {"PEPE": "1000PEPE", "SHIB": "1000SHIB", "FLOKI": "1000FLOKI",
           "BONK": "1000BONK", "GOLD": "XAUT"}
HORIZON_DAYS = 30


def bsym(s): return ALIASES.get(s.upper(), s.upper()) + "USDT"
def parse_dt(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))
def ms(dt): return int(dt.timestamp() * 1000)


ohlcv = {}
for f in glob.glob(f"{DIR}/ohlcv/*.json"):
    rows = json.load(open(f)); rows.sort(key=lambda r: r[0])
    ohlcv[os.path.basename(f)[:-5]] = rows
trades = [json.loads(l) for l in open(f"{DIR}/trades.jsonl") if l.strip()]


def eidx(rows, t):
    lo, hi = 0, len(rows)
    while lo < hi:
        m = (lo + hi) // 2
        if rows[m][0] < t: lo = m + 1
        else: hi = m
    return lo if lo < len(rows) else None


def deepest(t):
    d, sl, tgs = t["direction"], t["sl"], t["targets"] or []
    if d not in ("long", "short") or not sl or not tgs: return None
    rows = ohlcv.get(bsym(t["symbol"]))
    if not rows: return None
    ei = eidx(rows, ms(parse_dt(t["open_ts"])))
    if ei is None: return None
    entry = rows[ei][1]
    if entry <= 0: return None
    is_long = d == "long"
    tg = sorted([x for x in tgs if x > entry]) if is_long else sorted([x for x in tgs if x < entry], reverse=True)
    sl_ok = sl < entry if is_long else sl > entry
    if not tg or not sl_ok: return None
    end = ms(parse_dt(t["close_ts"])) if t.get("close_ts") else ms(parse_dt(t["open_ts"]) + timedelta(days=HORIZON_DAYS))
    n = len(tg); reached = 0
    for r in rows[ei:]:
        ot, o, h, l, c = r
        if ot > end: break
        if (l <= sl) if is_long else (h >= sl):
            break  # SL first (conservative)
        cnt = sum(1 for tp in tg if (h >= tp if is_long else l <= tp))
        reached = max(reached, cnt)
        if reached >= n: break
    return {"reached": reached, "n": n}


res = [r for r in (deepest(t) for t in trades) if r]
N = len(res)
maxn = max(r["n"] for r in res)
print(f"backtestable trades: {N}")
print(f"avg ladder length: {sum(r['n'] for r in res)/N:.1f} targets\n")
print(f"{'reach >= TP':<12}{'count':>7}{'% of trades':>13}")
for k in range(1, min(maxn, 10) + 1):
    c = sum(1 for r in res if r["reached"] >= k)
    print(f"TP{k:<10}{c:>7}{c*100/N:>12.1f}%")
print()
full = sum(1 for r in res if r["reached"] >= r["n"])
none = sum(1 for r in res if r["reached"] == 0)
print(f"reached 0 targets (straight to SL/flat): {none} ({none*100/N:.0f}%)")
print(f"completed the FULL published ladder: {full} ({full*100/N:.0f}%)")
print(f"avg targets reached: {sum(r['reached'] for r in res)/N:.2f} of {sum(r['n'] for r in res)/N:.1f}")
