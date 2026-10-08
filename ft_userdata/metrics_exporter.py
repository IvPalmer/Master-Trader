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
import math
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth
from prometheus_client import start_http_server, Gauge, Info

from api_utils import api_get as _api_get_with_retry
from api_utils import auth_candidates_for

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
            # `active` selects autonomous-strategy tooling; receiver-managed
            # bots are marked production_live instead (see bots_config _doc).
            # `monitor` also includes deployed observation bots without
            # opting them into autonomous strategy tooling. Runtime dry_run,
            # not a registry flag, determines live circuit-breaker membership.
            # The exporter must scrape all of these: a live funded bot that is not
            # scraped contributes nothing to the circuit breaker's capital
            # math and cannot be halted by it. KillersScalpV1 — the only
            # leveraged bot in the fleet — sat outside the breaker for exactly
            # this reason.
            if not (info.get("active", True) or info.get("production_live")
                    or info.get("monitor")):
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
                "KillersScalpV1": "ft-killers-scalp",
                "InsidersScalpV1": "ft-insiders-scalp",
                "FundingShortV1": "fundingshortv1",
                # Compose names this service oi-trend-pullback, not
                # oitrendpullback. Without the mapping the exporter resolved a
                # hostname that does not exist, so a LIVE bot silently sat
                # outside the circuit breaker's capital math.
                "OITrendPullbackV1": "oi-trend-pullback",
            }
            service = service_map.get(name, service)
            bots.append({"service": service, "strategy": name,
                         "capital_account": info.get("capital_account") or service,
                         "capital_owner": info.get("capital_owner", False)})
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
    "http://trade-webhook:8088/freqtrade/event",
)
CAPITAL_REFRESH_EVERY = 60  # rescrape /show_config + /balance every N scrapes
PEAK_STATE_FILE = Path(os.environ.get("PEAK_STATE_FILE", "/state/portfolio_peak.json"))

_live_initial_capital = 0.0  # Sum of starting_capital across LIVE bots
_live_bots: list[dict] = []  # Subset of BOTS that report dry_run=False
_capital_refresh_counter = 0
_membership_complete = False

_portfolio_peak = 0.0
# The live-capital base the peak was recorded against. The peak is an ABSOLUTE
# dollar figure (base + pnl), so it is only comparable to a portfolio_value
# computed on the same base. Promoting or demoting a bot changes that base and
# would otherwise read as profit or loss that never happened.
_peak_basis = 0.0
_circuit_breaker_triggered = False
_last_trigger_time = 0.0
# Services whose /stopentry failed during the current breach. Only these are
# retried each cycle; the alert stays on the hourly cooldown.
_pending_halts: set[str] = set()
_equity_basis = "legacy"
_account_transfer_total = 0.0
_account_scope: dict[str, dict] | None = None
ACCOUNT_STATE_FILE = PEAK_STATE_FILE.with_name("account_health.json")
GATEWAY_URL = os.environ.get("HL_GATEWAY_URL", "http://hl-gateway:8080")


