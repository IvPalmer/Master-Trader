"""Booked partial exits count as realized P&L (#185).

Freqtrade keeps a filled partial exit (a Killers TP rung) in the open trade's
``realized_profit``; ``profit_abs`` in /status covers only the remaining size.
The fixture mirrors Freqtrade 2026.7 /status: a 3x long with three filled TP
rungs, a resting stop and a resting TP. Prices and sizes are synthetic.
"""

import asyncio
import time

import pytest

import app

FEE_OPEN = 0.0004
FEE_CLOSE = 0.00015
T1, T2, T3 = 1_791_219_617_000, 1_791_306_482_000, 1_791_437_802_000


def _order(side, filled, price, ts=None, *, is_open=False, amount=None):
    return {
        "ft_order_side": side, "status": "open" if is_open else "closed",
        "is_open": is_open, "amount": amount if amount is not None else filled,
        "filled": filled, "remaining": 0.0 if not is_open else amount,
        "safe_price": price, "ft_fee_base": None, "order_filled_timestamp": ts,
    }


def _ft_exit_pnl(amount, price, avg, short=False):
    """Freqtrade's calculate_profit(rate, amount, open_rate) without funding."""
    open_value = amount * avg * (1 - FEE_OPEN if short else 1 + FEE_OPEN)
    close_value = amount * price * (1 + FEE_CLOSE if short else 1 - FEE_CLOSE)
    return open_value - close_value if short else close_value - open_value


FILL_PNL = [_ft_exit_pnl(38, 0.3425, 0.3281), _ft_exit_pnl(38, 0.36, 0.3281),
            _ft_exit_pnl(39, 0.38, 0.3281)]
FUNDING = -0.077  # not in the API's order records; Freqtrade nets it into realized_profit
REALIZED = sum(FILL_PNL) + FUNDING


def jup_trade(**overrides):
    trade = {
        "trade_id": 15, "pair": "JUP/USDC:USDC", "is_short": False, "is_open": True,
        "open_rate": 0.3281, "amount": 192.0, "leverage": 3.0,
        "fee_open": FEE_OPEN, "fee_close": FEE_CLOSE, "trading_mode": "futures",
        "open_timestamp": T1 - 3_600_000, "current_rate": 0.37,
        "profit_abs": 7.33, "realized_profit": REALIZED,
        "total_profit_abs": 7.33 + REALIZED,
        "nr_of_successful_entries": 1, "nr_of_successful_exits": 3,
        "orders": [
            _order("buy", 307.0, 0.3281, T1 - 3_600_000),
            _order("stoploss", 0.0, 0.2891, is_open=True, amount=307.0),
            _order("sell", 38.0, 0.3425, T1),
            _order("sell", 38.0, 0.36, T2),
            _order("sell", 39.0, 0.38, T3),
            _order("sell", 0.0, 0.40, is_open=True, amount=38.0),
        ],
    }
    trade.update(overrides)
    return trade


def test_fills_split_freqtrade_realized_profit_at_fill_times():
    fills = app.partial_exit_fills(jup_trade())

    assert [ts for ts, _ in fills] == [T1, T2, T3]
    assert fills[0][1] == pytest.approx(FILL_PNL[0])
    assert fills[1][1] == pytest.approx(FILL_PNL[1])
    # Funding is unknown per order, so the last fill carries the remainder and
    # the parts add up to Freqtrade's own figure.
    assert fills[2][1] == pytest.approx(FILL_PNL[2] + FUNDING)
    assert sum(p for _, p in fills) == pytest.approx(REALIZED, abs=1e-12)


def test_short_trade_exits_are_buys_and_entry_average_is_used():
    pnl = _ft_exit_pnl(5.0, 90.0, 100.0, short=True)
    trade = {
        "is_short": True, "fee_open": FEE_OPEN, "fee_close": FEE_CLOSE,
        "realized_profit": pnl,
        "orders": [_order("sell", 10.0, 100.0, T1), _order("buy", 5.0, 90.0, T2)],
    }
    assert app.partial_exit_fills(trade) == [[T2, pytest.approx(pnl)]]


def test_filled_stop_counts_as_an_exit_and_unfilled_orders_do_not():
    trade = jup_trade(realized_profit=-1.0, orders=[
        _order("buy", 10.0, 1.0, T1),
        _order("stoploss", 4.0, 0.75, T2),
        _order("sell", 0.0, 1.2, is_open=True, amount=6.0),
    ])
    assert app.partial_exit_fills(trade) == [[T2, -1.0]]


def test_realized_without_fill_times_is_returned_undated():
    trade = jup_trade(orders=[])
    assert app.partial_exit_fills(trade) == [[None, pytest.approx(REALIZED)]]


