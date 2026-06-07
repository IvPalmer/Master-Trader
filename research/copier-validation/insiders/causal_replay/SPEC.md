# Causal Replay Substrate — SPEC

**Status:** design (BUILD phase implements the modules below).
**Owner dir:** `research/insiders_april_replication/causal_replay/`
**Sibling truth dirs:** `../paid_export/paid_messages.json`, `../trades_may.json`,
`../RESULTS_MAY.md`, `../prices_may/<SYM>.<venue>.jsonl`, `../causal_test/` (prior fixtures).

## 0. Why this exists — the hole we are closing

The previous workflow (call it **WF#2**) produced per-decision answers (see
`../causal_test/out/*.json`) whose only causality guarantee was a **self-reported boolean**
`"used_only_causal_prefix": true`. Two failures hide behind that:

1. **The price cache was not time-gated.** The interpreter could read any candle in the
   file — including candles *after* the decision minute T. Nothing structurally stopped a
   look-ahead read; the harness merely *asked* the model not to.
2. **The model self-certified causality and could lie** (or be wrong) about it. A `true`
   flag is not evidence. The "BTC-1609 breakeven trap" is the canonical failure: a model
   that peeked at the future sees BTC fall to 73000 on 05-28 and books a fat win on a short
   that Dennis explicitly closed at breakeven 24 minutes after opening it.

**The fix, in one sentence:** the future must be *absent*, not *ignored*. The harness owns a
**point-in-time feed** that physically cannot return data with `t > T`, owns the position
**ledger** (the model never mutates state directly), and **machine-checks every evidence
reference** the model cites against T. Causality is *enforced by construction and audit*,
never *trusted from the model*.

