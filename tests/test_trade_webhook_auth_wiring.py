"""Every caller of trade-webhook can authenticate, and nothing else can reach it (#97).

services/trade-webhook/tests/test_event_auth.py pins the route's behaviour.
This file pins the wiring around it:

- trade-webhook is no longer on dokploy-network, the Swarm overlay it shared
  with ~25 unrelated apps; its callers are all on master-trader's network.
- Each Freqtrade bot gets the token through FREQTRADE__WEBHOOK__<TEMPLATE>__
  WEBHOOK_TOKEN env vars, for exactly the body templates its config defines.
  Freqtrade 2026.7 deep-merges those vars into the config, so a var for a
  template the config lacks would create a token-only template and the bot
  would start posting that event type (checked against the running image on
  2026-10-02 with Freqtrade's own parser and formatter).
- The exporter's circuit-breaker alert and the host health-report cron send it
  as X-Notify-Token.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
FT_DIR = ROOT / "ft_userdata"
CONFIGS = FT_DIR / "user_data" / "configs"
PROD = FT_DIR / "docker-compose.prod.yml"
TW_DIR = ROOT / "services" / "trade-webhook"
HEALTH_WRAPPER = ROOT / "deploy" / "vps" / "run-health-report.sh"
TOKEN = "notify-token-for-tests-0123456789abcdef"
TOKEN_REF = "${TRADE_WEBHOOK_NOTIFY_TOKEN:-}"
ENV_KEY = re.compile(r"^FREQTRADE__WEBHOOK__([A-Z]+)__WEBHOOK_TOKEN$")


@pytest.fixture(scope="module")
def prod():
    return yaml.safe_load(PROD.read_text())["services"]


def _bots(services):
    for name, svc in services.items():
        entry = svc.get("entrypoint")
        entry = " ".join(entry) if isinstance(entry, list) else str(entry or "")
        if str(svc.get("image", "")).startswith("freqtradeorg/freqtrade") and "freqtrade trade" in entry:
            config = re.search(r"--config /freqtrade/user_data/configs/(\S+\.json)", entry).group(1)
            yield name, config


def _templates(config_name):
    webhook = json.loads((CONFIGS / config_name).read_text())["webhook"]
    return {k: v for k, v in webhook.items() if isinstance(v, dict)}


def test_the_fleet_is_five_bots(prod):
    assert len(list(_bots(prod))) == 5


def test_trade_webhook_is_not_on_dokploy_network():
    compose = yaml.safe_load((TW_DIR / "docker-compose.yml").read_text())
    svc = compose["services"]["trade-webhook"]
    assert list(svc["networks"]) == ["master-trader-net"]
    assert "dokploy-network" not in compose["networks"]
    assert compose["networks"]["master-trader-net"]["name"] == "compose-bypass-mobile-port-fbk1m6_default"
    assert svc["ports"] == ["127.0.0.1:8088:8088"]


def test_every_bot_injects_the_token_into_exactly_its_templates(prod):
    for service, config in _bots(prod):
        env = prod[service]["environment"]
        injected = {ENV_KEY.match(k).group(1).lower(): v for k, v in env.items() if ENV_KEY.match(k)}
        assert set(injected) == set(_templates(config)), (service, config)
        assert set(injected.values()) == {TOKEN_REF}, service


def test_every_bot_posts_json_to_trade_webhook(prod):
    for _, config in _bots(prod):
        webhook = json.loads((CONFIGS / config).read_text())["webhook"]
        assert webhook["url"] == "http://trade-webhook:8088/freqtrade/event", config
        assert webhook["format"] == "json", config


def test_header_callers_carry_the_token(prod):
    for service in ("metrics-exporter", "killers-receiver"):
        assert prod[service]["environment"]["TRADE_WEBHOOK_NOTIFY_TOKEN"] == TOKEN_REF, service


@pytest.fixture
def webhook_app(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADES_DIR", str(tmp_path))
    monkeypatch.setenv("TRADE_WEBHOOK_NOTIFY_TOKEN", TOKEN)
    monkeypatch.setenv("TRADE_WEBHOOK_EVENT_AUTH", "enforce")
    monkeypatch.delenv("OPS_BOT_TOKEN", raising=False)
    monkeypatch.delenv("OPS_BOT_CHAT_ID", raising=False)
    spec = importlib.util.spec_from_file_location("trade_webhook_for_wiring_tests", TW_DIR / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sent = []

    async def fake_send(text):
        sent.append(text)
        return True

    monkeypatch.setattr(module, "telegram_send", fake_send)
    return TestClient(module.app), sent, tmp_path


# Every field any deployed template formats.
MSG = {"pair": "ARB/USDT", "stake_amount": 10, "stake_currency": "USDT", "limit": 0.51,
       "open_rate": 0.51, "order_type": "limit", "direction": "Long", "leverage": 1,
       "reason": "timeout", "profit_ratio": -0.0123, "profit_amount": -0.1845,
       "close_rate": 0.5037, "exit_reason": "stop_loss", "status": "Bot started"}


def _freqtrade_body(template, token):
    """The body Freqtrade 2026.7 posts: the template, with the env-merged
    webhook_token, every string formatted with the message (recursive_format)."""
    merged = {**template, "webhook_token": token}
    return {k: v.format(**MSG) if isinstance(v, str) else v for k, v in merged.items()}


def test_every_bot_event_is_accepted_under_enforce_and_the_token_is_not_kept(prod, webhook_app):
    client, sent, lake = webhook_app
    posted = 0
    for _, config in _bots(prod):
        for template in _templates(config).values():
            r = client.post("/freqtrade/event", json=_freqtrade_body(template, TOKEN))
            assert r.status_code == 200, (config, template["type"])
            posted += 1
    assert posted == len(sent) - sum(t.startswith("⚠ PAIR DRIFT") for t in sent)
    stored = "".join(p.read_text() for p in lake.glob("*.jsonl"))
    assert TOKEN not in stored and "webhook_token" not in stored
    assert not any(TOKEN in t for t in sent)
    assert not (lake / "unknown.jsonl").exists()


def test_a_bot_without_the_token_is_refused_under_enforce(prod, webhook_app):
    client, sent, lake = webhook_app
    _, config = next(_bots(prod))
    template = _templates(config)["webhookstatus"]
    assert client.post("/freqtrade/event", json=_freqtrade_body(template, "")).status_code == 401
    assert sent == [] and list(lake.iterdir()) == []


@pytest.fixture
def exporter(monkeypatch):
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
    spec = importlib.util.spec_from_file_location("exporter_for_wiring_tests", FT_DIR / "metrics_exporter.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._live_initial_capital = 100.0
    module._live_bots = [{"strategy": "ExampleBot", "service": "example"}]
    return module


@pytest.mark.parametrize("token, expected", [(TOKEN, {"X-Notify-Token": TOKEN}), ("", {})])
def test_circuit_breaker_alert_sends_the_token_header(exporter, monkeypatch, token, expected):
    captured = []
    monkeypatch.setattr(exporter.requests, "post",
                        lambda url, **kw: captured.append(kw) or types.SimpleNamespace(status_code=200))
    monkeypatch.setenv("TRADE_WEBHOOK_NOTIFY_TOKEN", token)
    exporter.send_circuit_breaker_alert(85.0, 15.0)
    assert captured[0]["headers"] == expected


@pytest.mark.parametrize("token, expected", [(TOKEN, {"X-Notify-Token": TOKEN}), ("", {})])
def test_ops_alerts_send_the_token_header(exporter, monkeypatch, token, expected):
    """Breaker halt pages (#205) and the other ops alerts share the route."""
    captured = []
    monkeypatch.setattr(exporter.requests, "post", lambda url, **kw: captured.append(kw) or
                        types.SimpleNamespace(status_code=200, json=lambda: {"telegram_sent": True}))
    monkeypatch.setenv("TRADE_WEBHOOK_NOTIFY_TOKEN", token)
    assert exporter.send_ops_alert("fleet-breaker-halt", "message")
    assert captured[0]["headers"] == expected


def _token_block():
    text = HEALTH_WRAPPER.read_text()
    start = text.index('OPS_ENV_FILE="/etc/lake/ops-bot.env"')
    end = text.index("\nfi\n", start) + len("\nfi\n")
    return text[start:end]


def test_health_wrapper_exports_only_the_token(tmp_path):
    env_file = tmp_path / "ops-bot.env"
    env_file.write_text(
        "OPS_BOT_TOKEN=telegram-bot-secret\n"
        "OPS_BOT_CHAT_ID=1\n"
        f"TRADE_WEBHOOK_NOTIFY_TOKEN={TOKEN}\r\n"
    )
    block = _token_block().replace("/etc/lake/ops-bot.env", str(env_file))
    out = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + block + "\nenv"],
        capture_output=True, text=True, check=True,
        env={"PATH": os.environ["PATH"]},
    ).stdout
    assert f"TRADE_WEBHOOK_NOTIFY_TOKEN={TOKEN}\n" in out
    assert "telegram-bot-secret" not in out


def test_health_wrapper_runs_without_the_env_file(tmp_path):
    block = _token_block().replace("/etc/lake/ops-bot.env", str(tmp_path / "missing.env"))
    out = subprocess.run(["bash", "-c", "set -euo pipefail\n" + block + "\nenv"],
                         capture_output=True, text=True, check=True,
                         env={"PATH": os.environ["PATH"]}).stdout
    assert "TRADE_WEBHOOK_NOTIFY_TOKEN" not in out