def _load_peak_state() -> None:
    """Restore high-water mark from disk so a restart mid-drawdown doesn't
    erase the real peak. Without this, _portfolio_peak resets every restart
    and the breaker silently shifts its threshold downward."""
    global _portfolio_peak, _peak_basis, _circuit_breaker_triggered, _last_trigger_time, _equity_basis, _account_transfer_total, _pending_halts, _account_scope
    try:
        if PEAK_STATE_FILE.exists():
            with open(PEAK_STATE_FILE) as f:
                state = json.load(f)
            _portfolio_peak = float(state.get("peak", 0.0))
            _peak_basis = float(state.get("peak_basis", 0.0))
            _circuit_breaker_triggered = bool(state.get("triggered", False))
            _last_trigger_time = float(state.get("last_trigger_time", 0.0))
            _equity_basis = state.get("equity_basis", "legacy")
            _account_transfer_total = float(state.get("account_transfer_total", 0))
            _pending_halts = set(state.get("pending_halts", []))
            scope = state.get("accounts")
            _account_scope = None if scope is None else {
                name: {"equity": float(a["equity"]), "transfers": float(a["transfers"])}
                for name, a in scope.items()}
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
                "peak_basis": _peak_basis,
                "triggered": _circuit_breaker_triggered,
                "last_trigger_time": _last_trigger_time,
                "saved_at": time.time(),
                "equity_basis": _equity_basis,
                "account_transfer_total": _account_transfer_total,
                "pending_halts": sorted(_pending_halts),
                "accounts": _account_scope,
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
    "Observed equity summed once per live exchange account in USD stablecoin units",
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
    global _live_bots, _live_initial_capital, _membership_complete
    live = []
    _membership_complete = True
    for bot in BOTS:
        meta = fetch_bot_meta(bot["service"])
        if meta is None:
            _membership_complete = False
            log.warning("Mode unavailable for %s; preserving membership, freezing account checks", bot["strategy"])
            live.extend(b for b in _live_bots if b["service"] == bot["service"])
            continue
        if meta["dry_run"]:
            log.debug("Excluding %s from breaker (dry_run)", bot["strategy"])
            continue
        if not math.isfinite(meta["starting_capital"]):
            _membership_complete = False
            meta["starting_capital"] = 0
        live.append({**bot, "starting_capital": meta["starting_capital"]})

    _live_bots = live
    _live_initial_capital = account_starting_capital(live)
    log.info(
        "Circuit breaker capital refreshed: %d live bots, $%.2f total starting capital",
        len(_live_bots), _live_initial_capital,
    )
    for account, strategies in unvalued_live_accounts(live).items():
        log.error(
            "CONFIGURATION ERROR: live %s on account %s, which has no valuation adapter. "
            "It is excluded from the circuit breaker's drawdown; value the account or "
            "return the bot to dry-run.", ", ".join(strategies), account,
        )


# Accounts the exporter can value from a verified source. A live bot on any
# other account is a configuration error, not a transient gap: it cannot close
# on the next scrape, so it must not freeze the breaker for every account (#104).
VALUED_ACCOUNTS = frozenset({"binance-spot", "hyperliquid-killers"})


def unvalued_live_accounts(live_bots: list[dict]) -> dict[str, list[str]]:
    """Live accounts without a valuation adapter, with the strategies on each."""
    unvalued: dict[str, list[str]] = {}
    for bot in live_bots:
        account = bot.get("capital_account") or bot["service"]
        if account not in VALUED_ACCOUNTS:
            unvalued.setdefault(account, []).append(bot.get("strategy", bot["service"]))
    return unvalued


def account_starting_capital(live_bots: list[dict]) -> float:
    """Diagnostic baseline only; the breaker uses observed account equity.

    Shared accounts elect an explicit representative. Neither the smallest
    nor largest balance establishes chronology or account ownership.
    """
    groups = {}
    for bot in live_bots:
        groups.setdefault(bot.get("capital_account") or bot["service"], []).append(bot)
    total = 0.0
    for members in groups.values():
        owners = [b for b in members if b.get("capital_owner")]
        if len(members) > 1 and len(owners) != 1:
            raise ValueError("shared capital account needs exactly one representative")
        total += (owners[0] if owners else members[0])["starting_capital"]
    return total


