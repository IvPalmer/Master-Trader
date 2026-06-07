"""Extract replay-ready Killers signals from the parsed 2yr corpus (runs on VPS host).

Reuses killers_analyzer's trade-building (recycled-ID handling, move_sl edits,
channel close events) and ADDS the full TP ladder parsed from the message text
(killers_analyzer only kept the published %, not the ladder we need for a
real-price replay). Emits /tmp/killers_signals.json.
"""
import json, re, glob, os
from collections import Counter
from datetime import datetime

BASE = "/home/ubuntu/master-trader/ft_userdata/insiders_bridge"

def load_cls():
    cls = {}
    for p in sorted(glob.glob(BASE + "/out/classifications_killers_chunk*.jsonl")):
        for line in open(p):
            line = line.strip()
            if line:
                o = json.loads(line)
                cls[o["id"]] = o
    return cls

msgs = {m["id"]: m for m in json.load(open(BASE + "/_local/killers_messages.json"))}
cls = load_cls()

def pdt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

TARGETS_RE = re.compile(r"TARGETS?\s*:\s*(.+)", re.I)
NUM_RE = re.compile(r"\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
PCT_RE = re.compile(r"([+\-]?\d+(?:\.\d+)?)\s*%")

def parse_targets(text):
    if not text:
        return []
    m = TARGETS_RE.search(text)
    if m:
        line = m.group(1).splitlines()[0]
        vals = [float(x) for x in NUM_RE.findall(line)]
        if vals:
            return vals
    # fallback: "Target N: x" lines (close/update messages)
    return [float(x) for x in re.findall(r"Target\s*\d+\s*:\s*(\d+(?:\.\d+)?)", text)]

def pub_pct(notes):
    if not notes:
        return None
    p = [float(x.group(1)) for x in PCT_RE.finditer(notes)]
    return max(p, key=abs) if p else None

def norm_entry(entry, er):
    if er and isinstance(er, list) and len(er) == 2:
        try:
            return float(er[0]), float(er[1])
        except (TypeError, ValueError):
            return None, None
    if isinstance(entry, (int, float)):
        return float(entry), float(entry)
    return None, None

trades, last = {}, {}
for cid in sorted(cls):
    o = cls[cid]; msg = msgs.get(cid)
    if not msg:
        continue
    sid, sym, kind = o.get("signal_id"), o.get("symbol"), o.get("kind")
    d = pdt(msg["date"])
    if kind == "open":
        if not sid or not sym:
            continue
        prev = last.get((sid, sym))
        if prev and prev in trades:
            if (d - pdt(trades[prev]["open_date"])).days > 90 and trades[prev]["closed"]:
                tk = (sid, sym, d.year, d.month)
            else:
                continue  # re-announcement of an open lifecycle
        else:
            tk = (sid, sym, d.year, d.month)
        elo, ehi = norm_entry(o.get("entry"), o.get("entry_range"))
        sl = o.get("sl"); sl = float(sl) if isinstance(sl, (int, float)) else None
        trades[tk] = {
            "signal_id": sid, "symbol": sym, "direction": (o.get("direction") or "").lower(),
            "entry_lo": elo, "entry_hi": ehi, "sl_initial": sl, "sl_moves": [],
            "tp_ladder": parse_targets(msg.get("text", "")), "open_date": msg["date"],
            "closed": False, "channel_close_date": None, "channel_close_reason": None,
            "channel_final_pct": None, "max_pct": 0.0,
            "channel_events": [], "last_event_date": None,
        }
        last[(sid, sym)] = tk
    elif kind in ("close_partial", "close_full", "move_sl"):
        if not sid or not sym:
            continue
        tk = last.get((sid, sym))
        if not tk or tk not in trades:
            continue
        t = trades[tk]; pct = pub_pct(o.get("notes", ""))
        t["channel_events"].append({"date": msg["date"], "kind": kind, "pct": pct})
        t["last_event_date"] = msg["date"]   # corpus is chronological by msg id
        if kind == "move_sl":
            ns = o.get("sl")
            if isinstance(ns, (int, float)):
                t["sl_moves"].append([msg["date"], float(ns)])
        elif kind == "close_partial":
            if pct is not None and abs(pct) > abs(t["max_pct"]):
                t["max_pct"] = pct
        elif kind == "close_full":
            t["closed"] = True
            t["channel_close_date"] = msg["date"]
            t["channel_close_reason"] = "sl_hit" if (pct is not None and pct < 0) else "tp_or_manual"
            t["channel_final_pct"] = pct if pct is not None else t["max_pct"]

out = list(trades.values())
json.dump(out, open("/tmp/killers_signals.json", "w"))

usable = [t for t in out if t["entry_lo"] and t["sl_initial"] and t["tp_ladder"]
          and t["direction"] in ("long", "short")]
dates = [t["open_date"] for t in out]
print("total trades:", len(out))
print("usable (entry+sl+tp+dir):", len(usable))
print("  of usable, long/short:", Counter(t["direction"] for t in usable))
print("closed by channel:", sum(1 for t in out if t["closed"]))
print("  sl-hit closes:", sum(1 for t in out if t["channel_close_reason"] == "sl_hit"))
print("  tp/manual closes:", sum(1 for t in out if t["channel_close_reason"] == "tp_or_manual"))
print("with sl_moves:", sum(1 for t in out if t["sl_moves"]))
print("date range:", min(dates), "->", max(dates))
print("top symbols:", Counter(t["symbol"] for t in usable).most_common(10))
