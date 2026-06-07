"""
papertrading.parser
~~~~~~~~~~~~~~~~~~~~
Parses Telegram messages into structured trade-open signals and management events.

Key functions:
  parse_opens(text, known_coins) -> list[dict]   -- detect new trade opens
  parse_details(text)            -> dict          -- extract entry/sl/tp from reply
  parse_management(text)         -> dict|None     -- detect close / SL-move / partial-close
  coins_mentioned_on_first_line(text, known_coins) -> list[str]
"""
import re
from typing import Optional


# --- Regex patterns -----------------------------------------------------------

COIN_DIR_RE = re.compile(
    r'^([A-Z0-9]{2,15})\s+(Long|Short)\b',
    re.IGNORECASE | re.MULTILINE,
)

ENTRY_RANGE_RE = re.compile(
    r'Entry(?:\s+zone)?[:\s]+([0-9,._]+)(?![0-9,.])\s*[-\u2013\u2014]\s*([0-9,._]+)',
    re.IGNORECASE,
)

ENTRY_SINGLE_RE = re.compile(
    r'Entry(?:\s+zone)?[:\s]+([0-9,._]+)(?![0-9,.])(?!\s*%)',
    re.IGNORECASE,
)

BARE_RANGE_RE = re.compile(
    r'^\s*([0-9]+[0-9,._]*)\s*[-\u2013\u2014]\s*([0-9]+[0-9,._]*)\s*$',
    re.MULTILINE,
)

SL_RE = re.compile(r'\bS\.?L\.?\s*[:\-\u2013]?\s*([0-9,._]+)', re.IGNORECASE)

TP_RE = re.compile(
    r'(?:^|\b)(?:\d\s+)?(?:Target|TP(?:\d(?!\d))?)\s*[:\-\u2013]?\s*([0-9,._]+)',
    re.IGNORECASE | re.MULTILINE,
)

_FULL_CLOSE_RE = re.compile(
    r'\b(full\s+close|fully\s+clos|close\s+all|closed?\s+all|got\s+stopped|stop(?:ped)?)\b',
    re.IGNORECASE,
)
_PARTIAL_CLOSE_RE = re.compile(r'\bclose\s+(\d+)\s*%', re.IGNORECASE)
_MOVE_SL_RE = re.compile(r'\bS\.?L\.?\s+to\s+(breakeven|([0-9,._]+))', re.IGNORECASE)


# --- Helpers ------------------------------------------------------------------

def normalize(text) -> str:
    if isinstance(text, list):
        text = "".join(p if isinstance(p, str) else p.get("text", "") for p in text)
    return text.replace("\u200b", "").replace("\u00a0", " ").strip()


def parse_float(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", "").replace("_", "").rstrip("."))
    except (ValueError, AttributeError):
        return None


def _parse_entry(section: str) -> Optional[float]:
    m = ENTRY_RANGE_RE.search(section)
    if m:
        lo, hi = parse_float(m.group(1)), parse_float(m.group(2))
        if lo and hi:
            return (lo + hi) / 2

    m = ENTRY_SINGLE_RE.search(section)
    if m:
        return parse_float(m.group(1))

    m = BARE_RANGE_RE.search(section)
    if m:
        lo, hi = parse_float(m.group(1)), parse_float(m.group(2))
        if lo and hi:
            return (lo + hi) / 2

    return None


def _parse_sl(section: str) -> Optional[float]:
    m = SL_RE.search(section)
    return parse_float(m.group(1)) if m else None


def _parse_tp(section: str) -> Optional[float]:
    m = TP_RE.search(section)
    return parse_float(m.group(1)) if m else None


# --- Management parser --------------------------------------------------------

def parse_management(text) -> Optional[dict]:
    """
    Detect trade management signals in a message.

    Returns a dict with key "kind" plus optional details, or None.

    Kinds:
      "close_full"    -- full position close ("Full close", "Got stopped", ...)
      "close_partial" -- partial close with pct ("Close 50%"); may include sl
      "move_sl"       -- stop-loss move; sl=price or sl="breakeven"
    """
    text = normalize(text)

    if _FULL_CLOSE_RE.search(text):
        return {"kind": "close_full"}

    m = _PARTIAL_CLOSE_RE.search(text)
    if m:
        event = {"kind": "close_partial", "pct": float(m.group(1))}
        mv = _MOVE_SL_RE.search(text)
        if mv:
            val = mv.group(1)
            event["sl"] = "breakeven" if val.lower() == "breakeven" else parse_float(val)
        return event

    m = _MOVE_SL_RE.search(text)
    if m:
        val = m.group(1)
        return {
            "kind": "move_sl",
            "sl":   "breakeven" if val.lower() == "breakeven" else parse_float(val),
        }

    return None


# --- Main parser --------------------------------------------------------------

def parse_opens(text: str, known_coins: Optional[set] = None) -> list:
    """
    Parse a message and return a list of trade-open dicts.

    Each dict: {"symbol": str, "direction": str, "entry": float|None,
                "sl": float|None, "tp": float|None}
    """
    text = normalize(text)

    headers = []
    for m in COIN_DIR_RE.finditer(text):
        raw = m.group(1).upper()
        direction = m.group(2).upper()
        coin = re.sub(r'(USDT|USDC|BUSD|PERP)$', '', raw) or raw
        if known_coins is not None and coin not in known_coins:
            continue
        headers.append((m.start(), coin, direction))

    if not headers:
        return []

    results = []
    for i, (start, coin, direction) in enumerate(headers):
        body_start = text.index("\n", start) + 1 if "\n" in text[start:] else len(text)
        body_end = headers[i + 1][0] if i + 1 < len(headers) else len(text)
        section = text[body_start:body_end]

        results.append({
            "symbol":    coin,
            "direction": direction,
            "entry":     _parse_entry(section),
            "sl":        _parse_sl(section),
            "tp":        _parse_tp(section),
        })

    return results


# --- Follow-up / reply parser -------------------------------------------------

def parse_details(text) -> dict:
    """Extract entry/sl/tp from a reply with no coin/direction header."""
    text = normalize(text)
    return {
        "entry": _parse_entry(text),
        "sl":    _parse_sl(text),
        "tp":    _parse_tp(text),
    }


def coins_mentioned_on_first_line(text, known_coins: set) -> list:
    """
    Return any known coin names that appear on the first line of the message.
    Used for time-based follow-up linking.
    """
    text = normalize(text)
    first_line = text.split("\n")[0].upper()
    return [c for c in known_coins if re.search(rf'\b{re.escape(c)}\b', first_line)]


# --- Backward-compat shim -----------------------------------------------------

def try_parse_open(msg: dict, known_coins: Optional[set] = None) -> Optional[dict]:
    opens = parse_opens(msg.get("text", ""), known_coins)
    return opens[0] if opens else None
