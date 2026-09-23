"""
Tests for the config the out-of-sample validation backtest actually runs on.

`validate_optimization` took the hyperopt result as `optimized_params` and never
read it, running the committed `config-backtest.json` instead. So the training
figure described the tuned parameters while the validation figure described the
untuned ones, and `generate_proposal` compared the two.

Hyperopt runs with `--disable-param-export`, so the parameters exist only as a
parsed dict. A config is the only route to get them into the validation run, and
a config can only express the roi, stoploss and trailing families.
"""

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

FT_DIR = Path(__file__).parent.parent / "ft_userdata"
STRATEGY = "ClucHAnix"

BASE_CONFIG = {
    "max_open_trades": 3,
    "stake_currency": "USDT",
    "stoploss": -0.05,
    "minimal_roi": {"0": 0.10},
    "dry_run": True,
}


@pytest.fixture(scope="module")
def optimizer(tmp_path_factory):
    """Redirect HOME before import: the module resolves every path off it.

    The module is dropped from sys.modules either side so this test and
    test_hyperopt_windows.py cannot inherit each other's temporary HOME.
    """
    home = tmp_path_factory.mktemp("home")
    base = home / "ft_userdata" / "user_data" / "config-backtest.json"
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_text(json.dumps(BASE_CONFIG))

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("HOME", str(home))
        mp.syspath_prepend(str(FT_DIR))
        sys.modules.pop("hyperopt_optimizer", None)
        yield importlib.import_module("hyperopt_optimizer")
    sys.modules.pop("hyperopt_optimizer", None)


@pytest.fixture
def validate(optimizer, monkeypatch):
    """Run validate_optimization and return the config the backtest was handed."""

    def run(params: dict):
        calls = []

        def fake_run(cmd, **_kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(optimizer.subprocess, "run", fake_run)
        result = optimizer.validate_optimization(STRATEGY, params)

        if not calls:
            return None, None, result

        cmd = calls[0]
        container_path = cmd[cmd.index("--config") + 1]
        host_path = Path(str(optimizer.FT_DIR)) / container_path.replace(
            "/freqtrade/", "", 1
        )
        return container_path, json.loads(host_path.read_text()), result

    return run


def test_optimized_params_reach_the_backtest(validate):
    """The whole point: the backtest must run on what hyperopt found."""
    _, config, _ = validate({"stoploss": -0.12, "trailing_stop": True})
    assert config["stoploss"] == -0.12
    assert config["trailing_stop"] is True


def test_roi_alias_is_written_as_minimal_roi(validate):
    """Hyperopt emits `roi`; Freqtrade reads `minimal_roi`."""
    _, config, _ = validate({"roi": {"0": 0.03, "30": 0.01}})
    assert config["minimal_roi"] == {"0": 0.03, "30": 0.01}


def test_base_config_settings_survive(validate):
    """Only the optimized keys change; the rest of the backtest setup is untouched."""
    _, config, _ = validate({"stoploss": -0.12})
    assert config["max_open_trades"] == BASE_CONFIG["max_open_trades"]
    assert config["stake_currency"] == BASE_CONFIG["stake_currency"]
    assert config["minimal_roi"] == BASE_CONFIG["minimal_roi"]


def test_empty_params_validate_the_baseline(validate):
    """No optimized params is not an error; it just validates the baseline."""
    _, config, _ = validate({})
    assert config["stoploss"] == BASE_CONFIG["stoploss"]


def test_inexpressible_params_abort_the_run(validate):
    """A buy-space param cannot reach the backtest, so validating would be a lie.

    Paired against the supported case on purpose. Asserting only that the
    buy-space run aborts would also pass on code that aborts every run.
    """
    supported_path, _, _ = validate({"stoploss": -0.12})
    assert supported_path is not None, "the supported case must still run"

    container_path, config, result = validate({"stoploss": -0.12, "buy_rsi": 30})
    assert container_path is None, "no backtest may run"
    assert config is None
    assert result is None, "a skipped validation must not read as a passed one"
