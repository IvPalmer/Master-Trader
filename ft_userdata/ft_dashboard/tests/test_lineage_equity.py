"""Regression tests for dry-run → live strategy lineage curves."""

import sqlite3

import app


def _legacy_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE trades (is_open INTEGER, open_date TEXT, close_date TEXT, "
        "close_profit_abs REAL)"
    )
    conn.executemany(
        "INSERT INTO trades VALUES (?, ?, ?, ?)",
        [
            (0, "2026-08-01 00:00:00", "2026-08-02 00:00:00", 10.0),
            (0, "2026-08-03 00:00:00", "2026-08-04 00:00:00", -5.0),
            # A retired epoch's open trade must never enter the lineage.
            (1, "2026-08-05 00:00:00", None, 99.0),
            # A parallel dry-run may continue after live cutover; freeze it.
            (0, "2027-02-01 00:00:00", "2027-02-02 00:00:00", 500.0),
        ],
    )
    conn.commit()
    conn.close()


def test_lineage_stitches_closed_dry_run_to_rebased_live(tmp_path, monkeypatch):
    db = tmp_path / "legacy.sqlite"
    _legacy_db(db)
    monkeypatch.setattr(app, "LINEAGE_DB_DIR", tmp_path)
    transition = 1_800_000_000_000
    meta = {
        "lineage": {
            "legacy_db": db.name,
            "legacy_starting_capital": 200.0,
            "transition_ts_ms": transition,
            "transition_label": "live + strategy v2",
            "legacy_label": "dry-run",
            "live_label": "live",
        }
    }
    snap = {
        "wallet": {"starting_capital": 50.0},
        "equity_live": [[transition, 50.0], [transition + 1_000, 55.0]],
    }

    lineage = app._lineage_payload(meta, snap)

    assert lineage["legacy_closed_trades"] == 2
    assert lineage["legacy_ending_equity"] == 205.0
    assert lineage["legacy"][-1] == [transition - 1, 205.0]
    assert lineage["live"] == [[transition, 205.0], [transition + 1_000, 225.5]]
    assert lineage["transition"]["label"] == "live + strategy v2"
    assert lineage["drawdown"][-1][1] == 0.0


def test_lineage_is_absent_when_history_db_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "LINEAGE_DB_DIR", tmp_path)
    meta = {"lineage": {"legacy_db": "missing.sqlite", "transition_ts_ms": 1}}
    snap = {"wallet": {"starting_capital": 50.0}, "equity_live": [[1, 50.0]]}

    assert app._lineage_payload(meta, snap) is None
