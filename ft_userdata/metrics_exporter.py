#!/usr/bin/env python3
"""
Freqtrade Prometheus Metrics Exporter

Scrapes all Freqtrade bot REST APIs and exposes metrics for Prometheus.
Runs as a long-lived process, updating metrics every 60 seconds.
"""

import json
import os
import time
import logging
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth
from prometheus_client import start_http_server, Gauge, Info

from api_utils import api_get as _api_get_with_retry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("ft-exporter")

# ── Bot configuration ────────────────────────────────────────────────
# Inside Docker compose network, all bots listen on internal port 8080.
# We reach them by service name.
def _load_bots_config() -> list[dict]:
    """Load bot registry from shared config, fall back to hardcoded defaults."""
    import json
    from pathlib import Path
    config_path = Path(__file__).parent / "bots_config.json"
    try:
        with open(config_path) as f:
            data = json.load(f)
        bots = []
        for name, info in data["bots"].items():
            if not info.get("active", True):
                continue
            service = info.get("service", name.lower().replace("v1", "").replace("strategy", ""))
            # Handle known service name mappings
            service_map = {
                "IchimokuTrendV1": "ichimokutrendv1",
                "EMACrossoverV1": "emacrossoverv1",
                "SupertrendStrategy": "supertrendstrategy",
                "MasterTraderV1": "mastertraderv1",
                "BollingerRSIMeanReversion": "bollingerrsimeanreversion",
                "FuturesSniperV1": "futuressniper",
                "AlligatorTrendV1": "alligatortrendv1",
                "GaussianChannelV1": "gaussianchannelv1",
                "BearCrashShortV1": "bearcrashshortv1",
                "BollingerBounceV1": "bollingerbouncev1",
                "KeltnerBounceV1": "keltnerbouncev1",
                "FundingFadeV1": "fundingfadev1",
                "FundingShortV1": "fundingshortv1",
            }
            service = service_map.get(name, service)
            bots.append({"service": service, "strategy": name})
        return bots
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return [
            {"service": "supertrendstrategy",       "strategy": "SupertrendStrategy"},
            {"service": "mastertraderv1",           "strategy": "MasterTraderV1"},
            {"service": "alligatortrendv1",         "strategy": "AlligatorTrendV1"},
            {"service": "gaussianchannelv1",        "strategy": "GaussianChannelV1"},
            {"service": "bearcrashshortv1",         "strategy": "BearCrashShortV1"},
            {"service": "bollingerbouncev1",        "strategy": "BollingerBounceV1"},
        ]

BOTS = _load_bots_config()

AUTH = HTTPBasicAuth(
    os.environ.get("FREQTRADE__API_SERVER__USERNAME", "freqtrader"),
    os.environ.get("FREQTRADE__API_SERVER__PASSWORD", "mastertrader"),
)
API_PORT = 8080
SCRAPE_INTERVAL = 60  # seconds

# ── Circuit Breaker ───────────────────────────────────────────────
# Dynamic capital tracking: starting capital is read from each LIVE bot's
# /balance endpoint and summed. Dry-run bots are excluded — their simulated
# P&L would dilute the breaker math and let real money go to zero without
# tripping the threshold (this is what the hardcoded INITIAL_CAPITAL=550
# regression caused on the $52 live FundingFade wallet).
CIRCUIT_BREAKER_PCT = 10.0
CIRCUIT_BREAKER_COOLDOWN = 3600
WEBHOOK_URL = os.environ.get(
    "CIRCUIT_BREAKER_WEBHOOK_URL",
    "http://trade-webhook:8088/webhooks/freqtrade",
)
CAPITAL_REFRESH_EVERY = 60  # rescrape /show_config + /balance every N scrapes
PEAK_STATE_FILE = Path(os.environ.get("PEAK_STATE_FILE", "/state/portfolio_peak.json"))

_live_initial_capital = 0.0  # Sum of starting_capital across LIVE bots
_live_bots: list[dict] = []  # Subset of BOTS that report dry_run=False
_capital_refresh_counter = 0

_portfolio_peak = 0.0
_circuit_breaker_triggered = False
_last_trigger_time = 0.0


