"""Build trades from Binance Killers VIP classifications.

Different shape from Insiders Scalp:
  - Signal IDs (#NNNN) key the lifecycle, not reply chains.
  - Signal IDs RECYCLE across the 2-year corpus (multiple resets) → key by
    (signal_id, symbol) within a chronological window.
  - close_partial events carry cumulative realized profit% in their notes
    ("15.85% Profit (5x)" etc) — we trust the signaler's published number
    rather than re-simulating target hits.
  - SL-hits explicit: kind="close_full" with negative pct in notes.

Sizing mirrors Eduardo's risk-budget rule (consistency with Insiders Scalp
report): position_notional = $10 / sl_distance_pct  ($1k account, 1% risk).
"""
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
LOCAL = HERE / "_local"
OUT = HERE / "out"

CLASSIFICATIONS_GLOB = os.environ.get("CLASSIFICATIONS_GLOB", "classifications_killers_chunk*.jsonl")
MESSAGES_PATH = os.environ.get("MESSAGES_PATH", str(LOCAL / "killers_messages.json"))
OUTPUT_PATH = os.environ.get("OUTPUT_PATH", str(OUT / "trades_killers.json"))

ACCOUNT = 1000.0
RISK_PER_TRADE = 10.0
MARGIN_PER_TRADE = 50.0

PCT_RE = re.compile(r"([+\-]?\d+(?:\.\d+)?)\s*%")
SIGNAL_ID_TEXT_RE = re.compile(r"#\s*(\d+)")


def load_classifications():
    cls = {}
    for path in sorted(OUT.glob(CLASSIFICATIONS_GLOB)):
        for line in path.read_text().splitlines():
            if line.strip():
                o = json.loads(line)
                cls[o["id"]] = o
    return cls


def load_messages():
    msgs = json.loads(Path(MESSAGES_PATH).read_text())
    return {m["id"]: m for m in msgs}


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def extract_published_pct(notes: str) -> float | None:
    """Extract realized profit% from notes. Positive for wins, negative for losses."""
    if not notes:
        return None
    pcts = [float(m.group(1)) for m in PCT_RE.finditer(notes)]
    if not pcts:
        return None
    # Take MAX absolute value — for Killers, this is typically the cumulative gain
    return max(pcts, key=abs)


def normalize_entry_range(entry, entry_range):
    if entry_range and isinstance(entry_range, list) and len(entry_range) == 2:
        try:
            return float(entry_range[0]), float(entry_range[1])
        except (TypeError, ValueError):
            return None, None
    if isinstance(entry, (int, float)):
        return float(entry), float(entry)
    return None, None


