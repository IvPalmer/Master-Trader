"""
Tests for the bot evolution tracker.

Validates: snapshots work, changelogs save, peaks detect, graduation gates calculate.
"""

import json
import re
import subprocess
import sys
import pytest
from pathlib import Path

FT_DIR = Path(__file__).parent.parent / "ft_userdata"
TRACKER = FT_DIR / "bot_evolution_tracker.py"
BOTS_CONFIG = FT_DIR / "bots_config.json"
CONFIG_DIR = FT_DIR / "user_data" / "configs"

ACTIVE_BOTS = [
    name
    for name, info in json.loads(BOTS_CONFIG.read_text())["bots"].items()
    if info.get("active", True)
]


@pytest.fixture(scope="module", autouse=True)
def evolution_dir(tmp_path_factory):
    """Redirect the tracker's data dir so the suite never writes into ft_userdata/evolution/."""
    path = tmp_path_factory.mktemp("evolution")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MT_EVOLUTION_DIR", str(path))
        yield path


def run_tracker(*args):
    result = subprocess.run(
        [sys.executable, str(TRACKER)] + list(args),
        capture_output=True,
        text=True,
        cwd=str(FT_DIR),
        timeout=30,
    )
    return result


@pytest.fixture(scope="module")
def snapshot_result(evolution_dir):
    return run_tracker("snapshot", "--note", "test snapshot")


@pytest.fixture(scope="module")
def changelog_result(evolution_dir):
    return run_tracker("changelog", ACTIVE_BOTS[0], "test change entry")


# ── Tracker script validity ───────────────────────────────────────


def test_tracker_exists():
    assert TRACKER.exists()


def test_tracker_parses():
    """Tracker must be valid Python."""
    import ast
    ast.parse(TRACKER.read_text())


def test_tracker_help():
    """Tracker should show help without errors."""
    result = run_tracker("--help")
    assert result.returncode == 0


# ── Dashboard command ─────────────────────────────────────────────


def test_dashboard_runs():
    result = run_tracker("dashboard")
    assert result.returncode == 0
    assert "BOT EVOLUTION DASHBOARD" in result.stdout


def test_dashboard_shows_all_bots():
    assert ACTIVE_BOTS, "No active bots in bots_config.json"
    result = run_tracker("dashboard")
    for bot in ACTIVE_BOTS:
        assert bot in result.stdout, f"{bot} is active but missing from the dashboard"


# ── Graduation command ────────────────────────────────────────────


def test_graduation_runs():
    result = run_tracker("graduation")
    assert result.returncode == 0
    assert "GRADUATION GATE CHECK" in result.stdout


def test_graduation_shows_gates():
    result = run_tracker("graduation")
    assert "GATE 1" in result.stdout


# ── Snapshot command ──────────────────────────────────────────────


def test_snapshot_runs(snapshot_result):
    assert snapshot_result.returncode == 0
    assert "Snapshot" in snapshot_result.stdout
    assert "saved" in snapshot_result.stdout


def test_snapshot_creates_files(evolution_dir, snapshot_result):
    """Snapshot should create per-bot and combined JSON files."""
    assert ACTIVE_BOTS, "No active bots in bots_config.json"
    assert evolution_dir.exists()

    for bot in ACTIVE_BOTS:
        bot_dir = evolution_dir / bot
        assert bot_dir.exists(), f"No evolution dir for {bot}"
        snapshots = list(bot_dir.glob("2*.json"))
        assert len(snapshots) > 0, f"No snapshots for {bot}"

        # Validate snapshot structure
        with open(snapshots[-1]) as f:
            data = json.load(f)
        assert "id" in data
        assert "timestamp" in data
        assert "metrics" in data
        assert "parameters" in data


# ── Changelog command ─────────────────────────────────────────────


def test_changelog_runs(changelog_result):
    assert changelog_result.returncode == 0
    assert "Logged change" in changelog_result.stdout


def test_changelog_persists(evolution_dir, changelog_result):
    changelog_file = evolution_dir / ACTIVE_BOTS[0] / "changelog.json"
    assert changelog_file.exists()
    with open(changelog_file) as f:
        entries = json.load(f)
    assert len(entries) > 0
    assert entries[-1]["description"] == "test change entry"


# ── History command ───────────────────────────────────────────────


@pytest.mark.usefixtures("snapshot_result")
def test_history_runs():
    result = run_tracker("history", ACTIVE_BOTS[0])
    assert result.returncode == 0
    assert "EVOLUTION TIMELINE" in result.stdout


# ── Peak detection ────────────────────────────────────────────────


def test_peak_file_created_for_profitable_bots():
    """Bots with 10+ trades and positive P/L should have a peak file."""
    evolution_dir = FT_DIR / "evolution"
    st_peak = evolution_dir / "SupertrendStrategy" / "peak.json"
    if st_peak.exists():
        with open(st_peak) as f:
            peak = json.load(f)
        assert "metrics" in peak
        assert "parameters" in peak
        assert peak["metrics"]["profit_factor"] > 0


# Data directory resolution


