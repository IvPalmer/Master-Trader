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
  /api/killers/state   killers copy-trader paper-sim state (SQLite)
  /healthz             liveness
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import re
import sqlite3
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import yaml
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
    # ShortKeltnerV2 Binance dry-run (port 8100) RETIRED 2026-05-29 — going
    # HL-only for the short (Binance futures are CVM-banned for BR anyway).
    # Code kept in git (ShortKeltnerV2.py/.json) — it's the only backtestable
    # version since HL serves no history. Only the HL forward bot runs live.
    {
        "key": "short-keltner-hl",
        "name": "ShortKeltnerV2HL",
        "label": "short-keltner-hl",
        "url": "http://ft-short-keltner-hl:8080",
        # DRY-RUN on Hyperliquid (self-custody DEX perps, USDC-margined). Same
        # logic as short-keltner, forward-only: HL serves NO historical OHLCV so
        # it cannot be backtested — this is the on-venue OOS measurement codex
        # required before any capital. No baseline transfers from the Binance
        # backtest (HL funding is oracle/premium-based and inverts vs Binance).
        # Observational; no keys, no capital. Standalone container (not in this
        # compose). See docs/hyperliquid_short_validation_2026-05-29.md.
        "observational": True,
        "no_baseline": True,
        "baseline": None,
    },
    # killers-scalp + insiders-scalp RETIRED 2026-05-29: both validated dead this
    # session (Killers unprofitable −$511/−$1536 + live PF 0.011; Insiders copier
    # edge negative −8.7%/−13%). Containers removed; do not re-add.
]

API_USER = os.environ.get("FREQTRADE__API_SERVER__USERNAME", "")
API_PASS = os.environ.get("FREQTRADE__API_SERVER__PASSWORD", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "10"))
OVERLAYS_DIR = Path(os.environ.get("OVERLAYS_DIR", "/overlays"))
KILLERS_DB = Path(os.environ.get("KILLERS_DB", "/data/killers/state.db"))

# Phase 5 / Gate constants
GATE1_TRADES, GATE1_DAYS, GATE1_PAIRS = 30, 14, 5
GATE2_PROFIT_BAND, GATE2_PF_BAND, GATE2_DD_MULT = 0.25, 0.20, 1.5
GATE3_LOSS_MULT, GATE3_CONSEC_LOSSES = 1.5, 5
CONCENTRATION_WARN, CONCENTRATION_DANGER = 0.40, 0.50

# How long since last successful poll before a bot is considered stale.
STALE_THRESHOLD_S = 60

_cache: dict[str, Any] = {
    "last_poll_started_at": None,
    "last_poll_finished_at": None,
    "bots": {},
    "errors": {},
    # Maps bot_key → unix timestamp of last successful (reachable=True) poll.
    "last_reachable_at": {},
}

# ── Events store ──────────────────────────────────────────────────────────────
# events.yml lives alongside app.py.  We cache in module scope and hot-reload
# when the file modtime changes — no restart required.
_EVENTS_PATH = Path(__file__).parent / "events.yml"
_events_cache: dict[str, Any] = {"mtime": 0.0, "data": []}


def _load_events() -> list[dict]:
    """Load and cache fleet events from events.yml.

    Contract: each entry has {bot, ts, label, kind}.  Returns a list of dicts
    ready for JSON serialisation.  Hot-reloads on file modtime change so the
    operator can append events live without restarting the container.
    """
    try:
        mtime = _EVENTS_PATH.stat().st_mtime
    except FileNotFoundError:
        return []
    if mtime != _events_cache["mtime"]:
        try:
            with open(_EVENTS_PATH) as f:
                raw = yaml.safe_load(f) or []
            _events_cache["data"] = [
                {"bot": e.get("bot", "fleet"), "ts": str(e.get("ts", "")),
                 "label": str(e.get("label", "")), "kind": str(e.get("kind", "milestone"))}
                for e in raw if isinstance(e, dict)
            ]
            _events_cache["mtime"] = mtime
        except Exception as exc:
            log.warning("events.yml parse error: %s", exc)
    return _events_cache["data"]


def _global_events() -> list[dict]:
    """Return global events feed sorted newest-first."""
    events = _load_events()
    return sorted(events, key=lambda e: e["ts"], reverse=True)


