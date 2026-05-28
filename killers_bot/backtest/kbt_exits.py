"""Does a different EXIT policy make the Killers signals profitable?

Tests several exit strategies on the same entries/SLs. Reports expectancy in
R-multiples (sizing-independent: R = the $ risked if SL hits). If R-expectancy
is negative for a policy, NO wallet sizing can make it profitable; if positive,
the signals ARE mirrorable+profitable with that exit and sizing just scales it.
"""
import json, glob, os
from datetime import datetime, timezone, timedelta

DIR = "/home/ubuntu/killers_backtest"
ALIASES = {"PEPE": "1000PEPE", "SHIB": "1000SHIB", "FLOKI": "1000FLOKI",
           "BONK": "1000BONK", "GOLD": "XAUT"}
NOTIONAL = 100.0
TAKER, MAKER, SLIP = 0.0005, 0.0002, 0.0005
HORIZON_DAYS = 30


def bsym(s): return ALIASES.get(s.upper(), s.upper()) + "USDT"
def parse_dt(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))
def ms(dt): return int(dt.timestamp() * 1000)


ohlcv = {}
for f in glob.glob(f"{DIR}/ohlcv/*.json"):
    rows = json.load(open(f)); rows.sort(key=lambda r: r[0])
    ohlcv[os.path.basename(f)[:-5]] = rows
trades = [json.loads(l) for l in open(f"{DIR}/trades.jsonl") if l.strip()]


def entry_idx(rows, t):
    lo, hi = 0, len(rows)
    while lo < hi:
        m = (lo + hi) // 2
        if rows[m][0] < t: lo = m + 1
        else: hi = m
    return lo if lo < len(rows) else None


def build_legs(tg, policy):
    """Return (legs, naked_frac, breakeven). legs=[(frac,target)]; naked_frac
    rides to SL/horizon with no target."""
    n = len(tg)
    if policy == "ladder":
        return [(1.0 / n, tp) for tp in tg], 0.0, False
    if policy == "tp1_100":
        return [(1.0, tg[0])], 0.0, False
    if policy == "tp2_100":
        return [(1.0, tg[1] if n >= 2 else tg[0])], 0.0, False
    if policy == "tp1_50_be":
        if n == 1:
            return [(1.0, tg[0])], 0.0, False
        rest = [(0.5 / (n - 1), tp) for tp in tg[1:]]
        return [(0.5, tg[0])] + rest, 0.0, True
    if policy == "tp1_75_run":
        # 75% at TP1, 25% rides to far targets with BE
        if n == 1:
            return [(1.0, tg[0])], 0.0, False
        rest = [(0.25 / (n - 1), tp) for tp in tg[1:]]
        return [(0.75, tg[0])] + rest, 0.0, True
    raise ValueError(policy)


