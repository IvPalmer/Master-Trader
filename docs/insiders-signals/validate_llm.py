#!/usr/bin/env python3
"""
Validate Claude Haiku 4.5 as a Telegram-signal parser for Insiders Scalp.

Run:
    pip install anthropic
    ANTHROPIC_API_KEY=sk-... python validate_llm.py

Expected cost: ~$0.04 (50 messages, system prompt cached after call #1).
"""
import json
import os
import sys

from anthropic import Anthropic

MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = """You are a signal parser for a crypto Telegram trading channel ("Insiders Scalp").

Each user turn contains ONE Telegram message plus optional parent/sibling context. Your job is to decide what trade event, if any, the message represents — and emit one JSON object that conforms to the response schema.

Channel format facts (memorize these):

1. A message is a TRADE SIGNAL only if it explicitly opens, closes, resizes, or moves the stop on a position. Market commentary, analysis, P&L brags, and reasoning are NOT signals — set is_signal=false and kind="chat".

2. Signal kinds:
   - "open": a new position. Triggered by "<COIN> Long" or "<COIN> Short" as a header, possibly with Entry/SL/TP details in the same message or in a reply.
   - "close_full": full exit. Phrases: "Full close", "Fully closed", "Close all", "Got stopped", "Stopped out", "Closing in small profit" (when applied to a specific position).
   - "close_partial": partial exit. "Close 30%", "Close 50% of remaining position", "Closing 25%", "Close half" (=50%).
   - "move_sl": stop-loss moved. "SL to 77900", "SL to breakeven", "Move SL to ...", "Moving the stop-loss to ...", "Stop at breakeven". A stop being SET on a fresh open is NOT a move_sl — it's part of the open.
   - "increase": adding to existing position. "Adding +30% to BTC short", "Add +50%", "Place a limit order at X and add +N%".
   - "chat": anything else, including: brags, calls, analysis, encouragement, generic risk warnings, hedging commentary, position status updates without an action.

3. The word "stop" is a TRAP. Most messages containing "stop", "stopped", or "stop-loss" are commentary, not actions. Only emit a close/move signal when the author is clearly DOING something to a position right now, not discussing where a stop should be or what might happen.

4. Multi-coin signals: "BTC and ETH" or "BTC & ETH" applies the action to both coins. Set applies_to=["BTC","ETH"]. If single coin, applies_to=null.

5. Entry formats: single number, range ("75800-76600"), staged ("20% - 2360 / 20% - 2400 / ..."), or "by market". For ranges, set entry=null and entry_range=[lo,hi]. For staged, set entry=null and put the per-tranche breakdown into notes. For market, set entry="market".

6. "Breakeven" is a string, not a number — set sl="breakeven".

7. Coins outside Binance (PUMP, WLFI, XPL, FARTCOIN, USELESS) are still valid signals.

8. If unsure, prefer "chat" with confidence<=0.6. False signals lose money; missed chats lose nothing.

CONTEXT RESOLUTION:
- If the message is a reply, you receive the parent message text and the last 2 sibling replies. Use them ONLY to resolve ambiguous references.
- Do NOT re-emit a signal that was already emitted by the parent.

OUTPUT: emit ONE JSON object matching the schema. No prose, no markdown, no chain-of-thought."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["is_signal", "kind", "symbol", "direction", "entry", "entry_range",
                 "sl", "tp", "pct", "applies_to", "confidence", "notes"],
    "properties": {
        "is_signal":   {"type": "boolean"},
        "kind":        {"type": "string",
                        "enum": ["open", "close_full", "close_partial",
                                 "move_sl", "increase", "chat"]},
        "symbol":      {"type": ["string", "null"]},
        "direction":   {"type": ["string", "null"]},
        "entry":       {},
        "entry_range": {},
        "sl":          {},
        "tp":          {},
        "pct":         {"type": ["number", "null"]},
        "applies_to":  {},
        "confidence":  {"type": "number"},
        "notes":       {"type": "string"},
    }
}

SAMPLE = [
    {"id": 1073, "reply_to": None, "text": "XTIU Long \n\nEntry 79-85\n\nSL 73.5\n\n1 Target - 98\n2 Target - 118"},
    {"id": 1088, "reply_to": None, "text": "HYPE Short\n\nEntry 43.5-45\n\nSL 46.181\n\nTarget 36.4"},
    {"id": 1089, "reply_to": None, "text": "PUMP Long \n\nEntry: 0.00182-0.00186\n\nSL: 0.001795\n\nTarget: 0.00203"},
    {"id": 1331, "reply_to": None, "text": "WLFI Long\n\nVery high risk\n\nEntry: 0.053-0.057\n\nSL: 0.0498\n\nTarget: later"},
    {"id": 1453, "reply_to": None, "text": "FARTCOIN Long\n\nEntry: 0.245-0.255\n\nSL: 0.241\n\nTarget: 0.29\n\nHigh risk"},
    {"id": 1056, "reply_to": None, "text": "BTC Short"},
    {"id": 1058, "reply_to": 1056, "text": "BTC Short \n\nEntry 75800-76600\n\nSL 77300\n\nTarget 71000"},
    {"id": 1057, "reply_to": None, "text": "ETH Short"},
    {"id": 1118, "reply_to": None, "text": "BTC Short\n\nAlright, let's set up the short orders.\n\nLimit orders:\n\n10% - by market\n20% - 76,600\n20% - 77,200\n20% - 78,100\n20% - 78,700\n\nSL - 79800"},
    {"id": 1119, "reply_to": None, "text": "ETH Short\n\nHere I have 30% of planned position \n\nLimit orders:\n\n20% - 2,360\n20% - 2,400\n30% - 2,440\n\nSL - 2,480"},
    {"id": 1163, "reply_to": None, "text": "FF Long\n\nEntry: \n\n20% by Market (~0.0723)\n30% 0.0698\n50% 0.0684\n\nSL: 0.0669\n\nTarget: Later"},
    {"id": 1059, "reply_to": 1057, "text": "ETH Short\n\nEntry 2360-2420\n\nSL 2480\n\nTarget 2100"},
    {"id": 1415, "reply_to": None, "text": "XPL Short\n\nEntry: 0.101-0.104\n\nSL: 0.106\n\nTarget: 0.09"},
    {"id": 1074, "reply_to": 1071, "text": "BTC & ETH\n\nClose 30% in both trades"},
    {"id": 1076, "reply_to": 1074, "text": "Close 30% more"},
    {"id": 1530, "reply_to": None, "text": "BTC and ETH\n\nClose 30% in both positions"},
    {"id": 1246, "reply_to": 1203, "text": "SOL\n\nClose 50% of the remaining position\n\nSL to breakeven"},
    {"id": 1274, "reply_to": 1265, "text": "AAVE\n\nClose 50% of remaining position"},
    {"id": 1101, "reply_to": 1085, "text": "BTC and ETH Shorts\n\nClosing 50% of current positions here"},
    {"id": 1509, "reply_to": None, "text": "ETH and BTC Shorts\n\nClose 25% more in both"},
    {"id": 1550, "reply_to": None, "text": "BTC and ETH \n\nFull close \n\nGreat trades"},
    {"id": 1091, "reply_to": 1088, "text": "HYPE  \n\nSL to breakeven"},
    {"id": 1227, "reply_to": 1222, "text": "FARTCOIN \n\nClose 20% and SL to breakeven"},
    {"id": 1344, "reply_to": 1341, "text": "WLFI\n\nClose 25% and move SL to breakeven"},
    {"id": 1252, "reply_to": 1249, "text": "SOL — after adding, my average is 85.8.\n\nMoving the stop-loss to breakeven as well"},
    {"id": 1308, "reply_to": None, "text": "Those who are still holding BTC Long - you can close 40% and move your stop-loss to breakeven"},
    {"id": 1358, "reply_to": 1352, "text": "Stop at breakeven and stay online - we might close and flip into a short earlier."},
    {"id": 1222, "reply_to": None, "text": "FARTCOIN Long"},
    {"id": 1054, "reply_to": 1053, "text": "Like I said - high risk. Ideally, the stop should've been set a bit wider, but that would've been too much"},
    {"id": 1070, "reply_to": None, "text": "Most likely we'll get stopped out here and then re-enter as a new setup."},
    {"id": 1144, "reply_to": None, "text": "I've mapped out a possible scenario on the chart for you."},
    {"id": 1147, "reply_to": 1141, "text": "BTC\n\nWaiting for a final push toward 80,000.\n\nMoving the stop loss to 80,933 so it doesn't get clipped!!!"},
    {"id": 1322, "reply_to": None, "text": "Overall, I want to say - don't overdo it with shorts right now. If your risk is too high, reduce exposure."},
    {"id": 1349, "reply_to": 1347, "text": "There are still chance that we are going to 80k+, that's why stop loss for this short is quite tight"},
    {"id": 1379, "reply_to": None, "text": "Watch your risk - there's a high chance we push higher from here."},
    {"id": 1048, "reply_to": 1040, "text": "+$3,300\n\nNot bad for such trade"},
    {"id": 1050, "reply_to": 1045, "text": "Good morning! Closed the shorts perfectly yesterday."},
    {"id": 1055, "reply_to": 1054, "text": "They might pump the price from here, but I'm not re-entering anymore"},
    {"id": 1090, "reply_to": 1088, "text": "HYPE position much smaller"},
    {"id": 1127, "reply_to": 1118, "text": "Another BTC short order filled\n\n40% of position now"},
    {"id": 1209, "reply_to": 1204, "text": "Closing hedge long in small profit \n\nBounce is too weak"},
    {"id": 1305, "reply_to": 1304, "text": "Closing in small profit"},
    {"id": 1136, "reply_to": 1130, "text": "Close half\n\nAnd SL to breakeven"},
    {"id": 1189, "reply_to": 1151, "text": "quick adjustment on ETH.\n\nSL to breakeven \n\nLike I said, if BTC get acceptance above 78.3k area, we'll push to 80.5k."},
    {"id": 1103, "reply_to": 1078, "text": "On BTC Long\n\nSet the stop at 73,000.\n\nPlace a limit order at 74,000 and add +50% to the position"},
    {"id": 1258, "reply_to": 1257, "text": "Go stopped at breakeven"},
    {"id": 1473, "reply_to": 1465, "text": "FARTCOIN \n\nGot stopped at breakeven with some profit"},
    {"id": 1537, "reply_to": None, "text": "FIDA\n\nFull close in small profit \n\nFonts wanna hold this shit anymore"},
    {"id": 1133, "reply_to": None, "text": "Closing in small profit"},
    {"id": 1394, "reply_to": 1393, "text": "Positions update:\n\nSOL - still in the accumulation zone. You should have around 30-50%.\n\nETH - around 50-70%."},
]

GROUND_TRUTH = {
    1073: {"kind": "open", "symbol": "XTIU", "direction": "long"},
    1088: {"kind": "open", "symbol": "HYPE", "direction": "short"},
    1089: {"kind": "open", "symbol": "PUMP", "direction": "long"},
    1331: {"kind": "open", "symbol": "WLFI", "direction": "long"},
    1453: {"kind": "open", "symbol": "FARTCOIN", "direction": "long"},
    1056: {"kind": "open", "symbol": "BTC", "direction": "short"},
    1058: {"kind": "open", "symbol": "BTC", "direction": "short"},
    1057: {"kind": "open", "symbol": "ETH", "direction": "short"},
    1118: {"kind": "open", "symbol": "BTC", "direction": "short"},
    1119: {"kind": "open", "symbol": "ETH", "direction": "short"},
    1163: {"kind": "open", "symbol": "FF", "direction": "long"},
    1059: {"kind": "open", "symbol": "ETH", "direction": "short"},
    1415: {"kind": "open", "symbol": "XPL", "direction": "short"},
    1074: {"kind": "close_partial", "applies_to": ["BTC", "ETH"]},
    1076: {"kind": "close_partial"},
    1530: {"kind": "close_partial", "applies_to": ["BTC", "ETH"]},
    1246: {"kind": "close_partial", "symbol": "SOL"},
    1274: {"kind": "close_partial", "symbol": "AAVE"},
    1101: {"kind": "close_partial", "applies_to": ["BTC", "ETH"]},
    1509: {"kind": "close_partial", "applies_to": ["ETH", "BTC"]},
    1550: {"kind": "close_full", "applies_to": ["BTC", "ETH"]},
    1091: {"kind": "move_sl", "symbol": "HYPE"},
    1227: {"kind": "close_partial", "symbol": "FARTCOIN"},
    1344: {"kind": "close_partial", "symbol": "WLFI"},
    1252: {"kind": "move_sl", "symbol": "SOL"},
    1308: {"kind": "chat"},
    1358: {"kind": "move_sl"},
    1222: {"kind": "open", "symbol": "FARTCOIN", "direction": "long"},
    1054: {"kind": "chat"},
    1070: {"kind": "chat"},
    1144: {"kind": "chat"},
    1147: {"kind": "move_sl", "symbol": "BTC"},
    1322: {"kind": "chat"},
    1349: {"kind": "chat"},
    1379: {"kind": "chat"},
    1048: {"kind": "chat"},
    1050: {"kind": "chat"},
    1055: {"kind": "chat"},
    1090: {"kind": "chat"},
    1127: {"kind": "chat"},
    1209: {"kind": "close_full"},
    1305: {"kind": "close_full"},
    1136: {"kind": "close_partial"},
    1189: {"kind": "move_sl", "symbol": "ETH"},
    1103: {"kind": "increase", "symbol": "BTC"},
    1258: {"kind": "close_full"},
    1473: {"kind": "close_full", "symbol": "FARTCOIN"},
    1537: {"kind": "close_full", "symbol": "FIDA"},
    1133: {"kind": "close_full"},
    1394: {"kind": "chat"},
}


def build_user_turn(msg, by_id):
    parent_id = msg["reply_to"]
    parent_text = by_id[parent_id]["text"] if parent_id in by_id else "<none>"
    siblings = [m for m in SAMPLE
                if m["reply_to"] == parent_id and m["id"] != msg["id"]][:2]
    sib_lines = "\n".join(f"- (id={s['id']}): {s['text']}" for s in siblings) or "<none>"
    return (f"PARENT (id={parent_id}): {parent_text}\n"
            f"SIBLINGS:\n{sib_lines}\n\n"
            f"THIS MESSAGE (id={msg['id']}):\n{msg['text']}")


def call_llm(client, user_turn):
    resp = client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_turn}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    return json.loads(text), resp.usage


def compare(pred, truth):
    if pred.get("kind") != truth.get("kind"):
        return False, f"kind: pred={pred.get('kind')} truth={truth.get('kind')}"
    for field in ("symbol", "direction", "applies_to"):
        if field in truth:
            p, t = pred.get(field), truth[field]
            if isinstance(p, str) and isinstance(t, str) and p.lower() == t.lower():
                continue
            if isinstance(p, list) and isinstance(t, list) and sorted(p) == sorted(t):
                continue
            if p != t:
                return False, f"{field}: pred={p} truth={t}"
    return True, "ok"


def main():
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set")
    client = Anthropic()
    by_id = {m["id"]: m for m in SAMPLE}
    confusion = {}
    passed = failed = 0
    cache_reads_total = 0
    for msg in SAMPLE:
        user_turn = build_user_turn(msg, by_id)
        try:
            pred, usage = call_llm(client, user_turn)
        except Exception as e:
            print(f"[{msg['id']}] ERROR: {e}")
            failed += 1
            continue
        truth = GROUND_TRUTH[msg["id"]]
        ok, reason = compare(pred, truth)
        key = (truth["kind"], pred.get("kind", "?"))
        confusion[key] = confusion.get(key, 0) + 1
        cache_reads_total += getattr(usage, "cache_read_input_tokens", 0) or 0
        status = "✓" if ok else "✗"
        snippet = msg["text"].replace("\n", " ")[:50]
        print(f"[{status}] id={msg['id']:>4} kind={pred.get('kind'):<14} | {snippet:<52} | {reason}")
        passed += ok
        failed += not ok
    print(f"\n=== RESULTS: {passed}/{len(SAMPLE)} passed ===")
    print(f"Cache reads: {cache_reads_total} tokens (should be high after the first call)")
    print("\nConfusion matrix (truth_kind -> pred_kind):")
    kinds = sorted({k for pair in confusion for k in pair})
    header = "truth\\pred"
    print(f"{header:<14}" + "".join(f"{k:<14}" for k in kinds))
    for tk in kinds:
        row = f"{tk:<14}" + "".join(f"{confusion.get((tk, pk), 0):<14}" for pk in kinds)
        print(row)


if __name__ == "__main__":
    main()