def _bot_events(bot_key: str) -> list[dict]:
    """Return events for a specific bot, oldest-first (for equity chart annotations)."""
    events = _load_events()
    return sorted([e for e in events if e.get("bot") == bot_key], key=lambda e: e["ts"])


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
    """Gate 1: minimum sample checks.

    Adds `blocked_on` to each sub-key: a human-readable string when the gate
    is not yet met, null when it passes.
    """
    closed = [t for t in trades if not t.get("is_open")]
    pairs = {t.get("pair") for t in closed if t.get("pair")}
    trade_ok = len(closed) >= GATE1_TRADES
    days_ok = days_running >= GATE1_DAYS
    pairs_ok = len(pairs) >= GATE1_PAIRS
    return {
        "trades": {
            "actual": len(closed), "target": GATE1_TRADES, "ok": trade_ok,
            "pct": min(100, len(closed) / GATE1_TRADES * 100),
            "blocked_on": (f"{GATE1_TRADES - len(closed)} more trades" if not trade_ok else None),
        },
        "days": {
            "actual": round(days_running, 1), "target": GATE1_DAYS, "ok": days_ok,
            "pct": min(100, days_running / GATE1_DAYS * 100),
            "blocked_on": (f"{GATE1_DAYS - days_running:.1f} more days" if not days_ok else None),
        },
        "pairs": {
            "actual": len(pairs), "target": GATE1_PAIRS, "ok": pairs_ok,
            "pct": min(100, len(pairs) / GATE1_PAIRS * 100),
            "blocked_on": (f"{GATE1_PAIRS - len(pairs)} more pairs" if not pairs_ok else None),
        },
    }


def _gate2(profit: dict, starting_capital: float, days_running: float, baseline: dict) -> dict:
    """Gate 2: calibration checks (profit, profit-factor, drawdown).

    Adds `blocked_on` to each sub-key: human string when failing, null when ok.
    """
    actual_pct = (profit.get("profit_all_coin", 0.0) / starting_capital * 100) if starting_capital else 0
    expected_pct = baseline["annual_return_pct"] * (days_running / 365) if days_running > 0 else 0
    profit_lower = round(expected_pct * (1 - GATE2_PROFIT_BAND), 2)
    profit_upper = round(expected_pct * (1 + GATE2_PROFIT_BAND), 2)
    profit_status = ("n/a" if expected_pct == 0
                     else "cold" if actual_pct < profit_lower
                     else "hot" if actual_pct > profit_upper
                     else "ok")
    profit_ok = profit_status == "ok"
    delta_pp = round(actual_pct - expected_pct, 2)
    profit_b = {
        "actual_pct": round(actual_pct, 2), "expected_pct": round(expected_pct, 2),
        "lower": profit_lower, "upper": profit_upper, "status": profit_status,
        "blocked_on": (f"outside ±25% band · {delta_pp:+.1f}pp vs expected"
                       if not profit_ok and profit_status != "n/a" else None),
    }

    pf_actual = profit.get("profit_factor")
    pf_lower = round(baseline["profit_factor"] * (1 - GATE2_PF_BAND), 2)
    pf_upper = round(baseline["profit_factor"] * (1 + GATE2_PF_BAND), 2)
    pf_status = ("n/a" if pf_actual is None
                 else "cold" if pf_actual < pf_lower
                 else "hot" if pf_actual > pf_upper
                 else "ok")
    pf_ok = pf_status == "ok"
    pf_b = {
        "actual": round(pf_actual, 2) if pf_actual else None,
        "expected": baseline["profit_factor"],
        "lower": pf_lower, "upper": pf_upper, "status": pf_status,
        "blocked_on": (f"outside ±20% band · need {pf_lower:.2f} to {pf_upper:.2f}"
                       if not pf_ok and pf_status != "n/a" else None),
    }

    dd_actual = (profit.get("max_drawdown", 0.0) or 0.0) * 100
    dd_cap = baseline["max_dd_pct"] * GATE2_DD_MULT
    dd_status = "breach" if dd_actual > dd_cap else "hot" if dd_actual > baseline["max_dd_pct"] else "ok"
    dd_ok = dd_status == "ok"
    dd_b = {
        "actual_pct": round(dd_actual, 2), "expected_pct": baseline["max_dd_pct"],
        "cap_pct": round(dd_cap, 2), "status": dd_status,
        "blocked_on": (f"DD {dd_actual / baseline['max_dd_pct']:.1f}× backtest · cap 1.5×"
                       if not dd_ok else None),
    }
    return {"profit": profit_b, "pf": pf_b, "dd": dd_b}