def observe_accounts() -> dict:
    """Actual wallet marks, once per live account. Partial data never marks equity."""
    result = {"observed_at": time.time(), "complete": _membership_complete,
              "accounts": {}, "errors": [], "gateway": None}
    try:
        response = requests.get(GATEWAY_URL + "/healthz", timeout=5)
        response.raise_for_status()
        result["gateway"] = response.json()
    except (requests.RequestException, ValueError):
        result["errors"].append("Hyperliquid request telemetry unavailable")
    groups = {}
    transfers = {}
    for bot in _live_bots:
        groups.setdefault(bot.get("capital_account") or bot["service"], []).append(bot)
    unvalued = unvalued_live_accounts(_live_bots)
    # The breaker's scope: every live account it can value.
    covered = [account for account in groups if account not in unvalued]
    for account in covered:
        members = groups[account]
        try:
            owners = [b for b in members if b.get("capital_owner")]
            if len(members) > 1 and len(owners) != 1:
                raise ValueError("ambiguous account representative")
            owner = owners[0] if owners else members[0]
            if account == "hyperliquid-killers":
                response = requests.get(GATEWAY_URL + "/account/killers", timeout=20)
                response.raise_for_status()
                mark = response.json()
            elif account == "binance-spot":
                bal = fetch_json(owner["service"], "balance")
                if not isinstance(bal, dict):
                    raise ValueError("balance unavailable")
                mark = {"equity": float(bal["total"]), "observed_at": time.time(),
                        "free": sum(float(c.get("free") or 0) for c in bal.get("currencies", [])
                                    if c.get("currency") == bal.get("stake")),
                        "margin": None, "notional": None}
            else:
                raise ValueError("no verified account valuation adapter")
            if not math.isfinite(mark["equity"]) or mark["equity"] < 0:
                raise ValueError("invalid equity")
            if time.time() - mark["observed_at"] > 90:
                raise ValueError("stale account observation")
            result["accounts"][account] = mark
        except (KeyError, TypeError, ValueError, requests.RequestException):
            result["complete"] = False
            result["errors"].append(f"Account equity unavailable: {account}")
    try:
        ledger = json.loads(Path(__file__).with_name("account_transfers.json").read_text())["transfers"]
        ids = [row["id"] for row in ledger]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate transfer")
        transfers = {account: 0.0 for account in covered}
        for row in ledger:
            if row["account"] in transfers:
                transfers[row["account"]] += float(row["amount"])
        result["net_transfers"] = sum(transfers.values())
        if not math.isfinite(result["net_transfers"]):
            raise ValueError("invalid transfer")
    except (OSError, ValueError, KeyError, TypeError):
        result["complete"] = False
        result["errors"].append("External cash-flow ledger unavailable or invalid")
    # A transient failure on any covered account still freezes the breaker: a
    # partial total would fake a drawdown. An account with no adapter was never
    # part of the total, so excluding it changes nothing the peak was built on.
    result["breaker_complete"] = result["complete"] and bool(covered)
    result["breaker_equity"] = (sum(result["accounts"][a]["equity"] for a in covered)
                                if result["breaker_complete"] else None)
    result["breaker_accounts"] = ({a: {"equity": result["accounts"][a]["equity"], "transfers": transfers[a]}
                                   for a in covered} if result["breaker_complete"] else None)
    if unvalued:
        result["complete"] = False  # the portfolio total itself is not observed
        result["unvalued_accounts"] = unvalued
        for account, strategies in unvalued.items():
            result["errors"].append(
                f"Live account {account} ({', '.join(strategies)}) has no valuation "
                "adapter; excluded from the circuit breaker")
    result["equity"] = (sum(a["equity"] for a in result["accounts"].values())
                        if result["complete"] and groups else None)
    if not _membership_complete:
        result["errors"].append("Live account membership is not fully observed")
    return result


def save_account_health(observation):
    observation["breaker_triggered"] = _circuit_breaker_triggered
    observation["peak"] = _portfolio_peak
    if observation.get("breaker_equity") is not None and _portfolio_peak > 0:
        observation["drawdown_pct"] = max(0, (_portfolio_peak - observation["breaker_equity"]) / _portfolio_peak * 100)
    try:
        ACCOUNT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = ACCOUNT_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(observation))
        os.replace(tmp, ACCOUNT_STATE_FILE)
    except OSError:
        log.exception("Could not persist account health")


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
        bot_up.labels(strategy=strategy).set(0)
        return None  # missing open marks must not silently become zero P&L

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
    live_seen = set()
    live_services = {b["service"] for b in _live_bots}
    for bot in BOTS:
        try:
            pnl = scrape_bot(bot)
            if pnl is not None:
                total_pnl += pnl
                reachable += 1
                if bot["service"] in live_services:
                    live_pnl += pnl
                    live_seen.add(bot["service"])
        except Exception as exc:
            log.error("Unexpected error scraping %s: %s", bot["strategy"], exc)
    if reachable == 0:
        return None, None
    return total_pnl, live_pnl if live_seen == live_services else None


