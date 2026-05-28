"""Extract price-verifiable trade specs from the Killers corpus.

Robust target parser handles BOTH formats:
  old inline:  "TARGETS: a - b - c"
  current:     "TARGETS\nShort Term: a - b - c\nMid Term: d - e - f"
Outputs trades.jsonl: one row per open with symbol, direction, entry_mid,
sl, ordered target ladder, open_ts, and the explicit close_ts if the channel
later posted a close_full for that (signal_id, symbol).
"""
import json, re, glob
from datetime import datetime

BASE = "/home/ubuntu/master-trader/ft_userdata/insiders_bridge"
OUT = "/home/ubuntu/killers_backtest/trades.jsonl"

msgs = {m["id"]: m for m in json.load(open(f"{BASE}/_local/killers_messages.json"))}
cls = {}
for p in sorted(glob.glob(f"{BASE}/out/classifications_killers_chunk*.jsonl")):
    for line in open(p):
        if line.strip():
            o = json.loads(line)
            cls[o["id"]] = o

NUM_RE = re.compile(r"\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")
TARGETS_ANCHOR = re.compile(r"^\s*TARGETS?\b", re.I)
STOP_RE = re.compile(r"STOP\s*LOSS|^\s*SL\b", re.I)
SEP_RE = re.compile(r"^\s*[➖\-—–=*_\s]{3,}\s*$")
LABEL_RE = re.compile(r"(short|mid|long)\s*term", re.I)


def parse_nums(s):
    out = []
    for r in NUM_RE.findall(s or ""):
        try:
            v = float(r.replace(",", "."))
        except ValueError:
            continue
        if v > 0:
            out.append(v)
    return out


def extract_targets(text):
    """Ordered ladder from TARGETS block; handles inline + Short/Mid Term."""
    if not text:
        return []
    lines = text.splitlines()
    start = None
    for i, l in enumerate(lines):
        if TARGETS_ANCHOR.match(l):
            start = i
            break
    if start is None:
        return []
    nums = []
    # inline numbers on the TARGETS line itself (old format)
    if ":" in lines[start]:
        nums += parse_nums(lines[start].split(":", 1)[1])
    for l in lines[start + 1:]:
        if STOP_RE.search(l):
            break
        if SEP_RE.match(l):
            # separator inside block is unusual; stop to avoid stray numbers
            if nums:
                break
            continue
        if LABEL_RE.search(l):
            nums += parse_nums(l.split(":", 1)[-1])
        elif re.search(r"\d.*[\-–—].*\d", l):
            # a bare dash-separated number line within the block
            nums += parse_nums(l)
    return nums


def entry_mid(o):
    er = o.get("entry_range")
    if isinstance(er, list) and len(er) == 2:
        try:
            return (float(er[0]) + float(er[1])) / 2
        except (TypeError, ValueError):
            pass
    e = o.get("entry")
    if isinstance(e, (int, float)):
        return float(e)
    return None


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


opens = [o for o in cls.values() if o.get("kind") == "open"]
# index closes by (signal_id, symbol) -> sorted list of (ts, msg_id)
closes = {}
for o in cls.values():
    if o.get("kind") == "close_full" and o.get("signal_id") and o.get("symbol"):
        m = msgs.get(o["id"])
        if not m:
            continue
        closes.setdefault((o["signal_id"], o["symbol"]), []).append(parse_dt(m["date"]))
for k in closes:
    closes[k].sort()

rows = []
n_targets = n_entry_sl = 0
for o in sorted(opens, key=lambda x: x["id"]):
    m = msgs.get(o["id"])
    if not m:
        continue
    sym = o.get("symbol")
    direction = (o.get("direction") or "").lower()
    sl = o.get("sl")
    sl = float(sl) if isinstance(sl, (int, float)) else None
    em = entry_mid(o)
    tgts = extract_targets(m.get("text", ""))
    if tgts:
        n_targets += 1
    if em and sl:
        n_entry_sl += 1
    open_ts = parse_dt(m["date"])
    # first close_full strictly after open
    ct = None
    for c in closes.get((o.get("signal_id"), sym), []):
        if c > open_ts:
            ct = c.isoformat()
            break
    rows.append({
        "msg_id": o["id"], "signal_id": o.get("signal_id"), "symbol": sym,
        "direction": direction, "entry_mid": em, "sl": sl,
        "targets": tgts, "open_ts": open_ts.isoformat(), "close_ts": ct,
    })

with open(OUT, "w") as f:
    for r in rows:
        f.write(json.dumps(r) + "\n")

syms = sorted({r["symbol"] for r in rows if r["symbol"]})
print(f"opens: {len(rows)}")
print(f"with targets: {n_targets} ({n_targets*100//max(1,len(rows))}%)")
print(f"with entry+sl: {n_entry_sl} ({n_entry_sl*100//max(1,len(rows))}%)")
print(f"backtestable (dir+sl+>=1 target): {sum(1 for r in rows if r['direction'] in ('long','short') and r['sl'] and r['targets'])}")
print(f"with explicit close_ts: {sum(1 for r in rows if r['close_ts'])}")
print(f"distinct symbols: {len(syms)}")
print(f"date range: {min(r['open_ts'] for r in rows)} -> {max(r['open_ts'] for r in rows)}")
print(f"wrote {OUT}")
