"""Parser-free simulator driven by LLM classifications.

Reads classifications.jsonl + last_month_messages.json, walks events
chronologically, and produces Trade objects compatible with the prototype's
Trade/TradeEvent dataclasses. The output is fed into weex.resolve_exits
(Eduardo's chronological PnL walker — unchanged).

Open-merge rule:
  An "open" classification with no entry/sl/tp that refers to a coin which
  has another open within 30 minutes BEFORE it (same direction) is treated
  as a detail-fill — its entry/sl/tp updates the prior open, no new trade.
  Conversely, if an "open" has entry/sl/tp but the prior open did not,
  the prior open absorbs the details (most common pattern: header msg
  then reply with numbers).

Symbol resolution for management events:
  1. If classification carries `symbol` → use it.
  2. If `applies_to` → fan out to each coin (one event per coin).
  3. Otherwise: walk back through the message's reply chain to find the
     nearest ancestor that classifies as `open` and use its symbol.
  4. If still unresolved: try first-line coin mention in the original text.
  5. Last resort: skip event (logged as 'unresolved').

Market-entry policy:
  If a trade is opened with entry="market" (or no parsed entry) but has a
  valid SL, fill the entry via weex.get_price_at(signal_timestamp). This
  recovers the ~25% of "by market" trades that the regex skipped.
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
LOCAL = HERE / "_local"
OUT = HERE / "out"
sys.path.insert(0, str(LOCAL))

from simulator import Trade, TradeEvent  # noqa: E402
from weex import get_price_at, resolve_exits  # noqa: E402

ACCOUNT = 1000.0
RISK_PER_TRADE = 10.0
MARGIN_PER_TRADE = 50.0
OPEN_MERGE_WINDOW_SECONDS = 1800  # 30 minutes


def load_classifications():
    cls = {}
    for path in sorted(OUT.glob("classifications_*.jsonl")):
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            cls[obj["id"]] = obj
    return cls


def load_messages():
    content = (LOCAL / "last_month_messages.json").read_text()
    msgs, _ = json.JSONDecoder().raw_decode(content)
    return msgs


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def ms(s):
    return int(parse_dt(s).timestamp() * 1000)


def resolve_symbol(msg, by_id, cls_by_id, fallback_known_coins):
    """Walk reply chain to find nearest open's symbol; fall back to text scan."""
    # Walk parent chain
    visited = set()
    cur = msg.get("reply_to_msg_id")
    while cur and cur not in visited and cur in by_id:
        visited.add(cur)
        parent_cls = cls_by_id.get(cur)
        if parent_cls and parent_cls.get("kind") == "open" and parent_cls.get("symbol"):
            return parent_cls["symbol"]
        cur = by_id[cur].get("reply_to_msg_id")
    # First-line coin scan
    text = msg.get("text", "")
    first_line = text.split("\n")[0]
    import re
    for w in re.findall(r"\b([A-Z][A-Z0-9]{1,14})\b", first_line):
        if w in fallback_known_coins:
            return w
    return None


