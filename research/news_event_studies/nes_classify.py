"""Part C title and body classifiers (#229), prereg O8-O10, O12 and O17.

Pure functions over notice titles and bodies. Nothing here reads prices.
"""
import html
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import NamedTuple

EXCLUDE_WORDS = ("종료", "유의", "제거", "변경", "중단", "연기", "재개")
KRW_MARKERS = ("KRW", "원화")
ADDITION_MARKERS = ("디지털 자산 추가", "신규 상장", "신규 거래지원")
END_MARKERS = ("거래지원 종료", "상장폐지", "상장 폐지")
# An end that is postponed, withdrawn or cancelled has not happened.
END_NEGATIONS = ("연기", "철회", "취소")
START_HEADERS = ("거래지원 개시 시점", "거래 지원 개시 시점")
START_LINES = ("거래지원 개시", "거래 지원 개시", "거래 오픈")

KST = timezone(timedelta(hours=9))
_TICKER = re.compile(r"[A-Z0-9]{1,15}")


class BinanceClass(NamedTuple):
    kind: str
    tokens: tuple = ()


def _is_ticker(text):
    return _TICKER.fullmatch(text) is not None


def _dedupe(items):
    return tuple(dict.fromkeys(items))


def _tickers(clause):
    """Split a token list on ',', '&' and ' and '; None if any piece is not a ticker."""
    clause = re.split(r"\s+on\s+", clause.strip(), maxsplit=1)[0]
    clause = re.sub(r"\s*\([^()]*\)\s*$", "", clause)    # a trailing "(Cancelled)" or "(Update)"
    pieces = [p.strip() for p in re.split(r",|&|\s+and\s+", clause)]
    if not pieces or not all(_is_ticker(p) for p in pieces):
        return None
    return _dedupe(pieces)


def _excluded(reason):
    return BinanceClass("excluded:" + reason, ())


UNCLASSIFIED = BinanceClass("unclassified", ())


def classify_binance(title):
    t = " ".join(title.split())
    if re.search(r"\bVote\b", t):
        return _excluded("vote")
    # Only a notice that is itself a cancellation; an edited "(Cancelled)" suffix on a
    # delisting stays in (rules_verbatim: retractions are unknowable at entry).
    if re.match(r"(?:Binance\s+Will\s+)?(?:Cancel|Revoke|Retract)", t):
        return _excluded("retraction")
    if "Monitoring Tag" in t:
        m = re.search(r"\bInclude\s+(.+)$", t) or \
            re.search(r"\bAdd\s+(?:the\s+)?Monitoring\s+Tags?\s+(?:to|on)\s+(.+)$", t)
        if m:
            tokens = _tickers(re.split(r"\s+and\s+Remove\b", m.group(1), maxsplit=1)[0])
            return BinanceClass("monitoring_add", tokens) if tokens else UNCLASSIFIED
        if re.search(r"\bRemov", t):
            return _excluded("tag_removal")
        return UNCLASSIFIED
    if re.search(r"\bMargin\b", t):
        return _excluded("margin")
    if re.search(r"Futures|Perpetual|USDⓈ-M|COIN-M", t):
        return _excluded("futures")
    if "Leveraged" in t:
        return _excluded("leveraged")
    if re.search(r"\bOptions\b", t):
        return _excluded("options")
    if "Trading Pair" in t or "/" in t:
        return _excluded("pair_removal")
    if re.match(r"Binance\s+(?!Will\b)\S.*?\s+Will\s+Delist\b", t):
        return _excluded("other_product")
    m = re.match(r"Binance Will Delist\s+(.+)$", t)
    if m:
        tokens = _tickers(m.group(1))
        return BinanceClass("full_delist", tokens) if tokens else UNCLASSIFIED
    return UNCLASSIFIED


def mentions_token(title, token):
    pattern = (r"(?<![A-Z0-9])(?:1000000|1000|1M)?" + re.escape(token)
               + r"(?:USDT|USDC|FDUSD|BTC)?(?![A-Z0-9])")
    return re.search(pattern, title) is not None


# --- Upbit titles (O8, O9) ---------------------------------------------------

def _has_krw(text):
    return any(m in text for m in KRW_MARKERS)


def _upbit_tokens(title):
    named = re.findall(r"(?<=[^\s(),])\(([A-Z0-9]{1,15})\)", title)
    if named:
        return _dedupe(named)
    groups = [g for g in re.findall(r"\(([^()]*)\)", title) if not g.strip().endswith("마켓")]
    if not groups:
        return None
    tokens = []
    for item in groups[-1].split(","):
        words = re.findall(r"[A-Za-z0-9]+", item)
        if not words or not _is_ticker(words[-1]):
            return None
        tokens.append(words[-1])
    return _dedupe(tokens)


def upbit_addition(title):
    if not _has_krw(title) or not any(m in title for m in ADDITION_MARKERS):
        return None
    if any(w in title for w in EXCLUDE_WORDS):
        return None
    return _upbit_tokens(title)


def upbit_end(title):
    if not any(m in title for m in END_MARKERS):
        return None
    if any(w in title for w in END_NEGATIONS):
        return None
    if "마켓" in title and not _has_krw(title):
        return None                    # an end limited to BTC/USDT markets
    return _upbit_tokens(title)


