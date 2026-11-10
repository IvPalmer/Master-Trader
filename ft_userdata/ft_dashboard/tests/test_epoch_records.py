"""Ended bot epochs stay on the dashboard as immutable records (#277).

A bot moved to dry-run, retired or deleted no longer serves its live trades,
so its epoch is archived once as a record and served from it. All trades,
prices and identities here are synthetic.
"""

import asyncio
import json
import sqlite3
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import app
import build_epoch_record
import epoch_records

DAY = 86_400_000
START = 1_790_000_000_123
END = START + 10 * DAY
RID = "killers-ft.live-r1"


def _sqlite_date(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).replace(tzinfo=None).isoformat(sep=" ")


def _trade(tid, day, profit, pair="SOL/USDC:USDC"):
    opened = START + day * DAY
    closed = opened + 3_600_000
    return {
        "trade_id": tid, "pair": pair, "is_open": False, "is_short": False,
        "open_timestamp": opened, "close_timestamp": closed,
        "open_date": _sqlite_date(opened), "close_date": _sqlite_date(closed),
        "open_rate": 100.0, "close_rate": 100.0 + profit, "amount": 1.0,
        "stake_amount": 100.0, "leverage": 1.0, "profit_abs": profit,
        "profit_ratio": profit / 100, "profit_pct": profit, "exit_reason": "roi",
    }


def _spec(trades, **overrides):
    spec = {
        "record_id": RID, "bot_key": "killers-ft", "mode": "live", "start_ms": START,
        "end_ms": END, "starting_capital": 98.0, "reason": "moved to dry-run", "issue": 999,
        "source_backup": "archive-synthetic.sqlite", "source_sha256": "0" * 64,
        "trades": trades, "display": {"epoch_label": "synthetic live epoch"},
    }
    spec.update(overrides)
    return spec


def _build(spec):
    return asyncio.run(build_epoch_record.build(spec))


def _write(directory, record):
    (directory / f"{record['record_id']}.json").write_text(json.dumps(record))


@pytest.fixture
def frozen_only(monkeypatch):
    """No bot API at all; Hyperliquid fills are counted and $1 short per trade."""
    async def forbidden(*args, **kwargs):
        raise AssertionError("a stopped epoch must not call its bot")

    for name in ("_get", "_get_plain", "_fetch_epoch_trades"):
        monkeypatch.setattr(app, name, forbidden)
    calls = []

    async def fills(client, bot):
        calls.append(bot["key"])
        return [], None

    def reconcile(trades, exchange_fills):
        return [{**t, "freqtrade_profit_abs": t["profit_abs"], "profit_abs": t["profit_abs"] - 1.0,
                 "hyperliquid_fill_mismatch": True} for t in trades]

    monkeypatch.setattr(app, "_hyperliquid_user_fills", fills)
    monkeypatch.setattr(app, "reconcile_trades", reconcile)
    return calls


@pytest.fixture
def served(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "EPOCH_RECORDS_DIR", tmp_path)
    return tmp_path


def test_frozen_epoch_is_identical_at_any_later_time(frozen_only, monkeypatch):
    trades = [_trade(1, 1, 3.0), _trade(2, 2, -1.5)]
    monkeypatch.setattr(app.time, "time", lambda: END / 1000 + 3600)
    first = _build(_spec(trades))
    monkeypatch.setattr(app.time, "time", lambda: END / 1000 + 90 * 86_400)
    assert _build(_spec(trades)) == first
    snap = first["snapshot"]
    assert (snap["key"], snap["bot_key"], snap["stopped"], snap["dry_run"]) == (RID, "killers-ft", True, False)
    assert snap["open_trades"] == [] and snap["days_running"] == 10.0
    assert (snap["epoch"]["end_ts_ms"], snap["epoch"]["reason"], snap["epoch"]["issue"]) == (END, "moved to dry-run", 999)


