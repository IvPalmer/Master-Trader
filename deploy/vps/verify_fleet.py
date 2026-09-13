#!/usr/bin/env python3
"""Read-only fleet verification. Run on the VPS, never start local services."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path('/etc/dokploy/compose/compose-bypass-mobile-port-fbk1m6/code')
BOTS = [('ft-keltner-bounce', 8095, 'KeltnerBounceV1'),
        ('ft-funding-fade', 8096, 'FundingFadeV1'),
        ('ft-oi-trend-pullback', 8102, 'OITrendPullbackV1'),
        ('ft-killers-scalp', 8099, 'KillersScalpV1'),
        ('ft-insiders-scalp', 8098, 'KillersScalpV1'),
        ('ft-short-keltner-hl-live', 8103, 'ShortKeltnerV2HL')]


def container(name):
    return json.loads(subprocess.check_output(['docker', 'inspect', name], text=True))[0]


def exec_json(name, script):
    return json.loads(subprocess.check_output(['docker', 'exec', '-i', name, 'python', '-'], input=script, text=True))


def verify():
    result = {'commit': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(), 'bots': []}
    for name, port, expected in BOTS:
        try:
            meta = container(name)
            env = dict(x.split('=', 1) for x in meta['Config']['Env'] if '=' in x)
            auth = base64.b64encode((env['FREQTRADE__API_SERVER__USERNAME'] + ':' + env['FREQTRADE__API_SERVER__PASSWORD']).encode()).decode()
            def get(endpoint):
                req = urllib.request.Request(f'http://127.0.0.1:{port}/api/v1/{endpoint}', headers={'Authorization': 'Basic ' + auth})
                return json.load(urllib.request.urlopen(req, timeout=15))
            config = get('show_config')
            trades = get('status')
            result['bots'].append({'container': name, 'state': config['state'], 'strategy': config['strategy'],
                'expected_strategy': expected, 'dry_run': config['dry_run'],
                'restarts': meta['RestartCount'], 'open_trades': [{k: t.get(k) for k in ['trade_id', 'pair', 'amount', 'current_rate', 'stop_loss_abs']} for t in trades]})
            if name == 'ft-killers-scalp':
                req = urllib.request.Request('https://api.hyperliquid.xyz/info', data=json.dumps({'type': 'frontendOpenOrders', 'user': env['FREQTRADE__EXCHANGE__WALLET_ADDRESS']}).encode(), headers={'Content-Type': 'application/json'})
                orders = json.load(urllib.request.urlopen(req, timeout=20))
                result['exchange_orders'] = [{k: o.get(k) for k in ['coin', 'oid', 'sz', 'limitPx', 'triggerPx', 'orderType', 'reduceOnly']} for o in orders]
        except Exception as exc:
            result['bots'].append({'container': name, 'error': type(exc).__name__})
    result['dashboard'] = exec_json('ft-dashboard', '''import json,urllib.request
j=json.load(urllib.request.urlopen('http://localhost:8000/api/state'))
print(json.dumps({k:j.get(k) for k in ['status','poll_age_s','account_health']}))''')
    result['gateway'] = exec_json('ft-hl-gateway', "import json,urllib.request; print(urllib.request.urlopen('http://localhost:8080/healthz').read().decode())")
    result['runtime_source_matches'] = {}
    for name, deployed, source in [('killers-receiver','/app/app/main.py','services/killers-receiver/app/main.py'),
            ('insiders-receiver','/app/app/main.py','services/killers-receiver/app/main.py'),
            ('ft-hl-gateway','/app/app/main.py','services/hl-gateway/app/main.py'),
            ('ft-dashboard','/app/app.py','ft_userdata/ft_dashboard/app.py'),
            ('ft-metrics-exporter','/app/metrics_exporter.py','ft_userdata/metrics_exporter.py')]:
        code = 'import json,hashlib,pathlib; print(json.dumps(hashlib.sha256(pathlib.Path('+repr(deployed)+').read_bytes()).hexdigest()))'
        actual = exec_json(name, code)
        result['runtime_source_matches'][name] = actual == hashlib.sha256((ROOT / source).read_bytes()).hexdigest()
    return result


if __name__ == '__main__':
    print(json.dumps(verify()))
