"""Runtime membership and emergency-alert regressions for the deployed fleet."""

import importlib.util
import json
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FT_DIR = ROOT / "ft_userdata"


@pytest.fixture
def exporter(monkeypatch):
    # Metrics are write-only sinks in these tests. Keep the control-path
    # checks runnable without installing Prometheus or binding a server port.
    class Gauge:
        def __init__(self, *args, **kwargs):
            pass

        def labels(self, *args, **kwargs):
            return self

        def set(self, *args, **kwargs):
            pass

    prometheus = types.ModuleType("prometheus_client")
    prometheus.Gauge = prometheus.Info = Gauge
    prometheus.start_http_server = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "prometheus_client", prometheus)
    monkeypatch.syspath_prepend(str(FT_DIR))
    monkeypatch.delenv("CIRCUIT_BREAKER_WEBHOOK_URL", raising=False)
    spec = importlib.util.spec_from_file_location(
        "exporter_reliability_under_test", FT_DIR / "metrics_exporter.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exporter_covers_every_deployed_trading_service(exporter):
    yaml = pytest.importorskip("yaml")
    compose = yaml.safe_load((FT_DIR / "docker-compose.prod.yml").read_text())
    trading_services = {
        name for name, service in compose["services"].items()
        if "guard_db_mode.py --config" in str(service.get("entrypoint", ""))
    }
    assert {bot["service"] for bot in exporter.BOTS} == trading_services

    registry = json.loads((FT_DIR / "bots_config.json").read_text())["bots"]
    short = registry["ShortKeltnerV2HL"]
    assert short["active"] is False, "monitoring must not enable autonomous tooling"
    assert short["port"] == 8103


def test_stopped_retired_insiders_bot_does_not_freeze_breaker_membership(exporter, monkeypatch):
    """#216: ft-insiders-scalp is stopped. While the registry still listed it as
    production_live, its unanswered /show_config made refresh_live_capital mark
    membership incomplete, which freezes the breaker for every account."""
    assert "ft-insiders-scalp" not in {bot["service"] for bot in exporter.BOTS}

    def meta(service):
        return None if service == "ft-insiders-scalp" else {"dry_run": True, "starting_capital": 0.0}

    monkeypatch.setattr(exporter, "fetch_bot_meta", meta)
    exporter.refresh_live_capital()
    assert exporter._membership_complete is True


@pytest.mark.parametrize("dry_run", [True, False])
def test_short_keltner_breaker_membership_uses_runtime_mode(exporter, monkeypatch, dry_run):
    bot = next(bot for bot in exporter.BOTS if bot["strategy"] == "ShortKeltnerV2HL")
    exporter.BOTS = [bot]
    calls = []

    def fetch(service, endpoint):
        calls.append((service, endpoint))
        assert service == "ft-short-keltner-hl-live"
        if endpoint == "show_config":
            return {"dry_run": dry_run}
        assert endpoint == "balance"
        return {"starting_capital": 40.0}

    monkeypatch.setattr(exporter, "fetch_json", fetch)
    exporter.refresh_live_capital()
    assert ("ft-short-keltner-hl-live", "show_config") in calls
    assert exporter._live_initial_capital == (0.0 if dry_run else 40.0)
    assert [entry["service"] for entry in exporter._live_bots] == (
        [] if dry_run else ["ft-short-keltner-hl-live"]
    )

    monkeypatch.setattr(exporter, "scrape_bot", lambda bot: -7.0)
    total_pnl, live_pnl = exporter.scrape_all()
    assert total_pnl == -7.0, "observation P&L remains available to metrics"
    assert live_pnl == (0.0 if dry_run else -7.0)


def test_exporter_attribution_corrects_hl_stop_but_breaker_return_stays_raw(exporter, monkeypatch):
    class Sink:
        def __init__(self):
            self.value = None
        def labels(self, **_kwargs):
            return self
        def set(self, value):
            self.value = value

    for name in (
        "profit_total", "profit_total_raw", "profit_pct", "trades_total", "drawdown",
        "win_rate", "trades_open", "unrealized_pnl", "true_pnl", "balance", "bot_up",
        "hyperliquid_fill_mismatches", "hyperliquid_overbooked_stops",
        "hyperliquid_fill_reconciliation_up",
    ):
        monkeypatch.setattr(exporter, name, Sink())
    bot = {"service": "ft-killers-scalp", "strategy": "KillersScalpV1",
           "venue": "hyperliquid", "wallet_env": "TEST_HL_WALLET"}
    trade = {
        "close_date": "2026-10-08 15:23:00", "open_rate": 11.24,
        "fee_open": 0.0004, "fee_close": 0.00015, "profit_abs": -10.04074610245,
        "orders": [{"order_id": "avax-stop-16", "ft_order_side": "stoploss",
                    "is_open": False, "filled": 8.33}],
    }

    def fetch(_service, endpoint):
        if endpoint == "profit":
            return {"profit_closed_coin": -10.04074610245, "closed_trade_count": 1,
                    "winning_trades": 0, "losing_trades": 1}
        if endpoint.startswith("trades"):
            return {"trades": [trade]}
        if endpoint == "status":
            return []
        if endpoint == "balance":
            return {"total": 90}
        raise AssertionError(endpoint)

    monkeypatch.setattr(exporter, "fetch_json", fetch)
    monkeypatch.setattr(exporter, "fetch_hyperliquid_user_fills", lambda _bot: [
        {"oid": "avax-stop-16", "sz": "7.29", "px": "9.9851"}
    ])

    breaker_pnl = exporter.scrape_bot(bot)

    assert exporter.profit_total.value == pytest.approx(-8.72941658685)
    assert exporter.profit_total_raw.value == pytest.approx(-10.04074610245)
    assert exporter.true_pnl.value == pytest.approx(-8.73)
    assert exporter.hyperliquid_fill_mismatches.value == 1
    assert exporter.hyperliquid_overbooked_stops.value == 1
    assert breaker_pnl == pytest.approx(-10.04074610245)


def test_emergency_alert_matches_trade_webhook_json_contract(exporter, monkeypatch):
    captured = []

    def post(url, **kwargs):
        captured.append((url, kwargs))
        return types.SimpleNamespace(status_code=200)

    monkeypatch.setattr(exporter.requests, "post", post)
    exporter._live_initial_capital = 100.0
    exporter._live_bots = [{"strategy": "ExampleBot", "service": "example"}]
    exporter.send_circuit_breaker_alert(85.0, 15.0)

    assert len(captured) == 1
    url, kwargs = captured[0]
    assert url == "http://trade-webhook:8088/freqtrade/event"
    assert "data" not in kwargs, "the receiving route rejects form bodies"
    assert kwargs["timeout"] == 10
    payload = kwargs["json"]
    assert payload["type"] == "status"
    assert payload["bot_name"] == "fleet-circuit-breaker"
    assert "15.0%" in payload["status"]
    assert "ExampleBot" in payload["status"]
    assert json.loads(json.dumps(payload)) == payload


def test_shared_wallet_counts_once_in_breaker_capital(exporter):
    """FundingFadeV1 and KeltnerBounceV1 trade one Binance wallet. Each
    reports the whole wallet as starting_capital; the breaker must not add
    them twice, and the earliest snapshot is the account's base."""
    live = [
        {"service": "fundingfadev1", "strategy": "FundingFadeV1",
         "capital_account": "binance-spot", "capital_owner": True, "starting_capital": 89.3788},
        {"service": "keltnerbouncev1", "strategy": "KeltnerBounceV1",
         "capital_account": "binance-spot", "starting_capital": 90.3356},
        {"service": "ft-killers-scalp", "strategy": "KillersScalpV1",
         "capital_account": "hyperliquid-killers", "starting_capital": 84.5705},
    ]
    assert exporter.account_starting_capital(live) == pytest.approx(89.3788 + 84.5705)
    # A bot without a declared account is its own account.
    assert exporter.account_starting_capital(
        [{"service": "a", "strategy": "A", "starting_capital": 10.0},
         {"service": "b", "strategy": "B", "starting_capital": 10.0}]
    ) == pytest.approx(20.0)


def test_registry_declares_the_shared_binance_wallet():
    data = json.loads((FT_DIR / "bots_config.json").read_text())["bots"]
    shared = {name for name, info in data.items() if info.get("capital_account") == "binance-spot"}
    assert {"FundingFadeV1", "KeltnerBounceV1"} <= shared
    assert data["KillersScalpV1"].get("capital_account") != "binance-spot"


def test_shared_baseline_requires_an_owner_not_minimum(exporter):
    bots = [{'service': 'a', 'capital_account': 'shared', 'starting_capital': 100, 'capital_owner': True},
            {'service': 'b', 'capital_account': 'shared', 'starting_capital': 80}]
    assert exporter.account_starting_capital(bots) == 100
    bots[0].pop('capital_owner')
    with pytest.raises(ValueError):
        exporter.account_starting_capital(bots)


def test_incomplete_live_pnl_is_not_a_zero_loss(exporter, monkeypatch):
    exporter.BOTS = exporter._live_bots = [{'service': 'a', 'strategy': 'A'}, {'service': 'b', 'strategy': 'B'}]
    monkeypatch.setattr(exporter, 'scrape_bot', lambda b: 2 if b['service'] == 'a' else None)
    assert exporter.scrape_all() == (2, None)


def test_account_equity_deduplicates_shared_wallet_and_uses_venue_margin(exporter, monkeypatch):
    exporter._membership_complete = True
    exporter._live_bots = [
        {'service': 'a', 'capital_account': 'binance-spot', 'capital_owner': True},
        {'service': 'b', 'capital_account': 'binance-spot'},
        {'service': 'killers', 'capital_account': 'hyperliquid-killers'}]
    seen = []
    def fetch(service, endpoint):
        seen.append(service)
        return {'total': 90, 'total_bot': 40, 'stake': 'USDT', 'currencies': [{'currency': 'USDT', 'free': 60}]}
    monkeypatch.setattr(exporter, 'fetch_json', fetch)
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'equity': 101, 'free': 24, 'margin': 77, 'observed_at': exporter.time.time()}
    monkeypatch.setattr(exporter.requests, 'get', lambda *a, **k: Response())
    result = exporter.observe_accounts()
    assert result['complete']
    assert result['equity'] == 191
    assert seen == ['a']
    assert result['accounts']['hyperliquid-killers']['margin'] == 77
    monkeypatch.setattr(exporter, 'fetch_json', lambda *a: None)
    assert exporter.observe_accounts()['equity'] is None


