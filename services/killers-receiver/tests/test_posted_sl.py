"""KILLERS_POSTED_SL hard-stop mode — breach logic + force-exit lifecycle.

The mode is OFF by default and force-exits an open position once mark price
breaches the signal's posted SL, mirroring the channel-close path (full exit +
cancel TP ladder + mark closed). Fail-open on missing mark / failed exit.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import main as receiver_main  # noqa: E402
from app.main import _posted_sl_breached  # noqa: E402


# ── pure breach logic ──────────────────────────────────────────────────────

def test_long_breaches_at_or_below_sl():
    assert _posted_sl_breached("long", 0.060, 0.060) is True   # exactly at SL
    assert _posted_sl_breached("long", 0.0599, 0.060) is True  # below
    assert _posted_sl_breached("long", 0.061, 0.060) is False  # above → safe

def test_short_breaches_at_or_above_sl():
    assert _posted_sl_breached("short", 180.0, 180.0) is True
    assert _posted_sl_breached("short", 181.0, 180.0) is True
    assert _posted_sl_breached("short", 179.0, 180.0) is False


# ── lifecycle ──────────────────────────────────────────────────────────────

def _setup(posted_sl: bool, sl_abs=0.060, direction="long"):
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    os.environ["KILLERS_DB"] = tf.name
    os.environ["KILLERS_POSTED_SL"] = "true" if posted_sl else "false"
    cfg = receiver_main.Config()
    conn = receiver_main.init_db(cfg.db_path)
    conn.execute(
        "INSERT INTO positions (signal_id, symbol, pair, direction, state, "
        " open_msg_id, open_date, stake_usd, leverage, sl_abs, ft_trade_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (1, "SKY", "SKY/USDT:USDT", direction, "open", 111,
         "2026-06-02T14:41:00+00:00", 20.0, 5.0, sl_abs, 10),
    )
    pos_id = conn.execute("SELECT pos_id FROM positions WHERE open_msg_id=111").fetchone()[0]
    # an active TP rung that must be cancelled on SL exit
    conn.execute("INSERT INTO target_orders (pos_id, idx, price, amount, state) "
                 "VALUES (?,?,?,?, 'active')", (pos_id, 0, 0.07, 100.0))
    return cfg, conn, pos_id


def _patch(monkeypatch, mark, exit_status=200):
    calls = {"exit": []}

    async def fake_mark(symbol, session=None):
        return mark

    async def fake_exit(_cfg, trade_id, pct=None, session=None):
        calls["exit"].append((trade_id, pct))
        return {"status": exit_status, "body": json.dumps({"result": "ok"})}

    monkeypatch.setattr(receiver_main, "get_binance_mark_price", fake_mark)
    monkeypatch.setattr(receiver_main, "ft_force_exit", fake_exit)
    return calls


def _state(conn, pos_id):
    r = conn.execute("SELECT state, close_reason FROM positions WHERE pos_id=?", (pos_id,)).fetchone()
    to = conn.execute("SELECT state FROM target_orders WHERE pos_id=?", (pos_id,)).fetchone()
    return r["state"], r["close_reason"], (to["state"] if to else None)


def test_breach_force_exits_and_cancels_ladder(monkeypatch):
    cfg, conn, pid = _setup(posted_sl=True, sl_abs=0.060)
    calls = _patch(monkeypatch, mark=0.0585)  # below SL → breach
    asyncio.run(receiver_main._check_posted_sl(cfg, conn))
    assert calls["exit"] == [(10, 100)]                       # full force_exit fired
    assert _state(conn, pid) == ("closed", "posted_sl", "cancelled")


def test_no_breach_leaves_open(monkeypatch):
    cfg, conn, pid = _setup(posted_sl=True, sl_abs=0.060)
    calls = _patch(monkeypatch, mark=0.063)   # above SL → safe
    asyncio.run(receiver_main._check_posted_sl(cfg, conn))
    assert calls["exit"] == []
    assert _state(conn, pid) == ("open", None, "active")


def test_off_by_default_is_noop(monkeypatch):
    cfg, conn, pid = _setup(posted_sl=False, sl_abs=0.060)
    calls = _patch(monkeypatch, mark=0.0585)  # would breach, but mode OFF
    asyncio.run(receiver_main._check_posted_sl(cfg, conn))
    assert calls["exit"] == []
    assert _state(conn, pid) == ("open", None, "active")


def test_missing_mark_fails_open(monkeypatch):
    cfg, conn, pid = _setup(posted_sl=True, sl_abs=0.060)
    calls = _patch(monkeypatch, mark=None)    # mark fetch failed
    asyncio.run(receiver_main._check_posted_sl(cfg, conn))
    assert calls["exit"] == []
    assert _state(conn, pid) == ("open", None, "active")


def test_failed_exit_leaves_open(monkeypatch):
    cfg, conn, pid = _setup(posted_sl=True, sl_abs=0.060)
    calls = _patch(monkeypatch, mark=0.0585, exit_status=500)  # FT rejects
    asyncio.run(receiver_main._check_posted_sl(cfg, conn))
    assert calls["exit"] == [(10, 100)]                        # attempted
    assert _state(conn, pid) == ("open", None, "active")       # but not marked closed


def test_short_breach_above_sl(monkeypatch):
    cfg, conn, pid = _setup(posted_sl=True, sl_abs=180.0, direction="short")
    calls = _patch(monkeypatch, mark=182.0)   # above SL → short breach
    asyncio.run(receiver_main._check_posted_sl(cfg, conn))
    assert calls["exit"] == [(10, 100)]
    assert _state(conn, pid)[:2] == ("closed", "posted_sl")
