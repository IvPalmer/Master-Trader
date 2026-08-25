"""Regression coverage for the live observability contract."""

import asyncio
import time

import app


def test_epoch_stats_ignore_lifetime_values_and_use_complete_trade_set():
    closed = [
        {"pair": "BTC/USDT", "profit_abs": 3.0, "trade_duration": 10},
        {"pair": "ETH/USDT", "profit_abs": -1.0, "trade_duration": 30},
    ]
    pnl, stats, closed_pnl = app._epoch_stats(
        closed, [{"profit_abs": 0.5}], 100.0
    )

    assert closed_pnl == 2.0
    assert pnl == {"closed": 2.0, "all_coin": 2.5, "closed_pct": 2.0, "all_pct": 2.5}
    assert stats["closed_trade_count"] == 2
    assert stats["winning_trades"] == 1
    assert stats["losing_trades"] == 1
    assert stats["profit_factor"] == 3.0
    assert stats["scope"] == "epoch"


def test_trade_history_paginates_until_epoch_boundary(monkeypatch):
    epoch = 10_000
    pages = {
        0: [{"trade_id": 3, "close_timestamp": 13_000, "is_open": False},
            {"trade_id": 2, "close_timestamp": 12_000, "is_open": False}],
        2: [{"trade_id": 1, "close_timestamp": 11_000, "is_open": False},
            {"trade_id": 0, "close_timestamp": 9_000, "is_open": False}],
    }

    async def fake_get(_client, _url, path):
        offset = int(path.split("offset=")[1])
        return {"trades": pages[offset], "trades_count": 4}, None

    monkeypatch.setattr(app, "_get", fake_get)
    trades, complete, err = asyncio.run(app._fetch_epoch_trades(
        object(), {"url": "http://bot"}, epoch, page_size=2
    ))

    assert [trade["trade_id"] for trade in trades] == [3, 2, 1]
    assert complete is True
    assert err is None


def test_native_stop_requires_order_evidence_and_has_first_fill_state():
    bot = {"venue": "hyperliquid"}
    assert app._native_stop_verification(bot, [], [])["status"] == "awaiting-first-fill"

    old_open = [{"open_timestamp": int((time.time() - 180) * 1000), "orders": []}]
    assert app._native_stop_verification(bot, old_open, [])["status"] == "missing"

    with_stop = [{
        "open_timestamp": int((time.time() - 180) * 1000),
        "orders": [{"ft_order_side": "stoploss", "status": "open"}],
    }]
    assert app._native_stop_verification(bot, with_stop, [])["status"] == "verified"


def test_oi_readiness_exposes_dominant_gate_and_feed_age():
    now_ms = int(time.time() * 1000)
    payload = {
        "pair": "ETH/USDT",
        "last_analyzed_ts": now_ms // 1000,
        "data_stop_ts": now_ms,
        "columns": ["date", "oi_growth", "btc_trend", "enter_long"],
        "data": [[now_ms, 0.013, 1, 0]],
    }
    bot = {
        "key": "oi-trend",
        "entry_gate_label": "EMA20 reclaim + fresh OI ≥ 2% + BTC trend",
    }

    readiness = app._candle_readiness(bot, payload, "1h")

    assert readiness["healthy"] is True
    assert readiness["status"] == "ready"
    assert "needs 2.00%" in readiness["detail"]
    assert readiness["metrics"]["oi_growth"] == 0.013


def test_every_bot_declares_epoch_version_and_gate_contract():
    for bot in app.BOTS:
        assert bot["epoch_start_ts_ms"] > 0
        assert bot["epoch_label"]
        assert bot["strategy_version"]
        assert bot["entry_gate_label"]