Non-negotiable invariants (every module upholds at least one):
- **I1 — No future data reachable.** A query that would reveal a candle whose minute has not
  yet closed at T RAISES. Under the default `closed_minute` policy the precise rule is:
  a candle with open-time `t` is observable iff `t + 60000 <= T_ms`; any query that would
  return or depend on a candle violating that RAISES — it does not return `None`, does not
  clamp, does not warn-and-continue. (Throughout this SPEC, shorthand "`t > T`" / "future
  candle" means "fails `t + 60000 <= T_ms`".)
- **I2 — No global state.** No module reads files, clocks, or caches via globals. Everything
  the interpreter sees is passed in explicitly and is already bounded by T.
- **I3 — Cited evidence is checked, not trusted.** Every `msg_id` and `(symbol,venue,candle_ts)`
  the model cites is verified causal (`date <= T` / `t + 60000 <= T_ms`) by the auditor. A
  single future reference flags/rejects the whole intent. **Scope limit (honest):** the audit
  enforces causality of the *cited* evidence and, combined with the bounded prompt (I2),
  guarantees no future data is *in the model's context*. It does NOT and cannot prove the model
  ignored *uncited* knowledge it may hold from pre-training (e.g. that BTC hit 73000 on 05-28).
  That residual is mitigated, not eliminated — see §4 "residual threat" and the deterministic
  MockInterpreter twin (§9 test 6) which removes model variance entirely for the core proof.
- **I4 — Ledger is harness-owned.** State transitions come only from `apply_intent`; the
  prompt receives a read-only snapshot and returns an *intent*, never a mutation.
- **I5 — Determinism where it matters.** Ledger math, fill/stop checks, and the MockInterpreter
  are fully deterministic and reproducible from persisted inputs.

---

## 1. Shared data shapes (frozen — match existing files)

These already exist on disk. The BUILD phase consumes them as-is; it does not reshape them.

**Message** (`paid_export/paid_messages.json` is a JSON list of):
```jsonc
{ "id": 1609, "date": "2026-05-21T21:56:44+00:00", "from": "Insiders scalp", "text": "BTC Short ..." }
```
- `date` is ISO-8601 **with** `+00:00`; parse with `datetime.fromisoformat`. Resolution is
  **seconds**; same-second ties are broken by **original export order** (the list index).
  (The free-channel file `../raw_free_messages.json` adds a `"dennis": bool` flag and is an
  alternate source; the paid export has no such flag — Dennis-authorship is inferred from
  `from`/content. The substrate is source-agnostic: it takes whatever list it is handed.)

**Candle** (`prices_may/<SYM>.<venue>.jsonl`, one JSON object per line):
```jsonc
{ "t": 1779744000000, "o": 77684.1, "h": 77684.1, "l": 77647.2, "c": 77647.2, "v": 19.99 }
```
- `t` is **epoch milliseconds**, candle **open time**, 1-minute bars. `v` may be absent
  (binance files omit it). A candle labeled `t` covers `[t, t+60000)`; it is "knowable" only
  once that minute has *closed*, i.e. it is causal at decision time T (ms) iff `t + 60000 <= T_ms`
  — an in-progress candle is NOT yet observable. (See §2 `as_of_policy`.)
- Venues per symbol: `weex` (primary, has alts), `binance` (majors/parity),
  `hyperliquid` (partial). File suffix `.partial-tail.jsonl` is tolerated.

**Time convention:** all module APIs take T as a `datetime` (tz-aware, UTC) OR epoch-ms;
internally everything compares in epoch-ms (`T_ms`). One helper `to_ms(T)` lives in `oracle.py`
and is the single source of truth for the conversion.

---

## 2. `oracle.py` — PointInTimeFeed + PriceOracle

The bounded window onto the world. Nothing else reads the raw files.

```python
class CausalityViolation(Exception):
    """Raised on ANY attempt to read data at t > T. Carries (symbol, venue, requested_t_ms, T_ms)."""

class PriceOracle:
    """Bounded price reader. Constructed by PointInTimeFeed.at(T); knows its own T_ms.
    Answers ONLY for candles whose minute has closed at/before T. Future RAISES."""

    def candle_at(self, symbol: str, t_ms: int, venue: str = "weex") -> dict:
        """Exact 1m candle whose open time == t_ms. RAISES CausalityViolation if t_ms+60000 > T_ms.
        RAISES KeyError if the minute is in-range but missing from the file (gap)."""

    def last_candle(self, symbol: str, venue: str = "weex") -> dict:
        """Most recent CAUSAL candle (max t with t+60000 <= T_ms). RAISES LookupError if none."""

    def last_price(self, symbol: str, venue: str = "weex") -> float:
        """Convenience: last_candle(...)['c']. The 'current price snapshot <= T' the prompt sees."""

    def window(self, symbol: str, a_ms: int, b_ms: int, venue: str = "weex") -> list[dict]:
        """Candles with a_ms <= t <= b_ms, ascending. RAISES CausalityViolation if b_ms+60000 > T_ms
        (the caller asked for a window extending into the future — refuse the whole call,
        do not silently truncate). Empty list if the in-range slice has no candles."""

    def touched(self, symbol: str, level: float, side: str, since_ms: int,
                venue: str = "weex") -> int | None:
        """First candle (by open-time, ascending) in the causal window whose [l,h] range crosses
        `level` for a stop/target of the given side. The window is open-times in [since_ms, T_causal]
        where T_causal is the max open-time with t+60000 <= T_ms (the last CLOSED minute — the
        in-progress bar is excluded). Used by the price-loop to confirm fills/stops on BOUNDED
        candles only. Returns the crossing candle's open-time, or None if untouched in-window.
        RAISES CausalityViolation if since_ms+60000 > T_ms (caller's start is itself in the future)."""

    @property
    def T_ms(self) -> int: ...
    @property
    def t_causal_ms(self) -> int:
        """Open-time of the last fully-closed candle at T (== max t with t+60000 <= T_ms across the
        symbol's grid; in practice floor((T_ms)/60000)*60000 - 60000). The single reference point
        for 'most recent knowable price'. RAISES LookupError if no candle has closed yet."""
    @property
    def symbols(self) -> list[str]: ...

class PointInTimeFeed:
    """Loads messages + per-(symbol,venue) candle arrays ONCE, sorted ascending. Immutable after load."""
    def __init__(self, messages_path: str, prices_dir: str,
                 as_of_policy: str = "closed_minute"):
        # as_of_policy: "closed_minute" (default, causal: candle observable iff t+60000 <= T_ms,
        #                                 i.e. only FULLY-CLOSED minutes are visible)
        #               "open_minute"  (lenient: t <= T_ms; the bar CONTAINING T is visible —
        #                                NOT causal for intra-bar exit pricing, diagnostics only)
        # The acceptance test and ALL unit tests run under the DEFAULT "closed_minute".
        ...

    def at(self, T, decision_msg_id: int | None = None) -> "Slice":
        """Returns a Slice bound to T (datetime or epoch-ms). The ONLY way to get data.
        decision_msg_id is REQUIRED when T is a message timestamp, to break same-second ties
        deterministically (see Slice.messages). When None, the slice includes ALL messages with
        date <= T regardless of export order (used only for pure price-loop steps with no decision)."""

class Slice:
    """Immutable bounded view at T. The harness passes this — never the raw feed — downstream."""
    @property
    def T_ms(self) -> int: ...
    @property
    def decision_msg_id(self) -> int | None: ...
    def messages(self) -> list[dict]:
        """All messages with date < T, PLUS same-second messages (date == T) whose export-order
        index _idx <= the decision message's _idx. Ascending; each dict is the raw message PLUS an
        injected '_idx' (export order). When decision_msg_id is set, that message is the LAST element
        returned and no same-second message posted after it leaks in. A message strictly after T is
        structurally absent. (Identical rule to ../causal_test/gen_fixtures.py INVARIANTS 1-3.)"""
    def prices(self) -> PriceOracle:
        """The bounded PriceOracle for this T."""
```

**Mandatory behaviors / acceptance for this module**
- Construction does not look at T. `at(T, decision_msg_id)` is O(log n) slicing over pre-sorted arrays.
- `messages()` reproduces `../causal_test/gen_fixtures.py` INVARIANT 1 (no msg with date > T),
  INVARIANT 2 (no same-second msg with `_idx >` the decision's leaks in), INVARIANT 3 (the
  decision message is exactly the last element). The Slice carries `decision_msg_id` for this.
- Every read path enforces I1 under `closed_minute`. There is no flag, no override, no
  `allow_future=` kwarg. The only relaxation is the explicit `as_of_policy="open_minute"` feed
  setting, which is forbidden in the acceptance test and unit tests.
- No module-level mutable state; two concurrent `Slice`s at different T do not interfere.

---

## 3. `ledger.py` — PositionLedger (harness-owned book)

The independent ground truth of "what is open." This is what *knows*, without asking the model,
that "a BTC short opened at msg 1609 (21:56) is still live at 22:11" — and that msg 1611
("Closing around be") flattens it. Mutated ONLY by the harness via `apply_intent`.

```python
@dataclass
class Fill:
    t_ms: int                 # candle open-time of the CLOSED candle that confirmed the fill (causal)
    price: float              # the fill price (limit price, or entry-zone edge for a market-style fill)
    frac_of_planned: float    # this fill's share of the original PLANNED signal size (legs sum <= 1.0)
    src_msg_id: int           # the message that declared the leg/entry
    confirmed: bool           # True iff price-confirmed by a closed candle; declared-only => False

@dataclass
class PositionState:
    symbol: str
    side: str                 # "long" | "short"
    status: str               # "watcher" | "open" | "closed"
    opener_msg_id: int
    entry_lo: float; entry_hi: float
    planned_legs: list[dict]  # [{price, frac_of_planned, status: "filled"|"watcher_unfilled"}]
    avg: float | None         # size-weighted avg of CONFIRMED fills; None while pure watcher
    # SIZE BOOKKEEPING — two distinct denominators (P1.4):
    #   filled_pct_of_planned : sum of confirmed legs' frac_of_planned (0..1). The fraction of the
    #                           signal's planned size the copier actually got on. Set once at fill.
    #   size_pct              : current OPEN size as a fraction of the COPIER-HELD original
    #                           (== filled_pct_of_planned at the moment of last fill). 1.0 means
    #                           "100% of what we hold is still open". ALL close fractions below
    #                           operate on this held-original denominator, matching the
    #                           02_compounding fixture's "treat the filled position as 100% held".
    filled_pct_of_planned: float
    size_pct: float           # current OPEN size as fraction of copier-held original (0.0 .. 1.0)
    remaining: float          # alias of size_pct, the harness/sim convention name
    original_sl: float
    current_sl: float | None  # moves on sl_to; "breakeven" resolves to avg/entry
    tps: list[float]
    fills: list[Fill]
    realized_R: float         # cumulative realized PnL in R units of original risk (risk = |avg - original_sl|)
    closed_at_msg_id: int | None
    last_event_t_ms: int

class PositionLedger:
    """All positions keyed by symbol. One live position per symbol at a time (matches Dennis's book);
    a re-open after a close starts a fresh PositionState (history retained in a closed-list)."""

    def apply_intent(self, intent: "Intent", oracle: "PriceOracle") -> "LedgerDelta":
        """The ONLY mutator. Pure function of (current state, intent, bounded oracle).
        Uses the oracle to PRICE-CONFIRM fills/stops on candles <= T; never reads the future.
        Returns a LedgerDelta describing exactly what changed (for persistence + grading)."""

    def snapshot(self) -> dict:
        """Read-only, JSON-serializable view of all positions. This is what the prompt assembler
        hands to the interpreter as 'current ledger snapshot'. Deterministic key order."""

    def open_positions(self) -> list[PositionState]: ...
    def get(self, symbol: str) -> PositionState | None: ...
```

**Deterministic state machine (the rules `apply_intent` must implement)**

- **open / open_partial (an opener signal):** create a PositionState `status="watcher"`.
  Each entry leg becomes a `planned_leg` with `frac_of_planned`. Fills are confirmed ONLY by
  CLOSED candles (`closed_minute`): a leg flips to `filled` (and a `Fill` with `confirmed=True`
  is appended, `t_ms` = the confirming closed candle's open-time) when a causal candle's `[l,h]`
  range crosses its limit — OR, for a market-style fill, when the FIRST closed candle at/after
  the opener message shows price already inside the entry zone for the trade's side. The opener
  message does NOT itself fill the position at decision time (the opener's own minute has not
  closed); the price-loop confirms the fill on the next closed candle and the ledger snapshot
  then shows it. When ≥1 leg is filled, `status` flips `watcher → open`, `avg` = confirmed-fill
  VWAP, `filled_pct_of_planned` = sum of filled legs' `frac_of_planned`, and `size_pct` is
  (re)set to 1.0 of the copier-held original. Unfilled legs stay `watcher_unfilled`, size 0.
- **watcher → open requires price-confirm OR a Dennis-authored fill declaration.** Two and only
  two paths flip a watcher live: (a) a closed causal candle confirms the limit was touched
  (`confirmed=True`); (b) Dennis himself posts an explicit fill/loaded declaration ("Fully
  loaded", "filled", "in at X") — a message authored by Dennis, NOT the interpreter's inference.
  The harness then appends a `Fill` and IMMEDIATELY re-checks it against the oracle: if a closed
  causal candle supports the declared price it stays `confirmed=True`; if not, the fill is kept
  but marked `confirmed=False` and the position is flagged `declared_unconfirmed` in the snapshot
  (it carries size for copy-fidelity but is auditable as unproven). The interpreter's own
  `epistemic_tag` never flips a watcher — only Dennis's words or a candle do (closes the
  phantom-fill path). A watcher that is never confirmed and never Dennis-declared stays size-0.
- **close_partial — %-of-original vs %-of-remaining (must match `../harness.py:280` exactly),
  denominator = `size_pct` (copier-held original):**
  - `frac` (a bare "Close 30%") ⇒ fraction **of held-original**: `size_pct -= min(frac, size_pct)`.
  - `frac_of_remaining` ("Close 30% of remaining") ⇒ fraction **of current remaining**:
    `closed = frac_of_remaining * size_pct; size_pct -= closed`.
  - The first reduction posted as a bare "Close 30%" is 30% of held-original (equivalently of
    remaining, since `size_pct == 1.0` at that point) — consistent with the `02_compounding` fixture.
- **close_full / close:** `size_pct → 0`, `status → "closed"`, record `closed_at_msg_id`,
  realize PnL of the just-closed remainder at the **close reference price** = `oracle.last_price`
  (the close of the last FULLY-CLOSED candle at T, i.e. `t_causal_ms`'s close) UNLESS Dennis
  posted an explicit close price, in which case use that. Never the in-progress (T-containing)
  candle. R is computed against `risk = |avg - original_sl|`.
- **sl_to:** move `current_sl`. `"breakeven"` resolves to `avg` (or entry mid if `avg is None`).
  A numeric value sets it directly. SL moves do NOT change `size_pct`.
- **commentary / abstain-hold:** no state change. `apply_intent` returns an empty `LedgerDelta`.
- **SL-first sequencing within a candle** (conservative, matches harness): when both the stop
  and a favorable level fall inside one closed candle, the stop is assumed hit first.

**Compounding worked example (frozen — a unit test asserts these exact numbers):**
ETH short, only leg-1 filled, so `filled_pct_of_planned = 0.25` but that filled position is
treated as 100% held ⇒ `size_pct` starts at 1.0. `size_pct` trajectory under the close ladder:
`1.00 → close 30% (of held) → 0.70 → close 20% of remaining → 0.56 → close 30% of remaining → 0.392`.
(`0.392 = 0.56 * (1 - 0.30)`; `0.56 = 0.70 * (1 - 0.20)`; `0.70 = 1.00 * (1 - 0.30)`.)
Matches `../causal_test/out/02_compounding_eth_remaining.json` (`fraction_remaining_of_original
0.392`). NOTE: "of original" in the fixture means "of copier-held original" (`size_pct`), not
"of planned signal size" (`filled_pct_of_planned`) — the two denominators are kept distinct in
`PositionState` precisely so this is unambiguous.

---

## 4. `interpreter.py` — pluggable intent producer

Maps a **bounded prompt** to a **structured intent**. Two implementations behind one interface.
The interpreter is the ONLY component that may be non-deterministic (Claude); everything around
it is deterministic, and a deterministic Mock exists so the causality machinery is testable
without the model.

```python
@dataclass
class Intent:
    intent_type: str       # "open" | "open_partial" | "close_partial" | "close_full"
                           # | "sl_to" | "commentary" | "abstain"
    symbol: str | None
    side: str | None       # "long" | "short" | None
    action_now: str        # "open" | "close_partial" | "close_full" | "sl_move"
                           # | "abstain-hold" | "abstain-flat"
    inferred_state: str    # model's prose description of the book it believes is live at T
    epistemic_tag: str     # "price-confirmed" | "declared-by-dennis"
                           # | "inferred-unconfirmed" | "commentary-no-position-change"
    confidence: float      # 0..1
    reasoning: str
    evidence: "Evidence"   # MUST cite the bounded inputs it used (see below) — checked in audit.py
    # optional structured fields mirrored from the fixtures when present:
    fraction_closed_now_of_original: float | None = None
    fraction_remaining_of_original: float | None = None

@dataclass
class CandleRef:
    symbol: str            # which instrument the candle belongs to
    venue: str             # "weex" | "binance" | "hyperliquid" — so the auditor can resolve it
    t_ms: int              # candle open-time (epoch-ms)

@dataclass
class Evidence:
    msg_ids: list[int]         # every message the decision relied on
    candles: list["CandleRef"] # every candle the decision relied on, each tagged with symbol+venue
                               # so audit.py can (a) check causality and (b) verify the candle exists
                               # AND actually supports any claimed fill/stop. A bare timestamp with
                               # no symbol/venue is NOT auditable, so it is structurally disallowed.
    # NOTE: there is intentionally NO 'used_only_causal_prefix' self-cert field.
    # Causality is established by auditing these refs, not by a model-set boolean (closes WF#2).

class Interpreter(Protocol):
    def interpret(self, prompt: "BoundedPrompt") -> Intent: ...

@dataclass
class BoundedPrompt:
    """Assembled BY THE HARNESS from ONLY bounded data. The interpreter receives nothing else —
    no file paths, no oracle, no clock. This is the structural guarantee behind I2."""
    T_iso: str
    messages: list[dict]          # slice.messages()  (date <= T, ascending)
    ledger_snapshot: dict         # ledger.snapshot() (harness-owned state)
    price_snapshot: dict          # {symbol: {"last_t_ms", "last_close", recent_window}} from PriceOracle
    decision_msg_id: int          # the message we are reacting to (the last Dennis message)

class ClaudeCliInterpreter:
    """Shells out: `claude -p --output-format json` with BoundedPrompt rendered to text +
    a system instruction defining the Intent JSON schema and the evidence requirement.
    Parses the JSON envelope, extracts the assistant message, validates it against the Intent
    schema. On schema failure: ONE structured re-ask, then raise InterpreterError (no silent
    default). The CLI is invoked with tools/file/network access DISABLED (e.g.
    `--allowedTools ''` / no MCP), so the only world it can see is the prompt text. Records raw
    stdout for the run log."""
    def __init__(self, claude_bin: str = "claude", model: str | None = None, timeout_s: int = 120): ...

class MockInterpreter:
    """Deterministic. Maps decision_msg_id -> a hardcoded Intent for the curated scenarios
    (BTC-1609 -> close_full short ~0R with evidence={msg_ids:[1609,1611],
    candles:[CandleRef(BTC,weex, <=22:19)]}). Used by every causality unit test so the
    harness/oracle/audit/ledger are exercised with ZERO model variance. Includes an adversarial
    'cheater' variant that cites a FUTURE candle (e.g. BTC.weex 05-28 @73000), to prove the
    auditor rejects it."""
    def __init__(self, table: dict[int, Intent]): ...
```

**What the bounded prompt does and does NOT guarantee (the honest scope, per I3):**
- **Guaranteed by construction (I2):** no future *data* is in the model's context. The prompt is
  a finite string + JSON snapshots, all `<= T`; there is no API, tool, or file handle by which
  the interpreter can request the 05-28 candle. A future-data *read* is impossible.
- **NOT guaranteed:** that the model ignored future *knowledge* it already holds from pre-training
  (the LLM may simply "know" BTC bottomed near 73000 in late May). The audit catches this only if
  the model *cites* such a fact; a model that uses it silently while citing only causal evidence
  is undetectable by inspection of one run.
- **Residual-threat mitigations (relied on, stated plainly so reviewers don't over-trust):**
  (1) the deterministic **MockInterpreter twin** (§9 test 6) proves the substrate books 1609 at
  ~0R with zero model variance — the core causality proof does not depend on the LLM at all;
  (2) grading rewards a model whose *reasoning + evidence* are causally grounded and penalizes
  answers that can only be reached via uncited future facts; (3) the breakeven target (~0R) is
  itself the tell — a model leaking the future books a multi-R win, which fails the acceptance bar.

**Prompt-assembly contract (harness side, see §6):** the prompt is built by serializing the
`BoundedPrompt`. The interpreter physically receives a finite string + a JSON ledger/price
snapshot, all already causal (`<= T` / last-closed-candle). There is no API by which the
interpreter can request more data. This makes a future-data *read* impossible by construction,
not merely forbidden by instruction — while (per I3 scope limit) NOT eliminating uncited
pre-training knowledge, which the Mock twin and the ~0R acceptance bar guard against instead.

---

## 5. `audit.py` — evidence causality enforcement

Where causality stops being a promise and becomes a checked fact. Runs AFTER `interpret`,
BEFORE `apply_intent`. The intent does not reach the ledger until it passes.

```python
@dataclass
class EvidenceAudit:
    ok: bool
    T_ms: int
    checked_msg_ids: list[int]
    checked_candles: list[dict]   # [{symbol, venue, t_ms}] actually checked
    violations: list[dict]   # [{kind:"future_msg"|"future_candle"|"unknown_msg"|"missing_candle"
                             #         |"unsupported_claim",
                             #   ref: <id-or-{symbol,venue,t_ms}>, detail: str}]
    verdict: str             # "accept" | "reject"

def audit_evidence(intent: Intent, slice_: "Slice") -> EvidenceAudit:
    """For EVERY intent.evidence.msg_id: must exist in slice.messages() (id known AND date <= T);
         else violation 'unknown_msg' (id absent) or 'future_msg' (date > T).
       For EVERY intent.evidence.candles[i] = CandleRef(symbol, venue, t_ms):
         (a) CAUSALITY — must satisfy t_ms + 60000 <= slice.T_ms; else 'future_candle' (HARD reject).
         (b) EXISTENCE — the (symbol,venue) candle with open-time t_ms must exist in the feed;
             else 'missing_candle' (HARD reject — a cited-but-absent candle is fabrication).
       ANY future_* / unknown_msg / missing_candle => verdict='reject', ok=False, refs listed.
       Causality is NEVER inferred from intent.epistemic_tag or any self-cert flag — only from
       direct comparison of cited refs against T (resolved through slice_, the same bounded view)."""

class FutureReferenceRejected(Exception):
    """Raised by replay when a rejected audit must hard-stop the run (strict mode)."""
```

- **Reject policy is configurable but defaults to fail-closed:** in `strict` mode a rejected
  audit aborts the step (raise `FutureReferenceRejected`) — the model tried to use the future,
  so the run is void. In `flag` mode the step is recorded with `verdict="reject"`,
  the intent is **downgraded to `abstain-hold`** before reaching the ledger (never applied as
  cited), and the run continues for diagnostics. The acceptance test runs in `strict`.
- The auditor also re-derives, independently of the model, whether each cited candle actually
  supports the claimed fill/stop (cross-check against the oracle). A model that cites a real
  causal candle that does NOT cross the level it claims is flagged `unsupported_claim`
  (warning, not a causality violation) — kept separate from the hard future/unknown rejects.

---

## 6. `replay.py` — the streaming driver

Walks messages and candles in strict timestamp order; at each Dennis decision point runs the
full bounded loop and persists an auditable record.

```python
def replay(name: str, feed: "PointInTimeFeed", interpreter: "Interpreter",
           ledger: "PositionLedger" = None, *, mode: str = "strict",
           start_msg_id: int | None = None, end_msg_id: int | None = None,
           seed_ledger: list["PositionState"] | None = None,
           decision_filter=None) -> "ReplayResult":
    """Stream. Persist to runs/<name>/. Returns aggregate ReplayResult.
    seed_ledger pre-loads positions opened BEFORE start_msg_id (e.g. the BTC long from msg 1561),
    so an early-window close (1608 'Close long fully') is a real transition, not a vacuous no-op.
    Seeded positions are recorded in meta.json so the seed is explicit and reproducible."""
```

**Clock convention (fixes the open- vs close-time ambiguity, P1.2):** the streaming clock is
**event time in epoch-ms**. A candle with open-time `t` generates a "minute-closed" event at
wall time `t + 60000` (when it becomes observable under `closed_minute`). Messages fire at their
`date` ms. The merged timeline is ordered by these event times. So a candle is processed by the
price-loop only AFTER its minute has closed — never at its open.

**Per-step algorithm (the loop):**
1. **Stream in event-time order.** Merge candle minute-closed events (at `t + 60000`) and message
   events (at `date`) into one monotonic timeline. Two sub-loops share the clock:
   - **Price-loop:** when a candle's minute-closed event fires (event time `t+60000`), advance the
     ledger's fill/stop checks for that newly-closed candle via `oracle.touched(...)` /
     `oracle.window(.., a_ms, t, ..)` evaluated at a `Slice` bound to `T = t+60000` (so `t` is the
     last closed candle and is in-range; `t+60000` itself is NOT). This is how watcher legs flip
     to `filled` and hard SLs trigger between messages — on closed candles only, never ahead.
   - **Message-loop:** at each message event, if it is a Dennis actionable message (opener/manage/
     close/commentary by Dennis; `decision_filter` selects which), set `T = message.date` and run
     steps 2-7. Non-Dennis / non-actionable messages advance the clock but produce no decision step.
2. **Bind the slice:** `slice_ = feed.at(T, decision_msg_id=message.id)`; `oracle = slice_.prices()`.
   (Before this, the price-loop has already settled all fills/stops on candles whose minute closed
   at or before T, so the ledger snapshot is causally current.)
3. **Assemble bounded prompt:** `BoundedPrompt(T_iso, slice_.messages(), ledger.snapshot(),
   price_snapshot_from(oracle), decision_msg_id=message.id)`. (Only bounded data — I2. The
   price_snapshot uses `oracle.last_price`/`last_candle`, i.e. the last CLOSED candle.)
4. **Interpret:** `intent = interpreter.interpret(prompt)`.
5. **AUDIT:** `ea = audit_evidence(intent, slice_)`. In `strict`, reject ⇒ raise
   `FutureReferenceRejected` and void the run. In `flag`, reject ⇒ downgrade intent to
   abstain-hold, attach `ea` to the record, continue.
6. **Apply:** `delta = ledger.apply_intent(intent, oracle)` (only if audit accepted / after downgrade).
7. **Persist** one record per step (see schema). Flush immediately (crash-safe, replayable).

**Persistence — `runs/<name>/`:**
- `meta.json` — run name, feed paths, interpreter class + model, mode, as_of_policy, git sha,
  start/end bounds, wall-clock, schema version.
- `steps.jsonl` — one object per decision step:
  ```jsonc
  {
    "step": 7, "T_ms": 1779744053000, "T_iso": "2026-05-21T22:20:53+00:00",
    "decision_msg_id": 1611,
    "intent": { ...full Intent... },
    "evidence_audit": { ...EvidenceAudit... },
    "ledger_delta": { ...LedgerDelta... },
    "ledger_snapshot": { ...PositionLedger.snapshot() AFTER apply... },
    "prompt_digest": "sha256(BoundedPrompt serialization)",   // fast equality check
    "prompt_ref": "prompts/step_0007.txt",                    // FULL serialized bounded prompt
    "raw_interpreter_stdout_ref": "raw/step_0007.json"        // ClaudeCli only
  }
  ```
- `prompts/step_NNNN.txt` — the FULL serialized BoundedPrompt fed to the interpreter (so a
  serialization bug is reconstructable, not just digest-mismatched — P2.3). Always written.
- `raw/step_NNNN.json` — raw interpreter stdout (Claude runs only), for forensics.
- `final_ledger.json` — terminal `snapshot()` + realized PnL per position, in R and (optionally) $.

`ReplayResult` aggregates: steps run, audits accepted/rejected/flagged, final per-symbol R,
and a pointer to `runs/<name>/`.

---

## 7. `grade.py` — score the run against truth + a baseline

Compares the persisted run to (a) hand-curated truth and (b) a naive-regex baseline, so we can
state both "did the causal agent get it right" and "did causality + LLM beat dumb parsing."

```python
def grade(run_dir: str,
          truth_events_path: str = "../trades_may.json",
          truth_results_path: str = "../RESULTS_MAY.md",
          baseline: str = "regex") -> "GradeReport":
    ...
```

- **Truth source:** `../trades_may.json` is the curated event ledger (per-trade opener +
  ordered close/sl events with `src_id`, plus `claim_usd/claim_pct`). `../RESULTS_MAY.md`
  supplies the prose verdicts (e.g. BTC-1609 "books ~0R", AAVE/APT "win required holding
  through posted SL = uncopyable"). The grader reduces `trades_may.json` to a per-symbol,
  per-decision **expected intent/state timeline** (the close_full at 1611 → flat ~0R, the
  03/02 compounding fractions, etc.) and diffs the run's `steps.jsonl` against it.
- **Per-step grading dimensions** (each pass/fail with detail):
  - `intent_type` / `action_now` match (close_full vs close_partial vs sl_move vs abstain).
  - `symbol` + `side` attribution (the 01 case: 77,240 binds to BTC swing, NOT NEAR).
  - `size_pct` / fraction math within tolerance (02 compounding 0.392).
  - terminal realized R per position within tolerance of truth (1609 ≈ 0R, not +5–7R).
  - **evidence audit clean** (no future refs) — a step that needed a `flag`/`reject` to get the
    right answer is NOT a pass.
- **Naive-regex baseline (`baseline.py`, built alongside):** a deterministic parser that pulls
  `direction/entry/sl/tp/close X%` by regex with NO state inference and NO causal price-confirm
  — i.e. it cannot distinguish "Closing around be" (close) from "SL to be" (stop move), cannot
  do %-of-remaining compounding, and rides the empty-events trap on 1609. The grader reports the
  causal-LLM vs regex delta per dimension. (This mirrors WF#1's "LLM beats regex" framing but now
  on a causally honest substrate.)
- **`GradeReport`** (returned + written to `run_dir/grade.json`): per-step table, aggregate
  accuracy by dimension, causal-cleanliness count, and the LLM-vs-baseline delta. Plain-language
  summary suitable for pasting into a codex-reviewed verdict.

---

## 8. ACCEPTANCE TEST (the run that proves the substrate works)

**Name:** `runs/btc1609/`. **Interpreter:** `ClaudeCliInterpreter` (the real test of the LLM)
AND, separately, `MockInterpreter` (to prove the machinery). **Mode:** `strict`.
**as_of_policy:** `closed_minute` (default). **Source:** `../paid_export/paid_messages.json`,
`../prices_may/BTC.weex.jsonl` (cross-check `BTC.binance.jsonl`).

**Seeding (so 1608's close is not vacuous — fixes P0.5):** the prior BTC LONG (opener msg 1561,
05-18) opened well before this window and `trades_may.json` shows no explicit full-close before
1609; in reality msg **1608 "Close long fully"** is that close. Starting the stream at 1602 would
give the ledger no BTC long to close, making "ledger flat before the short" vacuously true. So
the acceptance run is configured with `seed_ledger` containing the open BTC long (from src_id
1561: long, entry zone 76200-76950, avg ~76575, SL→75250 per event 1562, status `open`,
`size_pct 1.0`). The grader then VERIFIES that 1608 transitions that seeded long to `closed`
(a real attribution check), and that BTC is flat at the instant 1609 opens the short.
(Alternatively the window may begin at the 1561 opener; seeding is the smaller, deterministic
choice and is what the test uses. Either way the "flat before short" check must be non-vacuous.)

**Window — stream from a few messages BEFORE the opener through the breakeven close:**
- Start: msg **1602** (`"I'll drop all the BTC trades we caught… in the next few days"`,
  14:56 — pre-opener BTC chatter; a distractor that must NOT be read as an action — it talks
  about *past* BTC trades and a *future* recap, neither of which is an order).
- Through: **1605** ETH full close, **1606** FARTCOIN full close, **1608** `"Close long fully"`
  (closes the SEEDED BTC long ⇒ ledger BTC flat), **1609**
  `"BTC Short / Entry: 77300-77900 / SL: 78400 / Target: 73000"` (21:56:44 — opener),
  **1610** `"No"`, **1611** `"Closing around be"` (22:20:53 — the decision), with the price-loop
  consuming BTC 1m candles whose minutes CLOSE in `[21:56:00 .. 22:20:00]` event-time
  (i.e. open-times 21:55 .. 22:19 inclusive — the 22:20 open-time candle does NOT close until
  22:21:00 and is therefore never observed during this run).

**Ground-truth facts the run must reproduce (`closed_minute`; from `trades_may.json` src_id 1609
+ the BTC.weex candles verified this session):**
- The 1609 short opener posts at 21:56:44. At that instant the last CLOSED candle is open-time
  21:55 (close 77684.1). The fill is confirmed by the price-loop when the 21:56 candle CLOSES at
  21:57:00: its range is `l 77647.2 / h 77684.1`, inside the entry zone 77300-77900 ⇒ **market-
  style fill** at ~entry-zone edge, `status open`, `filled_pct_of_planned 1.0`, `size_pct 1.0`,
  `avg ≈ 77650`. (The fill shows in the ledger snapshot at the NEXT decision, not at 21:56:44.)
- Across closed candles open-time 21:55 .. 22:19, BTC traded the band **77556 (low, 22:16 candle)
  … 77721 (high, 22:03 candle)**. SL 78400 is **never** touched. Target 73000 is **never** touched
  (BTC only reached 73000 on 05-28, 7 days later — the future the model must NOT see).
- Msg 1611 `"Closing around be"` at 22:20:53 ⇒ **close_full** at the close reference price = the
  last CLOSED candle's close = **22:19 candle close 77592.2** (NOT the still-open 22:20 candle).
  Realized vs `avg ≈ 77650` on a short ⇒ +~7 bps, well within **±0.15R** of 0 ⇒ **≈ 0R / breakeven**.
- Msg 1612 `"If we will fell below 77200 we will open by market"` is **after T** for the 1611
  decision (and the condition never fired: min was 77556 > 77200). It is **structurally absent**
  at the decision and must not create a new short.

**PASS criteria (all required):**
1. **Seeded long closed (non-vacuous attribution):** after msg 1608, the seeded BTC LONG
   (opener 1561) is `status="closed"`, and BTC is flat at the instant 1609 posts. (If the run
   started with an empty ledger and had nothing to close at 1608, this criterion FAILS — guards
   against the vacuous pass P0.5 flagged.)
2. **Final ledger:** the 1609 BTC SHORT is `status="closed"`, `closed_at_msg_id=1611`,
   `realized_R` within `±0.15R` of 0 (breakeven). NOT a multi-R win.
3. **Evidence is causal-clean:** the 1611 step's `evidence.msg_ids ⊆ {…≤1611}` (e.g. {1609,1611},
   optionally 1608/1610 context) and every `evidence.candles[i]` (a `CandleRef`) satisfies
   `t_ms + 60000 <= T_ms` — i.e. open-time ≤ **22:19** — AND exists in BTC.weex/BTC.binance.
   `evidence_audit.verdict == "accept"`, `violations == []`.
4. **No future reference anywhere:** no cited candle with open-time ≥ **22:20** (the in-progress
   minute) and none from 05-28; no `msg_id ≥ 1612`. Any such ref hard-stops the strict run.
5. **Attribution:** the close binds to the BTC **short** opened by 1609, not to the prior long
   nor any other symbol.
6. **`grade.py` verdict:** causal-LLM PASSES the 1609 dimension; **regex baseline FAILS** it
   (rides the ladder / mis-reads "around be" as stop-move-to-BE), demonstrating the substrate's value.

A run that books +5–7R on 1609, OR cites any candle with open-time ≥ 22:20 (or any 05-28 candle),
OR needs `flag`-mode downgrade to reach 0R, is a **FAIL** — that is exactly the WF#2 hole, and the
substrate must make it impossible in `strict`.

---

## 9. CAUSALITY UNIT TESTS (the BUILD must pass these; `tests/` under causal_replay/)

Deterministic, no Claude (MockInterpreter only). Each maps to an invariant.

1. **`test_oracle_raises_on_future` (I1).** With T=1611's timestamp,
   `feed.at(T,1611).prices().candle_at("BTC", t_2220)` where the 22:20 candle is in-progress
   (`t+60000 > T_ms`) ⇒ `CausalityViolation`; same for a 05-28 candle. Same for
   `window(b_ms = 22:20-open)` and `touched(since_ms in future)`. AND `candle_at` for the 22:19
   candle (closed at/before T) returns the right candle — no false positive at the boundary.
2. **`test_messages_time_gated_and_tiebroken`.** `feed.at(T_1611, decision_msg_id=1611).messages()`
   ends with msg 1611 and excludes 1612 (and any same-second-after message), reproducing
   `gen_fixtures.py` INVARIANTS 1-3.
3. **`test_future_evidence_intent_rejected` (I3).** A `MockInterpreter` "cheater" intent for the
   1611 decision whose `evidence.candles` includes `CandleRef("BTC","weex", 05-28@73000)` and/or
   `msg_ids` includes 1612 ⇒ `audit_evidence(...).verdict == "reject"`, the future refs enumerated
   in `violations` (`future_candle`/`future_msg`); in `strict` replay this raises
   `FutureReferenceRejected` (the run is void). Also: a `CandleRef` whose `t_ms` does not exist in
   the feed ⇒ `missing_candle` reject.
4. **`test_clean_evidence_intent_accepted` (I3 complement).** The honest 1611 Mock intent
   (evidence msg_ids {1609,1611}, candles all BTC.weex open-time ≤ 22:19) audits `accept`,
   `violations == []`.
5. **`test_ledger_compounding_math` (I5).** Apply close-30% (bare, of held) → 20%-of-remaining →
   30%-of-remaining to a filled position (`size_pct` starts 1.0) ⇒ `size_pct` sequence
   `0.70 → 0.56 → 0.392` (exact, to 1e-9). Asserts the bare-`frac` vs `frac_of_remaining`
   distinction and the held-original (`size_pct`) vs planned (`filled_pct_of_planned`) denominator
   split; matches `out/02_compounding_eth_remaining.json` (`fraction_remaining_of_original 0.392`).
6. **`test_mock_1609_books_breakeven` (acceptance, deterministic).** MockInterpreter replay of the
   §8 window in `strict`, WITH the seeded BTC long ⇒ 1608 closes the seeded long (criterion 1),
   1609 short fills on the closed 21:56 candle, 1611 closes it at the 22:19-close reference,
   `realized_R` within `±0.15R` of 0, evidence causal-clean. The deterministic twin of the
   acceptance test (no model variance) — the core proof that does not depend on the LLM.
7. **`test_watcher_fill_requires_confirmation`.** An opener whose entry zone the closed candles
   never reach stays `status="watcher"`, `size_pct=0`, contributes 0 PnL; a close on it is a no-op.
   A price-confirmed touch on a closed candle flips it to `open`. A Dennis-authored "Fully loaded"
   with NO supporting candle flips to `open` but flagged `declared_unconfirmed`,`confirmed=False`.
   An interpreter `epistemic_tag` alone never flips a watcher. (Guards against phantom fills, P1.3.)
8. **`test_no_global_state` (I2).** Two `Slice`s at different T from the same feed answer
   independently; mutating one ledger does not affect another; `BoundedPrompt` carries no path,
   oracle handle, or clock — only bounded data.

**Definition of done for BUILD:** all 8 unit tests green under the default `closed_minute` policy,
AND the `runs/btc1609/` acceptance run (Mock = test 6; Claude = manual check) satisfies every §8
PASS criterion (1-6), AND `grade.py` shows causal-LLM > regex on the 1609 dimension.

---

## 10. Module / file layout

```
causal_replay/
  SPEC.md            # this file
  oracle.py          # PointInTimeFeed, Slice, PriceOracle, CausalityViolation, to_ms
  ledger.py          # PositionLedger, PositionState, Fill, LedgerDelta
  interpreter.py     # Intent, Evidence, Interpreter, ClaudeCliInterpreter, MockInterpreter, BoundedPrompt
  audit.py           # audit_evidence, EvidenceAudit, FutureReferenceRejected
  replay.py          # replay(), ReplayResult, the streaming driver + persistence
  grade.py           # grade(), GradeReport
  baseline.py        # naive-regex baseline interpreter (for grade.py)
  tests/             # the 8 causality unit tests (§9)
  runs/<name>/       # meta.json, steps.jsonl, raw/, final_ledger.json, grade.json
```

**Dependency direction (acyclic), spelled as imports (P2.2):**
- `oracle.py` imports nothing in-package.
- `ledger.py` imports `oracle` (uses `PriceOracle` for fill/stop confirmation).
- `interpreter.py` imports nothing in-package (defines `Intent`/`Evidence`/`CandleRef`/`BoundedPrompt`;
  it receives a serialized prompt, NOT a `Slice`, `PriceOracle`, or `PositionLedger`).
- `audit.py` imports `oracle` (resolves `CandleRef`s against the `Slice`) and `interpreter` (the
  `Intent`/`Evidence` types). It does NOT import `ledger`.
- `replay.py` imports `oracle`, `ledger`, `interpreter`, `audit` — it is the only orchestrator.
- `baseline.py` imports `interpreter` (implements the `Interpreter` protocol).
- `grade.py` imports nothing in-package at runtime; it reads `runs/<name>/` JSON files. No module
  imports `replay` except via its output files.

Stdlib only (json, datetime, dataclasses, subprocess, hashlib, bisect); no pandas, no network at
replay time.
```
