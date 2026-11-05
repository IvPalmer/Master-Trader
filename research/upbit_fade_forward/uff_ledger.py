"""Append-only JSONL ledger, idempotent on replay (#229 forward monitor).

Every record carries a deterministic `rid` (`entry:<event id>`, `oracle:<hour ms>`, ...).
append() writes a record only when its rid is new, and replay keeps the first record of each
rid, so re-running a step, restarting, or replaying a ledger with repeated lines never
duplicates or changes an outcome. A torn last line left by a crash is skipped on replay and
fenced off with a newline before the next append. Nothing is ever rewritten.
"""
import json
import os


class Ledger:
    def __init__(self, path):
        self.path = str(path)
        self.records = {}
        self.order = []
        self._kinds = {}
        self.skipped = 0
        self._torn = False
        self._load()

    def _load(self):
        try:
            with open(self.path, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            return
        self._torn = bool(data) and not data.endswith(b"\n")
        for line in data.splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                self.skipped += 1
                continue
            if not isinstance(rec, dict) or not isinstance(rec.get("rid"), str):
                self.skipped += 1
                continue
            if rec["rid"] not in self.records:
                self._keep(rec)

    def __contains__(self, rid):
        return rid in self.records

    def __len__(self):
        return len(self.order)

    def get(self, rid):
        return self.records.get(rid)

    def kind(self, kind):
        """Records of one kind in append order (do not mutate the list)."""
        return self._kinds.get(kind, [])

    def _keep(self, rec):
        self.records[rec["rid"]] = rec
        self.order.append(rec)
        self._kinds.setdefault(rec.get("kind"), []).append(rec)

    def append(self, rec):
        """Write `rec` unless its rid exists. True when written."""
        if rec["rid"] in self.records:
            return False
        line = json.dumps(rec, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(self.path, "ab") as f:
            if self._torn:
                f.write(b"\n")
            f.write(line.encode("utf-8") + b"\n")
            f.flush()
            os.fsync(f.fileno())
        self._torn = False
        self._keep(rec)
        return True
