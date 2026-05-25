"""
papertrading.weex
~~~~~~~~~~~~~~~~~
WEEX Futures API client (V2 market data + V3 demo trading).

Market data endpoints (no auth required):
  GET /capi/v2/market/contracts      — list of futures contracts
  GET /capi/v2/market/historyCandles — OHLCV historical candlestick data

Price lookups prefer Binance Futures (fapi.binance.com) and fall back to
WEEX historyCandles for symbols not listed on Binance (e.g. XTIU, XAG).

Demo (sim) endpoints (API key required):
  GET  /capi/v3/sim/balance        — account balance
  POST /capi/v3/sim/order          — place a sim order
  GET  /capi/v3/sim/order/history  — order history

Symbols:
  Market data:  cmt_{coin}usdt  (e.g. cmt_btcusdt, cmt_pumpusdt)
  Demo trading: {COIN}SUSDT     (e.g. BTCSUSDT, PUMPSUSDT)

Auth env vars (only needed for demo trading):
  WEEX_API_KEY        — ACCESS-KEY header
  WEEX_SECRET_KEY     — used for HMAC SHA256 signature
  WEEX_PASSPHRASE     — ACCESS-PASSPHRASE header
"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.request
import urllib.parse
from typing import Optional

BASE_URL = "https://api-contract.weex.com"
BINANCE_FAPI = "https://fapi.binance.com"

# Module-level caches
_BINANCE_SYMBOLS = None
_CANDLE_CACHE = {}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def _market_get(path: str, params: dict) -> list:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE_URL}{path}?{query}" if params else f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    if isinstance(data, dict) and data.get("code") and data["code"] != "0":
        raise RuntimeError(f"WEEX API error {data.get('code')}: {data.get('msg')}")
    return data


def _json_get(url: str, params: dict) -> object:
    """Generic JSON GET for external APIs (e.g. Binance Futures)."""
    if params:
        query = urllib.parse.urlencode(params)
        url = f"{url}?{query}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Authenticated helpers (demo trading)
# ---------------------------------------------------------------------------

def _sign(secret: str, timestamp: str, method: str, path: str,
          query_string: str = "", body: str = "") -> str:
    """Build the HMAC SHA256 + Base64 signature required by WEEX."""
    if query_string:
        message = f"{timestamp}{method.upper()}{path}?{query_string}{body}"
    else:
        message = f"{timestamp}{method.upper()}{path}{body}"
    raw = hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(raw).decode()


def _auth_request(method: str, path: str, params: Optional[dict] = None,
                  body: Optional[dict] = None) -> object:
    api_key    = os.environ.get("WEEX_API_KEY", "")
    secret_key = os.environ.get("WEEX_SECRET_KEY", "")
    passphrase = os.environ.get("WEEX_PASSPHRASE", "")
    if not api_key:
        raise RuntimeError("WEEX_API_KEY not set — demo trading requires API keys")

    timestamp    = str(int(time.time() * 1000))
    query_string = "&".join(f"{k}={v}" for k, v in (params or {}).items())
    body_str     = json.dumps(body) if body else ""
    signature    = _sign(secret_key, timestamp, method, path, query_string, body_str)

    url = f"{BASE_URL}{path}"
    if query_string:
        url += f"?{query_string}"

    headers = {
        "Content-Type":      "application/json",
        "ACCESS-KEY":        api_key,
        "ACCESS-SIGN":       signature,
        "ACCESS-PASSPHRASE": passphrase,
        "ACCESS-TIMESTAMP":  timestamp,
    }
    data_bytes = body_str.encode() if body_str else None
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

def get_futures_coins() -> set:
    """
    Return the set of base coin names for all active futures contracts.
    e.g. {'BTC', 'ETH', 'PUMP', ...}
    """
    contracts = _market_get("/capi/v2/market/contracts", {})
    return {c["underlying_index"] for c in contracts if "underlying_index" in c}


# ---------------------------------------------------------------------------
# Binance Futures (primary price source)
# ---------------------------------------------------------------------------

def _binance_symbols() -> set:
    """Return the set of active PERPETUAL USDT symbols on Binance Futures."""
    global _BINANCE_SYMBOLS
    if _BINANCE_SYMBOLS is None:
        data = _json_get(f"{BINANCE_FAPI}/fapi/v1/exchangeInfo", {})
        _BINANCE_SYMBOLS = {
            s["symbol"] for s in data["symbols"]
            if s.get("contractType") == "PERPETUAL"
            and s.get("quoteAsset") == "USDT"
            and s.get("status") == "TRADING"
        }
    return _BINANCE_SYMBOLS


def _binance_klines(symbol: str, start_ms: int, end_ms: int, limit: int = 1) -> list:
    """Fetch 1-min klines from Binance Futures. Returns [] if symbol not listed."""
    pair = symbol.upper()
    if not pair.endswith("USDT"):
        pair = f"{pair}USDT"
    if pair not in _binance_symbols():
        return []
    rows = _json_get(f"{BINANCE_FAPI}/fapi/v1/klines", {
        "symbol": pair, "interval": "1m",
        "startTime": str(start_ms), "endTime": str(end_ms),
        "limit": str(limit),
    })
    return [{"time_ms": int(r[0]), "open": float(r[1]), "high": float(r[2]),
             "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])}
            for r in rows]


# ---------------------------------------------------------------------------
# WEEX historical candles (fallback for symbols not on Binance)
# ---------------------------------------------------------------------------

def get_weex_history_klines(symbol: str, start_ms: int, end_ms: int,
                             limit: int = 100) -> list:
    """
    Fetch historical OHLCV candles from WEEX using /historyCandles endpoint.
    This endpoint accepts startTime/endTime and returns historical data,
    unlike /candles which only returns the latest candles.
    """
    params = {
        "symbol": _to_market_symbol(symbol),
        "granularity": _interval_to_granularity(1),
        "limit": str(min(limit, 100)),
        "priceType": "LAST",
    }
    if start_ms is not None:
        params["startTime"] = str(start_ms)
    if end_ms is not None:
        params["endTime"] = str(end_ms)
    rows = _market_get("/capi/v2/market/historyCandles", params)
    candles = [{
        "time_ms": int(r[0]), "open": float(r[1]), "high": float(r[2]),
        "low": float(r[3]), "close": float(r[4]), "volume": float(r[5]),
    } for r in rows]
    candles.sort(key=lambda c: c["time_ms"])
    return candles


def get_klines(symbol: str, interval: int, start_ms: int,
               end_ms: Optional[int] = None, limit: int = 1000) -> list:
    """
    Fetch OHLCV candles. Tries Binance Futures first, falls back to WEEX
    historyCandles for symbols not listed on Binance (e.g. XTIU, XAG).

    Args:
        symbol:   e.g. "BTCUSDT" or "BTC"
        interval: candle size in minutes (1, 3, 5, ...)
        start_ms: start time in milliseconds (UTC)
        end_ms:   end time in milliseconds (UTC)
        limit:    max candles to return

    Returns list of dicts oldest-first:
        [{"time_ms": int, "open": float, "high": float,
          "low": float, "close": float, "volume": float}, ...]
    """
    _end_ms = end_ms if end_ms is not None else int(time.time() * 1000)
    # Try Binance first (reliable historical data)
    candles = _binance_klines(symbol, start_ms, _end_ms, limit)
    if candles:
        return candles
    # Fall back to WEEX historyCandles
    return get_weex_history_klines(symbol, start_ms, _end_ms, limit)


def get_price_at(symbol: str, timestamp_ms: int,
                 max_drift_minutes: int = 2) -> Optional[float]:
    """
    Return the close price of the 1-minute candle nearest to timestamp_ms.
    Tries Binance Futures first, falls back to WEEX historyCandles.
    Raises RuntimeError if the nearest candle is more than max_drift_minutes away.
    Returns None if no candle is found at all.
    """
    minute_ms = timestamp_ms - (timestamp_ms % 60_000)
    key = (symbol.upper(), minute_ms)
    if key in _CANDLE_CACHE:
        return _CANDLE_CACHE[key]["close"]

    # Try Binance first
    candles = _binance_klines(symbol, minute_ms, minute_ms + 60_000, 1)
    if not candles:
        # Fall back to WEEX historyCandles
        try:
            candles = get_weex_history_klines(symbol, minute_ms, minute_ms + 60_000, 1)
        except Exception:
            candles = []

    if not candles:
        return None

    c = min(candles, key=lambda x: abs(x["time_ms"] - minute_ms))
    if abs(c["time_ms"] - minute_ms) > max_drift_minutes * 60_000:
        raise RuntimeError(
            f"stale candle for {symbol}: requested={minute_ms} got={c['time_ms']}"
        )
    _CANDLE_CACHE[key] = c
    return c["close"]


def resolve_exits(trades: list, position_size: float = 100.0) -> None:
    """
    For each trade with an entry price, walk 1-min klines to find the first
    SL or TP hit. Sets trade.exit_price, trade.exit_reason, trade.pnl in-place.

    For trades still open (neither hit), uses the last available candle price.

    Args:
        trades:        list of Trade objects (must have entry, symbol, date set)
        position_size: USD size of each trade (default $100)
    """
    from datetime import datetime, timezone

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    for trade in trades:
        if trade.entry is None:
            continue

        try:
            dt = datetime.fromisoformat(trade.date.replace("Z", "+00:00"))
            start_ms = int(dt.timestamp() * 1000)
        except Exception:
            continue

        # If the channel posted an explicit close event, stop kline walk at that time
        close_events = [e for e in getattr(trade, "events", []) if e.kind == "close_full"]
        if close_events:
            try:
                close_dt = datetime.fromisoformat(close_events[0].date.replace("Z", "+00:00"))
                end_ms = int(close_dt.timestamp() * 1000)
            except Exception:
                end_ms = now_ms
        else:
            end_ms = now_ms

        try:
            candles = get_klines(f"{trade.symbol}USDT", 1, start_ms, end_ms)
        except Exception:
            continue
        if not candles:
            continue

        exit_price = None
        exit_reason = "open"

        for candle in candles:
            high = candle["high"]
            low  = candle["low"]

            if trade.direction == "LONG":
                if trade.tp and high >= trade.tp:
                    exit_price  = trade.tp
                    exit_reason = "tp"
                    break
                if trade.sl and low <= trade.sl:
                    exit_price  = trade.sl
                    exit_reason = "sl"
                    break
            else:  # SHORT
                if trade.tp and low <= trade.tp:
                    exit_price  = trade.tp
                    exit_reason = "tp"
                    break
                if trade.sl and high >= trade.sl:
                    exit_price  = trade.sl
                    exit_reason = "sl"
                    break

        if exit_price is None:
            # Use last candle close; if channel closed it, mark as channel_close
            exit_price = candles[-1]["close"]
            if close_events:
                exit_reason = "manual"

        trade.exit_price  = exit_price
        trade.exit_reason = exit_reason

        if trade.direction == "LONG":
            trade.pnl = round(position_size * (exit_price - trade.entry) / trade.entry, 2)
        else:
            trade.pnl = round(position_size * (trade.entry - exit_price) / trade.entry, 2)


# ---------------------------------------------------------------------------
# Demo trading (requires API keys)
# ---------------------------------------------------------------------------

def get_balance() -> list:
    """Return the demo account balance. Returns list of asset dicts."""
    return _auth_request("GET", "/capi/v3/sim/balance")


def place_order(symbol: str, direction: str, entry: Optional[float] = None,
                quantity: float = 0.01, tp: Optional[float] = None,
                sl: Optional[float] = None, client_order_id: str = "") -> dict:
    """
    Place a demo order on WEEX.

    Args:
        symbol:    base coin name, e.g. "BTC" → order symbol "BTCSUSDT"
        direction: "LONG" or "SHORT"
        entry:     limit price (None = MARKET order)
        quantity:  contract quantity
        tp:        take-profit trigger price
        sl:        stop-loss trigger price
        client_order_id: optional custom order ID

    Returns the API response dict.
    """
    side          = "BUY" if direction == "LONG" else "SELL"
    position_side = direction  # LONG / SHORT
    order_type    = "LIMIT" if entry else "MARKET"

    body: dict = {
        "symbol":        f"{symbol.upper()}SUSDT",
        "side":          side,
        "positionSide":  position_side,
        "type":          order_type,
        "quantity":      str(quantity),
    }
    if entry:
        body["price"]       = str(entry)
        body["timeInForce"] = "GTC"
    if tp:
        body["tpTriggerPrice"]  = str(tp)
        body["TpWorkingType"]   = "MARK_PRICE"
    if sl:
        body["slTriggerPrice"]  = str(sl)
        body["SlWorkingType"]   = "MARK_PRICE"
    if client_order_id:
        body["newClientOrderId"] = client_order_id

    return _auth_request("POST", "/capi/v3/sim/order", body=body)


def get_order_history(symbol: Optional[str] = None) -> list:
    """Return demo order history."""
    params = {}
    if symbol:
        params["symbol"] = f"{symbol.upper()}SUSDT"
    return _auth_request("GET", "/capi/v3/sim/order/history", params=params)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_market_symbol(symbol: str) -> str:
    """Convert 'BTCUSDT' or 'BTC' to WEEX market format 'cmt_btcusdt'."""
    base = symbol.upper()
    if base.endswith("USDT"):
        base = base[:-4]
    return f"cmt_{base.lower()}usdt"


def _interval_to_granularity(minutes: int) -> str:
    """Convert interval in minutes to WEEX granularity string."""
    mapping = {
        1: "1m", 3: "3m", 5: "5m", 15: "15m", 30: "30m",
        60: "1h", 120: "2h", 240: "4h", 360: "6h", 720: "12h",
        1440: "1d",
    }
    return mapping.get(minutes, f"{minutes}m")
