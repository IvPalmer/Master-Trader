"""Proper event-driven backtest of Dennis's Insiders Scalp trades.

Neither prior sim modeled Dennis's actual strategy:
  - The +76% sim stamped phantom mark-to-end exit prices (e.g. msg 79 BTC
    long claimed exit 76,095 when real BTC max in the window was 69,958 and
    SL was hit at 65,081). It ignored all partial closes + SL moves.
  - The agent's +24.8% re-walk used initial-SL/TP-only, scoring managed
    scale-out trades as clean SL losses.

This sim processes the FULL event stream per trade:
  entry -> [walk OHLCV for SL/TP between events] -> partial closes at
  event-time price -> trailing SL moves -> increases -> close_full -> blended PnL.

Sizing matches the original methodology for comparability:
  notional = RISK_PER_TRADE / sl_distance_pct  ($10 risk, $1k account)
  PnL_usd  = sum over closed chunks of  chunk_units * (exit - avg_entry)   [long]

Price source pluggable: 'binance' (fapi) or 'weex' (api-contract). Data is
fetched clean per-window (paginated, no gaps) and cached on disk.

Usage:
  python3 proper_backtest.py binance
  python3 proper_backtest.py weex
  python3 proper_backtest.py both
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
TRADES_JSON = HERE.parent / "docs/insiders-signals/replay/trades_llm_2026-05-26.json"
CACHE_DIR = HERE / "backtest_klines"
CACHE_DIR.mkdir(exist_ok=True)

ACCOUNT = 1000.0
RISK_PER_TRADE = 10.0
MARGIN_PER_TRADE = 50.0

# Default pct when a close_partial / increase carries no explicit pct.
DEFAULT_PARTIAL_PCT = 33.0
DEFAULT_INCREASE_PCT = 25.0

# How long to keep walking for SL/TP after the last event before marking out.
MAX_TAIL_HOURS = 48

BINANCE_FAPI = "https://fapi.binance.com"
WEEX_BASE = "https://api-contract.weex.com"


# ── symbol mapping ─────────────────────────────────────────────────────────

def binance_pair(sym: str) -> str:
    s = sym.upper()
    # Binance uses 1000-prefix for these
    if s in ("PEPE", "SHIB", "FLOKI", "BONK"):
        return f"1000{s}USDT"
    return f"{s}USDT"


def weex_pair(sym: str) -> str:
    s = sym.upper()
    if s in ("PEPE", "SHIB", "FLOKI", "BONK"):
        return f"1000{s}USDT"
    return f"{s}USDT"


# ── price fetch (clean, paginated, cached) ─────────────────────────────────

def _http_json(url: str, params: dict):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt == 3:
                raise
            time.sleep(1.5 * (attempt + 1))
    return None


def fetch_binance(pair: str, start_ms: int, end_ms: int) -> list[dict]:
    out = []
    cur = start_ms
    while cur < end_ms:
        rows = _http_json(f"{BINANCE_FAPI}/fapi/v1/klines", {
            "symbol": pair, "interval": "1m",
            "startTime": cur, "endTime": end_ms, "limit": 1500,
        })
        if not rows:
            break
        for r in rows:
            out.append({"t": int(r[0]), "o": float(r[1]), "h": float(r[2]),
                        "l": float(r[3]), "c": float(r[4])})
        last = int(rows[-1][0])
        if last <= cur:
            break
        cur = last + 60_000
        if len(rows) < 1500:
            break
    return out


def fetch_weex(pair: str, start_ms: int, end_ms: int) -> list[dict]:
    out = []
    cur = start_ms
    while cur < end_ms:
        rows = _http_json(f"{WEEX_BASE}/capi/v3/market/klines", {
            "symbol": pair, "interval": "1m",
            "startTime": cur, "endTime": end_ms, "limit": 1500,
        })
        if not rows or not isinstance(rows, list):
            break
        batch = []
        for r in rows:
            try:
                batch.append({"t": int(r[0]), "o": float(r[1]), "h": float(r[2]),
                              "l": float(r[3]), "c": float(r[4])})
            except (ValueError, TypeError, IndexError):
                continue
        if not batch:
            break
        out.extend(batch)
        last = batch[-1]["t"]
        if last <= cur:
            break
        cur = last + 60_000
        if len(batch) < 1500:
            break
    out.sort(key=lambda c: c["t"])
    return out


def get_window(source: str, sym: str, start_ms: int, end_ms: int) -> list[dict]:
    pair = binance_pair(sym) if source == "binance" else weex_pair(sym)
    cache = CACHE_DIR / f"{source}_{pair}_{start_ms}_{end_ms}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    try:
        candles = fetch_binance(pair, start_ms, end_ms) if source == "binance" \
            else fetch_weex(pair, start_ms, end_ms)
    except Exception as e:
        candles = []
    cache.write_text(json.dumps(candles))
    return candles


def price_at(source: str, sym: str, ts_ms: int) -> float | None:
    """1-min candle open covering ts_ms."""
    minute = ts_ms - (ts_ms % 60_000)
    candles = get_window(source, sym, minute, minute + 120_000)
    if not candles:
        return None
    c = min(candles, key=lambda x: abs(x["t"] - minute))
    if abs(c["t"] - minute) > 5 * 60_000:
        return None
    return c["o"]


# ── event-driven simulation ────────────────────────────────────────────────

def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def ms(s: str) -> int:
    return int(parse_dt(s).timestamp() * 1000)


@dataclass
class SimResult:
    msg_id: int
    symbol: str
    direction: str
    realized_pnl_usd: float
    notional: float
    leverage: float
    n_partials: int
    n_sl_moves: int
    n_increases: int
    exit_kind: str          # 'sl' | 'tp' | 'close_full' | 'mark_tail' | 'no_data'
    detail: str = ""


def simulate_trade(t: dict, source: str,
                   partial_default: float = DEFAULT_PARTIAL_PCT) -> SimResult | None:
    sym = t["symbol"]
    direction = t["direction"]
    entry = t.get("entry")
    init_sl = t.get("sl")
    init_tp = t.get("tp")
    if entry is None or init_sl is None or not isinstance(entry, (int, float)) \
       or not isinstance(init_sl, (int, float)) or entry <= 0:
        return None
    sl_dist = abs(entry - init_sl) / entry
    if sl_dist <= 0:
        return None

    notional = RISK_PER_TRADE / sl_dist
    leverage = notional / MARGIN_PER_TRADE
    units0 = notional / entry              # base coins for the initial position
    is_long = direction == "LONG"

    # mutable position state
    remaining = units0
    avg_entry = entry
    realized = 0.0
    current_sl = init_sl
    current_tp = init_tp

    n_partials = n_slmoves = n_incr = 0

    entry_ms = ms(t["date"])
    events = sorted(t.get("events", []), key=lambda e: e["date"])

    def close_units(u: float, p: float):
        nonlocal realized
        if is_long:
            realized += u * (p - avg_entry)
        else:
            realized += u * (avg_entry - p)

    def walk_for_stop(a_ms: int, b_ms: int) -> tuple[str, float] | None:
        """Walk 1m candles in [a,b). Return ('sl'|'tp', price) on first hit."""
        if b_ms <= a_ms:
            return None
        candles = get_window(source, sym, a_ms, b_ms)
        for c in candles:
            if c["t"] < a_ms or c["t"] >= b_ms:
                continue
            if is_long:
                # SL-first (conservative)
                if current_sl and c["l"] <= current_sl:
                    return ("sl", current_sl)
                if current_tp and c["h"] >= current_tp:
                    return ("tp", current_tp)
            else:
                if current_sl and c["h"] >= current_sl:
                    return ("sl", current_sl)
                if current_tp and c["l"] <= current_tp:
                    return ("tp", current_tp)
        return None

    # Build timeline boundaries
    prev_ms = entry_ms
    exit_kind = "open"
    for e in events:
        e_ms = ms(e["date"])
        # 1) walk OHLCV from prev_ms to this event for SL/TP
        hit = walk_for_stop(prev_ms, e_ms)
        if hit:
            close_units(remaining, hit[1])
            remaining = 0.0
            exit_kind = hit[0]
            break
        # 2) apply the event at its timestamp
        kind = e["kind"]
        if kind == "close_partial":
            pct = e.get("pct")
            pct = float(pct) if isinstance(pct, (int, float)) else partial_default
            ep = price_at(source, sym, e_ms)
            if ep is not None and remaining > 0:
                cu = remaining * min(pct, 100.0) / 100.0
                close_units(cu, ep)
                remaining -= cu
                n_partials += 1
        elif kind == "move_sl":
            sl_val = e.get("sl")
            if sl_val == "breakeven":
                current_sl = avg_entry
                n_slmoves += 1
            elif isinstance(sl_val, (int, float)):
                current_sl = float(sl_val)
                n_slmoves += 1
        elif kind == "increase":
            pct = e.get("pct")
            pct = float(pct) if isinstance(pct, (int, float)) else DEFAULT_INCREASE_PCT
            ep = price_at(source, sym, e_ms)
            if ep is not None:
                add_u = units0 * pct / 100.0
                if remaining + add_u > 0:
                    avg_entry = (avg_entry * remaining + ep * add_u) / (remaining + add_u)
                remaining += add_u
                n_incr += 1
        elif kind == "close_full":
            ep = price_at(source, sym, e_ms)
            if ep is not None and remaining > 0:
                close_units(remaining, ep)
                remaining = 0.0
            exit_kind = "close_full"
            break
        prev_ms = e_ms

    # tail: position still open after all events
    if remaining > 1e-12 and exit_kind in ("open",):
        tail_end = prev_ms + MAX_TAIL_HOURS * 3600 * 1000
        hit = walk_for_stop(prev_ms, tail_end)
        if hit:
            close_units(remaining, hit[1])
            remaining = 0.0
            exit_kind = hit[0]
        else:
            # mark out at last available candle in the tail window
            candles = get_window(source, sym, prev_ms, tail_end)
            if candles:
                close_units(remaining, candles[-1]["c"])
                remaining = 0.0
                exit_kind = "mark_tail"
            else:
                exit_kind = "no_data"

    return SimResult(
        msg_id=t["msg_id"], symbol=sym, direction=direction,
        realized_pnl_usd=round(realized, 2), notional=round(notional, 2),
        leverage=round(leverage, 2), n_partials=n_partials,
        n_sl_moves=n_slmoves, n_increases=n_incr, exit_kind=exit_kind,
    )


def run(source: str, partial_default: float = DEFAULT_PARTIAL_PCT):
    d = json.load(open(TRADES_JSON))
    trades = d["trades"]
    results = []
    skipped = 0
    for t in trades:
        r = simulate_trade(t, source, partial_default)
        if r is None:
            skipped += 1
            continue
        results.append(r)

    total = sum(r.realized_pnl_usd for r in results)
    wins = [r for r in results if r.realized_pnl_usd > 0]
    losses = [r for r in results if r.realized_pnl_usd < 0]
    gross_win = sum(r.realized_pnl_usd for r in wins)
    gross_loss = -sum(r.realized_pnl_usd for r in losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    no_data = [r for r in results if r.exit_kind == "no_data"]

    print(f"\n{'='*64}\n  SOURCE: {source}   partial_default={partial_default}%\n{'='*64}")
    print(f"  trades simulated: {len(results)}  (skipped {skipped} no-entry/no-SL)")
    print(f"  TOTAL PnL: ${total:.2f}   account return: {total/ACCOUNT*100:.2f}%")
    print(f"  win rate: {len(wins)}/{len(results)} = {len(wins)/max(1,len(results))*100:.1f}%")
    print(f"  profit factor: {pf:.2f}")
    print(f"  gross win ${gross_win:.2f} / gross loss ${gross_loss:.2f}")
    print(f"  no-data trades (excluded from trust): {len(no_data)}")
    # exit kind distribution
    from collections import Counter
    print(f"  exit kinds: {dict(Counter(r.exit_kind for r in results))}")
    # top winners / losers
    st = sorted(results, key=lambda r: r.realized_pnl_usd)
    print("  worst 5:", [(r.msg_id, r.symbol, r.realized_pnl_usd, r.exit_kind) for r in st[:5]])
    print("  best 5: ", [(r.msg_id, r.symbol, r.realized_pnl_usd, r.exit_kind) for r in st[-5:]])
    return results, total


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "binance"
    if mode == "both":
        run("binance")
        run("weex")
    else:
        run(mode)