@pytest.mark.parametrize("realized", [None, 0, 0.0, "x", float("nan")])
def test_no_booked_profit_means_no_fills(realized):
    assert app.partial_exit_fills(jup_trade(realized_profit=realized)) == []


def test_epoch_realized_includes_booked_partials_but_trade_stats_do_not():
    closed = [{"pair": "SUI/USDC:USDC", "profit_abs": -10.0, "trade_duration": 60}]
    pnl, stats, closed_pnl = app._epoch_stats(closed, [jup_trade()], 100.0)

    assert pnl["closed_trades"] == -10.0
    assert pnl["partial_exits"] == round(REALIZED, 2)
    assert pnl["closed"] == round(-10.0 + REALIZED, 2)
    assert pnl["unrealized"] == 7.33
    assert pnl["all_coin"] == round(-10.0 + REALIZED + 7.33, 2)
    # Freqtrade /profit profit_all_coin for the same trades
    assert pnl["all_coin"] == round(-10.0 + jup_trade()["total_profit_abs"], 2)
    assert closed_pnl == -10.0
    assert stats["closed_trade_count"] == 1
    assert stats["winning_trades"] == 0 and stats["losing_trades"] == 1


def test_partial_fill_before_epoch_start_is_outside_the_epoch():
    pnl, _, _ = app._epoch_stats([], [jup_trade()], 100.0, epoch_start_ts_ms=T2)
    assert pnl["partial_exits"] == round(FILL_PNL[1] + FILL_PNL[2] + FUNDING, 2)


def test_realized_equity_steps_at_each_partial_fill():
    events = app._realized_events([], [jup_trade()], 0)
    curve = app._equity_curve_live(events, [], 100.0, T1 - 7_200_000)

    assert [p[0] for p in curve[:4]] == [T1 - 7_200_000, T1, T2, T3]
    assert curve[1][1] == pytest.approx(100.0 + FILL_PNL[0], abs=1e-4)
    assert curve[3][1] == pytest.approx(100.0 + REALIZED, abs=1e-4)
    assert curve[-1][1] == pytest.approx(100.0 + REALIZED, abs=1e-4)


def test_delta_24h_counts_partial_fills_but_not_as_trades():
    now_ms = int(time.time() * 1000)
    trade = jup_trade(realized_profit=2.5, orders=[
        _order("buy", 10.0, 1.0, now_ms - 3 * 86_400_000),
        _order("sell", 2.0, 1.1, now_ms - 2 * 86_400_000),
        _order("sell", 2.0, 1.2, now_ms - 3_600_000),
    ])
    delta = app._delta_24h([], 0.0, None, {}, partial_fills=app.partial_exit_fills(trade))
    fills = app.partial_exit_fills(trade)
    assert delta["new_trades"] == 0
    assert delta["pnl_usd"] == round(fills[1][1], 4)


def test_poll_snapshot_reports_booked_partials(monkeypatch):
    bot = app._bot_meta("killers-ft")
    payloads = {
        "profit": {"bot_start_timestamp": 0},
        "status": [jup_trade()],
        "balance": {"starting_capital": 100.0, "total_bot": 100.0, "total": 100.0},
        "show_config": {"dry_run": False, "timeframe": "5m", "stake_currency": "USDC"},
        "whitelist": {"whitelist": []},
    }

    async def fake_get(client, url, path, *args, **kwargs):
        return payloads.get(path.split("?")[0]), None

    async def fake_plain(*args, **kwargs):
        return None, "unavailable"

    async def fake_history(client, bot, epoch_start_ts_ms):
        return [], True, None

    monkeypatch.setattr(app, "_get", fake_get)
    monkeypatch.setattr(app, "_get_plain", fake_plain)
    monkeypatch.setattr(app, "_fetch_epoch_trades", fake_history)
    monkeypatch.setattr(app, "killers_tp_ladder", lambda *a, **k: {})
    monkeypatch.setitem(bot, "epoch_start_ts_ms", T1 - 7_200_000)
    snapshot = asyncio.run(app._poll_bot(None, bot))

    assert snapshot["pnl"]["closed"] == round(REALIZED, 2)
    assert snapshot["pnl"]["all_coin"] == round(REALIZED + 7.33, 2)
    row = snapshot["open_trades"][0]
    assert row["realized_abs"] == pytest.approx(REALIZED)
    assert [ts for ts, _ in row["partial_exits"]] == [T1, T2, T3]
    start = snapshot["equity_realized"][0][1]
    assert [p[0] for p in snapshot["equity_realized"][1:4]] == [T1, T2, T3]
    assert snapshot["equity_realized"][-1][1] == pytest.approx(start + REALIZED, abs=1e-4)
