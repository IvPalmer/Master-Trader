"""#220: Freqtrade must never expire the Killers receiver's resting take-profits.

The receiver places every source take-profit as a resting limit exit through
/forceexit. With ``unfilledtimeout.exit`` set, Freqtrade cancels such a limit
once it is older than the timeout (``ft_check_timed_out`` reads the config
before the strategy's ``check_exit_timeout`` callback, so a callback cannot
veto it). The cancelled zero-fill order then disappears from /trade/{id} and
the receiver parks the rung as ``unknown``. With the key absent the config
check is skipped and the default callback returns False.

Freqtrade is not installed in CI; the in-image behavior is asserted by the
``exit_timeout_contract`` check in deploy/vps/verify_fleet.py.
"""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "ft_userdata" / "user_data" / "configs" / "KillersScalpV1.json"
STRATEGY = ROOT / "ft_userdata" / "user_data" / "strategies" / "KillersScalpV1.py"


def _config() -> dict:
    return json.loads(CONFIG.read_text())


def _strategy_class() -> ast.ClassDef:
    tree = ast.parse(STRATEGY.read_text())
    return next(node for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == "KillersScalpV1")


def test_killers_has_no_exit_timeout():
    timeout = _config()["unfilledtimeout"]
    assert "exit" not in timeout
    # Freqtrade maps the deprecated 'sell' key to 'exit' at config validation.
    assert "sell" not in timeout
    assert "_exit_note" in timeout


def test_killers_entry_timeout_and_no_emergency_exit_unchanged():
    timeout = _config()["unfilledtimeout"]
    assert timeout["entry"] == 1440
    assert timeout["unit"] == "minutes"
    # A timed-out exit never escalates to an emergency market exit.
    assert timeout["exit_timeout_count"] == 0


def test_killers_stop_stays_exchange_resident():
    # Stoploss orders are excluded from Freqtrade's timeout handling
    # (Trade.open_orders); keep them on the exchange.
    assert _config()["order_types"]["stoploss_on_exchange"] is True


def test_strategy_cannot_reintroduce_or_override_the_timeout():
    cls = _strategy_class()
    assigned = {target.id
                for node in cls.body if isinstance(node, (ast.Assign, ast.AnnAssign))
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
                if isinstance(target, ast.Name)}
    methods = {node.name for node in cls.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "unfilledtimeout" not in assigned
    # Overrides here could cancel or replace a resting take-profit.
    assert not methods & {"check_exit_timeout", "check_sell_timeout",
                          "adjust_exit_price", "adjust_order_price"}
