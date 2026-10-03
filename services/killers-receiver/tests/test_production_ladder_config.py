"""The reviewed production env must fund the equal source ladder (#106).

Reads the killers-receiver environment from docker-compose.prod.yml and runs
it through the real sizing and legacy planner, using posted levels from live
signals whose stop distances cover the channel's range (9-14.5%).
"""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.main import compute_stake
from app.tp_plan import executable_targets


COMPOSE = Path(__file__).resolve().parents[3] / "ft_userdata" / "docker-compose.prod.yml"


def _env():
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    return services["killers-receiver"]["environment"]


def _cfg(env):
    return SimpleNamespace(
        stake_usd=10.0,
        leverage=2.0,
        risk_usd=float(env["KILLERS_RISK_USD"]),
        min_margin_usd=float(env["KILLERS_MIN_MARGIN_USD"]),
        max_margin_usd=float(env["KILLERS_MAX_MARGIN_USD"]),
        max_leverage=float(env["KILLERS_MAX_LEVERAGE"]),
        stop_limit_ratio=float(env["KILLERS_STOP_LIMIT_RATIO"]),
        min_notional_usd=float(env["KILLERS_MIN_NOTIONAL_USD"]),
        bump_to_min_notional=env["KILLERS_BUMP_TO_MIN_NOTIONAL"] == "true",
        max_bump_risk_usd=float(env["KILLERS_MAX_BUMP_RISK_USD"]),
    )


# symbol, fill, posted SL, posted targets, Hyperliquid size step
SIGNALS = [
    ("DOT", 0.84007, 0.75, [0.86, 0.9, 0.95, 1.0, 1.06, 1.13, 1.21, 1.3, 1.4], 0.1),
    ("TRX", 0.33934, 0.315, [0.35, 0.362, 0.375, 0.39, 0.41, 0.435, 0.465, 0.5], 1),
    ("LINK", 10.684, 9.5, [11.0, 11.5, 12.1, 12.7, 13.5, 14.5, 15.75, 17.0], 0.1),
    ("ARB", 0.20636, 0.18, [0.211, 0.22, 0.2325, 0.245, 0.26, 0.2775, 0.2975, 0.32], 0.1),
    ("POL", 0.10094, 0.09, [0.105, 0.11, 0.1175, 0.125, 0.1325, 0.14, 0.15, 0.16], 1),
    ("HYPE", 91.399, 81.0, [94.5, 99.0, 104.0, 110.0, 117.5, 127.0, 137.5, 150.0], 0.01),
    ("RENDER", 1.95, 1.71, [2.0, 2.1, 2.225, 2.35, 2.5, 2.65, 2.8, 3.0], 0.1),
    ("AERO", 0.8, 0.72, [0.84, 0.88, 0.93, 0.99, 1.05, 1.12, 1.2, 1.3], 1),
]


def test_entry_chases_up_to_5pct_then_skips():
    env = _env()
    assert env["KILLERS_MAX_ENTRY_SLIPPAGE_PCT"] == "5.0"
    assert env["KILLERS_ENTRY_LIMIT_IN_ZONE"] == "false"


def test_pinned_equal_ladder_policy():
    env = _env()
    assert env["KILLERS_TP_MODE"] == "legacy"
    assert env["KILLERS_TP_ALLOCATIONS"] == ""


@pytest.mark.parametrize("symbol, fill, sl, targets, step", SIGNALS)
def test_production_size_funds_a_ladder_leg_per_target(monkeypatch, symbol, fill, sl, targets, step):
    monkeypatch.setenv("KILLERS_EXECUTION_VENUE", "hyperliquid")
    cfg = _cfg(_env())
    stake, leverage, distance = compute_stake(
        {"direction": "long", "entry": fill, "sl": sl}, cfg,
        effective_entry=fill, stop_limit_ratio=cfg.stop_limit_ratio,
    )
    notional = stake * leverage
    assert leverage == int(leverage) <= cfg.max_leverage
    assert stake <= cfg.max_margin_usd
    # Planned loss at the adverse stop-limit edge stays within the budget.
    assert notional * distance <= cfg.risk_usd + 1e-6
    assert notional >= 80

    step_d = Decimal(str(step))
    amount = float((Decimal(str(notional / fill)) / step_d).to_integral_value(rounding="ROUND_FLOOR") * step_d)
    # As at arming: the snapshot may still carry the strategy's initial
    # -0.07 stop; the receiver passes the posted stop for the later ratio.
    trade = {
        "amount": amount, "is_open": True, "nr_of_successful_entries": 1,
        "is_short": False, "stop_loss_ratio": -0.07,
        "open_rate": fill, "leverage": leverage,
        "amount_precision": step, "precision_mode": 4,
        "price_precision": 0.00001, "precision_mode_price": 4,
        "contract_size": 1, "orders": [],
    }
    plan = executable_targets(trade, targets, 10, planned_stop=sl)

    indices = [idx for idx, _, _ in plan]
    # Every leg is executable and the ladder sells everything by the last target.
    assert all(qty * price >= 10 for _, price, qty in plan)
    assert sum(Decimal(str(q)) for _, _, q in plan) == Decimal(str(amount))
    assert indices[-1] == len(targets) - 1
    # The ladder starts at TP1 (no roll-forward of the first slice) and uses
    # at least all but one posted target; at $2 risk it was a single exit.
    assert indices[0] == 0
    assert len(plan) >= len(targets) - 1