def test_reconciled_once_at_creation_with_raw_and_corrected_totals(frozen_only, served):
    record = _build(_spec([_trade(1, 1, 3.0), _trade(2, 2, -1.5), _trade(3, 11, 9.0)]))
    assert frozen_only == ["killers-ft"]
    # The trade closed after the window belongs to no record of this epoch.
    assert record["totals"] == {"closed_trades": 2, "raw_profit_abs": pytest.approx(1.5),
                                "corrected_profit_abs": pytest.approx(-0.5), "reconciled_trades": 2,
                                "fill_reconciliation": "ok"}
    assert [t["freqtrade_profit_abs"] for t in record["trades"]] == [3.0, -1.5]
    _write(served, record)
    client = TestClient(app.app)
    assert client.get("/api/state").json()["bots"][RID]["pnl"]["closed"] == pytest.approx(-0.5)
    assert client.get(f"/api/equity/{RID}").status_code == 200
    rows = [t for t in client.get("/api/closed_trades").json()["trades"] if t["bot_key"] == RID]
    assert sorted(t["profit_abs"] for t in rows) == [-2.5, 2.0]
    assert all(t["stopped"] is True and t["dry_run"] is False for t in rows)
    assert frozen_only == ["killers-ft"], "serving a record never reconciles again"


def test_an_unpriced_fill_mismatch_is_never_frozen(frozen_only, monkeypatch):
    """Codex #277 P1: an incomplete correction left raw P&L in the record for good."""
    def reconcile(trades, exchange_fills):
        return [{**t, "freqtrade_profit_abs": t["profit_abs"], "hyperliquid_fill_mismatch": True,
                 "hyperliquid_fill_reconciliation": {"status": "fill_mismatch_unpriced",
                                                     "profit_correction_complete": False}}
                if t["trade_id"] == 2 else t for t in trades]

    monkeypatch.setattr(app, "reconcile_trades", reconcile)
    with pytest.raises(ValueError, match=r"incomplete for trade\(s\) \[2\]"):
        _build(_spec([_trade(1, 1, 3.0), _trade(2, 2, -1.5)]))


def test_a_trade_owned_twice_rejects_the_later_record_whole(frozen_only, tmp_path):
    _write(tmp_path, _build(_spec([_trade(1, 1, 3.0)])))
    _write(tmp_path, _build(_spec([_trade(1, 1, 3.0), _trade(2, 2, 1.0)], record_id="killers-ft.live-r2")))
    (tmp_path / "killers-ft.live-r3.json").write_text('{"schema": 1, "start_ms": NaN}')
    records = epoch_records.load_records(tmp_path)
    assert list(records.by_id) == [RID]
    assert records.owned == {("SOL/USDC:USDC", START + DAY, 1)}
    assert [e.split(" rejected")[0] for e in records.errors] == [
        "Epoch record killers-ft.live-r2.json", "Epoch record killers-ft.live-r3.json"]
    assert "already owned" in records.errors[0]


@pytest.mark.parametrize("damage", [
    lambda r: r["snapshot"].pop("pnl"),
    lambda r: r["snapshot"].pop("stats"),
    lambda r: r["snapshot"].pop("realized_events"),
    lambda r: r["snapshot"]["stats"].update(closed_trade_count=1),
    lambda r: r["snapshot"]["pnl"].update(closed=0.0),
    lambda r: r["totals"].update(raw_profit_abs=0.0),
    lambda r: r["trades"][0].update(profit_abs=None),
    # Round 2: figures that agree with each other but not with the trades.
    lambda r: (r["snapshot"]["pnl"].update(closed=0.0), r["snapshot"].update(realized_events=[])),
    lambda r: r["snapshot"]["stats"].update(gross_profit=0.0, gross_loss=999.0),
    lambda r: r["snapshot"]["realized_events"][0].__setitem__(0, END),
])
def test_a_record_without_consistent_measurements_owns_nothing(frozen_only, tmp_path, damage):
    """Codex #277 P2: a record with no P&L still took its trades from the running bot."""
    record = _build(_spec([_trade(1, 1, 3.0), _trade(2, 2, -1.5)]))
    damage(record)
    _write(tmp_path, record)
    records = epoch_records.load_records(tmp_path)
    assert records.by_id == {} and records.owned == frozenset() and len(records.errors) == 1


