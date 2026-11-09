"""Strategy-managed exit policy shown on position cards (#41).

The ROI table, stoploss and trailing settings come from each bot's
/show_config. Time rules and exit signals are not reported by Freqtrade, so
app.STRATEGY_EXIT_RULES mirrors them; these tests parse the strategy source and
fail when the mirror drifts.
"""
import ast
import asyncio
from pathlib import Path

import pytest

import app

STRATEGIES = Path(__file__).resolve().parents[2] / "user_data" / "strategies"


def _module(strategy: str) -> ast.Module:
    return ast.parse((STRATEGIES / f"{strategy}.py").read_text())


def _class_attr(strategy: str, name: str):
    for node in ast.walk(_module(strategy)):
        if isinstance(node, ast.ClassDef) and node.name == strategy:
            for item in node.body:
                if (isinstance(item, ast.Assign) and len(item.targets) == 1
                        and isinstance(item.targets[0], ast.Name) and item.targets[0].id == name):
                    return ast.literal_eval(item.value)
    raise AssertionError(f"{strategy}.{name} not found")


def _custom_exit_time_rules(strategy: str) -> set[tuple]:
    """(after_hours, profit_below | None, reason) for each `if hours >= N ...: return "reason"`."""
    functions = [node for node in ast.walk(_module(strategy))
                 if isinstance(node, ast.FunctionDef) and node.name == "custom_exit"]
    rules = set()
    for function in functions:
        for node in ast.walk(function):
            if not (isinstance(node, ast.If) and node.body and isinstance(node.body[0], ast.Return)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                continue
            hours = profit_below = None
            for compare in ast.walk(node.test):
                if not (isinstance(compare, ast.Compare) and len(compare.ops) == 1
                        and isinstance(compare.comparators[0], ast.Constant)):
                    continue
                left, value = ast.unparse(compare.left), compare.comparators[0].value
                if isinstance(compare.ops[0], ast.GtE) and "hours" in left:
                    hours = value
                elif isinstance(compare.ops[0], ast.Lt) and left == "current_profit":
                    profit_below = float(value)
            if hours is not None:
                rules.add((hours, profit_below, node.body[0].value.value))
    return rules


def _string_constants(strategy: str) -> set[str]:
    return {node.value for node in ast.walk(_module(strategy))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def test_every_bot_declares_its_strategy_exit_rules():
    assert {bot["key"] for bot in app.BOTS} == set(app.STRATEGY_EXIT_RULES)


@pytest.mark.parametrize("bot_key", sorted(app.STRATEGY_EXIT_RULES))
def test_declared_time_rules_match_strategy_source(bot_key):
    declared = app.STRATEGY_EXIT_RULES[bot_key]
    strategy = declared["strategy"]
    expected = {(rule["after_hours"], rule["profit_below"], rule["reason"])
                for rule in declared["rules"] if rule["kind"] == "time"}
    assert _custom_exit_time_rules(strategy) == expected


@pytest.mark.parametrize("bot_key", sorted(app.STRATEGY_EXIT_RULES))
def test_declared_rules_are_reachable_exit_reasons(bot_key):
    declared = app.STRATEGY_EXIT_RULES[bot_key]
    strategy = declared["strategy"]
    reasons = _string_constants(strategy)
    for rule in declared["rules"]:
        assert rule["reason"] in reasons
    # custom_exit and dataframe exit signals only run when use_exit_signal is
    # set; a receiver-driven bot must not hide its own time or signal exits.
    expected = declared.get("exit_signals", not declared.get("receiver_driven", False))
    assert _class_attr(strategy, "use_exit_signal") is expected


def test_policy_normalizes_reported_roi_and_trailing():
    policy = app._exit_policy({
        "minimal_roi": {"720": 0.03, "0": "0.08", "360.0": 0.05, "bad": 1},
        "stoploss": -0.06,
        "trailing_stop": True,
        "trailing_stop_positive": 0.03,
        "trailing_stop_positive_offset": 0.05,
        "trailing_only_offset_is_reached": True,
    }, "keltner")
    assert policy["roi"] == [[0, 0.08], [360, 0.05], [720, 0.03]]
    assert policy["stoploss"] == -0.06
    assert policy["trailing"] == {"enabled": True, "positive": 0.03, "offset": 0.05,
                                  "only_offset_reached": True}
    assert policy["rules"] == app.STRATEGY_EXIT_RULES["keltner"]["rules"]
    assert policy["receiver_driven"] is False


def test_policy_marks_unreported_settings_unknown_not_off():
    policy = app._exit_policy({}, "killers-ft")
    assert policy["roi"] is None
    assert policy["trailing"] is None
    assert policy["stoploss"] is None
    assert policy["receiver_driven"] is True
    assert app._exit_policy({"trailing_stop": False}, "fundingfade")["trailing"] == {"enabled": False}


def test_policy_returns_copies_of_declared_rules():
    policy = app._exit_policy({}, "fundingfade")
    policy["rules"][0]["after_hours"] = 1
    assert app.STRATEGY_EXIT_RULES["fundingfade"]["rules"][0]["after_hours"] == 96


def test_poll_snapshot_carries_exit_policy_and_trade_leverage(monkeypatch):
    bot = app._bot_meta("short-keltner-hl")
    payloads = {
        "profit": {"bot_start_timestamp": 0},
        "status": [{"trade_id": 7, "pair": "ETH/USDC:USDC", "is_open": True, "is_short": True,
                    "leverage": 3.0, "open_rate": 100.0, "current_rate": 99.0,
                    "open_timestamp": 1_790_000_000_000, "amount": 0.3, "stake_amount": 10.0,
                    "nr_of_successful_entries": 1, "nr_of_successful_exits": 0, "orders": []}],
        "balance": {"starting_capital": 40.0, "total_bot": 40.0, "total": 40.0},
        "show_config": {"dry_run": False, "timeframe": "1h", "stoploss": -0.05,
                        "minimal_roi": {"0": 0.06, "2160": 0.0}, "trailing_stop": False},
        "whitelist": {"whitelist": []},
    }

    async def fake_get(client, url, path, *args, **kwargs):
        return payloads.get(path.split("?")[0]), None

    async def fake_history(client, bot, epoch_start_ts_ms):
        return [], True, None

    monkeypatch.setattr(app, "_get", fake_get)
    monkeypatch.setattr(app, "_fetch_epoch_trades", fake_history)
    snapshot = asyncio.run(app._poll_bot(None, bot))
    assert snapshot["reachable"] is True
    assert snapshot["open_trades"][0]["leverage"] == 3.0
    assert snapshot["exit_policy"]["roi"] == [[0, 0.06], [2160, 0.0]]
    assert snapshot["exit_policy"]["trailing"] == {"enabled": False}
    assert [rule["reason"] for rule in snapshot["exit_policy"]["rules"]] == [
        "time_exit_36h", "regime_flip_or_oversold"]
