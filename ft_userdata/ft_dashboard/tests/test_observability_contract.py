"""Regression coverage for the live observability contract."""

import asyncio
import time
from urllib.parse import parse_qs, urlsplit

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
        query = parse_qs(urlsplit(path).query)
        assert query["order_by_id"] == ["false"]
        offset = int(query["offset"][0])
        return {
            "trades": pages[offset],
            "trades_count": len(pages[offset]),
            "total_trades": 4,
        }, None

    monkeypatch.setattr(app, "_get", fake_get)
    trades, complete, err = asyncio.run(app._fetch_epoch_trades(
        object(), {"url": "http://bot"}, epoch, page_size=2
    ))

    assert [trade["trade_id"] for trade in trades] == [3, 2, 1]
    assert complete is True
    assert err is None


def test_trade_history_uses_total_trades_not_page_count(monkeypatch):
    calls = []

    async def fake_get(_client, _url, path):
        query = parse_qs(urlsplit(path).query)
        offset = int(query["offset"][0])
        calls.append(offset)
        remaining = max(0, 250 - offset)
        size = min(100, remaining)
        rows = [
            {"trade_id": offset + index + 1, "close_timestamp": 20_000 - offset - index}
            for index in range(size)
        ]
        return {"trades": rows, "trades_count": size, "total_trades": 250}, None

    monkeypatch.setattr(app, "_get", fake_get)
    trades, complete, err = asyncio.run(app._fetch_epoch_trades(
        object(), {"url": "http://bot"}, 0, page_size=100
    ))

    assert calls == [0, 100, 200]
    assert len(trades) == 250
    assert complete is True
    assert err is None


def test_partial_history_never_replaces_last_complete_cache(monkeypatch):
    monkeypatch.setattr(app, "_trade_cache", {"bot": [{"trade_id": 7}]})

    retained, using_cache = app._retain_complete_history(
        "bot", [{"trade_id": 8}], complete=False
    )

    assert retained == [{"trade_id": 7}]
    assert using_cache is True
    assert app._trade_cache["bot"] == [{"trade_id": 7}]


def test_native_stop_requires_order_evidence_and_has_first_fill_state():
    bot = {"key": "hl-test", "venue": "hyperliquid"}
    assert app._native_stop_verification(bot, [], [])["status"] == "awaiting-first-fill"

    resting = [{"trade_id": 1, "open_timestamp": int((time.time() - 600) * 1000),
                "nr_of_successful_entries": 0, "orders": []}]
    assert app._native_stop_verification(bot, resting, [])["status"] == "awaiting-fill"

    old_fill = [{"trade_id": 2, "open_fill_timestamp": int((time.time() - 180) * 1000),
                 "nr_of_successful_entries": 1, "orders": []}]
    assert app._native_stop_verification(bot, old_fill, [])["status"] == "missing"

    with_stop = [{
        "trade_id": 3, "open_fill_timestamp": int((time.time() - 180) * 1000),
        "nr_of_successful_entries": 1,
        "orders": [{"ft_order_side": "stoploss", "status": "open", "is_open": True}],
    }]
    assert app._native_stop_verification(bot, with_stop, [])["status"] == "verified"

    cancelled = [{
        "trade_id": 4, "open_fill_timestamp": int((time.time() - 180) * 1000),
        "nr_of_successful_entries": 1,
        "orders": [{"ft_order_side": "stoploss", "status": "canceled", "is_open": False}],
    }]
    assert app._native_stop_verification(bot, cancelled, [])["status"] == "missing"


def test_native_stop_is_evaluated_for_every_filled_open_position():
    now_ms = int(time.time() * 1000)
    bot = {"key": "hl-multi", "venue": "hyperliquid"}
    protected = {
        "trade_id": 1, "pair": "BTC/USDC:USDC", "open_fill_timestamp": now_ms - 180_000,
        "nr_of_successful_entries": 1,
        "orders": [{"ft_order_side": "stoploss", "status": "open", "is_open": True}],
    }
    naked = {
        "trade_id": 2, "pair": "ETH/USDC:USDC", "open_fill_timestamp": now_ms - 180_000,
        "nr_of_successful_entries": 1, "orders": [],
    }

    result = app._native_stop_verification(bot, [protected, naked], [])

    assert result["status"] == "missing"
    assert result["counts"] == {
        "verified": 1, "awaiting-fill": 0, "awaiting-stop": 0, "missing": 1,
    }


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
    assert readiness["status"] == "blocked"
    assert readiness["label"] == "entry gate blocked"
    assert "needs 2.00%" in readiness["detail"]
    assert readiness["metrics"]["oi_growth"] == 0.013


def test_readiness_aggregates_every_watched_pair():
    now_ms = int(time.time() * 1000)
    bot = {"key": "oi-trend", "entry_gate_label": "OI gate"}

    def payload(pair, growth):
        return {
            "pair": pair, "last_analyzed_ts": now_ms // 1000, "data_stop_ts": now_ms,
            "columns": ["date", "oi_growth", "btc_trend", "enter_long"],
            "data": [[now_ms, growth, 1, 0]],
        }

    readiness = app._fleet_candle_readiness(
        bot, [payload("BTC/USDT", 0.01), payload("ETH/USDT", 0.03)], "1h"
    )

    assert readiness["pair_count"] == 2
    assert len(readiness["pairs"]) == 2
    assert readiness["label"] == "1/2 pairs clear OI/BTC gates"
    assert readiness["metrics"] == {"oi_growth_min": 0.01, "oi_growth_max": 0.03}


def test_receiver_counts_only_actionable_signal_kinds():
    now = time.time()
    ingress = {"ingress": [
        {"received_at": now, "kind": "chat", "final_action": "ignored"},
        {"received_at": now - 10, "kind": "open", "final_action": "skipped"},
        {"received_at": now - 20, "kind": "signal_update", "final_action": "updated"},
    ]}

    result = app._receiver_readiness(
        {"entry_gate_label": "external signal"}, {"ok": True}, ingress, None
    )

    assert result["signals_24h"] == 2
    assert result["last_action"] == "skipped"
    assert result["last_event_ts_ms"] > result["last_signal_ts_ms"]


def test_gate2_uses_epoch_metrics_only():
    baseline = {"annual_return_pct": 10, "profit_factor": 1.5, "max_dd_pct": 10}
    gate = app._gate2(
        {"all_pct": 1.0}, {"profit_factor": 1.4, "max_drawdown": 0.05}, 36.5, baseline
    )

    assert gate["profit"]["actual_pct"] == 1.0
    assert gate["pf"]["actual"] == 1.4
    assert gate["dd"]["actual_pct"] == 5.0


def test_every_bot_declares_epoch_version_and_gate_contract():
    for bot in app.BOTS:
        assert bot["epoch_start_ts_ms"] > 0
        assert bot["epoch_label"]
        assert bot["strategy_version"]
        assert bot["entry_gate_label"]
