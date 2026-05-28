"""Price-verified backtest of the (fixed) Killers copy-bot.

For each signal: market-enter at the first 15m candle after the post time,
apply the bot's target-guard (drop targets already crossed), then walk candles
placing the FULL TP ladder as resting limits (the fixed-bot behaviour) plus the
signal SL. Compute realized P&L at REAL prices — ignoring the channel's
self-reported numbers.

Conservative choices (stated in the report):
  - same-candle TP+SL touch  -> assume SL filled first (worst case)
  - market fills (entry, SL, horizon) pay taker + slippage; TP limits pay maker
  - bot's real fixed sizing: $20 stake x 5x = $100 notional per trade
  - hold horizon: explicit channel close_ts if present, else entry + HORIZON_DAYS
"""
import json, glob, os
from datetime import datetime, timezone, timedelta

DIR = "/home/ubuntu/killers_backtest"
ALIASES = {"PEPE": "1000PEPE", "SHIB": "1000SHIB", "FLOKI": "1000FLOKI",
           "BONK": "1000BONK", "GOLD": "XAUT"}

STAKE = 20.0
LEV = 5.0
NOTIONAL = STAKE * LEV          # $100
TAKER = 0.0005
MAKER = 0.0002
SLIP = 0.0005
HORIZON_DAYS = 30


def bsym(s):
    return ALIASES.get(s.upper(), s.upper()) + "USDT"


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def ms(dt):
    return int(dt.timestamp() * 1000)


# load ohlcv
ohlcv = {}
for f in glob.glob(f"{DIR}/ohlcv/*.json"):
    bs = os.path.basename(f)[:-5]
    rows = json.load(open(f))
    rows.sort(key=lambda r: r[0])
    ohlcv[bs] = rows

trades = [json.loads(l) for l in open(f"{DIR}/trades.jsonl") if l.strip()]


def find_entry_idx(rows, ot_ms):
    lo, hi = 0, len(rows)
    while lo < hi:
        mid = (lo + hi) // 2
        if rows[mid][0] < ot_ms:
            lo = mid + 1
        else:
            hi = mid
    return lo if lo < len(rows) else None


def simulate(t, sl_first_on_tie=True, breakeven_after_tp1=False):
    sym = t["symbol"]
    direction = t["direction"]
    sl = t["sl"]
    targets = t["targets"] or []
    if direction not in ("long", "short") or not sl or not targets:
        return {"status": "unbacktestable"}
    bs = bsym(sym)
    rows = ohlcv.get(bs)
    if not rows:
        return {"status": "no_data"}
    ot_ms = ms(parse_dt(t["open_ts"]))
    ei = find_entry_idx(rows, ot_ms)
    if ei is None:
        return {"status": "no_data_after_signal"}
    entry = rows[ei][1]  # candle open = market fill
    if entry <= 0:
        return {"status": "bad_entry"}

    is_long = direction == "long"
    if is_long:
        tg = sorted([x for x in targets if x > entry])
        sl_valid = sl < entry
    else:
        tg = sorted([x for x in targets if x < entry], reverse=True)
        sl_valid = sl > entry
    if not tg:
        return {"status": "all_targets_crossed"}
    if not sl_valid:
        return {"status": "sl_wrong_side"}

    n = len(tg)
    slice_notional = NOTIONAL / n
    if t.get("close_ts"):
        end_ms = ms(parse_dt(t["close_ts"]))
    else:
        end_ms = ms(parse_dt(t["open_ts"]) + timedelta(days=HORIZON_DAYS))

    remaining = list(tg)
    pnl = 0.0
    fees = NOTIONAL * (TAKER + SLIP)  # entry
    tp_hits = 0
    exit_reason = "horizon"
    last_close = entry
    cur_sl = sl

    for r in rows[ei:]:
        ot, o, h, l, c = r
        last_close = c
        if ot > end_ms:
            exit_reason = "horizon"
            break
        sl_touch = (l <= cur_sl) if is_long else (h >= cur_sl)
        reached = ([tp for tp in remaining if h >= tp] if is_long
                   else [tp for tp in remaining if l <= tp])

        if sl_touch and (sl_first_on_tie or not reached):
            for tp in remaining:
                ret = (cur_sl - entry) / entry if is_long else (entry - cur_sl) / entry
                pnl += slice_notional * ret
                fees += slice_notional * (TAKER + SLIP)
            remaining = []
            exit_reason = "sl" if cur_sl != entry else "breakeven_stop"
            break

        for tp in reached:
            ret = (tp - entry) / entry if is_long else (entry - tp) / entry
            pnl += slice_notional * ret
            fees += slice_notional * MAKER
            tp_hits += 1
        if reached and breakeven_after_tp1:
            cur_sl = entry  # move stop to breakeven after first TP
        remaining = [tp for tp in remaining if tp not in reached]
        if not remaining:
            exit_reason = "all_tp"
            break

    if remaining and exit_reason == "horizon":
        for tp in remaining:
            ret = (last_close - entry) / entry if is_long else (entry - last_close) / entry
            pnl += slice_notional * ret
            fees += slice_notional * (TAKER + SLIP)
        remaining = []

    net = pnl - fees
    risk = abs(entry - sl) / entry
    return {
        "status": "ok", "symbol": sym, "dir": direction, "entry": entry,
        "n_targets": n, "tp_hits": tp_hits, "exit_reason": exit_reason,
        "net": round(net, 4),
        "r_mult": round(net / (NOTIONAL * risk), 3) if risk > 0 else None,
        "open_ts": t["open_ts"], "sl_dist_pct": round(risk * 100, 2),
    }


