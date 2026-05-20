# Insiders Scalp — LLM Parser Validation (for Eduardo)

**TL;DR for Eduardo:** the regex parser fails on 23 of 50 hand-checked messages,
and 35% of its mistakes would have **force-closed real positions** because
someone (often you) used the word *"stop"* in commentary. An LLM (Claude Haiku
4.5) with the prompt below understands the difference between *"I'm setting a
stop"* and *"I'm hitting a stop"* the way a human reader does. Cost to validate
all 50 messages is ~$0.04. Run `validate_llm.py` (in this folder) to see the
pass/fail printout.

The killer example: message **#1252**:

> *"SOL — after adding, my average is 85.8. Moving the stop-loss to breakeven as well."*

This is you locking in a winner. **The regex marks it `close_full` — your bot
would exit the winning trade in profit and never re-enter.** The LLM with the
prompt below routes it to `move_sl(sl="breakeven")` and the bot keeps the
position with the stop tightened.

---

## 1. LLM Prompt + Structured-Output Schema

**Model:** `claude-haiku-4-5` (SDK resolves to `claude-haiku-4-5-20251001`).

Short messages (median ~80 chars), bounded classification + small-number
extraction, sub-second latency. Re-running all 428 messages costs pennies.

### System prompt (frozen, cached — every byte stable across all 50 calls)

```text
You are a signal parser for a crypto Telegram trading channel ("Insiders Scalp").

Each user turn contains ONE Telegram message plus optional parent/sibling
context. Your job is to decide what trade event, if any, the message
represents — and emit one JSON object that conforms to the response schema.

Channel format facts (memorize these):

1. A message is a TRADE SIGNAL only if it explicitly opens, closes, resizes,
   or moves the stop on a position. Market commentary, analysis, P&L brags,
   and reasoning are NOT signals — set is_signal=false and kind="chat".

2. Signal kinds:
   - "open": a new position. Triggered by "<COIN> Long" or "<COIN> Short" as
     a header, possibly with Entry/SL/TP details in the same message or in a
     reply.
   - "close_full": full exit. Phrases: "Full close", "Fully closed",
     "Close all", "Got stopped", "Stopped out", "Closing in small profit"
     (when applied to a specific position).
   - "close_partial": partial exit. "Close 30%", "Close 50% of remaining
     position", "Closing 25%", "Close half" (=50%).
   - "move_sl": stop-loss moved. "SL to 77900", "SL to breakeven",
     "Move SL to ...", "Moving the stop-loss to ...", "Stop at breakeven".
     A stop being SET on a fresh open is NOT a move_sl — it's part of the
     open.
   - "increase": adding to existing position. "Adding +30% to BTC short",
     "Add +50%", "Place a limit order at X and add +N%".
   - "chat": anything else, including: brags, calls, analysis,
     encouragement, generic risk warnings, hedging commentary, position
     status updates without an action.

3. The word "stop" is a TRAP. Most messages containing "stop", "stopped", or
   "stop-loss" are commentary, not actions. Only emit a close/move signal
   when the author is clearly DOING something to a position right now, not
   discussing where a stop should be or what might happen.

4. Multi-coin signals: "BTC and ETH" or "BTC & ETH" applies the action to
   both coins. Set applies_to=["BTC","ETH"]. If single coin, applies_to=null.

5. Entry formats: single number, range ("75800-76600"), staged ("20% - 2360
   / 20% - 2400 / ..."), or "by market". For ranges, set entry=null and
   entry_range=[lo,hi]. For staged, set entry=null and put the per-tranche
   breakdown into notes. For market, set entry="market".

6. "Breakeven" is a string, not a number — set sl="breakeven" and let the
   harness resolve it to the entry price.

7. Coins outside Binance (PUMP, WLFI, XPL, FARTCOIN, USELESS) are still
   valid signals — set the symbol field and let the simulator decide whether
   to skip.

8. If unsure between two kinds, prefer "chat" with confidence<=0.6 and
   explain in notes. False signals lose money; missed chats lose nothing.

CONTEXT RESOLUTION:
- If the message is a reply, you receive the parent message text and the
  last 2 sibling replies. Use them ONLY to resolve ambiguous references
  ("SL to breakeven" → look up the parent's entry; "the position" → which
  coin).
- Do NOT re-emit a signal that was already emitted by the parent. Each
  message produces ONE event.

OUTPUT: emit ONE JSON object that matches the schema. No prose, no markdown,
no chain-of-thought.
```