def build_trades(classifications, messages):
    """Walk all messages chronologically, materialize trades + events."""
    by_id = {m["id"]: m for m in messages}
    msgs_sorted = sorted(messages, key=lambda m: m["date"])

    # Active open trades, keyed by (symbol, direction). Value is the most
    # recent Trade object. A trade becomes "closed" once we record a
    # close_full event for it (then it stops being a target for new events).
    active = {}  # (symbol, direction) -> Trade
    trades = []

    # Known coin universe — grows as we see opens.
    known_coins = set()

    for msg in msgs_sorted:
        cls = classifications.get(msg["id"])
        if not cls:
            continue
        kind = cls.get("kind")

        if kind == "open":
            symbol = cls.get("symbol")
            applies_to = cls.get("applies_to")
            direction = cls.get("direction")
            entry = cls.get("entry")
            entry_range = cls.get("entry_range")
            sl = cls.get("sl")
            tp = cls.get("tp")
            if isinstance(sl, str) and sl != "breakeven":
                sl = None  # only "breakeven" string is allowed; coerce others

            # Pick entry value: midpoint of range, or raw number, or "market".
            entry_val = None
            if isinstance(entry, (int, float)):
                entry_val = float(entry)
            elif entry == "market":
                entry_val = "market"
            elif entry_range and len(entry_range) == 2:
                lo, hi = entry_range
                if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                    entry_val = (lo + hi) / 2

            # Multi-coin opens (applies_to without single symbol): create one
            # trade per coin.
            target_coins = applies_to if applies_to else ([symbol] if symbol else [])
            if not target_coins or not direction:
                # Detail-only reply with no parent context yet — best-effort
                # merge into the most recent active open in our reply chain.
                cur = msg.get("reply_to_msg_id")
                while cur and cur in by_id:
                    pcls = classifications.get(cur)
                    if pcls and pcls.get("kind") == "open" and pcls.get("symbol"):
                        symbol = pcls["symbol"]
                        direction = pcls.get("direction")
                        break
                    cur = by_id[cur].get("reply_to_msg_id")
                if symbol and direction:
                    target_coins = [symbol]

            for coin in target_coins:
                key = (coin, direction.upper() if direction else None)
                known_coins.add(coin)
                if key[1] is None:
                    continue

                existing = active.get(key)
                msg_ms = ms(msg["date"])
                if existing is not None:
                    existing_ms = ms(existing.date)
                    # Merge if recent and existing lacks details
                    recent = (msg_ms - existing_ms) <= OPEN_MERGE_WINDOW_SECONDS * 1000
                    if recent:
                        # Fill missing fields on the existing trade
                        if existing.entry is None and entry_val is not None:
                            existing.entry = entry_val
                        if existing.sl is None and sl is not None:
                            existing.sl = sl
                        if existing.tp is None and tp is not None:
                            existing.tp = tp
                        existing.events.append(TradeEvent(
                            msg_id=msg["id"], date=msg["date"], kind="detail",
                            text=msg.get("text", ""),
                        ))
                        continue

                # New trade
                t = Trade(
                    msg_id=msg["id"],
                    date=msg["date"],
                    symbol=coin,
                    direction=key[1],  # LONG or SHORT
                    entry=entry_val if entry_val != "market" else None,
                    sl=sl if isinstance(sl, (int, float)) else None,
                    tp=tp,
                    events=[],
                )
                # Track market-entry flag via a custom attribute so we can
                # fill the price later from WEEX.
                t.market_entry = (entry_val == "market") or (entry_val is None and entry_range is None)
                # Sanity-check SL direction
                if t.entry is not None and t.sl is not None:
                    if t.direction == "LONG" and t.sl >= t.entry:
                        t.sl = None
                    elif t.direction == "SHORT" and t.sl <= t.entry:
                        t.sl = None
                trades.append(t)
                active[key] = t

        elif kind in ("close_full", "close_partial", "move_sl", "increase"):
            symbol = cls.get("symbol")
            applies_to = cls.get("applies_to")
            target_coins = applies_to if applies_to else ([symbol] if symbol else [])

            if not target_coins:
                resolved = resolve_symbol(msg, by_id, classifications, known_coins)
                if resolved:
                    target_coins = [resolved]

            for coin in target_coins:
                # Try both directions — match the one with an active trade
                for direction in ("LONG", "SHORT"):
                    key = (coin, direction)
                    t = active.get(key)
                    if not t:
                        continue

                    ev_sl = cls.get("sl")
                    if isinstance(ev_sl, str) and ev_sl != "breakeven":
                        ev_sl = None

                    ev = TradeEvent(
                        msg_id=msg["id"],
                        date=msg["date"],
                        kind=kind,
                        pct=cls.get("pct"),
                        sl=ev_sl,
                        text=msg.get("text", ""),
                    )
                    t.events.append(ev)

                    if kind == "close_full":
                        t.exit_reason = "manual"  # weex.resolve_exits resets this
                        # Mark this trade no longer active for future events
                        active.pop(key, None)
                    break

    trades.sort(key=lambda t: t.date)
    return trades


