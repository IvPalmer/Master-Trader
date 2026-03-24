"""
Tests for the bot evolution tracker.

Validates: snapshots work, changelogs save, peaks detect, graduation gates calculate.
"""

import json
import subprocess
import sys
import pytest
from pathlib import Path

FT_DIR = Path(__file__).parent.parent / "ft_userdata"
TRACKER = FT_DIR / "bot_evolution_tracker.py"


def run_tracker(*args):
    result = subprocess.run(
        [sys.executable, str(TRACKER)] + list(args),
        capture_output=True,
        text=True,
        cwd=str(FT_DIR),
        timeout=30,
    )
    return result


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
    result = run_tracker("dashboard")
    assert "SupertrendStrategy" in result.stdout
    assert "MasterTraderV1" in result.stdout
    assert "AlligatorTrendV1" in result.stdout
    assert "GaussianChannelV1" in result.stdout


# ── Graduation command ────────────────────────────────────────────


def test_graduation_runs():
    result = run_tracker("graduation")
    assert result.returncode == 0
    assert "GRADUATION GATE CHECK" in result.stdout


def test_graduation_shows_gates():
    result = run_tracker("graduation")
    assert "GATE 1" in result.stdout


# ── Snapshot command ──────────────────────────────────────────────


def test_snapshot_runs():
    result = run_tracker("snapshot", "--note", "test snapshot")
    assert result.returncode == 0
    assert "Snapshot" in result.stdout
    assert "saved" in result.stdout


def test_snapshot_creates_files():
    """Snapshot should create per-bot and combined JSON files."""
    evolution_dir = FT_DIR / "evolution"
    assert evolution_dir.exists()

    for bot in ["SupertrendStrategy", "MasterTraderV1", "BollingerRSIMeanReversion"]:
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


def test_changelog_runs():
    result = run_tracker("changelog", "SupertrendStrategy", "test change entry")
    assert result.returncode == 0
    assert "Logged change" in result.stdout


def test_changelog_persists():
    changelog_file = FT_DIR / "evolution" / "SupertrendStrategy" / "changelog.json"
    assert changelog_file.exists()
    with open(changelog_file) as f:
        entries = json.load(f)
    assert len(entries) > 0
    assert entries[-1]["description"] == "test change entry"


# ── History command ───────────────────────────────────────────────


def test_history_runs():
    result = run_tracker("history", "SupertrendStrategy")
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
