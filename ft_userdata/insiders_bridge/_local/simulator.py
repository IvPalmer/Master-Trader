"""
papertrading.simulator
~~~~~~~~~~~~~~~~~~~~~~~~
Simulates paper trades from parsed open signals.

Follow-up linking uses two rules:
  1. Reply-based: messages that reply (directly or transitively) to the trade root.
  2. Time-based:  standalone messages (no reply) that mention an open coin on their
     first line AND contain a management keyword — linked until the trade is closed.
"""
from dataclasses import dataclass, field
from typing import Optional

from parser import coins_mentioned_on_first_line, parse_details, parse_management, parse_opens


# --- Data model ---------------------------------------------------------------

@dataclass
class TradeEvent:
    msg_id: int
    date: str
    kind: str                     # "detail" | "close_full" | "close_partial" | "move_sl"
    pct: Optional[float] = None   # close_partial: % closed
    sl: Optional[object] = None   # move_sl / close_partial: new SL price or "breakeven"
    text: str = ""


@dataclass
class Trade:
    msg_id: int
    date: str
    symbol: str
    direction: str           # LONG or SHORT
    entry: Optional[float]   # None = market order
    sl: Optional[float]
    tp: Optional[float]
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None   # "tp" | "sl" | "open" | "manual"
    pnl: Optional[float] = None         # in USD, assuming position_size
    events: list = field(default_factory=list)  # list[TradeEvent]


# --- Thread builder (reply-based) --------------------------------------------

def _build_reply_threads(messages: list) -> dict:
    """
    Group messages into reply threads keyed by root message ID.
    Returns {root_id: [root_msg, reply1, ...]} sorted chronologically.
    Also returns the set of message IDs claimed by a reply thread.
    """
    by_id = {m["id"]: m for m in messages}
    threads = {}

    def root_of(msg_id):
        visited = set()
        current = msg_id
        while current not in visited:
            visited.add(current)
            parent = by_id.get(current, {}).get("reply_to_msg_id")
            if not parent or parent not in by_id:
                return current
            current = parent
        return current

    for msg in messages:
        root = root_of(msg["id"])
        threads.setdefault(root, [])
        if msg not in threads[root]:
            threads[root].append(msg)

    for root_id in threads:
        threads[root_id].sort(key=lambda m: m["date"])

    return threads


# --- Simulator ----------------------------------------------------------------

def simulate(messages: list, known_coins: Optional[set] = None,
             resolve_market_entries: bool = False) -> list:
    """
    Parse all trade opens from a list of Telegram messages.

    Follow-up rules:
      1. Reply threads: replies to the trade root fill entry/sl/tp and add events.
      2. Time-based: standalone messages that mention an open coin on the first
         line and contain a management keyword are attached to that trade.

    Args:
        messages:               list of message dicts (id, date, text)
        known_coins:            optional set of valid coin base names
        resolve_market_entries: if True, fetch Bybit price for market-entry trades

    Returns list of Trade objects, sorted by message date.
    """
    messages = sorted(messages, key=lambda m: m["date"])
    threads = _build_reply_threads(messages)

    # IDs claimed by a reply thread (non-root replies)
    reply_claimed = set()
    for root_id, thread_msgs in threads.items():
        for m in thread_msgs[1:]:
            reply_claimed.add(m["id"])

    trades = []
    # symbol -> list of currently-open Trade objects (closed ones removed as we go)
    open_by_symbol: dict = {}

    for root_id, thread_msgs in sorted(threads.items()):
        root_msg = thread_msgs[0]
        text = root_msg.get("text", "") or ""
        opens = parse_opens(text, known_coins)
        if not opens:
            continue

        for o in opens:
            # Fill entry/sl/tp and collect events from reply thread
            events = []
            for reply in thread_msgs[1:]:
                reply_text = reply.get("text", "") or ""

                mgmt = parse_management(reply_text)
                if mgmt:
                    events.append(TradeEvent(
                        msg_id=reply["id"],
                        date=reply["date"],
                        kind=mgmt["kind"],
                        pct=mgmt.get("pct"),
                        sl=mgmt.get("sl"),
                        text=reply_text,
                    ))
                else:
                    details = parse_details(reply_text)
                    if not o["entry"] and details["entry"]:
                        o["entry"] = details["entry"]
                    if not o["sl"] and details["sl"]:
                        o["sl"] = details["sl"]
                    if not o["tp"] and details["tp"]:
                        o["tp"] = details["tp"]
                    events.append(TradeEvent(
                        msg_id=reply["id"],
                        date=reply["date"],
                        kind="detail",
                        text=reply_text,
                    ))

            entry = o["entry"]
            sl = o["sl"]
            tp = o["tp"]

            # Sanity-check SL direction
            if entry and sl:
                if o["direction"] == "LONG" and sl >= entry:
                    sl = None
                elif o["direction"] == "SHORT" and sl <= entry:
                    sl = None

            trade = Trade(
                msg_id=root_msg["id"],
                date=root_msg["date"],
                symbol=o["symbol"],
                direction=o["direction"],
                entry=entry,
                sl=sl,
                tp=tp,
                events=events,
            )
            trades.append(trade)
            open_by_symbol.setdefault(o["symbol"], []).append(trade)

    # --- Time-based follow-up pass -------------------------------------------
    # Walk messages chronologically; for unclaimed, non-reply messages check if
    # they mention an open trade's coin on the first line + have a management signal.

    all_known = known_coins or set()

    for msg in messages:
        if msg["id"] in reply_claimed:
            continue
        # Skip root messages of trade opens (already processed above)
        if msg["id"] in {t.msg_id for t in trades}:
            continue
        # Only standalone messages (not replies to anything we track)
        if msg.get("reply_to_msg_id"):
            continue

        text = msg.get("text", "") or ""
        mgmt = parse_management(text)
        if not mgmt and not parse_details(text)["sl"] and not parse_details(text)["tp"]:
            # No management and no SL/TP detail — skip (avoid noise)
            continue

        mentioned = coins_mentioned_on_first_line(text, all_known or {t.symbol for t in trades})
        for coin in mentioned:
            for trade in open_by_symbol.get(coin, []):
                if trade.exit_reason == "manual":
                    continue
                if mgmt:
                    event = TradeEvent(
                        msg_id=msg["id"],
                        date=msg["date"],
                        kind=mgmt["kind"],
                        pct=mgmt.get("pct"),
                        sl=mgmt.get("sl"),
                        text=text,
                    )
                    trade.events.append(event)
                    if mgmt["kind"] == "close_full":
                        trade.exit_reason = "manual"
                else:
                    details = parse_details(text)
                    if not trade.sl and details["sl"]:
                        trade.sl = details["sl"]
                    if not trade.tp and details["tp"]:
                        trade.tp = details["tp"]
                    trade.events.append(TradeEvent(
                        msg_id=msg["id"],
                        date=msg["date"],
                        kind="detail",
                        text=text,
                    ))

    trades.sort(key=lambda t: t.date)

    if resolve_market_entries:
        from bybit import get_price_at
        from datetime import datetime

        market_trades = [t for t in trades if t.entry is None]
        if market_trades:
            print(f"  Fetching market prices for {len(market_trades)} trades...", flush=True)
        for trade in market_trades:
            try:
                dt = datetime.fromisoformat(trade.date.replace("Z", "+00:00"))
                price = get_price_at(f"{trade.symbol}USDT", int(dt.timestamp() * 1000))
                if price:
                    trade.entry = price
            except Exception:
                pass

    return trades


