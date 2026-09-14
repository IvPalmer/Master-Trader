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
    result['routing'] = {}
    for name, client in [('ft-killers-scalp', 'killers'), ('ft-insiders-scalp', 'insiders'), ('ft-short-keltner-hl-live', 'short')]:
        effective = exec_json(name, '''import json
from freqtrade.configuration.environment_vars import environment_vars_to_dict
from freqtrade.misc import deep_merge_dicts
files={'killers':'KillersScalpV1.json','insiders':'InsidersScalpV2.json','short':'ShortKeltnerV2HL-live.json'}
env=environment_vars_to_dict()
client=env['exchange']['ccxt_config']['urls']['api']['public'].rsplit('/',1)[-1]
c=deep_merge_dicts(env,json.load(open('/freqtrade/user_data/configs/'+files[client])))
print(json.dumps({'urls':c['exchange'].get('ccxt_config',{}).get('urls'), 'market_types':c['exchange'].get('ccxt_config',{}).get('options',{}).get('fetchMarkets',{}).get('types'), 'cancel_on_exit':c.get('cancel_open_orders_on_exit'), 'candle_limits':c['exchange'].get('_ft_has_params',{}).get('ohlcv_candle_limit_per_timeframe',{}), 'subscriptions':c['exchange'].get('pair_whitelist')}))''')
        expected = 'http://hl-gateway:8080/' + client
        result['routing'][name] = effective['urls'] == {'api': {'public': expected, 'private': expected}} and effective['cancel_on_exit'] is False and effective['market_types'] == ['swap']
        if client in {'killers', 'insiders'}:
            result['routing'][name] = result['routing'][name] and effective['candle_limits'] == {'5m': 100} and effective['subscriptions'] == ['BTC/USDC:USDC']
    # Exercise only validation/subscription functions against in-memory fakes.
    # Never invoke order submission, an exchange client, or a real RPC sender.
    result['copier_subscription_contract'] = exec_json('ft-killers-scalp', '''import json
from types import SimpleNamespace as NS
from freqtrade.rpc.rpc import RPC
from freqtrade.freqtradebot import FreqtradeBot
from freqtrade.enums import State, TradingMode, SignalDirection
pair='GRAM/USDC:USDC'
bot=NS(config={'force_entry_enable':True,'stake_currency':'USDC'}, state=State.RUNNING,
    trading_mode=TradingMode.FUTURES,
    exchange=NS(get_markets=lambda **kw:{pair:{}}, get_pair_quote_currency=lambda p:'USDC'),
    pairlists=NS(whitelist=['BTC/USDC:USDC'],refresh_pairlist=lambda:None),
    rpc=NS(send_msg=lambda message:None))
rpc=RPC.__new__(RPC); rpc._freqtrade=bot
rpc._force_entry_validations(pair,SignalDirection.LONG)
active=FreqtradeBot._refresh_active_whitelist(bot,[NS(pair=pair)])
print(json.dumps(pair in active and 'BTC/USDC:USDC' in active))''')
    # Execute the pinned exchange's option lookup without initializing a live
    # exchange. Funding history must retain its separate 1h page sizes.
    result['copier_candle_contract'] = exec_json('ft-killers-scalp', '''import json,ccxt
from types import SimpleNamespace as NS, MethodType
from freqtrade.exchange import Exchange
from freqtrade.exchange.hyperliquid import Hyperliquid
from freqtrade.configuration.environment_vars import environment_vars_to_dict
from freqtrade.enums import CandleType
from freqtrade.misc import deep_merge_dicts
c=environment_vars_to_dict()
options=deep_merge_dicts(c['exchange'].get('_ft_has_params',{}),Hyperliquid.combine_ft_has(include_futures=True))
fake=NS(_ft_has=options,_api_async=ccxt.hyperliquid())
fake.features=MethodType(Exchange.features,fake)
limit=lambda tf,typ: Exchange.ohlcv_candle_limit(fake,tf,typ)
print(json.dumps(options['mark_ohlcv_timeframe']=='1h' and options['funding_fee_timeframe']=='1h'
    and limit('5m',CandleType.FUTURES)==100
    and limit('1h',CandleType.FUTURES)==5000
    and limit('1h',CandleType.FUNDING_RATE)==500))''')
    result['native_market_contract'] = exec_json('ft-killers-scalp', '''import json,ccxt
from freqtrade.configuration.environment_vars import environment_vars_to_dict
from freqtrade.misc import deep_merge_dicts
c=deep_merge_dicts(environment_vars_to_dict(),json.load(open('/freqtrade/user_data/configs/KillersScalpV1.json')))
exchange=ccxt.hyperliquid(c['exchange']['ccxt_config'])
calls=[]
exchange.fetch_swap_markets=lambda params: calls.append('swap') or []
exchange.fetch_spot_markets=lambda params: calls.append('spot') or []
exchange.fetch_hip3_markets=lambda params: calls.append('hip3') or []
exchange.fetch_markets()
exchange.markets={}
exchange.fetch_tickers()
print(json.dumps(calls==['swap','swap']))''')
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
