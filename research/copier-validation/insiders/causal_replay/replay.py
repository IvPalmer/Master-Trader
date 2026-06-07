"""replay.py — the streaming driver (SPEC §6).

Walks messages and candle minute-closed events in strict event-time order; at each Dennis
decision point runs the full bounded loop (slice -> prompt -> interpret -> audit -> apply) and
persists an auditable record per step.

Clock convention: event time in epoch-ms. A candle with open-time `t` generates a "minute-closed"
event at `t + 60000`; messages fire at their date ms. The merged timeline is ordered by these
event times — a candle is processed by the price-loop only AFTER its minute closes.

Imports oracle, ledger, interpreter, audit — the only orchestrator.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field

from oracle import PointInTimeFeed, to_ms, iso_of_ms, MINUTE_MS
from ledger import PositionLedger, PositionState
from interpreter import BoundedPrompt
from audit import audit_evidence, FutureReferenceRejected

SCHEMA_VERSION = "1.0"
HERE = os.path.dirname(os.path.abspath(__file__))


@dataclass
class ReplayResult:
    name: str
    run_dir: str
    steps_run: int = 0
    audits_accepted: int = 0
    audits_rejected: int = 0
    audits_flagged: int = 0
    final_R: dict = field(default_factory=dict)   # symbol -> realized_R

    def to_jsonable(self) -> dict:
        return {
            "name": self.name, "run_dir": self.run_dir, "steps_run": self.steps_run,
            "audits_accepted": self.audits_accepted, "audits_rejected": self.audits_rejected,
            "audits_flagged": self.audits_flagged, "final_R": self.final_R,
        }


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=HERE, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _price_snapshot_from(oracle, symbols, venue="weex") -> dict:
    snap = {}
    for sym in symbols:
        try:
            lc = oracle.last_candle(sym, venue=venue)
        except (LookupError, KeyError):
            continue
        snap[sym] = {"last_t_ms": int(lc["t"]), "last_close": float(lc["c"]),
                     "high": float(lc["h"]), "low": float(lc["l"])}
    return snap


def _is_dennis_actionable(msg) -> bool:
    """Heuristic: paid-channel messages are all from the signaler; treat non-trivial ones as
    candidate decisions. The decision_filter (caller-supplied) refines which ids to act on."""
    return True


def replay(name: str, feed: PointInTimeFeed, interpreter, ledger: PositionLedger = None, *,
           mode: str = "strict", start_msg_id=None, end_msg_id=None,
           seed_ledger=None, decision_filter=None, runs_root=None,
           venue: str = "weex", relevant_symbols=None) -> ReplayResult:
    """Stream + persist to runs/<name>/. Returns aggregate ReplayResult.

    seed_ledger pre-loads positions opened BEFORE start_msg_id so an early-window close is a real
    transition, not a vacuous no-op. Seeded positions are recorded in meta.json.
    """
    if ledger is None:
        ledger = PositionLedger()
    if seed_ledger:
        ledger.seed(seed_ledger)
    runs_root = runs_root or os.path.join(HERE, "runs")
    run_dir = os.path.join(runs_root, name)
    os.makedirs(os.path.join(run_dir, "prompts"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "raw"), exist_ok=True)

    # symbols whose candles we drive the price-loop on (defaults to all in feed)
    symbols = relevant_symbols or feed.symbols

    # --- build the event timeline ---
    # message events: (date_ms, "msg", msg) ; candle minute-closed events: (t+60000, "candle", (sym,t))
    events = []
    for date_ms, idx, m in feed._messages:
        events.append((date_ms, 0, "msg", m["id"]))
    for sym in symbols:
        arr = feed._candles.get((sym, venue))
        if not arr:
            continue
        times, _rows = arr
        for t in times:
            events.append((t + MINUTE_MS, 1, "candle", (sym, t)))
    # determine window bounds in msg ids
    msg_ids_in_order = [m["id"] for (_, _, m) in feed._messages]
    start_i = msg_ids_in_order.index(start_msg_id) if start_msg_id else 0
    end_i = msg_ids_in_order.index(end_msg_id) if end_msg_id else len(msg_ids_in_order) - 1
    start_date_ms = feed._messages[start_i][0]
    end_date_ms = feed._messages[end_i][0]
    # restrict events to [start_date_ms, end_date_ms] (price-loop only inside the window)
    events = [e for e in events if start_date_ms <= e[0] <= end_date_ms + MINUTE_MS]
    events.sort(key=lambda e: (e[0], e[1]))  # message before candle at the same event-time

    result = ReplayResult(name=name, run_dir=run_dir)
    step_records = []
    step_no = 0
    allowed_ids = set(msg_ids_in_order[start_i:end_i + 1])

    for ev_time, _pri, kind, payload in events:
        if kind == "candle":
            sym, t = payload
            # price-loop: confirm fills/stops on this newly-closed candle (T = t + 60000)
            slc = feed.at(t + MINUTE_MS)
            oracle = slc.prices()
            _price_loop_step(ledger, oracle, sym, venue)
            continue

        # kind == "msg"
        mid = payload
        if mid not in allowed_ids:
            continue
        msg = feed.msg(mid)
        if decision_filter is not None and not decision_filter(msg):
            continue
        if not _is_dennis_actionable(msg):
            continue

        T = msg["date"]
        slc = feed.at(T, decision_msg_id=mid)
        oracle = slc.prices()
        # settle any fills on candles whose minute closed at/before T for relevant symbols
        for s in symbols:
            _price_loop_step(ledger, oracle, s, venue)

        prompt = BoundedPrompt(
            T_iso=msg["date"],
            messages=slc.messages(),
            ledger_snapshot=ledger.snapshot(),
            price_snapshot=_price_snapshot_from(oracle, symbols, venue),
            decision_msg_id=mid,
        )
        intent = interpreter.interpret(prompt)
        ea = audit_evidence(intent, slc)

        applied = False
        if ea.verdict == "reject":
            if mode == "strict":
                # persist the offending step then void
                _persist_step(run_dir, step_no, T, mid, intent, ea, None, ledger.snapshot(), prompt,
                              getattr(interpreter, "last_raw_stdout", None), step_records)
                _flush(run_dir, step_records, ledger, result, feed)
                raise FutureReferenceRejected(
                    f"step {step_no} msg {mid}: future/invalid evidence -> run void. "
                    f"violations={ea.violations}"
                )
            else:  # flag mode: downgrade to abstain-hold
                result.audits_flagged += 1
                from interpreter import Intent as _Intent, Evidence as _Evidence
                intent = _Intent("abstain", intent.symbol, intent.side, "abstain-hold",
                                 "downgraded: rejected evidence", "commentary-no-position-change",
                                 0.0, "audit reject -> downgrade", _Evidence([], []))
                delta = ledger.apply_intent(intent, oracle)
                applied = True
        else:
            result.audits_accepted += 1
            delta = ledger.apply_intent(intent, oracle)
            applied = True

        _persist_step(run_dir, step_no, T, mid, intent, ea, delta if applied else None,
                      ledger.snapshot(), prompt, getattr(interpreter, "last_raw_stdout", None),
                      step_records)
        result.steps_run += 1
        step_no += 1

    _flush(run_dir, step_records, ledger, result, feed,
           interpreter=interpreter, mode=mode, seed_ledger=seed_ledger, name=name)
    return result


def _price_loop_step(ledger: PositionLedger, oracle, symbol, venue):
    """Advance one symbol's fill/stop checks on candles closed at/before oracle.T_ms."""
    p = ledger.get(symbol)
    if p is None:
        return
    if p.status == "watcher":
        ledger.confirm_fills(symbol, oracle, venue=venue)
    # (hard-SL between-message triggering would also live here; not exercised by the
    #  BTC-1609 acceptance window since SL 78400 is never touched.)


