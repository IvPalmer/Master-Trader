"""Read-only widgets for the operator's widget platform (contract v1).

One widget, `bots`: the rolling 24 h P&L of the live bots (Master Trader keeps a
rolling 24-hour figure, delta_24h.pnl_usd, not a calendar day), one row per bot
with a status tone, the live bots' summed realized equity (only when every live
bot has a series, so never a partial total), and the fleet status
as an alert when it is yellow or red, and a `metrics` view that repeats the dashboard
header (account equity, realized, unrealized and 24 h P&L of the live bots; the math is
`get hero()` in static/dashboard.js). Paper and live are never mixed in a number.

Its own bearer (WIDGETS_TOKEN) guards /widgets* only; every other route and the
Cloudflare Access edge are unchanged. Unset token => 503, never open.
"""
import hmac
import os
from datetime import datetime, timezone
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse

MAX_TEXT = 500
MAX_POINTS = 120
CATALOG = {
    "contract": 1,
    "app": "trader",
    "widgets": [{
        "id": "bots", "title": "Bots", "views": ["stat", "list", "spark", "alert", "metrics"],
        "default_view": "stat", "refresh_s": 60, "actions": [],
    }],
}
STATUS_TONE = {"green": "good", "yellow": "warn", "red": "bad"}
TONE_RANK = {"good": 0, "neutral": 1, "warn": 2, "bad": 3}


def _clip(text) -> str:
    return str(text)[:MAX_TEXT]


def usd(value: float) -> str:
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _pnl(bot: dict) -> float:
    return float((bot.get("delta_24h") or {}).get("pnl_usd") or 0.0)


def _bot_tone(bot: dict) -> str:
    if not bot.get("reachable"):
        return "bad"
    integrity = (bot.get("position_integrity") or {}).get("status")
    execution = (bot.get("execution_health") or {}).get("status")
    if integrity == "critical" or execution == "critical":
        return "bad"
    if execution == "warning":
        return "warn"
    return "neutral"


def _row(bot: dict) -> dict:
    mode = "dry-run" if bot.get("dry_run", True) else "live"
    prefix = "" if bot.get("reachable") else "unreachable · "
    opened = len(bot.get("open_trades") or [])
    item = {
        "key": _clip(f"bot:{bot['key']}"),
        "title": _clip(bot.get("label") or bot.get("name") or bot["key"]),
        "subtitle": _clip(f"{prefix}{mode} · 24 h {usd(_pnl(bot))} · {opened} open"),
    }
    total = (bot.get("wallet") or {}).get("total")
    if total is not None:
        item["detail"] = _clip(f"wallet ${float(total):,.2f}")
    tone = _bot_tone(bot)
    if tone != "neutral":
        item["tone"] = tone
    return item


def fleet_equity(series_list: list[list], max_points: int = MAX_POINTS) -> list[float]:
    """Sum step series [[ts_ms, usd]] at every timestamp once every series has
    started (realized equity only moves when a trade closes)."""
    series = [sorted((int(t), float(v)) for t, v in s) for s in series_list if s]
    if not series:
        return []
    stamps = sorted({t for s in series for t, _ in s})
    idx, last, out = [0] * len(series), [None] * len(series), []
    for ts in stamps:
        for i, s in enumerate(series):
            while idx[i] < len(s) and s[idx[i]][0] <= ts:
                last[i] = s[idx[i]][1]
                idx[i] += 1
        if all(v is not None for v in last):
            out.append(round(sum(last), 2))
    return out[-max_points:]


def build_bots(state: dict) -> dict:
    """The `bots` payload from an /api/state subset. Pure. Needs last_poll;
    account_health is optional (only the equity row reads it)."""
    bots = list((state.get("bots") or {}).values())
    live = [b for b in bots if not b.get("dry_run", True)]
    pnl = sum(_pnl(b) for b in live)
    trades = sum(int((b.get("delta_24h") or {}).get("new_trades") or 0) for b in live)
    stat_tone = "good" if pnl > 0 else "bad" if pnl < 0 else "neutral"
    data = {
        "id": "bots", "title": "Bots",
        "as_of": datetime.fromtimestamp(float(state["last_poll"]), timezone.utc).isoformat(timespec="seconds"),
        "stat": {"value": usd(pnl), "label": "24 h P&L · live",
                 "delta": f"{trades} trade{'' if trades == 1 else 's'} closed", "tone": stat_tone},
        "metrics": build_metrics(state),
    }
    ordered = sorted(bots, key=lambda b: (bool(b.get("dry_run", True)), str(b.get("label") or b.get("key"))))
    if ordered:
        data["list"] = {"groups": [{"title": "Bots", "items": [_row(b) for b in ordered[:100]]}]}
    # Only when every live bot has a series: a missing one would make the total partial.
    series = [b.get("equity_realized") or [] for b in live]
    points = fleet_equity(series) if series and all(series) else []
    if len(points) >= 2:
        data["spark"] = {"label": "Live equity (realized)", "points": points, "unit": "USD"}
    status = state.get("status") or {}
    tone = stat_tone
    if status.get("level") in ("yellow", "red"):
        alert_tone = STATUS_TONE[status["level"]]
        data["alert"] = {"text": _clip(status.get("summary") or status["level"]), "tone": alert_tone}
        tone = max(stat_tone, alert_tone, key=TONE_RANK.__getitem__)
    data["tone"] = tone
    return data


