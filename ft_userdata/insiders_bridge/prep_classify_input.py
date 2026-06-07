"""Build a compact prompt-input file from a Telethon-shape message JSON.

For each message, attach parent text + last 2 sibling replies so the classifier
has full context (matches validate_llm.py's build_user_turn). Output is JSONL,
one compact line per message, for easy chunked reading by the classifier.

Usage:
    python3 prep_classify_input.py [input_json] [output_jsonl]

Defaults: _local/last_month_messages.json → out/classify_input.jsonl
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
in_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "_local" / "last_month_messages.json"
out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "out" / "classify_input.jsonl"

content = in_path.read_text()
msgs, _ = json.JSONDecoder().raw_decode(content)

by_id = {m["id"]: m for m in msgs}


def build_ctx(msg):
    parent_id = msg.get("reply_to_msg_id")
    parent_text = by_id[parent_id]["text"] if parent_id in by_id else None
    siblings = [
        m for m in msgs
        if m.get("reply_to_msg_id") == parent_id and m["id"] != msg["id"]
    ][:2]
    return {
        "id": msg["id"],
        "date": msg["date"],
        "text": msg.get("text", ""),
        "parent_id": parent_id,
        "parent_text": parent_text,
        "siblings": [[s["id"], s["text"]] for s in siblings],
    }


out = [build_ctx(m) for m in sorted(msgs, key=lambda m: m["id"])]
out_path.parent.mkdir(parents=True, exist_ok=True)
with out_path.open("w") as f:
    for item in out:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
print(f"wrote {len(out)} lines to {out_path}")
print(f"size: {out_path.stat().st_size} bytes")