def test_missing_membership_does_not_drop_a_live_bot(exporter, monkeypatch):
    bot = {'service': 'a', 'strategy': 'A', 'starting_capital': 100}
    exporter.BOTS = [bot]
    exporter._live_bots = [bot]
    monkeypatch.setattr(exporter, 'fetch_bot_meta', lambda *a: None)
    exporter.refresh_live_capital()
    assert exporter._live_bots == [bot]
    assert exporter._membership_complete is False


def test_account_migration_preserves_drawdown_and_ignores_changing_bot_base(exporter, monkeypatch):
    exporter._live_initial_capital = exporter._peak_basis = 170
    exporter._live_bots = [{'service': 'a', 'strategy': 'A'}]
    exporter._portfolio_peak = 180
    monkeypatch.setattr(exporter, '_save_peak_state', lambda: None)
    exporter.check_circuit_breaker(5, _binance(195))
    assert exporter._portfolio_peak == 200  # preserve the old $5 drawdown
    exporter._live_initial_capital = 120  # new position altered FT's margin estimate
    exporter.check_circuit_breaker(5, _binance(195))
    assert exporter._portfolio_peak == 200


def test_entry_halt_keeps_exit_management_running(exporter, monkeypatch):
    urls = []
    monkeypatch.setattr(exporter, 'auth_candidates_for', lambda *a: [object()])
    monkeypatch.setattr(exporter.requests, 'post', lambda url, **k: (urls.append(url) or types.SimpleNamespace(status_code=200)))
    assert exporter.stop_bot({'service': 'a', 'strategy': 'A'})
    assert urls == ['http://a:8080/api/v1/stopentry']


def test_external_cash_flows_preserve_dollar_drawdown(exporter, monkeypatch):
    exporter._live_initial_capital = 100
    exporter._live_bots = [{'service': 'a'}]
    exporter._equity_basis = 'accounts-v1'
    exporter._portfolio_peak = 100
    monkeypatch.setattr(exporter, '_save_peak_state', lambda: None)
    exporter.check_circuit_breaker(0, _binance(195, transfers=100))
    assert exporter._portfolio_peak == 200
    exporter.check_circuit_breaker(0, _binance(145, transfers=50))
    assert exporter._portfolio_peak == 150


def _binance(equity, transfers=0.0):
    return {"binance-spot": {"equity": equity, "transfers": transfers}}


def _gateway_ok(exporter, monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'status': 'ok', 'observed_at': exporter.time.time()}
    monkeypatch.setattr(exporter.requests, 'get', lambda *a, **k: Response())


def test_all_dry_run_fleet_is_fully_observed_with_no_equity(exporter, monkeypatch):
    exporter._membership_complete = True
    exporter._live_bots = []
    _gateway_ok(exporter, monkeypatch)
    result = exporter.observe_accounts()
    assert result['complete'] is True
    assert result['accounts'] == {}
    assert result['equity'] is None
    assert result['errors'] == []


def test_unobserved_membership_with_no_live_bots_stays_incomplete(exporter, monkeypatch):
    exporter._membership_complete = False
    exporter._live_bots = []
    _gateway_ok(exporter, monkeypatch)
    result = exporter.observe_accounts()
    assert result['complete'] is False
    assert result['equity'] is None
    assert 'Live account membership is not fully observed' in result['errors']


def test_health_with_no_equity_keeps_peak_without_drawdown(exporter, monkeypatch, tmp_path):
    monkeypatch.setattr(exporter, 'ACCOUNT_STATE_FILE', tmp_path / 'account_health.json')
    exporter._portfolio_peak = 120.0
    observation = {'complete': True, 'equity': None, 'accounts': {}, 'errors': []}
    exporter.save_account_health(observation)
    saved = json.loads((tmp_path / 'account_health.json').read_text())
    assert saved['peak'] == 120.0
    assert 'drawdown_pct' not in saved


class _Webhook:
    """Captures trade-webhook posts; `replies` scripts (status, telegram_sent)."""

    def __init__(self, replies=()):
        self.posts = []
        self.replies = list(replies)

    def __call__(self, url, **kwargs):
        self.posts.append((url, kwargs))
        status, sent = self.replies.pop(0) if self.replies else (200, True)
        return types.SimpleNamespace(status_code=status, json=lambda: {"ok": True, "telegram_sent": sent})

    def messages(self):
        return [(k["json"]["type"], k["json"]["bot_name"], k["json"]["status"]) for _, k in self.posts]


def test_gateway_outage_alerts_once_after_window_and_once_on_recovery(exporter, monkeypatch):
    webhook = _Webhook()
    monkeypatch.setattr(exporter.requests, "post", webhook)
    for t in (0, 60, 120):
        exporter.watch_gateway(None, 1000 + t)
    assert webhook.posts == [], "a short blip must not page the operator"
    exporter.watch_gateway(None, 1180)
    exporter.watch_gateway(None, 1240)
    exporter.watch_gateway(None, 1300)
    assert len(webhook.posts) == 1, "one alert per outage, not one per cycle"
    kind, bot, message = webhook.messages()[0]
    assert (kind, bot) == ("warning", "fleet-hl-gateway")
    assert "unreachable for 3 min" in message
    assert len("WARN " + message) <= 200, "trade-webhook truncates at 200 chars"
    assert webhook.posts[0][0] == "http://trade-webhook:8088/freqtrade/event"

    exporter.watch_gateway({"status": "ok", "faults": 0}, 1360)
    assert webhook.messages()[1] == ("status", "fleet-hl-gateway", "Recovered after 6 min.")
    exporter.watch_gateway({"status": "ok", "faults": 0}, 1420)
    assert len(webhook.posts) == 2

    # The next outage is a new episode with its own window.
    exporter.watch_gateway(None, 2000)
    exporter.watch_gateway(None, 2100)
    assert len(webhook.posts) == 2
    exporter.watch_gateway(None, 2180)
    assert len(webhook.posts) == 3