def upbit_needs_review(title):
    if not _has_krw(title) or any(w in title for w in EXCLUDE_WORDS):
        return False
    return upbit_addition(title) is None and upbit_end(title) is None


# --- Upbit body: trading start (O10) -----------------------------------------

class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._open, self._row, self._cell = [], [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._open.append([])
        elif tag == "tr" and self._open:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            a = dict(attrs)
            self._cell = [[], _span(a.get("rowspan")), _span(a.get("colspan"))]
        elif tag == "br" and self._cell is not None:
            self._cell[0].append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            text = " ".join("".join(self._cell[0]).split())
            self._row.append((text, self._cell[1], self._cell[2]))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._open[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._open:
            self.tables.append(self._open.pop())

    def handle_data(self, data):
        if self._cell is not None:
            self._cell[0].append(data)


def _span(value):
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def _grid(rows):
    """Expand rowspan and colspan so every row lists its cells by column."""
    out, carry = [], {}
    for row in rows:
        line, col, i = [], 0, 0
        while i < len(row) or any(c >= col for c in carry):
            if col in carry:
                text, left = carry[col]
                line.append(text)
                if left <= 1:
                    del carry[col]
                else:
                    carry[col] = (text, left - 1)
                col += 1
            elif i < len(row):
                text, rowspan, colspan = row[i]
                i += 1
                for _ in range(colspan):
                    line.append(text)
                    if rowspan > 1:
                        carry[col] = (text, rowspan - 1)
                    col += 1
            else:
                line.append("")
                col += 1
        out.append(line)
    return out


_WEEKDAY = r"(?:\s*\(\s*[월화수목금토일]\s*\))?"
_CLOCK = (r"\s*(?P<ampm>오전|오후)?\s*(?:(?P<h1>\d{1,2})\s*:\s*(?P<m1>\d{2})"
          r"|(?P<h2>\d{1,2})\s*시\s*(?P<m2>\d{1,2})\s*분)")
_WITH_YEAR = [re.compile(d + _WEEKDAY + _CLOCK) for d in (
    r"(?P<y>\d{4})\s*년\s*(?P<mo>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일",
    r"(?P<y>\d{4})-(?P<mo>\d{1,2})-(?P<d>\d{1,2})",
    r"(?P<y>\d{4})\s*\.\s*(?P<mo>\d{1,2})\s*\.\s*(?P<d>\d{1,2})\.?",
)]
_NO_YEAR = re.compile(r"(?<!\d)(?P<mo>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일" + _WEEKDAY + _CLOCK)


def _kst_ms(year, month, day, hour, minute):
    try:
        return int(datetime(year, month, day, hour, minute, tzinfo=KST).timestamp() * 1000)
    except ValueError:
        return None


def _clock(m):
    hour = int(m.group("h1") or m.group("h2"))
    minute = int(m.group("m1") or m.group("m2"))
    if m.group("ampm") == "오후" and hour < 12:
        hour += 12
    elif m.group("ampm") == "오전" and hour == 12:
        hour = 0
    return hour, minute


def _starts_in(text, t0_ms):
    """Every start time stated in one piece of text, as a set of UTC ms."""
    found, masked = set(), text
    for pattern in _WITH_YEAR:
        for m in pattern.finditer(text):
            found.add(_kst_ms(int(m.group("y")), int(m.group("mo")), int(m.group("d")), *_clock(m)))
            masked = masked[:m.start()] + " " * (m.end() - m.start()) + masked[m.end():]
    year = datetime.fromtimestamp(t0_ms / 1000, KST).year
    for m in _NO_YEAR.finditer(masked):
        options = [ms for ms in (_kst_ms(y, int(m.group("mo")), int(m.group("d")), *_clock(m))
                                 for y in (year - 1, year, year + 1)) if ms is not None]
        if not options:
            found.add(None)
            continue
        options.sort(key=lambda ms: abs(ms - t0_ms))
        tie = len(options) > 1 and abs(options[0] - t0_ms) == abs(options[1] - t0_ms)
        found.add(None if tie else options[0])
    return found


def _single(values):
    return next(iter(values)) if len(values) == 1 else None


def _token_in(text, token):
    return re.search(r"(?<![A-Z0-9])" + re.escape(token) + r"(?![A-Z0-9])", text) is not None


def upbit_trading_start_ms(body, token, t0_ms):
    """The KST trading start stated for `token`, as UTC ms; None when unknown (O10)."""
    body = body or ""
    parser = _TableParser()
    parser.feed(body)
    parser.close()
    table_seen, found = False, set()
    for rows in parser.tables:
        grid = _grid(rows)
        for h, header in enumerate(grid):
            col = next((j for j, c in enumerate(header) if any(k in c for k in START_HEADERS)), None)
            if col is None:
                continue
            table_seen = True
            for row in grid[h + 1:]:
                if col < len(row) and any(_token_in(c, token) for j, c in enumerate(row) if j != col):
                    found |= _starts_in(row[col], t0_ms) or {None}
            break
    if table_seen:
        return _single(found)
    text = re.sub(r"<br\s*/?>|</(?:p|div|li|tr|h\d|table)>", "\n", body, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    for line in text.splitlines():
        if any(k in line for k in START_LINES):
            found |= _starts_in(line, t0_ms)
    return _single(found)