def run_scenario(name, **kw):
    res = [simulate(t, **kw) for t in trades]
    ok = [r for r in res if r["status"] == "ok"]
    wins = [r for r in ok if r["net"] > 0]
    losses = [r for r in ok if r["net"] <= 0]
    total = sum(r["net"] for r in ok)
    from collections import Counter
    ex = Counter(r["exit_reason"] for r in ok)
    eq = peak = maxdd = 0.0
    for r in sorted(ok, key=lambda x: x["open_ts"]):
        eq += r["net"]; peak = max(peak, eq); maxdd = max(maxdd, peak - eq)
    gw = sum(r["net"] for r in wins); gl = -sum(r["net"] for r in losses)
    pf = gw / gl if gl > 0 else float("inf")
    print(f"\n### {name}")
    print(f"  trades={len(ok)}  win%={len(wins)*100/max(1,len(ok)):.1f}  "
          f"PF={pf:.2f}  total=${total:+.0f}  exp=${total/max(1,len(ok)):+.2f}/trade  "
          f"maxDD=${maxdd:.0f}")
    print(f"  exits: SL={ex.get('sl',0)} BE-stop={ex.get('breakeven_stop',0)} "
          f"allTP={ex.get('all_tp',0)} horizon={ex.get('horizon',0)}")
    return res


print("=" * 64)
print("PRICE-VERIFIED BACKTEST — Killers signals at real Binance 15m prices")
print("=" * 64)
print(f"model: ${STAKE:.0f}x{LEV:.0f}=${NOTIONAL:.0f} notional; taker{TAKER*100}%/maker{MAKER*100}%/slip{SLIP*100}%; horizon{HORIZON_DAYS}d")
res0 = run_scenario("A. conservative (SL-first ties, fixed SL)", sl_first_on_tie=True, breakeven_after_tp1=False)
run_scenario("B. realistic (breakeven after TP1, SL-first ties)", sl_first_on_tie=True, breakeven_after_tp1=True)
run_scenario("C. optimistic (TP-first ties, breakeven after TP1)", sl_first_on_tie=False, breakeven_after_tp1=True)
print("\n(channel self-reported, for contrast: +$23,063 / 98% win / PF~big)")

from collections import Counter
status_dist = Counter(r["status"] for r in res0)
print("\n" + "-" * 64)
print(f"coverage: signals={len(trades)}  status={dict(status_dist)}")
ok = [r for r in res0 if r["status"] == "ok"]
print(f"avg targets/ladder: {sum(r['n_targets'] for r in ok)/max(1,len(ok)):.1f}  "
      f"avg SL dist: {sum(r['sl_dist_pct'] for r in ok)/max(1,len(ok)):.1f}%")
json.dump(res0, open(f"{DIR}/results.json", "w"), default=str)
print(f"wrote {DIR}/results.json")