def resolve_data_dir():
    result = subprocess.run(
        [sys.executable, "-c", "import bot_evolution_tracker as t; print(t.DATA_DIR)"],
        capture_output=True,
        text=True,
        cwd=str(FT_DIR),
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.parametrize("override", [None, ""], ids=["unset", "empty"])
def test_data_dir_defaults_to_repo_evolution(override, monkeypatch):
    """Unset or empty MT_EVOLUTION_DIR must still resolve to ft_userdata/evolution/."""
    if override is None:
        monkeypatch.delenv("MT_EVOLUTION_DIR", raising=False)
    else:
        monkeypatch.setenv("MT_EVOLUTION_DIR", override)
    assert resolve_data_dir() == str(FT_DIR / "evolution")


def test_data_dir_honours_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MT_EVOLUTION_DIR", str(tmp_path))
    assert resolve_data_dir() == str(tmp_path)


def test_override_creates_missing_parent_dirs(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "evolution"
    monkeypatch.setenv("MT_EVOLUTION_DIR", str(target))
    result = run_tracker("snapshot", "--note", "nested path check")
    assert result.returncode == 0, result.stderr
    assert target.exists()


# Config capture: an absent config must be recorded, never a silent {}


def probe_config_params(bot_name, config_name=None):
    """Call extract_config_params out of process, as the data-dir probe above does."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, sys, bot_evolution_tracker as t\n"
            "name = sys.argv[2] if len(sys.argv) > 2 else None\n"
            "print('JSON:' + json.dumps(t.extract_config_params(sys.argv[1], name)))",
            bot_name,
        ]
        + ([config_name] if config_name else []),
        capture_output=True,
        text=True,
        cwd=str(FT_DIR),
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = next(ln for ln in result.stdout.splitlines() if ln.startswith("JSON:"))
    return json.loads(payload.removeprefix("JSON:")), result.stdout


CONFIG_KEYS = {
    "dry_run",
    "dry_run_wallet",
    "max_open_trades",
    "stake_amount",
    "stoploss_on_exchange",
    "trading_mode",
}


def deployed_configs():
    """strategy -> config filenames, from the prod compose `freqtrade trade` commands.

    A set per strategy: one strategy can run under several configs
    (InsidersScalpV2.json runs --strategy KillersScalpV1). Commented lines are ignored.
    """
    pattern = re.compile(
        r"exec freqtrade trade .*?--config /freqtrade/user_data/configs/(\S+) --strategy (\S+)"
    )
    deployed = {}
    for line in (FT_DIR / "docker-compose.prod.yml").read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        for config, strategy in pattern.findall(line):
            deployed.setdefault(strategy, set()).add(config)
    return deployed


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_runtime_config_matches_the_deployed_config(bot):
    """runtime_config has to name the file prod actually runs, or the snapshot records
    parameters from a config the bot never loaded."""
    deployed = deployed_configs()
    assert bot in deployed, f"{bot} has no freqtrade command in docker-compose.prod.yml"
    assert len(deployed[bot]) == 1, f"{bot} runs under several configs: {deployed[bot]}"
    runtime = json.loads(BOTS_CONFIG.read_text())["bots"][bot].get("runtime_config")
    assert {runtime} == deployed[bot]


@pytest.mark.parametrize("bot", ACTIVE_BOTS)
def test_active_bot_config_is_extracted(bot):
    params, _ = probe_config_params(bot)
    assert "_config_missing" not in params
    assert set(params) == CONFIG_KEYS


def test_bot_without_runtime_config_resolves_by_name():
    """Paired control for the fallback: no runtime_config, <name>.json exists."""
    bots = json.loads(BOTS_CONFIG.read_text())["bots"]
    assert not bots["SupertrendStrategy"].get("runtime_config")
    assert (CONFIG_DIR / "SupertrendStrategy.json").exists()
    params, _ = probe_config_params("SupertrendStrategy")
    assert set(params) == CONFIG_KEYS


def test_missing_config_is_recorded():
    params, stdout = probe_config_params("NoSuchBotV0")
    assert params == {"_config_missing": "NoSuchBotV0.json"}
    assert "WARNING" in stdout


def test_recorded_config_that_is_absent_does_not_fall_back_to_name():
    """KeltnerBounceV1.json exists, but a recorded config that does not must be flagged
    rather than silently replaced by it."""
    assert (CONFIG_DIR / "KeltnerBounceV1.json").exists()
    params, stdout = probe_config_params("KeltnerBounceV1", "KeltnerBounceV1.gone.json")
    assert params == {"_config_missing": "KeltnerBounceV1.gone.json"}
    assert "WARNING" in stdout


def test_snapshot_never_records_an_empty_config(evolution_dir, snapshot_result):
    """The defect at the artifact level: a snapshot whose config is {} cannot be told
    apart from one whose config held no values, and a snapshot cannot be backfilled."""
    for bot in ACTIVE_BOTS:
        snapshots = sorted((evolution_dir / bot).glob("2*.json"))
        assert snapshots, f"no snapshot written for {bot}"
        with open(snapshots[-1]) as f:
            data = json.load(f)
        assert "config" in data, f"{bot} snapshot has no config key"
        assert data["config"], f"{bot} snapshot recorded an empty config"