### Per-message user turn template

```text
PARENT (id={parent_id}): {parent_text or "<none>"}
SIBLINGS:
- (id={s1_id}): {s1_text}
- (id={s2_id}): {s2_text}

THIS MESSAGE (id={msg_id}):
{text}
```

### Structured-output JSON Schema

```python
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["is_signal", "kind", "symbol", "direction", "entry",
                 "entry_range", "sl", "tp", "pct", "applies_to",
                 "confidence", "notes"],
    "properties": {
        "is_signal":   {"type": "boolean"},
        "kind":        {"type": "string",
                        "enum": ["open", "close_full", "close_partial",
                                 "move_sl", "increase", "chat"]},
        "symbol":      {"type": ["string", "null"]},
        "direction":   {"type": ["string", "null"]},
        "entry":       {},  # number | "market" | null
        "entry_range": {},  # [lo, hi] | null
        "sl":          {},  # number | "breakeven" | null
        "tp":          {},  # [numbers] | null
        "pct":         {"type": ["number", "null"]},
        "applies_to":  {},  # [strings] | null
        "confidence":  {"type": "number"},
        "notes":       {"type": "string"},
    }
}
```

---

## 2. Validation Sample

50 messages hand-picked from the last 30 days, covering every category the
regex parser fails on:

| Category | Count |
|---|---|
| Clean single-message open | 5 |
| Two-part header (bare) | 2 |
| Reply with details (resolves a header) | 2 |
| Staged / laddered entries | 3 |
| Range entry | 2 |
| Partial close with % | 3 |
| "Close X% of remaining" | 2 |
| Multi-coin close | 3 |
| "SL to breakeven" canonical | 3 |
| Non-canonical breakeven phrasing | 3 |
| Bare hedge / header without details | 2 |
| **Non-trade chat that mentions "stop" (regex disaster)** | 7 |
| Non-Binance coin | 4 |
| Update / reply that's pure commentary | 7 |
| Trickiest 5 | 5 |

All 50 message IDs and full text are baked into `validate_llm.py` so the
script is self-contained.

---

## 3. Regex Parser Output on the Sample

Computed by calling `parse_opens`, `parse_management`, `parse_details` from
the prototype's `parser.py` on each message.

**Headline:** the regex fires `close_full` on **7 out of 7** non-trade
messages that mention "stop" (false-positive rate **100%** on this category).
It also mis-classifies 4 management updates as `close_full` because the
broad `\bstop(?:ped)?\b` arm of `_FULL_CLOSE_RE` matches the word "stop"
anywhere in the text.

---

## 4. Validation Table — regex vs ground truth

Compact JSON in cells; `null` keys omitted for brevity. ✓ = regex matches
ground truth on the load-bearing fields (kind, symbol, key numbers); ✗ =
wrong kind, wrong symbol, or hallucinated/missed signal.

