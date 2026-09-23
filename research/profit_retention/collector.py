"""Read-only VPS observer. Private append-only tape; no exchange signing/order API.

Host: python collector.py --once --directory /private/shadow
Fetch mode runs via docker exec in the dashboard's existing network/auth context.
Only GET Freqtrade and POST Hyperliquid /info are permitted by this implementation.
"""
import argparse
import base64
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

VERSION = 'killers-retention-shadow-v1'


def fetch():
    user = os.environ.get('FT_API_USER_KILLERS') or os.environ['FREQTRADE__API_SERVER__USERNAME']
    password = os.environ.get('FT_API_PASS_KILLERS') or os.environ['FREQTRADE__API_SERVER__PASSWORD']
    auth = 'Basic '+base64.b64encode(f'{user}:{password}'.encode()).decode()

    def ft(path):
        req = urllib.request.Request('http://ft-killers-scalp:8080/api/v1/'+path,
                                     headers={'Authorization':auth})
        with urllib.request.urlopen(req,timeout=35) as response:
            return json.load(response)

    def info(body):
        req = urllib.request.Request('https://api.hyperliquid.xyz/info',data=json.dumps(body).encode(),
                                     headers={'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(req,timeout=10) as response:
            return json.load(response)

    began = time.time()
    opened = ft('status')
    closed = ft('trades?limit=500&offset=0')
    if closed.get('total_trades',closed.get('trades_count',0)) > 500:
        raise ValueError('Trade pagination limit requires a versioned collector update')
    trades = {str(t['trade_id']):t for t in closed['trades']}
    trades.update({str(t['trade_id']):t for t in opened})
    meta_start = time.time()
    meta, ctxs = info({'type':'metaAndAssetCtxs'})
    meta_end = time.time()
    context = {asset['name']:ctx for asset,ctx in zip(meta['universe'],ctxs)}
    market = {}
    for coin in sorted({t['base_currency'] for t in opened if t.get('amount',0)>0}):
        if coin not in context:
            market[coin] = {'error':'asset_not_in_context'}
            continue
        book = info({'type':'l2Book','coin':coin})
        market[coin] = {'mark':float(context[coin]['markPx']), 'funding_rate':context[coin]['funding'],
                        'mark_requested':meta_start,'mark_received':meta_end,
                        'book_time':book['time']/1000, 'levels':book['levels'], 'received':time.time()}
    # All content remains private; never print this fetch payload to user logs.
    return {'version':VERSION,'started':began,'ts':time.time(),'trades':list(trades.values()),'market':market}


def collect(directory):
    os.umask(0o077)
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    if directory.stat().st_mode & 0o077:
        raise ValueError('Observation directory must be private (0700)')
    with (directory/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        source = Path(__file__).read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        manifest = directory/'manifest.json'
        if manifest.exists():
            protocol = json.loads(manifest.read_text())
            if protocol['collector_sha256'] != digest:
                raise ValueError('Collector changed; use a new version and directory')
        else:
            protocol = {'version':VERSION,'start':time.time(),'collector_sha256':digest,
                        'policy':'arm_2r_trail_1r','poll_seconds':60,'max_gap_seconds':120,
                        'status':'forward_observations_only_no_live_orders'}
            with manifest.open('x') as f:
                json.dump(protocol,f,indent=2)
                f.flush()
                os.fsync(f.fileno())
        result = subprocess.run(['docker','exec','-i','ft-dashboard','python3','-','--fetch'],
                                input=source,capture_output=True,timeout=100)
        if result.returncode:
            # stderr can contain remote response bodies or auth context; do not log it.
            raise RuntimeError('Read-only snapshot failed; no observation credited')
        snapshot = json.loads(result.stdout)
        snapshot['collector_sha256'] = digest
        day = datetime.fromtimestamp(snapshot['ts'],timezone.utc).strftime('%Y%m%d')
        with (directory/f'observations-{day}.jsonl').open('a') as f:
            f.write(json.dumps(snapshot,separators=(',',':'))+'\n')
            f.flush()
            os.fsync(f.fileno())
        summary = {'ok':True,'version':VERSION,'ts':snapshot['ts'],
                   'observed_trades':len(snapshot['trades']),'market_count':len(snapshot['market'])}
        temporary = directory/'health.tmp'
        temporary.write_text(json.dumps(summary))
        temporary.replace(directory/'health.json')
        return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--fetch',action='store_true')
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--directory',type=Path)
    args = parser.parse_args()
    try:
        if args.fetch:
            print(json.dumps(fetch()))
        elif args.once and args.directory:
            print(json.dumps(collect(args.directory)))
        else:
            parser.error('Use --once --directory PATH or --fetch')
    except Exception as exc:
        print(json.dumps({'ok':False,'error_type':type(exc).__name__}),file=sys.stderr)
        sys.exit(1)
