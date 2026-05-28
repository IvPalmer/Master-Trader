"""WEEX USDT-M perpetual futures REST client.

Direct REST against api-contract.weex.com (no ccxt — not supported, see
ccxt issue #27680). Auth is OKX-style: key + secret + passphrase.

Sign string format:
    msg = ts + METHOD + path + ?query_string + body

Where:
    ts        : current Unix time in milliseconds, as string
    METHOD    : uppercase (GET, POST, DELETE)
    path      : /capi/v3/...   (no host, no query)
    query     : compact urlencoded form, omitted for empty
    body      : compact JSON for POST, empty string for GET/DELETE

Signature = base64(HMAC-SHA256(secret, msg))
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode

import requests


WEEX_BASE = "https://api-contract.weex.com"


@dataclass
class WeexCredentials:
    api_key: str
    api_secret: str
    passphrase: str


class WeexError(Exception):
    def __init__(self, status: int, payload: Any, msg: str = ""):
        super().__init__(f"{msg or 'WEEX error'} status={status} payload={payload!r}")
        self.status = status
        self.payload = payload


class WeexClient:
    def __init__(
        self,
        credentials: Optional[WeexCredentials] = None,
        base_url: str = WEEX_BASE,
        timeout_s: float = 10.0,
    ):
        self.creds = credentials
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.session = requests.Session()

    # ── Signing ───────────────────────────────────────────────────────────

    def _sign(
        self,
        method: str,
        path: str,
        query: Optional[dict] = None,
        body: Optional[dict] = None,
    ) -> dict:
        if self.creds is None:
            raise RuntimeError("no credentials configured for signed request")
        ts = str(int(time.time() * 1000))
        qs = urlencode(query or {}, doseq=True)
        body_str = "" if not body else json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        msg = f"{ts}{method.upper()}{path}"
        if qs:
            msg += f"?{qs}"
        msg += body_str
        sig = base64.b64encode(
            hmac.new(self.creds.api_secret.encode(), msg.encode(), hashlib.sha256).digest()
        ).decode()
        return {
            "ACCESS-KEY": self.creds.api_key,
            "ACCESS-SIGN": sig,
            "ACCESS-TIMESTAMP": ts,
            "ACCESS-PASSPHRASE": self.creds.passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }

    # ── HTTP ──────────────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        query: Optional[dict] = None,
        body: Optional[dict] = None,
        auth: bool = False,
    ) -> Any:
        url = self.base_url + path
        headers = self._sign(method, path, query, body) if auth else {"Content-Type": "application/json"}
        body_str = None if not body else json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        r = self.session.request(
            method=method,
            url=url,
            params=query or None,
            data=body_str,
            headers=headers,
            timeout=self.timeout_s,
        )
        try:
            payload = r.json()
        except ValueError:
            payload = r.text
        if r.status_code >= 400:
            raise WeexError(r.status_code, payload)
        if isinstance(payload, dict) and payload.get("success") is False:
            raise WeexError(r.status_code, payload, "logical failure")
        return payload

    # ── Public market data ────────────────────────────────────────────────

    def server_time(self) -> dict:
        return self._request("GET", "/capi/v3/market/time")

    def exchange_info(self) -> dict:
        return self._request("GET", "/capi/v3/market/exchangeInfo")

    def mark_price(self, symbol: str) -> dict:
        return self._request("GET", "/capi/v3/market/premiumIndex", query={"symbol": symbol})

    def klines(self, symbol: str, interval: str = "1h", limit: int = 100) -> list:
        return self._request(
            "GET",
            "/capi/v3/market/klines",
            query={"symbol": symbol, "interval": interval, "limit": limit},
        )

    def ticker_24hr(self, symbol: Optional[str] = None) -> Any:
        q = {"symbol": symbol} if symbol else {}
        return self._request("GET", "/capi/v3/market/ticker/24hr", query=q)

    def depth(self, symbol: str) -> dict:
        # NOTE: WEEX rejects any `limit` param on depth with error -1142. Omit.
        return self._request("GET", "/capi/v3/market/depth", query={"symbol": symbol})

    def funding_rate(self, symbol: str) -> dict:
        return self._request("GET", "/capi/v3/market/fundingRate", query={"symbol": symbol})

    # ── Account (signed) ──────────────────────────────────────────────────

    def balance(self) -> dict:
        return self._request("GET", "/capi/v3/account/balance", auth=True)

    def account_config(self) -> dict:
        return self._request("GET", "/capi/v3/account/accountConfig", auth=True)

    def positions(self) -> list:
        return self._request("GET", "/capi/v3/account/position/allPosition", auth=True)

    def position(self, symbol: str) -> dict:
        return self._request(
            "GET", "/capi/v3/account/position/singlePosition", query={"symbol": symbol}, auth=True
        )

    def set_leverage(
        self,
        symbol: str,
        margin_type: str,
        cross_leverage: Optional[int] = None,
        isolated_long_leverage: Optional[int] = None,
        isolated_short_leverage: Optional[int] = None,
    ) -> dict:
        body: dict[str, Any] = {"symbol": symbol, "marginType": margin_type}
        if cross_leverage is not None:
            body["crossLeverage"] = cross_leverage
        if isolated_long_leverage is not None:
            body["isolatedLongLeverage"] = isolated_long_leverage
        if isolated_short_leverage is not None:
            body["isolatedShortLeverage"] = isolated_short_leverage
        return self._request("POST", "/capi/v3/account/leverage", body=body, auth=True)

    def set_margin_type(self, symbol: str, margin_type: str, separated_type: str) -> dict:
        body = {"symbol": symbol, "marginType": margin_type, "separatedType": separated_type}
        return self._request("POST", "/capi/v3/account/marginType", body=body, auth=True)

    # ── Orders (signed) ───────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,
        position_side: str,
        order_type: str,
        quantity: str,
        client_order_id: str,
        price: Optional[str] = None,
        time_in_force: Optional[str] = None,
        tp_trigger_price: Optional[str] = None,
        sl_trigger_price: Optional[str] = None,
        tp_working_type: str = "MARK_PRICE",
        sl_working_type: str = "MARK_PRICE",
    ) -> dict:
        body: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "positionSide": position_side,
            "type": order_type,
            "quantity": quantity,
            "newClientOrderId": client_order_id,
        }
        if price is not None:
            body["price"] = price
        if time_in_force is not None:
            body["timeInForce"] = time_in_force
        if tp_trigger_price is not None:
            body["tpTriggerPrice"] = tp_trigger_price
            body["TpWorkingType"] = tp_working_type
        if sl_trigger_price is not None:
            body["slTriggerPrice"] = sl_trigger_price
            body["SlWorkingType"] = sl_working_type
        return self._request("POST", "/capi/v3/order", body=body, auth=True)

    def place_tp_sl(
        self,
        symbol: str,
        position_side: str,
        plan_type: str,
        trigger_price: str,
        quantity: str,
        client_algo_id: str,
        position_id: Optional[str] = None,
        execute_price: Optional[str] = None,
        trigger_price_type: str = "MARK_PRICE",
    ) -> dict:
        body: dict[str, Any] = {
            "symbol": symbol,
            "positionSide": position_side,
            "planType": plan_type,
            "triggerPrice": trigger_price,
            "quantity": quantity,
            "clientAlgoId": client_algo_id,
            "triggerPriceType": trigger_price_type,
        }
        # Hedge (SEPARATED) mode requires positionId, returned as `id` from positions()
        if position_id is not None:
            body["positionId"] = position_id
        if execute_price is not None:
            body["executePrice"] = execute_price
        return self._request("POST", "/capi/v3/placeTpSlOrder", body=body, auth=True)

    def close_positions(self, symbol: Optional[str] = None) -> dict:
        body = {"symbol": symbol} if symbol else {}
        return self._request("POST", "/capi/v3/closePositions", body=body, auth=True)

    def cancel_order(self, symbol: str, order_id: Optional[str] = None,
                     orig_client_order_id: Optional[str] = None) -> dict:
        body: dict[str, Any] = {"symbol": symbol}
        if order_id is not None:
            body["orderId"] = order_id
        if orig_client_order_id is not None:
            body["origClientOrderId"] = orig_client_order_id
        return self._request("DELETE", "/capi/v3/order", body=body, auth=True)

    def open_orders(self, symbol: Optional[str] = None) -> Any:
        q = {"symbol": symbol} if symbol else {}
        return self._request("GET", "/capi/v3/openOrders", query=q, auth=True)
