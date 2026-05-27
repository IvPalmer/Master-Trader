"""Backtest the killers acceleration bundle against the historical 3.4k-msg
corpus.

Two analyses:

A. Fast-path coverage — how many OPENs would `is_strict_killers_open` catch
   without false positives? Compares against Claude classifications stored
   in `ft_userdata/insiders_bridge/out/classifications_killers_chunk*.jsonl`.

B. Slippage-gate replay against captured live opens — what would the
   `KILLERS_MAX_ENTRY_SLIPPAGE_PCT=3.0` gate have decided on each? Uses
   Binance 1m klines at the channel-post timestamp to estimate mark.

Run on VPS (path-aware to canonical Dokploy compose mount). Local copy
also works if the files are scp'd:
    python3 -m killers_bot.tests.backtest_acceleration
"""
import json
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from killers_bot.strict_open import is_strict_killers_open  # noqa: E402

CORPUS_LOCATIONS = [
    "/home/ubuntu/master-trader/ft_userdata/insiders_bridge/_local/killers_messages.json",
    "/Users/palmer/Work/Dev/master-trader/ft_userdata/insiders_bridge/_local/killers_messages.json",
]
CLASSIFICATIONS_GLOB = [
    "/home/ubuntu/master-trader/ft_userdata/insiders_bridge/out/classifications_killers_chunk*.jsonl",
    "/Users/palmer/Work/Dev/master-trader/ft_userdata/insiders_bridge/out/classifications_killers_chunk*.jsonl",
]


def find_first(paths):
    for p in paths:
        if Path(p).exists():
            return p
    return None


def load_corpus():
    msgs_path = find_first(CORPUS_LOCATIONS)
    if not msgs_path:
        print("ERROR: killers_messages.json not found locally — run on VPS or scp first")
        sys.exit(1)
    with open(msgs_path) as f:
        msgs = json.load(f)
    msgs_by_id = {m["id"]: m for m in msgs}

    cls_by_id = {}
    import glob
    for pattern in CLASSIFICATIONS_GLOB:
        for path in sorted(glob.glob(pattern)):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    cls_by_id[obj["id"]] = obj
            if cls_by_id:
                break
        if cls_by_id:
            break

    return msgs_by_id, cls_by_id


# ── (A) Fast-path coverage ────────────────────────────────────────────────


def analyze_fast_path(msgs_by_id, cls_by_id):
    """Compare strict_open verdict against Claude classifications."""
    truth_open = set()      # Claude says open
    fast_open = set()       # rule says open
    disagreements = []      # (msg_id, fp, claude) where fields differ

    for msg_id, msg in msgs_by_id.items():
        claude_cls = cls_by_id.get(msg_id)
        if not claude_cls:
            continue
        if claude_cls.get("kind") == "open":
            truth_open.add(msg_id)
        fp = is_strict_killers_open(msg.get("text") or "", msg_id)
        if fp is not None:
            fast_open.add(msg_id)
        # Disagreement only meaningful when fast-path fired AND claude has a verdict
        if fp is not None and claude_cls.get("kind") != "open":
            disagreements.append(("FP_BUT_NOT_OPEN", msg_id, fp, claude_cls))
        elif fp is not None and claude_cls.get("kind") == "open":
            mism = []
            for f in ("symbol", "direction"):
                fpv = fp.get(f)
                cv = claude_cls.get(f)
                if (fpv or "").lower() != (cv or "").lower():
                    mism.append(f)
            if mism:
                disagreements.append(("FIELD_MISMATCH", msg_id, fp, claude_cls, mism))

    tp = len(fast_open & truth_open)             # rule says open, Claude says open
    fp_count = len(fast_open - truth_open)        # rule says open, Claude says not
    fn_ids = sorted(truth_open - fast_open)
    fn = len(fn_ids)
    print("\nMISSED OPENS (rule failed, Claude said open):")
    for mid in fn_ids[:5]:
        text = (msgs_by_id[mid].get("text") or "")[:500]
        print(f"  msg_id={mid}\n  text={text!r}\n")
    tn = len(set(msgs_by_id) - fast_open - truth_open)

    recall = tp / max(1, tp + fn)
    precision = tp / max(1, tp + fp_count)
    fast_path_share = len(fast_open) / max(1, len(cls_by_id))

    return {
        "total_classified": len(cls_by_id),
        "truth_open_count": len(truth_open),
        "fast_open_count": len(fast_open),
        "true_positive": tp,
        "false_positive": fp_count,
        "false_negative": fn,
        "true_negative": tn,
        "recall_on_opens": recall,
        "precision_on_opens": precision,
        "fast_path_corpus_share": fast_path_share,
        "disagreements": disagreements[:30],  # cap output
        "disagreement_count": len(disagreements),
    }


