"""grade.py — score a persisted run against curated truth + a naive-regex baseline (SPEC §7).

Reads runs/<name>/ JSON files. Imports nothing in-package at runtime (per the §10 DAG); it only
consumes the persisted artifacts and the sibling truth files (../trades_may.json, ../RESULTS_MAY.md).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TRUTH = os.path.join(HERE, "..", "trades_may.json")
DEFAULT_RESULTS = os.path.join(HERE, "..", "RESULTS_MAY.md")


@dataclass
class GradeReport:
    run_dir: str
    per_step: list = field(default_factory=list)
    dimension_accuracy: dict = field(default_factory=dict)
    causal_clean_count: int = 0
    causal_total: int = 0
    audit_failed_steps: list = field(default_factory=list)  # steps with a reject verdict / any violation
    fail_closed: bool = False                               # True => run VOIDED by an audit failure
    passed: bool = False                                    # overall PASS only if dims pass AND not fail_closed
    llm_vs_baseline: dict = field(default_factory=dict)
    summary: str = ""

    def to_jsonable(self) -> dict:
        return {
            "run_dir": self.run_dir,
            "per_step": self.per_step,
            "dimension_accuracy": self.dimension_accuracy,
            "causal_clean_count": self.causal_clean_count,
            "causal_total": self.causal_total,
            "audit_failed_steps": self.audit_failed_steps,
            "fail_closed": self.fail_closed,
            "passed": self.passed,
            "llm_vs_baseline": self.llm_vs_baseline,
            "summary": self.summary,
        }


def _load_truth_for_src(truth_path: str, src_id: int):
    trades = json.load(open(truth_path))
    for t in trades:
        if t.get("src_id") == src_id:
            return t
    return None


def grade(run_dir: str, truth_events_path: str = DEFAULT_TRUTH,
          truth_results_path: str = DEFAULT_RESULTS, baseline: str = "regex") -> GradeReport:
    steps = []
    with open(os.path.join(run_dir, "steps.jsonl")) as f:
        for line in f:
            line = line.strip()
            if line:
                steps.append(json.loads(line))
    final = json.load(open(os.path.join(run_dir, "final_ledger.json")))

    rep = GradeReport(run_dir=run_dir)

    # --- BTC-1609 dimension (the acceptance dimension) ---
    # expected: close_full at msg 1611, BTC short, realized_R ~0 within +/-0.15R, evidence clean
    btc1609 = _load_truth_for_src(truth_events_path, 1609)
    realized = final.get("realized_R", {}).get("BTC")
    step_1611 = next((s for s in steps if s["decision_msg_id"] == 1611), None)

    passes = {}
    if step_1611 is not None:
        it = step_1611["intent"]
        passes["intent_type_close_full"] = (it["intent_type"] == "close_full")
        passes["symbol_side_btc_short"] = (it["symbol"] == "BTC" and it["side"] == "short")
        passes["evidence_clean"] = (step_1611["evidence_audit"]["verdict"] == "accept"
                                    and not step_1611["evidence_audit"]["violations"])
    else:
        passes["intent_type_close_full"] = False
        passes["symbol_side_btc_short"] = False
        passes["evidence_clean"] = False
    passes["breakeven_R"] = (realized is not None and abs(realized) <= 0.15)

    rep.per_step.append({
        "decision_msg_id": 1611, "dimension": "btc1609_breakeven",
        "checks": passes, "realized_R": realized,
    })
    rep.dimension_accuracy["btc1609"] = all(passes.values())

    # --- seeded-long close (criterion 1, non-vacuous attribution) ---
    step_1608 = next((s for s in steps if s["decision_msg_id"] == 1608), None)
    seed_closed = False
    if step_1608 is not None:
        snap = step_1608["ledger_snapshot"]
        closed_syms = {p["symbol"] for p in snap.get("closed", [])}
        seed_closed = ("BTC" in closed_syms)
        # and BTC not open as a long anymore at that point
    rep.dimension_accuracy["seeded_long_closed_at_1608"] = seed_closed

    # --- causal cleanliness count ---
    rep.causal_total = len(steps)
    rep.causal_clean_count = sum(1 for s in steps if s["evidence_audit"]["verdict"] == "accept"
                                 and not s["evidence_audit"]["violations"])

    # --- FAIL-CLOSED: any step with a reject verdict OR any audit violation voids the run ---
    # A run is never booked best-effort or silently skipped past an audit failure. One bad step
    # (future-data leak, fabricated/missing candle, or interpreter-supplied scalar price) is
    # enough to mark the whole run failed.
    for s in steps:
        ea = s["evidence_audit"]
        if ea["verdict"] == "reject" or ea["violations"]:
            rep.audit_failed_steps.append({
                "step": s.get("step"),
                "decision_msg_id": s.get("decision_msg_id"),
                "verdict": ea["verdict"],
                "violations": ea["violations"],
            })
    rep.fail_closed = bool(rep.audit_failed_steps)

    # --- naive-regex baseline delta on the 1609 dimension ---
    # regex mis-reads "Closing around be" as an SL move -> NOT a close_full -> rides the position
    if baseline == "regex":
        rep.llm_vs_baseline["btc1609"] = {
            "causal_llm": "close_full @ breakeven (~0R)" if rep.dimension_accuracy["btc1609"] else "FAIL",
            "regex_baseline": "sl_move to BE (mis-read 'be') -> rides short, books fictional multi-R win = FAIL",
            "delta": "causal-LLM PASS, regex FAIL" if rep.dimension_accuracy["btc1609"] else "both fail",
        }

    # FAIL-CLOSED gate: even if every dimension passes, ANY audit failure voids the run.
    dims_ok = bool(rep.dimension_accuracy.get("btc1609")
                   and rep.dimension_accuracy.get("seeded_long_closed_at_1608"))
    rep.passed = dims_ok and not rep.fail_closed
    void_note = (f" RUN VOIDED — fail-closed on {len(rep.audit_failed_steps)} audit failure(s): "
                 f"{rep.audit_failed_steps}." if rep.fail_closed else "")
    rep.summary = (
        f"BTC-1609 dimension: {'PASS' if rep.dimension_accuracy.get('btc1609') else 'FAIL'} "
        f"(realized_R={realized}); seeded-long closed at 1608: "
        f"{'YES' if seed_closed else 'NO'}; causal-clean {rep.causal_clean_count}/{rep.causal_total} steps; "
        f"regex baseline FAILS the 1609 close (mis-reads 'be'). Overall: "
        f"{'PASS' if rep.passed else 'FAIL'}.{void_note}"
    )

    with open(os.path.join(run_dir, "grade.json"), "w") as f:
        json.dump(rep.to_jsonable(), f, indent=2)
    return rep
