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


# ── Direction-aware target resolution (P1 #8) ─────────────────────────────


def test_resolve_target_direction_filtered():
    """When classification carries direction, target the matching position."""
    g = _new_graph()
    pid_long = g.open_position(
        symbol="ETH", direction="long",
        opened_by_msg_id=80, open_entry=2400, open_sl=2300, open_tp=2600,
    )
    pid_short = g.open_position(
        symbol="ETH", direction="short",
        opened_by_msg_id=81, open_entry=2500, open_sl=2600, open_tp=2300,
    )
    cls_close_long = {"kind": "close_full", "symbol": "ETH", "direction": "long"}
    targets = g.resolve_target_positions(cls_close_long, [])
    assert len(targets) == 1
    assert targets[0].position_id == pid_long

    cls_close_short = {"kind": "close_full", "symbol": "ETH", "direction": "short"}
    targets = g.resolve_target_positions(cls_close_short, [])
    assert len(targets) == 1
    assert targets[0].position_id == pid_short


def test_resolve_target_ambiguous_no_direction():
    """Long + short open on same coin AND classification has no direction →
    refuse to guess, return empty."""
    g = _new_graph()
    g.open_position(
        symbol="SOL", direction="long",
        opened_by_msg_id=82, open_entry=200, open_sl=190, open_tp=220,
    )
    g.open_position(
        symbol="SOL", direction="short",
        opened_by_msg_id=83, open_entry=210, open_sl=220, open_tp=190,
    )
    cls = {"kind": "close_full", "symbol": "SOL"}  # no direction
    targets = g.resolve_target_positions(cls, [])
    assert targets == []  # ambiguous, must not guess


def test_resolve_target_single_position_no_direction_ok():
    """Only one open position for the symbol → safe to act without direction."""
    g = _new_graph()
    pid = g.open_position(
        symbol="HBAR", direction="long",
        opened_by_msg_id=84, open_entry=0.09, open_sl=0.085, open_tp=0.10,
    )
    cls = {"kind": "close_partial", "symbol": "HBAR", "pct": 50}
    targets = g.resolve_target_positions(cls, [])
    assert len(targets) == 1
    assert targets[0].position_id == pid


def test_resolve_target_applies_to_direction_filtered():
    g = _new_graph()
    pid_btc_short = g.open_position(
        symbol="BTC", direction="short",
        opened_by_msg_id=85, open_entry=80000, open_sl=82000, open_tp=75000,
    )
    g.open_position(
        symbol="BTC", direction="long",
        opened_by_msg_id=86, open_entry=79000, open_sl=77000, open_tp=83000,
    )
    pid_eth_short = g.open_position(
        symbol="ETH", direction="short",
        opened_by_msg_id=87, open_entry=2400, open_sl=2500, open_tp=2100,
    )
    cls = {"kind": "close_partial", "applies_to": ["BTC", "ETH"],
           "direction": "short", "pct": 30}
    targets = g.resolve_target_positions(cls, [])
    ids = {p.position_id for p in targets}
    assert ids == {pid_btc_short, pid_eth_short}


def test_resolve_target_garbage_direction_treated_as_none():
    g = _new_graph()
    g.open_position(
        symbol="ARB", direction="long",
        opened_by_msg_id=88, open_entry=1.2, open_sl=1.1, open_tp=1.4,
    )
    cls = {"kind": "close_full", "symbol": "ARB", "direction": "up"}
    targets = g.resolve_target_positions(cls, [])
    # garbage direction → treated as None → single position is unambiguous
    assert len(targets) == 1


# ── Requested-position lifecycle (P0 #4) ──────────────────────────────────


def test_requested_position_invisible_to_open_queries():
    """A 'requested' position must not appear in open_positions() until
    finalized. Otherwise reconciler will treat it as an FT-missing graph row
    and alert spuriously."""
    g = _new_graph()
    pid = g.open_position(
        symbol="POL", direction="long",
        opened_by_msg_id=90, open_entry=0.09, open_sl=0.085, open_tp=0.10,
        status="requested",
    )
    assert g.latest_open_position("POL") is None
    assert g.open_positions() == []
    orphans = g.requested_orphans()
    assert len(orphans) == 1
    assert orphans[0].position_id == pid


