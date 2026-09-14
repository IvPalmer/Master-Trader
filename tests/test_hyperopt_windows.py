"""
Tests for the hyperopt train/validation split.

Both windows were anchored at `now`, so the validation window sat inside the
training window whenever val_days < train_days, which is the default (20 < 60).
"""

import importlib
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

FT_DIR = Path(__file__).parent.parent / "ft_userdata"
DATE_FMT = "%Y%m%d"
STRATEGY = "ClucHAnix"

# automation_scheduler.sh:47 downloads 90 days at Sun 03:00; hyperopt runs 06:00.
DOWNLOADED_HISTORY_DAYS = 90


@pytest.fixture(scope="module")
def optimizer(tmp_path_factory):
    """Redirect HOME: importing the module creates log and proposal dirs under it."""
    home = tmp_path_factory.mktemp("home")
    config = home / "ft_userdata" / "user_data" / "configs" / f"{STRATEGY}.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("{}")

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("HOME", str(home))
        mp.syspath_prepend(str(FT_DIR))
        yield importlib.import_module("hyperopt_optimizer")


@pytest.fixture
def windows(optimizer, monkeypatch):
    """The --timerange values the Docker calls would use under cron's defaults."""
    captured = {}

    def fake_run(cmd, **_kwargs):
        subcommand = "backtesting" if "backtesting" in cmd else "hyperopt"
        captured[subcommand] = cmd[cmd.index("--timerange") + 1]
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(optimizer.subprocess, "run", fake_run)

    optimizer.run_hyperopt(STRATEGY, epochs=1)
    optimizer.validate_optimization(STRATEGY, {})

    assert set(captured) == {"hyperopt", "backtesting"}
    return captured


def _dates(timerange):
    start, end = timerange.split("-")
    return (
        datetime.strptime(start, DATE_FMT).date(),
        datetime.strptime(end, DATE_FMT).date(),
    )


def test_validation_window_is_out_of_sample(windows):
    """The validation window must not overlap the window hyperopt trained on."""
    _, train_end = _dates(windows["hyperopt"])
    val_start, _ = _dates(windows["backtesting"])
    assert val_start >= train_end


def test_training_window_fits_downloaded_history(windows):
    """Reserving a holdout must not push training past the data on disk."""
    train_start, _ = _dates(windows["hyperopt"])
    oldest = datetime.now(timezone.utc).date() - timedelta(days=DOWNLOADED_HISTORY_DAYS)
    assert train_start >= oldest
