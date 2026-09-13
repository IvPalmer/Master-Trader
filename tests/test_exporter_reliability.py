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
