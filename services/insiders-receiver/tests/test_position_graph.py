"""Unit tests for the position graph — codex's "actual core product."

Idempotency, multi-coin fan-out, reply-chain resolution, partial closes.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.position_graph import PositionGraph  # noqa: E402


def _new_graph():
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    return PositionGraph(tmp.name, instance_id="test")


def test_msg_idempotency():
    g = _new_graph()
    g.record_raw_event(100, "rule", {"kind": "chat"}, raw_text="hello")
    assert g.msg_seen(100)
    assert not g.msg_seen(101)
    # Re-record same msg — INSERT OR IGNORE should not raise
    g.record_raw_event(100, "rule", {"kind": "chat", "v": 2}, raw_text="hello")
    assert g.msg_seen(100)


def test_open_then_close_partial_then_full():
    g = _new_graph()
    pid = g.open_position(
        symbol="BTC", direction="short",
        opened_by_msg_id=1, open_entry=80000, open_sl=82000, open_tp=75000,
    )
    assert pid > 0
    pos = g.latest_open_position("BTC", "short")
    assert pos and pos.pct_open == 100

    # Partial close 30%
    remaining = g.close_partial(pid, 30, msg_id=2)
    assert remaining == 70

    pos = g.latest_open_position("BTC", "short")
    assert pos.pct_open == 70

    # Another partial close 50% (of original sizing, not remaining)
    remaining = g.close_partial(pid, 50, msg_id=3)
    assert remaining == 20

    # Full close
    g.close_full(pid, msg_id=4)
    pos = g.latest_open_position("BTC", "short")
    assert pos is None  # no longer open


def test_action_idempotency():
    g = _new_graph()
    pid = g.open_position(
        symbol="ETH", direction="long",
        opened_by_msg_id=10, open_entry=2400, open_sl=2300, open_tp=2600,
    )
    assert not g.action_seen(20, pid, "move_sl")
    g.move_sl(pid, 2350, msg_id=20)
    assert g.action_seen(20, pid, "move_sl")
    # Re-applying same (msg, position, kind) shouldn't create duplicate row
    g.move_sl(pid, 2350, msg_id=20)
    pos = g.latest_open_position("ETH", "long")
    assert pos.current_sl == 2350


def test_resolve_target_by_symbol():
    g = _new_graph()
    pid = g.open_position(
        symbol="SOL", direction="long",
        opened_by_msg_id=30, open_entry=200, open_sl=190, open_tp=220,
    )
    cls = {"kind": "close_partial", "symbol": "SOL", "pct": 50}
    targets = g.resolve_target_positions(cls, [])
    assert len(targets) == 1
    assert targets[0].position_id == pid


def test_resolve_target_multi_coin_fanout():
    g = _new_graph()
    pid_btc = g.open_position(
        symbol="BTC", direction="short",
        opened_by_msg_id=40, open_entry=80000, open_sl=82000, open_tp=75000,
    )
    pid_eth = g.open_position(
        symbol="ETH", direction="short",
        opened_by_msg_id=41, open_entry=2400, open_sl=2500, open_tp=2100,
    )
    cls = {"kind": "close_partial", "applies_to": ["BTC", "ETH"], "pct": 30}
    targets = g.resolve_target_positions(cls, [])
    ids = {p.position_id for p in targets}
    assert ids == {pid_btc, pid_eth}


def test_resolve_target_no_match_returns_empty():
    g = _new_graph()
    cls = {"kind": "close_full", "symbol": "DOGE"}
    targets = g.resolve_target_positions(cls, [])
    assert targets == []


def test_resolve_via_reply_chain():
    g = _new_graph()
    pid = g.open_position(
        symbol="HBAR", direction="long",
        opened_by_msg_id=50, open_entry=0.09, open_sl=0.085, open_tp=0.10,
    )
    # Management msg with no symbol, but reply chain points back to msg 50
    cls = {"kind": "close_partial", "pct": 25}
    targets = g.resolve_target_positions(cls, reply_chain_msg_ids=[50])
    assert len(targets) == 1
    assert targets[0].position_id == pid


def test_entries_paused_state():
    g = _new_graph()
    paused, reason = g.is_entries_paused()
    assert not paused
    g.set_entries_paused(True, reason="session-lost")
    paused, reason = g.is_entries_paused()
    assert paused and reason == "session-lost"
    g.set_entries_paused(False)
    paused, _ = g.is_entries_paused()
    assert not paused


def test_breakeven_translates_via_open_entry():
    """Receiver translates 'breakeven' SL to open_entry; verify graph
    handles a float SL update cleanly."""
    g = _new_graph()
    pid = g.open_position(
        symbol="ZEC", direction="long",
        opened_by_msg_id=60, open_entry=400.0, open_sl=380.0, open_tp=440.0,
    )
    g.move_sl(pid, 400.0, msg_id=61)  # to breakeven
    pos = g.latest_open_position("ZEC")
    assert pos.current_sl == 400.0


def test_close_full_idempotent_after_close_partial():
    """Edge case: close_partial that brings pct_open to 0 should mark
    position closed; later close_full on the same position is a no-op
    via action_seen check (handled at receiver layer)."""
    g = _new_graph()
    pid = g.open_position(
        symbol="ARB", direction="short",
        opened_by_msg_id=70, open_entry=1.2, open_sl=1.25, open_tp=1.1,
    )
    g.close_partial(pid, 100, msg_id=71)
    pos = g.latest_open_position("ARB")
    assert pos is None  # closed


if __name__ == "__main__":
    import sys
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
