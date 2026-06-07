"""interpreter.py — pluggable intent producer (SPEC §4).

Maps a BOUNDED prompt to a structured Intent. Two implementations behind one interface:
  - ClaudeCliInterpreter : shells out to `claude -p --output-format json` with tools/file/network
                           DISABLED, so the model's whole world is the prompt text.
  - MockInterpreter      : deterministic table lookup, used by every causality unit test so the
                           harness/oracle/audit/ledger are exercised with ZERO model variance.

Imports nothing in-package: it receives a SERIALIZED prompt + JSON snapshots, NOT a Slice,
PriceOracle, or PositionLedger. This is the structural guarantee behind I2 — a future-data read
is impossible by construction.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field, asdict
from typing import Optional, Protocol


# --------------------------------------------------------------------------- #
# Evidence shapes                                                             #
# --------------------------------------------------------------------------- #
@dataclass
class CandleRef:
    """A cited candle, tagged with symbol+venue so audit.py can resolve + existence-check it.

    A bare timestamp with no symbol/venue is NOT auditable, so it is structurally disallowed.
    """

    symbol: str
    venue: str  # "weex" | "binance" | "hyperliquid"
    t_ms: int   # candle open-time (epoch-ms)


@dataclass
class Evidence:
    msg_ids: list           # every message id the decision relied on
    candles: list           # list[CandleRef] — every candle the decision relied on
    # NOTE: there is intentionally NO 'used_only_causal_prefix' self-cert field.
    # Causality is established by auditing these refs (audit.py), not by a model-set boolean.

    def __post_init__(self):
        # coerce dict-shaped candle refs (e.g. from JSON) into CandleRef
        norm = []
        for c in self.candles:
            if isinstance(c, CandleRef):
                # normalize casing so a model that writes venue "WEEX"/symbol "btc" still resolves
                norm.append(CandleRef(symbol=c.symbol.upper(), venue=c.venue.lower(), t_ms=int(c.t_ms)))
            elif isinstance(c, dict):
                norm.append(CandleRef(symbol=str(c["symbol"]).upper(), venue=str(c["venue"]).lower(),
                                      t_ms=int(c["t_ms"])))
            else:
                raise TypeError(f"candle evidence must be CandleRef or dict, got {type(c)!r}")
        self.candles = norm


@dataclass
class Intent:
    intent_type: str       # "open"|"open_partial"|"close_partial"|"close_full"|"sl_to"|"commentary"|"abstain"
    symbol: Optional[str]
    side: Optional[str]    # "long" | "short" | None
    action_now: str        # "open"|"close_partial"|"close_full"|"sl_move"|"abstain-hold"|"abstain-flat"
    inferred_state: str
    epistemic_tag: str     # "price-confirmed"|"declared-by-dennis"|"inferred-unconfirmed"|"commentary-no-position-change"
    confidence: float
    reasoning: str
    evidence: Evidence
    # optional structured fields mirrored from the fixtures when present:
    fraction_closed_now_of_original: Optional[float] = None
    fraction_remaining_of_original: Optional[float] = None
    # close mechanics (how a close_partial reduces size): "frac" (of held) | "frac_of_remaining"
    close_mode: Optional[str] = None
    close_frac: Optional[float] = None
    # sl_to target: numeric or the literal "breakeven"
    sl_to: Optional[object] = None
    # explicit close price if Dennis posted one (else None -> oracle reference price)
    close_price: Optional[float] = None
    # opener metadata for intent_type=open/open_partial: the entry zone / SL / TPs / staged legs
    # the model EXTRACTS from the message text. sl MUST be corroborated by a cited <=T message
    # (audit 'unbound_sl' gate) — the model cannot fabricate a tighter stop to inflate R. The
    # fill price is oracle-confirmed (clamped to the real candle), so entry_lo/hi are not R-bearing.
    open_meta: Optional[dict] = None

    def to_jsonable(self) -> dict:
        d = asdict(self)
        # asdict turns Evidence + CandleRef into nested dicts already; ensure ordering stable
        return d


# --------------------------------------------------------------------------- #
# Bounded prompt — assembled BY THE HARNESS from ONLY bounded data.           #
# --------------------------------------------------------------------------- #
@dataclass
class BoundedPrompt:
    """Carries only bounded data: a serialized string + JSON snapshots. No oracle/file/clock
    handle — a future-data read is impossible by construction (I2)."""

    T_iso: str
    messages: list           # slice.messages() (date <= T, ascending)
    ledger_snapshot: dict    # ledger.snapshot()
    price_snapshot: dict     # {symbol: {last_t_ms, last_close, recent_window}}
    decision_msg_id: int

    def serialize(self) -> str:
        """Deterministic text serialization fed to the interpreter (and persisted whole)."""
        parts = []
        parts.append(f"DECISION TIME T = {self.T_iso}")
        parts.append(f"DECISION MESSAGE ID = {self.decision_msg_id}")
        parts.append("")
        parts.append("=== MESSAGES (date <= T, ascending; decide at the LAST one) ===")
        for m in self.messages:
            parts.append(f"[id={m['id']}] [{m['date']}] {m.get('from','')}")
            parts.append(m["text"].rstrip())
            parts.append("-" * 50)
        parts.append("")
        parts.append("=== CURRENT LEDGER SNAPSHOT (harness-owned) ===")
        parts.append(json.dumps(self.ledger_snapshot, indent=2, sort_keys=True))
        parts.append("")
        parts.append("=== PRICE SNAPSHOT (last CLOSED candle per symbol, <= T) ===")
        parts.append(json.dumps(self.price_snapshot, indent=2, sort_keys=True))
        return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Interpreter protocol                                                        #
# --------------------------------------------------------------------------- #
class Interpreter(Protocol):
    def interpret(self, prompt: BoundedPrompt) -> Intent: ...


class InterpreterError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Intent JSON schema (system instruction) + parsing                          #
# --------------------------------------------------------------------------- #
INTENT_SYSTEM_INSTRUCTION = """You are a mechanical copy-trader for the 'Insiders scalp' channel.
You are given ONLY messages dated at/before the decision time T, a harness-owned ledger snapshot,
and a price snapshot of the LAST CLOSED candle per symbol. You CANNOT see any future data; do not
speculate about prices after T.

