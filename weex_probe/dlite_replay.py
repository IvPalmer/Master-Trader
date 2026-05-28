"""Replay every Insiders Scalp event through the D-lite executor sketch.

For each of 147 trades in trades_llm_2026-05-26.json:
  1. Generate an `open` TradeIntent from entry/sl/tp/direction/symbol
  2. For each event in chronological order, generate the matching intent
  3. Dispatch it through DLiteExecutor (mocked WEEX, no live calls)
  4. Collect per-intent validation outcome + error type

Then aggregate:
  - total intents processed
  - payload-valid rate
  - error breakdown by type
  - symbols flagged at $25, $50, $100 notional
  - architectural gaps logged
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from typing import Any

from dlite_executor_sketch import DLiteExecutor, TradeIntent


def load_inputs(replay_dir: str, probe_dir: str) -> tuple[dict, dict, dict]:
    trades = json.load(open(os.path.join(replay_dir, "trades_llm_2026-05-26.json")))
    info = json.load(open(os.path.join(probe_dir, "exchange_info_cache.json")))
    marks = json.load(open(os.path.join(probe_dir, "mark_price_cache.json")))
    return trades, info, marks


def intents_from_trade(trade: dict, notional_usd: float) -> list[TradeIntent]:
    """Produce the full intent cascade for a single replay trade.

    Open intent always first, then events in chronological order. Events
    are tagged with parent_trade_id so the executor can find the position.
    """
    trade_id = f"msg{trade['msg_id']}"

    def _f(v: Any) -> Any:
        if v is None or isinstance(v, (int, float)):
            return v
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return None
        return None

    out: list[TradeIntent] = []
    out.append(TradeIntent(
        intent_id=f"{trade_id}-open",
        symbol=trade["symbol"],
        direction=trade["direction"],
        kind="open",
        entry=_f(trade.get("entry")),
        sl=_f(trade.get("sl")),
        tp=_f(trade.get("tp")),
        notional_usd=notional_usd,
    ))
    # Events are already in chronological order in the JSON
    for idx, ev in enumerate(trade.get("events") or []):
        kind = ev.get("kind")
        if kind not in ("close_partial", "close_full", "move_sl", "increase", "detail"):
            # Unknown — pass through and let executor flag it
            kind = kind or "unknown"
        sl_val = ev.get("sl")
        # Resolve "breakeven" string → None (executor uses entry_price)
        if isinstance(sl_val, str):
            sl_val = None
        out.append(TradeIntent(
            intent_id=f"{trade_id}-ev{idx}",
            symbol=trade["symbol"],
            direction=trade["direction"],
            kind=kind,
            sl=sl_val if isinstance(sl_val, (int, float)) else None,
            pct=ev.get("pct"),
            notional_usd=notional_usd,
            parent_trade_id=f"{trade_id}-open",
        ))
    return out


def replay_at_notional(trades_doc: dict, info: dict, marks: dict, notional_usd: float) -> dict:
    """Run a single notional configuration through the executor and aggregate."""
    ex = DLiteExecutor(client=None, exchange_info=info, mark_price_cache=marks)
    error_types: Counter = Counter()
    kind_counts: Counter = Counter()
    phase_counts: Counter = Counter()
    sym_issues: defaultdict = defaultdict(Counter)  # sym -> error_type -> count
    total_intents = 0
    valid_payloads = 0
    inflated_notional_examples: list[tuple[str, float, float]] = []  # (sym, target, actual)

    for trade in trades_doc.get("trades", []):
        intents = intents_from_trade(trade, notional_usd)
        for intent in intents:
            total_intents += 1
            kind_counts[intent.kind] += 1
            resp = ex.dispatch(intent)
            if resp.get("ok"):
                valid_payloads += 1
                # Check for min-size inflation on opens
                if intent.kind == "open" and resp.get("payload") and "quantity" in resp["payload"]:
                    state = ex.positions.get(intent.intent_id)
                    if state is not None:
                        actual_notional = state.contracts * state.contract_val * state.entry_price
                        if actual_notional > notional_usd * 1.5:
                            inflated_notional_examples.append(
                                (state.weex_symbol, notional_usd, actual_notional))
            else:
                err = resp.get("error_type", "unknown")
                error_types[err] += 1
                sym_issues[intent.symbol][err] += 1

    for je in ex.journal:
        phase_counts[je.phase] += 1

    # Aggregate
    return {
        "notional_usd": notional_usd,
        "total_intents": total_intents,
        "valid_payloads": valid_payloads,
        "pass_rate": valid_payloads / total_intents if total_intents else 0,
        "error_types": dict(error_types),
        "kind_counts": dict(kind_counts),
        "phase_counts": dict(phase_counts),
        "sym_issues": {k: dict(v) for k, v in sym_issues.items() if v},
        "inflated_notional_examples": inflated_notional_examples[:20],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay-dir",
                    default="/Users/palmer/Work/Dev/master-trader/docs/insiders-signals/replay")
    ap.add_argument("--probe-dir",
                    default="/Users/palmer/Work/Dev/master-trader/weex_probe")
    ap.add_argument("--notional", type=float, nargs="+", default=[25.0, 50.0, 100.0])
    args = ap.parse_args()

    trades, info, marks = load_inputs(args.replay_dir, args.probe_dir)

    print(f"trades loaded: {len(trades['trades'])}")
    print(f"exchange symbols: {len(info.get('symbols', []))}")
    print(f"mark prices cached: {len(marks)}")

    for n in args.notional:
        print("=" * 70)
        print(f"REPLAY @ ${n:.0f} NOTIONAL")
        print("=" * 70)
        r = replay_at_notional(trades, info, marks, n)
        print(f"  total intents : {r['total_intents']}")
        print(f"  valid payloads: {r['valid_payloads']}")
        print(f"  pass rate     : {r['pass_rate']*100:.2f}%")
        print(f"  by kind       : {r['kind_counts']}")
        print(f"  by phase      : {r['phase_counts']}")
        print(f"  error types   :")
        for et, c in sorted(r["error_types"].items(), key=lambda kv: -kv[1]):
            print(f"    {et:30s} {c}")
        if r["sym_issues"]:
            print(f"  per-symbol issues:")
            for sym, errs in sorted(r["sym_issues"].items()):
                total = sum(errs.values())
                print(f"    {sym:14s} {total:3d}  {dict(errs)}")
        if r["inflated_notional_examples"]:
            print(f"  notional inflation examples (>1.5x target):")
            for sym, target, actual in r["inflated_notional_examples"]:
                print(f"    {sym:14s} target=${target:.0f}  actual=${actual:.2f} ({actual/target:.1f}x)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