def print_fast_path_report(r):
    print()
    print("=== (A) Fast-path coverage ===")
    print(f"Total classified messages: {r['total_classified']}")
    print(f"OPENs per Claude (truth):   {r['truth_open_count']}")
    print(f"Rule fast-path fired on:    {r['fast_open_count']} messages "
          f"({r['fast_path_corpus_share']*100:.1f}% of corpus)")
    print()
    print(f"  True positives  (rule=open, truth=open):   {r['true_positive']}")
    print(f"  False positives (rule=open, truth≠open):   {r['false_positive']}")
    print(f"  False negatives (truth=open, rule missed): {r['false_negative']}")
    print()
    print(f"  RECALL on OPENs:    {r['recall_on_opens']*100:.1f}% "
          f"(of {r['truth_open_count']} real opens, rule catches {r['true_positive']})")
    print(f"  PRECISION on opens: {r['precision_on_opens']*100:.1f}% "
          f"(of {r['fast_open_count']} rule-fires, {r['true_positive']} are real opens)")
    print()
    if r['disagreement_count']:
        print(f"Disagreements ({r['disagreement_count']} total, showing up to 30):")
        for d in r['disagreements'][:30]:
            kind = d[0]
            msg_id = d[1]
            if kind == "FP_BUT_NOT_OPEN":
                claude = d[3]
                print(f"  [FP_BUT_NOT_OPEN] msg_id={msg_id} claude_kind={claude.get('kind')} sym={claude.get('symbol')}")
            elif kind == "FIELD_MISMATCH":
                fp, claude, mism = d[2], d[3], d[4]
                print(f"  [FIELD_MISMATCH] msg_id={msg_id} fields={mism} "
                      f"rule={{{fp.get('symbol')}/{fp.get('direction')}}} "
                      f"claude={{{claude.get('symbol')}/{claude.get('direction')}}}")
    else:
        print("Zero disagreements.")


# ── (B) Slippage gate replay ──────────────────────────────────────────────


# Symbol → binance perp mapping (mirror of receiver's map)
SYMBOL_ALIASES = {
    "PEPE": "1000PEPE", "SHIB": "1000SHIB", "FLOKI": "1000FLOKI",
    "BONK": "1000BONK", "GOLD": "XAUT",
}


def to_binance_perp(symbol: str) -> str:
    return f"{SYMBOL_ALIASES.get(symbol.upper(), symbol.upper())}USDT"