| msg_id | text (truncated) | regex_output | ground_truth | ✓/✗ | failure_mode |
|---|---|---|---|---|---|
| 1073 | XTIU Long / Entry 79-85 / SL 73.5 / 1 Target 98 / 2... | `{opens:[{sym:XTIU,dir:long,entry:82,sl:73.5,tp:98}]}` | `{kind:open,sym:XTIU,dir:long,entry_range:[79,85],sl:73.5,tp:[98,118]}` | ~ | regex loses TP2; midpoint OK |
| 1088 | HYPE Short / Entry 43.5-45 / SL 46.181 / Target 36.4 | `{opens:[{sym:HYPE,dir:short,entry:44.25,sl:46.181,tp:36.4}]}` | `{kind:open,sym:HYPE,dir:short,entry_range:[43.5,45],sl:46.181,tp:[36.4]}` | ✓ | — |
| 1089 | PUMP Long / Entry: 0.00182-0.00186 / SL: 0.001795 / T... | `{opens:[{sym:PUMP,dir:long,entry:0.00184,sl:0.001795,tp:0.00203}]}` | `{kind:open,sym:PUMP,dir:long,entry_range:[0.00182,0.00186],sl:0.001795,tp:[0.00203]}` | ✓ | — |
| 1331 | WLFI Long / Very high risk / Entry: 0.053-0.057 / SL... | `{opens:[{sym:WLFI,dir:long,entry:0.055,sl:0.0498,tp:null}]}` | `{kind:open,sym:WLFI,dir:long,entry_range:[0.053,0.057],sl:0.0498,tp:null}` | ✓ | — |
| 1453 | FARTCOIN Long / Entry: 0.245-0.255 / SL: 0.241 / Tar... | `{opens:[{sym:FARTCOIN,dir:long,entry:0.25,sl:0.241,tp:0.29}]}` | `{kind:open,sym:FARTCOIN,dir:long,entry_range:[0.245,0.255],sl:0.241,tp:[0.29]}` | ✓ | — |
| 1056 | BTC Short | `{opens:[{sym:BTC,dir:short,entry:null,sl:null,tp:null}]}` | `{kind:open,sym:BTC,dir:short,notes:"bare header, details in reply 1058"}` | ✓ | regex misses thread-awareness |
| 1058 | BTC Short / Entry 75800-76600 / SL 77300 / Target 71000 | `{opens:[{sym:BTC,dir:short,entry:76200,sl:77300,tp:71000}]}` | `{kind:open,sym:BTC,dir:short,entry_range:[75800,76600],sl:77300,tp:[71000],notes:"details for parent 1056"}` | ✓ | re-emits open instead of detail-fill |
| 1057 | ETH Short | `{opens:[{sym:ETH,dir:short,entry:null,sl:null,tp:null}]}` | `{kind:open,sym:ETH,dir:short,notes:"bare header, details in 1059"}` | ✓ | — |
| 1118 | BTC Short / Limit orders: 10% by market / 20% - 76,6... | `{opens:[{sym:BTC,dir:short,entry:null,sl:79800}]}` | `{kind:open,sym:BTC,dir:short,sl:79800,notes:"staged: 10%mkt,20%@76600,20%@77200,20%@78100,20%@78700"}` | ~ | regex misses staging |
| 1119 | ETH Short / Here I have 30% / Limit orders: 20% - 2,3... | `{opens:[{sym:ETH,dir:short,entry:null,sl:2480}]}` | `{kind:open,sym:ETH,dir:short,sl:2480,notes:"staged"}` | ~ | regex misses staging |
| 1163 | FF Long / Entry: 20% by Market (~0.0723) / 30% 0.0698... | `{opens:[{sym:FF,dir:long,entry:null,sl:0.0669}]}` | `{kind:open,sym:FF,dir:long,entry:"market",sl:0.0669,notes:"staged"}` | ~ | regex misses "by market" |
| 1059 | ETH Short / Entry 2360-2420 / SL 2480 / Target 2100 | `{opens:[{sym:ETH,dir:short,entry:2390,sl:2480,tp:2100}]}` | `{kind:open,sym:ETH,dir:short,entry_range:[2360,2420],sl:2480,tp:[2100]}` | ✓ | — |
| 1415 | XPL Short / Entry: 0.101-0.104 / SL: 0.106 / Target: ... | `{opens:[{sym:XPL,dir:short,entry:0.1025,sl:0.106,tp:0.09}]}` | `{kind:open,sym:XPL,dir:short,entry_range:[0.101,0.104],sl:0.106,tp:[0.09]}` | ✓ | — |
| 1074 | BTC & ETH / Close 30% in both trades | `{mgmt:{kind:close_partial,pct:30}}` | `{kind:close_partial,pct:30,applies_to:["BTC","ETH"]}` | ✗ | regex loses multi-coin scope |
| 1076 | Close 30% more | `{mgmt:{kind:close_partial,pct:30}}` | `{kind:close_partial,pct:30,applies_to:["BTC","ETH"]}` | ✗ | no parent context — can't resolve "more" |
| 1530 | BTC and ETH / Close 30% in both positions | `{mgmt:{kind:close_partial,pct:30}}` | `{kind:close_partial,pct:30,applies_to:["BTC","ETH"]}` | ✗ | loses multi-coin scope |
| 1246 | SOL / Close 50% of the remaining position / SL to br... | `{mgmt:{kind:close_partial,pct:50,sl:"breakeven"}}` | `{kind:close_partial,sym:SOL,pct:50,sl:"breakeven"}` | ✓ | symbol lost |
| 1274 | AAVE / Close 50% of remaining position | `{mgmt:{kind:close_partial,pct:50}}` | `{kind:close_partial,sym:AAVE,pct:50}` | ✓ | symbol lost |
| 1101 | BTC and ETH Shorts / Closing 50% of current positions | `{none:true}` | `{kind:close_partial,pct:50,applies_to:["BTC","ETH"]}` | ✗ | **regex MISSES** — `_PARTIAL_CLOSE_RE` only matches "Close N%" not "Closing N%" |
| 1509 | ETH and BTC Shorts / Close 25% more in both | `{mgmt:{kind:close_partial,pct:25}}` | `{kind:close_partial,pct:25,applies_to:["ETH","BTC"]}` | ✗ | multi-coin scope lost |
| 1550 | BTC and ETH / Full close / Great trades | `{mgmt:{kind:close_full}}` | `{kind:close_full,applies_to:["BTC","ETH"]}` | ✗ | multi-coin scope lost |
| 1091 | HYPE / SL to breakeven | `{mgmt:{kind:move_sl,sl:"breakeven"}}` | `{kind:move_sl,sym:HYPE,sl:"breakeven"}` | ✓ | symbol lost |
| 1227 | FARTCOIN / Close 20% and SL to breakeven | `{mgmt:{kind:close_partial,pct:20,sl:"breakeven"}}` | `{kind:close_partial,sym:FARTCOIN,pct:20,sl:"breakeven"}` | ✓ | — |
| 1344 | WLFI / Close 25% and move SL to breakeven | `{mgmt:{kind:close_partial,pct:25,sl:"breakeven"}}` | `{kind:close_partial,sym:WLFI,pct:25,sl:"breakeven"}` | ✓ | — |
| **1252** | **SOL — after adding, my average is 85.8. / Moving the stop-loss to breakeven** | **`{mgmt:{kind:close_full}}`** | **`{kind:move_sl,sym:SOL,sl:"breakeven"}`** | **✗** | **CATASTROPHIC: regex says full close, real action is move_sl. Would force-exit a winning trade.** |
| 1308 | Those who are still holding BTC Long - you can close ... | `{mgmt:{kind:close_full}}` | `{kind:chat,notes:"advisory — 'you can' is optional"}` | ✗ | regex hallucinates close on advisory message |
| 1358 | Stop at breakeven and stay online - we might close an... | `{mgmt:{kind:close_full}}` | `{kind:move_sl,sl:"breakeven"}` | ✗ | wrong kind — regex closes, real intent is move SL |
| 1222 | FARTCOIN Long | `{opens:[{sym:FARTCOIN,dir:long}]}` | `{kind:open,sym:FARTCOIN,dir:long}` | ✓ | — |
| 1054 | Like I said - high risk. Ideally, the stop should've ... | `{mgmt:{kind:close_full}}` | `{kind:chat}` | ✗ | **REGEX DISASTER** — closes on the word "stop" in commentary |
| 1070 | Most likely we'll get stopped out here and then re-en... | `{mgmt:{kind:close_full}}` | `{kind:chat,notes:"market commentary"}` | ✗ | regex disaster |
| 1144 | I've mapped out a possible scenario on the chart for ... | `{mgmt:{kind:close_full}}` | `{kind:chat}` | ✗ | regex disaster (contains "stop" somewhere) |
| 1147 | BTC / Waiting for a final push toward 80,000. / Movin... | `{mgmt:{kind:close_full}}` | `{kind:move_sl,sym:BTC,sl:80933}` | ✗ | wrong kind: real action is move SL to a number |
| 1322 | Overall, I want to say - don't overdo it with shorts ... | `{mgmt:{kind:close_full}}` | `{kind:chat,notes:"general risk advice"}` | ✗ | regex disaster |
| 1349 | There are still chance that we are going to 80k+, tha... | `{mgmt:{kind:close_full}}` | `{kind:chat}` | ✗ | regex disaster |
| 1379 | Watch your risk - there's a high chance we push highe... | `{mgmt:{kind:close_full}}` | `{kind:chat}` | ✗ | regex disaster |
| 1048 | +$3,300 / Not bad for such trade | `{none:true}` | `{kind:chat,notes:"P&L brag"}` | ✓ | — |
| 1050 | Good morning! Closed the shorts perfectly yesterday. | `{none:true}` | `{kind:chat,notes:"retrospective"}` | ✓ | — |
| 1055 | They might pump the price from here, but I'm not re-e... | `{none:true}` | `{kind:chat}` | ✓ | — |
| 1090 | HYPE position much smaller | `{none:true}` | `{kind:chat,sym:HYPE,notes:"sizing comment"}` | ✓ | borderline |
| 1127 | Another BTC short order filled / 40% of position now | `{none:true}` | `{kind:chat,sym:BTC,notes:"fill confirmation"}` | ✓ | — |
| 1209 | Closing hedge long in small profit / Bounce is too weak | `{none:true}` | `{kind:close_full,notes:"closes the hedge leg"}` | ✗ | regex blind; LLM should catch via 'Closing ... in small profit' |
| 1305 | Closing in small profit | `{none:true}` | `{kind:close_full,notes:"symbol from parent"}` | ✗ | regex misses canonical channel idiom |
| 1136 | Close half / And SL to breakeven | `{mgmt:{kind:move_sl,sl:"breakeven"}}` | `{kind:close_partial,pct:50,sl:"breakeven"}` | ✗ | regex sees only SL move, misses partial close ("half" no "%") |
| 1189 | quick adjustment on ETH. / SL to breakeven / Like I s... | `{mgmt:{kind:close_full}}` | `{kind:move_sl,sym:ETH,sl:"breakeven"}` | ✗ | regex picks wrong arm |
| 1103 | On BTC Long / Set the stop at 73,000. / Place a limit... | `{mgmt:{kind:close_full}}` | `{kind:increase,sym:BTC,pct:50,notes:"adds via limit + sets stop; not a close"}` | ✗ | catastrophic miss — closes when Eduardo is *adding* |
| 1258 | Go stopped at breakeven | `{mgmt:{kind:close_full}}` | `{kind:close_full,notes:"typo 'Go' = 'Got'"}` | ✓ | both correct (regex got lucky) |
| 1473 | FARTCOIN / Got stopped at breakeven with some profit | `{mgmt:{kind:close_full}}` | `{kind:close_full,sym:FARTCOIN}` | ✓ | — |
| 1537 | FIDA / Full close in small profit | `{mgmt:{kind:close_full}}` | `{kind:close_full,sym:FIDA}` | ✓ | symbol lost by regex |
| 1133 | Closing in small profit | `{none:true}` | `{kind:close_full,notes:"bare close"}` | ✗ | regex misses canonical idiom |
| 1394 | Positions update: / SOL - still in accumulation zone... | `{none:true}` | `{kind:chat,notes:"status report"}` | ✓ | — |