def _load_peak_state() -> None:
    """Restore high-water mark from disk so a restart mid-drawdown doesn't
    erase the real peak. Without this, _portfolio_peak resets every restart
    and the breaker silently shifts its threshold downward."""
    global _portfolio_peak, _circuit_breaker_triggered, _last_trigger_time
    try:
        if PEAK_STATE_FILE.exists():
            with open(PEAK_STATE_FILE) as f:
                state = json.load(f)
            _portfolio_peak = float(state.get("peak", 0.0))
            _circuit_breaker_triggered = bool(state.get("triggered", False))
            _last_trigger_time = float(state.get("last_trigger_time", 0.0))
            log.info(
                "Restored portfolio peak from %s: $%.2f (triggered=%s)",
                PEAK_STATE_FILE, _portfolio_peak, _circuit_breaker_triggered,
            )
    except Exception as exc:
        log.error("Failed to load peak state: %s — starting from zero", exc)


def _save_peak_state() -> None:
    """Persist peak after every update. Atomic via temp + rename."""
    try:
        PEAK_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PEAK_STATE_FILE.with_suffix(PEAK_STATE_FILE.suffix + ".tmp")
        with open(tmp, "w") as f:
            json.dump({
                "peak": _portfolio_peak,
                "triggered": _circuit_breaker_triggered,
                "last_trigger_time": _last_trigger_time,
                "saved_at": time.time(),
            }, f)
        os.replace(tmp, PEAK_STATE_FILE)
    except Exception as exc:
        log.warning("Failed to save peak state: %s", exc)

# ── Prometheus metrics ───────────────────────────────────────────────
profit_total = Gauge(
    "freqtrade_profit_total",
    "Total closed profit in USDT",
    ["strategy"],
)
profit_pct = Gauge(
    "freqtrade_profit_pct",
    "Total closed profit percentage",
    ["strategy"],
)
trades_total = Gauge(
    "freqtrade_trades_total",
    "Total number of closed trades",
    ["strategy"],
)
trades_open = Gauge(
    "freqtrade_trades_open",
    "Number of currently open trades",
    ["strategy"],
)
win_rate = Gauge(
    "freqtrade_win_rate",
    "Win rate percentage (0-100)",
    ["strategy"],
)
balance = Gauge(
    "freqtrade_balance",
    "Current wallet balance in USDT",
    ["strategy"],
)
drawdown = Gauge(
    "freqtrade_drawdown",
    "Max drawdown percentage",
    ["strategy"],
)
unrealized_pnl = Gauge(
    "freqtrade_unrealized_pnl",
    "Total unrealized P&L of open trades in USDT",
    ["strategy"],
)
true_pnl = Gauge(
    "freqtrade_true_pnl",
    "True P&L (closed + unrealized) in USDT",
    ["strategy"],
)
bot_up = Gauge(
    "freqtrade_bot_up",
    "Whether the bot API is reachable (1=up, 0=down)",
    ["strategy"],
)
portfolio_drawdown_pct = Gauge(
    "freqtrade_portfolio_drawdown_pct",
    "Portfolio drawdown from high-water mark as percentage",
)
portfolio_value_total = Gauge(
    "freqtrade_portfolio_value_total",
    "Total portfolio value (initial capital + P&L) in USDT",
)


def fetch_json(service: str, endpoint: str, timeout: int = 10) -> dict | None:
    """GET JSON from a Freqtrade API endpoint with retry logic."""
    return _api_get_with_retry(API_PORT, endpoint, timeout=timeout, base_host=service)


def fetch_bot_meta(service: str) -> dict | None:
    """Fetch dry_run flag and starting_capital from a bot.

    /show_config exposes `dry_run`; /balance exposes `starting_capital`.
    Returns None if either call fails — caller treats that as 'unknown' and
    excludes the bot from breaker math until next refresh.
    """
    cfg = fetch_json(service, "show_config")
    if cfg is None:
        return None
    bal = fetch_json(service, "balance")
    if bal is None:
        return None
    return {
        "dry_run": bool(cfg.get("dry_run", True)),
        "starting_capital": float(bal.get("starting_capital", 0.0) or 0.0),
    }


def refresh_live_capital() -> None:
    """Rebuild the list of LIVE (non-dry-run) bots and sum their starting
    capital. Called on startup and periodically — a config change or a bot
    being added/removed propagates without an exporter restart."""
    global _live_bots, _live_initial_capital
    live = []
    total = 0.0
    for bot in BOTS:
        meta = fetch_bot_meta(bot["service"])
        if meta is None:
            log.warning(
                "Could not read meta for %s — excluding from breaker until next refresh",
                bot["strategy"],
            )
            continue
        if meta["dry_run"]:
            log.debug("Excluding %s from breaker (dry_run)", bot["strategy"])
            continue
        if meta["starting_capital"] <= 0:
            log.warning(
                "%s reports starting_capital=$%.2f — excluding from breaker",
                bot["strategy"], meta["starting_capital"],
            )
            continue
        live.append({**bot, "starting_capital": meta["starting_capital"]})
        total += meta["starting_capital"]

    _live_bots = live
    _live_initial_capital = total
    log.info(
        "Circuit breaker capital refreshed: %d live bots, $%.2f total starting capital",
        len(_live_bots), _live_initial_capital,
    )