def fetch_binance_kline_1m(symbol: str, ts_unix_ms: int):
    """Pull the 1-minute kline closest to ts_unix_ms. Returns (open, high, low, close)
    or None on failure."""
    url = "https://fapi.binance.com/fapi/v1/klines"
    # Pull a 1-minute window starting AT ts (1m kline starts on the minute mark)
    minute_start = (ts_unix_ms // 60_000) * 60_000
    params = urllib.parse.urlencode({
        "symbol": to_binance_perp(symbol),
        "interval": "1m",
        "startTime": minute_start,
        "endTime": minute_start + 60_000,
        "limit": 1,
    })
    try:
        with urllib.request.urlopen(f"{url}?{params}", timeout=5) as r:
            data = json.loads(r.read())
            if not data:
                return None
            k = data[0]
            return {"open": float(k[1]), "high": float(k[2]),
                    "low": float(k[3]), "close": float(k[4])}
    except Exception as e:
        print(f"  binance fetch fail {symbol}: {e}")
        return None


# Real captured opens (signal_id, date, entry_lo, entry_hi, direction, channel-claimed-targets)
CAPTURED_OPENS = [
    {"signal_id": 2143, "symbol": "POL", "direction": "long",
     "date": "2026-05-25T03:45:01+00:00",
     "entry_lo": 0.0894, "entry_hi": 0.0900, "sl": 0.0810,
     "targets": [0.0945, 0.0990, 0.1050, 0.1125, 0.1200, 0.1300, 0.1400, 0.1500]},
    {"signal_id": 2144, "symbol": "HYPE", "direction": "long",
     "date": "2026-05-27T03:23:32+00:00",
     "entry_lo": 56.80, "entry_hi": 57.00, "sl": 52.00,
     "targets": [59.50, 62.00, 65.00, 68.00, 72.00, 77.00, 83.00, 90.00]},
]

MAX_SLIPPAGE_PCT = 3.0


def simulate_open(o, kline_open_price):
    """Return what the receiver would have decided given an opening price."""
    if kline_open_price is None:
        return ("no_data", None)
    if o["direction"] == "long":
        bound = o["entry_hi"]
        slip = (kline_open_price - bound) / bound * 100.0
    else:
        bound = o["entry_lo"]
        slip = (bound - kline_open_price) / bound * 100.0
    breach = slip > MAX_SLIPPAGE_PCT
    # Target check
    if o["direction"] == "long":
        ahead = [t for t in o["targets"] if t > kline_open_price]
    else:
        ahead = [t for t in o["targets"] if t < kline_open_price]
    return ({
        "mark": kline_open_price,
        "slippage_pct": round(slip, 2),
        "slippage_breach": breach,
        "targets_remaining": ahead,
        "targets_crossed": len(o["targets"]) - len(ahead),
        "decision": "skip(slippage)" if breach
                    else "skip(all_targets_crossed)" if not ahead
                    else "open",
    }, slip)


def analyze_slippage_replay():
    print()
    print(f"=== (B) Slippage gate replay (cap={MAX_SLIPPAGE_PCT}%) ===")
    for o in CAPTURED_OPENS:
        ts = datetime.fromisoformat(o["date"]).timestamp() * 1000
        kline = fetch_binance_kline_1m(o["symbol"], int(ts))
        print(f"\nSignal #{o['signal_id']} {o['symbol']} {o['direction'].upper()}  "
              f"posted {o['date']}")
        print(f"  Signal entry: {o['entry_lo']} – {o['entry_hi']}  SL={o['sl']}")
        if not kline:
            print(f"  Binance kline: UNAVAILABLE")
            continue
        # The 1m kline open price is the actual fill rate a market order would
        # have hit at channel-post + (sub-second) — the cleanest proxy for
        # what our fast-path receiver would see for mark.
        verdict, _ = simulate_open(o, kline["open"])
        print(f"  Binance 1m kline @ minute of post:")
        print(f"    open={kline['open']}  high={kline['high']}  "
              f"low={kline['low']}  close={kline['close']}")
        if isinstance(verdict, tuple):
            print(f"  no kline data")
            continue
        v = verdict
        print(f"  Mark used:      {v['mark']}")
        print(f"  Slippage:       {v['slippage_pct']}%  (cap {MAX_SLIPPAGE_PCT}%)  "
              f"{'BREACH' if v['slippage_breach'] else 'OK'}")
        print(f"  Targets crossed: {v['targets_crossed']} / {len(o['targets'])}, "
              f"remaining: {v['targets_remaining']}")
        print(f"  Decision:       {v['decision']}")


def main():
    msgs_by_id, cls_by_id = load_corpus()
    if not cls_by_id:
        print("WARN: no Claude classifications found — only running slippage replay")
    else:
        r = analyze_fast_path(msgs_by_id, cls_by_id)
        print_fast_path_report(r)
    analyze_slippage_replay()


if __name__ == "__main__":
    main()
