"""PIT news archive store (issue #229, Part A): network-free."""
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "news_archive"))

import na_store  # noqa: E402
from na_store import Item  # noqa: E402

T0 = datetime(2026, 11, 3, 20, 0, tzinfo=timezone.utc)


def ts(minutes=0, days=0):
    return (T0 + timedelta(minutes=minutes, days=days)).isoformat(timespec="microseconds")


def item(iid, title="t", **kw):
    raw = {"id": iid, "title": title, **kw}
    return Item(source_item_id=iid, published_at=None, title=title, body=None,
                url=None, symbols=None, raw=raw)


def db(tmp_path):
    return na_store.connect(str(tmp_path / "archive.sqlite"))


def test_new_items_inserted_once(tmp_path):
    conn = db(tmp_path)
    batch = [item("1"), item("2")]
    assert na_store.upsert_items(conn, "tree", batch, ts(0), False) == (2, 0)
    assert na_store.upsert_items(conn, "tree", batch, ts(1), False) == (0, 0)
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM item_revisions").fetchone()[0] == 0


def test_duplicate_id_in_one_batch_is_one_item(tmp_path):
    conn = db(tmp_path)
    n_new, n_rev = na_store.upsert_items(
        conn, "tree", [item("A", "first"), item("A", "second")], ts(0), False)
    assert (n_new, n_rev) == (1, 0)
    assert conn.execute("SELECT title FROM items").fetchall() == [("first",)]
    assert conn.execute("SELECT COUNT(*) FROM item_revisions").fetchone()[0] == 0


def test_versions_compare_against_latest(tmp_path):
    conn = db(tmp_path)
    a, b = item("x", "A"), item("x", "B")
    ha, hb = na_store.content_hash(a.raw), na_store.content_hash(b.raw)
    results = [na_store.upsert_items(conn, "upbit", [v], ts(i), False)
               for i, v in enumerate([a, b, b, a])]
    assert results == [(1, 0), (0, 1), (0, 0), (0, 1)]
    revs = conn.execute(
        "SELECT prev_hash, content_hash FROM item_revisions ORDER BY rev_pk").fetchall()
    assert revs == [(ha, hb), (hb, ha)]
    assert conn.execute("SELECT title, content_hash FROM items").fetchone() == ("A", ha)


def test_revision_inherits_after_gap_flag(tmp_path):
    conn = db(tmp_path)
    na_store.upsert_items(conn, "upbit", [item("x", "A")], ts(0), False)
    na_store.upsert_items(conn, "upbit", [item("x", "B")], ts(1), True)
    assert conn.execute("SELECT after_gap FROM item_revisions").fetchone()[0] == 1
    assert conn.execute("SELECT after_gap FROM items").fetchone()[0] == 0


def test_write_succeeds_while_reader_holds_snapshot(tmp_path):
    path = tmp_path / "archive.sqlite"
    conn = na_store.connect(str(path))
    na_store.upsert_items(conn, "tree", [item("1")], ts(0), False)
    reader = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    reader.execute("BEGIN")
    assert reader.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
    assert na_store.upsert_items(conn, "tree", [item("2")], ts(1), False) == (1, 0)
    # the reader's snapshot is unchanged until it ends its transaction
    assert reader.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
    reader.rollback()
    assert reader.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2
    reader.close()


def test_prune_polls_keeps_180_days(tmp_path):
    conn = db(tmp_path)
    for d in (-181, -179):
        na_store.record_poll(conn, "tree", ts(days=d), ts(days=d), True, 200, 1, 0, 0, None)
    assert na_store.prune_polls(conn, ts(0)) == 1
    assert [r[0] for r in conn.execute("SELECT started_at FROM polls")] == [ts(days=-179)]
