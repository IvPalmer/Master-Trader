"""Attack lane (codex idea B, pre-registered): BTC-REGIME gate on market+T1 entry.

Most Killers signals are longs; crypto is beta-driven. Take a signal ONLY when BTC
trend agrees: long if BTC 1h close > BTC 1h EMA800 (~4h EMA200) AND BTC 12h return > 0;
short mirror. No MA/timeframe sweep (one regime def). Exit 100% at T1/SL, market entry
at signal-candle open, fees in R. Chronological 70/30; the gate is fixed (nothing to fit)
so we just report full-sample + OOS. Same hurdle: OOS n>=40, mean>=+0.15R, total>=+8R,
survives drop-top, beats ungated market-T1 baseline.
"""
import json, os, urllib.request, urllib.parse
import replay_v2 as r
from momentum_killers import fetch_sig, market_t1_R, stats

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "btc_1h.json")


def fetch_btc_1h(start_ms, end_ms):
    if os.path.exists(CACHE):
        return json.load(open(CACHE))
    out, cur = [], start_ms
    while cur < end_ms:
        q = urllib.parse.urlencode({"symbol": "BTCUSDT", "interval": "1h", "startTime": cur, "endTime": end_ms, "limit": 1500})
        req = urllib.request.Request(f"https://fapi.binance.com/fapi/v1/klines?" + q, headers={"User-Agent": "btc/1.0"})
        rows = json.load(urllib.request.urlopen(req, timeout=30))
        if not rows:
            break
        out.extend(rows)
        if len(rows) < 1500:
            break
        cur = rows[-1][0] + 3600_000
    c = [[int(x[0]), float(x[4])] for x in out]  # ts, close
    json.dump(c, open(CACHE, "w"))
    return c


def build_regime(btc):
    ts = [x[0] for x in btc]; cl = [x[1] for x in btc]
    # EMA800 on 1h ~ 4h EMA200
    ema, a = [], 2 / (800 + 1)
    e = cl[0]
    for px in cl:
        e = px * a + e * (1 - a); ema.append(e)
    reg = []  # (ts, long_ok, short_ok)
    for i in range(len(cl)):
        ret12 = (cl[i] / cl[i - 12] - 1) if i >= 12 else 0.0
        long_ok = cl[i] > ema[i] and ret12 > 0
        short_ok = cl[i] < ema[i] and ret12 < 0
        reg.append((ts[i], long_ok, short_ok))
    return reg


def regime_ok(reg, o_ms, is_long):
    # latest 1h bar at/before signal
    lo, hi, best = 0, len(reg) - 1, None
    for k in range(len(reg)):
        if reg[k][0] <= o_ms:
            best = reg[k]
        else:
            break
    if best is None:
        return False
    return best[1] if is_long else best[2]


def main():
    sigs = json.load(open(os.path.join(HERE, "killers_signals.json")))
    usable = [s for s in sigs if s["entry_lo"] and s["sl_initial"] and s["tp_ladder"] and s["direction"] in ("long", "short")]
    states = [s for s in (fetch_sig(x) for x in usable) if s]
    states.sort(key=lambda s: s["o_ms"])
    lo = min(s["o_ms"] for s in states); hi = max(s["o_ms"] for s in states)
    btc = fetch_btc_1h(lo - 40 * 86400_000, hi + 2 * 86400_000)
    reg = build_regime(btc)

    gated, ungated = [], []
    kept = 0
    for s in states:
        b = market_t1_R(s)
        if b is None:
            continue
        ungated.append(b)
        if regime_ok(reg, s["o_ms"], s["is_long"]):
            gated.append(b); kept += 1
    print(f"states={len(states)}  BTC-regime kept {kept}/{len(ungated)} signals\n")
    print(f"  ungated market-T1 (ALL):   {stats(ungated)}")
    print(f"  BTC-gated market-T1 (ALL): {stats(gated)}\n")

    # chronological OOS on the gated set
    cut = int(len(states) * 0.70)
    oos_states = states[cut:]
    g_oos, u_oos = [], []
    for s in oos_states:
        b = market_t1_R(s)
        if b is None:
            continue
        u_oos.append(b)
        if regime_ok(reg, s["o_ms"], s["is_long"]):
            g_oos.append(b)
    print(f"  OOS (last 30%): gated kept {len(g_oos)}/{len(u_oos)}")
    print(f"  OOS ungated: {stats(u_oos)}")
    print(f"  OOS gated:   {stats(g_oos)}")
    if g_oos:
        gm = sum(g_oos) / len(g_oos); um = sum(u_oos) / len(u_oos) if u_oos else 0
        srt = sorted(g_oos)
        print(f"\n  HURDLE: n>=40 [{len(g_oos)>=40}]  mean>=+0.15 [{gm:+.3f}->{gm>=0.15}]  "
              f"total>=+8 [{sum(g_oos):+.1f}->{sum(g_oos)>=8}]  beats-ungated [{gm-um:+.3f}->{gm-um>0}]  "
              f"drop-top>0 [{(sum(g_oos)-srt[-1])>0}]")


if __name__ == "__main__":
    main()