### Aggregate scores

**Opens (15 sample rows where ground-truth kind is `open`):**
- Regex precision on opens: 15/15 = **1.00**
- Regex recall on opens: 15/15 = **1.00**
- But: 7/15 opens drop information the simulator needs (range → midpoint,
  staging silently flattened, "by market" silently flattened, multi-TP
  truncated, symbol context lost on reply-with-details)

**Management events (15 sample rows where ground-truth is
close/partial/move_sl/increase):**
- Regex precision: 7/15 ≈ **0.47** — when regex says "this is a management
  event", it's right less than half the time
- Regex recall: 11/15 ≈ **0.73**

**Non-trade chat (20 sample rows where ground-truth is `chat`):**
- Regex false-close rate (false-positive `close_full` on chat): **7/20 = 35%**
  — every one of these would have force-closed a real open position

**Overall regex correctness: 27/50 ✓, 23/50 ✗.**

**Estimate:** Haiku 4.5 will pass ~46/50, because the dominant failure mode
is "regex matches the word 'stop' in commentary" — exactly the class of
error the system prompt above routes to `chat` with high confidence.

---

## 5. How to run

```bash
pip install anthropic
ANTHROPIC_API_KEY=sk-... python validate_llm.py
```

The script is self-contained: it embeds all 50 sample messages and the
ground-truth labels, calls Haiku 4.5 with the prompt above and prompt
caching enabled on the system block (~90% input-token discount), and prints
a per-message ✓/✗ table plus a confusion matrix.

**Expected total cost: ~$0.04 to run the full validation.**

---

## 6. Source data

- Channel: "Insiders Scalp" (private, channel ID `-1003881583689`)
- Messages: `last_month_messages.json` from the paper-trading prototype
  (428 messages, 30 days)
- Reference parser (the regex this LLM is replacing): `parser.py` in the
  prototype
- Channel format spec: `project.md` in the prototype
