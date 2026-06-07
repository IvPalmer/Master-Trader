"""PRE-REGISTERED overlay test (codex-sanctioned): does 'channel mentioned this coin recently'
improve the ALREADY-VALIDATED Keltner mean-reversion edge? Run the EXACT KeltnerBounceV1 logic
(lower-band cross + vol>1.75x + BTC>SMA50; ROI ladder + trailing + -7% stop; 1h) on each coin's
continuous 1h series. Tag each Keltner trade as in-attention (entry within N days AFTER a channel
mention of that coin) vs baseline (>30d from any mention). Compare expectancy. NO Keltner param
tuning — only the binary/age-bucket overlay. Same code both buckets so exit-model approx cancels.
"""
import json, os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "keltner_1h")
DAY = 86400_000
FEE = 0.001  # ~0.1% round trip (applied to all trades; cancels in the comparison)

# Keltner params (frozen, from KeltnerBounceV1.py)
KP, KMULT, VMULT, VSMA = 25, 2.5, 1.75, 20
ROI = [(0, 0.10), (360, 0.07), (720, 0.04), (1440, 0.02)]  # (minutes, roi)
HARD_STOP, TRAIL_OFF, TRAIL = -0.07, 0.05, 0.03
MAX_HOLD_H = 24 * 14


def load(sym):
    fp = os.path.join(DATA, f"{sym}.json")
    return json.load(open(fp)) if os.path.exists(fp) else None


def sma(vals, p, i):
    if i + 1 < p:
        return None
    return sum(vals[i - p + 1:i + 1]) / p


def btc_gate_map(btc):
    closes = [c[4] for c in btc]
    gate = {}
    for i, c in enumerate(btc):
        s = sma(closes, 50, i)
        gate[c[0]] = (s is not None and c[4] > s)
    return gate


def atr(cands, i, p):
    if i + 1 < p + 1:
        return None
    trs = []
    for j in range(i - p + 1, i + 1):
        h, l, pc = cands[j][2], cands[j][3], cands[j - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / p


def roi_at(elapsed_min):
    r = ROI[0][1]
    for m, v in ROI:
        if elapsed_min >= m:
            r = v
    return r


def simulate_exit(cands, entry_i, entry_px):
    """Walk from entry_i; ROI ladder + trailing + hard stop. Return (gross_ret, exit_i)."""
    peak = entry_px
    entry_ts = cands[entry_i][0]
    for j in range(entry_i, min(len(cands), entry_i + MAX_HOLD_H)):
        ts, o, h, l, c, v = cands[j]
        peak = max(peak, h)
        elapsed = (ts - entry_ts) / 60000
        eff_stop = entry_px * (1 + HARD_STOP)
        if peak >= entry_px * (1 + TRAIL_OFF):
            eff_stop = max(eff_stop, peak * (1 - TRAIL))
        if l <= eff_stop:
            return eff_stop / entry_px - 1, j
        target = entry_px * (1 + roi_at(elapsed))
        if h >= target:
            return roi_at(elapsed), j
    j = min(len(cands) - 1, entry_i + MAX_HOLD_H)
    return cands[j][4] / entry_px - 1, j


def keltner_trades(sym, gate):
    cands = load(sym)
    if not cands or len(cands) < KP + VSMA + 5:
        return []
    closes = [c[4] for c in cands]; vols = [c[5] for c in cands]
    trades = []
    in_pos_until = -1
    for i in range(KP + 1, len(cands) - 1):
        if i <= in_pos_until:
            continue
        a = atr(cands, i, KP); s = sma(closes, KP, i)
        ap = atr(cands, i - 1, KP); sp = sma(closes, KP, i - 1)
        vs = sma(vols, VSMA, i)
        if None in (a, s, ap, sp, vs):
            continue
        kl = s - KMULT * a; klp = sp - KMULT * ap
        cross = closes[i] > kl and closes[i - 1] <= klp
        volok = vols[i] > VMULT * vs and vols[i] > 0
        g = gate.get(cands[i][0])
        if g is None:  # carry-forward nearest earlier gate
            g = True
        if cross and volok and g:
            entry_px = cands[i + 1][1]  # enter next-bar open
            ret, exit_i = simulate_exit(cands, i + 1, entry_px)
            trades.append({"sym": sym, "entry_ts": cands[i + 1][0], "ret": ret - FEE})
            in_pos_until = exit_i  # no pyramiding: block until the position actually exits
    return trades


def main():
    btc = load("BTC")
    gate = btc_gate_map(btc)
    sigs = json.load(open(os.path.join(HERE, "killers_signals.json")))
    mentions = {}
    for x in sigs:
        if x.get("symbol") and x.get("open_date"):
            mentions.setdefault(x["symbol"].upper(), []).append(int(datetime.fromisoformat(x["open_date"].replace("Z", "+00:00")).timestamp() * 1000))
    coins = sorted(mentions)
    all_trades = []
    for c in coins:
        all_trades += keltner_trades(c, gate)
    print(f"Keltner trades on {len(coins)} channel coins: {len(all_trades)} total\n")

    def near(ts, sym, days):
        for m in mentions.get(sym, []):
            if 0 <= ts - m <= days * DAY:
                return True
        return False

    def stats(tag, rs):
        n = len(rs)
        if not n:
            print(f"  {tag:<24} n=0"); return
        tot = sum(rs); wins = [x for x in rs if x > 0]; losses = [x for x in rs if x <= 0]
        pf = (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else float("inf")
        print(f"  {tag:<24} n={n:<5} mean={tot/n*100:>+6.2f}%  win%={len(wins)/n*100:>4.0f}  PF={pf:>4.2f}  median={sorted(rs)[n//2]*100:>+5.1f}%")

    print("BASELINE = Keltner trades >30d from any mention of that coin:")
    base = [t["ret"] for t in all_trades if not near(t["entry_ts"], t["sym"], 30)]
    stats("baseline (>30d)", base)
    print("\nIN-ATTENTION = Keltner trade within N days AFTER a mention of that coin:")
    for d in (7, 14, 30):
        inw = [t["ret"] for t in all_trades if near(t["entry_ts"], t["sym"], d)]
        stats(f"within {d}d of mention", inw)
    print("\n(overlay value = in-attention expectancy vs baseline; same Keltner code both)")


if __name__ == "__main__":
    main()
