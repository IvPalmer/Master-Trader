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
# A start declaration: a start keyword in label form, `거래지원 개시 시점: ...` or `거래 오픈 : ...`.
_DECLARATION = re.compile("(?:%s)(?:\\s*시점)?\\s*[:：]" % "|".join(map(re.escape, START_LINES)))
# A start declared as not yet set (`거래지원 개시 시점은 추후 ... 안내`). On the harvested corpus
# (text only) it matched exactly the 8 TBD lines and none of the 785 other keyword lines.
TBD = re.compile(r"(거래\s?지원 개시|거래 오픈)\s*(시점|일정)?\s*(은|는|[:：])[^.]{0,80}?"
                 r"(추후|미정|별도 공지|추가 안내|추가로 안내)")
# Particles a Korean token name may carry and still name the token (스택스의 ...).
_PARTICLES = ("에서", "으로", "부터", "의", "은", "는", "이", "가", "을", "를", "도", "에", "와", "과", "만", "로")

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
        if t.startswith("Introducing "):          # the tag's launch notice names no token
            return _excluded("tag_introduction")
        m = re.search(r"\bInclude\s+(.+)$", t) or \
            re.search(r"\bAdd\s+(?:the\s+)?Monitoring\s+Tags?\s+(?:to|on)\s+(.+)$", t) or \
            re.search(r"\bExtend\s+the\s+Monitoring\s+Tag\s+to\s+(.+)$", t)
        if m:
            # The added list ends at the first removal clause: " and Remove", ", Remove"
            # or ", and Remove".
            added = re.split(r",?\s+(?:and\s+)?Remove\b", m.group(1), maxsplit=1)[0]
            tokens = _tickers(added)
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
    if re.match(r"Binance\s+(?!Will\b)\S.*?\s+Will\s+(?:Delist|Remove)\b", t):
        return _excluded("other_product")
    m = re.match(r"Binance Will Delist\s+(.+?)(?:\s+and\s+Support\b.*)?$", t)
    if m:
        tokens = _tickers(m.group(1))
        if tokens:
            return BinanceClass("full_delist", tokens)
    # Formats first met in the 2026-11-04 harvest. They apply only to titles the rules
    # above leave unclassified, so no earlier classification changes.
    m = re.match(r"Notice Regarding the Removal of ([A-Z0-9]{1,15}) and Conversion of \1 to ", t)
    if m:
        return BinanceClass("full_delist", (m.group(1),))
    if re.search(r"\b[A-Z0-9]+UP\s*&\s*[A-Z0-9]+DOWN\b", t):
        return _excluded("leveraged")
    if re.search(r"Binance Loans|Binance Earn|Dual Investment|Selected Stocks", t):
        return _excluded("other_product")
    if "Update on the Delisting Date" in t:
        return _excluded("delisting_update")
    if re.match(r"Upcoming Changes to \S+ Spot Trading\b", t):
        return _excluded("spot_trading_changes")
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
    # A group naming markets, or a trailing notice note (`(매도 ... 가격 안내)`), names no token.
    groups = [g for g in re.findall(r"\(([^()]*)\)", title) if not g.strip().endswith(("마켓", "안내"))]
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
    if "마켓 추가" in title and not any(m in title for m in ADDITION_MARKERS):
        return False                   # not an O8 marker: decided not an addition (upbit:4273)
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