Decide the single action implied by the LAST message and emit ONE JSON object (no prose) with keys:
  intent_type: one of open|open_partial|close_partial|close_full|sl_to|commentary|abstain
  symbol: ticker or null
  side: long|short|null
  action_now: open|close_partial|close_full|sl_move|abstain-hold|abstain-flat
  inferred_state: prose description of the book you believe is live at T
  epistemic_tag: price-confirmed|declared-by-dennis|inferred-unconfirmed|commentary-no-position-change
  confidence: 0..1
  reasoning: brief justification
  evidence: { "msg_ids": [int,...], "candles": [ {"symbol":..,"venue":..,"t_ms":int}, ... ] }
  fraction_closed_now_of_original: float or null
  fraction_remaining_of_original: float or null
  close_mode: "frac"|"frac_of_remaining"|null
  close_frac: float or null
  sl_to: number or "breakeven" or null
  open_meta: for intent_type=open/open_partial ONLY, an object you EXTRACT from the message:
            { "entry_lo": number|null, "entry_hi": number|null, "sl": number|null,
              "tps": [number,...], "legs": [ {"price": number, "frac_of_planned": 0..1}, ... ] }
            Use the entry ZONE and STOP exactly as Dennis posted them. For a staged ladder
            ("20% @ X / 30% @ Y / 50% @ Z") emit one leg per level with its frac_of_planned.
            For a single market/zone entry, one leg covering frac_of_planned=1.0. The `sl` you
            put here MUST appear (as a number) in the text of a message you cite in evidence —
            a stop not present in any cited message is machine-rejected (you cannot invent a stop).
            Omit open_meta (null) for non-open intents.

evidence MUST cite every message id and candle you relied on. Every candle MUST carry symbol,
venue, and t_ms (open-time). Cite NO data later than T — it will be machine-rejected.