def stop_bot(bot: dict) -> bool:
    """Stop a bot via the Freqtrade API."""
    base = f"http://{bot['service']}:{API_PORT}/api/v1"
    # Same credential resolution the scrape path uses: per-bot first, shared
    # next. The circuit breaker must not be the one call that 401s because a
    # bot was moved onto its own credentials.
    candidates = auth_candidates_for(bot["service"]) or (AUTH,)
    try:
        resp = None
        for auth in candidates:
            resp = requests.post(f"{base}/stopentry", auth=auth, timeout=10)
            if resp.status_code != 401:
                break
        if resp is not None and resp.status_code == 200:
            log.info("Stopped new entries for %s; exits remain managed", bot["strategy"])
            return True
        log.warning("Failed to stop %s: HTTP %s", bot["strategy"],
                    resp.status_code if resp is not None else "no-credentials")
        return False
    except Exception as exc:
        log.error("Error stopping %s: %s", bot["strategy"], exc)
        return False


def send_circuit_breaker_alert(portfolio_value: float, drawdown_pct: float) -> None:
    """Send emergency alert via webhook to Telegram."""
    message = (
        f"CIRCUIT BREAKER: live account drawdown {drawdown_pct:.1f}%\n"
        f"Account equity: ${portfolio_value:,.2f}; peak: ${_portfolio_peak:,.2f}\n"
        f"Entry halt requested for {', '.join(b['strategy'] for b in _live_bots)}. "
        f"Exits remain managed. Unreachable bots require verification.\n"
        f"Review positions and account data before resuming entries."
    )
    try:
        payload = {"type": "status", "bot_name": "fleet-circuit-breaker", "status": message}
        # trade-webhook's shared secret (#97); unset sends no header.
        token = os.environ.get("TRADE_WEBHOOK_NOTIFY_TOKEN", "").strip()
        headers = {"X-Notify-Token": token} if token else {}
        resp = requests.post(WEBHOOK_URL, json=payload, headers=headers, timeout=10)
        if resp.status_code in (200, 201, 204):
            log.info("Circuit breaker alert sent to Telegram")
        else:
            log.warning("Alert webhook returned HTTP %d", resp.status_code)
    except Exception as exc:
        log.error("Failed to send circuit breaker alert: %s", exc)


# ── Sustained-condition alerts ────────────────────────────────────
# The exporter probes the gateway from outside its failure domain every cycle.
# Without a push, an outage that starts after the last signal stays silent
# until the next signal fails or someone opens the dashboard (#94).
GATEWAY_DOWN_ALERT_AFTER = 180       # /healthz unreachable or malformed
GATEWAY_DEGRADED_ALERT_AFTER = 900   # /healthz reports request failures
# trade-webhook truncates "WARN <message>" to 200 characters before Telegram.
OPS_ALERT_MAX_CHARS = 190


def send_ops_alert(bot_name: str, message: str, kind: str = "warning") -> bool:
    """Push one operator message through trade-webhook to Telegram.

    Returns True only when the webhook accepted it and did not report a failed
    Telegram send, so the caller can retry an undelivered alert next cycle.
    """
    try:
        resp = requests.post(WEBHOOK_URL, json={"type": kind, "bot_name": bot_name,
                                                "status": message[:OPS_ALERT_MAX_CHARS]},
                             timeout=10)
    except requests.RequestException as exc:
        log.error("Failed to send %s alert: %s", bot_name, exc)
        return False
    if resp.status_code not in (200, 201, 204):
        log.warning("%s alert webhook returned HTTP %d", bot_name, resp.status_code)
        return False
    try:
        delivered = resp.json().get("telegram_sent") is not False
    except (ValueError, AttributeError):
        delivered = True
    if not delivered:
        log.warning("%s alert accepted by webhook but not sent to Telegram", bot_name)
    return delivered