def main():
    cls = load_classifications()
    msgs = load_messages()
    print(f"loaded {len(cls)} classifications, {len(msgs)} messages")

    # Build trades. Key: (signal_id, symbol) within a chronological window
    # (treat IDs as recycled if more than 90 days separate two opens with same key).
    trades = {}            # key -> trade dict
    last_open_for = {}     # (sid, sym) -> trade key (most recent)

    # Sort classifications by msg id (== chronological in this corpus)
    for cid in sorted(cls.keys()):
        o = cls[cid]
        msg = msgs.get(cid)
        if not msg:
            continue
        sid = o.get("signal_id")
        sym = o.get("symbol")
        kind = o.get("kind")
        msg_date = parse_dt(msg["date"])

        if kind == "open":
            if not sid or not sym:
                # GEM/MEGA signals without #NNNN — synth key
                tkey = ("synth", sym or "?", cid)
            else:
                # Check for recycle
                prev_key = last_open_for.get((sid, sym))
                if prev_key and prev_key in trades:
                    prev_date = trades[prev_key]["open_date"]
                    days = (msg_date - parse_dt(prev_date)).days
                    if days > 90 and trades[prev_key].get("closed"):
                        # Treat as new trade (recycled ID)
                        tkey = (sid, sym, msg_date.year, msg_date.month)
                    else:
                        # Same trade lifecycle; this is a re-announcement
                        continue
                else:
                    tkey = (sid, sym, msg_date.year, msg_date.month)
            e_lo, e_hi = normalize_entry_range(o.get("entry"), o.get("entry_range"))
            entry_mid = (e_lo + e_hi) / 2 if (e_lo is not None and e_hi is not None) else None
            sl = o.get("sl")
            sl_num = float(sl) if isinstance(sl, (int, float)) else None
            trades[tkey] = {
                "signal_id": sid,
                "symbol": sym,
                "direction": o.get("direction"),
                "entry_range": [e_lo, e_hi] if e_lo is not None else None,
                "entry_mid": entry_mid,
                "sl": sl_num,
                "sl_raw": sl,
                "open_msg_id": cid,
                "open_date": msg["date"],
                "open_confidence": o.get("confidence"),
                "events": [],
                "max_pct": 0.0,
                "final_pct": None,
                "closed": False,
                "close_reason": None,
                "close_msg_id": None,
            }
            last_open_for[(sid, sym)] = tkey

        elif kind in ("close_partial", "close_full", "move_sl", "increase"):
            if not sid or not sym:
                continue  # un-linkable event
            tkey = last_open_for.get((sid, sym))
            if not tkey or tkey not in trades:
                continue  # orphan management
            trade = trades[tkey]
            pct = extract_published_pct(o.get("notes", ""))
            event = {
                "msg_id": cid,
                "date": msg["date"],
                "kind": kind,
                "pct": pct,
                "notes": o.get("notes", ""),
            }
            trade["events"].append(event)

            if kind == "close_partial":
                if pct is not None and abs(pct) > abs(trade["max_pct"]):
                    trade["max_pct"] = pct
            elif kind == "close_full":
                trade["closed"] = True
                trade["close_msg_id"] = cid
                trade["close_reason"] = "sl_hit" if (pct is not None and pct < 0) else "tp_or_manual"
                trade["final_pct"] = pct if pct is not None else trade["max_pct"]
                if pct is not None and abs(pct) > abs(trade["max_pct"]):
                    trade["max_pct"] = pct
            elif kind == "move_sl":
                new_sl = o.get("sl")
                if isinstance(new_sl, (int, float)):
                    trade["sl"] = float(new_sl)
                event["new_sl"] = new_sl

    # Apply sizing
    out_trades = []
    n_sized = 0
    pnl_total = 0.0
    leverages = []
    for tkey, t in trades.items():
        sl_dist = None
        pos = None
        lev = None
        realized_pct = t["final_pct"] if t["final_pct"] is not None else t["max_pct"]
        scaled_pnl = None

        if t["entry_mid"] and t["sl"]:
            sl_dist = abs(t["entry_mid"] - t["sl"]) / t["entry_mid"]
            if sl_dist > 0:
                pos = RISK_PER_TRADE / sl_dist
                lev = pos / MARGIN_PER_TRADE
                n_sized += 1
                leverages.append(lev)
                # Channel publishes profit at "(5x)" — divide by leverage to get
                # underlying pct move, then scale by our notional.
                # Their "% Profit (5x)" = price_move% × 5. Underlying = published_pct / 5.
                # Our PnL = position_notional × (underlying_pct/100)
                # But we don't know if every signal was 5x... safer: use published pct
                # as-is on $50 margin (their position basis).
                if realized_pct is not None:
                    scaled_pnl = round(MARGIN_PER_TRADE * realized_pct / 100, 2)
                    pnl_total += scaled_pnl

        out_trades.append({
            "key": list(tkey) if isinstance(tkey, tuple) else tkey,
            "signal_id": t["signal_id"],
            "symbol": t["symbol"],
            "direction": t["direction"],
            "entry_range": t["entry_range"],
            "entry_mid": t["entry_mid"],
            "sl": t["sl"],
            "open_msg_id": t["open_msg_id"],
            "open_date": t["open_date"],
            "open_confidence": t["open_confidence"],
            "events": t["events"],
            "closed": t["closed"],
            "close_reason": t["close_reason"],
            "close_msg_id": t["close_msg_id"],
            "max_pct": t["max_pct"],
            "final_pct": t["final_pct"],
            "realized_pct": realized_pct,
            "sl_distance_pct": sl_dist,
            "position_notional": pos,
            "leverage": lev,
            "scaled_pnl": scaled_pnl,
        })

    # Linkage stats
    n_opens = sum(1 for t in out_trades)
    n_with_events = sum(1 for t in out_trades if t["events"])
    n_closed = sum(1 for t in out_trades if t["closed"])
    n_sl_hit = sum(1 for t in out_trades if t["close_reason"] == "sl_hit")
    n_win = sum(1 for t in out_trades if (t["realized_pct"] or 0) > 0)

    summary = {
        "source": "killers",
        "n_messages": len(msgs),
        "n_classifications": len(cls),
        "n_trades": n_opens,
        "n_trades_sized": n_sized,
        "n_trades_with_events": n_with_events,
        "n_trades_closed": n_closed,
        "n_sl_hit": n_sl_hit,
        "n_wins": n_win,
        "account_usd": ACCOUNT,
        "risk_per_trade_usd": RISK_PER_TRADE,
        "margin_per_trade_usd": MARGIN_PER_TRADE,
        "total_pnl_usd": round(pnl_total, 2),
        "account_return_pct": round(pnl_total / ACCOUNT * 100, 2),
        "avg_leverage": round(sum(leverages) / len(leverages), 1) if leverages else None,
        "trades": out_trades,
    }

    op = Path(OUTPUT_PATH)
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(summary, indent=2, default=str))
    print(f"wrote {op}")
    print()
    print(f"  trades:      {n_opens}")
    print(f"  sized:       {n_sized}   ({n_sized * 100 // max(1, n_opens)}%)")
    print(f"  with events: {n_with_events}   ({n_with_events * 100 // max(1, n_opens)}%)")
    print(f"  closed:      {n_closed}   ({n_closed * 100 // max(1, n_opens)}%)")
    print(f"  SL hits:     {n_sl_hit}")
    print(f"  wins:        {n_win}")
    print(f"  PnL:         ${pnl_total:.2f}  ({pnl_total/ACCOUNT*100:+.2f}% on ${ACCOUNT:.0f})")
    print(f"  avg lev:     {summary['avg_leverage']}x" if leverages else "  avg lev: n/a")


if __name__ == "__main__":
    main()