def test_gateway_request_failures_alert_only_when_sustained(exporter, monkeypatch):
    webhook = _Webhook()
    monkeypatch.setattr(exporter.requests, "post", webhook)
    degraded = {"status": "warning", "faults": 7}
    for t in range(0, 900, 60):
        exporter.watch_gateway(degraded, t)
    assert webhook.posts == [], "one fault keeps /healthz in warning for 5 min; do not page on it"
    exporter.watch_gateway(degraded, 900)
    assert len(webhook.posts) == 1
    assert "7 in last 5 min" in webhook.messages()[0][2]
    assert len("WARN " + webhook.messages()[0][2]) <= 200
    # Escalating to unreachable within the same episode is still one episode.
    exporter.watch_gateway(None, 960)
    assert len(webhook.posts) == 1
    # A recovered-then-briefly-degraded gateway does not page.
    exporter.watch_gateway({"status": "ok"}, 1020)
    exporter.watch_gateway(degraded, 1080)
    assert [m[0] for m in webhook.messages()] == ["warning", "status"]


def test_undelivered_gateway_alert_is_retried_next_cycle(exporter, monkeypatch):
    webhook = _Webhook(replies=[(500, None), (200, False), (200, True)])
    monkeypatch.setattr(exporter.requests, "post", webhook)
    exporter.watch_gateway(None, 0)
    for t in (180, 240, 300, 360):
        exporter.watch_gateway(None, t)
    assert len(webhook.posts) == 3, "retry after HTTP 500 and after a failed Telegram send, then stop"


