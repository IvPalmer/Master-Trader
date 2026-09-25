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


def test_build_contexts_exist():
    """A service built from source is undeployable if its context isn't in the repo."""
    for filename in ["docker-compose.yml", "docker-compose.prod.yml"]:
        services = yaml.safe_load((FT_DIR / filename).read_text())["services"]
        for service, spec in services.items():
            build = spec.get("build")
            if build is None:
                continue
            if isinstance(build, str):
                context, dockerfile = build, "Dockerfile"
            else:
                context, dockerfile = build["context"], build.get("dockerfile", "Dockerfile")
            assert (FT_DIR / context).is_dir(), f"{filename}: {service} builds missing {context}"
            assert (FT_DIR / context / dockerfile).is_file(), \
                f"{filename}: {service} missing {context}/{dockerfile}"


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


def test_hyperliquid_market_discovery_matches_native_perp_configs():
    prod = yaml.safe_load((FT_DIR / 'docker-compose.prod.yml').read_text())
    cases = {'ft-killers-scalp': 'KillersScalpV1.json',
             'ft-insiders-scalp': 'InsidersScalpV2.json',
             'ft-short-keltner-hl-live': 'ShortKeltnerV2HL-live.json'}
    import json
    for service, filename in cases.items():
        env = prod['services'][service]['environment']
        config = json.loads((FT_DIR / 'user_data/configs' / filename).read_text())
        assert config['exchange']['ccxt_config']['options']['fetchMarkets']['types'] == ['swap']
        assert config['trading_mode'] == 'futures'
        assert not config['exchange'].get('hip3_dexes')


def _prod_services():
    return yaml.safe_load((FT_DIR / 'docker-compose.prod.yml').read_text())['services']


def _ccxt_via_hl_gateway(service):
    env = service.get('environment') or {}
    return any('CCXT_CONFIG__urls' in key and 'hl-gateway' in str(value)
               for key, value in env.items())


def test_hyperliquid_bots_wait_for_healthy_gateway():
    """#11: a bot whose CCXT traffic goes through hl-gateway must not start
    before the gateway passes its healthcheck."""
    services = _prod_services()
    assert services['hl-gateway'].get('healthcheck'), \
        'service_healthy needs hl-gateway to define a healthcheck'
    bots = {name for name, svc in services.items() if _ccxt_via_hl_gateway(svc)}
    # Guard against the detector silently matching nothing.
    assert bots == {'ft-killers-scalp', 'ft-insiders-scalp', 'ft-short-keltner-hl-live'}
    for name in bots:
        depends = services[name].get('depends_on')
        assert isinstance(depends, dict), f'{name}: depends_on must be map form'
        assert depends.get('hl-gateway', {}).get('condition') == 'service_healthy', name


def test_receivers_do_not_wait_for_gateway():
    """Receivers must keep ingesting/auditing while the gateway is down; their
    entries already fail closed without a mark."""
    services = _prod_services()
    for name in ('killers-receiver', 'insiders-receiver'):
        depends = services[name].get('depends_on') or []
        assert 'hl-gateway' not in depends, name
