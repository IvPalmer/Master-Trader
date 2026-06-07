#!/usr/bin/env python3
"""Run the prototype's regex pipeline + Eduardo's risk-budget sizing.

For each parsed trade with a valid entry + initial SL:
  - sl_distance = |entry - sl| / entry
  - position_notional = $10 / sl_distance   (1% risk on $1k account)
  - leverage = position_notional / $50       ($50 margin per trade)

Calls weex.resolve_exits with position_size=1.0 to get fractional realized,
then scales per trade. Skips trades with no SL.

Output: out/trades_regex.json (input for render_report.py).

    python3 regex_replay.py
"""
import json
import sys
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).parent
LOCAL = HERE / "_local"
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(LOCAL))

from simulator import simulate  # noqa: E402
from weex import resolve_exits  # noqa: E402

ACCOUNT = 1000.0
RISK_PER_TRADE = 10.0     # 1% of account
MARGIN_PER_TRADE = 50.0   # 5% of account


DEFAULT_INPUT = LOCAL / "last_month_messages.json"
DEFAULT_OUTPUT = OUT / "trades_regex.json"


def load_messages(path: Path):
    content = path.read_text()
    msgs, _ = json.JSONDecoder().raw_decode(content)
    return msgs


def sl_distance_pct(entry, sl):
    if entry is None or sl is None:
        return None
    if isinstance(sl, str):
        return None
    if entry <= 0:
        return None
    return abs(entry - sl) / entry


def position_for(entry, sl):
    d = sl_distance_pct(entry, sl)
    if d is None or d <= 0:
        return None
    return RISK_PER_TRADE / d


def trade_to_dict(t, position_notional, leverage, scaled_pnl):
    d = asdict(t)
    d["events"] = [
        {
            "msg_id": e.msg_id,
            "date": e.date,
            "kind": e.kind,
            "pct": e.pct,
            "sl": e.sl,
            "text": e.text,
        }
        for e in t.events
    ]
    d["position_notional"] = position_notional
    d["leverage"] = leverage
    d["sl_distance_pct"] = sl_distance_pct(t.entry, t.sl)
    d["scaled_pnl"] = scaled_pnl  # in $, after Eduardo's risk-budget sizing
    return d


def main():
    in_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    msgs = load_messages(in_path)
    print(f"loaded {len(msgs)} messages from {in_path}", flush=True)

    trades = simulate(msgs, known_coins=None, resolve_market_entries=False)
    print(f"regex parsed {len(trades)} trades", flush=True)

    sized = [
        t for t in trades
        if t.entry is not None and position_for(t.entry, t.sl) is not None
    ]
    skipped = len(trades) - len(sized)
    print(f"sized: {len(sized)} / {len(trades)}   skipped: {skipped} (no SL or no entry)", flush=True)

    print(f"resolving exits via WEEX (fractional units)...", flush=True)
    resolve_exits(sized, position_size=1.0)

    out_trades = []
    pnl_total = 0.0
    leverages = []
    for t in trades:
        pos = position_for(t.entry, t.sl) if t.entry else None
        lev = (pos / MARGIN_PER_TRADE) if pos else None
        # t.pnl was fractional realized (PS=1.0); scale to $ using per-trade notional.
        scaled = round(pos * (t.pnl or 0), 2) if pos else None
        if scaled is not None:
            pnl_total += scaled
        if lev is not None:
            leverages.append(lev)
        out_trades.append(trade_to_dict(t, pos, lev, scaled))

    out = {
        "source": "regex",
        "n_messages": len(msgs),
        "n_trades_parsed": len(trades),
        "n_trades_sized": len(sized),
        "n_skipped": skipped,
        "account_usd": ACCOUNT,
        "risk_per_trade_usd": RISK_PER_TRADE,
        "margin_per_trade_usd": MARGIN_PER_TRADE,
        "total_pnl_usd": round(pnl_total, 2),
        "account_return_pct": round(pnl_total / ACCOUNT * 100, 2),
        "avg_leverage": round(sum(leverages) / len(leverages), 1) if leverages else None,
        "trades": out_trades,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"wrote {out_path}", flush=True)
    print(f"PnL: ${pnl_total:.2f}  ({pnl_total / ACCOUNT * 100:.2f}% on ${ACCOUNT:.0f})")
    print(f"avg leverage: {out['avg_leverage']}x")


if __name__ == "__main__":
    main()
