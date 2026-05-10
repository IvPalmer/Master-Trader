"""master-trader dashboard backend — FastAPI + bot REST polling.

Two tabs in frontend:
  LIVE      — real-money operational state
  DRY-RUN   — pre-flight graduation tracking

Endpoints:
  /                    static index.html
  /static/...          CSS + JS
  /api/state           full snapshot (cached)
  /api/equity/{key}    live cumulative + scaled backtest expected curve
  /api/candles/{key}   OHLC candles for current open trade pairs
  /healthz             liveness
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import re
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ft-dashboard")

BOTS: list[dict[str, Any]] = [
    {
        "key": "fundingfade",
        "name": "FundingFadeV1",
        "label": "funding-fade",
        "url": "http://ft-funding-fade:8080",
        "baseline": {
            "annual_return_pct": 18.4, "profit_factor": 1.29, "win_rate": 0.657,
            "max_dd_pct": 19.6, "trades_per_year": 131, "worst_trade_pct": -5.0,
            "starting_equity_in_csv": 200.0,
        },
    },
    {
        "key": "keltner",
        "name": "KeltnerBounceV1",
        "label": "keltner-bounce",
        "url": "http://ft-keltner-bounce:8080",
        "baseline": {
            "annual_return_pct": 15.6, "profit_factor": 1.58, "win_rate": 0.64,
            "max_dd_pct": 12.9, "trades_per_year": 46, "worst_trade_pct": -5.0,
            "starting_equity_in_csv": 200.0,
        },
    },
    {
        "key": "cascade",
        "name": "CascadeFaderV1",
        "label": "cascade-fader",
        "url": "http://ft-cascade-fader:8080",
        "baseline": {
            "annual_return_pct": 17.0, "profit_factor": 1.76, "win_rate": 0.84,
            "max_dd_pct": 0.51, "trades_per_year": 46, "worst_trade_pct": -8.0,
            "starting_equity_in_csv": 200.0,
        },
    },
]

API_USER = os.environ.get("FREQTRADE__API_SERVER__USERNAME", "")
API_PASS = os.environ.get("FREQTRADE__API_SERVER__PASSWORD", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "10"))
OVERLAYS_DIR = Path(os.environ.get("OVERLAYS_DIR", "/overlays"))

# Phase 5 / Gate constants
GATE1_TRADES, GATE1_DAYS, GATE1_PAIRS = 30, 14, 5
GATE2_PROFIT_BAND, GATE2_PF_BAND, GATE2_DD_MULT = 0.25, 0.20, 1.5
GATE3_LOSS_MULT, GATE3_CONSEC_LOSSES = 1.5, 5
CONCENTRATION_WARN, CONCENTRATION_DANGER = 0.40, 0.50

_cache: dict[str, Any] = {
    "last_poll_started_at": None,
    "last_poll_finished_at": None,
    "bots": {},
    "errors": {},
}


# ── HTTP ───────────────────────────────────────────────────────────────────
async def _get(client: httpx.AsyncClient, url: str, path: str) -> tuple[Any, str | None]:
    try:
        r = await client.get(f"{url}/api/v1/{path}", auth=(API_USER, API_PASS), timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return r.json(), None
        return None, f"HTTP {r.status_code}"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


# ── Computations ───────────────────────────────────────────────────────────
def _per_pair_pnl(trades: list[dict]) -> list[dict]:
    agg: dict[str, dict] = defaultdict(lambda: {"pair": "", "trades": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        p = t.get("pair", "?")
        agg[p]["pair"] = p
        agg[p]["trades"] += 1
        agg[p]["pnl"] += t.get("profit_abs", 0.0) or 0.0
        if (t.get("profit_abs") or 0.0) > 0:
            agg[p]["wins"] += 1
    return sorted(agg.values(), key=lambda r: r["pnl"], reverse=True)


def _concentration(per_pair: list[dict], total_pnl: float) -> dict:
    """Surface single-pair P&L concentration risk.

    Use the *gross* positive contribution as the denominator for the share
    ratio so it can't exceed 100% when other pairs lose money. Without this,
    a winner-among-losers shows ratios > 1 (e.g. ZEC carries 127%) which
    reads as a math error.

    The ex-top P&L is reported in dollars regardless — that's the honest
    number for "what's left if the top pair vanishes".
    """
    if not per_pair:
        return {"top_pair": None, "top_share": 0.0, "ex_top_pnl": 0.0, "warn": "ok"}
    top = per_pair[0]
    if top["pnl"] <= 0:
        # No profitable pair — concentration metric is meaningless, but show
        # the leader so the card isn't blank when the bot is in drawdown.
        return {
            "top_pair": top["pair"], "top_pair_trades": top["trades"],
            "top_pair_pnl": round(top["pnl"], 2),
            "top_share": 0.0,
            "ex_top_pnl": round(total_pnl - top["pnl"], 2),
            "warn": "ok",
        }
    gross_positive = sum(p["pnl"] for p in per_pair if p["pnl"] > 0)
    top_share = top["pnl"] / gross_positive if gross_positive else 0
    warn = "danger" if top_share >= CONCENTRATION_DANGER else ("warn" if top_share >= CONCENTRATION_WARN else "ok")
    return {
        "top_pair": top["pair"], "top_pair_trades": top["trades"],
        "top_pair_pnl": round(top["pnl"], 2),
        "top_share": round(top_share, 3),
        "ex_top_pnl": round(total_pnl - top["pnl"], 2),
        "warn": warn,
    }


def _expectancy(trades: list[dict]) -> dict:
    closed = [t for t in trades if not t.get("is_open")]
    wins = [t["profit_abs"] for t in closed if (t.get("profit_abs") or 0) > 0]
    losses = [t["profit_abs"] for t in closed if (t.get("profit_abs") or 0) < 0]
    n = len(closed)
    if n == 0:
        return {"sample": 0, "avg_win": 0, "avg_loss": 0, "payoff": None, "expectancy": 0}
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = sum(losses) / len(losses) if losses else 0.0
    payoff = (avg_w / abs(avg_l)) if avg_l else None
    win_rate = len(wins) / n if n else 0
    return {
        "sample": n,
        "avg_win": round(avg_w, 4),
        "avg_loss": round(avg_l, 4),
        "payoff": round(payoff, 2) if payoff else None,
        "expectancy": round((win_rate * avg_w) + ((1 - win_rate) * avg_l), 4),
    }


def _consec_losses(trades: list[dict]) -> int:
    streak = 0
    for t in sorted(trades, key=lambda x: x.get("close_timestamp") or 0, reverse=True):
        if t.get("is_open"):
            continue
        if (t.get("profit_abs") or 0) < 0:
            streak += 1
        else:
            break
    return streak


def _gate1(trades: list[dict], days_running: float) -> dict:
    closed = [t for t in trades if not t.get("is_open")]
    pairs = {t.get("pair") for t in closed if t.get("pair")}
    return {
        "trades": {"actual": len(closed), "target": GATE1_TRADES, "ok": len(closed) >= GATE1_TRADES,
                   "pct": min(100, len(closed) / GATE1_TRADES * 100)},
        "days":   {"actual": round(days_running, 1), "target": GATE1_DAYS, "ok": days_running >= GATE1_DAYS,
                   "pct": min(100, days_running / GATE1_DAYS * 100)},
        "pairs":  {"actual": len(pairs), "target": GATE1_PAIRS, "ok": len(pairs) >= GATE1_PAIRS,
                   "pct": min(100, len(pairs) / GATE1_PAIRS * 100)},
    }


def _gate2(profit: dict, starting_capital: float, days_running: float, baseline: dict) -> dict:
    actual_pct = (profit.get("profit_all_coin", 0.0) / starting_capital * 100) if starting_capital else 0
    expected_pct = baseline["annual_return_pct"] * (days_running / 365) if days_running > 0 else 0
    profit_b = {
        "actual_pct": round(actual_pct, 2), "expected_pct": round(expected_pct, 2),
        "lower": round(expected_pct * (1 - GATE2_PROFIT_BAND), 2),
        "upper": round(expected_pct * (1 + GATE2_PROFIT_BAND), 2),
    }
    profit_b["status"] = ("n/a" if expected_pct == 0
                          else "cold" if actual_pct < profit_b["lower"]
                          else "hot" if actual_pct > profit_b["upper"]
                          else "ok")

    pf_actual = profit.get("profit_factor")
    pf_b = {
        "actual": round(pf_actual, 2) if pf_actual else None,
        "expected": baseline["profit_factor"],
        "lower": round(baseline["profit_factor"] * (1 - GATE2_PF_BAND), 2),
        "upper": round(baseline["profit_factor"] * (1 + GATE2_PF_BAND), 2),
    }
    pf_b["status"] = ("n/a" if pf_actual is None
                      else "cold" if pf_actual < pf_b["lower"]
                      else "hot" if pf_actual > pf_b["upper"]
                      else "ok")

    dd_actual = (profit.get("max_drawdown", 0.0) or 0.0) * 100
    dd_cap = baseline["max_dd_pct"] * GATE2_DD_MULT
    dd_b = {
        "actual_pct": round(dd_actual, 2), "expected_pct": baseline["max_dd_pct"],
        "cap_pct": round(dd_cap, 2),
        "status": "breach" if dd_actual > dd_cap else "hot" if dd_actual > baseline["max_dd_pct"] else "ok",
    }
    return {"profit": profit_b, "pf": pf_b, "dd": dd_b}


def _gate3(trades: list[dict], baseline: dict) -> dict:
    closed = [t for t in trades if not t.get("is_open")]
    worst = min((t.get("profit_pct", 0) or 0) for t in closed) if closed else 0
    worst_cap = baseline["worst_trade_pct"] * GATE3_LOSS_MULT
    force_exits = sum(1 for t in closed if "force" in (t.get("exit_reason") or "").lower())
    consec = _consec_losses(closed)
    return {
        "worst_trade_pct": {"actual": round(worst, 2), "cap": round(worst_cap, 2), "ok": worst >= worst_cap},
        "consec_losses":   {"actual": consec, "cap": GATE3_CONSEC_LOSSES, "ok": consec <= GATE3_CONSEC_LOSSES},
        "force_exits":     {"actual": force_exits, "cap": 0, "ok": force_exits == 0},
    }


def _capital_at_risk(open_trades: list[dict]) -> dict:
    if not open_trades:
        return {"abs_loss": 0.0, "open_count": 0, "open_notional": 0.0}
    risk = 0.0
    notional = 0.0
    for t in open_trades:
        stake = t.get("stake_amount") or 0.0
        sl = t.get("stop_loss_ratio") or 0.0
        risk += stake * abs(sl)
        notional += stake
    return {"abs_loss": round(risk, 2), "open_count": len(open_trades), "open_notional": round(notional, 2)}


def _equity_curve_live(
    closed_trades: list[dict],
    open_trades: list[dict],
    starting_capital: float,
    bot_start_ts_ms: int,
) -> list[list]:
    """Return [[ts_ms, equity_usd], ...] from launch onward.

    Always seeds with [bot_start_ts_ms, starting_capital] so the curve renders
    even before the first trade closes. Closed trades stack cumulatively. A
    final synthetic point at 'now' includes unrealized P&L from open trades
    so the live tip reflects the wallet right now.
    """
    out: list[list] = []
    if bot_start_ts_ms:
        out.append([bot_start_ts_ms, round(starting_capital, 4)])
    pts = sorted(
        [(t.get("close_timestamp") or 0, float(t.get("profit_abs") or 0)) for t in closed_trades],
        key=lambda x: x[0],
    )
    cum = 0.0
    for ts, pnl in pts:
        if not ts:
            continue
        cum += pnl
        out.append([ts, round(starting_capital + cum, 4)])
    unrealized = sum(float(t.get("profit_abs") or 0) for t in open_trades)
    if unrealized:
        out.append([int(time.time() * 1000), round(starting_capital + cum + unrealized, 4)])
    return out


def _drawdown_curve(equity: list[list]) -> list[list]:
    """Underwater chart: % below running peak."""
    if not equity:
        return []
    peak = equity[0][1]
    out = []
    for ts, v in equity:
        if v > peak:
            peak = v
        dd = ((v - peak) / peak * 100) if peak else 0
        out.append([ts, round(dd, 4)])
    return out


# ── Polling ────────────────────────────────────────────────────────────────
async def _poll_bot(client: httpx.AsyncClient, bot: dict) -> dict:
    paths = ["profit", "status", "balance", "show_config", "whitelist"]
    results = await asyncio.gather(*[_get(client, bot["url"], p) for p in paths])
    profit, profit_err = results[0]
    status, _ = results[1]
    balance, balance_err = results[2]
    cfg, cfg_err = results[3]
    whitelist, _ = results[4]
    trades_resp, _ = await _get(client, bot["url"], "trades?limit=200")

    err = profit_err or balance_err or cfg_err
    if err:
        return {"key": bot["key"], "error": err, "reachable": False}

    open_trades = status if isinstance(status, list) else []
    closed_trades = (trades_resp or {}).get("trades", []) if trades_resp else []
    all_trades = closed_trades + open_trades

    starting_capital = float((balance or {}).get("starting_capital") or 0.0)
    bot_owned = float((balance or {}).get("total_bot") or 0.0)
    is_dry_run = bool((cfg or {}).get("dry_run"))
    bot_start_ts = (profit or {}).get("bot_start_timestamp", 0) / 1000.0
    days_running = (time.time() - bot_start_ts) / 86400.0 if bot_start_ts else 0

    per_pair = _per_pair_pnl(closed_trades)
    closed_pnl = float((profit or {}).get("profit_closed_coin") or 0.0)
    bot_start_ts_ms = int(bot_start_ts * 1000) if bot_start_ts else 0
    live_equity = _equity_curve_live(closed_trades, open_trades, starting_capital, bot_start_ts_ms)
    drawdown_curve = _drawdown_curve(live_equity)

    return {
        "key": bot["key"], "name": bot["name"], "label": bot["label"],
        "reachable": True, "dry_run": is_dry_run,
        "bot_start_ts": bot_start_ts, "days_running": round(days_running, 1),
        "wallet": {
            "starting_capital": round(starting_capital, 2),
            "bot_owned": round(bot_owned, 2),
            "total": round(float((balance or {}).get("total") or 0.0), 2),
        },
        "pnl": {
            "closed": round(closed_pnl, 2),
            "all_coin": round(float((profit or {}).get("profit_all_coin") or 0.0), 2),
            "closed_pct": round(float((profit or {}).get("profit_closed_percent") or 0.0), 2),
            "all_pct": round(float((profit or {}).get("profit_all_percent") or 0.0), 2),
        },
        "stats": {
            "trade_count": int((profit or {}).get("trade_count") or 0),
            "closed_trade_count": int((profit or {}).get("closed_trade_count") or 0),
            "winning_trades": int((profit or {}).get("winning_trades") or 0),
            "losing_trades": int((profit or {}).get("losing_trades") or 0),
            "winrate": float((profit or {}).get("winrate") or 0.0),
            "profit_factor": (profit or {}).get("profit_factor"),
            "sharpe": (profit or {}).get("sharpe"),
            "sortino": (profit or {}).get("sortino"),
            "max_drawdown": float((profit or {}).get("max_drawdown") or 0.0),
            "best_pair": (profit or {}).get("best_pair"),
            "best_pair_pct": (profit or {}).get("best_rate"),
            "avg_duration": (profit or {}).get("avg_duration"),
        },
        "open_trades": [
            {
                "pair": t.get("pair"),
                "open_rate": t.get("open_rate"),
                "current_rate": t.get("current_rate"),
                "profit_pct": t.get("profit_pct"),
                "profit_abs": t.get("profit_abs"),
                "stake_amount": t.get("stake_amount"),
                "open_date": t.get("open_date"),
                "open_timestamp": t.get("open_timestamp"),
                "stop_loss_abs": t.get("stop_loss_abs"),
                "stop_loss_pct": t.get("stop_loss_pct"),
                "amount": t.get("amount"),
            }
            for t in open_trades
        ],
        "recent_trades": [
            {
                "pair": t.get("pair"),
                "is_open": t.get("is_open"),
                "open_date": t.get("open_date"),
                "close_date": t.get("close_date"),
                "open_timestamp": t.get("open_timestamp"),
                "close_timestamp": t.get("close_timestamp"),
                "open_rate": t.get("open_rate"),
                "close_rate": t.get("close_rate"),
                "profit_pct": t.get("profit_pct"),
                "profit_abs": t.get("profit_abs"),
                "exit_reason": t.get("exit_reason"),
                "trade_duration": t.get("trade_duration"),
            }
            for t in sorted(closed_trades, key=lambda x: x.get("close_timestamp") or 0, reverse=True)[:30]
        ],
        "per_pair": per_pair,
        "expectancy": _expectancy(closed_trades),
        "capital_at_risk": _capital_at_risk(open_trades),
        "concentration": _concentration(per_pair, closed_pnl),
        "gate1": _gate1(all_trades, days_running),
        "gate2": _gate2(profit or {}, starting_capital, days_running, bot["baseline"]),
        "gate3": _gate3(all_trades, bot["baseline"]),
        "baseline": bot["baseline"],
        "equity_live": live_equity,
        "drawdown_curve": drawdown_curve,
        "whitelist_size": len((whitelist or {}).get("whitelist", [])) if whitelist else None,
    }


async def _poll_loop():
    while True:
        _cache["last_poll_started_at"] = time.time()
        try:
            async with httpx.AsyncClient() as client:
                results = await asyncio.gather(*[_poll_bot(client, b) for b in BOTS], return_exceptions=True)
                for bot, r in zip(BOTS, results):
                    if isinstance(r, Exception):
                        # Overwrite the cached snapshot so callers don't see
                        # last successful run as still 'reachable'.
                        msg = str(r)
                        _cache["errors"][bot["key"]] = msg
                        _cache["bots"][bot["key"]] = {
                            "key": bot["key"], "name": bot["name"], "label": bot["label"],
                            "reachable": False, "error": msg,
                        }
                    else:
                        _cache["bots"][bot["key"]] = r
                        if r.get("reachable"):
                            _cache["errors"].pop(bot["key"], None)
                        else:
                            _cache["errors"][bot["key"]] = r.get("error", "unreachable")
        except Exception as exc:
            log.exception("poll cycle failed: %s", exc)
        _cache["last_poll_finished_at"] = time.time()
        await asyncio.sleep(POLL_INTERVAL)


# ── App ────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_poll_loop())
    log.info("ft-dashboard up; poll interval %ds", POLL_INTERVAL)
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan, title="master-trader")


@app.middleware("http")
async def no_cache_headers(request, call_next):
    """Tell Cloudflare + browsers not to cache anything we serve. The dashboard
    is behind Cloudflare Access; without this, CF sometimes caches the auth
    challenge HTML and serves it to authenticated users on subsequent loads."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "last_poll": _cache.get("last_poll_finished_at")}


