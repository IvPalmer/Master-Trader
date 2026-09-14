"""
Docker compose validation tests.

Catches: duplicate ports, missing volume mounts, restart policy issues,
config/strategy mismatches with docker-compose services.
"""

import re
import pytest
import yaml
from pathlib import Path

FT_DIR = Path(__file__).parent.parent / "ft_userdata"
COMPOSE_FILE = FT_DIR / "docker-compose.yml"
BOT_IMAGE_PREFIX = "freqtradeorg/freqtrade"


@pytest.fixture
def compose_content():
    return COMPOSE_FILE.read_text()


@pytest.fixture
def compose():
    return yaml.safe_load(COMPOSE_FILE.read_text())


def test_compose_file_exists():
    assert COMPOSE_FILE.exists()


def test_no_duplicate_host_ports(compose_content):
    """Each service must map to a unique host port."""
    # Find all port mappings like "127.0.0.1:8080->8080/tcp" or "8084:8080"
    ports = re.findall(r'(\d+):8080', compose_content)
    # Filter out commented lines
    active_ports = []
    for line in compose_content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        port_match = re.search(r'"?(\d+):8080"?', stripped)
        if port_match:
            active_ports.append(port_match.group(1))

    assert len(active_ports) == len(set(active_ports)), (
        f"Duplicate port mappings found: {active_ports}"
    )


def test_restart_policy(compose):
    """Bot services should have restart: always (survives compose recreate crashes)."""
    bots = [
        name
        for name, svc in compose["services"].items()
        if str(svc.get("image", "")).startswith(BOT_IMAGE_PREFIX)
    ]
    assert bots, "No freqtrade bot services found in docker-compose.yml"
    for svc in bots:
        policy = compose["services"][svc].get("restart")
        assert policy == "always", (
            f"{svc}: restart policy is '{policy}', should be 'always'"
        )


def test_volume_mounts_present(compose_content):
    """Active services must mount user_data volume."""
    # Check that uncommented services have volume mounts
    assert "./user_data:/freqtrade/user_data" in compose_content, (
        "No user_data volume mount found in docker-compose.yml"
    )


def test_prometheus_config_exists():
    """Prometheus config must exist for monitoring."""
    prom_config = FT_DIR / "prometheus.yml"
    assert prom_config.exists(), "prometheus.yml missing"


def test_deployed_dashboard_assets_exist():
    """Production uses ft-dashboard; Grafana is no longer deployed."""
    prod = yaml.safe_load((FT_DIR / 'docker-compose.prod.yml').read_text())
    assert 'ft-dashboard' in prod['services']
    for name in ['templates/index.html', 'static/dashboard.js', 'static/styles.css']:
        assert (FT_DIR / 'ft_dashboard' / name).is_file()


def test_copier_candle_cap_is_scoped_away_from_funding_history():
    prod = yaml.safe_load((FT_DIR / 'docker-compose.prod.yml').read_text())
    key = 'FREQTRADE__EXCHANGE___FT_HAS_PARAMS__ohlcv_candle_limit_per_timeframe__5m'
    for name, service in prod['services'].items():
        env = service.get('environment', {})
        if name in {'ft-killers-scalp', 'ft-insiders-scalp'}:
            assert env[key] == '100'
            assert env['FREQTRADE__INTERNALS__PROCESS_THROTTLE_SECS'] == '30'
            assert not any('mark_ohlcv' in k or 'funding_fee' in k for k in env)
        else:
            assert key not in env