def _num(value) -> float:
    """JS `value ?? 0`: only None falls back, so a real 0 is kept."""
    return 0.0 if value is None else float(value)


def _signed(value: float) -> tuple[str, str]:
    """Signed dollars and the tone for the sign. Rounds to cents first, so float drift
    in a sum never shows as a green or red $0.00."""
    value = round(value, 2)
    return usd(value), "good" if value > 0 else "bad" if value < 0 else "neutral"


def _is_pending_entry(trade: dict) -> bool:
    """An unfilled entry order is not a position (dashboard.js isPendingEntry)."""
    if (trade.get("entry") or {}).get("state") != "pending":
        return False
    try:
        return not float(trade.get("amount")) > 0   # a missing amount counts as unfilled
    except (TypeError, ValueError):
        return True


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def build_metrics(state: dict) -> dict:
    """The `metrics` view: the dashboard header, `get hero()` in static/dashboard.js,
    for the live bots only (`dry_run === false`). Pure."""
    fleet = {name: b for name, b in (state.get("bots") or {}).items() if b.get("dry_run") is False}
    live = list(fleet.values())
    # Bots sharing one exchange account count its capital once: the largest wallet.
    accounts: dict = {}
    for name, b in fleet.items():
        wallet = b.get("wallet") or {}
        owned = wallet.get("bot_owned")
        if owned is None:
            owned = wallet.get("starting_capital")
        group = b.get("account_group") or b.get("key") or name
        accounts[group] = max(accounts.get(group, 0.0), _num(owned))
    observed = state.get("account_health")
    if observed is None:
        equity = sum(accounts.values())
    else:
        equity = observed.get("equity") if observed.get("complete") else None
    pnls = [b.get("pnl") or {} for b in live]
    realized = sum(_num(p.get("closed")) for p in pnls)
    unrealized = sum(_num(p["unrealized"]) if p.get("unrealized") is not None
                     else _num(p.get("all_coin")) - _num(p.get("closed")) for p in pnls)
    closed = sum(int(_num((b.get("stats") or {}).get("closed_trade_count"))) for b in live)
    trades = [t for b in live for t in b.get("open_trades") or []]
    positions = sum(1 for t in trades if not _is_pending_entry(t))
    day = sum(_pnl(b) for b in live)
    rows = [{"label": "Account equity",
             "value": "—" if equity is None
                      else ("−" if float(equity) < 0 else "") + f"${abs(float(equity)):,.2f}",
             "detail": "shared accounts counted once" if equity is not None else "valuation incomplete",
             "tone": "neutral" if equity is not None else "warn"}]
    for label, value, detail in (("Realized P&L", realized, f"{_count(closed, 'closed trade')} · live epochs"),
                                 ("Unrealized P&L", unrealized, _count(positions, "open position")),
                                 ("24 h P&L", day, "live bots · rolling 24 h")):
        text, tone = _signed(value)
        rows.append({"label": label, "value": text, "detail": detail, "tone": tone})
    return {"rows": rows}


def _authorized(request: Request) -> JSONResponse | None:
    token = os.environ.get("WIDGETS_TOKEN", "")
    if not 32 <= len(token) <= 128:
        return JSONResponse({"error": "widgets disabled: token not configured"}, status_code=503)
    presented = request.headers.get("authorization", "")
    if not hmac.compare_digest(presented.encode(), f"Bearer {token}".encode()):
        return JSONResponse({"error": "missing or bad token"}, status_code=401)
    return None


def install(app, get_state: Callable[[], dict]) -> None:
    @app.get("/widgets")
    async def widgets_catalog(request: Request):
        return _authorized(request) or JSONResponse(CATALOG)

    @app.get("/widgets/{widget_id}")
    async def widgets_data(widget_id: str, request: Request):
        if denied := _authorized(request):
            return denied
        if widget_id != "bots":
            return JSONResponse({"error": "unknown widget"}, status_code=404)
        state = get_state()
        if not state.get("last_poll"):
            return JSONResponse({"error": "no poll yet"}, status_code=503)
        return JSONResponse(build_bots(state))

    @app.post("/widgets/{widget_id}/actions/{action_id}")
    async def widgets_action(widget_id: str, action_id: str, request: Request):
        if denied := _authorized(request):
            return denied
        return JSONResponse({"ok": False, "message": "trader widgets have no actions", "refresh": False},
                            status_code=404)
