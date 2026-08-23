"""Venue-specific symbol and public-price coverage for Hyperliquid execution."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import main as receiver_main  # noqa: E402


class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    async def json(self):
        return self._payload


def test_hyperliquid_pair_mapping(monkeypatch):
    monkeypatch.setenv("KILLERS_EXECUTION_VENUE", "hyperliquid")

    assert receiver_main.to_freqtrade_pair("BTC") == "BTC/USDC:USDC"
    assert receiver_main.to_freqtrade_pair("PEPE") == "KPEPE/USDC:USDC"
    assert receiver_main.to_freqtrade_pair("1000BONK") == "KBONK/USDC:USDC"
    assert receiver_main.to_freqtrade_pair("GOLD") == "PAXG/USDC:USDC"
    assert receiver_main.to_freqtrade_pair("RNDR") == "RENDER/USDC:USDC"


def test_binance_mapping_remains_default(monkeypatch):
    monkeypatch.delenv("KILLERS_EXECUTION_VENUE", raising=False)

    assert receiver_main.to_freqtrade_pair("BTC") == "BTC/USDT:USDT"
    assert receiver_main.to_freqtrade_pair("PEPE") == "1000PEPE/USDT:USDT"


def test_parse_hyperliquid_mid_rejects_bad_values():
    assert asyncio.run(receiver_main._parse_hyperliquid_mid(
        _Response({"BTC": "77422.0"}), "BTC",
    )) == 77422.0
    assert asyncio.run(receiver_main._parse_hyperliquid_mid(
        _Response({"BTC": "nan"}), "BTC",
    )) is None
    assert asyncio.run(receiver_main._parse_hyperliquid_mid(
        _Response({"ETH": "2447.8"}), "BTC",
    )) is None
    assert asyncio.run(receiver_main._parse_hyperliquid_mid(
        _Response({"BTC": "77422.0"}, status=503), "BTC",
    )) is None


def test_execution_price_routes_to_hyperliquid(monkeypatch):
    monkeypatch.setenv("KILLERS_EXECUTION_VENUE", "hyperliquid")

    async def fake_hl(symbol, session=None):
        return 123.45

    async def forbidden_binance(symbol, session=None):
        raise AssertionError("Binance price API must not be used for HL execution")

    monkeypatch.setattr(receiver_main, "get_hyperliquid_mark_price", fake_hl)
    monkeypatch.setattr(receiver_main, "get_binance_mark_price", forbidden_binance)

    assert asyncio.run(receiver_main.get_execution_mark_price("SOL")) == 123.45