def fill_market_entries(trades):
    """For trades with market entry + valid SL, fill entry via WEEX open price."""
    filled = 0
    for t in trades:
        if getattr(t, "market_entry", False) and t.entry is None and t.sl is not None:
            try:
                price = get_price_at(f"{t.symbol}USDT", ms(t.date))
                if price:
                    t.entry = float(price)
                    filled += 1
                    # Re-validate SL direction
                    if t.direction == "LONG" and t.sl >= t.entry:
                        t.sl = None
                    elif t.direction == "SHORT" and t.sl <= t.entry:
                        t.sl = None
            except Exception:
                pass
    print(f"market-entry fills: {filled} trades got entry from WEEX")


def sl_distance_pct(entry, sl):
    # Guard against entry="market" sneaking past fill_market_entries (e.g.
    # WEEX lookup failed). Prior version raised TypeError comparing str <= 0.
    if entry is None or sl is None or isinstance(sl, str) or isinstance(entry, str) or entry <= 0:
        return None
    return abs(entry - sl) / entry


def position_for(entry, sl):
    d = sl_distance_pct(entry, sl)
    if d is None or d <= 0:
        return None
    return RISK_PER_TRADE / d


def trade_to_dict(t, position_notional, leverage, scaled_pnl):
    from dataclasses import asdict
    d = asdict(t)
    d["events"] = [
        {
            "msg_id": e.msg_id,
            "date": e.date,
            "kind": e.kind,
            "pct": e.pct,
            "sl": e.sl,
            "text": e.text,
        }
        for e in t.events
    ]
    d["position_notional"] = position_notional
    d["leverage"] = leverage
    d["sl_distance_pct"] = sl_distance_pct(t.entry, t.sl)
    d["scaled_pnl"] = scaled_pnl
    d["market_entry"] = getattr(t, "market_entry", False)
    return d


def main():
    classifications = load_classifications()
    messages = load_messages()
    print(f"loaded {len(classifications)} classifications, {len(messages)} messages")

    trades = build_trades(classifications, messages)
    print(f"materialized {len(trades)} trades")

    fill_market_entries(trades)

    sized = [
        t for t in trades
        if t.entry is not None and position_for(t.entry, t.sl) is not None
    ]
    skipped = len(trades) - len(sized)
    print(f"sized: {len(sized)} / {len(trades)}   skipped: {skipped} (no SL or no entry)")

    print(f"resolving exits via WEEX (fractional units)...", flush=True)
    resolve_exits(sized, position_size=1.0)

    out_trades = []
    pnl_total = 0.0
    leverages = []
    for t in trades:
        pos = position_for(t.entry, t.sl) if t.entry else None
        lev = (pos / MARGIN_PER_TRADE) if pos else None
        scaled = round(pos * (t.pnl or 0), 2) if pos else None
        if scaled is not None:
            pnl_total += scaled
        if lev is not None:
            leverages.append(lev)
        out_trades.append(trade_to_dict(t, pos, lev, scaled))

    out = {
        "source": "llm",
        "n_messages": len(messages),
        "n_classifications": len(classifications),
        "n_trades_parsed": len(trades),
        "n_trades_sized": len(sized),
        "n_skipped": skipped,
        "account_usd": ACCOUNT,
        "risk_per_trade_usd": RISK_PER_TRADE,
        "margin_per_trade_usd": MARGIN_PER_TRADE,
        "total_pnl_usd": round(pnl_total, 2),
        "account_return_pct": round(pnl_total / ACCOUNT * 100, 2),
        "avg_leverage": round(sum(leverages) / len(leverages), 1) if leverages else None,
        "trades": out_trades,
    }

    op = OUT / "trades_llm.json"
    op.write_text(json.dumps(out, indent=2, default=str))
    print(f"wrote {op}", flush=True)
    print(f"PnL: ${pnl_total:.2f}  ({pnl_total / ACCOUNT * 100:.2f}% on ${ACCOUNT:.0f})")
    print(f"avg leverage: {out['avg_leverage']}x")


if __name__ == "__main__":
    main()