def _running_poll(monkeypatch, history, status=()):
    bot = app._bot_meta("keltner")
    payloads = {
        "profit": {"bot_start_timestamp": 0}, "status": list(status),
        "balance": {"starting_capital": 100.0, "total_bot": 100.0, "total": 100.0},
        "show_config": {"dry_run": False, "timeframe": "1h", "stake_currency": "USDT"},
        "whitelist": {"whitelist": []},
    }

    async def fake_get(client, url, path, *args, **kwargs):
        return payloads.get(path.split("?")[0]), None

    async def fake_plain(*args, **kwargs):
        return None, "unavailable"

    async def fake_history(client, bot, epoch_start_ts_ms):
        return history

    monkeypatch.setattr(app, "_get", fake_get)
    monkeypatch.setattr(app, "_get_plain", fake_plain)
    monkeypatch.setattr(app, "_fetch_epoch_trades", fake_history)
    monkeypatch.setitem(bot, "epoch_start_ts_ms", START)
    snapshot = asyncio.run(app._poll_bot(None, bot))
    return (snapshot["stats"]["closed_trade_count"], snapshot["pnl"]["closed"]), snapshot


def test_running_bot_never_repeats_a_record_trade_even_from_its_cache(frozen_only, served, monkeypatch):
    owned, kept = _trade(1, 1, 3.0, pair="BTC/USDT"), _trade(3, 3, 2.0, pair="BTC/USDT")
    _write(served, _build(_spec([owned], record_id="keltner.live-r1", bot_key="keltner")))
    monkeypatch.setattr(app, "_trade_cache", {})
    counted, _ = _running_poll(monkeypatch, ([owned, kept], True, None))
    assert counted == (1, 2.0)
    counted, snapshot = _running_poll(monkeypatch, ([], False, "timeout"))  # falls back to the cache
    assert snapshot["history"]["using_last_complete"] is True
    assert counted == (1, 2.0)


def test_a_cached_snapshot_never_counts_a_trade_a_new_record_owns(frozen_only, served, monkeypatch):
    """Codex #277: an unreachable bot's last snapshot plus its record counted $12 as $24.

    Round 2: the check must not depend on _trade_cache, which a live-to-paper
    switch replaces before a new snapshot is published, and only closed
    history is withheld: the open position and its stop risk stay.
    """
    owned, kept = _trade(1, 1, 3.0, pair="BTC/USDT"), _trade(3, 3, 2.0, pair="BTC/USDT")
    position = {"trade_id": 9, "pair": "ETH/USDT", "is_open": True, "is_short": False,
                "open_rate": 100.0, "current_rate": 101.0, "amount": 1.0, "stake_amount": 100.0,
                "leverage": 1.0, "open_timestamp": START + 5 * DAY, "profit_abs": 1.0,
                "profit_pct": 1.0, "stop_loss_abs": 95.0, "stop_loss_ratio": -0.05,
                "realized_profit": 0.0}
    monkeypatch.setattr(app, "_trade_cache", {})
    monkeypatch.setitem(app._cache, "bots", {})

    def poll_and_store():  # what the poll loop does with a reachable result
        _, snapshot = _running_poll(monkeypatch, ([owned, kept], True, None), [position])
        app._cache["bots"]["keltner"] = snapshot
        return snapshot

    cached = poll_and_store()  # before the epoch was archived
    assert cached["pnl"]["closed"] == 5.0 and cached["open_trades"]
    assert cached["capital_at_risk"]["abs_loss"] > 0
    _write(served, _build(_spec([owned], record_id="keltner.live-r1", bot_key="keltner")))
    app._trade_cache["keltner"] = []  # a paper ledger replaced it mid-poll; the snapshot did not change
    client = TestClient(app.app)
    bots = client.get("/api/state").json()["bots"]  # the bot is unreachable: last snapshot kept
    assert bots["keltner.live-r1"]["pnl"]["closed"] == 3.0
    stale = bots["keltner"]
    assert stale["measurements_withheld"] is True and stale["history"]["complete"] is False
    assert stale["pnl"]["closed"] is None and stale["stats"] is None and stale["realized_events"] is None
    assert stale["pnl"]["unrealized"] == cached["pnl"]["unrealized"]
    assert stale["open_trades"] == json.loads(json.dumps(cached["open_trades"]))
    assert stale["capital_at_risk"] == json.loads(json.dumps(cached["capital_at_risk"]))
    assert "_ledger" not in stale
    assert client.get("/api/equity/keltner").status_code == 503
    poll_and_store()  # the next successful poll counts the rest, once
    assert client.get("/api/state").json()["bots"]["keltner"]["pnl"]["closed"] == 2.0