def _body_lines(body):
    text = re.sub(r"<br\s*/?>|</(?:p|div|li|tr|h\d|table)>", "\n", body or "", flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", " ", text)).splitlines()


def _single(values):
    return next(iter(values)) if len(values) == 1 else None


def _token_in(text, token):
    return re.search(r"(?<![A-Z0-9])" + re.escape(token) + r"(?![A-Z0-9])", text) is not None


def _upbit_names(title):
    """Each token of an Upbit title with the Korean names it is written with:
    `에이(AAA), 비(BBB) ...` -> {AAA: [에이], BBB: [비]}; `(이오스 EOS)` -> {EOS: [이오스]}."""
    names = {t: [] for t in _upbit_tokens(title) or ()}
    pairs = re.findall(r"([^\s(),\[\]][^(),\[\]]*?)\s*\(([A-Z0-9]{1,15})\)", title)
    for group in re.findall(r"\(([^()]*)\)", title):
        pairs += [m.groups() for m in (re.fullmatch(r"\s*(\S.*?)\s+([A-Z0-9]{1,15})\s*", item)
                                       for item in group.split(",")) if m]
    for name, tok in pairs:
        if tok in names and not _is_ticker(name.strip()):
            names[tok].append(name.strip())
    return names


def _names_token(text, token, names):
    """The ticker as a whole word, or a Korean name of the title ending at a word boundary or
    in one particle (스택스의); 비 is not named by 비트코인 or 서비스."""
    tail = r"(?:%s)?(?![가-힣A-Za-z0-9])" % "|".join(_PARTICLES)
    return _token_in(text, token) or any(
        re.search(r"(?<![가-힣A-Za-z0-9])" + re.escape(n) + tail, text) for n in names)


def upbit_trading_start_ms(body, token, t0_ms, title=""):
    """The KST trading start stated for `token`, as UTC ms; None when unknown (O10).

    `title` is the notice title; its tokens and their Korean names (O8) attribute the lines.
    Outside a table, a single-token notice reads every start line, as on main, except that a
    TBD line with no dated label line gives None. A multi-token notice reads declarations
    (a start keyword in label form, or a TBD line, which states no time) and fails closed:
    if any declaration names a token, each token's start is the one time every declaration
    naming it states; if none does, the same check runs over all declarations; no
    declaration, one without a parseable time, or two times give None."""
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
    names = _upbit_names(title)
    names.setdefault(token, [])
    lines = _body_lines(body)
    if len(names) == 1:
        dated_label = False
        for line in lines:
            if any(k in line for k in START_LINES):
                times = _starts_in(line, t0_ms)
                found |= times
                dated_label = dated_label or bool(times and _DECLARATION.search(line))
        if not dated_label and any(TBD.search(line) for line in lines):
            return None
        return _single(found)
    declared = [(line, {t for t, ns in names.items() if _names_token(line, t, ns)})
                for line in lines if _DECLARATION.search(line) or TBD.search(line)]
    if any(scope for _, scope in declared):
        declared = [(line, scope) for line, scope in declared if token in scope]
    times = [set() if TBD.search(line) else _starts_in(line, t0_ms) for line, _ in declared]
    if not times or not all(times):
        return None                      # no declaration, or one with no parseable time
    return _single(set().union(*times))


# --- Upbit: which tokens of an addition join the KRW market (O8) -------------------

_MARKETS = ("KRW", "BTC", "USDT")
_TITLE_TOKEN_MARKETS = re.compile(r"\(([A-Z0-9]{1,15})\)\s*\(([^()]*?)\s*마켓\)")
_MARKET_WORD = r"(?:KRW|BTC|USDT|원화)"
_MARKET_LIST = r"%s(?:\s*[,/]\s*%s)*" % (_MARKET_WORD, _MARKET_WORD)
_BULLET = r"^[\s\-•·*]*"
# A declaration is the whole line, with the whole market list: `- KRW, BTC 마켓 : ARB`,
# `- ALT : BTC 마켓` or `- ALT : BTC 마켓, KRW 마켓`; never `- ALT : KRW 마켓 전일 종가`.
_LINE_MARKET_TOKENS = re.compile(r"%s(%s)\s*마켓\s*[:：]\s*(.+?)\s*$" % (_BULLET, _MARKET_LIST))
_LINE_TOKEN_MARKETS = re.compile(r"%s([A-Z0-9]{1,15})\s*[:：]\s*((?:%s)\s*마켓(?:\s*[,/]\s*(?:%s)\s*마켓)*)\s*$"
                                 % (_BULLET, _MARKET_LIST, _MARKET_LIST))


def _markets(text):
    found = {m for m in _MARKETS if _token_in(text, m)}
    return found | {"KRW"} if "원화" in text else found


def _body_markets(body, token):
    """The markets the body assigns to `token`: a `마켓` table column, `- ALT : BTC 마켓` or
    `- KRW 마켓 : SHIB` lines. Empty when the body does not say."""
    found = set()
    parser = _TableParser()
    parser.feed(body)
    parser.close()
    for rows in parser.tables:
        grid = _grid(rows)
        for h, header in enumerate(grid):
            col = next((j for j, c in enumerate(header) if c.strip() == "마켓"), None)
            if col is None:
                continue
            for row in grid[h + 1:]:
                if col < len(row) and any(_token_in(c, token) for j, c in enumerate(row) if j != col):
                    found |= _markets(row[col])
            break
    for line in _body_lines(body):
        m = _LINE_TOKEN_MARKETS.match(line)
        if m and m.group(1) == token:
            found |= _markets(m.group(2))
        m = _LINE_MARKET_TOKENS.match(line)
        if m and token in (_tickers(m.group(2)) or ()):     # a price on the right says nothing
            found |= _markets(m.group(1))
    return found


def upbit_krw_membership(title, body=None):
    """Each token of an O8 addition -> True if it joins the KRW market, False if the notice
    gives its markets without KRW, None if the notice does not say.

    The token's own market group in the title decides; else a title naming only the KRW
    market, or a single token, means KRW; else the body's per-token markets."""
    tokens = upbit_addition(title) or ()
    own = {tok: _markets(mk) for tok, mk in _TITLE_TOKEN_MARKETS.findall(title)}
    krw_only = _markets(re.sub(r"\([^()]*\)", " ", title)) | _markets(
        " ".join(g for g in re.findall(r"\(([^()]*마켓)\)", title))) == {"KRW"}
    out = {}
    for tok in tokens:
        if own.get(tok):
            out[tok] = "KRW" in own[tok]
        elif krw_only or len(tokens) == 1:
            out[tok] = True
        else:
            found = _body_markets(body, tok) if body else set()
            out[tok] = ("KRW" in found) if found else None
    return out