def test_exporter_loop_pushes_gateway_outage_between_signals(exporter, monkeypatch, tmp_path):
    """No signal, no dashboard viewer: the exporter loop alone must page."""

    class Clock:
        now = 1_800_000_000.0
        cycles = 0

        def time(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds
            self.cycles += 1
            if self.cycles >= 5:
                raise KeyboardInterrupt

    monkeypatch.setattr(exporter, "time", Clock())
    monkeypatch.setattr(exporter, "ACCOUNT_STATE_FILE", tmp_path / "account_health.json")
    monkeypatch.setattr(exporter, "PEAK_STATE_FILE", tmp_path / "portfolio_peak.json")
    monkeypatch.setattr(exporter, "refresh_live_capital", lambda: None)
    monkeypatch.setattr(exporter, "scrape_all", lambda: (0.0, 0.0))

    def gateway_down(url, **kwargs):
        raise exporter.requests.ConnectionError("connection refused")

    monkeypatch.setattr(exporter.requests, "get", gateway_down)
    webhook = _Webhook()
    monkeypatch.setattr(exporter.requests, "post", webhook)
    with pytest.raises(KeyboardInterrupt):
        exporter.main()
    assert [(m[0], m[1]) for m in webhook.messages()] == [("warning", "fleet-hl-gateway")]


# ── #104: a live bot on an account the exporter cannot value ─────────────
FUNDING = {"service": "fundingfadev1", "strategy": "FundingFadeV1",
           "capital_account": "binance-spot", "capital_owner": True}
KELTNER = {"service": "keltnerbouncev1", "strategy": "KeltnerBounceV1",
           "capital_account": "binance-spot"}
KILLERS = {"service": "ft-killers-scalp", "strategy": "KillersScalpV1",
           "capital_account": "hyperliquid-killers", "capital_owner": True}
LEDGER = json.loads((FT_DIR / "account_transfers.json").read_text())["transfers"]
LEDGER_TOTAL = sum(row["amount"] for row in LEDGER)
BINANCE_T = sum(row["amount"] for row in LEDGER if row["account"] == "binance-spot")
KILLERS_T = sum(row["amount"] for row in LEDGER if row["account"] == "hyperliquid-killers")


def _registry_bot(exporter, strategy):
    return next(dict(bot) for bot in exporter.BOTS if bot["strategy"] == strategy)


class _Fleet:
    """Fake Freqtrade mode endpoints for enforce_halts().

    `modes` maps service -> (dry_run, state), or None while /show_config is
    unreadable. A successful stop moves the bot to `paused`, as /stopentry
    does; `failing` scripts per-service stop results (True = the POST fails).
    """

    def __init__(self, exporter, monkeypatch, bots, failing=None, serve_fetch=True):
        exporter.BOTS = [dict(bot) for bot in bots]
        self.modes = {bot["service"]: (False, "running") for bot in bots}
        self.failing = failing or {}
        self.stops = []
        monkeypatch.setattr(exporter, "stop_bot", self.stop)
        if serve_fetch:
            monkeypatch.setattr(exporter, "fetch_json", lambda service, endpoint: (
                self.show_config(service) if endpoint == "show_config" else None))

    def show_config(self, service):
        mode = self.modes.get(service)
        return None if mode is None else {"dry_run": mode[0], "state": mode[1]}

    def stop(self, bot):
        self.stops.append(bot["strategy"])
        script = self.failing.get(bot["service"])
        ok = not (script and script.pop(0))
        if ok and self.modes.get(bot["service"]):
            self.modes[bot["service"]] = (self.modes[bot["service"]][0], "paused")
        return ok


def _venues(exporter, monkeypatch, killers_ok=True, fleet=None):
    """Binance wallet 300 + Hyperliquid Killers account 100, HTTP mocked."""
    requested = []

    class Response:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            if self.body is None:
                raise exporter.requests.HTTPError("503")

        def json(self):
            return self.body

    def get(url, **kwargs):
        requested.append(url)
        now = exporter.time.time()
        if url.endswith("/healthz"):
            return Response({"status": "ok", "faults": 0, "observed_at": now})
        if url.endswith("/account/killers"):
            return Response({"equity": 100.0, "free": 80.0, "margin": 20.0,
                             "notional": 40.0, "observed_at": now} if killers_ok else None)
        raise AssertionError(f"unexpected valuation request {url}")

    def fetch(service, endpoint):
        if fleet is not None and endpoint == "show_config":
            return fleet.show_config(service)
        assert (service, endpoint) == ("fundingfadev1", "balance")
        return {"total": 300.0, "stake": "USDC", "currencies": [{"currency": "USDC", "free": 250.0}]}

    monkeypatch.setattr(exporter.requests, "get", get)
    monkeypatch.setattr(exporter, "fetch_json", fetch)
    return requested


def test_todays_valued_accounts_observe_exactly_as_before(exporter, monkeypatch):
    exporter._membership_complete = True
    exporter._live_bots = [FUNDING, KELTNER, KILLERS]
    _venues(exporter, monkeypatch)
    result = exporter.observe_accounts()
    assert result["complete"] is True
    assert result["equity"] == 400.0
    assert result["breaker_complete"] is True
    assert result["breaker_equity"] == result["equity"]
    assert result["net_transfers"] == pytest.approx(LEDGER_TOTAL)
    assert result["breaker_accounts"] == {
        "binance-spot": {"equity": 300.0, "transfers": pytest.approx(BINANCE_T)},
        "hyperliquid-killers": {"equity": 100.0, "transfers": pytest.approx(KILLERS_T)},
    }
    assert result["errors"] == []
    assert "unvalued_accounts" not in result


def test_live_bot_on_unvalued_account_leaves_breaker_running_on_the_rest(exporter, monkeypatch):
    """Issue #104 repro: FundingFade + Killers live, plus a Hyperliquid bot with no
    valuation adapter promoted (Insiders in the issue, retired in #216;
    ShortKeltnerV2HL has the same registry shape)."""
    unvalued = _registry_bot(exporter, "ShortKeltnerV2HL")
    assert unvalued["capital_account"] == "ft-short-keltner-hl-live", "registry default the issue describes"
    exporter._membership_complete = True
    exporter._live_bots = [FUNDING, KELTNER, KILLERS, unvalued]
    requested = _venues(exporter, monkeypatch)
    result = exporter.observe_accounts()

    assert result["breaker_complete"] is True, "one unvalued account must not freeze the breaker"
    assert result["breaker_equity"] == 400.0
    assert result["net_transfers"] == pytest.approx(LEDGER_TOTAL)
    assert set(result["breaker_accounts"]) == {"binance-spot", "hyperliquid-killers"}
    # The whole-portfolio total is still not claimed: that wallet is unobserved.
    assert result["complete"] is False
    assert result["equity"] is None
    assert result["unvalued_accounts"] == {"ft-short-keltner-hl-live": ["ShortKeltnerV2HL"]}
    assert any("ft-short-keltner-hl-live (ShortKeltnerV2HL)" in e and "excluded from the circuit breaker" in e
               for e in result["errors"])
    assert not any("Account equity unavailable" in e for e in result["errors"]), \
        "a configuration error is not reported as a transient fetch failure"
    assert set(requested) == {exporter.GATEWAY_URL + "/healthz", exporter.GATEWAY_URL + "/account/killers"}


def test_transient_failure_on_a_valued_account_still_freezes_the_breaker(exporter, monkeypatch):
    exporter._membership_complete = True
    exporter._live_bots = [FUNDING, KILLERS, _registry_bot(exporter, "ShortKeltnerV2HL")]
    _venues(exporter, monkeypatch, killers_ok=False)
    result = exporter.observe_accounts()
    assert result["breaker_complete"] is False, "a partial total would fake a drawdown"
    assert result["breaker_equity"] is None
    assert result["breaker_accounts"] is None
    assert "Account equity unavailable: hyperliquid-killers" in result["errors"]


def test_only_unvalued_accounts_live_never_values_the_breaker_at_zero(exporter, monkeypatch):
    exporter._membership_complete = True
    exporter._live_bots = [_registry_bot(exporter, "ShortKeltnerV2HL")]
    _venues(exporter, monkeypatch)
    result = exporter.observe_accounts()
    assert result["breaker_complete"] is False
    assert result["breaker_equity"] is None
    assert result["unvalued_accounts"] == {"ft-short-keltner-hl-live": ["ShortKeltnerV2HL"]}


def test_capital_refresh_reports_unvalued_live_account_as_configuration_error(exporter, monkeypatch, caplog):
    exporter.BOTS = [FUNDING, _registry_bot(exporter, "ShortKeltnerV2HL")]
    monkeypatch.setattr(exporter, "fetch_json", lambda service, endpoint:
                        {"dry_run": False} if endpoint == "show_config" else {"starting_capital": 50.0})
    with caplog.at_level("ERROR", logger="ft-exporter"):
        exporter.refresh_live_capital()
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == 1
    assert "CONFIGURATION ERROR" in errors[0] and "ShortKeltnerV2HL" in errors[0]
    assert "ft-short-keltner-hl-live" in errors[0]


def test_drawdown_on_health_file_follows_the_breaker_scope(exporter, monkeypatch, tmp_path):
    monkeypatch.setattr(exporter, "ACCOUNT_STATE_FILE", tmp_path / "account_health.json")
    exporter._portfolio_peak = 500.0
    exporter.save_account_health({"complete": False, "equity": None, "breaker_complete": True,
                                  "breaker_equity": 400.0, "accounts": {}, "errors": []})
    saved = json.loads((tmp_path / "account_health.json").read_text())
    assert saved["drawdown_pct"] == pytest.approx(20.0)
    exporter.save_account_health({"complete": False, "equity": None, "breaker_complete": False,
                                  "breaker_equity": None, "accounts": {}, "errors": []})
    assert "drawdown_pct" not in json.loads((tmp_path / "account_health.json").read_text())


def _run_cycles(exporter, monkeypatch, tmp_path, cycles, peak_state):
    class Clock:
        now = 1_800_000_000.0
        count = 0

        def time(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds
            self.count += 1
            if self.count >= cycles:
                raise KeyboardInterrupt

    monkeypatch.setattr(exporter, "time", Clock())
    (tmp_path / "portfolio_peak.json").write_text(json.dumps(peak_state))
    monkeypatch.setattr(exporter, "PEAK_STATE_FILE", tmp_path / "portfolio_peak.json")
    monkeypatch.setattr(exporter, "ACCOUNT_STATE_FILE", tmp_path / "account_health.json")
    monkeypatch.setattr(exporter, "refresh_live_capital", lambda: None)
    monkeypatch.setattr(exporter, "scrape_all", lambda: (0.0, 0.0))
    with pytest.raises(KeyboardInterrupt):
        exporter.main()


def test_breach_on_valued_accounts_halts_entries_with_an_unvalued_bot_live(exporter, monkeypatch, tmp_path):
    """End to end through main(): before #104 the breaker never ran here."""
    unvalued = _registry_bot(exporter, "ShortKeltnerV2HL")
    exporter._membership_complete = True
    exporter._live_bots = [FUNDING, KELTNER, KILLERS, unvalued]
    exporter._live_initial_capital = 400.0
    fleet = _Fleet(exporter, monkeypatch, exporter._live_bots, serve_fetch=False)
    _venues(exporter, monkeypatch, fleet=fleet)
    stopped, alerts = fleet.stops, []
    monkeypatch.setattr(exporter, "send_circuit_breaker_alert", lambda *a: alerts.append(a))
    webhook = _Webhook()
    monkeypatch.setattr(exporter.requests, "post", webhook)
    # $500 peak on the two valued accounts, now worth $400: a 20% drawdown.
    _run_cycles(exporter, monkeypatch, tmp_path, 1, {
        "peak": 500.0, "equity_basis": "accounts-v1", "account_transfer_total": LEDGER_TOTAL})

    assert alerts and alerts[0][0] == 400.0 and alerts[0][1] == pytest.approx(20.0)
    assert stopped == ["FundingFadeV1", "KeltnerBounceV1", "KillersScalpV1", "ShortKeltnerV2HL"], \
        "the halt still covers every live bot, including the unvalued one"
    assert set(fleet.modes.values()) == {(False, "paused")}
    assert ("warning", "fleet-breaker-coverage") in [(m[0], m[1]) for m in webhook.messages()]
    health = json.loads((tmp_path / "account_health.json").read_text())
    assert health["drawdown_pct"] == pytest.approx(20.0)


def test_valued_accounts_within_threshold_do_not_halt(exporter, monkeypatch, tmp_path):
    exporter._membership_complete = True
    exporter._live_bots = [FUNDING, KELTNER, KILLERS, _registry_bot(exporter, "ShortKeltnerV2HL")]
    _venues(exporter, monkeypatch)
    stopped = []
    monkeypatch.setattr(exporter, "stop_bot", lambda bot: stopped.append(bot) or True)
    monkeypatch.setattr(exporter.requests, "post", _Webhook())
    _run_cycles(exporter, monkeypatch, tmp_path, 1, {
        "peak": 410.0, "equity_basis": "accounts-v1", "account_transfer_total": LEDGER_TOTAL})
    assert stopped == []
    assert exporter._portfolio_peak == 410.0, "the excluded wallet never enters the peak"


def test_unvalued_account_pages_once_and_reports_when_cleared(exporter, monkeypatch):
    webhook = _Webhook()
    monkeypatch.setattr(exporter.requests, "post", webhook)
    exporter._membership_complete = True
    exporter._live_bots = [FUNDING]
    observation = {"unvalued_accounts": {"ft-short-keltner-hl-live": ["ShortKeltnerV2HL"]}, "errors": []}
    exporter.watch_breaker(observation, True, 0)
    exporter.watch_breaker(observation, True, 60)
    assert len(webhook.posts) == 1, "page on the first cycle, not every cycle"
    kind, bot, message = webhook.messages()[0]
    assert (kind, bot) == ("warning", "fleet-breaker-coverage")
    assert "ft-short-keltner-hl-live (ShortKeltnerV2HL)" in message
    assert len("WARN " + message) <= 200
    exporter.watch_breaker({"errors": []}, True, 120)
    assert webhook.messages()[1][:2] == ("status", "fleet-breaker-coverage")


def test_breaker_not_evaluating_pages_after_sustained_window(exporter, monkeypatch):
    webhook = _Webhook()
    monkeypatch.setattr(exporter.requests, "post", webhook)
    exporter._membership_complete = True
    exporter._live_bots = [KILLERS]
    stuck = {"errors": ["Account equity unavailable: hyperliquid-killers"]}
    for t in range(0, 900, 60):
        exporter.watch_breaker(stuck, False, t)
    assert webhook.posts == []
    exporter.watch_breaker(stuck, False, 900)
    kind, bot, message = webhook.messages()[0]
    assert (kind, bot) == ("warning", "fleet-breaker-watch")
    assert message.startswith("Circuit breaker not evaluated for 15 min")
    assert "hyperliquid-killers" in message
    exporter.watch_breaker({"errors": []}, True, 960)
    assert webhook.messages()[1] == ("status", "fleet-breaker-watch", "Recovered after 16 min.")


def test_breaker_watch_covers_unknown_membership_but_not_an_all_dry_fleet(exporter, monkeypatch):
    webhook = _Webhook()
    monkeypatch.setattr(exporter.requests, "post", webhook)
    exporter._live_bots = []
    exporter._membership_complete = True
    for t in range(0, 1200, 60):
        exporter.watch_breaker({"errors": []}, False, t)
    assert webhook.posts == [], "no live bot: nothing to protect"
    exporter._membership_complete = False
    for t in range(1200, 2200, 60):
        exporter.watch_breaker({"errors": ["Live account membership is not fully observed"]}, False, t)
    assert [m[1] for m in webhook.messages()] == ["fleet-breaker-watch"]


def _breached_fleet(exporter, monkeypatch, failing):
    """Two live bots, 20% below the peak; `failing` scripts stop_bot results per service."""
    clock = types.SimpleNamespace(now=1_800_000_000.0)
    monkeypatch.setattr(exporter, "time", types.SimpleNamespace(time=lambda: clock.now))
    monkeypatch.setattr(exporter, "_save_peak_state", lambda: None)
    exporter._live_bots = [FUNDING, _registry_bot(exporter, "ShortKeltnerV2HL")]
    exporter._live_initial_capital = 400.0
    exporter._equity_basis = "accounts-v1"
    exporter._portfolio_peak = 500.0
    fleet = _Fleet(exporter, monkeypatch, exporter._live_bots, failing=failing)
    alerts = []
    monkeypatch.setattr(exporter, "send_circuit_breaker_alert", lambda *a: alerts.append(a))
    monkeypatch.setattr(exporter.requests, "post", _Webhook())
    return clock, fleet, alerts


def _cycle(exporter, accounts):
    """One exporter cycle's breaker work: check (when evaluated), then enforce."""
    exporter.check_circuit_breaker(0.0, accounts)
    exporter.enforce_halts()


def test_failed_halt_is_retried_alone_without_repeating_the_alert(exporter, monkeypatch):
    """Codex review of #141: one failed halt re-stopped every bot and re-sent
    the global alert on every 60-second scrape."""
    clock, fleet, alerts = _breached_fleet(
        exporter, monkeypatch, failing={"ft-short-keltner-hl-live": [True, True, False]})
    stops = fleet.stops
    _cycle(exporter, _binance(400.0))
    assert stops == ["FundingFadeV1", "ShortKeltnerV2HL"] and len(alerts) == 1
    assert exporter._pending_halts == {"ft-short-keltner-hl-live"}

    for _ in range(3):  # it fails once more, then succeeds
        clock.now += 60
        _cycle(exporter, _binance(400.0))
    assert stops[2:] == ["ShortKeltnerV2HL", "ShortKeltnerV2HL"], "only the unresolved halt is retried"
    assert len(alerts) == 1, "a retry is not a new breach"
    assert exporter._pending_halts == set()

    clock.now += 60
    _cycle(exporter, _binance(400.0))
    assert len(stops) == 4 and len(alerts) == 1, "nothing left to retry"

    clock.now += exporter.CIRCUIT_BREAKER_COOLDOWN
    _cycle(exporter, _binance(400.0))
    assert len(alerts) == 2, "the hourly reminder while still breached is unchanged"
    assert len(stops) == 4, "paused bots are not re-stopped blindly every hour"


def test_pending_halts_clear_when_the_breach_recovers(exporter, monkeypatch):
    clock, fleet, alerts = _breached_fleet(exporter, monkeypatch, failing={"ft-short-keltner-hl-live": [True]})
    _cycle(exporter, _binance(400.0))
    assert exporter._pending_halts == {"ft-short-keltner-hl-live"}
    clock.now += 60
    _cycle(exporter, _binance(495.0))  # 1% drawdown: the breaker resets
    assert exporter._circuit_breaker_triggered is False
    assert exporter._pending_halts == set(), "no halt is retried once the breach has cleared"
    assert exporter._halt_pages == {}
    assert fleet.stops == ["FundingFadeV1", "ShortKeltnerV2HL"]


def test_pending_halts_survive_an_exporter_restart(exporter, monkeypatch, tmp_path):
    monkeypatch.setattr(exporter, "PEAK_STATE_FILE", tmp_path / "portfolio_peak.json")
    exporter._circuit_breaker_triggered = True
    exporter._pending_halts = {"ft-short-keltner-hl-live"}
    exporter._save_peak_state()
    exporter._pending_halts = set()
    exporter._load_peak_state()
    assert exporter._pending_halts == {"ft-short-keltner-hl-live"}


# ── #205: a live bot restarted while the breaker is armed ─────────────────
DRY = {"service": "dry-observer", "strategy": "DryObserverV1"}
TOKEN = "synthetic-notify-token-0123456789abcdef"


class _Venue:
    """Fake HTTP for whole-loop tests: each bot's /show_config, /balance and
    /stopentry, the Hyperliquid gateway, and trade-webhook. stop_bot, the
    alerts and refresh_live_capital stay real. Binance 300 + Killers 100."""

    def __init__(self, exporter, monkeypatch, bots):
        exporter.BOTS = [dict(bot) for bot in bots]
        self.modes = {bot["service"]: (False, "running") for bot in bots}
        self.balance_down = set()
        self.cycle = 0
        self.stopentry = []  # (cycle, service)
        self.webhook = _Webhook()
        self.exporter = exporter
        monkeypatch.setattr(exporter, "fetch_json", self.fetch)
        monkeypatch.setattr(exporter.requests, "get", self.get)
        monkeypatch.setattr(exporter.requests, "post", self.post)

    def fetch(self, service, endpoint):
        if endpoint == "show_config":
            mode = self.modes.get(service)
            return None if mode is None else {"dry_run": mode[0], "state": mode[1]}
        if endpoint == "balance" and service not in self.balance_down:
            return {"starting_capital": 100.0, "total": 300.0, "stake": "USDC",
                    "currencies": [{"currency": "USDC", "free": 250.0}]}
        return None  # /profit and /status: P&L is not needed on the account basis

    def get(self, url, **kwargs):
        now = self.exporter.time.time()
        body = ({"status": "ok", "faults": 0, "observed_at": now} if url.endswith("/healthz") else
                {"equity": 100.0, "free": 80.0, "margin": 20.0, "notional": 40.0, "observed_at": now})
        return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: body)

    def post(self, url, **kwargs):
        if not url.endswith("/stopentry"):
            return self.webhook(url, **kwargs)
        service = url.split("//")[1].split(":")[0]
        self.stopentry.append((self.cycle, service))
        dry_run, _ = self.modes[service]
        self.modes[service] = (dry_run, "paused")
        return types.SimpleNamespace(status_code=200)

    def pages(self):
        return [m for m in self.webhook.messages() if m[1] == "fleet-breaker-halt"]


def _loop(exporter, monkeypatch, tmp_path, venue, peak_state, between=()):
    """Real main() for len(between) + 1 cycles; between[i] runs in the i-th sleep."""
    class Clock:
        now = 1_800_000_000.0

        def time(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds
            if venue.cycle >= len(between):
                raise KeyboardInterrupt
            between[venue.cycle]()
            venue.cycle += 1

    monkeypatch.setattr(exporter, "time", Clock())
    (tmp_path / "portfolio_peak.json").write_text(json.dumps(peak_state))
    monkeypatch.setattr(exporter, "PEAK_STATE_FILE", tmp_path / "portfolio_peak.json")
    monkeypatch.setattr(exporter, "ACCOUNT_STATE_FILE", tmp_path / "account_health.json")
    with pytest.raises(KeyboardInterrupt):
        exporter.main()
    return json.loads((tmp_path / "portfolio_peak.json").read_text())


BREACHED = {"peak": 500.0, "equity_basis": "accounts-v1", "account_transfer_total": LEDGER_TOTAL}


def test_live_bot_restarted_while_armed_is_paused_again_next_cycle(exporter, monkeypatch, tmp_path):
    """#205: a bot restarted after a SUCCESSFUL halt came back running for up to an hour."""
    monkeypatch.setenv("TRADE_WEBHOOK_NOTIFY_TOKEN", TOKEN)
    venue = _Venue(exporter, monkeypatch, [FUNDING, KILLERS, DRY])
    venue.modes[DRY["service"]] = (True, "running")

    def restart_killers():
        venue.modes[KILLERS["service"]] = (False, "running")  # initial_state: running

    state = _loop(exporter, monkeypatch, tmp_path, venue, BREACHED,
                  between=[lambda: None, restart_killers, lambda: None, lambda: None])

    assert venue.stopentry == [(0, "fundingfadev1"), (0, "ft-killers-scalp"),
                               (2, "ft-killers-scalp")], \
        "halted in the breach cycle, re-halted the cycle after the restart, nothing else"
    assert venue.modes[KILLERS["service"]] == (False, "paused")
    assert venue.modes[DRY["service"]] == (True, "running"), "a dry-run bot is never touched"
    assert [m[1] for m in venue.webhook.messages()].count("fleet-circuit-breaker") == 1
    pages = venue.pages()
    assert len(pages) == 3, "one page per bot at the breach, one for the restart, none after"
    assert "KillersScalpV1 was running; entry halt sent" in pages[-1][2]
    assert all(len("WARN " + m[2]) <= 200 for m in pages)
    assert all(k["headers"] == {"X-Notify-Token": TOKEN} for _, k in venue.webhook.posts)
    assert state["triggered"] is True and state["pending_halts"] == []


def test_armed_breaker_repauses_on_the_first_cycle_after_an_exporter_restart(
        exporter, monkeypatch, tmp_path):
    """Host reboot: membership is not observed yet (/balance down), the breaker
    cannot evaluate, and the bots came back running. Enforcement does not wait."""
    venue = _Venue(exporter, monkeypatch, [FUNDING, KILLERS])
    venue.balance_down = {"fundingfadev1", "ft-killers-scalp"}
    _loop(exporter, monkeypatch, tmp_path, venue,
          {**BREACHED, "triggered": True, "last_trigger_time": 1_800_000_000.0 - 60,
           "pending_halts": []})
    assert exporter._live_bots == [] and exporter._membership_complete is False
    assert venue.stopentry == [(0, "fundingfadev1"), (0, "ft-killers-scalp")]


def test_halt_targets_follow_current_mode_not_cached_membership(exporter, monkeypatch):
    exporter._circuit_breaker_triggered = True
    oitrend = _registry_bot(exporter, "OITrendPullbackV1")
    exporter._live_bots = [FUNDING, KELTNER, KILLERS]
    exporter._pending_halts = {"ft-killers-scalp"}
    monkeypatch.setattr(exporter, "_save_peak_state", lambda: None)
    webhook = _Webhook()
    monkeypatch.setattr(exporter.requests, "post", webhook)
    other = {"service": "unknown-bot", "strategy": "UnknownV1"}
    fleet = _Fleet(exporter, monkeypatch, [FUNDING, KELTNER, KILLERS, oitrend, other])
    fleet.modes.update({
        "fundingfadev1": (True, "running"),        # cached live, now dry-run
        "keltnerbouncev1": None,                   # unreadable, known live
        "ft-killers-scalp": (False, "stopped"),    # pending, now observed halted
        oitrend["service"]: (False, None),         # live, state missing
        "unknown-bot": None,                       # unreadable, never seen live
    })
    exporter.enforce_halts()
    assert fleet.stops == ["KeltnerBounceV1", "OITrendPullbackV1"]
    assert exporter._pending_halts == set()
    assert [m[2] for m in webhook.messages()] == [
        "Circuit breaker armed: OITrendPullbackV1 was not paused; "
        "entry halt sent. Exits remain managed."], "an unreadable bot is not paged as found live"


def test_promoted_bot_failing_halt_stays_pending_through_cooldown_and_unreadable_config(
        exporter, monkeypatch):
    clock, fleet, alerts = _breached_fleet(
        exporter, monkeypatch, failing={"ft-short-keltner-hl-live": [True, True, True]})
    exporter._live_bots = [FUNDING]  # bot promoted; membership not refreshed yet
    webhook = _Webhook()
    monkeypatch.setattr(exporter.requests, "post", webhook)
    _cycle(exporter, _binance(400.0))
    assert fleet.stops == ["FundingFadeV1", "ShortKeltnerV2HL"]
    assert exporter._pending_halts == {"ft-short-keltner-hl-live"}

    fleet.modes["ft-short-keltner-hl-live"] = None  # its API stops answering
    for _ in range(2):  # each past the cooldown: the hourly reminder fires
        clock.now += exporter.CIRCUIT_BREAKER_COOLDOWN + 60
        _cycle(exporter, _binance(400.0))
    assert fleet.stops[2:] == ["ShortKeltnerV2HL", "ShortKeltnerV2HL"], "one attempt per cycle"
    assert exporter._pending_halts == {"ft-short-keltner-hl-live"}
    assert len(alerts) == 3, "first breach plus the hourly reminders"
    halt_pages = [m[2] for m in webhook.messages() if m[1] == "fleet-breaker-halt"]
    assert len(halt_pages) == 2, "one page per bot episode, not one per failed cycle"
    assert any("entry halt FAILED for ShortKeltnerV2HL" in m for m in halt_pages)


def test_enforcement_runs_in_the_hysteresis_band_and_without_an_evaluation(exporter, monkeypatch):
    clock, fleet, alerts = _breached_fleet(exporter, monkeypatch, failing={})
    _cycle(exporter, _binance(400.0))
    assert len(fleet.stops) == 2

    fleet.modes["fundingfadev1"] = (False, "running")
    clock.now += 60
    _cycle(exporter, _binance(465.0))  # 7% drawdown: below the trip, above the reset
    assert exporter._circuit_breaker_triggered is True
    assert fleet.stops[2:] == ["FundingFadeV1"]

    fleet.modes["fundingfadev1"] = (False, "running")
    exporter.enforce_halts()  # main() runs it even when the breaker could not evaluate
    assert fleet.stops[3:] == ["FundingFadeV1"]

    exporter._circuit_breaker_triggered = False
    fleet.modes["fundingfadev1"] = (False, "running")
    exporter.enforce_halts()
    assert len(fleet.stops) == 4, "nothing is halted while the breaker is not triggered"


def test_halt_page_is_one_per_episode_retried_until_delivered(exporter, monkeypatch):
    monkeypatch.setenv("TRADE_WEBHOOK_NOTIFY_TOKEN", TOKEN)
    exporter._circuit_breaker_triggered = True
    monkeypatch.setattr(exporter, "_save_peak_state", lambda: None)
    fleet = _Fleet(exporter, monkeypatch, [FUNDING])
    webhook = _Webhook(replies=[(500, None), (200, False)])
    monkeypatch.setattr(exporter.requests, "post", webhook)

    exporter.enforce_halts()  # found running, halted; HTTP 500 on the page
    exporter.enforce_halts()  # observed paused; Telegram send failed: retry again
    assert exporter._halt_pages == {"fundingfadev1": (
        "Circuit breaker armed: FundingFadeV1 was running; entry halt sent. Exits remain managed.")}
    exporter.enforce_halts()  # delivered, episode closes
    exporter.enforce_halts()
    assert len(webhook.posts) == 3 and exporter._halt_pages == {}
    assert fleet.stops == ["FundingFadeV1"]

    fleet.modes["fundingfadev1"] = (False, "running")  # restarted: a new episode
    exporter.enforce_halts()
    exporter.enforce_halts()
    assert len(webhook.posts) == 4
    assert {m[:2] for m in webhook.messages()} == {("warning", "fleet-breaker-halt")}
    assert all(k["headers"] == {"X-Notify-Token": TOKEN} for _, k in webhook.posts)


RUNBOOK = ROOT / "docs" / "ops" / "UPDATING-WITHOUT-BREAKING-BOTS.md"


_FAKE_DOCKER = r"""#!/usr/bin/env bash
echo "$*" >> "$DOCKER_LOG"
case "$1:$2" in
  stop:*) [[ " $DOCKER_FAIL " == *" stop "* ]] && exit 1 ;;
  cp:*rebaselined*) [[ " $DOCKER_FAIL " == *" install "* ]] && exit 1 ;;
  cp:*.bak.json) [[ " $DOCKER_FAIL " == *" restore "* ]] && exit 1 ;;
esac
if [ "$1" = cp ]; then cp "${2/ft-metrics-exporter:\/state/$VOLUME}" "${3/ft-metrics-exporter:\/state/$VOLUME}"; fi
"""


def _rebaseline(tmp_path, snapshot, state, ts, fail=""):
    """Run the runbook's steps 1-3 as written. `docker` stands in for the
    exporter container (cp maps ft-metrics-exporter:/state to a directory;
    `fail` names copies that fail) and `date` returns `ts`."""
    text = RUNBOOK.read_text()
    block = text[text.index("ts=$(date -u"):text.index("# 4. After one cycle")]
    volume, work, bin_dir = tmp_path / "state", tmp_path / "work", tmp_path / "bin"
    for d in (volume, work, bin_dir):
        d.mkdir(exist_ok=True)
    (volume / "account_health.json").write_text(json.dumps(snapshot))
    (volume / "portfolio_peak.json").write_text(json.dumps(state))
    (bin_dir / "docker").write_text(_FAKE_DOCKER)
    (bin_dir / "date").write_text('#!/usr/bin/env bash\necho "$TS"\n')
    (bin_dir / "python3").write_text(f'#!/usr/bin/env bash\nexec "{sys.executable}" "$@"\n')
    for tool in bin_dir.iterdir():
        tool.chmod(0o755)
    log = tmp_path / "docker.log"
    log.write_text("")
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "VOLUME": str(volume), "DOCKER_LOG": str(log),
           "DOCKER_FAIL": fail, "TS": ts}
    run = subprocess.run(["bash", "-c", block], cwd=work, env=env, check=True,
                         capture_output=True, text=True)
    installs = [c for c in log.read_text().splitlines()
                if c.startswith("cp portfolio_peak.") and c.endswith(":/state/portfolio_peak.json")]
    return (json.loads((volume / "portfolio_peak.json").read_text()), installs,
            "start ft-metrics-exporter" in log.read_text(), run.stdout + run.stderr)


ARMED = {"peak": 500.0, "peak_basis": 400.0, "triggered": True, "last_trigger_time": 1.0,
         "equity_basis": "accounts-v1", "account_transfer_total": LEDGER_TOTAL,
         "pending_halts": ["ft-killers-scalp"],
         "accounts": {"binance-spot": {"equity": 360.0, "transfers": BINANCE_T}}}


def _snapshot(**changes):
    return {"observed_at": time.time(), "breaker_complete": True, "breaker_equity": 400.0,
            "breaker_accounts": _both(300.0, 100.0), **changes}


@pytest.mark.parametrize("ts, changes, fail, reason", [
    ("T2", {"breaker_complete": False, "breaker_accounts": None}, "", "not a complete breaker observation"),
    ("T3", {"observed_at": time.time() - 3600}, "", "older than 10 min"),
    ("T1", {}, "", "already exists"),  # same timestamp as the earlier run's output
    ("T4", {}, "stop", None),  # exporter still running: never edit under a live writer
])
def test_runbook_rebaseline_refusals_keep_the_armed_state(tmp_path, ts, changes, fail, reason):
    _rebaseline(tmp_path, _snapshot(), ARMED, "T1")  # an earlier successful run's output stays
    state, installs, started, output = _rebaseline(tmp_path, _snapshot(**changes), ARMED, ts, fail)
    assert state == ARMED and installs == []
    assert started, "the exporter comes back still triggered, so the bots stay paused"
    if reason:
        assert "refused: " in output and reason in output
    else:
        assert "refused" not in output and "new peak" not in output, "step 2 never ran"


def test_runbook_rebaseline_failed_install_restores_the_backup_or_stays_stopped(tmp_path):
    state, installs, started, _ = _rebaseline(tmp_path, _snapshot(), ARMED, "T1", "install")
    assert state == ARMED and len(installs) == 2 and started, "backup put back, then started"
    state, installs, started, output = _rebaseline(tmp_path, _snapshot(), ARMED, "T2", "install restore")
    assert not started and "exporter NOT started" in output


def test_runbook_rebaseline_clears_the_latch_without_retripping(exporter, monkeypatch, tmp_path):
    state, installs, started, output = _rebaseline(tmp_path, _snapshot(), ARMED, "T1")
    assert len(installs) == 1 and started and "breaker state: new" in output
    assert state["triggered"] is False and state["peak"] == pytest.approx(400.0)

    monkeypatch.setattr(exporter, "PEAK_STATE_FILE", tmp_path / "state" / "portfolio_peak.json")
    exporter._load_peak_state()
    assert exporter._circuit_breaker_triggered is False and exporter._pending_halts == set()

    fleet = _Fleet(exporter, monkeypatch, [FUNDING, KILLERS])
    exporter._live_bots = [FUNDING, KILLERS]
    monkeypatch.setattr(exporter, "send_circuit_breaker_alert", lambda *a: None)
    monkeypatch.setattr(exporter.requests, "post", _Webhook())
    _cycle(exporter, _both(299.0, 100.0))  # one evaluation a minute later
    assert exporter._circuit_breaker_triggered is False
    assert exporter._portfolio_peak == pytest.approx(400.0), "the scope rebase shifted nothing"
    assert fleet.stops == []

    _cycle(exporter, _both(260.0, 100.0))  # a new 10% loss from the new peak still trips
    assert exporter._circuit_breaker_triggered is True
    assert fleet.stops == ["FundingFadeV1", "KillersScalpV1"]


# ── #142: an account entering or leaving the breaker's scope ──────────────
def _scoped_breaker(exporter, monkeypatch):
    exporter._live_bots = [FUNDING, KILLERS]
    exporter._live_initial_capital = 400.0
    exporter._equity_basis = "accounts-v1"
    exporter._portfolio_peak = 0.0
    exporter._circuit_breaker_triggered = False
    exporter._pending_halts = set()
    monkeypatch.setattr(exporter, "_save_peak_state", lambda: None)
    fleet = _Fleet(exporter, monkeypatch, [FUNDING, KILLERS])
    monkeypatch.setattr(exporter, "send_circuit_breaker_alert", lambda *a: None)
    monkeypatch.setattr(exporter.requests, "post", _Webhook())
    return fleet


def _demote_killers(exporter, fleet):
    exporter._live_bots = [FUNDING]
    fleet.modes["ft-killers-scalp"] = (True, "running")


def _both(binance, killers):
    return {"binance-spot": {"equity": binance, "transfers": BINANCE_T},
            "hyperliquid-killers": {"equity": killers, "transfers": KILLERS_T}}


def _dollar_drawdown(exporter, value):
    return exporter._portfolio_peak - value


def test_demoting_the_only_bot_on_an_account_halts_nothing(exporter, monkeypatch):
    """Issue #142 repro: Killers demoted, Binance keeps its real $15 drawdown."""
    fleet = _scoped_breaker(exporter, monkeypatch)
    stopped = fleet.stops
    _cycle(exporter, _both(221.0, 309.0))
    _cycle(exporter, _both(206.0, 309.0))
    assert _dollar_drawdown(exporter, 515.0) == pytest.approx(15.0)

    _demote_killers(exporter, fleet)
    _cycle(exporter, _binance(206.0, transfers=BINANCE_T))
    assert stopped == []
    assert _dollar_drawdown(exporter, 206.0) == pytest.approx(15.0), "the Binance drawdown is unchanged"


def test_promoting_an_account_keeps_an_existing_drawdown(exporter, monkeypatch):
    """Killers enters holding more than its ledger total; Binance's loss must survive."""
    fleet = _scoped_breaker(exporter, monkeypatch)
    stopped = fleet.stops
    _cycle(exporter, _binance(221.0, transfers=BINANCE_T))
    _cycle(exporter, _binance(206.0, transfers=BINANCE_T))
    _cycle(exporter, _both(206.0, 300.0))
    assert stopped == []
    assert _dollar_drawdown(exporter, 506.0) == pytest.approx(15.0)


def test_promoting_an_account_below_its_ledger_total_trips_nothing(exporter, monkeypatch):
    """Killers enters holding less than its ledger total; that loss predates its scope."""
    fleet = _scoped_breaker(exporter, monkeypatch)
    stopped = fleet.stops
    _cycle(exporter, _binance(206.0, transfers=BINANCE_T))
    _cycle(exporter, _both(206.0, 150.0))
    assert stopped == []
    assert _dollar_drawdown(exporter, 356.0) == pytest.approx(0.0)


def test_real_loss_after_a_scope_change_still_trips(exporter, monkeypatch):
    fleet = _scoped_breaker(exporter, monkeypatch)
    stopped = fleet.stops
    _cycle(exporter, _both(206.0, 324.0))
    _demote_killers(exporter, fleet)
    _cycle(exporter, _binance(206.0, transfers=BINANCE_T))
    _cycle(exporter, _binance(180.0, transfers=BINANCE_T))
    assert stopped == ["FundingFadeV1"]


def test_departure_keeps_the_dollar_drawdown_on_a_smaller_peak(exporter, monkeypatch):
    """Approved trade-off: a $40 loss is 7.5% of $530 but 18% of the $221 left."""
    fleet = _scoped_breaker(exporter, monkeypatch)
    stopped = fleet.stops
    _cycle(exporter, _both(221.0, 309.0))
    _cycle(exporter, _both(181.0, 309.0))
    assert stopped == []
    _demote_killers(exporter, fleet)
    _cycle(exporter, _binance(181.0, transfers=BINANCE_T))
    assert _dollar_drawdown(exporter, 181.0) == pytest.approx(40.0)
    assert stopped == ["FundingFadeV1"]

def test_cash_flow_and_departure_in_one_cycle_both_apply(exporter, monkeypatch):
    fleet = _scoped_breaker(exporter, monkeypatch)
    stopped = fleet.stops
    _cycle(exporter, _both(206.0, 324.0))
    _demote_killers(exporter, fleet)
    _cycle(exporter, _binance(256.0, transfers=BINANCE_T + 50.0))
    assert stopped == []
    assert exporter._portfolio_peak == pytest.approx(256.0)


def test_account_scope_survives_an_exporter_restart(exporter, monkeypatch, tmp_path):
    save = exporter._save_peak_state
    fleet = _scoped_breaker(exporter, monkeypatch)
    stopped = fleet.stops
    monkeypatch.setattr(exporter, "_save_peak_state", save)
    monkeypatch.setattr(exporter, "PEAK_STATE_FILE", tmp_path / "portfolio_peak.json")
    _cycle(exporter, _both(206.0, 324.0))

    exporter._account_scope = None
    exporter._portfolio_peak = 0.0
    exporter._load_peak_state()
    _demote_killers(exporter, fleet)
    _cycle(exporter, _binance(206.0, transfers=BINANCE_T))
    assert stopped == []
    assert exporter._portfolio_peak == pytest.approx(206.0)


def test_malformed_saved_scope_is_reseeded_instead_of_crashing(exporter, monkeypatch, tmp_path):
    monkeypatch.setattr(exporter, "PEAK_STATE_FILE", tmp_path / "portfolio_peak.json")
    (tmp_path / "portfolio_peak.json").write_text(json.dumps({
        "peak": 530.0, "equity_basis": "accounts-v1", "account_transfer_total": LEDGER_TOTAL,
        "accounts": {"hyperliquid-killers": {"equity": "n/a"}}}))
    exporter._load_peak_state()
    assert exporter._portfolio_peak == 530.0
    assert exporter._account_scope is None

def test_state_without_account_scope_seeds_it_without_a_shift(exporter, monkeypatch):
    """The deployed peak file predates per-account scope: it holds one transfer total."""
    fleet = _scoped_breaker(exporter, monkeypatch)
    stopped = fleet.stops
    exporter._portfolio_peak = 530.0
    exporter._account_scope = None
    exporter._account_transfer_total = LEDGER_TOTAL
    _cycle(exporter, _both(206.0, 324.0))
    assert exporter._portfolio_peak == pytest.approx(530.0)

    _demote_killers(exporter, fleet)
    _cycle(exporter, _binance(206.0, transfers=BINANCE_T))
    assert stopped == []
    assert exporter._portfolio_peak == pytest.approx(206.0)


def test_seeding_still_applies_a_transfer_recorded_before_the_upgrade(exporter, monkeypatch):
    _scoped_breaker(exporter, monkeypatch)
    exporter._portfolio_peak = 320.0
    exporter._account_scope = None
    exporter._account_transfer_total = BINANCE_T
    exporter.check_circuit_breaker(0, _both(206.0, 300.0))
    assert exporter._portfolio_peak == pytest.approx(320.0 + KILLERS_T)


def test_saved_state_keeps_a_transfer_total_old_code_can_read(exporter, monkeypatch, tmp_path):
    monkeypatch.setattr(exporter, "PEAK_STATE_FILE", tmp_path / "portfolio_peak.json")
    exporter._live_bots = [FUNDING, KILLERS]
    exporter._equity_basis = "accounts-v1"
    exporter.check_circuit_breaker(0, _both(206.0, 324.0))
    saved = json.loads((tmp_path / "portfolio_peak.json").read_text())
    assert saved["account_transfer_total"] == pytest.approx(LEDGER_TOTAL)
    assert saved["accounts"]["hyperliquid-killers"] == {"equity": 324.0, "transfers": pytest.approx(KILLERS_T)}


def test_true_pnl_includes_booked_partial_exits_of_open_trades(exporter, monkeypatch):
    # #185: Freqtrade's /status profit_abs marks only the size still open; a
    # filled TP rung sits in realized_profit until the last piece exits.
    bot = {"service": "killers", "strategy": "KillersScalpV1"}
    payloads = {
        "profit": {"profit_closed_coin": -10.0, "closed_trade_count": 1},
        "status": [{"profit_abs": 7.33, "realized_profit": 3.68},
                   {"profit_abs": -0.34, "realized_profit": 0.0}],
        "balance": {"total": 100.0},
    }
    monkeypatch.setattr(exporter, "fetch_json", lambda service, endpoint: payloads[endpoint])
    assert exporter.scrape_bot(bot) == pytest.approx(-10.0 + 3.68 + 7.33 - 0.34)

    payloads["status"] = None  # missing open marks still fail closed
    assert exporter.scrape_bot(bot) is None


@pytest.mark.parametrize("bad", [
    {"profit_abs": float("nan"), "realized_profit": 0.0},
    {"profit_abs": 1.0, "realized_profit": float("nan")},
    {"profit_abs": 1.0, "realized_profit": float("inf")},
    {"profit_abs": 1.0, "realized_profit": "x"},
])
def test_non_finite_open_pnl_is_unavailable_not_a_breaker_reading(exporter, monkeypatch, bad):
    bot = {"service": "killers", "strategy": "KillersScalpV1"}
    payloads = {"profit": {"profit_closed_coin": -10.0}, "status": [bad], "balance": {"total": 1.0}}
    monkeypatch.setattr(exporter, "fetch_json", lambda service, endpoint: payloads[endpoint])
    assert exporter.scrape_bot(bot) is None