@app.get("/api/state")
async def api_state():
    return JSONResponse({
        "last_poll": _cache.get("last_poll_finished_at"),
        "poll_age_s": (time.time() - _cache["last_poll_finished_at"]) if _cache.get("last_poll_finished_at") else None,
        "bots": _cache.get("bots", {}),
        "errors": _cache.get("errors", {}),
    })


def _bot_meta(key: str) -> dict | None:
    for b in BOTS:
        if b["key"] == key:
            return b
    return None


@app.get("/api/equity/{bot_key}")
async def api_equity(bot_key: str):
    """Live cumulative equity + scaled backtest expected curve.

    Backtest CSV is `timestamp_ms,equity` starting at $200; we rescale to
    bot's actual starting capital so the curves are comparable.
    """
    snap = _cache["bots"].get(bot_key)
    meta = _bot_meta(bot_key)
    if not snap or not meta:
        return JSONResponse({"error": "not found"}, status_code=404)

    starting = snap["wallet"]["starting_capital"]
    bot_start_ts_ms = int(snap.get("bot_start_ts", 0) * 1000)

    # Read the backtest CSV (timestamp_ms, equity starting at $200) and rebase
    # it onto the live timeline: equity scaled to live starting capital, AND
    # timestamps shifted so day 0 of the backtest = bot_start_ts. Without the
    # time shift the expected curve sits in 2023 and the chart filters it
    # away when the user is looking at the live window.
    csv_path = OVERLAYS_DIR / f"expected_{snap['name']}.csv"
    expected: list[list] = []
    if csv_path.exists() and starting > 0 and bot_start_ts_ms:
        scale = starting / meta["baseline"]["starting_equity_in_csv"]
        try:
            raw: list[tuple[int, float]] = []
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    raw.append((int(row["timestamp_ms"]), float(row["equity"])))
            if raw:
                csv_origin_ms = raw[0][0]
                # End the projection at "now" so the dashed line stays in view.
                horizon_ms = int(time.time() * 1000) + 86_400_000
                for ts, eq in raw:
                    shifted = bot_start_ts_ms + (ts - csv_origin_ms)
                    if shifted > horizon_ms:
                        break
                    expected.append([shifted, round(eq * scale, 4)])
        except Exception as exc:
            log.warning("overlay parse %s: %s", csv_path.name, exc)

    return JSONResponse({
        "starting_capital": starting,
        "live": snap.get("equity_live", []),
        "drawdown": snap.get("drawdown_curve", []),
        "expected": expected,
        "bot_start_ts_ms": bot_start_ts_ms,
    })