# --- Display ------------------------------------------------------------------

def _pct(a: float, b: float) -> str:
    return f"{abs(b - a) / a * 100:.1f}%"


def print_trade(trade: Trade) -> None:
    entry_str = f"{trade.entry:.6g}" if trade.entry else "market"

    if trade.sl and trade.entry:
        sl_str = f"{trade.sl:.6g} ({_pct(trade.entry, trade.sl)})"
    else:
        sl_str = f"{trade.sl:.6g}" if trade.sl else "—"

    if trade.tp and trade.entry:
        tp_str = f"{trade.tp:.6g} ({_pct(trade.entry, trade.tp)})"
    else:
        tp_str = f"{trade.tp:.6g}" if trade.tp else "—"

    pnl_str = ""
    if trade.pnl is not None:
        reason_icon = {"tp": "✅", "sl": "🔴", "open": "🟡", "manual": "🤝"}.get(trade.exit_reason, "")
        sign = "+" if trade.pnl >= 0 else ""
        pnl_pct = trade.pnl
        pnl_str = f"  {reason_icon} {sign}${trade.pnl:.2f} ({sign}{pnl_pct:.1f}%)"

    events_str = ""
    if trade.events:
        kinds = [e.kind for e in trade.events]
        events_str = f"  [{', '.join(kinds)}]"

    print(f"[{trade.date[:10]}] #{trade.msg_id:>5}  "
          f"{trade.symbol:<10} {trade.direction:<5}  "
          f"entry={entry_str:<12}  sl={sl_str:<22}  tp={tp_str}{pnl_str}{events_str}")


def print_summary(trades: list) -> None:
    total   = len(trades)
    with_sl = sum(1 for t in trades if t.sl)
    with_tp = sum(1 for t in trades if t.tp)
    market  = sum(1 for t in trades if not t.entry)

    pnl_trades = [t for t in trades if t.pnl is not None]
    print("\n" + "=" * 60)
    print(f"SUMMARY  ({total} trade opens parsed)")
    print(f"  With SL:       {with_sl}/{total}")
    print(f"  With TP:       {with_tp}/{total}")
    print(f"  Market entry:  {market}/{total}")
    if pnl_trades:
        tp_hits  = sum(1 for t in pnl_trades if t.exit_reason == "tp")
        sl_hits  = sum(1 for t in pnl_trades if t.exit_reason == "sl")
        manual   = sum(1 for t in pnl_trades if t.exit_reason == "manual")
        open_pos = sum(1 for t in pnl_trades if t.exit_reason == "open")
        total_pnl = sum(t.pnl for t in pnl_trades)
        sign = "+" if total_pnl >= 0 else ""
        print(f"\n  PnL trades:    {len(pnl_trades)}")
        print(f"  ✅ TP hits:     {tp_hits}")
        print(f"  🔴 SL hits:     {sl_hits}")
        print(f"  🤝 Manual close:{manual}")
        print(f"  🟡 Still open:  {open_pos}")
        print(f"  Total PnL:     {sign}${total_pnl:.2f}  (@ $100/trade)")
    print("=" * 60)
