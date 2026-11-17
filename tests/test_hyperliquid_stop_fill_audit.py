import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "audit_hyperliquid_stop_fill", ROOT / "scripts" / "audit_hyperliquid_stop_fill.py"
)
assert SPEC and SPEC.loader
audit_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_module)


def fixture_payload():
    path = ROOT / "tests" / "fixtures" / "hyperliquid_partial_tp_stop.json"
    return json.loads(path.read_text())


def test_avax_partial_tp_stop_replay_uses_order_specific_exchange_fill():
    result = audit_module.audit(fixture_payload())

    assert result["ccxt_4_5_4_filled"] == pytest.approx(8.33)
    assert result["reported_filled"] == pytest.approx(8.33)
    assert result["exchange_filled"] == pytest.approx(7.29)
    assert result["overbooked_quantity"] == pytest.approx(1.04)
    assert result["exchange_average"] == pytest.approx(9.9851)
    assert result["reported_replay_profit_abs"] == pytest.approx(-10.04074610245)
    assert result["exchange_replay_profit_abs"] == pytest.approx(-8.72941658685)
    assert result["reported_minus_exchange_profit_abs"] == pytest.approx(-1.31132951560)
    assert result["loss_overstatement_abs"] == pytest.approx(1.31132951560)


def test_only_fills_for_the_requested_order_are_authoritative():
    payload = fixture_payload()
    payload["exchange_fills"].append(
        {"order_id": "another-order", "amount": 99, "price": 1}
    )

    result = audit_module.audit(payload)

    assert result["exchange_filled"] == pytest.approx(7.29)


def test_missing_order_specific_fills_cannot_silently_rewrite_history():
    payload = fixture_payload()
    payload["exchange_fills"] = []

    with pytest.raises(ValueError, match="no exchange fills found"):
        audit_module.audit(payload)
