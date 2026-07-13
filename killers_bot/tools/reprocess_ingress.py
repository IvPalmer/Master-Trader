#!/usr/bin/env python3
"""Re-classify a receiver's ingress corpus and diff old vs new `kind`.

Reads a receiver.sqlite (the `ingress_events` audit table), re-runs each
stored message through `classifier.classify`, and writes a CSV of
`msg_id, old_kind, new_kind, changed`.

Purpose: after a classifier change (e.g. adding the `signal_update` kind
in prereg killers-fill-realism-2026-07), measure how many historical
messages would now classify differently — especially the `chat → signal_update`
misses like KITE #2154 that cost −$9.42.

READ-ONLY on the DB. The only write is the output CSV. No FT calls, no
receiver side effects. Runnable ONLY where the `claude` CLI is available
(classify shells out to it), i.e. the VPS — NOT run automatically here.

Usage:
    python3 reprocess_ingress.py RECEIVER_SQLITE OUTPUT_CSV \
        [--template killers|insiders] \
        [--binary "claude"] [--model MODEL] [--limit N] [--timeout SEC]

Example (VPS):
    python3 killers_bot/tools/reprocess_ingress.py \
        /var/lib/killers/receiver.sqlite /tmp/reprocess_killers.csv \
        --template killers
"""
import argparse
import asyncio
import csv
import json
import sqlite3
import sys
from pathlib import Path

# Import the classifier from the killers_bot package (parent of this tools dir).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from killers_bot import classifier  # noqa: E402


def _template_for(name: str) -> str:
    if name == "insiders":
        return classifier.INSIDERS_PROMPT_TEMPLATE
    return classifier.PROMPT_TEMPLATE


def _rows(db_path: str, limit=None):
    """Yield (msg_id, old_kind, msg_dict) from ingress_events, read-only."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    sql = ("SELECT msg_id, kind, raw_payload FROM ingress_events "
           "ORDER BY msg_id ASC")
    if limit:
        sql += f" LIMIT {int(limit)}"
    try:
        for r in conn.execute(sql):
            try:
                payload = json.loads(r["raw_payload"])
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            msg = payload.get("msg") or {}
            cls = payload.get("classification") or {}
            # old_kind: prefer the ingress column, fall back to the stored cls.
            old_kind = r["kind"] or cls.get("kind")
            if not isinstance(msg, dict) or msg.get("id") is None:
                # Reconstruct a minimal msg from the ingress row when the stored
                # payload lacks one (defensive; older rows may differ).
                msg = {"id": r["msg_id"], "text": msg.get("text") if isinstance(msg, dict) else None}
            yield r["msg_id"], old_kind, msg
    finally:
        conn.close()


async def _run(args):
    template = _template_for(args.template)
    out_path = Path(args.output_csv)
    total = 0
    changed = 0
    with out_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["msg_id", "old_kind", "new_kind", "changed"])
        for msg_id, old_kind, msg in _rows(args.receiver_sqlite, args.limit):
            total += 1
            result = await classifier.classify(
                msg, [],  # no reply-chain reconstruction; single-message pass
                binary=args.binary, model=args.model,
                timeout_sec=args.timeout, template=template,
            )
            new_kind = result.get("kind") if isinstance(result, dict) else None
            is_changed = (new_kind is not None and new_kind != old_kind)
            if is_changed:
                changed += 1
            w.writerow([msg_id, old_kind, new_kind,
                        "1" if is_changed else "0"])
            if total % 50 == 0:
                print(f"...processed {total} (changed so far: {changed})",
                      file=sys.stderr)
    print(f"done: {total} messages, {changed} changed → {out_path}",
          file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("receiver_sqlite", help="path to receiver.sqlite (read-only)")
    ap.add_argument("output_csv", help="path to write the diff CSV")
    ap.add_argument("--template", choices=["killers", "insiders"],
                    default="killers", help="which prompt template to use")
    ap.add_argument("--binary", default="claude",
                    help="claude CLI command (may be multi-word, e.g. "
                         "'docker exec elder-brain-bot claude')")
    ap.add_argument("--model", default=None, help="optional --model for claude")
    ap.add_argument("--limit", type=int, default=None,
                    help="only reprocess the first N ingress rows")
    ap.add_argument("--timeout", type=float, default=15.0,
                    help="per-message classify timeout (seconds)")
    args = ap.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
