"""Portfolio stop-at-risk warden tests.

Mocks the Freqtrade REST layer (patch.object on risk_warden.<helper>) and
builds a tmp in-memory sqlite `positions` table for the SL lookup.
"""
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

# risk_warden lives in ../warden relative to this tests dir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "warden"))
import risk_warden  # noqa: E402


def _conn(rows):
    """Build an in-memory positions table. `rows` = list of
    (ft_trade_id, pair, sl_abs, state)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE positions (pos_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "ft_trade_id INTEGER, pair TEXT, sl_abs REAL, state TEXT, "
        "open_date TEXT)")
    for i, (tid, pair, sl, state) in enumerate(rows):
        conn.execute(
            "INSERT INTO positions (ft_trade_id, pair, sl_abs, state, open_date) "
            "VALUES (?,?,?,?,?)",
            (tid, pair, sl, state, f"2026-07-0{i+1}T00:00:00+00:00"))
    return conn


def _cfg(dry_run=True, cap_pct=10.0):
    cfg = risk_warden.WardenConfig()
    cfg.dry_run = dry_run
    cfg.cap_pct = cap_pct
    return cfg


def _trade(trade_id, pair, amount, current_rate, is_short=False):
    return {"trade_id": trade_id, "pair": pair, "amount": amount,
            "current_rate": current_rate, "is_short": is_short, "leverage": 5}


# ── loss_at_stop unit ───────────────────────────────────────────────────────


def test_loss_at_stop_long():
    t = _trade(1, "AAA/USDT:USDT", amount=10, current_rate=100)
    assert risk_warden.loss_at_stop(t, 90.0) == 100.0  # (100-90)*10


def test_loss_at_stop_short():
    t = _trade(1, "AAA/USDT:USDT", amount=2, current_rate=100, is_short=True)
    assert risk_warden.loss_at_stop(t, 120.0) == 40.0  # (120-100)*2


def test_loss_at_stop_floors_at_zero():
    # Long whose stop is ABOVE current (favorable) → no downside contribution.
    t = _trade(1, "AAA/USDT:USDT", amount=10, current_rate=100)
    assert risk_warden.loss_at_stop(t, 110.0) == 0.0


# ── cap not breached → no action ────────────────────────────────────────────


def test_cap_not_breached_no_action():
    conn = _conn([(42, "KITE/USDT:USDT", 95.0, "open")])
    cfg = _cfg(dry_run=False)
    trades = [_trade(42, "KITE/USDT:USDT", amount=1.0, current_rate=100.0)]

    called = {"forceexit": False}

    def fake_forceexit(*a, **k):
        called["forceexit"] = True
        return 200, "ok"

    with patch.object(risk_warden, "get_open_trades", return_value=trades), \
         patch.object(risk_warden, "get_wallet_total", return_value=1000.0), \
         patch.object(risk_warden, "forceexit_full", side_effect=fake_forceexit):
        summary = risk_warden.run_once(cfg, conn)

    # risk = (100-95)*1 = 5 <= cap 100
    assert summary["breached"] is False
    assert summary["actions"] == []
    assert called["forceexit"] is False
    assert summary["initial_risk"] == 5.0


# ── breached → largest closed first; dry-run doesn't forceexit ──────────────


def test_breached_dry_run_reports_largest_no_forceexit():
    conn = _conn([
        (1, "AAA/USDT:USDT", 90.0, "open"),   # loss (100-90)*10 = 100
        (2, "BBB/USDT:USDT", 50.0, "open"),   # loss (100-50)*1  = 50
    ])
    cfg = _cfg(dry_run=True)
    trades = [
        _trade(1, "AAA/USDT:USDT", amount=10, current_rate=100),
        _trade(2, "BBB/USDT:USDT", amount=1, current_rate=100),
    ]

    def boom(*a, **k):
        raise AssertionError("dry-run must NOT call forceexit")

    with patch.object(risk_warden, "get_open_trades", return_value=trades), \
         patch.object(risk_warden, "get_wallet_total", return_value=1000.0), \
         patch.object(risk_warden, "forceexit_full", side_effect=boom):
        summary = risk_warden.run_once(cfg, conn)

    # total 150 > cap 100 → breach; largest (trade 1, loss 100) targeted first.
    assert summary["breached"] is True
    assert len(summary["actions"]) == 1
    assert summary["actions"][0]["trade_id"] == 1
    assert summary["actions"][0]["closed"] is False
    assert summary["actions"][0]["dry_run"] is True
    # After removing trade 1, remaining risk 50 <= cap 100.
    assert summary["remaining_risk"] == 50.0


def test_breached_live_closes_largest_first():
    conn = _conn([
        (1, "AAA/USDT:USDT", 90.0, "open"),   # loss 100
        (2, "BBB/USDT:USDT", 50.0, "open"),   # loss 50
    ])
    cfg = _cfg(dry_run=False)
    trades = [
        _trade(1, "AAA/USDT:USDT", amount=10, current_rate=100),
        _trade(2, "BBB/USDT:USDT", amount=1, current_rate=100),
    ]

    closed = []

    def fake_forceexit(_cfg, trade_id):
        closed.append(trade_id)
        return 200, '{"result":"closed"}'

    with patch.object(risk_warden, "get_open_trades", return_value=trades), \
         patch.object(risk_warden, "get_wallet_total", return_value=1000.0), \
         patch.object(risk_warden, "forceexit_full", side_effect=fake_forceexit):
        summary = risk_warden.run_once(cfg, conn)

    assert closed == [1], "largest loss_at_stop closed first, and only until resolved"
    assert summary["actions"][0]["closed"] is True
    assert summary["actions"][0]["ft_status"] == 200
    assert summary["remaining_risk"] == 50.0


def test_safety_valve_caps_at_three_closes():
    # Five equally-large positions, cap forces closing but 3-close valve stops.
    rows = [(i, f"P{i}/USDT:USDT", 50.0, "open") for i in range(1, 6)]
    conn = _conn(rows)
    cfg = _cfg(dry_run=False)
    trades = [_trade(i, f"P{i}/USDT:USDT", amount=1, current_rate=100)
              for i in range(1, 6)]  # each loss (100-50)*1 = 50, total 250

    closed = []

    def fake_forceexit(_cfg, trade_id):
        closed.append(trade_id)
        return 200, "ok"

    with patch.object(risk_warden, "get_open_trades", return_value=trades), \
         patch.object(risk_warden, "get_wallet_total", return_value=1000.0), \
         patch.object(risk_warden, "forceexit_full", side_effect=fake_forceexit):
        summary = risk_warden.run_once(cfg, conn)

    # cap = 100; total 250. Closing 3 (=150 removed) leaves 100 which is NOT
    # > cap, so loop stops — but never more than 3 regardless.
    assert len(closed) <= risk_warden.MAX_CLOSES_PER_RUN
    assert len(summary["actions"]) <= risk_warden.MAX_CLOSES_PER_RUN


# ── live forceexit failure → victim stays in risk, loop breaks ──────────────


def test_live_failed_forceexit_keeps_risk_and_breaks():
    conn = _conn([
        (1, "AAA/USDT:USDT", 90.0, "open"),   # loss 100
        (2, "BBB/USDT:USDT", 50.0, "open"),   # loss 50
    ])
    cfg = _cfg(dry_run=False)
    trades = [
        _trade(1, "AAA/USDT:USDT", amount=10, current_rate=100),
        _trade(2, "BBB/USDT:USDT", amount=1, current_rate=100),
    ]

    calls = []

    def fake_forceexit(_cfg, trade_id):
        calls.append(trade_id)
        return 500, '{"error":"exchange down"}'

    with patch.object(risk_warden, "get_open_trades", return_value=trades), \
         patch.object(risk_warden, "get_wallet_total", return_value=1000.0), \
         patch.object(risk_warden, "forceexit_full", side_effect=fake_forceexit):
        summary = risk_warden.run_once(cfg, conn)

    # cap=100, total 150 > cap → breach; largest (trade 1) targeted, fails.
    assert summary["breached"] is True
    assert calls == [1], "loop breaks after first failure — no further closes"
    assert summary["actions"][0]["closed"] is False
    # Victim NOT removed → its risk stays; remaining_risk keeps the full 150.
    assert summary["remaining_risk"] == 150.0
    assert len(summary["attempted_failed"]) == 1
    assert summary["attempted_failed"][0]["trade_id"] == 1
    assert summary["attempted_failed"][0]["ft_status"] == 500


# ── ft_trade_id / pair mismatch skipped ─────────────────────────────────────


def test_pair_mismatch_skipped():
    # Receiver row for ft_trade_id=42 has a DIFFERENT pair (reuse corruption).
    # If it were priced, loss = (100-1)*100 = 9900 → huge breach. It must be
    # SKIPPED instead, leaving risk 0 → no action.
    conn = _conn([(42, "DOGE/USDT:USDT", 1.0, "open")])
    cfg = _cfg(dry_run=False)
    trades = [_trade(42, "KITE/USDT:USDT", amount=100, current_rate=100)]

    def boom(*a, **k):
        raise AssertionError("mismatched trade must not be closed")

    with patch.object(risk_warden, "get_open_trades", return_value=trades), \
         patch.object(risk_warden, "get_wallet_total", return_value=1000.0), \
         patch.object(risk_warden, "forceexit_full", side_effect=boom):
        summary = risk_warden.run_once(cfg, conn)

    assert summary["breached"] is False
    assert summary["initial_risk"] == 0.0
    assert summary["actions"] == []


def test_missing_sl_skipped():
    conn = _conn([(42, "KITE/USDT:USDT", None, "open")])
    cfg = _cfg(dry_run=False)
    trades = [_trade(42, "KITE/USDT:USDT", amount=100, current_rate=100)]

    with patch.object(risk_warden, "get_open_trades", return_value=trades), \
         patch.object(risk_warden, "get_wallet_total", return_value=1000.0), \
         patch.object(risk_warden, "forceexit_full",
                      side_effect=AssertionError):
        summary = risk_warden.run_once(cfg, conn)

    assert summary["initial_risk"] == 0.0
    assert summary["breached"] is False


# ── FT unreachable → no action ──────────────────────────────────────────────


def test_ft_unreachable_no_action():
    conn = _conn([(1, "AAA/USDT:USDT", 90.0, "open")])
    cfg = _cfg(dry_run=False)

    with patch.object(risk_warden, "get_open_trades", return_value=None), \
         patch.object(risk_warden, "get_wallet_total", return_value=1000.0), \
         patch.object(risk_warden, "forceexit_full",
                      side_effect=AssertionError):
        summary = risk_warden.run_once(cfg, conn)

    assert summary["status"] == "ft_unreachable"
    assert summary["breached"] is False


if __name__ == "__main__":
    funcs = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    failed = []
    for f in funcs:
        try:
            f()
            print(f"PASS  {f.__name__}")
        except Exception as e:
            failed.append((f.__name__, e))
            print(f"FAIL  {f.__name__}: {e}")
    if failed:
        sys.exit(1)
    print(f"\n{len(funcs)} tests passed")