_ALLOWED_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"}
_PAIR_RE = re.compile(r"^[A-Z0-9]{2,15}/(USDT|USDC|BTC|ETH|BUSD)$")


@app.get("/api/closed_trades")
async def api_closed_trades():
    """Aggregate closed trades across the fleet for the trades tab.

    Reuses the snapshot cache's recent_trades (last 30 per bot, already in
    timestamp form). Returns a flat list sorted newest-first with everything
    a chart card needs: pair, timestamps, entry/exit rates, stoploss pct,
    exit reason, win flag, bot identity for color theming.
    """
    out: list[dict] = []
    for bot in BOTS:
        snap = _cache["bots"].get(bot["key"])
        if not snap:
            continue
        for t in snap.get("recent_trades", []):
            if t.get("is_open") or not t.get("close_timestamp"):
                continue
            entry = t.get("open_rate")
            stoploss_pct = bot.get("baseline", {}).get("worst_trade_pct", -5.0) / 100.0
            stop_price = entry * (1 + stoploss_pct) if entry else None
            out.append({
                "bot_key": bot["key"],
                "bot_name": bot["name"],
                "pair": t.get("pair"),
                "open_date": t.get("open_date"),
                "close_date": t.get("close_date"),
                "open_ts": t.get("open_timestamp"),
                "close_ts": t.get("close_timestamp"),
                "open_rate": entry,
                "close_rate": t.get("close_rate"),
                "stop_rate": stop_price,
                "stoploss_pct": stoploss_pct * 100,
                "profit_pct": t.get("profit_pct"),
                "profit_abs": t.get("profit_abs"),
                "exit_reason": t.get("exit_reason"),
                "duration_min": t.get("trade_duration"),
                "is_win": (t.get("profit_abs") or 0) > 0,
            })
    out.sort(key=lambda x: x.get("close_ts") or 0, reverse=True)
    return JSONResponse({"trades": out, "count": len(out)})


