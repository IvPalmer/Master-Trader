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


def test_oi_price_exit_uses_custom_exit_without_same_candle_entry_veto():
    pd = pytest.importorskip("pandas")
    from datetime import datetime, timezone

    module = _load_strategy("OITrendPullbackV1.py")
    strategy = module.OITrendPullbackV1.__new__(module.OITrendPullbackV1)
    frame = pd.DataFrame(
        {
            "close": [99.0, 99.0, 101.0],
            "ema50": [100.0, 100.0, 100.0],
            "oi_growth": [float("nan"), 0.02, -0.02],
            "date": pd.to_datetime(
                ["2026-08-24T18:00:00Z", "2026-08-24T19:00:00Z", None],
                utc=True,
            ),
        }
    )

    result = strategy.populate_exit_trend(frame.copy(), {})

    # No dataframe exit signal: Freqtrade may admit an EMA20 reclaim below
    # EMA50 instead of silently vetoing enter_long on the same candle.
    assert result["exit_long"].tolist() == [0, 0, 0]

    trade = SimpleNamespace(
        open_date_utc=datetime(2026, 8, 24, 18, 0, tzinfo=timezone.utc)
    )

    # The entry candle cannot immediately unwind the new trade, even below
    # EMA50. The first complete candle that began after entry can exit it.
    strategy.dp = SimpleNamespace(
        get_analyzed_dataframe=lambda pair, timeframe: (frame.iloc[:1], None)
    )
    assert strategy.custom_exit(
        "BTC/USDT", trade, None, 99.0, -0.01
    ) is None
    strategy.dp = SimpleNamespace(
        get_analyzed_dataframe=lambda pair, timeframe: (frame.iloc[1:2], None)
    )
    assert strategy.custom_exit(
        "BTC/USDT", trade, None, 99.0, -0.01
    ) == "ema50_break"

    # Warm-up/invalid timestamps and a price above EMA50 remain safe no-ops.
    strategy.dp = SimpleNamespace(
        get_analyzed_dataframe=lambda pair, timeframe: (frame.iloc[-1:], None)
    )
    assert strategy.custom_exit(
        "BTC/USDT", trade, None, 101.0, 0.01
    ) is None


def test_killers_stop_is_absolute_recomputed_and_after_fill_aware():
    module = _load_strategy("KillersScalpV1.py")
    strategy = module.KillersScalpV1.__new__(module.KillersScalpV1)
    strategy._sl_cache = {}
    strategy._sl_cache_updated = {}
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


def test_killers_rejects_freqtrade_minimum_stake_bump():
    module = _load_strategy("KillersScalpV1.py")
    strategy = module.KillersScalpV1.__new__(module.KillersScalpV1)

    rejected = strategy.custom_stake_amount(
        "BTC/USDC:USDC", None, 100.0, 4.99, 5.0, 100.0, 3.0,
        "signal:1|sl:95", "long",
    )
    accepted = strategy.custom_stake_amount(
        "BTC/USDC:USDC", None, 100.0, 5.0, 5.0, 100.0, 3.0,
        "signal:1|sl:95", "long",
    )

    assert rejected == 0.0
    assert accepted == 5.0


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


def test_production_freqtrade_image_is_digest_pinned_and_funding_v2_isolated():
    compose = (ROOT / "ft_userdata" / "docker-compose.prod.yml").read_text()
    funding = json.loads((CONFIGS / "FundingFadeV1.live.json").read_text())
    digest = (
        "freqtradeorg/freqtrade@sha256:"
        "50720a4af314a812be2cfbf5cc6331c63e9332b06f3f4372241f54bc61a35486"
    )

    assert "freqtradeorg/freqtrade:stable" not in compose
    assert compose.count(digest) == 7
    assert funding["db_url"].endswith("tradesv3.live.FundingFadeV1.v2.sqlite")
