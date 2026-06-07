"""Reconciler tests — orphan healing with ambiguity refusal (P0/P1 #C).

Uses a fake FT client (no aiohttp) so the test exercises the matching
logic without spinning a Freqtrade roundtrip.
"""
import asyncio
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.position_graph import PositionGraph  # noqa: E402
from app.reconciler import reconcile_once, ORPHAN_LINK_MIN_AGE_SEC  # noqa: E402


class FakeFt:
    """Drop-in for FreqtradeClient — only needs get_open_trades() for
    reconcile_once()."""
    def __init__(self, trades):
        self._trades = trades

    async def get_open_trades(self):
        return list(self._trades)


def _new_graph():
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    return PositionGraph(tmp.name, instance_id="test")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else \
        asyncio.new_event_loop().run_until_complete(coro)


def _aged_request(g, *, symbol, direction, msg_id):
    """Create an orphan and backdate it past ORPHAN_LINK_MIN_AGE_SEC by
    rewriting opened_at directly."""
    pid = g.open_position(
        symbol=symbol, direction=direction, opened_by_msg_id=msg_id,
        open_entry=100.0, open_sl=99.0, open_tp=110.0, status="requested",
    )
    # Backdate so it passes the age cutoff
    g.conn.execute(
        "UPDATE positions SET opened_at = ? WHERE position_id = ?",
        ("2020-01-01T00:00:00+00:00", pid),
    )
    return pid


# ── Happy path: 1↔1 ───────────────────────────────────────────────────────


def test_reconcile_links_single_orphan_to_single_ft():
    g = _new_graph()
    pid = _aged_request(g, symbol="POL", direction="long", msg_id=1)
    ft = FakeFt([{
        "trade_id": 555, "pair": "POL/USDT:USDT",
        "is_short": False, "amount": 100, "open_rate": 0.09,
        "open_date": "2026-05-26T12:00:00Z",
    }])
    summary = _run(reconcile_once(g, ft))
    assert summary["orphans_linked"] == 1
    assert summary["orphans_ambiguous"] == []
    pos = g.latest_open_position("POL")
    assert pos.position_id == pid
    assert pos.freqtrade_trade_id == 555


def test_reconcile_skips_already_linked_ft():
    """FT trades already attached to a graph position must not be reclaimed."""
    g = _new_graph()
    g.open_position(
        symbol="BTC", direction="long", opened_by_msg_id=10,
        open_entry=80000, open_sl=78000, open_tp=85000,
        freqtrade_trade_id=999,
    )
    _aged_request(g, symbol="BTC", direction="long", msg_id=11)
    ft = FakeFt([{
        "trade_id": 999, "pair": "BTC/USDT:USDT",
        "is_short": False, "amount": 0.01, "open_rate": 80000,
        "open_date": "2026-05-26T12:00:00Z",
    }])
    summary = _run(reconcile_once(g, ft))
    # 999 is already claimed → no orphans to link to (orphan stays requested)
    assert summary["orphans_linked"] == 0
    assert summary["orphans_ambiguous"] == []


# ── Ambiguity refusal ─────────────────────────────────────────────────────


def test_reconcile_refuses_many_orphans_one_ft():
    """N orphans + 1 unclaimed FT trade → cannot attribute → refuse."""
    g = _new_graph()
    _aged_request(g, symbol="POL", direction="long", msg_id=20)
    _aged_request(g, symbol="POL", direction="long", msg_id=21)
    ft = FakeFt([{
        "trade_id": 700, "pair": "POL/USDT:USDT",
        "is_short": False, "amount": 100, "open_rate": 0.09,
        "open_date": "2026-05-26T12:00:00Z",
    }])
    summary = _run(reconcile_once(g, ft))
    assert summary["orphans_linked"] == 0
    assert len(summary["orphans_ambiguous"]) == 1
    item = summary["orphans_ambiguous"][0]
    assert item["pair"] == "POL/USDT:USDT"
    assert item["orphan_count"] == 2
    assert item["ft_unclaimed_count"] == 1
    # No graph mutation
    assert g.latest_open_position("POL") is None


