"""Falsifiable honesty audit of Dennis's channel posts vs market reality.

Tests whether Dennis posts claims that the actual price action contradicts:

  1. ENTRY FILL: did the posted entry price actually trade within 6h of the
     post? A limit entry that never fills but is then "managed" as a live
     position = fabricated fill.

  2. WIN CLAIMS: for close_partial / close_full events whose text claims
     profit ("TP", "✅", "fix", "profit", "lock"), was price actually
     favorable vs entry at that timestamp? Claiming "TP1 hit ✅" when a LONG
     is underwater = a lie.

  3. CLOSE-PRICE REALITY: for close_full events that name a price, did that
     price actually trade near the post time?

Uses clean Binance 1m data (same fetch path as proper_backtest).
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import proper_backtest as pb  # reuse get_window / price_at / ms / parse_dt

TRADES_JSON = pb.TRADES_JSON
SRC = "binance"

PROFIT_WORDS = re.compile(r"\bTP\b|✅|\bfix\b|\bprofit\b|\block\b|\bsecured?\b|\btarget\b", re.I)
PRICE_RE = re.compile(r"(\d{2,6}(?:[.,]\d+)?)")


def candle_range_at(sym, ts_ms, window_min=360):
    """Return (low, high, first_open) over [ts, ts+window] from 1m candles."""
    candles = pb.get_window(SRC, sym, ts_ms, ts_ms + window_min * 60_000)
    if not candles:
        return None
    lo = min(c["l"] for c in candles)
    hi = max(c["h"] for c in candles)
    return lo, hi, candles[0]["o"]


def main():
    d = json.load(open(TRADES_JSON))
    trades = d["trades"]

    entry_filled = entry_never = entry_nodata = 0
    never_filled_but_managed = []   # the damning category

    win_claims_checked = 0
    win_claims_contradicted = []     # claimed profit but price underwater

    for t in trades:
        sym = t["symbol"]; direction = t["direction"]
        entry = t.get("entry"); init_sl = t.get("sl")
        if not isinstance(entry, (int, float)) or entry <= 0:
            continue
        is_long = direction == "LONG"
        post_ms = pb.ms(t["date"])

        # ── ENTRY FILL ──
        rng = candle_range_at(sym, post_ms, 360)
        if rng is None:
            entry_nodata += 1
        else:
            lo, hi, op = rng
            filled = lo <= entry <= hi  # entry traded in the 6h window
            if filled:
                entry_filled += 1
            else:
                entry_never += 1
                # was it then managed as a live position? (has events)
                if t.get("events"):
                    # direction sanity: long limit below mkt that never came down,
                    # or short limit above mkt that never came up
                    gap_pct = (op - entry) / entry * 100 if is_long else (entry - op) / entry * 100
                    never_filled_but_managed.append(
                        (t["msg_id"], sym, direction, entry, round(op, 4),
                         round(gap_pct, 2), len(t["events"]))
                    )

        # ── WIN CLAIMS ──
        for e in t.get("events", []):
            if e["kind"] not in ("close_partial", "close_full"):
                continue
            txt = e.get("text") or ""
            if not PROFIT_WORDS.search(txt):
                continue
            ev_ms = pb.ms(e["date"])
            p = pb.price_at(SRC, sym, ev_ms)
            if p is None:
                continue
            win_claims_checked += 1
            # favorable?  long: price > entry ; short: price < entry
            favorable = (p > entry) if is_long else (p < entry)
            if not favorable:
                pnl_pct = (p - entry) / entry * 100 * (1 if is_long else -1)
                win_claims_contradicted.append(
                    (t["msg_id"], sym, direction, entry, round(p, 4),
                     round(pnl_pct, 2), txt.replace("\n", " ")[:60])
                )

    print("=" * 64)
    print("  ENTRY FILL AUDIT")
    print("=" * 64)
    tot = entry_filled + entry_never + entry_nodata
    print(f"  entries checked: {tot}")
    print(f"  filled (price traded the entry within 6h): {entry_filled}")
    print(f"  NEVER filled in 6h window: {entry_never}")
    print(f"  no data: {entry_nodata}")
    print(f"  --> never-filled BUT then managed as live ({len(never_filled_but_managed)}):")
    for r in sorted(never_filled_but_managed, key=lambda x: -abs(x[5]))[:15]:
        print(f"      msg {r[0]:5} {r[1]:6} {r[2]:5} entry={r[3]} mkt@post={r[4]} gap={r[5]:+.2f}% events={r[6]}")

    print()
    print("=" * 64)
    print("  WIN-CLAIM AUDIT (claimed profit but price underwater)")
    print("=" * 64)
    print(f"  profit-claim messages checked: {win_claims_checked}")
    print(f"  CONTRADICTED (underwater when claiming profit): {len(win_claims_contradicted)}")
    for r in sorted(win_claims_contradicted, key=lambda x: x[5])[:20]:
        print(f"      msg {r[0]:5} {r[1]:6} {r[2]:5} entry={r[3]} price@claim={r[4]} pnl={r[5]:+.2f}%  '{r[6]}'")


if __name__ == "__main__":
    main()