def scrape_bot(bot: dict) -> float | None:
    """Scrape one bot and update its Prometheus metrics. Returns true P&L or None."""
    service = bot["service"]
    strategy = bot["strategy"]

    # ── /profit ──────────────────────────────────────────────────
    data = fetch_json(service, "profit")
    if data is None:
        bot_up.labels(strategy=strategy).set(0)
        return None

    bot_up.labels(strategy=strategy).set(1)

    closed_pnl = data.get("profit_closed_coin", 0)
    profit_total.labels(strategy=strategy).set(closed_pnl)
    profit_pct.labels(strategy=strategy).set(
        data.get("profit_closed_percent_sum", 0)
    )
    trades_total.labels(strategy=strategy).set(
        data.get("closed_trade_count", 0)
    )
    drawdown.labels(strategy=strategy).set(
        data.get("max_drawdown", 0)
    )

    # Win rate: derive from winning/losing trade counts
    winning = data.get("winning_trades", 0)
    losing = data.get("losing_trades", 0)
    total_closed = winning + losing
    if total_closed > 0:
        win_rate.labels(strategy=strategy).set(
            round(winning / total_closed * 100, 2)
        )
    else:
        win_rate.labels(strategy=strategy).set(0)

    # ── /status (open trades + unrealized P&L) ───────────────────
    bot_true_pnl = closed_pnl
    status_data = fetch_json(service, "status")
    if isinstance(status_data, list):
        trades_open.labels(strategy=strategy).set(len(status_data))
        open_pnl = sum(t.get("profit_abs", 0) for t in status_data)
        unrealized_pnl.labels(strategy=strategy).set(round(open_pnl, 2))
        bot_true_pnl = closed_pnl + open_pnl
        true_pnl.labels(strategy=strategy).set(round(bot_true_pnl, 2))
    else:
        trades_open.labels(strategy=strategy).set(0)
        unrealized_pnl.labels(strategy=strategy).set(0)
        true_pnl.labels(strategy=strategy).set(closed_pnl)

    # ── /balance ─────────────────────────────────────────────────
    bal_data = fetch_json(service, "balance")
    if bal_data:
        balance.labels(strategy=strategy).set(
            bal_data.get("total", 0)
        )

    return bot_true_pnl


def scrape_all() -> tuple[float | None, float | None]:
    """Scrape every configured bot.

    Returns (total_pnl_all_bots, live_pnl_only). `live_pnl_only` is the sum
    across bots in `_live_bots` and is the only number fed into the circuit
    breaker — dry-run P&L (simulated) cannot be allowed to dilute the
    threshold for real-money positions.
    """
    total_pnl = 0.0
    live_pnl = 0.0
    reachable = 0
    live_services = {b["service"] for b in _live_bots}
    for bot in BOTS:
        try:
            pnl = scrape_bot(bot)
            if pnl is not None:
                total_pnl += pnl
                reachable += 1
                if bot["service"] in live_services:
                    live_pnl += pnl
        except Exception as exc:
            log.error("Unexpected error scraping %s: %s", bot["strategy"], exc)
    if reachable == 0:
        return None, None
    return total_pnl, live_pnl


def stop_bot(bot: dict) -> bool:
    """Stop a bot via the Freqtrade API."""
    base = f"http://{bot['service']}:{API_PORT}/api/v1"
    try:
        resp = requests.post(f"{base}/stop", auth=AUTH, timeout=10)
        if resp.status_code == 200:
            log.info("Stopped %s", bot["strategy"])
            return True
        log.warning("Failed to stop %s: HTTP %d", bot["strategy"], resp.status_code)
        return False
    except Exception as exc:
        log.error("Error stopping %s: %s", bot["strategy"], exc)
        return False