def test_coverage_flags_unowned_trades_and_never_calls_an_unreadable_db_covered(tmp_path):
    db = tmp_path / "tradesv3.live.Synthetic.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE trades (id INTEGER, pair TEXT, open_date TEXT, close_date TEXT, is_open INTEGER)")
    rows = [_trade(1, 1, 1.0), _trade(2, 2, 1.0), _trade(4, 9, 1.0)]
    conn.executemany("INSERT INTO trades VALUES (?, ?, ?, ?, 0)",
                     [(t["trade_id"], t["pair"], t["open_date"], t["close_date"]) for t in rows])
    conn.execute("INSERT INTO trades VALUES (3, 'SOL/USDC:USDC', ?, NULL, 1)", (_sqlite_date(START),))
    conn.commit()
    conn.close()
    (tmp_path / "tradesv3.live.Broken.sqlite").write_bytes(b"not a database")
    (tmp_path / "tradesv3.dryrun.Paper.sqlite").write_bytes(b"paper is out of scope")
    owned = {epoch_records.trade_identity(rows[0])}
    result = epoch_records.coverage(tmp_path, owned, closed_before_ms=START + 9 * DAY)
    assert result["uncovered"] == [{"db": db.name, "count": 1, "trade_ids": [2]}]
    assert [u["db"] for u in result["unverified"]] == ["tradesv3.live.Broken.sqlite"]


def test_a_record_never_changes_fleet_status(frozen_only, served):
    before = app._fleet_status()
    _write(served, _build(_spec([_trade(1, 1, 3.0)])))
    after = app._fleet_status()
    assert (after["level"], after["stale_bots"]) == (before["level"], before["stale_bots"])
    state = TestClient(app.app).get("/api/state").json()
    assert RID in state["bots"] and state["epoch_records"]["errors"] == []
    assert state["status"]["level"] == before["level"]


def test_trade_actions_refuse_a_record_and_bot_candles_say_unavailable(frozen_only, served, tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_ACTION_DB", str(tmp_path / "actions.sqlite"))
    _write(served, _build(_spec([_trade(1, 1, 3.0)])))
    client = TestClient(app.app, base_url="https://dashboard.test")
    body = {"request_id": str(uuid.uuid4()), "pair": "SOL/USDC:USDC", "amount": 1.0,
            "open_timestamp": float(START + DAY), "is_short": False}
    for action, extra in (("close", {}), ("cancel-entry", {"order_id": "synthetic", "amount": 0.0})):
        r = client.post(f"/api/trades/{RID}/1/{action}", json={**body, **extra},
                        headers={"Origin": "https://dashboard.test", "X-Trade-Action": action})
        assert r.status_code == 404
    candles = client.get(f"/api/candles/{RID}", params={"pair": "SOL/USDC:USDC"})
    assert candles.status_code == 410 and candles.json()["unavailable"] is True
