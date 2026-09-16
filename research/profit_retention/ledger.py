"""Private, unsigned Hyperliquid fill/funding ledger. No order/signing capability."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request


def fetch_interval(request, kind, start, end):
    """Split saturated intervals, preserving events sharing a millisecond."""
    rows = request({'type':kind,'startTime':start,'endTime':end})
    if not isinstance(rows,list):
        raise ValueError('Invalid ledger response')
    if len(rows) < 500:
        if any(not start <= r['time'] <= end for r in rows):
            raise ValueError('Out-of-window ledger response')
        return rows
    if start == end:
        raise ValueError('Saturated millisecond; cannot establish complete history')
    mid = (start+end)//2
    return fetch_interval(request,kind,start,mid)+fetch_interval(request,kind,mid+1,end)


def fetch(start,end):
    # Read the public account address only; never read the private-key variable.
    account = os.environ['FREQTRADE__EXCHANGE__WALLET_ADDRESS']
    def request(body):
        body = dict(body,user=account)
        req = urllib.request.Request('https://api.hyperliquid.xyz/info',
            data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(req,timeout=15) as response:
            return json.load(response)
    fees=request({'type':'userFees'})
    fee_observation={'ts':int(time.time()*1000),'taker_rate':float(fees['userCrossRate'])}
    return {'fee_observation':fee_observation,'start_ms':start,'end_ms':end,'received_ms':int(time.time()*1000),
            'fills':fetch_interval(request,'userFillsByTime',start,end),
            'funding':fetch_interval(request,'userFunding',start,end)}


def collect(directory):
    os.umask(0o077)
    if directory.stat().st_mode & 0o077:
        raise ValueError('Ledger directory must be private')
    with (directory/'ledger.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        cursor_file = directory/'ledger-cursor.json'
        now = int(time.time()*1000)
        if cursor_file.exists():
            start = json.loads(cursor_file.read_text())['end_ms']-7200000
        else:
            start = now-90*86400000
        source = Path(__file__).read_bytes()
        proc = subprocess.run(['docker','exec','-i','ft-killers-scalp','python3','-',
            '--fetch',str(start),str(now)],input=source,capture_output=True,timeout=240)
        if proc.returncode:
            raise RuntimeError('Ledger read failed')
        payload = json.loads(proc.stdout)
        # Timestamp-named immutable batches. Cursor advances only after durable write.
        ledger = directory/'ledger'
        ledger.mkdir(mode=0o700,exist_ok=True)
        temporary = ledger/f'{now}.tmp'
        with temporary.open('x') as f:
            json.dump(payload,f,separators=(',',':'))
            f.flush()
            os.fsync(f.fileno())
        temporary.rename(ledger/f'{now}.json')
        health = {'ok':True,'end_ms':now,'fill_count':len(payload['fills']),
                  'funding_count':len(payload['funding'])}
        temp_cursor = directory/'ledger-cursor.tmp'
        temp_cursor.write_text(json.dumps(health))
        temp_cursor.replace(cursor_file)
        return health


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--fetch',nargs=2,type=int)
    p.add_argument('--directory',type=Path)
    a=p.parse_args()
    try:
        print(json.dumps(fetch(*a.fetch) if a.fetch else collect(a.directory)))
    except Exception as exc:
        print(json.dumps({'ok':False,'error_type':type(exc).__name__}),file=sys.stderr)
        sys.exit(1)
