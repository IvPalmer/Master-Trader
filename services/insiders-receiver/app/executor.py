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

# aiohttp is imported lazily inside the network methods so that pure-helper
# users (sizing, builders, sanity checks) can import this module in
# environments without aiohttp installed (e.g. CI test runs without the
# Docker image layer).

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


async def get_mark_price(session, symbol: str) -> Optional[float]:
    """Fetch current mark price from Binance Futures public API.

    `session` is an aiohttp.ClientSession — typed loosely so this module
    can be imported in test environments without aiohttp installed.
    """
    import aiohttp
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
        # Defer aiohttp import + auth construction so this class can be
        # imported (and statically inspected) without aiohttp installed.
        # _auth is built on first use.
        self._auth = None
        self._auth_built = False

    def _ensure_auth(self):
        if self._auth_built:
            return
        import aiohttp
        if self.cfg.username:
            self._auth = aiohttp.BasicAuth(self.cfg.username, self.cfg.password)
        self._auth_built = True

    async def ping(self) -> bool:
        import aiohttp
        self._ensure_auth()
        async with aiohttp.ClientSession(auth=self._auth) as s:
            async with s.get(f"{self.cfg.base_url}/api/v1/ping",
                             timeout=aiohttp.ClientTimeout(total=3)) as r:
                return r.status == 200

    async def force_enter(self, pair: str, side: str,
                          stake_amount: float, leverage: float) -> dict:
        """Place a forced MARKET entry. Side = 'long' or 'short' for futures.

        Copy-trader fires market — no limit price. Freqtrade payload field
        names are flat (no underscores): `stakeamount`, `ordertype`. The
        working Killers receiver uses this same shape.
        """
        import aiohttp
        self._ensure_auth()
        body = build_forceenter_body(pair, side, stake_amount, leverage)
        async with aiohttp.ClientSession(auth=self._auth) as s:
            async with s.post(f"{self.cfg.base_url}/api/v1/forceenter", json=body,
                              timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                data["_http_status"] = r.status
                return data

    async def force_exit(self, trade_id: int, amount_pct: Optional[float] = None) -> dict:
        """Force exit a trade. amount_pct = None means full exit. amount_pct in 0-100.

        Freqtrade's `amount` field is base-currency amount, NOT a percentage.
        For partial closes we must look up the trade's current amount and
        compute `current_amount * pct / 100`. Without the lookup the value
        passed as percent would be treated as base coins (e.g. amount_pct=50
        → "amount": 0.5 BTC instead of 50% of the position).
        """
        import aiohttp
        self._ensure_auth()
        current_amount: Optional[float] = None
        if amount_pct is not None and amount_pct < 100:
            trade = await self.get_trade(trade_id)
            if trade is None:
                return {"_http_status": 0,
                        "error": f"cannot fetch trade {trade_id} for partial exit"}
            current_amount = trade.get("amount")
            if current_amount is None or current_amount <= 0:
                return {"_http_status": 0,
                        "error": f"trade {trade_id} has no usable amount: {current_amount}"}
        body = build_forceexit_body(trade_id, amount_pct, current_amount)
        async with aiohttp.ClientSession(auth=self._auth) as s:
            async with s.post(f"{self.cfg.base_url}/api/v1/forceexit", json=body,
                              timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                data["_http_status"] = r.status
                return data

    async def get_open_trades(self) -> list[dict]:
        import aiohttp
        self._ensure_auth()
        async with aiohttp.ClientSession(auth=self._auth) as s:
            async with s.get(f"{self.cfg.base_url}/api/v1/status",
                             timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status != 200:
                    logger.warning("freqtrade /status returned %d", r.status)
                    return []
                return await r.json()

    async def get_trade(self, trade_id: int) -> Optional[dict]:
        """Fetch a single trade by ID. Returns None on miss / HTTP error."""
        import aiohttp
        self._ensure_auth()
        async with aiohttp.ClientSession(auth=self._auth) as s:
            try:
                async with s.get(f"{self.cfg.base_url}/api/v1/trade/{trade_id}",
                                 timeout=aiohttp.ClientTimeout(total=5)) as r:
                    if r.status != 200:
                        logger.warning("freqtrade /trade/%d returned %d",
                                       trade_id, r.status)
                        return None
                    return await r.json()
            except Exception as e:
                logger.warning("get_trade(%d) failed: %s", trade_id, e)
                return None


# ── Execution orchestration ──────────────────────────────────────────────


def pair_for_symbol(symbol: str) -> str:
    """Convert classifier symbol → Freqtrade pair string (USDT-M perp)."""
    return f"{symbol.upper()}/USDT:USDT"


# ── Pure body builders (testable without aiohttp) ────────────────────────


def build_forceenter_body(pair: str, side: str, stake_amount: float,
                          leverage: float) -> dict:
    """Construct the JSON body for POST /api/v1/forceenter.

    Pure function — separated from the HTTP call so tests can verify the
    payload shape without mocking aiohttp. Field names match the working
    Killers receiver and Freqtrade's REST contract: flat keys (no
    underscores) for `stakeamount` and `ordertype`.
    """
    return {
        "pair": pair,
        "side": side,
        "stakeamount": round(stake_amount, 2),
        "leverage": leverage,
        "ordertype": "market",
        "entry_tag": "insiders",
    }


def build_forceexit_body(trade_id: int, amount_pct: Optional[float],
                         current_amount: Optional[float]) -> dict:
    """Construct the JSON body for POST /api/v1/forceexit.

    `amount_pct` is the percentage of the position to close (0-100).
    `current_amount` is the trade's current base-currency size, only
    used when `amount_pct < 100`. When omitted or amount_pct is None or
    >= 100, the body omits `amount` and Freqtrade closes the full position.
    """
    body: dict = {"tradeid": str(trade_id), "ordertype": "market"}
    if (amount_pct is not None and amount_pct < 100
            and current_amount is not None and current_amount > 0):
        body["amount"] = round(current_amount * amount_pct / 100.0, 8)
    return body
