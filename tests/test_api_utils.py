"""Tests for api_utils: fallback, deferred persistence, trade-type rate limiting."""

import json
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "ft_userdata"))

from api_utils import (
    DeferredStateWriter,
    TradeTypeRateLimiter,
    execute_with_fallback,
)


# -- Provider fallback --

def test_fallback_uses_primary_on_success():
    result = execute_with_fallback(
        primary_fn=lambda: "primary_data",
        fallback_fn=lambda: "fallback_data",
        context="test",
    )
    assert result == "primary_data"


def test_fallback_uses_secondary_on_failure():
    def failing_primary():
        raise ConnectionError("primary down")

    result = execute_with_fallback(
        primary_fn=failing_primary,
        fallback_fn=lambda: "fallback_data",
        context="test",
    )
    assert result == "fallback_data"


def test_fallback_returns_none_if_both_fail():
    def failing():
        raise ConnectionError("down")

    result = execute_with_fallback(
        primary_fn=failing,
        fallback_fn=failing,
        context="test",
    )
    assert result is None


# -- Deferred persistence --

def test_deferred_writer_stage_and_commit(tmp_path):
    path = tmp_path / "state.json"
    writer = DeferredStateWriter(path)

    writer.stage({"status": "pending"})
    assert writer.has_staged
    assert not path.exists()  # Not written yet

    writer.commit()
    assert not writer.has_staged
    assert path.exists()
    assert json.loads(path.read_text())["status"] == "pending"


def test_deferred_writer_discard(tmp_path):
    path = tmp_path / "state.json"
    writer = DeferredStateWriter(path)

    writer.stage({"status": "pending"})
    writer.discard()
    assert not writer.has_staged
    assert not path.exists()


def test_deferred_writer_commit_without_stage(tmp_path):
    path = tmp_path / "state.json"
    writer = DeferredStateWriter(path)
    assert writer.commit() is False


# -- Trade-type rate limiting --

def test_trade_limiter_allows_within_limit():
    limiter = TradeTypeRateLimiter({"scalp": {"max_per_hour": 5, "max_concurrent": 3}})
    allowed, reason = limiter.check("scalp", current_open_trades=0)
    assert allowed is True


def test_trade_limiter_blocks_hourly_excess():
    limiter = TradeTypeRateLimiter({"scalp": {"max_per_hour": 2, "max_concurrent": 10}})
    limiter.record_trade("scalp")
    limiter.record_trade("scalp")
    allowed, reason = limiter.check("scalp")
    assert allowed is False
    assert "Hourly limit" in reason


def test_trade_limiter_blocks_concurrent_excess():
    limiter = TradeTypeRateLimiter({"swing": {"max_per_hour": 100, "max_concurrent": 2}})
    allowed, reason = limiter.check("swing", current_open_trades=2)
    assert allowed is False
    assert "Concurrent limit" in reason


def test_trade_limiter_unknown_type_allowed():
    limiter = TradeTypeRateLimiter({"scalp": {"max_per_hour": 1, "max_concurrent": 1}})
    allowed, _ = limiter.check("unknown_type")
    assert allowed is True


def test_trade_limiter_stats():
    limiter = TradeTypeRateLimiter({"scalp": {"max_per_hour": 10, "max_concurrent": 5}})
    limiter.record_trade("scalp")
    limiter.record_trade("scalp")
    stats = limiter.get_stats()
    assert stats["scalp"]["trades_this_hour"] == 2
