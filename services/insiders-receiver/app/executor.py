"""Freqtrade REST executor + market sanity bands + risk-budget sizing.

This is where structured classification events become actual order calls.
Every action passes through:

  1. Idempotency check (already handled in receiver before reaching us)
  2. Market sanity bands (codex's mandatory bug catcher)
  3. Risk-budget sizing
  4. Freqtrade REST call (forceenter / forceexit / custom_stoploss)
  5. Result recorded back to position graph

If sanity check fails → reject and alert. No "policy" overrides on the
signal itself.
"""
import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


# Hard skip-list — coins NOT on Binance USDT-M Futures (per VPS verification
# 2026-05-19). Only one entry; keep updated if Binance adds.
SKIP_COINS = {"MNT"}

# Market sanity band: reject if signal entry deviates from current mark
# price by more than this fraction. Catches classifier bugs like the
# ETH SHORT entry=77100 (BTC price) we saw in the benchmark.
MAX_PRICE_DEVIATION = 0.20  # 20% — generous for volatile alts


@dataclass
class SizingConfig:
    risk_usd: float = 2.0          # $2 risk per trade (5x scale-down of Eduardo's $10)
    margin_usd: float = 10.0        # $10 notional margin per trade
    max_leverage: float = 30.0      # cap leverage if SL is super tight


@dataclass
class ExecutorResult:
    ok: bool
    detail: str
    freqtrade_trade_id: Optional[int] = None
    sized_stake: Optional[float] = None
    leverage: Optional[float] = None


# ── Sizing ────────────────────────────────────────────────────────────────


def size_position(entry: float, sl: float, cfg: SizingConfig) -> tuple[float, float]:
    """Return (stake_usdt, leverage) using risk-budget model.

    stake = risk / sl_distance_pct, capped by max_leverage.
    """
    if entry is None or sl is None or entry <= 0 or sl <= 0:
        raise ValueError("invalid entry/sl for sizing")
    sl_distance_pct = abs(entry - sl) / entry
    if sl_distance_pct <= 0:
        raise ValueError("entry == sl, can't size")
    stake = cfg.risk_usd / sl_distance_pct
    leverage = stake / cfg.margin_usd
    if leverage > cfg.max_leverage:
        # Cap leverage by reducing stake
        stake = cfg.max_leverage * cfg.margin_usd
        leverage = cfg.max_leverage
    return round(stake, 2), round(leverage, 2)


# ── Market sanity bands ──────────────────────────────────────────────────


async def get_mark_price(session: aiohttp.ClientSession, symbol: str) -> Optional[float]:
    """Fetch current mark price from Binance Futures public API."""
    url = "https://fapi.binance.com/fapi/v1/premiumIndex"
    params = {"symbol": f"{symbol.upper()}USDT"}
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=3)) as r:
            if r.status != 200:
                logger.warning("mark price fetch failed for %s: HTTP %d", symbol, r.status)
                return None
            data = await r.json()
            return float(data["markPrice"])
    except Exception as e:
        logger.warning("mark price fetch error for %s: %s", symbol, e)
        return None


def sanity_check_entry(symbol: str, entry: float, mark: Optional[float]) -> tuple[bool, str]:
    """Reject entry if it's wildly off market. Catches classifier bugs."""
    if symbol in SKIP_COINS:
        return False, f"skip-list (no Binance Futures): {symbol}"
    if mark is None:
        # If we can't verify, fail closed.
        return False, f"could not fetch mark price for {symbol}"
    if mark <= 0:
        return False, f"invalid mark price: {mark}"
    deviation = abs(entry - mark) / mark
    if deviation > MAX_PRICE_DEVIATION:
        return False, (
            f"entry {entry} vs mark {mark} = {deviation*100:.1f}% deviation "
            f"(threshold {MAX_PRICE_DEVIATION*100:.0f}%) — likely classifier bug"
        )
    return True, f"ok (deviation {deviation*100:.1f}%)"


# ── Freqtrade REST client ────────────────────────────────────────────────


@dataclass
class FreqtradeConfig:
    base_url: str
    username: str
    password: str

    @classmethod
    def from_env(cls) -> "FreqtradeConfig":
        return cls(
            base_url=os.getenv("INSIDERS_FT_BASE_URL", "http://insiders-bot:8080"),
            username=os.getenv("INSIDERS_FT_USERNAME", ""),
            password=os.getenv("INSIDERS_FT_PASSWORD", ""),
        )


class FreqtradeClient:
    def __init__(self, cfg: FreqtradeConfig):
        self.cfg = cfg
        self._auth = aiohttp.BasicAuth(cfg.username, cfg.password) if cfg.username else None

    async def ping(self) -> bool:
        async with aiohttp.ClientSession(auth=self._auth) as s:
            async with s.get(f"{self.cfg.base_url}/api/v1/ping",
                             timeout=aiohttp.ClientTimeout(total=3)) as r:
                return r.status == 200

    async def force_enter(self, pair: str, side: str, price: Optional[float],
                          stake_amount: float, leverage: float) -> dict:
        """Place a forced entry. Side = 'long' or 'short' for futures."""
        body = {
            "pair": pair,
            "side": side,
            "stake_amount": stake_amount,
            "leverage": leverage,
        }
        if price is not None:
            body["price"] = price
            body["entry_tag"] = "insiders-limit"
            body["order_type"] = "limit"
        else:
            body["entry_tag"] = "insiders-market"
            body["order_type"] = "market"
        async with aiohttp.ClientSession(auth=self._auth) as s:
            async with s.post(f"{self.cfg.base_url}/api/v1/forceenter", json=body,
                              timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                data["_http_status"] = r.status
                return data

    async def force_exit(self, trade_id: int, amount_pct: Optional[float] = None) -> dict:
        """Force exit a trade. amount_pct = None means full exit. amount_pct in 0-100."""
        body = {"tradeid": str(trade_id)}
        if amount_pct is not None and amount_pct < 100:
            body["amount"] = amount_pct / 100.0
        async with aiohttp.ClientSession(auth=self._auth) as s:
            async with s.post(f"{self.cfg.base_url}/api/v1/forceexit", json=body,
                              timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                data["_http_status"] = r.status
                return data

    async def get_open_trades(self) -> list[dict]:
        async with aiohttp.ClientSession(auth=self._auth) as s:
            async with s.get(f"{self.cfg.base_url}/api/v1/status",
                             timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status != 200:
                    logger.warning("freqtrade /status returned %d", r.status)
                    return []
                return await r.json()


# ── Execution orchestration ──────────────────────────────────────────────


def pair_for_symbol(symbol: str) -> str:
    """Convert classifier symbol → Freqtrade pair string (USDT-M perp)."""
    return f"{symbol.upper()}/USDT:USDT"