class SustainedAlert:
    """One push when a condition persists past a window, one when it clears.

    An episode starts at the first bad observation. Undelivered messages are
    retried on the next update instead of being marked as sent.
    """

    def __init__(self, bot_name: str):
        self.bot_name = bot_name
        self.since: float | None = None
        self.alerted = False

    def update(self, detail: str | None, now: float, after: float) -> None:
        if detail:
            if self.since is None:
                self.since = now
            if not self.alerted and now - self.since >= after:
                minutes = int((now - self.since) // 60)
                self.alerted = send_ops_alert(self.bot_name, detail.format(minutes=minutes))
            return
        if self.alerted:
            minutes = int((now - self.since) // 60) if self.since is not None else 0
            if not send_ops_alert(self.bot_name, f"Recovered after {minutes} min.", "status"):
                return
            self.alerted = False
        self.since = None


GATEWAY_ALERT = SustainedAlert("fleet-hl-gateway")


def watch_gateway(gateway, now: float) -> None:
    """Alert on a sustained hl-gateway outage or request failure, and on recovery."""
    if not isinstance(gateway, dict):
        GATEWAY_ALERT.update(
            "Hyperliquid gateway unreachable for {minutes} min: HL bots cannot place, "
            "move or cancel orders (exits, stop moves, TP ladder). Check ft-hl-gateway.",
            now, GATEWAY_DOWN_ALERT_AFTER)
    elif gateway.get("status") != "ok":
        GATEWAY_ALERT.update(
            f"Hyperliquid gateway failing requests for {{minutes}} min "
            f"({gateway.get('faults', '?')} in last 5 min): HL orders and exits may not "
            "reach the venue. Check ft-hl-gateway.",
            now, GATEWAY_DEGRADED_ALERT_AFTER)
    else:
        GATEWAY_ALERT.update(None, now, 0)


# #104: a frozen or partial breaker used to show only as a dashboard warning.
BREAKER_STALL_ALERT_AFTER = 900
BREAKER_STALL_ALERT = SustainedAlert("fleet-breaker-watch")
COVERAGE_ALERT = SustainedAlert("fleet-breaker-coverage")


def _literal(text: str) -> str:
    """Escape observed text for SustainedAlert's {minutes} template."""
    return text.replace("{", "{{").replace("}", "}}")


def watch_breaker(observation: dict, evaluated: bool, now: float) -> None:
    """Page when a live account sits outside the breaker, and when the breaker
    has not evaluated for a sustained window while live or unknown-mode bots exist."""
    unvalued = observation.get("unvalued_accounts") or {}
    COVERAGE_ALERT.update(
        _literal("Live bot outside the circuit breaker: "
                 + "; ".join(f"{a} ({', '.join(s)})" for a, s in unvalued.items())
                 + " has no valuation adapter. Value the account or return the bot to dry-run.")
        if unvalued else None, now, 0)
    stalled = (bool(_live_bots) or not _membership_complete) and not evaluated
    reason = "; ".join(observation.get("errors") or []) or "no complete account observation"
    BREAKER_STALL_ALERT.update(
        "Circuit breaker not evaluated for {minutes} min; the drawdown halt is not running. "
        + _literal(reason) if stalled else None,
        now, BREAKER_STALL_ALERT_AFTER)


def _rebase_account_scope(accounts: dict[str, dict]) -> None:
    """Shift the peak so an account entering or leaving scope moves dollar drawdown by zero."""
    global _portfolio_peak, _account_scope, _account_transfer_total
    transfer_total = sum(a["transfers"] for a in accounts.values())
    if _account_scope is None:
        shift = transfer_total - _account_transfer_total
    else:
        shift = -sum(prev["equity"] for name, prev in _account_scope.items() if name not in accounts)
        for name, current in accounts.items():
            prev = _account_scope.get(name)
            shift += current["equity"] if prev is None else current["transfers"] - prev["transfers"]
        left = sorted(set(_account_scope) - set(accounts))
        entered = sorted(set(accounts) - set(_account_scope))
        if left or entered:
            log.info("Breaker scope changed (left %s, entered %s); shifting peak $%.2f -> $%.2f",
                     left or "none", entered or "none", _portfolio_peak, max(0, _portfolio_peak + shift))
    if shift:
        _portfolio_peak = max(0, _portfolio_peak + shift)
    _account_scope = {name: {"equity": a["equity"], "transfers": a["transfers"]} for name, a in accounts.items()}
    _account_transfer_total = transfer_total
    _save_peak_state()


def check_circuit_breaker(live_pnl: float, accounts: dict[str, dict] | None = None) -> None:
    """Check if LIVE portfolio drawdown exceeds threshold and stop LIVE bots if so.

    Inputs are scoped to live (non-dry-run) bots only. The dry-run sleeve has
    no real money and must not influence the breaker.
    """
    global _portfolio_peak, _peak_basis, _circuit_breaker_triggered, _last_trigger_time, _equity_basis, _pending_halts, _account_scope

    account_equity = None if accounts is None else sum(a["equity"] for a in accounts.values())
    if not _live_bots or (account_equity is None and _live_initial_capital <= 0):
        # No live bots configured — breaker is a no-op. Don't update Prometheus
        # gauges so a stale 'all good' signal doesn't show on Grafana.
        return

    portfolio_value = _live_initial_capital + live_pnl if account_equity is None else account_equity
    if not math.isfinite(portfolio_value) or portfolio_value < 0:
        return
    if accounts is not None:
        if _equity_basis != "accounts-v1":
            # Preserve the previously measured dollar drawdown at migration;
            # changing valuation must not erase an existing loss or trip the
            # breaker because the old margin estimate was wrong.
            legacy_value = _peak_basis + live_pnl
            prior_drawdown = max(0, _portfolio_peak - legacy_value) if _portfolio_peak else 0
            _portfolio_peak = portfolio_value + prior_drawdown
            _equity_basis = "accounts-v1"
            _account_scope = {name: dict(a) for name, a in accounts.items()}
            log.info("Migrated to actual account equity; retained $%.2f drawdown", prior_drawdown)
        _rebase_account_scope(accounts)

    # Rebase the peak when the live set changes. On 2026-08-30 22:00 the peak
    # stood at $254.96 from a three-live-bot fleet; demoting FundingFadeV1 to
    # dry-run dropped the base to $165.53, and the breaker read the $89
    # difference as a 35% drawdown and stopped BOTH remaining live bots —
    # while total P&L was -$0.11. It halted a bot holding an open leveraged
    # position with no exchange-resident stop, for fifteen hours.
    #
    # Shifting the peak by exactly the capital that entered or left keeps the
    # comparison denominated in the same base, so a composition change moves
    # drawdown by zero. Only real P&L can move it.
    if account_equity is not None:
        pass  # actual marks do not rebase when a bot reports a different starting balance
    elif _peak_basis <= 0:
        _peak_basis = _live_initial_capital
    elif abs(_live_initial_capital - _peak_basis) > 0.01:
        delta = _live_initial_capital - _peak_basis
        log.info(
            "Live capital base changed $%.2f -> $%.2f; rebasing breaker peak "
            "$%.2f -> $%.2f (composition change, not P&L)",
            _peak_basis, _live_initial_capital,
            _portfolio_peak, _portfolio_peak + delta,
        )
        _portfolio_peak += delta
        _peak_basis = _live_initial_capital
        _save_peak_state()

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
            _pending_halts = {bot["service"] for bot in _live_bots if not stop_bot(bot)}
            send_circuit_breaker_alert(portfolio_value, drawdown_pct)
            _circuit_breaker_triggered = True
            _last_trigger_time = now
            _save_peak_state()
        elif _pending_halts:
            # Retry only the halts that failed. Re-stopping every bot and
            # re-sending the alert each 60s cycle would page indefinitely
            # whenever one bot was unreachable.
            retry = [bot for bot in _live_bots if bot["service"] in _pending_halts]
            _pending_halts = {bot["service"] for bot in retry if not stop_bot(bot)}
            if _pending_halts:
                log.warning("Entry halt still failing for %s", ", ".join(sorted(_pending_halts)))
            _save_peak_state()
    elif _circuit_breaker_triggered and drawdown_pct < CIRCUIT_BREAKER_PCT * 0.5:
        _circuit_breaker_triggered = False
        _pending_halts = set()
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
        observation = observe_accounts()
        watch_gateway(observation["gateway"], time.time())
        if live_pnl is None:
            observation["errors"].append("Live bot status or P&L observation unavailable")
        evaluated = observation["breaker_complete"] and (live_pnl is not None or _equity_basis == "accounts-v1")
        if evaluated:
            check_circuit_breaker(live_pnl or 0.0, observation["breaker_accounts"])
        watch_breaker(observation, evaluated, time.time())
        save_account_health(observation)
        if total_pnl is None:
            log.warning("No bots reachable. Sleeping %ds.", SCRAPE_INTERVAL)

        _capital_refresh_counter += 1
        if not _membership_complete or _capital_refresh_counter >= CAPITAL_REFRESH_EVERY:
            _capital_refresh_counter = 0
            refresh_live_capital()

        time.sleep(SCRAPE_INTERVAL)


if __name__ == "__main__":
    main()
