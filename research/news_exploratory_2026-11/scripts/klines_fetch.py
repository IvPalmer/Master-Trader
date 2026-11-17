"""Download Binance spot klines from data.binance.vision (static archive, includes delisted symbols)."""
import io, os, sys, zipfile, urllib.request, csv, time
BASE = "https://data.binance.vision/data/spot"
def get(url):
    for att in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research-script"}), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            time.sleep(2 + att * 3)
        except Exception:
            time.sleep(2 + att * 3)
    return None
def monthly(symbol, interval, ym):
    raw = get(f"{BASE}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{ym}.zip")
    return parse(raw)
def daily(symbol, interval, ymd):
    raw = get(f"{BASE}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{ymd}.zip")
    return parse(raw)
def parse(raw):
    if raw is None: return None
    z = zipfile.ZipFile(io.BytesIO(raw))
    rows = []
    for row in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))):
        if not row or not row[0].isdigit(): continue
        t = int(row[0]);  t = t // 1000 if t > 10**14 else t   # 2025+ files use microseconds
        rows.append((t, float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])))
    return rows