def send_circuit_breaker_alert(portfolio_value: float, drawdown_pct: float) -> None:
    """Send emergency alert via webhook to Telegram."""
    message = (
        f"CIRCUIT BREAKER TRIGGERED\n\n"
        f"Live portfolio drawdown: {drawdown_pct:.1f}% (threshold: {CIRCUIT_BREAKER_PCT}%)\n"
        f"Live portfolio value: ${portfolio_value:,.2f} "
        f"(starting: ${_live_initial_capital:,.2f})\n"
        f"Loss: ${_live_initial_capital - portfolio_value:,.2f}\n\n"
        f"LIVE BOTS STOPPED ({', '.join(b['strategy'] for b in _live_bots)}). "
        f"Manual restart required.\n"
        f"Review positions before restarting."
    )
    try:
        payload = {"type": "status", "status": message}
        resp = requests.post(WEBHOOK_URL, data=payload, timeout=10)
        if resp.status_code in (200, 201, 204):
            log.info("Circuit breaker alert sent to Telegram")
        else:
            log.warning("Alert webhook returned HTTP %d", resp.status_code)
    except Exception as exc:
        log.error("Failed to send circuit breaker alert: %s", exc)


def check_circuit_breaker(live_pnl: float) -> None:
    """Check if LIVE portfolio drawdown exceeds threshold and stop LIVE bots if so.

    Inputs are scoped to live (non-dry-run) bots only. The dry-run sleeve has
    no real money and must not influence the breaker.
    """
    global _portfolio_peak, _circuit_breaker_triggered, _last_trigger_time

    if _live_initial_capital <= 0 or not _live_bots:
        # No live bots configured — breaker is a no-op. Don't update Prometheus
        # gauges so a stale 'all good' signal doesn't show on Grafana.
        return

    portfolio_value = _live_initial_capital + live_pnl

    if portfolio_value > _portfolio_peak:
        _portfolio_peak = portfolio_value
        _save_peak_state()

    if _portfolio_peak <= 0:
        # First scrape and we're at or below initial capital — seed the peak.
        _portfolio_peak = max(portfolio_value, _live_initial_capital)
        _save_peak_state()

    drawdown_pct = ((_portfolio_peak - portfolio_value) / _portfolio_peak) * 100

    portfolio_drawdown_pct.set(round(drawdown_pct, 2))
    portfolio_value_total.set(round(portfolio_value, 2))

    if drawdown_pct >= CIRCUIT_BREAKER_PCT:
        now = time.time()
        if not _circuit_breaker_triggered or (now - _last_trigger_time > CIRCUIT_BREAKER_COOLDOWN):
            log.critical(
                "CIRCUIT BREAKER: Live portfolio drawdown %.1f%% >= %.1f%%! "
                "Value: $%.2f, Peak: $%.2f, Live starting capital: $%.2f",
                drawdown_pct, CIRCUIT_BREAKER_PCT, portfolio_value,
                _portfolio_peak, _live_initial_capital,
            )
            for bot in _live_bots:
                stop_bot(bot)
            send_circuit_breaker_alert(portfolio_value, drawdown_pct)
            _circuit_breaker_triggered = True
            _last_trigger_time = now
            _save_peak_state()
    elif _circuit_breaker_triggered and drawdown_pct < CIRCUIT_BREAKER_PCT * 0.5:
        _circuit_breaker_triggered = False
        log.info("Circuit breaker reset: drawdown recovered to %.1f%%", drawdown_pct)
        _save_peak_state()


def main() -> None:
    global _capital_refresh_counter

    log.info("Starting Freqtrade metrics exporter on :9090")
    _load_peak_state()
    refresh_live_capital()
    log.info(
        "Circuit breaker: %.0f%% live-portfolio drawdown threshold ($%.2f loss on $%.2f live capital)",
        CIRCUIT_BREAKER_PCT,
        _live_initial_capital * CIRCUIT_BREAKER_PCT / 100,
        _live_initial_capital,
    )
    start_http_server(9090)

    while True:
        log.info("Scraping %d bots (%d live)...", len(BOTS), len(_live_bots))
        total_pnl, live_pnl = scrape_all()
        if total_pnl is not None:
            log.info(
                "Scrape complete. Total P&L: $%.2f, Live P&L: $%.2f. Sleeping %ds.",
                total_pnl, live_pnl or 0.0, SCRAPE_INTERVAL,
            )
            if live_pnl is not None:
                check_circuit_breaker(live_pnl)
        else:
            log.warning("No bots reachable. Sleeping %ds.", SCRAPE_INTERVAL)

        _capital_refresh_counter += 1
        if _capital_refresh_counter >= CAPITAL_REFRESH_EVERY:
            _capital_refresh_counter = 0
            refresh_live_capital()

        time.sleep(SCRAPE_INTERVAL)


if __name__ == "__main__":
    main()