def test_reconcile_refuses_many_orphans_many_ft():
    """N↔M ambiguity → refuse all linking for that bucket."""
    g = _new_graph()
    _aged_request(g, symbol="ETH", direction="short", msg_id=30)
    _aged_request(g, symbol="ETH", direction="short", msg_id=31)
    ft = FakeFt([
        {"trade_id": 800, "pair": "ETH/USDT:USDT", "is_short": True,
         "amount": 1.0, "open_rate": 2400, "open_date": "2026-05-26T12:00:00Z"},
        {"trade_id": 801, "pair": "ETH/USDT:USDT", "is_short": True,
         "amount": 1.0, "open_rate": 2400, "open_date": "2026-05-26T12:01:00Z"},
    ])
    summary = _run(reconcile_once(g, ft))
    assert summary["orphans_linked"] == 0
    assert len(summary["orphans_ambiguous"]) == 1


def test_reconcile_one_orphan_many_ft_refuses():
    """1 orphan + N unclaimed FT trades → REFUSE (could be a manual or
    stale trade hijacking the link). Operator must investigate."""
    g = _new_graph()
    _aged_request(g, symbol="POL", direction="long", msg_id=40)
    ft = FakeFt([
        {"trade_id": 900, "pair": "POL/USDT:USDT", "is_short": False,
         "amount": 100, "open_rate": 0.09, "open_date": "2026-05-26T12:05:00Z"},
        {"trade_id": 901, "pair": "POL/USDT:USDT", "is_short": False,
         "amount": 100, "open_rate": 0.09, "open_date": "2026-05-26T12:00:00Z"},
    ])
    summary = _run(reconcile_once(g, ft))
    assert summary["orphans_linked"] == 0
    assert len(summary["orphans_ambiguous"]) == 1
    item = summary["orphans_ambiguous"][0]
    assert item["orphan_count"] == 1
    assert item["ft_unclaimed_count"] == 2
    # Orphan must remain requested for operator inspection
    assert g.latest_open_position("POL") is None
    assert len(g.requested_orphans()) == 1


# ── Age cutoff ────────────────────────────────────────────────────────────


def test_reconcile_skips_young_orphans():
    """Orphans younger than ORPHAN_LINK_MIN_AGE_SEC must not be linked
    (could still be in-flight inside _handle_open)."""
    g = _new_graph()
    g.open_position(
        symbol="POL", direction="long", opened_by_msg_id=50,
        open_entry=0.09, open_sl=0.085, open_tp=0.10, status="requested",
    )
    # Don't backdate — fresh orphan
    ft = FakeFt([{
        "trade_id": 1000, "pair": "POL/USDT:USDT", "is_short": False,
        "amount": 100, "open_rate": 0.09, "open_date": "2026-05-26T12:00:00Z",
    }])
    summary = _run(reconcile_once(g, ft))
    # Young orphan: not linked, not ambiguous (filtered out before matching)
    assert summary["orphans_linked"] == 0
    assert summary["orphans_ambiguous"] == []


# ── Different sides on same pair are independent buckets ──────────────────


def test_reconcile_long_and_short_independent():
    g = _new_graph()
    pid_long = _aged_request(g, symbol="ETH", direction="long", msg_id=60)
    pid_short = _aged_request(g, symbol="ETH", direction="short", msg_id=61)
    ft = FakeFt([
        {"trade_id": 1100, "pair": "ETH/USDT:USDT", "is_short": False,
         "amount": 1.0, "open_rate": 2400, "open_date": "2026-05-26T12:00:00Z"},
        {"trade_id": 1101, "pair": "ETH/USDT:USDT", "is_short": True,
         "amount": 1.0, "open_rate": 2400, "open_date": "2026-05-26T12:00:00Z"},
    ])
    summary = _run(reconcile_once(g, ft))
    assert summary["orphans_linked"] == 2
    assert summary["orphans_ambiguous"] == []
    long_pos = g.latest_open_position("ETH", direction="long")
    short_pos = g.latest_open_position("ETH", direction="short")
    assert long_pos.freqtrade_trade_id == 1100
    assert short_pos.freqtrade_trade_id == 1101


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
