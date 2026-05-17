"""LLM-style classifier for Insiders Scalp messages.

Implements the SYSTEM_PROMPT rules from docs/insiders-signals/validate_llm.py
as a pure-Python function. Same output schema as a Haiku 4.5 call against that
prompt — so swapping in real API calls later is a one-line change inside
`classify()` (return the JSON Haiku gives back instead of the rule output).

What this fixes vs the prototype's regex parser:

  1. Bare "stop" / "stopped" in chat is NOT a close_full.
     Only "got stopped", "got stopped out", "stopped at breakeven",
     "got stopped at breakeven", "fully stopped", "stop hit" count as closes.

  2. Multi-coin actions ("BTC and ETH", "BTC & ETH", "ETH and BTC") emit
     applies_to=[..] so the simulator fans out.

  3. "Close half" maps to close_partial pct=50.

  4. "Got stopped at breakeven" → kind=close_full but the simulator marks
     the exit as 'manual' (scratch), not 'sl'.

  5. Reply context: messages that mention an action but no coin inherit the
     symbol from their parent's resolved coin (handled by simulator, not
     classifier — classifier just emits applies_to=None when ambiguous).

  6. Open signals with details split across messages: the classifier emits
     'open' for the header (e.g. "BTC Short") AND emits 'open' for the
     follow-up detail message (e.g. "Entry 75800 SL 77300 TP 71000"). The
     simulator merges them when they refer to the same coin+direction.

Output schema per message (compact JSONL, one line each):
    {"id": int, "kind": str, ...optional fields...}
    kind ∈ {"open", "close_full", "close_partial", "move_sl", "increase", "chat"}

Run:
    python3 classifier.py
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
LOCAL = HERE / "_local"
OUT = HERE / "out"

# Coin universe: extract from prior known signals + a curated allowlist.
# This matches Haiku's behaviour of resolving coin tickers from context.
KNOWN_COINS = {
    "BTC", "ETH", "SOL", "PUMP", "FF", "WLFI", "FARTCOIN", "VIRTUAL", "AAVE",
    "MNT", "XPL", "ASTER", "DYDX", "APT", "DOT", "HYPE", "FIDA", "XTIU",
    "PEPE", "TST", "NEAR", "FIDAUSDT", "SKY", "USELESS",
}


_HEADER_RE = re.compile(
    r"^([A-Z][A-Z0-9]{1,14})(?:USDT|USDC)?\s+(Long|Short)\b",
    re.IGNORECASE | re.MULTILINE,
)

# Multi-coin headers like "BTC and ETH" / "BTC & ETH" / "ETH and BTC Shorts"
_MULTI_HEADER_RE = re.compile(
    r"\b([A-Z][A-Z0-9]{1,14})\s*(?:and|&|,)\s*([A-Z][A-Z0-9]{1,14})\b",
    re.IGNORECASE,
)


def _num(s):
    if s is None:
        return None
    try:
        return float(s.replace(",", "").replace("_", "").rstrip("."))
    except (ValueError, AttributeError):
        return None


def _parse_entry(text):
    # Range: "Entry 75800-76600" or "Entry: 0.245-0.255"
    m = re.search(
        r"Entry(?:\s+zone)?[:\s]+([0-9][0-9,._]*)\s*[-–—]\s*([0-9][0-9,._]*)",
        text, re.IGNORECASE,
    )
    if m:
        lo, hi = _num(m.group(1)), _num(m.group(2))
        if lo and hi:
            return None, [lo, hi]
    # "by market" / "By market"
    if re.search(r"\bby\s+market\b", text, re.IGNORECASE):
        return "market", None
    # Single: "Entry: 79-85" already caught; try single number
    m = re.search(r"Entry(?:\s+zone)?[:\s]+([0-9][0-9,._]*)(?!\s*%)",
                  text, re.IGNORECASE)
    if m:
        v = _num(m.group(1))
        if v:
            return v, None
    # Bare range on its own line: "84.7-86.5"
    m = re.search(r"^\s*([0-9][0-9,._]*)\s*[-–—]\s*([0-9][0-9,._]*)\s*$",
                  text, re.MULTILINE)
    if m:
        lo, hi = _num(m.group(1)), _num(m.group(2))
        if lo and hi:
            return None, [lo, hi]
    return None, None


def _parse_sl(text):
    # "SL: 77300" or "SL 77300" or "S.L. 77300" or "Stop loss to 80,933"
    m = re.search(r"\bS\.?L\.?\s*[:\-–]?\s*([0-9][0-9,._]*)", text, re.IGNORECASE)
    if m:
        v = _num(m.group(1))
        if v:
            return v
    # "stop loss to X" / "Moving the stop loss to X"
    m = re.search(r"\bstop\s*(?:[-_ ])?loss(?:\s+(?:to|at))?\s+([0-9][0-9,._]*)",
                  text, re.IGNORECASE)
    if m:
        v = _num(m.group(1))
        if v:
            return v
    return None


def _parse_tp(text):
    m = re.search(
        r"(?:^|\b)(?:\d\s+)?(?:Target|TP\d?|🎯Target)\s*[:\-–]?\s*([0-9][0-9,._]*)",
        text, re.IGNORECASE | re.MULTILINE,
    )
    if m:
        v = _num(m.group(1))
        if v:
            return v
    return None


def _parse_pct(text):
    m = re.search(r"\bclos(?:e|ing)\s+(\d+)\s*%", text, re.IGNORECASE)
    if m:
        return float(m.group(1))
    if re.search(r"\bclos(?:e|ing)\s+half\b", text, re.IGNORECASE):
        return 50.0
    return None


def _parse_move_sl(text):
    """Return new SL value if msg moves stop-loss; None otherwise."""
    # "SL to breakeven" / "Move SL to breakeven" / "Stop at breakeven"
    if re.search(r"\b(?:S\.?L\.?|stop(?:[\s-]?loss)?)\s+(?:to|at|should\s+be\s+at)\s+(?:be|breakeven)\b",
                 text, re.IGNORECASE):
        return "breakeven"
    if re.search(r"\bmov(?:e|ing)\s+(?:the\s+)?(?:S\.?L\.?|stop(?:[\s-]?loss)?)\s+(?:to|at)\s+(?:be|breakeven)\b",
                 text, re.IGNORECASE):
        return "breakeven"
    if re.search(r"\bS\.?L\.?\s+mo\s+to\s+breakeven\b", text, re.IGNORECASE):
        return "breakeven"
    # "SL to 77900" / "SL 77600!" / "Move SL to 88.1" / "Moving SL to 0.002075"
    m = re.search(
        r"\b(?:mov(?:e|ing)\s+(?:the\s+)?)?(?:S\.?L\.?|stop(?:[\s-]?loss)?)\s+(?:to|at|stays?\s+at|to\s+be\s+at)?\s*([0-9][0-9,._]*)",
        text, re.IGNORECASE,
    )
    if m:
        v = _num(m.group(1))
        if v:
            return v
    return None


def _is_full_close(text):
    """True if message is a manual close action.

    Strict — bare 'stop' or 'stopped' alone does NOT match.
    """
    t = text.lower()

    # Explicit close phrases
    if re.search(r"\bfull\s+close\b", t):
        return True
    if re.search(r"\bfully\s+clos(?:e|ed)\b", t):
        return True
    if re.search(r"\bclose\s+all\b", t):
        return True
    if re.search(r"\bclos(?:e|ed|ing)\s+(?:the\s+)?(?:position\s+)?fully\b", t):
        return True
    if re.search(r"\bclose\s+(?:the\s+)?long\b", t):
        return True
    if re.search(r"\bclose\s+(?:the\s+)?short\b", t):
        return True
    if re.search(r"\bclosed\s+at\s+breakeven\b", t):
        return True
    if re.search(r"\bclosing\s+(?:in\s+)?(?:hedge\s+)?(?:long|short)?\s*(?:in\s+small\s+profit|around\s+breakeven|at\s+breakeven|small\s+profit)\b", t):
        return True
    if re.search(r"\bclosing\s+in\s+small\s+profit\b", t):
        return True
    # Bare "Full close" on its own
    if t.strip() in {"full close", "fully closed", "fully close"}:
        return True

    # "Got stopped" / "Got stopped out" / "Got stopped at breakeven"
    if re.search(r"\bgot\s+stopp?ed\b", t):
        return True
    if re.search(r"\bgo\s+stopped\b", t):  # typo in dataset
        return True
    if re.search(r"\bstopped\s+out\b", t):
        return True
    if re.search(r"\bstopped\s+at\s+breakeven\b", t):
        return True
    # "Reached tp and fully closed"
    if re.search(r"\breached\s+tp\b", t):
        return True

    return False


def _is_close_partial(text):
    # Anything with "close N%" or "close half" or "closing N%"
    if _parse_pct(text) is not None:
        return True
    # "Close 50% of remaining" (already caught by pct)
    return False


def _is_increase(text):
    t = text.lower()
    # "Adding +N%" / "Add +N%" / "add +N% to ..."
    if re.search(r"\b(?:add(?:ing)?)\s*\+\s*\d+\s*%", t):
        return True
    # "Adding +30% to BTC short" — already caught
    if re.search(r"\bplace\s+a?\s*limit\s+order\s+at\s+[0-9][0-9,._]*\s+and\s+add\s+\+\s*\d+%", t):
        return True
    if re.search(r"\badding\s+back\s+what\s+i\s+closed\b", t):
        return True
    return False


def _detect_coins(text):
    """Return list of coin tickers mentioned on the first line of text.

    Used to resolve multi-coin actions and management mentions without
    explicit symbol.
    """
    first_line = text.split("\n")[0]
    found = []
    for w in re.findall(r"\b([A-Z][A-Z0-9]{1,14})\b", first_line):
        if w in KNOWN_COINS and w not in found:
            found.append(w)
    return found


def _opens_from_header(text, allow_no_known=True):
    """Find all '<COIN> Long/Short' headers. Return list of (coin, direction)."""
    out = []
    for m in _HEADER_RE.finditer(text):
        raw = m.group(1).upper()
        direction = m.group(2).lower()
        coin = re.sub(r"(USDT|USDC|BUSD|PERP)$", "", raw) or raw
        if not allow_no_known and coin not in KNOWN_COINS:
            continue
        out.append((coin, direction))
    # Multi-coin form: "BTC and ETH Shorts"
    mm = re.search(
        r"^([A-Z][A-Z0-9]{1,14})\s*(?:and|&)\s*([A-Z][A-Z0-9]{1,14})\s+(Long|Short)s?\b",
        text, re.IGNORECASE | re.MULTILINE,
    )
    if mm:
        c1, c2 = mm.group(1).upper(), mm.group(2).upper()
        direction = mm.group(3).lower()
        if c1 in KNOWN_COINS and c2 in KNOWN_COINS:
            for c in (c1, c2):
                if (c, direction) not in out:
                    out.append((c, direction))
    return out


def classify(msg, by_id):
    """Classify a single message dict.

    msg: {"id", "date", "text", "reply_to_msg_id"} from last_month_messages.json
    by_id: lookup of all messages by id (for parent/sibling context resolution)

    Returns dict matching the validate_llm.py SCHEMA, omitting null fields.
    """
    text = (msg.get("text") or "").strip()
    if not text:
        return {"id": msg["id"], "kind": "chat", "confidence": 0.95}

    parent_id = msg.get("reply_to_msg_id")
    parent_text = (by_id.get(parent_id) or {}).get("text", "") if parent_id else ""

    # ---------- OPEN ----------
    headers = _opens_from_header(text)
    if headers:
        # Single-coin standard form
        if len(headers) == 1:
            coin, direction = headers[0]
            entry, entry_range = _parse_entry(text)
            sl = _parse_sl(text)
            tp = _parse_tp(text)
            result = {
                "id": msg["id"],
                "kind": "open",
                "symbol": coin,
                "direction": direction,
                "confidence": 0.95,
            }
            if entry is not None:
                result["entry"] = entry
            if entry_range is not None:
                result["entry_range"] = entry_range
            if sl is not None:
                result["sl"] = sl
            if tp is not None:
                result["tp"] = tp
            return result
        # Multi-coin: emit one open per coin via applies_to (single message,
        # simulator will fan out). Use the first direction.
        coins = [c for c, _ in headers]
        directions = {d for _, d in headers}
        direction = directions.pop() if len(directions) == 1 else None
        sl = _parse_sl(text)
        tp = _parse_tp(text)
        entry, entry_range = _parse_entry(text)
        result = {
            "id": msg["id"], "kind": "open",
            "applies_to": coins, "direction": direction,
            "confidence": 0.9,
        }
        if entry is not None: result["entry"] = entry
        if entry_range is not None: result["entry_range"] = entry_range
        if sl is not None: result["sl"] = sl
        if tp is not None: result["tp"] = tp
        return result

    # ---------- DETAIL REPLY (entry/sl/tp without a header) ----------
    # If this is a reply to a known open and contains entry/sl/tp numbers,
    # treat it as an "open" detail-fill — symbol/direction inherited from parent.
    entry, entry_range = _parse_entry(text)
    sl = _parse_sl(text)
    tp = _parse_tp(text)
    if parent_id and (entry is not None or entry_range is not None or sl is not None or tp is not None):
        # Only count as detail-fill if there's no management verb and no
        # "Close X%" — otherwise it's a management event, not a detail.
        if (not _is_full_close(text) and not _is_close_partial(text)
                and _parse_move_sl(text) is None
                and not re.search(r"\bclose\b", text, re.IGNORECASE)):
            # Parent's header should give us coin/direction.
            parent_headers = _opens_from_header(parent_text or "")
            if parent_headers:
                coin, direction = parent_headers[0]
                result = {
                    "id": msg["id"], "kind": "open",
                    "symbol": coin, "direction": direction,
                    "confidence": 0.85,
                }
                if entry is not None: result["entry"] = entry
                if entry_range is not None: result["entry_range"] = entry_range
                if sl is not None: result["sl"] = sl
                if tp is not None: result["tp"] = tp
                return result

    # ---------- CLOSE FULL ----------
    if _is_full_close(text):
        coins_on_line = _detect_coins(text)
        # Resolve symbol via mentions or parent
        applies_to = None
        symbol = None
        if len(coins_on_line) > 1:
            applies_to = coins_on_line
        elif len(coins_on_line) == 1:
            symbol = coins_on_line[0]
        else:
            parent_coins = _detect_coins(parent_text)
            if len(parent_coins) == 1:
                symbol = parent_coins[0]
            elif len(parent_coins) > 1:
                applies_to = parent_coins
        result = {"id": msg["id"], "kind": "close_full", "confidence": 0.9}
        if symbol:
            result["symbol"] = symbol
        if applies_to:
            result["applies_to"] = applies_to
        return result

    # ---------- MOVE SL ----------
    move_sl_val = _parse_move_sl(text)
    if move_sl_val is not None and not _is_close_partial(text):
        coins_on_line = _detect_coins(text)
        applies_to = None
        symbol = None
        if len(coins_on_line) > 1:
            applies_to = coins_on_line
        elif len(coins_on_line) == 1:
            symbol = coins_on_line[0]
        else:
            parent_coins = _detect_coins(parent_text)
            if len(parent_coins) == 1:
                symbol = parent_coins[0]
        result = {"id": msg["id"], "kind": "move_sl", "sl": move_sl_val,
                  "confidence": 0.9}
        if symbol: result["symbol"] = symbol
        if applies_to: result["applies_to"] = applies_to
        return result

    # ---------- CLOSE PARTIAL ----------
    pct = _parse_pct(text)
    if pct is not None:
        coins_on_line = _detect_coins(text)
        applies_to = None
        symbol = None
        if len(coins_on_line) > 1:
            applies_to = coins_on_line
        elif len(coins_on_line) == 1:
            symbol = coins_on_line[0]
        else:
            parent_coins = _detect_coins(parent_text)
            if len(parent_coins) == 1:
                symbol = parent_coins[0]
            elif len(parent_coins) > 1:
                applies_to = parent_coins
        result = {"id": msg["id"], "kind": "close_partial", "pct": pct,
                  "confidence": 0.9}
        if symbol: result["symbol"] = symbol
        if applies_to: result["applies_to"] = applies_to
        # SL move alongside partial close
        sl_in_partial = _parse_move_sl(text)
        if sl_in_partial is not None:
            result["sl"] = sl_in_partial
        return result

    # ---------- INCREASE ----------
    if _is_increase(text):
        coins_on_line = _detect_coins(text)
        applies_to = None
        symbol = None
        if len(coins_on_line) > 1:
            applies_to = coins_on_line
        elif len(coins_on_line) == 1:
            symbol = coins_on_line[0]
        else:
            parent_coins = _detect_coins(parent_text)
            if len(parent_coins) == 1:
                symbol = parent_coins[0]
        sl_in_inc = _parse_move_sl(text)
        result = {"id": msg["id"], "kind": "increase", "confidence": 0.8}
        if symbol: result["symbol"] = symbol
        if applies_to: result["applies_to"] = applies_to
        if sl_in_inc is not None: result["sl"] = sl_in_inc
        return result

    # ---------- CHAT (default) ----------
    return {"id": msg["id"], "kind": "chat", "confidence": 0.85}


def main():
    content = (LOCAL / "last_month_messages.json").read_text()
    msgs, _ = json.JSONDecoder().raw_decode(content)
    by_id = {m["id"]: m for m in msgs}

    OUT.mkdir(exist_ok=True)
    op = OUT / "classifications.jsonl"
    counts = {}
    with op.open("w") as f:
        for msg in msgs:
            c = classify(msg, by_id)
            counts[c["kind"]] = counts.get(c["kind"], 0) + 1
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"wrote {sum(counts.values())} classifications to {op}")
    for k in sorted(counts, key=counts.get, reverse=True):
        print(f"  {k}: {counts[k]}")


if __name__ == "__main__":
    main()
