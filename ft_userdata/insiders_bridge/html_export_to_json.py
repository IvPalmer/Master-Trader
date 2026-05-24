"""Adapt a Telegram chat HTML export into the Telethon JSON shape the
rest of the insiders_bridge pipeline expects.

Telethon shape: {id: int, date: ISO-8601 UTC, text: str, reply_to_msg_id: int|None}

Usage:
    python3 html_export_to_json.py <export_dir> <out_json>

<export_dir>: dir containing messages.html, messages2.html, ...
<out_json>:   path to write the JSON array.
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path

MSG_RE = re.compile(
    r'<div class="message default[^"]*" id="message(\d+)">(.*?)(?=<div class="message |</div>\s*</div>\s*</body>)',
    re.S,
)
REPLY_RE = re.compile(r'<a href="#go_to_message(\d+)"')
DATE_RE = re.compile(r'<div class="pull_right date details" title="([^"]+)">')
TEXT_RE = re.compile(r'<div class="text">(.*?)</div>', re.S)


def strip_tags(html: str) -> str:
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"<[^>]+>", "", html)
    return unescape(html).strip()


def parse_export_date(s: str) -> str:
    # "29.01.2026 11:34:10 UTC-03:00" -> ISO-8601 UTC
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4}) (\d{2}):(\d{2}):(\d{2}) UTC([+-]\d{2}):(\d{2})", s)
    if not m:
        raise ValueError(f"bad date: {s}")
    d, mo, y, hh, mm, ss, oh, omin = m.groups()
    dt = datetime(int(y), int(mo), int(d), int(hh), int(mm), int(ss),
                  tzinfo=timezone(timedelta(hours=int(oh), minutes=int(omin) * (1 if oh.startswith("+") else -1))))
    return dt.astimezone(timezone.utc).isoformat()


def parse_file(path: Path):
    html = path.read_text(encoding="utf-8")
    out = []
    for m in MSG_RE.finditer(html):
        mid = int(m.group(1))
        block = m.group(2)
        date_m = DATE_RE.search(block)
        if not date_m:
            continue
        text_m = TEXT_RE.search(block)
        text = strip_tags(text_m.group(1)) if text_m else ""
        reply_m = REPLY_RE.search(block)
        out.append({
            "id": mid,
            "date": parse_export_date(date_m.group(1)),
            "text": text,
            "reply_to_msg_id": int(reply_m.group(1)) if reply_m else None,
        })
    return out


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    export_dir = Path(sys.argv[1])
    out_path = Path(sys.argv[2])

    files = sorted(export_dir.glob("messages*.html"),
                   key=lambda p: (len(p.stem), p.stem))
    all_msgs = []
    seen = set()
    for f in files:
        msgs = parse_file(f)
        new = [m for m in msgs if m["id"] not in seen]
        seen.update(m["id"] for m in new)
        all_msgs.extend(new)
        print(f"{f.name}: {len(msgs)} parsed, {len(new)} unique kept")

    all_msgs.sort(key=lambda m: m["id"])
    out_path.write_text(json.dumps(all_msgs, ensure_ascii=False, indent=2))
    print(f"wrote {len(all_msgs)} messages to {out_path}")
    print(f"date range: {all_msgs[0]['date']} -> {all_msgs[-1]['date']}")


if __name__ == "__main__":
    main()
