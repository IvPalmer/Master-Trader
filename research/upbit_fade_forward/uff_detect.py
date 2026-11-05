"""Detection for the forward monitor (#229): Upbit notices relayed by Tree in the PIT archive.

The archive (`research/news_archive/data/archive.sqlite`) is opened read-only. Two durable
cursors, `items.item_pk` and `item_revisions.rev_pk`, make every Tree record and every
revision of one visible exactly once, so a revised title that turns into a listing is seen.
Classification reuses nes_classify (Part C, O8-O10) by import.
"""
import json
import sqlite3
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import uff_common as uc
import na_sources
import na_store
import nes_classify as nc

TREE = "tree"
BINANCE_LISTING = "binance_listing"
NOTICE_HOST = "upbit.com"
NOTICE_PATH = "/service_center/notice"
NOTICE_NEEDLE = "upbit.com/service_center/notice"
UNCLASSIFIED_WORDS = ("거래지원", "마켓")


@dataclass(frozen=True)
class Notice:
    ref: str                    # "items:<item_pk>" or "item_revisions:<rev_pk>"
    item_pk: int
    notice_id: str
    title: str
    body: "str | None"
    published_at: "str | None"
    received_at: str
    after_gap: int


def open_archive(path):
    """Read-only; the archive's writer keeps it in WAL mode, so reading never blocks it."""
    return sqlite3.connect(Path(path).absolute().as_uri() + "?mode=ro", uri=True, timeout=5.0)


def notice_id(url):
    """The `id` of an upbit.com/service_center/notice URL, else None."""
    if not url or NOTICE_NEEDLE not in url:
        return None
    parts = urllib.parse.urlsplit(url.strip())
    host = parts.netloc.lower()
    if not (host == NOTICE_HOST or host.endswith("." + NOTICE_HOST)):
        return None
    if parts.path.rstrip("/") != NOTICE_PATH:
        return None
    ids = [i.strip() for i in urllib.parse.parse_qs(parts.query).get("id", []) if i.strip()]
    return ids[0] if ids else None


def bounds(conn):
    """The current (max item_pk, max rev_pk): the epoch cursors of a first start."""
    items = conn.execute("SELECT COALESCE(MAX(item_pk), 0) FROM items").fetchone()[0]
    revs = conn.execute("SELECT COALESCE(MAX(rev_pk), 0) FROM item_revisions").fetchone()[0]
    return {"items_pk": int(items), "rev_pk": int(revs)}


def read_new(conn, cursor):
    """Tree records of Upbit notices past `cursor`, items first, then revisions, each in pk order.

    The upper bounds are read first; with one writer every row up to them is committed, so the
    returned cursor never skips a row. Revisions are matched by their item's URL."""
    top = bounds(conn)
    out = []
    rows = conn.execute(
        "SELECT item_pk, received_at, published_at, title, body, url, after_gap FROM items"
        " WHERE item_pk > ? AND item_pk <= ? AND source = ? AND instr(url, ?) > 0"
        " ORDER BY item_pk", (cursor["items_pk"], top["items_pk"], TREE, NOTICE_NEEDLE)).fetchall()
    for pk, received, published, title, body, url, gap in rows:
        nid = notice_id(url)
        if nid:
            out.append(Notice("items:%d" % pk, pk, nid, title or "", body, published, received,
                              int(gap)))
    revs = conn.execute(
        "SELECT r.rev_pk, r.item_pk, r.received_at, r.raw_json, r.after_gap FROM item_revisions r"
        " JOIN items i ON i.item_pk = r.item_pk"
        " WHERE r.rev_pk > ? AND r.rev_pk <= ? AND i.source = ? AND instr(i.url, ?) > 0"
        " ORDER BY r.rev_pk", (cursor["rev_pk"], top["rev_pk"], TREE, NOTICE_NEEDLE)).fetchall()
    for rpk, ipk, received, raw, gap in revs:
        try:
            parsed = na_sources.parse_tree(("[%s]" % raw).encode("utf-8"))
        except ValueError:
            continue
        if not parsed:
            continue
        it = parsed[0]
        nid = notice_id(it.url)
        if nid:
            out.append(Notice("item_revisions:%d" % rpk, ipk, nid, it.title or "", it.body,
                              it.published_at, received, int(gap)))
    return out, top