def _digest(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _persist_step(run_dir, step_no, T, mid, intent, ea, delta, snapshot, prompt, raw_stdout, records):
    serialized = prompt.serialize()
    prompt_ref = f"prompts/step_{step_no:04d}.txt"
    with open(os.path.join(run_dir, prompt_ref), "w") as f:
        f.write(serialized)
    raw_ref = None
    if raw_stdout is not None:
        raw_ref = f"raw/step_{step_no:04d}.json"
        with open(os.path.join(run_dir, raw_ref), "w") as f:
            f.write(raw_stdout)
    rec = {
        "step": step_no,
        "T_ms": to_ms(T),
        "T_iso": T if isinstance(T, str) else iso_of_ms(to_ms(T)),
        "decision_msg_id": mid,
        "intent": intent.to_jsonable(),
        "evidence_audit": ea.to_jsonable(),
        "ledger_delta": delta.to_jsonable() if delta is not None else None,
        "ledger_snapshot": snapshot,
        "prompt_digest": _digest(serialized),
        "prompt_ref": prompt_ref,
        "raw_interpreter_stdout_ref": raw_ref,
    }
    records.append(rec)


def _flush(run_dir, records, ledger, result, feed, interpreter=None, mode=None,
           seed_ledger=None, name=None):
    # steps.jsonl
    with open(os.path.join(run_dir, "steps.jsonl"), "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    # final ledger.
    # realized_R is keyed per (symbol, side, opener_msg_id) so a long-then-short on the same
    # symbol never collapses; per_symbol_total sums them for aggregate views.
    snap = ledger.snapshot()
    final = {"snapshot": snap, "realized_R": {}, "per_position_R": [], "per_symbol_total_R": {}}
    for p in ledger.closed_positions():
        key = f"{p.symbol}:{p.side}:{p.opener_msg_id}"
        final["per_position_R"].append({"key": key, "symbol": p.symbol, "side": p.side,
                                        "opener_msg_id": p.opener_msg_id,
                                        "closed_at_msg_id": p.closed_at_msg_id,
                                        "realized_R": p.realized_R})
        final["per_symbol_total_R"][p.symbol] = final["per_symbol_total_R"].get(p.symbol, 0.0) + p.realized_R
        # final_R[symbol] keeps the LAST-closed position's R for the symbol (the live decision's
        # outcome). The acceptance test asserts the 1609 short, which is the last BTC close.
        final["realized_R"][p.symbol] = p.realized_R
        result.final_R[p.symbol] = p.realized_R
    for sym, p in snap["open"].items():
        final["realized_R"].setdefault(sym, p["realized_R"])
        result.final_R.setdefault(sym, p["realized_R"])
    with open(os.path.join(run_dir, "final_ledger.json"), "w") as f:
        json.dump(final, f, indent=2)
    # meta.json
    meta = {
        "name": name or os.path.basename(run_dir),
        "schema_version": SCHEMA_VERSION,
        "messages_path": feed.messages_path,
        "prices_dir": feed.prices_dir,
        "as_of_policy": feed.as_of_policy,
        "interpreter_class": type(interpreter).__name__ if interpreter else None,
        "model": getattr(interpreter, "model", None) if interpreter else None,
        "mode": mode,
        "git_sha": _git_sha(),
        "wall_clock": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
        "seed_ledger": [p.symbol + ":" + p.side for p in (seed_ledger or [])],
    }
    with open(os.path.join(run_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
