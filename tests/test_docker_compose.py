"""
Docker compose validation tests.

Catches: duplicate ports, missing volume mounts, restart policy issues,
config/strategy mismatches with docker-compose services.
"""

import re
import pytest
from pathlib import Path

FT_DIR = Path(__file__).parent.parent / "ft_userdata"
COMPOSE_FILE = FT_DIR / "docker-compose.yml"


@pytest.fixture
def compose_content():
    return COMPOSE_FILE.read_text()


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


def test_restart_policy(compose_content):
    """Active bot services should have restart: always (survives compose recreate crashes)."""
    active_services = [
        "supertrendstrategy",
        "mastertraderv1",
        "alligatortrendv1",
        "gaussianchannelv1",
        "bearcrashshortv1",
    ]
    for svc in active_services:
        # Find the service block (rough check)
        pattern = rf'{svc}:.*?restart:\s*(\S+)'
        match = re.search(pattern, compose_content, re.DOTALL)
        if match:
            policy = match.group(1)
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


def test_grafana_dashboards_exist():
    """At least one Grafana dashboard must exist."""
    dashboard_dir = FT_DIR / "grafana" / "dashboards"
    assert dashboard_dir.exists(), "Grafana dashboards directory missing"
    dashboards = list(dashboard_dir.glob("*.json"))
    assert len(dashboards) > 0, "No Grafana dashboard JSON files found"
