"""
Infrastructure tests — Docker, services, monitoring pipeline.

Run with: pytest tests/test_infrastructure.py -v
These tests require Docker to be running and bots to be up.
Mark with @pytest.mark.live so they can be skipped offline.
"""

import json
import os
import subprocess
import pytest
import urllib.request
import urllib.error
from pathlib import Path

FT_DIR = Path(__file__).parent.parent / "ft_userdata"


def is_docker_running():
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def api_get(port, endpoint, timeout=5):
    """Call a Freqtrade API endpoint."""
    url = f"http://localhost:{port}/api/v1/{endpoint}"
    req = urllib.request.Request(url)
    # Basic auth: freqtrader:mastertrader
    import base64
    creds = base64.b64encode(b"freqtrader:mastertrader").decode()
    req.add_header("Authorization", f"Basic {creds}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


live = pytest.mark.skipif(
    not is_docker_running(),
    reason="Docker not running"
)

def _load_bot_ports() -> dict:
    """Load bot name→port mapping from shared config, fall back to hardcoded defaults."""
    config_path = Path(__file__).parent.parent / "ft_userdata" / "bots_config.json"
    try:
        with open(config_path) as f:
            data = json.load(f)
        return {
            name: info["port"]
            for name, info in data["bots"].items()
            if info.get("active", True)
        }
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return {
            "IchimokuTrendV1": 8080,
            "EMACrossoverV1": 8083,
            "SupertrendStrategy": 8084,
            "MasterTraderV1": 8086,
            "BollingerRSIMeanReversion": 8089,
            "FuturesSniperV1": 8090,
        }

BOT_PORTS = _load_bot_ports()


# ── Docker containers ─────────────────────────────────────────────


@live
def test_docker_compose_valid():
    """docker-compose.yml must parse without errors."""
    result = subprocess.run(
        ["docker", "compose", "config", "--quiet"],
        cwd=str(FT_DIR),
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, f"docker-compose invalid: {result.stderr.decode()}"


@live
def test_all_containers_running():
    """All trading bot containers must be running."""
    result = subprocess.run(
        ["docker", "compose", "ps", "--format", "json"],
        cwd=str(FT_DIR),
        capture_output=True,
        timeout=10,
    )
    output = result.stdout.decode()
    # Docker compose outputs one JSON object per line
    containers = []
    for line in output.strip().split("\n"):
        if line.strip():
            containers.append(json.loads(line))

    running = {c["Service"]: c["State"] for c in containers}

    expected_services = [
        "bollingerrsimeanreversion",
        "emacrossoverv1",
        "supertrendstrategy",
        "mastertraderv1",
        "futuressniper",
        "ichimokutrendv1",
        "prometheus",
        "grafana",
        "metrics-exporter",
    ]

    for svc in expected_services:
        assert svc in running, f"Container '{svc}' not found"
        assert running[svc] == "running", f"Container '{svc}' state: {running[svc]}"


# ── Bot API health ────────────────────────────────────────────────


@live
@pytest.mark.parametrize("bot,port", list(BOT_PORTS.items()))
def test_bot_api_responds(bot, port):
    """Each bot's API must respond to health checks."""
    data = api_get(port, "show_config")
    assert data is not None, f"{bot} (port {port}): API not responding"
    assert "bot_name" in data, f"{bot}: API response missing bot_name"


@live
@pytest.mark.parametrize("bot,port", list(BOT_PORTS.items()))
def test_bot_state_running(bot, port):
    """Each bot must be in 'running' state, not 'stopped'."""
    data = api_get(port, "show_config")
    assert data is not None, f"{bot}: API not responding"
    state = data.get("state", "")
    assert state == "running", f"{bot}: state is '{state}', expected 'running'"


@live
@pytest.mark.parametrize("bot,port", list(BOT_PORTS.items()))
def test_bot_config_matches_strategy(bot, port):
    """Bot must be running the correct strategy."""
    data = api_get(port, "show_config")
    assert data is not None
    # The strategy name in the API should match what we expect
    strategy = data.get("strategy", "")
    assert bot.replace("V1", "") in strategy or strategy in bot, (
        f"Port {port} running '{strategy}' but expected '{bot}'"
    )


# ── Monitoring pipeline ──────────────────────────────────────────


@live
def test_prometheus_healthy():
    """Prometheus must be up and scraping."""
    try:
        with urllib.request.urlopen("http://localhost:9091/-/healthy", timeout=5) as resp:
            assert resp.status == 200
    except Exception as e:
        pytest.fail(f"Prometheus not healthy: {e}")


@live
def test_metrics_exporter_serving():
    """Metrics exporter must be serving Freqtrade metrics."""
    try:
        with urllib.request.urlopen("http://localhost:9090/metrics", timeout=5) as resp:
            content = resp.read().decode()
        assert "freqtrade_balance" in content, "No freqtrade_balance metric found"
        assert "freqtrade_profit" in content, "No freqtrade_profit metric found"
    except Exception as e:
        pytest.fail(f"Metrics exporter not working: {e}")


@live
def test_grafana_healthy():
    """Grafana must be up and serving."""
    try:
        with urllib.request.urlopen("http://localhost:3000/api/health", timeout=5) as resp:
            data = json.loads(resp.read())
        assert data.get("database") == "ok", f"Grafana DB not ok: {data}"
    except Exception as e:
        pytest.fail(f"Grafana not healthy: {e}")


@live
def test_metrics_balance_reasonable():
    """Sanity check: reported balances should be reasonable."""
    try:
        with urllib.request.urlopen("http://localhost:9090/metrics", timeout=5) as resp:
            content = resp.read().decode()
    except Exception:
        pytest.skip("Metrics exporter not available")

    import re
    balances = re.findall(r'freqtrade_balance\{strategy="(\w+)"\}\s+([\d.]+)', content)
    for strategy, balance in balances:
        bal = float(balance)
        assert 0 < bal < 100000, (
            f"{strategy}: balance ${bal} looks wrong (expected $100-$10000 range)"
        )


# ── Symlink integrity ────────────────────────────────────────────


def test_ft_userdata_symlink():
    """~/ft_userdata must be a symlink pointing to the repo."""
    home = Path.home()
    link = home / "ft_userdata"
    assert link.is_symlink(), f"{link} should be a symlink"
    target = link.resolve()
    assert target == FT_DIR.resolve(), (
        f"Symlink points to {target}, expected {FT_DIR.resolve()}"
    )


def test_docker_compose_accessible_via_symlink():
    """Docker compose file must be accessible through the symlink."""
    home = Path.home()
    compose = home / "ft_userdata" / "docker-compose.yml"
    assert compose.exists(), f"docker-compose.yml not accessible via symlink"