def test_finalize_requested_promotes_to_open():
    g = _new_graph()
    pid = g.open_position(
        symbol="POL", direction="long",
        opened_by_msg_id=91, open_entry=0.09, open_sl=0.085, open_tp=0.10,
        status="requested",
    )
    g.finalize_requested_position(pid, ft_trade_id=12345)
    pos = g.latest_open_position("POL")
    assert pos is not None
    assert pos.position_id == pid
    assert pos.freqtrade_trade_id == 12345
    assert g.requested_orphans() == []


def test_finalize_only_acts_on_requested():
    """Already-open position should NOT be re-finalized (idempotent)."""
    g = _new_graph()
    pid = g.open_position(
        symbol="ETH", direction="long",
        opened_by_msg_id=92, open_entry=2400, open_sl=2300, open_tp=2600,
        freqtrade_trade_id=999,
    )
    # Second finalize should be a no-op (status already 'open')
    g.finalize_requested_position(pid, ft_trade_id=12345)
    pos = g.latest_open_position("ETH")
    assert pos.freqtrade_trade_id == 999  # NOT overwritten


def test_mark_position_failed_removes_from_open():
    g = _new_graph()
    pid = g.open_position(
        symbol="SOL", direction="short",
        opened_by_msg_id=93, open_entry=200, open_sl=210, open_tp=180,
        status="requested",
    )
    g.mark_position_failed(pid, reason="ft-rejected: HTTP 400")
    assert g.latest_open_position("SOL") is None
    assert g.requested_orphans() == []  # no longer requested


