#!/usr/bin/env python3
"""
Freqtrade Prometheus Metrics Exporter

Scrapes all Freqtrade bot REST APIs and exposes metrics for Prometheus.
Runs as a long-lived process, updating metrics every 60 seconds.
"""

import time
import logging
import requests
from requests.auth import HTTPBasicAuth
from prometheus_client import start_http_server, Gauge, Info

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("ft-exporter")

# ── Bot configuration ────────────────────────────────────────────────
# Inside Docker compose network, all bots listen on internal port 8080.
# We reach them by service name.
BOTS = [
    {"service": "cluchanix",              "strategy": "ClucHAnix"},
    # {"service": "combinedbinhandcluc",    "strategy": "CombinedBinHAndCluc"},  # PAUSED
    {"service": "nasosv5",                "strategy": "NASOSv5"},
    {"service": "elliotv5",              "strategy": "ElliotV5"},
    {"service": "supertrendstrategy",     "strategy": "SupertrendStrategy"},
    {"service": "mastertraderv1",         "strategy": "MasterTraderV1"},
    {"service": "mastertraderai",         "strategy": "MasterTraderAI"},
    # {"service": "nostalgiaforinfinityx6", "strategy": "NostalgiaForInfinityX6"},  # KILLED
]

AUTH = HTTPBasicAuth("freqtrader", "mastertrader")
API_PORT = 8080
SCRAPE_INTERVAL = 60  # seconds

# ── Circuit Breaker ───────────────────────────────────────────────
INITIAL_CAPITAL = 7000.0  # Total across all bots
CIRCUIT_BREAKER_PCT = 10.0  # Trigger at 10% portfolio drawdown ($700)
CIRCUIT_BREAKER_COOLDOWN = 3600  # Don't re-alert for 1 hour after triggering
WEBHOOK_URL = "http://host.docker.internal:8088/webhooks/freqtrade"

_portfolio_peak = INITIAL_CAPITAL  # Track high-water mark
_circuit_breaker_triggered = False
_last_trigger_time = 0.0

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


def fetch_json(url: str, timeout: int = 10) -> dict | None:
    """GET JSON from a Freqtrade API endpoint. Returns None on any error."""
    try:
        resp = requests.get(url, auth=AUTH, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning("Failed to fetch %s: %s", url, exc)
        return None


def scrape_bot(bot: dict) -> float | None:
    """Scrape one bot and update its Prometheus metrics. Returns true P&L or None."""
    base = f"http://{bot['service']}:{API_PORT}/api/v1"
    strategy = bot["strategy"]

    # ── /profit ──────────────────────────────────────────────────
    data = fetch_json(f"{base}/profit")
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
    status_data = fetch_json(f"{base}/status")
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
    bal_data = fetch_json(f"{base}/balance")
    if bal_data:
        balance.labels(strategy=strategy).set(
            bal_data.get("total", 0)
        )

    return bot_true_pnl


def scrape_all() -> float | None:
    """Scrape every configured bot. Returns total portfolio true P&L or None."""
    total_pnl = 0.0
    reachable = 0
    for bot in BOTS:
        try:
            pnl = scrape_bot(bot)
            if pnl is not None:
                total_pnl += pnl
                reachable += 1
        except Exception as exc:
            log.error("Unexpected error scraping %s: %s", bot["strategy"], exc)
    return total_pnl if reachable > 0 else None


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
        f"Portfolio drawdown: {drawdown_pct:.1f}% (threshold: {CIRCUIT_BREAKER_PCT}%)\n"
        f"Portfolio value: ${portfolio_value:,.2f} (initial: ${INITIAL_CAPITAL:,.0f})\n"
        f"Loss: ${INITIAL_CAPITAL - portfolio_value:,.2f}\n\n"
        f"ALL BOTS STOPPED. Manual restart required.\n"
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


def check_circuit_breaker(portfolio_pnl: float) -> None:
    """Check if portfolio drawdown exceeds threshold and stop all bots if so."""
    global _portfolio_peak, _circuit_breaker_triggered, _last_trigger_time

    portfolio_value = INITIAL_CAPITAL + portfolio_pnl

    # Update high-water mark
    if portfolio_value > _portfolio_peak:
        _portfolio_peak = portfolio_value

    # Calculate drawdown from peak
    drawdown_pct = ((_portfolio_peak - portfolio_value) / _portfolio_peak) * 100

    # Update Prometheus gauges
    portfolio_drawdown_pct.set(round(drawdown_pct, 2))
    portfolio_value_total.set(round(portfolio_value, 2))

    if drawdown_pct >= CIRCUIT_BREAKER_PCT:
        now = time.time()
        if not _circuit_breaker_triggered or (now - _last_trigger_time > CIRCUIT_BREAKER_COOLDOWN):
            log.critical(
                "CIRCUIT BREAKER: Portfolio drawdown %.1f%% >= %.1f%% threshold! "
                "Value: $%.2f, Peak: $%.2f",
                drawdown_pct, CIRCUIT_BREAKER_PCT, portfolio_value, _portfolio_peak,
            )
            # Stop all bots
            for bot in BOTS:
                stop_bot(bot)
            # Alert via Telegram
            send_circuit_breaker_alert(portfolio_value, drawdown_pct)
            _circuit_breaker_triggered = True
            _last_trigger_time = now
    elif _circuit_breaker_triggered and drawdown_pct < CIRCUIT_BREAKER_PCT * 0.5:
        # Reset trigger once drawdown recovers below half the threshold
        _circuit_breaker_triggered = False
        log.info("Circuit breaker reset: drawdown recovered to %.1f%%", drawdown_pct)


def main() -> None:
    log.info("Starting Freqtrade metrics exporter on :9090")
    log.info("Circuit breaker: %.0f%% drawdown threshold ($%.0f loss)",
             CIRCUIT_BREAKER_PCT, INITIAL_CAPITAL * CIRCUIT_BREAKER_PCT / 100)
    start_http_server(9090)

    while True:
        log.info("Scraping %d bots...", len(BOTS))
        portfolio_pnl = scrape_all()
        if portfolio_pnl is not None:
            log.info("Scrape complete. Portfolio P&L: $%.2f. Sleeping %ds.",
                     portfolio_pnl, SCRAPE_INTERVAL)
            check_circuit_breaker(portfolio_pnl)
        else:
            log.warning("No bots reachable. Sleeping %ds.", SCRAPE_INTERVAL)
        time.sleep(SCRAPE_INTERVAL)


if __name__ == "__main__":
    main()
