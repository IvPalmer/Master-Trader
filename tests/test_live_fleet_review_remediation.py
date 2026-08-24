"""Regression contracts for the 2026-08-24 live-fleet review remediation."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parent.parent
STRATEGIES = ROOT / "ft_userdata" / "user_data" / "strategies"
CONFIGS = ROOT / "ft_userdata" / "user_data" / "configs"


def _class_assignment(path: Path, class_name: str, attribute: str):
    tree = ast.parse(path.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    for node in cls.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == attribute for target in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError(f"{class_name}.{attribute} not found")


@pytest.mark.parametrize(
    ("strategy", "class_name"),
    [("FundingFadeV1.py", "FundingFadeV1"), ("KeltnerBounceV1.py", "KeltnerBounceV1")],
)
def test_custom_exit_strategies_enable_exit_callbacks(strategy, class_name):
    assert _class_assignment(STRATEGIES / strategy, class_name, "use_exit_signal") is True


@contextmanager
def _strategy_import_stubs():
    names = ["freqtrade", "freqtrade.strategy", "talib", "talib.abstract"]
    saved = {name: sys.modules.get(name) for name in names}
    freqtrade = types.ModuleType("freqtrade")
    strategy = types.ModuleType("freqtrade.strategy")
    strategy.IStrategy = object
    strategy.informative = lambda *args, **kwargs: (lambda fn: fn)
    strategy.stoploss_from_absolute = lambda **kwargs: kwargs["stop_rate"] / kwargs["current_rate"]
    talib = types.ModuleType("talib")
    talib_abstract = types.ModuleType("talib.abstract")
    talib.abstract = talib_abstract
    sys.modules.update(
        {
            "freqtrade": freqtrade,
            "freqtrade.strategy": strategy,
            "talib": talib,
            "talib.abstract": talib_abstract,
        }
    )
    try:
        yield
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def _load_strategy(filename: str):
    with _strategy_import_stubs():
        path = STRATEGIES / filename
        spec = importlib.util.spec_from_file_location(f"review_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module


def test_oi_uses_nearest_eligible_baseline_and_expires_failures():
    module = _load_strategy("OITrendPullbackV1.py")
    strategy = module.OITrendPullbackV1.__new__(module.OITrendPullbackV1)
    strategy._oi_history = {"BTC/USDT": [(3_000.0, 80.0), (7_000.0, 100.0)]}
    strategy._oi_growth = {}
    strategy._oi_growth_updated = {}

    strategy._record_oi_result("BTC/USDT", 103.0, 10_000.0)
    assert strategy._oi_growth["BTC/USDT"] == pytest.approx(0.03)
    assert strategy._fresh_oi_growth("BTC/USDT", 10_900.0) == pytest.approx(0.03)
    assert strategy._fresh_oi_growth("BTC/USDT", 10_901.0) is None

    strategy._oi_growth["BTC/USDT"] = 0.05
    strategy._oi_growth_updated["BTC/USDT"] = 11_000.0
    strategy._record_oi_result("BTC/USDT", None, 11_001.0)
    assert "BTC/USDT" not in strategy._oi_growth
    assert "BTC/USDT" not in strategy._oi_growth_updated


def test_killers_stop_is_absolute_recomputed_and_after_fill_aware():
    module = _load_strategy("KillersScalpV1.py")
    strategy = module.KillersScalpV1.__new__(module.KillersScalpV1)
    strategy._sl_cache = {}
    strategy._sl_refreshing = set()
    strategy._schedule_stop_refresh = lambda trade_id: None
    trade = SimpleNamespace(
        id=7, enter_tag="signal:2144|sl:95", entry_tag=None,
        is_short=False, leverage=1.0,
    )

    first = strategy.custom_stoploss("BTC/USDC:USDC", trade, None, 100.0, 0.0, True)
    second = strategy.custom_stoploss("BTC/USDC:USDC", trade, None, 110.0, 0.1, False)

    assert strategy._sl_cache[7] == 95.0
    assert first == pytest.approx(0.95)
    assert second == pytest.approx(95.0 / 110.0)
    assert first != second  # relative value is not cached/trailing.


@pytest.mark.parametrize(
    "filename",
    ["KillersScalpV1.json", "InsidersScalpV2.json", "ShortKeltnerV2HL-live.json"],
)
def test_hyperliquid_live_configs_have_native_limit_stops(filename):
    config = json.loads((CONFIGS / filename).read_text())
    orders = config["order_types"]
    assert config["dry_run"] is False
    assert orders["stoploss"] == "limit"
    assert orders["stoploss_on_exchange"] is True
    assert orders["stoploss_on_exchange_limit_ratio"] == pytest.approx(0.98)


def test_production_compose_isolates_dry_and_live_databases_and_serializes_opens():
    compose = (ROOT / "ft_userdata" / "docker-compose.prod.yml").read_text()
    receiver = (ROOT / "services" / "killers-receiver" / "app" / "main.py").read_text()
    for bot in ("KillersScalpV1", "InsidersScalpV2", "ShortKeltnerV2HLlive"):
        assert f"tradesv3.dryrun.{bot}" in compose
        assert f"tradesv3.live.{bot}" in compose
    assert "tradesv3.snapshot.ShortKeltnerV2HL.pre-live.sqlite" in compose
    assert "app.state.entry_lock = asyncio.Lock()" in receiver
    assert "async with app.state.entry_lock" in receiver