def _gate3(trades: list[dict], baseline: dict) -> dict:
    """Gate 3: tail-risk checks (worst trade, consec losses, force exits).

    Adds `blocked_on` to each sub-key.
    """
    closed = [t for t in trades if not t.get("is_open")]
    worst = min((t.get("profit_pct", 0) or 0) for t in closed) if closed else 0
    worst_cap = baseline["worst_trade_pct"] * GATE3_LOSS_MULT
    force_exits = sum(1 for t in closed if "force" in (t.get("exit_reason") or "").lower())
    consec = _consec_losses(closed)
    worst_ok = worst >= worst_cap
    consec_ok = consec <= GATE3_CONSEC_LOSSES
    force_ok = force_exits == 0
    return {
        "worst_trade_pct": {
            "actual": round(worst, 2), "cap": round(worst_cap, 2), "ok": worst_ok,
            "blocked_on": (f"worst trade {worst:.1f}% · cap {worst_cap:.1f}%"
                           if not worst_ok else None),
        },
        "consec_losses": {
            "actual": consec, "cap": GATE3_CONSEC_LOSSES, "ok": consec_ok,
            "blocked_on": (f"{consec} consecutive losses · cap {GATE3_CONSEC_LOSSES}"
                           if not consec_ok else None),
        },
        "force_exits": {
            "actual": force_exits, "cap": 0, "ok": force_ok,
            "blocked_on": (f"{force_exits} force-exit(s) detected" if not force_ok else None),
        },
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


# ── New helpers: links, 24h delta, equity annotations ─────────────────────────

def _bot_links(bot: dict, open_trades: list[dict], per_pair: list[dict]) -> dict:
    """Build the `links` block for a bot.

    freqtrade_ui derives the public hostname from the bot's label (same
    subdomain pattern as the Cloudflare Access-protected dashboard).

    tradingview_top_pair picks the top open position by stake; if none, falls
    back to the top-profit closed pair.  Futures pairs get `.P` suffix.
    """
    label = bot.get("label", bot["key"])
    freqtrade_ui = f"https://{label}.master-trader.grooveops.dev/"

    # Pick candidate pair for TradingView link.
    tv_pair: str | None = None
    is_futures = False  # KillersScalp uses futures
    if open_trades:
        best_open = max(open_trades, key=lambda t: t.get("stake_amount") or 0)
        tv_pair = best_open.get("pair")
        # Detect futures by checking the pair string or bot name
        is_futures = "killers" in bot["key"].lower()
    elif per_pair:
        tv_pair = per_pair[0]["pair"]
        is_futures = "killers" in bot["key"].lower()

    tv_url: str | None = None
    if tv_pair:
        symbol = tv_pair.replace("/", "")
        suffix = ".P" if is_futures else ""
        tv_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}{suffix}"

    return {
        "freqtrade_ui": freqtrade_ui,
        "tradingview_top_pair": tv_url,
        "logs_hint": f"docker logs ft-{label} --tail 50",
    }


def _delta_24h(
    closed_trades: list[dict],
    current_dd_pct: float,
    baseline: dict | None,
    bot: dict,
) -> dict:
    """Compute 24-hour rolling window metrics.

    closed_trades — all closed trades for the bot (not just recent 30).
    current_dd_pct — current max drawdown as a percentage (0-100 scale).
    baseline — bot baseline dict or None for observational bots.

    Returns:
      new_trades        — closed trades in the last 24 h
      pnl_usd           — sum of profit_abs for those trades
      dd_breach         — True if current drawdown > 1.5× baseline drawdown cap
      signals_observed  — placeholder (killers-style bots would populate this
                          from SQLite; for Freqtrade bots always 0)
    """
    cutoff_ms = (time.time() - 86_400) * 1000
    recent = [t for t in closed_trades
              if not t.get("is_open") and (t.get("close_timestamp") or 0) >= cutoff_ms]
    pnl_usd = sum(float(t.get("profit_abs") or 0) for t in recent)

    dd_breach = False
    if baseline and baseline.get("max_dd_pct"):
        dd_cap = baseline["max_dd_pct"] * GATE2_DD_MULT
        dd_breach = current_dd_pct > dd_cap

    return {
        "new_trades": len(recent),
        "pnl_usd": round(pnl_usd, 4),
        "dd_breach": dd_breach,
        "signals_observed": 0,  # populated for killers bots via /api/killers/state
    }


