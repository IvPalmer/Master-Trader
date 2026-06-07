"""Event-driven backtest harness for Dennis's signals — offline, deterministic.

Reads ONLY the local price cache (prices/<SYM>.<venue>.jsonl) so it never touches
the network: every run is reproducible and reviewable. WEEX is primary (has the
alts); Binance is fallback/parity.

Two ENTRY x EXIT axes are reported, ALL pre-declared and FIXED (no fitting to the
+$22,119 scoreboard):

  ENTRY models (the limit/range/market sensitivity):
    - "posted"  : fill at posted entry (range midpoint). Skip if entry never trades
                  within FILL_WINDOW_H (a real limit copier). = most generous to Dennis.
    - "edge"    : fill at the BEST favorable price actually touched inside the posted
                  range (optimistic limit; not literally the range edge unless touched).
    - "market"  : fill at the candle open at signal time (what our bot does; no waiting).

  EXIT models:
    - "ladder"  : MECHANICAL. Equal-fraction scale-out across the posted TP list,
                  SL->breakeven after TP1, hard SL otherwise. Pure rules, no discretion.
                  This is the objective copyable rule when Dennis posted numeric TPs.
    - "manage"  : FOLLOW DENNIS'S POSTED MANAGEMENT. Replays the per-trade `events[]`
                  timeline (close X% at event-time price, move SL to breakeven, full
                  close) extracted from the free channel. Walks for the *current* SL
                  between events. If a trade has no events, falls back to the mechanical
                  ladder (so a posted TP ladder IS Dennis's posted management).

Where ladder and manage diverge, the discretion matters — RESULTS.md flags it.

A trade dict:
  {
    "symbol": "SOL", "direction": "SHORT"|"LONG",
    "date": "2026-04-22T05:28:00+00:00",
    "entry": 89.5 | null,              # posted entry (range midpoint) or null
    "entry_lo": 88, "entry_hi": 91,    # posted range edges (optional)
    "sl": 93 | null,                   # posted hard SL or null (11/23 have none)
    "tps": [84, 82, ...],              # ordered take-profits (may be empty)
    "events": [                        # posted management timeline (may be empty)
       {"t": ISO, "action": "close", "frac": 0.30, "sl_to": "breakeven"},
       {"t": ISO, "action": "close", "frac_of_remaining": 0.70},
       {"t": ISO, "action": "sl_to", "sl_to": "breakeven"},
       {"t": ISO, "action": "close_full"}
    ],
    "claim_usd": 5797, "claim_pct": 409   # Dennis's reported result (for reconcile)
  }

Sizing: notional = RISK_PER_TRADE / sl_distance. PnL reported in R (=PnL/RISK_$) and
in account-% at RISK_PCT per trade. Trades with NO posted SL cannot be risk-sized;
they are reported in a separate "no-hard-stop" diagnostic, never folded into the
risk-sized copier total.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
# PRICES_DIR env override lets the same engine run on a different cache (e.g. the
# May +2702% ledger in prices_may/) without clobbering the April cache.
PRICES = Path(os.environ["PRICES_DIR"]) if os.environ.get("PRICES_DIR") else HERE / "prices"

RISK_PER_TRADE = 10.0      # 1R in $ (arbitrary unit; results reported in R)
RISK_PCT = 5.0             # Dennis's stated "5% risk per trade" (for account-% view)
FILL_WINDOW_H = 6          # a limit copier's entry must trade within this many hours
MAX_TAIL_HOURS = 24 * 12   # walk up to 12 days for an unclosed position

_cache: dict[tuple[str, str], list[dict]] = {}


def load(sym: str, venue: str) -> list[dict]:
    key = (sym.upper(), venue)
    if key in _cache:
        return _cache[key]
    p = PRICES / f"{sym.upper()}.{venue}.jsonl"
    rows = []
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows.sort(key=lambda c: c["t"])
    _cache[key] = rows
    return rows


def candles(sym: str, prefer: str = "weex") -> tuple[list[dict], str]:
    """Return (candles, venue_used). Prefer WEEX (has alts); fall back to Binance."""
    w = load(sym, prefer)
    if w:
        return w, prefer
    other = "binance" if prefer == "weex" else "weex"
    return load(sym, other), other


def ms(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)


def window(cs: list[dict], a: int, b: int) -> list[dict]:
    return [c for c in cs if a <= c["t"] < b]


def price_at(cs: list[dict], t_ms: int) -> float | None:
    """Close of the candle covering t_ms (first candle at/after t_ms)."""
    for c in cs:
        if c["t"] >= t_ms:
            return c["c"]
    return None


@dataclass
class Result:
    symbol: str
    direction: str
    entry_model: str
    exit_model: str
    venue: str
    filled: bool
    entry_price: float | None
    realized_R: float | None     # PnL in R units (PnL / RISK_$). None => not risk-sized.
    realized_units: float | None # raw PnL per 1.0 notional (price terms), for no-SL view
    exit_kind: str               # 'ladder'|'sl'|'manage'|'tail'|'no_fill'|'no_data'|'no_sl'...
    n_partials: int = 0
    note: str = ""


def _first_touch_ts(win: list[dict], price: float, signal_ts: int) -> int:
    """Timestamp of the first candle in `win` whose [low, high] range contains `price`
    (i.e. the minute a resting limit at `price` would actually have traded). Falls back
    to `signal_ts` if no candle straddles the level (shouldn't happen once a fill is
    decided, but keeps the walk-start defined)."""
    for c in win:
        if c["l"] <= price <= c["h"]:
            return c["t"]
    return signal_ts


def _entry_fill(t: dict, cs: list[dict], model: str):
    """Return (entry_price, fill_ts) or (None, reason).

    fill_ts is the minute the position actually opens — the candle whose range first
    contains the fill price for a limit/range fill, or the signal candle for a market
    fill. simulate() walks SL/TP/event management from fill_ts, never from the signal
    minute, so management cannot act on candles before the position existed.
    """
    a = ms(t["date"])
    win = window(cs, a, a + FILL_WINDOW_H * 3600 * 1000)
    if not win:
        return None, "no_data"
    is_long = t["direction"] == "LONG"
    if model == "market":
        return win[0]["o"], a          # market fills at the signal-candle open: fill_ts == a
    lo = t.get("entry_lo"); hi = t.get("entry_hi"); posted = t.get("entry")
    rlo = min(c["l"] for c in win); rhi = max(c["h"] for c in win)
    if model == "posted":
        if not isinstance(posted, (int, float)):
            return None, "no_entry"
        if rlo <= posted <= rhi:
            return posted, _first_touch_ts(win, posted, a)
        return None, "no_fill"
    if model == "edge":
        if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float))):
            posted = t.get("entry")
            if not isinstance(posted, (int, float)):
                return None, "no_entry"
            lo = hi = posted
        if is_long:                       # buy: best is the low edge if price dips to it
            if rlo > hi:
                return None, "no_fill"
            fill = max(lo, rlo)
            return fill, _first_touch_ts(win, fill, a)
        else:                             # short: best is the high edge if price rises to it
            if rhi < lo:
                return None, "no_fill"
            fill = min(hi, rhi)
            return fill, _first_touch_ts(win, fill, a)
    return None, "bad_model"


def _pnl_units(is_long: bool, frac: float, entry: float, exit_p: float) -> float:
    return frac * ((exit_p - entry) if is_long else (entry - exit_p))


def _simulate_ladder(t, cs, ep, is_long, sl, a):
    """MECHANICAL equal-fraction TP ladder + SL->breakeven after TP1 + hard SL.

    sl=None  => no hard stop is live until TP1; the position rides unstopped until a
    TP1 hit moves the stop to breakeven (used for the no-hard-stop diagnostic).
    """
    risk = abs(ep - sl) if isinstance(sl, (int, float)) else None
    walk = [c for c in cs if c["t"] >= a]
    tps = sorted([x for x in (t.get("tps") or []) if isinstance(x, (int, float))],
                 reverse=not is_long)
    n = len(tps)
    remaining = 1.0
    realized = 0.0
    cur_sl = sl                       # may be None => unstopped until TP1
    tp_idx = 0
    n_hits = 0
    frac = (1.0 / n) if n else 0.0
    end = a + MAX_TAIL_HOURS * 3600 * 1000
    exit_kind = "open"
    for c in walk:
        if c["t"] >= end:
            break
        hit_sl = cur_sl is not None and ((c["l"] <= cur_sl) if is_long else (c["h"] >= cur_sl))
        if hit_sl:
            realized += _pnl_units(is_long, remaining, ep, cur_sl)
            remaining = 0.0
            exit_kind = "sl" if n_hits == 0 else "tp_then_sl"
            break
        while tp_idx < n:
            tp = tps[tp_idx]
            hit_tp = (c["h"] >= tp) if is_long else (c["l"] <= tp)
            if not hit_tp:
                break
            realized += _pnl_units(is_long, frac, ep, tp)
            remaining -= frac
            n_hits += 1
            tp_idx += 1
            if n_hits == 1:
                cur_sl = ep            # SL -> breakeven after TP1
        if remaining <= 1e-9:
            exit_kind = "ladder"
            break
    if remaining > 1e-9:
        capped = [c for c in walk if c["t"] < end]   # honor MAX_TAIL_HOURS, not cache end
        if capped:
            realized += _pnl_units(is_long, remaining, ep, capped[-1]["c"])
            exit_kind = "tail" if n_hits == 0 else ("tp_then_tail" if exit_kind == "open" else exit_kind)
            remaining = 0.0
    return realized, risk, exit_kind, n_hits


def _simulate_manage(t, cs, ep, is_long, sl, a):
    """FOLLOW Dennis's posted management timeline (events[]).

    Walks candle-by-candle. Between events the CURRENT SL is live (hard SL if posted,
    or a breakeven stop once an event moves it there). At each event timestamp we apply
    the posted action (partial close at event-time price, SL move, or full close).
    SL is checked first within a candle (conservative).
    """
    # only events at/after the actual fill: a copier cannot act on management that was
    # posted before its position existed (pre-fill look-ahead guard — codex gate fix).
    events = sorted([e for e in (t.get("events") or []) if ms(e["t"]) >= a],
                    key=lambda e: ms(e["t"]))
    walk = [c for c in cs if c["t"] >= a]
    end = a + MAX_TAIL_HOURS * 3600 * 1000
    remaining = 1.0
    realized = 0.0
    cur_sl = sl if isinstance(sl, (int, float)) else None
    n_partials = 0
    ev_idx = 0
    exit_kind = "open"

    for c in walk:
        if c["t"] >= end:
            break
        # 1) honor current SL first (conservative, only if a stop exists)
        if cur_sl is not None and remaining > 1e-9:
            hit_sl = (c["l"] <= cur_sl) if is_long else (c["h"] >= cur_sl)
            if hit_sl:
                realized += _pnl_units(is_long, remaining, ep, cur_sl)
                remaining = 0.0
                exit_kind = "sl" if n_partials == 0 else "managed_then_sl"
                break
        # 2) apply every event whose timestamp falls at/before this candle
        while ev_idx < len(events) and ms(events[ev_idx]["t"]) <= c["t"]:
            e = events[ev_idx]
            ev_idx += 1
            act = e.get("action")
            ep_t = price_at(cs, ms(e["t"]))  # mark price at the event minute
            if act == "close_full":
                if ep_t is not None and remaining > 1e-9:
                    realized += _pnl_units(is_long, remaining, ep, ep_t)
                remaining = 0.0
                exit_kind = "managed_full"
                break
            if act in ("close",):
                if "frac_of_remaining" in e:
                    f = e["frac_of_remaining"] * remaining
                else:
                    f = min(e.get("frac", 0.0), remaining)
                if ep_t is not None and f > 0:
                    realized += _pnl_units(is_long, f, ep, ep_t)
                    remaining -= f
                    n_partials += 1
            slto = e.get("sl_to")
            if slto == "breakeven":
                cur_sl = ep  # move stop to entry (breakeven)
            elif isinstance(slto, (int, float)):
                cur_sl = slto  # posted numeric SL move (may sit above entry on a short = locked profit)
        if remaining <= 1e-9:
            if exit_kind == "open":
                exit_kind = "managed_full"
            break
    # tail: anything still open after the timeline ran out
    if remaining > 1e-9:
        capped = [c for c in walk if c["t"] < end]   # honor MAX_TAIL_HOURS, not cache end
        if capped:
            realized += _pnl_units(is_long, remaining, ep, capped[-1]["c"])
            exit_kind = "tail" if n_partials == 0 else "managed_then_tail"
            remaining = 0.0
    risk = abs(ep - sl) if isinstance(sl, (int, float)) else None
    return realized, risk, exit_kind, n_partials


def simulate(t: dict, entry_model: str = "posted", exit_model: str = "ladder") -> Result:
    sym = t["symbol"]; is_long = t["direction"] == "LONG"
    if not t.get("date"):
        return Result(sym, t["direction"], entry_model, exit_model, "none", False,
                      None, None, None, "unplaceable", note="no timestamp (UNPLACEABLE)")
    cs, venue = candles(sym)
    if not cs:
        return Result(sym, t["direction"], entry_model, exit_model, "none", False,
                      None, None, None, "no_data")
    sl = t.get("sl")
    has_sl = isinstance(sl, (int, float))

    # entry fill (independent of exit model). On success `info` is the TRUE fill_ts —
    # the minute the position actually opened (limit touch, or signal-candle open for
    # market). Management walks from there, NOT from the signal minute, so SL/TP/events
    # can never act on candles before the position existed (no pre-fill look-ahead).
    ep, info = _entry_fill(t, cs, entry_model)
    if ep is None:
        return Result(sym, t["direction"], entry_model, exit_model, venue, False,
                      None, None, None, info)
    a = info                              # walk start = actual fill timestamp

    has_events = bool(t.get("events"))
    use_manage = exit_model == "manage" and has_events

    if use_manage:
        realized, risk, exit_kind, n_part = _simulate_manage(t, cs, ep, is_long, sl, a)
    else:
        # ladder model, OR manage with no posted events => mechanical ladder fallback.
        if not has_sl and not (t.get("tps")):
            # nothing to manage mechanically and no stop: walk to tail (capped at MAX_TAIL_HOURS)
            end = a + MAX_TAIL_HOURS * 3600 * 1000
            walk = [c for c in cs if a <= c["t"] < end]   # honor MAX_TAIL_HOURS, not cache end
            realized = _pnl_units(is_long, 1.0, ep, walk[-1]["c"]) if walk else 0.0
            risk = None
            exit_kind = "tail_no_rule"
            n_part = 0
        elif not has_sl:
            # TPs but no hard SL: ride unstopped until TP1, then breakeven-only protection
            realized, risk, exit_kind, n_part = _simulate_ladder(
                t, cs, ep, is_long, None, a)   # no hard SL until TP1 moves it to breakeven
            risk = None
            exit_kind = "ladder_no_sl" if exit_kind in ("ladder", "tail", "tp_then_tail") else exit_kind
        else:
            realized, risk, exit_kind, n_part = _simulate_ladder(t, cs, ep, is_long, sl, a)
        if exit_model == "manage" and not has_events:
            exit_kind = exit_kind + "(no_events->ladder)"

    realized_R = (realized / risk) if (risk and risk > 0) else None
    return Result(sym, t["direction"], entry_model, exit_model, venue, True,
                  round(ep, 8),
                  round(realized_R, 3) if realized_R is not None else None,
                  round(realized / ep, 6) if ep else None,
                  exit_kind, n_part,
                  note=("no hard SL posted" if not has_sl else ""))


def run(trades: list[dict], entry_model: str = "posted", exit_model: str = "ladder"):
    rows = [simulate(t, entry_model, exit_model) for t in trades]
    sized = [r for r in rows if r.realized_R is not None]          # risk-sized (has SL)
    totR = sum(r.realized_R for r in sized)
    wins = [r for r in sized if r.realized_R > 0]
    return rows, sized, totR, wins


if __name__ == "__main__":
    import sys
    tf = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "trades.json")
    trades = json.load(open(tf))
    print(f"loaded {len(trades)} trades from {tf}")
    dated = [t for t in trades if t.get("date")]
    with_sl = [t for t in dated if isinstance(t.get("sl"), (int, float))]
    print(f"  dated/placeable: {len(dated)}/{len(trades)}   posted-SL (risk-sizeable): {len(with_sl)}/{len(trades)}\n")

    for exit_model in ("ladder", "manage"):
        print(f"################## EXIT MODEL = {exit_model} ##################")
        for entry_model in ("posted", "edge", "market"):
            rows, sized, totR, wins = run(trades, entry_model, exit_model)
            acct = totR * RISK_PCT
            print(f"=== entry={entry_model:7} exit={exit_model:7} === "
                  f"sized={len(sized)}/{len(trades)}  totalR={totR:+.2f}  "
                  f"WR={len(wins)}/{len(sized)}  acct@{RISK_PCT}%={acct:+.1f}%")
            for r in rows:
                rstr = ('R=' + format(r.realized_R, '+.2f')) if r.realized_R is not None else r.exit_kind
                print(f"   {r.symbol:9}{r.direction:6}{rstr:>11}  "
                      f"fill={r.entry_price}  {r.exit_kind}  parts={r.n_partials}  [{r.venue}] {r.note}")
            print()
