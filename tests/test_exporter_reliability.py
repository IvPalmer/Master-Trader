"""Runtime membership and emergency-alert regressions for the deployed fleet."""

import importlib.util
import json
import sys
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
    exporter.check_circuit_breaker(5, 195)
    assert exporter._portfolio_peak == 200  # preserve the old $5 drawdown
    exporter._live_initial_capital = 120  # new position altered FT's margin estimate
    exporter.check_circuit_breaker(5, 195)
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
    exporter.check_circuit_breaker(0, 195, net_transfers=100)
    assert exporter._portfolio_peak == 200
    exporter.check_circuit_breaker(0, 145, net_transfers=50)
    assert exporter._portfolio_peak == 150


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
LEDGER_TOTAL = sum(row["amount"] for row in json.loads(
    (FT_DIR / "account_transfers.json").read_text())["transfers"])


def _registry_bot(exporter, strategy):
    return next(dict(bot) for bot in exporter.BOTS if bot["strategy"] == strategy)


def _venues(exporter, monkeypatch, killers_ok=True):
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
    assert result["errors"] == []
    assert "unvalued_accounts" not in result


def test_live_bot_on_unvalued_account_leaves_breaker_running_on_the_rest(exporter, monkeypatch):
    """Issue #104 repro: FundingFade + Killers live, plus Insiders promoted."""
    insiders = _registry_bot(exporter, "InsidersScalpV1")
    assert insiders["capital_account"] == "ft-insiders-scalp", "registry default the issue describes"
    exporter._membership_complete = True
    exporter._live_bots = [FUNDING, KELTNER, KILLERS, insiders]
    requested = _venues(exporter, monkeypatch)
    result = exporter.observe_accounts()

    assert result["breaker_complete"] is True, "one unvalued account must not freeze the breaker"
    assert result["breaker_equity"] == 400.0
    assert result["net_transfers"] == pytest.approx(LEDGER_TOTAL)
    # The whole-portfolio total is still not claimed: the Insiders wallet is unobserved.
    assert result["complete"] is False
    assert result["equity"] is None
    assert result["unvalued_accounts"] == {"ft-insiders-scalp": ["InsidersScalpV1"]}
    assert any("ft-insiders-scalp (InsidersScalpV1)" in e and "excluded from the circuit breaker" in e
               for e in result["errors"])
    assert not any("Account equity unavailable" in e for e in result["errors"]), \
        "a configuration error is not reported as a transient fetch failure"
    assert set(requested) == {exporter.GATEWAY_URL + "/healthz", exporter.GATEWAY_URL + "/account/killers"}


def test_transient_failure_on_a_valued_account_still_freezes_the_breaker(exporter, monkeypatch):
    exporter._membership_complete = True
    exporter._live_bots = [FUNDING, KILLERS, _registry_bot(exporter, "InsidersScalpV1")]
    _venues(exporter, monkeypatch, killers_ok=False)
    result = exporter.observe_accounts()
    assert result["breaker_complete"] is False, "a partial total would fake a drawdown"
    assert result["breaker_equity"] is None
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
    exporter.BOTS = [FUNDING, _registry_bot(exporter, "InsidersScalpV1")]
    monkeypatch.setattr(exporter, "fetch_json", lambda service, endpoint:
                        {"dry_run": False} if endpoint == "show_config" else {"starting_capital": 50.0})
    with caplog.at_level("ERROR", logger="ft-exporter"):
        exporter.refresh_live_capital()
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == 1
    assert "CONFIGURATION ERROR" in errors[0] and "InsidersScalpV1" in errors[0]
    assert "ft-insiders-scalp" in errors[0]


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
    insiders = _registry_bot(exporter, "InsidersScalpV1")
    exporter._membership_complete = True
    exporter._live_bots = [FUNDING, KELTNER, KILLERS, insiders]
    exporter._live_initial_capital = 400.0
    _venues(exporter, monkeypatch)
    stopped, alerts = [], []
    monkeypatch.setattr(exporter, "stop_bot", lambda bot: stopped.append(bot["strategy"]) or True)
    monkeypatch.setattr(exporter, "send_circuit_breaker_alert", lambda *a: alerts.append(a))
    webhook = _Webhook()
    monkeypatch.setattr(exporter.requests, "post", webhook)
    # $500 peak on the two valued accounts, now worth $400: a 20% drawdown.
    _run_cycles(exporter, monkeypatch, tmp_path, 1, {
        "peak": 500.0, "equity_basis": "accounts-v1", "account_transfer_total": LEDGER_TOTAL})

    assert alerts and alerts[0][0] == 400.0 and alerts[0][1] == pytest.approx(20.0)
    assert stopped == ["FundingFadeV1", "KeltnerBounceV1", "KillersScalpV1", "InsidersScalpV1"], \
        "the halt still covers every live bot, including the unvalued one"
    assert ("warning", "fleet-breaker-coverage") in [(m[0], m[1]) for m in webhook.messages()]
    health = json.loads((tmp_path / "account_health.json").read_text())
    assert health["drawdown_pct"] == pytest.approx(20.0)