def _equity_annotations(bot_key: str) -> list[dict]:
    """Return equity chart annotations for a bot from the events store.

    Shape: [{ts, label, kind}, ...] ordered oldest-first so the chart can
    render vertical markers chronologically.
    """
    return [
        {"ts": e["ts"], "label": e["label"], "kind": e["kind"]}
        for e in _bot_events(bot_key)
    ]


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

    # ── New: compute current DD % for dd_breach check ──────────────────────
    current_dd_pct = (profit or {}).get("max_drawdown", 0.0) or 0.0
    current_dd_pct *= 100  # Freqtrade returns ratio (e.g. 0.05 = 5%)

    # ── New: no-baseline bots (killers-scalp) ─────────────────────────────
    no_baseline = bot.get("no_baseline", False)
    baseline = bot.get("baseline") if not no_baseline else None

    open_trades_out = [
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
    ]

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
        "open_trades": open_trades_out,
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
        "observational": bot.get("observational", False),
        # Gates: null for no-baseline bots, observational marker for copy-traders
        # with soft gating, full gate objects for quant-validated bots.
        "gate1": (None if no_baseline
                  else {"status": "observational"} if bot.get("observational")
                  else _gate1(all_trades, days_running)),
        "gate2": (None if no_baseline
                  else {"status": "observational"} if bot.get("observational")
                  else _gate2(profit or {}, starting_capital, days_running, bot["baseline"])),
        "gate3": (None if no_baseline
                  else {"status": "observational"} if bot.get("observational")
                  else _gate3(all_trades, bot["baseline"])),
        "baseline": baseline,
        "equity_live": live_equity,
        "drawdown_curve": drawdown_curve,
        "whitelist_size": len((whitelist or {}).get("whitelist", [])) if whitelist else None,
        # ── NEW: additive fields (frontend feature-detects these) ──────────
        "links": _bot_links(bot, open_trades_out, per_pair),
        "delta_24h": _delta_24h(closed_trades, current_dd_pct, baseline, bot),
        "equity_annotations": _equity_annotations(bot["key"]),
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
                            _cache["last_reachable_at"][bot["key"]] = time.time()
                        else:
                            _cache["errors"][bot["key"]] = r.get("error", "unreachable")
        except Exception as exc:
            log.exception("poll cycle failed: %s", exc)
        _cache["last_poll_finished_at"] = time.time()
        await asyncio.sleep(POLL_INTERVAL)


# ── Status level ──────────────────────────────────────────────────────────────

def _fleet_status() -> dict:
    """Compute top-level status level for the fleet.

    green  — all bots reachable, none stale.
    yellow — one or more dry-run bots stale/unreachable.
    red    — any live bot unreachable, or any bot stale > threshold AND live.

    live bot = dry_run is False in its snapshot.
    """
    now = time.time()
    stale_bots: list[str] = []
    any_live_unreachable = False

    for bot in BOTS:
        key = bot["key"]
        snap = _cache["bots"].get(key, {})
        last_ok = _cache["last_reachable_at"].get(key)
        is_stale = (last_ok is None) or ((now - last_ok) > STALE_THRESHOLD_S)
        is_live = not snap.get("dry_run", True)

        if is_stale:
            stale_bots.append(key)
            if is_live:
                any_live_unreachable = True

    if any_live_unreachable:
        level = "red"
        summary = (f"live bot unreachable: {', '.join(stale_bots)}"
                   if stale_bots else "live bot unreachable")
    elif stale_bots:
        level = "yellow"
        summary = f"{len(stale_bots)} bot(s) stale: {', '.join(stale_bots)}"
    else:
        level = "green"
        n = len([b for b in _cache["bots"].values() if b.get("reachable")])
        summary = f"all {n} bots reachable"

    return {"level": level, "summary": summary, "stale_bots": stale_bots}


# ── Killers SQLite helpers ─────────────────────────────────────────────────────

def _killers_db_query(sql: str, params: tuple = ()) -> list[dict]:
    """Run a read-only query against the killers state.db.

    Returns list of row dicts. Returns [] if the DB file doesn't exist or any
    error occurs — the endpoint degrades gracefully rather than 500ing.
    """
    if not KILLERS_DB.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{KILLERS_DB}?mode=ro", uri=True, check_same_thread=False)
        con.row_factory = sqlite3.Row
        try:
            cur = con.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
        finally:
            con.close()
    except Exception as exc:
        log.warning("killers DB query failed: %s", exc)
        return []


