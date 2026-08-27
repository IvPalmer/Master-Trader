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
    assert lineage["normalized"] is True
    assert lineage["normalization_status"] == "rebased"


def test_lineage_is_absent_when_history_db_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "LINEAGE_DB_DIR", tmp_path)
    meta = {"lineage": {"legacy_db": "missing.sqlite", "transition_ts_ms": 1}}
    snap = {"wallet": {"starting_capital": 50.0}, "equity_live": [[1, 50.0]]}

    assert app._lineage_payload(meta, snap) is None


def test_lineage_rejects_tiny_live_capital_amplification(tmp_path, monkeypatch):
    db = tmp_path / "legacy.sqlite"
    _legacy_db(db)
    monkeypatch.setattr(app, "LINEAGE_DB_DIR", tmp_path)
    transition = 1_800_000_000_000
    meta = {
        "lineage": {
            "legacy_db": db.name,
            "legacy_starting_capital": 200.0,
            "transition_ts_ms": transition,
        }
    }
    snap = {
        "wallet": {"starting_capital": 0.01},
        "equity_live": [[transition, 0.01], [transition + 1_000, 0.02]],
    }

    lineage = app._lineage_payload(meta, snap)

    assert lineage["normalized"] is False
    assert lineage["normalization_status"] == "invalid-live-capital-basis"
    assert lineage["live"] == [[transition, 205.0]]


def test_live_equity_filters_pre_epoch_trades_and_stays_chronological():
    epoch = 1_800_000_000_000
    closed = [
        {"close_timestamp": epoch + 2_000, "profit_abs": 2.0},
        {"close_timestamp": epoch - 1_000, "profit_abs": 99.0},
        {"close_timestamp": epoch + 1_000, "profit_abs": -1.0},
    ]

    curve = app._equity_curve_live(closed, [], 50.0, epoch)

    assert curve == [
        [epoch, 50.0],
        [epoch + 1_000, 49.0],
        [epoch + 2_000, 51.0],
    ]


def test_ff_and_keltner_historical_baselines_are_explicitly_stale():
    bots = {bot["key"]: bot for bot in app.BOTS}

    for key in ("fundingfade", "keltner"):
        assert bots[key]["baseline_status"] == "stale-pre-v2"
        assert bots[key]["epoch_start_ts_ms"] == bots[key]["lineage"]["transition_ts_ms"]
    assert bots["fundingfade"]["lineage"]["legacy_db"] == "tradesv3.live.FundingFadeV1.sqlite"


def test_round3_bots_use_the_post_change_measurement_epoch():
    bots = {bot["key"]: bot for bot in app.BOTS}

    assert app.KILLERS_ROUND5_EPOCH_TS_MS == 1787854748304
    assert app.INSIDERS_ROUND5_EPOCH_TS_MS == 1787854752005
    assert app.OI_ROUND4_EPOCH_TS_MS == 1787619881124
    assert bots["oi-trend"]["epoch_start_ts_ms"] == app.OI_ROUND4_EPOCH_TS_MS
    assert bots["killers-ft"]["epoch_start_ts_ms"] == app.KILLERS_ROUND5_EPOCH_TS_MS
    assert (
        bots["killers-ft"]["lineage"]["transition_ts_ms"]
        == app.KILLERS_ROUND5_EPOCH_TS_MS
    )
    assert (
        bots["insiders-ft"]["lineage"]["transition_ts_ms"]
        == app.INSIDERS_ROUND5_EPOCH_TS_MS
    )