@app.get("/api/binance_candles")
async def api_binance_candles(pair: str, timeframe: str = "1h", limit: int = 500):
    """Hit Binance public klines REST directly. No auth needed, supports
    any timeframe, no Freqtrade-bot dependency. Used by the trades-tab
    candle charts so closed-trade history can be visualized at any
    timeframe even after a bot is killed.

    Binance kline schema:
      [open_time_ms, open, high, low, close, volume, close_time_ms, ...]

    We normalize to the same shape as /api/candles/{bot_key}:
      [date_ms, open, close, low, high, volume]
    """
    pair = pair.strip().upper()
    if not _PAIR_RE.match(pair):
        return JSONResponse({"error": "invalid pair"}, status_code=400)
    if timeframe not in _ALLOWED_TIMEFRAMES:
        return JSONResponse({"error": "invalid timeframe"}, status_code=400)
    limit = max(10, min(limit, 1000))

    symbol = pair.replace("/", "")
    url = "https://api.binance.com/api/v3/klines"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                url,
                params={"symbol": symbol, "interval": timeframe, "limit": limit},
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code != 200:
                return JSONResponse({"error": f"HTTP {r.status_code}"}, status_code=502)
            rows = r.json()
    except Exception as exc:
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=502)

    ohlc = []
    for row in rows:
        try:
            ohlc.append([
                int(row[0]),       # open_time_ms
                float(row[1]),     # open
                float(row[4]),     # close
                float(row[3]),     # low
                float(row[2]),     # high
                float(row[5]),     # volume
            ])
        except Exception:
            continue
    return JSONResponse({"pair": pair, "timeframe": timeframe, "candles": ohlc})