def _killers_open_positions() -> list[dict]:
    """Read open positions from the killers SQLite positions table.

    Returns a list of dicts shaped for the frontend hero card.
    Computes pnl_pct from entry vs current price (uses entry if current unknown).
    """
    rows = _killers_db_query(
        "SELECT id, symbol, side, entry_price, current_price, opened_at, signal_id "
        "FROM positions WHERE state = 'open' ORDER BY opened_at DESC"
    )
    now = time.time()
    out = []
    for r in rows:
        entry = r.get("entry_price") or 0.0
        current = r.get("current_price") or entry
        pnl_pct = ((current - entry) / entry * 100) if entry else 0.0
        side = (r.get("side") or "LONG").upper()
        if side == "SHORT":
            pnl_pct = -pnl_pct

        opened_at_str = r.get("opened_at") or ""
        age_minutes = 0
        if opened_at_str:
            try:
                import datetime
                opened_dt = datetime.datetime.fromisoformat(opened_at_str.replace("Z", "+00:00"))
                age_minutes = int((now - opened_dt.timestamp()) / 60)
            except Exception:
                age_minutes = 0

        out.append({
            "symbol": r.get("symbol", ""),
            "side": side,
            "entry": round(entry, 8),
            "current": round(current, 8),
            "pnl_pct": round(pnl_pct, 4),
            "age_minutes": age_minutes,
            "signal_id": r.get("signal_id"),
        })
    return out


def _killers_paper_pnl_history(wallet_start: float = 1000.0) -> list[dict]:
    """Build a time-indexed paper P&L series from the killers SQLite.

    Starts at wallet_start (default $1 000) at the bot's first event.
    Appends each closed position cumulatively.  If zero closed positions,
    returns a 2-point series so the frontend chart always has something to draw.

    Shape: [{ts: ISO8601, equity: float}, ...]
    """
    import datetime

    # Try to get the earliest event timestamp as "started_at"
    meta_rows = _killers_db_query(
        "SELECT MIN(created_at) as started_at FROM positions LIMIT 1"
    )
    started_at_str = (meta_rows[0].get("started_at") if meta_rows else None) or ""

    now_iso = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    if not started_at_str:
        # No data at all — flat 2-point series
        return [
            {"ts": "2026-05-25T00:00:00Z", "equity": wallet_start},
            {"ts": now_iso, "equity": wallet_start},
        ]

    # Normalise to ISO
    started_iso = started_at_str if "T" in started_at_str else started_at_str.replace(" ", "T") + "Z"

    closed_rows = _killers_db_query(
        "SELECT closed_at, pnl_abs FROM positions "
        "WHERE state = 'closed' AND closed_at IS NOT NULL "
        "ORDER BY closed_at ASC"
    )

    history = [{"ts": started_iso, "equity": wallet_start}]
    cum = 0.0
    for r in closed_rows:
        closed_at = r.get("closed_at", "")
        pnl = float(r.get("pnl_abs") or 0.0)
        cum += pnl
        ts_iso = (closed_at if "T" in closed_at else closed_at.replace(" ", "T") + "Z")
        history.append({"ts": ts_iso, "equity": round(wallet_start + cum, 4)})

    # Ensure a final "now" point so the chart tip is up to date
    if not closed_rows:
        history.append({"ts": now_iso, "equity": wallet_start})

    return history


