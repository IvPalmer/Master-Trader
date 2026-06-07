"""Rule-based fast-path parser for Killers VIP OPEN signals.

Skips the 7.6s Claude CLI hop for messages that look like a standard,
unambiguous OPEN. The classifier still runs in shadow downstream so
disagreements are visible, but the receiver POST fires immediately on
the rule output → fill time drops from ~9s to ~1-2s on clean opens.

NEVER fast-paths anything that isn't a complete, single-coin OPEN:
close/target/move_sl/increase/chat messages all fall through to Claude.

Output schema matches `classifier.classify()` so the receiver path is
identical regardless of which classifier emitted the structured event.
"""
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


# A clean OPEN has all of these line markers in the body. Anything missing
# → fall back to Claude.
_SIGNAL_ID_RE = re.compile(r"SIGNAL\s*ID\s*:\s*#?(\d+)", re.IGNORECASE)
_COIN_RE = re.compile(
    r"COIN\s*:\s*\$?([A-Z0-9]{1,15})\s*/\s*USDT?", re.IGNORECASE,
)
# 1 char min because some Binance perp tickers are single-char (e.g. $T = TUSDT).
_DIRECTION_RE = re.compile(
    r"Direction\s*:\s*(LONG|SHORT)\b", re.IGNORECASE,
)
# ENTRY can be a single value or a range. Examples:
#   "ENTRY: 56.80 - 57.00"  (range)
#   "ENTRY: 56.80"          (single)
# The numeric tokenizer is unsigned for the same reason as the target
# parser — the channel uses `-` as the range separator, sometimes without
# a leading space ("56.80 -57.00").
# Capture everything after `ENTRY:` until end of line so we can detect
# malformed signals with 3+ numbers (channel format is always 1 or 2 values).
_ENTRY_RE = re.compile(
    r"ENTRY\s*:\s*(.+?)(?:\r?\n|$)", re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_SL_RE = re.compile(
    r"STOP\s*LOSS\s*:\s*([\d.,]+)", re.IGNORECASE,
)
# Leverage hint: "(2-5x)" or "(5x)" — optional, we just extract the high
# end as a sizing hint when present.
_LEVERAGE_RE = re.compile(r"\((\d+)\s*[-–]\s*(\d+)?\s*x\)", re.IGNORECASE)
# A signal title is preceded by 📍 emoji or contains "SIGNAL ID:" — both work.
# We further require the body to NOT mention TARGET HIT / CLOSED / PROFIT /
# Target 1 / etc., which are management-message markers; those go to Claude.
_MGMT_MARKERS_RE = re.compile(
    r"(target\s*\d|tp\d|✅|Profit\s*\(|CLOSED|Stop\s*Loss\s*Hit|Stop\s*Loss\s*Triggered|"
    r"Move\s*SL|breakeven|hit\s*target|target\s*hit|increase)",
    re.IGNORECASE,
)


def _parse_number(s: str) -> Optional[float]:
    """Tolerant float parser. Accepts `.` or `,` as decimal separator."""
    if s is None:
        return None
    try:
        return float(s.replace(",", "."))
    except (TypeError, ValueError):
        return None


def is_strict_killers_open(text: Optional[str], msg_id: int) -> Optional[dict]:
    """Try to parse a Killers OPEN signal from raw text.

    Returns a dict matching `classifier.classify()` output schema if every
    required field parses cleanly AND the message has no management-event
    markers. Returns None on any miss, in which case the caller MUST fall
    back to the Claude classifier.

    The output gets `confidence=1.0` because each required field had to
    match — there's no probabilistic guess. Use the receiver's downstream
    validators (is_strict_open, target guard, slippage gate) for actual
    safety.
    """
    if not text or not isinstance(text, str):
        return None

    # Reject management messages outright — Killers often uses similar
    # formatting for "Target 1: X✅" follow-ups that re-mention the symbol.
    if _MGMT_MARKERS_RE.search(text):
        return None

    sig_m = _SIGNAL_ID_RE.search(text)
    coin_m = _COIN_RE.search(text)
    dir_m = _DIRECTION_RE.search(text)
    entry_m = _ENTRY_RE.search(text)
    sl_m = _SL_RE.search(text)
    if not (sig_m and coin_m and dir_m and entry_m and sl_m):
        return None

    # Numeric extraction
    sl = _parse_number(sl_m.group(1))
    if sl is None or sl <= 0:
        return None

    entry_tokens = _NUMBER_RE.findall(entry_m.group(1))
    if not entry_tokens:
        return None
    entry_nums = [v for v in (_parse_number(t) for t in entry_tokens)
                  if v is not None and v > 0]
    if not entry_nums:
        return None
    if len(entry_nums) == 1:
        entry: Optional[float] = entry_nums[0]
        entry_range = None
    elif len(entry_nums) == 2:
        entry = None
        # Channel sometimes writes range hi-then-lo; sort defensively.
        entry_range = sorted(entry_nums)
    else:
        # 3+ numbers on the ENTRY line is unexpected — fall back to Claude.
        return None

    # SL-side validity (LONG: sl < entry_low; SHORT: sl > entry_high)
    direction = dir_m.group(1).lower()
    ref_low = entry if entry is not None else entry_range[0]
    ref_high = entry if entry is not None else entry_range[1]
    if direction == "long" and sl >= ref_low:
        return None
    if direction == "short" and sl <= ref_high:
        return None

    # Symbol: strip prefix/suffix and uppercase
    symbol = coin_m.group(1).upper()
    if not symbol or symbol in {"CLOSE", "USDT"}:
        return None

    signal_id = int(sig_m.group(1))

    out = {
        "id": msg_id,
        "kind": "open",
        "signal_id": signal_id,
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "entry_range": entry_range,
        "sl": sl,
        "tp": None,                 # individual TPs handled by target-guard
        "pct": None,
        "applies_to": None,
        "confidence": 1.0,
        "notes": "rule-fast-path",
    }
    return out
