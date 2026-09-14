"""Read-only production checks, explicitly enabled against the canonical VPS.

MT_VPS_INTEGRATION=1 python3 -m pytest -q tests/test_infrastructure.py
No local Docker probing, legacy symlinks, hardcoded credentials or retired bots.
"""
import json
import os
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def fleet():
    if os.environ.get('MT_VPS_INTEGRATION') != '1':
        pytest.skip('Opt in to read-only VPS checks with MT_VPS_INTEGRATION=1')
    script = (ROOT / 'deploy/vps/verify_fleet.py').read_text()
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
                             'main-instance', 'sudo', '-n', 'python3', '-'], input=script,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_running_fleet_matches_strategies(fleet):
    assert len(fleet['bots']) == 6
    for bot in fleet['bots']:
        assert 'error' not in bot, bot
        assert bot['state'] == 'running', bot
        assert bot['strategy'] == bot['expected_strategy'], bot
    assert sum(not b['dry_run'] for b in fleet['bots']) == 3


def test_live_positions_have_native_exit_coverage(fleet):
    killers = next(b for b in fleet['bots'] if b['container'] == 'ft-killers-scalp')
    for trade in killers['open_trades']:
        coin = trade['pair'].split('/')[0]
        orders = [o for o in fleet['exchange_orders'] if o['coin'] == coin and o['reduceOnly']]
        assert any(o['orderType'] == 'Stop Limit' and float(o['sz']) >= trade['amount'] for o in orders), coin
        assert any(o['orderType'] == 'Limit' for o in orders), coin


def test_actual_account_marks_and_request_health_are_observed(fleet):
    assert fleet['gateway']['ok']
    assert fleet['gateway']['status'] == 'ok', fleet['gateway']
    assert all(fleet['routing'].values()), fleet['routing']
    assert fleet['copier_subscription_contract']
    assert fleet['copier_candle_contract']
    assert fleet['dashboard']['poll_age_s'] < 180
    assert fleet['dashboard']['account_health']['complete']
    assert fleet['dashboard']['account_health']['equity'] > 0


def test_deployed_code_matches_source(fleet):
    assert all(fleet['runtime_source_matches'].values()), fleet['runtime_source_matches']