def sim(t, policy, entry_mode="market", limit_hours=48):
    direction, sl, targets = t["direction"], t["sl"], t["targets"] or []
    if direction not in ("long", "short") or not sl or not targets:
        return None
    rows = ohlcv.get(bsym(t["symbol"]))
    if not rows: return None
    sig_ms = ms(parse_dt(t["open_ts"]))
    ei = entry_idx(rows, sig_ms)
    if ei is None: return None
    if entry_mode == "limit":
        # only fill if price trades through the signal's entry zone within
        # limit_hours; enter at entry_mid; else skip the signal (no trade)
        em = t.get("entry_mid")
        if not em or em <= 0: return None
        deadline = sig_ms + limit_hours * 3600 * 1000
        filled = None
        for j in range(ei, len(rows)):
            ot, o, h, l, c = rows[j]
            if ot > deadline: break
            if l <= em <= h:
                filled = j; break
        if filled is None:
            return {"skipped": True}
        ei = filled
        entry = em
    else:
        entry = rows[ei][1]
    if entry <= 0: return None
    is_long = direction == "long"
    if is_long:
        tg = sorted([x for x in targets if x > entry]); sl_ok = sl < entry
    else:
        tg = sorted([x for x in targets if x < entry], reverse=True); sl_ok = sl > entry
    if not tg or not sl_ok: return None

    legs, naked, be = build_legs(tg, policy)
    end_ms = ms(parse_dt(t["close_ts"])) if t.get("close_ts") else ms(parse_dt(t["open_ts"]) + timedelta(days=HORIZON_DAYS))
    pnl = 0.0; fees = NOTIONAL * (TAKER + SLIP)
    cur_sl = sl; filled_any = False; last_close = entry; reason = "horizon"
    pending = list(legs)

    for r in rows[ei:]:
        ot, o, h, l, c = r; last_close = c
        if ot > end_ms: reason = "horizon"; break
        sl_touch = (l <= cur_sl) if is_long else (h >= cur_sl)
        if sl_touch:  # conservative: SL first
            rem = sum(f for f, _ in pending) + naked
            ret = (cur_sl - entry) / entry if is_long else (entry - cur_sl) / entry
            pnl += NOTIONAL * rem * ret; fees += NOTIONAL * rem * (TAKER + SLIP)
            pending = []; naked = 0.0
            reason = "be_stop" if cur_sl == entry else "sl"; break
        still = []
        for f, tp in pending:
            hit = (h >= tp) if is_long else (l <= tp)
            if hit:
                ret = (tp - entry) / entry if is_long else (entry - tp) / entry
                pnl += NOTIONAL * f * ret; fees += NOTIONAL * f * MAKER
                filled_any = True
            else:
                still.append((f, tp))
        pending = still
        if filled_any and be: cur_sl = entry
        if not pending and naked == 0.0: reason = "done"; break

    rem = sum(f for f, _ in pending) + naked
    if rem > 0 and reason == "horizon":
        ret = (last_close - entry) / entry if is_long else (entry - last_close) / entry
        pnl += NOTIONAL * rem * ret; fees += NOTIONAL * rem * (TAKER + SLIP)
    net = pnl - fees
    risk = abs(entry - sl) / entry
    return {"net": net, "r": net / (NOTIONAL * risk) if risk > 0 else None, "open_ts": t["open_ts"]}


print("=" * 70)
print("EXIT-POLICY SWEEP — same entries/SLs, different exits (real prices)")
print("R-expectancy is sizing-independent: <0 means no wallet size can profit.")
print("=" * 70)
def report(entry_mode):
    print(f"\n--- ENTRY MODE: {entry_mode} ---")
    print(f"{'policy':<14} {'trades':>6} {'win%':>6} {'PF':>6} {'$total':>9} {'$exp':>7} {'R-exp':>7} {'maxDD$':>8}")
    for policy in ["ladder", "tp1_100", "tp2_100", "tp1_50_be", "tp1_75_run"]:
        raw = [sim(t, policy, entry_mode=entry_mode) for t in trades]
        res = [r for r in raw if r and not r.get("skipped")]
        wins = [r for r in res if r["net"] > 0]; losses = [r for r in res if r["net"] <= 0]
        total = sum(r["net"] for r in res)
        gw = sum(r["net"] for r in wins); gl = -sum(r["net"] for r in losses)
        pf = gw / gl if gl > 0 else 99.9
        rs = [r["r"] for r in res if r["r"] is not None]
        rexp = sum(rs) / len(rs) if rs else 0
        eq = peak = dd = 0.0
        for r in sorted(res, key=lambda x: x["open_ts"]):
            eq += r["net"]; peak = max(peak, eq); dd = max(dd, peak - eq)
        print(f"{policy:<14} {len(res):>6} {len(wins)*100/max(1,len(res)):>5.1f}% {pf:>6.2f} "
              f"{total:>+9.0f} {total/max(1,len(res)):>+7.2f} {rexp:>+7.3f} {dd:>8.0f}")


report("market")
report("limit")