# ── App ────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-warm events cache at startup
    _load_events()
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
    """Full fleet snapshot.

    Additive extensions vs original schema:
      bots[key].links             — freqtrade_ui, tradingview_top_pair, logs_hint
      bots[key].delta_24h         — new_trades, pnl_usd, dd_breach, signals_observed
      bots[key].gate1/2/3.*.blocked_on — human string when gate fails, null when ok
      bots[key].equity_annotations — [{ts, label, kind}] for equity chart markers
      bots[key].baseline          — null for killers-scalp (no quant baseline)
      bots[key].gate1/2/3         — null for killers-scalp (no baseline to gate against)
      events_global               — fleet-wide event feed [{ts, label, kind, bot}]
      status                      — {level, summary, stale_bots}
    """
    return JSONResponse({
        "last_poll": _cache.get("last_poll_finished_at"),
        "poll_age_s": (time.time() - _cache["last_poll_finished_at"]) if _cache.get("last_poll_finished_at") else None,
        "bots": _cache.get("bots", {}),
        "errors": _cache.get("errors", {}),
        # ── NEW ──────────────────────────────────────────────────────────────
        "events_global": _global_events(),
        "status": _fleet_status(),
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
    baseline = meta.get("baseline") or {}
    if csv_path.exists() and starting > 0 and bot_start_ts_ms and baseline.get("starting_equity_in_csv"):
        scale = starting / baseline["starting_equity_in_csv"]
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


# ── killers_bot observer state ────────────────────────────────────────────
# Observer-only bot listening to Binance Killers VIP channel. Not a
# Freqtrade instance — has its own SQLite. Mounted read-only at KILLERS_DB.

import sqlite3 as _sqlite

KILLERS_DB = os.environ.get("KILLERS_DB", "/var/lib/killers/state.sqlite")


@app.get("/api/killers/state")
async def api_killers_state():
    """Compact summary of the killers_bot observer + paper positions."""
    db_path = Path(KILLERS_DB)
    if not db_path.exists():
        return JSONResponse({"error": "killers db not mounted",
                             "expected_at": str(db_path)}, status_code=404)

    try:
        conn = _sqlite.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = _sqlite.Row
    except _sqlite.Error as e:
        return JSONResponse({"error": f"sqlite open: {e}"}, status_code=500)

    try:
        msg_count = conn.execute("SELECT COUNT(*) FROM raw_messages").fetchone()[0]
        cls_count = conn.execute("SELECT COUNT(*) FROM classifications").fetchone()[0]
        last_msg = conn.execute(
            "SELECT msg_id, received_at, posted_at, text FROM raw_messages "
            "ORDER BY msg_id DESC LIMIT 1"
        ).fetchone()
        kinds = {row["kind"]: row["n"] for row in conn.execute(
            "SELECT kind, COUNT(*) AS n FROM classifications GROUP BY kind"
        )}
        positions_open = conn.execute(
            "SELECT COUNT(*) FROM paper_positions WHERE state IN ('open','pending')"
        ).fetchone()[0]
        positions_closed = conn.execute(
            "SELECT COUNT(*) FROM paper_positions WHERE state = 'closed'"
        ).fetchone()[0]
        realized_pnl_total = conn.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) FROM paper_positions WHERE state = 'closed'"
        ).fetchone()[0]
        recent_classifications = [dict(r) for r in conn.execute(
            "SELECT c.msg_id, c.classified_at, c.kind, c.signal_id, c.symbol, "
            "       c.direction, c.confidence, "
            "       substr(m.text, 1, 200) AS text "
            "FROM classifications c "
            "LEFT JOIN raw_messages m ON m.msg_id = c.msg_id "
            "ORDER BY c.msg_id DESC LIMIT 20"
        )]
        recent_positions = [dict(r) for r in conn.execute(
            "SELECT pos_id, signal_id, symbol, direction, state, "
            "       open_msg_id, open_date, entry_mid, sl, leverage, "
            "       position_notional, realized_pct, realized_pnl, "
            "       close_reason, last_event_at "
            "FROM paper_positions ORDER BY pos_id DESC LIMIT 20"
        )]
        # Equity timeline: each closed position contributes its realized_pnl
        # to a cumulative virtual-account equity series starting at $1000.
        equity_rows = [dict(r) for r in conn.execute(
            "SELECT close_date, realized_pnl FROM paper_positions "
            "WHERE state = 'closed' AND close_date IS NOT NULL "
            "ORDER BY close_date ASC"
        )]
        # Per-symbol P&L for the top-symbol bar chart.
        per_symbol = [dict(r) for r in conn.execute(
            "SELECT symbol, COUNT(*) AS n, "
            "       COALESCE(SUM(realized_pnl), 0) AS pnl "
            "FROM paper_positions "
            "WHERE symbol IS NOT NULL "
            "GROUP BY symbol "
            "ORDER BY ABS(pnl) DESC LIMIT 15"
        )]
        # Classification arrival rate — bucket by hour for an activity chart.
        rate_rows = [dict(r) for r in conn.execute(
            "SELECT substr(classified_at, 1, 13) AS hour, COUNT(*) AS n "
            "FROM classifications GROUP BY hour ORDER BY hour ASC"
        )]
    finally:
        conn.close()

    return JSONResponse({
        "ok": True,
        "msg_count": msg_count,
        "classification_count": cls_count,
        "last_msg": dict(last_msg) if last_msg else None,
        "kind_distribution": kinds,
        "positions": {
            "open": positions_open,
            "closed": positions_closed,
            "realized_pnl_total_usd": round(realized_pnl_total or 0, 2),
        },
        "equity_timeline": equity_rows,
        "per_symbol": per_symbol,
        "rate_by_hour": rate_rows,
        "recent_classifications": recent_classifications,
        "recent_positions": recent_positions,
    })


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
        baseline = bot.get("baseline") or {}
        for t in snap.get("recent_trades", []):
            if t.get("is_open") or not t.get("close_timestamp"):
                continue
            entry = t.get("open_rate")
            stoploss_pct = baseline.get("worst_trade_pct", -5.0) / 100.0
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