def test_invalid_initial_status_raises():
    g = _new_graph()
    try:
        g.open_position(
            symbol="X", direction="long", opened_by_msg_id=1,
            open_entry=1, open_sl=0.9, open_tp=1.1, status="bogus",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for status='bogus'")


# ── Atomic msg claim (P0 #A) ──────────────────────────────────────────────


def test_claim_msg_first_wins():
    """First claim returns True, subsequent same msg_id returns False."""
    g = _new_graph()
    assert g.claim_msg(100, raw_text="first")
    assert not g.claim_msg(100, raw_text="duplicate")
    assert not g.claim_msg(100, raw_text="another duplicate")


def test_claim_msg_then_complete():
    g = _new_graph()
    assert g.claim_msg(101, raw_text="hello", posted_at="2026-05-26T12:00:00Z")
    g.complete_claim(101, "claude", {"kind": "open", "symbol": "BTC"})
    # Once completed, msg_seen still says yes (idempotent for receiver)
    assert g.msg_seen(101)


def test_claim_msg_different_msgs_independent():
    g = _new_graph()
    assert g.claim_msg(200)
    assert g.claim_msg(201)
    assert not g.claim_msg(200)


# ── finalize_requested_position guards (P0 #B) ────────────────────────────


def test_finalize_rejects_none_trade_id():
    g = _new_graph()
    pid = g.open_position(
        symbol="POL", direction="long",
        opened_by_msg_id=300, open_entry=0.09, open_sl=0.085, open_tp=0.10,
        status="requested",
    )
    try:
        g.finalize_requested_position(pid, ft_trade_id=None)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for None ft_trade_id")
    # Position must still be 'requested' — not partially updated
    orphans = g.requested_orphans()
    assert len(orphans) == 1
    assert orphans[0].position_id == pid


def test_finalize_rejects_bool_trade_id():
    g = _new_graph()
    pid = g.open_position(
        symbol="POL", direction="long",
        opened_by_msg_id=301, open_entry=0.09, open_sl=0.085, open_tp=0.10,
        status="requested",
    )
    try:
        g.finalize_requested_position(pid, ft_trade_id=True)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for bool ft_trade_id")


def test_finalize_rejects_string_trade_id():
    g = _new_graph()
    pid = g.open_position(
        symbol="POL", direction="long",
        opened_by_msg_id=302, open_entry=0.09, open_sl=0.085, open_tp=0.10,
        status="requested",
    )
    try:
        g.finalize_requested_position(pid, ft_trade_id="123")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for string ft_trade_id")


# ── Reply-chain filters to open positions only (P1 #D) ────────────────────


def test_reply_chain_skips_closed_opener():
    """If the reply chain points back at a now-CLOSED opener, do not return
    that position to the management dispatcher."""
    g = _new_graph()
    pid = g.open_position(
        symbol="ETH", direction="long",
        opened_by_msg_id=400, open_entry=2400, open_sl=2300, open_tp=2600,
    )
    g.close_full(pid, msg_id=401)  # now closed
    cls = {"kind": "close_full"}  # no symbol/direction
    targets = g.resolve_target_positions(cls, reply_chain_msg_ids=[400])
    assert targets == []  # closed opener must not be returned


def test_reply_chain_skips_failed_opener():
    """A 'failed' requested position should also be invisible to reply
    chain resolution."""
    g = _new_graph()
    pid = g.open_position(
        symbol="POL", direction="long",
        opened_by_msg_id=410, open_entry=0.09, open_sl=0.085, open_tp=0.10,
        status="requested",
    )
    g.mark_position_failed(pid, reason="ft-rejected")
    cls = {"kind": "move_sl", "sl": 0.088}
    targets = g.resolve_target_positions(cls, reply_chain_msg_ids=[410])
    assert targets == []


def test_reply_chain_skips_requested_opener():
    """A still-'requested' position (no FT id yet) must not receive
    management actions via reply chain."""
    g = _new_graph()
    pid = g.open_position(
        symbol="SOL", direction="short",
        opened_by_msg_id=420, open_entry=200, open_sl=210, open_tp=180,
        status="requested",
    )
    cls = {"kind": "close_full"}
    targets = g.resolve_target_positions(cls, reply_chain_msg_ids=[420])
    assert targets == []


def test_reply_chain_finds_open_opener():
    """Sanity: open opener IS reachable via reply chain."""
    g = _new_graph()
    pid = g.open_position(
        symbol="ARB", direction="long",
        opened_by_msg_id=430, open_entry=1.2, open_sl=1.1, open_tp=1.4,
    )
    cls = {"kind": "close_partial", "pct": 25}
    targets = g.resolve_target_positions(cls, reply_chain_msg_ids=[430])
    assert len(targets) == 1
    assert targets[0].position_id == pid


# ── requested_orphans ordering (P0/P1 #C) ─────────────────────────────────


def test_finalize_rejects_double_claim_of_ft_trade_id():
    """Two requested positions cannot both finalize to the same FT
    trade_id — that would double-attribute one exchange exposure."""
    g = _new_graph()
    pid_a = g.open_position(
        symbol="POL", direction="long", opened_by_msg_id=600,
        open_entry=0.09, open_sl=0.085, open_tp=0.10, status="requested",
    )
    pid_b = g.open_position(
        symbol="POL", direction="long", opened_by_msg_id=601,
        open_entry=0.09, open_sl=0.085, open_tp=0.10, status="requested",
    )
    g.finalize_requested_position(pid_a, ft_trade_id=12345)
    try:
        g.finalize_requested_position(pid_b, ft_trade_id=12345)
    except ValueError as e:
        assert "already claimed" in str(e)
        return
    raise AssertionError("expected ValueError on double-claim")


def test_requested_orphans_ordered_oldest_first():
    """Reconciler depends on ASC ordering for deterministic
    oldest-orphan ↔ oldest-FT pairing."""
    import time as _time
    g = _new_graph()
    pid_a = g.open_position(
        symbol="POL", direction="long",
        opened_by_msg_id=500, open_entry=0.09, open_sl=0.085, open_tp=0.10,
        status="requested",
    )
    _time.sleep(0.01)  # ensure timestamps differ
    pid_b = g.open_position(
        symbol="POL", direction="long",
        opened_by_msg_id=501, open_entry=0.09, open_sl=0.085, open_tp=0.10,
        status="requested",
    )
    orphans = g.requested_orphans()
    assert [o.position_id for o in orphans] == [pid_a, pid_b]


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