@app.get("/api/candles/{bot_key}")
async def api_candles(bot_key: str, pair: str, timeframe: str = "1h", limit: int = 200):
    """Proxy bot's pair_candles endpoint, return normalized OHLC.

    Inputs are validated and forwarded as proper httpx params (no string
    concatenation into the URL), so a malicious `pair` can't smuggle extra
    query params or path traversal into the upstream Freqtrade REST.
    """
    bot = _bot_meta(bot_key)
    if not bot:
        return JSONResponse({"error": "bot not found"}, status_code=404)
    pair = pair.strip().upper()
    if not _PAIR_RE.match(pair):
        return JSONResponse({"error": "invalid pair"}, status_code=400)
    if timeframe not in _ALLOWED_TIMEFRAMES:
        return JSONResponse({"error": "invalid timeframe"}, status_code=400)
    limit = max(10, min(limit, 1000))

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{bot['url']}/api/v1/pair_candles",
                auth=(API_USER, API_PASS),
                params={"pair": pair, "timeframe": timeframe, "limit": limit},
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code != 200:
                return JSONResponse({"error": f"HTTP {r.status_code}"}, status_code=502)
            data = r.json()
    except Exception as exc:
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=502)

    cols = data.get("columns", [])
    rows = data.get("data", [])
    idx = {c: i for i, c in enumerate(cols)}
    needed = ("date", "open", "high", "low", "close", "volume")
    if not all(k in idx for k in needed):
        return JSONResponse({"error": "unexpected schema"}, status_code=502)
    ohlc = []
    for row in rows:
        try:
            ohlc.append([
                row[idx["date"]],
                row[idx["open"]], row[idx["close"]],
                row[idx["low"]], row[idx["high"]],
                row[idx["volume"]],
            ])
        except Exception:
            continue
    return JSONResponse({"pair": pair, "timeframe": timeframe, "candles": ohlc})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