def classify(title, body):
    """`addition` with per-token KRW membership (True / False / None), `end`, `unclassified`
    (mentions 거래지원 or 마켓 but does not classify) or `other`."""
    adds = nc.upbit_addition(title)
    if adds:
        krw = nc.upbit_krw_membership(title, body)
        return {"kind": "addition", "krw": {t: krw.get(t) for t in adds}}
    if nc.upbit_end(title):
        return {"kind": "end"}
    text = "%s %s" % (title, body or "")
    if any(w in text for w in UNCLASSIFIED_WORDS):
        return {"kind": "unclassified"}
    return {"kind": "other"}


def timing(published_at, received_at):
    """(t0 ms, "verified" | "unverified", reason). t0 is Tree's published_at (Tree clock)."""
    received = uc.ms(received_at)
    if published_at is None:
        return received, "unverified", "published_at missing (t0 = received_at)"
    published = uc.ms(published_at)
    if published > received:
        return published, "unverified", "published_at later than received_at"
    if received - published > uc.TREE_LAG_MAX_MS:
        return published, "unverified", "received %.1f s after published" % (
            (received - published) / 1000)
    return published, "verified", None


def trading_start(body, token, t0_ms, title):
    """The KST start the notice body states for `token` (O10), or None without a body."""
    if not body:
        return None
    return nc.upbit_trading_start_ms(body, token, t0_ms, title)


def binance_prior(conn, token, t0_ms):
    """A `binance_listing` notice for `token` published in [t0 - 24 h, t0] that the archive had
    received by t0: the item's first version, or a revision, received at or before t0 must
    name the token. A notice published after t0 never counts. Versions naming the token that
    were received after t0 (a late item, or a later revision) are listed as `late`,
    descriptive only: a bot at t0 could not have read them."""
    lo, hi = uc.iso(t0_ms - uc.BINANCE_PRIOR_MS), uc.iso(t0_ms)
    rows = conn.execute(
        "SELECT item_pk, source_item_id, published_at, received_at, title FROM items"
        " WHERE source = ? AND published_at >= ? AND published_at <= ?"
        " ORDER BY published_at, item_pk", (BINANCE_LISTING, lo, hi)).fetchall()
    late = []
    for pk, sid, published, received, title in rows:
        versions = [(received, title or "")]
        for rev_received, raw in conn.execute(
                "SELECT received_at, raw_json FROM item_revisions WHERE item_pk = ?"
                " ORDER BY rev_pk", (pk,)):
            try:
                versions.append((rev_received, json.loads(raw).get("title") or ""))
            except (ValueError, AttributeError):
                continue
        hits = [(r, t) for r, t in versions if nc.mentions_token(t, token)]
        timely = [(r, t) for r, t in hits if uc.ms(r) <= t0_ms]
        if timely:
            return {"found": True, "ref": "binance:%s" % sid, "published_at": published,
                    "received_at": timely[0][0], "title": timely[0][1], "late": late}
        if hits:
            late.append({"ref": "binance:%s" % sid, "published_at": published,
                         "received_at": hits[0][0], "title": hits[0][1]})
    gaps = conn.execute(
        "SELECT COUNT(*) FROM gaps WHERE source = ? AND gap_start <= ?"
        " AND (gap_end IS NULL OR gap_end >= ?)", (BINANCE_LISTING, hi, lo)).fetchone()[0]
    return {"found": False, "source_gaps_in_window": int(gaps), "late": late}


def pit(conn, notice):
    """Archive coverage diagnostics for one Tree record (descriptive)."""
    return {"after_gap": notice.after_gap,
            "pit_valid": na_store.pit_valid(conn, TREE, notice.received_at)}


def health(conn, now_ms):
    """Tree and Binance-listing liveness from the archive's polls and gaps tables."""
    week = uc.iso(now_ms - 7 * uc.DAY_MS)
    out = {}
    for source in (TREE, BINANCE_LISTING):
        last_ok = conn.execute("SELECT MAX(finished_at) FROM polls WHERE source = ? AND ok = 1",
                               (source,)).fetchone()[0]
        open_gaps = conn.execute(
            "SELECT reason, gap_start, detail FROM gaps WHERE source = ? AND gap_end IS NULL"
            " ORDER BY gap_start", (source,)).fetchall()
        week_gaps = conn.execute("SELECT COUNT(*) FROM gaps WHERE source = ? AND gap_start >= ?",
                                 (source, week)).fetchone()[0]
        out[source] = {"last_ok": last_ok, "open_gaps": [list(g) for g in open_gaps],
                       "gaps_7d": int(week_gaps)}
    return out