Do NOT emit a fill or exit PRICE. The harness derives every fill/exit price itself from the
last closed candle (<= T) or a cited candle; it does NOT accept a price scalar from you. Any
`close_price` (or other raw price scalar) you supply is machine-rejected fail-closed (the run
is voided / the intent dropped). State WHAT to do (close_full, close_partial, sl_to, ...) and
cite the evidence; the harness prices it causally.
"""


def intent_from_dict(d: dict) -> Intent:
    ev = d.get("evidence") or {"msg_ids": [], "candles": []}
    evidence = Evidence(msg_ids=list(ev.get("msg_ids", [])), candles=list(ev.get("candles", [])))
    return Intent(
        intent_type=d["intent_type"],
        symbol=d.get("symbol"),
        side=d.get("side"),
        action_now=d["action_now"],
        inferred_state=d.get("inferred_state", ""),
        epistemic_tag=d.get("epistemic_tag", ""),
        confidence=float(d.get("confidence", 0.0)),
        reasoning=d.get("reasoning", ""),
        evidence=evidence,
        fraction_closed_now_of_original=d.get("fraction_closed_now_of_original"),
        fraction_remaining_of_original=d.get("fraction_remaining_of_original"),
        close_mode=d.get("close_mode"),
        close_frac=d.get("close_frac"),
        sl_to=d.get("sl_to"),
        close_price=d.get("close_price"),
        open_meta=d.get("open_meta"),
    )


# --------------------------------------------------------------------------- #
# ClaudeCliInterpreter                                                        #
# --------------------------------------------------------------------------- #
class ClaudeCliInterpreter:
    """Shells out to the `claude` CLI with tools/file/network DISABLED.

    On schema failure: ONE structured re-ask, then raise InterpreterError (no silent default).
    Records raw stdout via `last_raw_stdout` for the run log.
    """

    def __init__(self, claude_bin: str = "claude", model: Optional[str] = None, timeout_s: int = 120,
                 cmd_override: Optional[list] = None):
        self.claude_bin = claude_bin
        self.model = model
        self.timeout_s = timeout_s
        self.last_raw_stdout: Optional[str] = None
        # cmd_override: full argv (prompt fed via stdin). Use to route to a remote claude, e.g. the
        # VPS elder-brain-bot container when the local Max token is expired:
        #   ["ssh","-o","BatchMode=yes","ubuntu@HOST",
        #    "docker exec -i elder-brain-bot claude -p --output-format json --model sonnet --allowedTools ''"]
        self.cmd_override = cmd_override

    def _invoke(self, prompt_text: str) -> str:
        if self.cmd_override:
            cmd = self.cmd_override
        else:
            cmd = [self.claude_bin, "-p", "--output-format", "json", "--allowedTools", ""]
            if self.model:
                cmd += ["--model", self.model]
        proc = subprocess.run(
            cmd,
            input=prompt_text,
            capture_output=True,
            text=True,
            timeout=self.timeout_s,
        )
        self.last_raw_stdout = proc.stdout
        if proc.returncode != 0:
            raise InterpreterError(f"claude CLI exited {proc.returncode}: {proc.stderr[:500]}")
        return proc.stdout

    @staticmethod
    def _extract_intent_json(stdout: str) -> dict:
        # The CLI returns a JSON envelope; the assistant message contains our JSON object.
        env = json.loads(stdout)
        text = env.get("result") or env.get("content") or env.get("text") or ""
        if isinstance(text, list):
            # content blocks
            text = "".join(b.get("text", "") for b in text if isinstance(b, dict))
        # find the first {...} JSON object in the assistant text
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise InterpreterError("no JSON object found in assistant message")
        return json.loads(text[start : end + 1])

    def interpret(self, prompt: BoundedPrompt) -> Intent:
        full = INTENT_SYSTEM_INSTRUCTION + "\n\n" + prompt.serialize()
        try:
            out = self._invoke(full)
            return intent_from_dict(self._extract_intent_json(out))
        except (json.JSONDecodeError, KeyError, InterpreterError):
            # ONE structured re-ask
            reask = full + "\n\nYOUR PREVIOUS REPLY WAS NOT VALID INTENT JSON. Reply with ONE JSON object only."
            out = self._invoke(reask)
            try:
                return intent_from_dict(self._extract_intent_json(out))
            except Exception as e:  # noqa: BLE001
                raise InterpreterError(f"interpreter produced invalid Intent JSON twice: {e}")


# --------------------------------------------------------------------------- #
# MockInterpreter                                                             #
# --------------------------------------------------------------------------- #
class MockInterpreter:
    """Deterministic. Maps decision_msg_id -> a hardcoded Intent for curated scenarios.

    Used by every causality unit test so the harness/oracle/audit/ledger run with ZERO model
    variance. A 'cheater' variant (built by the test) cites a FUTURE candle to prove the auditor
    rejects it.
    """

    def __init__(self, table: dict):
        self.table = dict(table)

    def interpret(self, prompt: BoundedPrompt) -> Intent:
        mid = prompt.decision_msg_id
        if mid not in self.table:
            raise InterpreterError(f"MockInterpreter has no intent for decision_msg_id {mid}")
        return self.table[mid]