def test_valued_accounts_within_threshold_do_not_halt(exporter, monkeypatch, tmp_path):
    exporter._membership_complete = True
    exporter._live_bots = [FUNDING, KELTNER, KILLERS, _registry_bot(exporter, "InsidersScalpV1")]
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
    observation = {"unvalued_accounts": {"ft-insiders-scalp": ["InsidersScalpV1"]}, "errors": []}
    exporter.watch_breaker(observation, True, 0)
    exporter.watch_breaker(observation, True, 60)
    assert len(webhook.posts) == 1, "page on the first cycle, not every cycle"
    kind, bot, message = webhook.messages()[0]
    assert (kind, bot) == ("warning", "fleet-breaker-coverage")
    assert "ft-insiders-scalp (InsidersScalpV1)" in message
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
    exporter._live_bots = [FUNDING, _registry_bot(exporter, "InsidersScalpV1")]
    exporter._live_initial_capital = 400.0
    exporter._equity_basis = "accounts-v1"
    exporter._portfolio_peak = 500.0
    stops, alerts = [], []

    def stop(bot):
        stops.append(bot["strategy"])
        return not failing.get(bot["service"]) or not failing[bot["service"]].pop(0)

    monkeypatch.setattr(exporter, "stop_bot", stop)
    monkeypatch.setattr(exporter, "send_circuit_breaker_alert", lambda *a: alerts.append(a))
    return clock, stops, alerts


def test_failed_halt_is_retried_alone_without_repeating_the_alert(exporter, monkeypatch):
    """Codex review of #141: one failed halt re-stopped every bot and re-sent
    the global alert on every 60-second scrape."""
    clock, stops, alerts = _breached_fleet(
        exporter, monkeypatch, failing={"ft-insiders-scalp": [True, True, False]})
    exporter.check_circuit_breaker(0.0, 400.0)
    assert stops == ["FundingFadeV1", "InsidersScalpV1"] and len(alerts) == 1

    for _ in range(3):  # Insiders fails once more, then succeeds
        clock.now += 60
        exporter.check_circuit_breaker(0.0, 400.0)
    assert stops[2:] == ["InsidersScalpV1", "InsidersScalpV1"], "only the failed halt is retried"
    assert len(alerts) == 1, "a retry is not a new breach"

    clock.now += 60
    exporter.check_circuit_breaker(0.0, 400.0)
    assert len(stops) == 4 and len(alerts) == 1, "nothing left to retry"

    clock.now += exporter.CIRCUIT_BREAKER_COOLDOWN
    exporter.check_circuit_breaker(0.0, 400.0)
    assert len(alerts) == 2, "the hourly re-halt and reminder while still breached is unchanged"
    assert stops[4:] == ["FundingFadeV1", "InsidersScalpV1"]


def test_pending_halts_clear_when_the_breach_recovers(exporter, monkeypatch):
    clock, stops, alerts = _breached_fleet(exporter, monkeypatch, failing={"ft-insiders-scalp": [True]})
    exporter.check_circuit_breaker(0.0, 400.0)
    assert exporter._pending_halts == {"ft-insiders-scalp"}
    clock.now += 60
    exporter.check_circuit_breaker(0.0, 495.0)  # 1% drawdown: the breaker resets
    assert exporter._circuit_breaker_triggered is False
    assert exporter._pending_halts == set(), "no halt is retried once the breach has cleared"


def test_pending_halts_survive_an_exporter_restart(exporter, monkeypatch, tmp_path):
    monkeypatch.setattr(exporter, "PEAK_STATE_FILE", tmp_path / "portfolio_peak.json")
    exporter._circuit_breaker_triggered = True
    exporter._pending_halts = {"ft-insiders-scalp"}
    exporter._save_peak_state()
    exporter._pending_halts = set()
    exporter._load_peak_state()
    assert exporter._pending_halts == {"ft-insiders-scalp"}


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