@app.get("/api/killers/state")
async def api_killers_state():
    """Killers copy-trader paper-sim state from SQLite.

    Reads /data/killers/state.db (read-only mount).  Returns both the
    existing summary fields (signal count, wallet equity, recent signals) AND
    the new hero-promotion fields:

      open_positions — [{symbol, side, entry, current, pnl_pct, age_minutes,
                         signal_id}]  — live SQLite read, not cached
      paper_pnl_history — [{ts, equity}] — full cumulative equity time series
                          starting at $1 000 wallet.  Always ≥2 points so the
                          frontend chart has something to draw.

    Degrades gracefully: if the DB file doesn't exist (e.g. running locally
    without the killers sidecar), returns empty collections rather than 500.
    """
    # ── Core summary (existing schema, kept additive) ─────────────────────
    signal_rows = _killers_db_query(
        "SELECT id, symbol, direction, confidence, raw_text, created_at "
        "FROM signals ORDER BY created_at DESC LIMIT 50"
    )
    position_summary = _killers_db_query(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN state='open' THEN 1 ELSE 0 END) as open_count, "
        "SUM(CASE WHEN state='closed' THEN 1 ELSE 0 END) as closed_count, "
        "SUM(CASE WHEN state='closed' THEN pnl_abs ELSE 0 END) as realized_pnl "
        "FROM positions"
    )
    summary = position_summary[0] if position_summary else {}

    realized_pnl = float(summary.get("realized_pnl") or 0.0)
    wallet_equity = 1000.0 + realized_pnl

    # ── NEW: hero data + pnl history ──────────────────────────────────────
    open_positions = _killers_open_positions()
    paper_pnl_history = _killers_paper_pnl_history(wallet_start=1000.0)

    return JSONResponse({
        # Existing fields (preserved)
        "reachable": KILLERS_DB.exists(),
        "wallet_equity": round(wallet_equity, 4),
        "realized_pnl": round(realized_pnl, 4),
        "total_positions": int(summary.get("total") or 0),
        "open_count": int(summary.get("open_count") or 0),
        "closed_count": int(summary.get("closed_count") or 0),
        "recent_signals": [
            {
                "id": r.get("id"),
                "symbol": r.get("symbol"),
                "direction": r.get("direction"),
                "confidence": r.get("confidence"),
                "raw_text": r.get("raw_text"),
                "created_at": r.get("created_at"),
            }
            for r in signal_rows
        ],
        # ── NEW ──────────────────────────────────────────────────────────────
        "open_positions": open_positions,
        "paper_pnl_history": paper_pnl_history,
    })


@app.get("/api/binance_candles")
async def api_binance_candles(
    pair: str,
    timeframe: str = "1h",
    limit: int = 500,
    start_ms: int | None = None,
    end_ms: int | None = None,
):
    """Hit Binance public klines REST directly. No auth needed, supports
    any timeframe, no Freqtrade-bot dependency. Used by the trades-tab
    candle charts so closed-trade history can be visualized at any
    timeframe even after a bot is killed.

    start_ms / end_ms (optional) center the fetched window on a specific
    time range. Without them Binance returns the most-recent `limit`
    candles, which doesn't cover trades older than a few days at low TFs.

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
    params: dict[str, int | str] = {"symbol": symbol, "interval": timeframe, "limit": limit}
    if start_ms is not None:
        params["startTime"] = int(start_ms)
    if end_ms is not None:
        params["endTime"] = int(end_ms)
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                url,
                params=params,
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
