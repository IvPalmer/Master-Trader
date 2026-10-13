"""ShortKeltnerV2HL signal study, GROSS vs NET of venue costs (issue #1).

Entry/exit rules mirror ft_userdata/user_data/strategies/ShortKeltnerV2HL.py
(rejection of the upper Keltner band, RSI>60 within 2 bars, volume > 1.75x,
BTC bear gate; stop -5%, ROI ladder, regime-flip/RSI<30 exit, 36h time exit).
All costs come from ft_userdata.analysis.costs (hyperliquid/perp fees, funding
accrued from real settled rates, slippage prior). Binance USDT klines proxy
Hyperliquid candles (same caveat as the 2026-08-29 note).

The simulation core takes DataFrames and is network-free; ``main`` fetches.
    python research/shortkeltner_net/study.py [--months 20]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ft_userdata.analysis.costs import FundingSeries, trade_costs  # noqa: E402

KP, KM, VM, VP, RSI_OB = 25, 2.5, 1.75, 20, 60
STOP = 0.05
ROI = [(0, 0.06), (360, 0.04), (720, 0.025), (1440, 0.015), (2160, 0.0)]  # minutes
MAX_HOURS = 36


def atr(d, n):
    tr = pd.concat([d.h - d.l, (d.h - d.c.shift(1)).abs(), (d.l - d.c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def rsi(s, n=14):
    x = s.diff()
    up, dn = x.clip(lower=0), -x.clip(upper=0)
    return 100 - 100 / (1 + up.ewm(alpha=1 / n, adjust=False).mean() / dn.ewm(alpha=1 / n, adjust=False).mean())


def btc_gate(btc1h: pd.DataFrame, btc1d: pd.DataFrame) -> pd.Series:
    sma50, sma200 = btc1h.c.rolling(50).mean(), btc1h.c.rolling(200).mean()
    d200 = btc1d.c.rolling(200).mean().shift(1).reindex(btc1h.index, method="ffill")
    return ((btc1h.c < sma50) & (btc1h.c < sma200) & ((sma50 - sma50.shift(24)) < 0) & (btc1h.c < d200))


def roi_target(hours_open: float) -> float:
    t = 0.0
    for minutes, v in ROI:
        if hours_open * 60 >= minutes:
            t = v
    return t


def simulate_pair(d: pd.DataFrame, gate: pd.Series, regime_flip: pd.Series) -> list[dict]:
    """Return gross short trades [{open, close, entry, exit, gross, reason}]."""
    sma, a = d.c.rolling(KP).mean(), atr(d, KP)
    up = sma + KM * a
    r = rsi(d.c)
    vol = d.v > VM * d.v.rolling(VP).mean()
    sig = ((d.c < up) & (d.c.shift(1) >= up.shift(1)) & vol
           & ((r.shift(1) > RSI_OB) | (r.shift(2) > RSI_OB))
           & gate.reindex(d.index, method="ffill").fillna(False))
    exit_sig = (regime_flip.reindex(d.index, method="ffill").fillna(False) | (r < 30))
    idx, trades, i, n = d.index, [], 0, len(d)
    while i < n - 1:
        if not sig.iloc[i]:
            i += 1
            continue
        entry, j, res = float(d.o.iloc[i + 1]), i + 1, None
        open_ts = idx[i + 1]
        while j < n and res is None:
            hrs = (idx[j] - open_ts).total_seconds() / 3600
            if j > i + 1 and exit_sig.iloc[j - 1]:
                res = (float(d.o.iloc[j]), "signal_exit")
            elif d.h.iloc[j] >= entry * (1 + STOP):
                res = (entry * (1 + STOP), "stoploss")
            elif d.l.iloc[j] <= entry * (1 - roi_target(hrs)) and roi_target(hrs) > 0:
                res = (entry * (1 - roi_target(hrs)), "roi")
            elif hrs >= MAX_HOURS:
                res = (float(d.o.iloc[j]), "time_exit_36h")
            j += 1
        if res is None:
            break
        close_ts = idx[j - 1] + (pd.Timedelta(hours=1) if res[1] in ("stoploss", "roi") else pd.Timedelta(0))
        trades.append({"open": idx[i + 1], "close": close_ts, "entry": entry, "exit": res[0],
                       "gross": (entry - res[0]) / entry, "reason": res[1]})
        i = j
    return trades


def net_trades(trades: list[dict], pair: str, funding: FundingSeries, *, slippage_bps: float | None = None,
               entry_liq: str = "taker") -> pd.DataFrame:
    rows = []
    for t in trades:
        kw = {} if slippage_bps is None else {"slippage_bps": slippage_bps}
        c = trade_costs("hyperliquid", "perp", pair, "short", 1.0,
                        t["open"].to_pydatetime(), max(t["close"], t["open"] + pd.Timedelta(hours=1)).to_pydatetime(),
                        entry=entry_liq, funding=funding, **kw)
        rows.append({**t, "pair": pair, "fees": c.entry_fee + c.exit_fee,
                     "slippage": c.entry_slippage + c.exit_slippage, "funding": c.funding,
                     "net": t["gross"] - c.total})
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0}
    return {"n": len(df), "gross_mean_pct": df.gross.mean() * 100, "net_mean_pct": df.net.mean() * 100,
            "fees_pct": df.fees.mean() * 100, "slippage_pct": df.slippage.mean() * 100,
            "funding_pct": df.funding.mean() * 100, "net_win_rate": float((df.net > 0).mean())}


# ---- network (not exercised by tests) ------------------------------------
def _get(u, body=None):
    for _ in range(4):
        try:
            req = urllib.request.Request(u, data=json.dumps(body).encode() if body else None,
                                         headers={"content-type": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=25))
        except Exception:
            time.sleep(1.5)
    raise RuntimeError(f"fetch failed: {u}")


def klines(sym, interval, months):
    step = {"1h": 3600_000, "1d": 86400_000}[interval]
    end = int(time.time() * 1000)
    start, out = end - months * 30 * 86400_000, []
    while start < end:
        d = _get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}"
                 f"&limit=1000&startTime={start}&endTime={end}")
        if not d:
            break
        out += d
        start = d[-1][0] + step
        if len(d) < 1000:
            break
    df = pd.DataFrame(out, columns="ot o h l c v ct qv n tb tq ig".split()).drop_duplicates("ot")
    df["date"] = pd.to_datetime(df.ot, unit="ms", utc=True)
    for k in "ohlcv":
        df[k] = df[k].astype(float)
    return df.set_index("date")[list("ohlcv")].sort_index()


def hl_funding(coin, months) -> FundingSeries:
    start, end, pairs = int((time.time() - months * 30 * 86400) * 1000), int(time.time() * 1000), []
    while start < end:
        d = _get("https://api.hyperliquid.xyz/info", {"type": "fundingHistory", "coin": coin, "startTime": start})
        if not d:
            break
        pairs += [(int(x["time"]), float(x["fundingRate"])) for x in d]
        if len(d) < 500:
            break
        start = d[-1]["time"] + 1
    return FundingSeries.from_pairs(pairs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=20)
    m = ap.parse_args().months
    b1h, b1d = klines("BTCUSDT", "1h", m), klines("BTCUSDT", "1d", m + 8)
    gate, flip = btc_gate(b1h, b1d), b1h.c > b1h.c.rolling(50).mean()
    allt = []
    for coin in ("BTC", "ETH", "SOL"):
        d = klines(f"{coin}USDT", "1h", m)
        allt.append(net_trades(simulate_pair(d, gate, flip), f"{coin}/USDC:USDC", hl_funding(coin, m)))
    df = pd.concat(allt, ignore_index=True)
    print(json.dumps(summarize(df), indent=2))
    for k, g in df.groupby("pair"):
        print(k, json.dumps(summarize(g)))
    print(df.reason.value_counts().to_string())


if __name__ == "__main__":
    main()
