"""Part C preregistrations (#229): the three retrospective event studies.

The entries freeze every rule before any Phase 1 code touches real data. Later tasks
test their constants against `frozen`, so these tests pin that block and check that the
verbatim rule strings really are spec text.

    python3 -m pytest tests/test_news_event_studies_prereg.py -q
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREREG = ROOT / "ft_userdata" / "preregistrations.json"
SPEC = ROOT / "docs" / "superpowers" / "specs" / "2026-11-03-news-archive-design.md"

IDS = ("binance-delisting-reaction-2026-11", "upbit-krw-listing-reaction-2026-11",
       "upbit-krw-listing-fade-2026-11")
COMMON = {  # identical in all three entries' "frozen"
    "window_utc": ["2023-01-01T00:00:00Z", "2026-11-01T00:00:00Z"],   # end exclusive
    "unit": "announcement", "entry_offset_s": 300, "descriptive_entry_offset_s": 60,
    "horizons_s": [1800, 14400, 86400], "primary_horizon_s": 14400,
    "fee_bps_per_side": {"hyperliquid": 4.5, "binance_spot": 7.5},
    "slippage_bps_per_side": 10, "stress_slippage_bps_per_side": 25,
    "leak_window_s": [-600, -120], "leak_abs_drift_gt": "0.02",
    "halt_resume_window_s": 259200, "min_announcements": 20,
    "top_decile_share_lt": 0.6, "coverage_gate_gt": 0.2,
    "bootstrap_resamples": 10000, "bootstrap_seed": 229,
    "hl_eligibility_window_s": [86400, 3600],
    "proxy_preference": ["binance_um_futures", "binance_spot"],
    "proxy_dates_d": [-1, 2], "kline_download_dates_d": [-1, 5],
}
LONG_BLOCK = {
    "direction": "long", "venues": ["hyperliquid", "binance_spot"],
    "t0_field": "upbit.first_listed_at", "binance48_overlap_s": 86400,
    "exclude_title_words": ["종료", "유의", "제거", "변경", "중단", "연기", "재개"],
    "manifest": "upbit-manifest.json",
}
STUDY_BLOCKS = {
    IDS[0]: {
        "direction": "short", "venues": ["hyperliquid"], "t0_field": "binance_cms.releaseDate",
        "event_catalogs": [161], "kinds": ["full_delist", "monitoring_add"],
        "same_token_overlap_s": 86400, "manifest": "delisting-manifest.json",
    },
    IDS[1]: LONG_BLOCK,
    IDS[2]: {**LONG_BLOCK, "direction": "short", "venues": ["hyperliquid"],
             "shares_manifest_with": IDS[1]},
}


def entries():
    reg = json.loads(PREREG.read_text(encoding="utf-8"))["preregistrations"]
    return {i: next(e for e in reg if e.get("id") == i) for i in IDS}


def test_entries_open_and_research_only():
    for i, e in entries().items():
        assert e["bot"] is None and e["issue"] == "#229" and e["review_by"] == "2027-02-01", i
        assert e["triggers"] == [], i
        # Open with no resolution, or closed with a mechanical one (Task 11). Every
        # amendment must be made before results (the manifest freeze, Task 10).
        assert (e["status"], e["resolution"] is None) in {("open", True), ("closed", False)}, i
        assert all(a.get("frozen_before_results") is True for a in e["amendments"]), i
        assert "allocation" in json.dumps(e, ensure_ascii=False).lower(), i


def test_frozen_common_block():
    for i, e in entries().items():
        assert {k: e["frozen"].get(k) for k in COMMON} == COMMON, i


def test_frozen_study_blocks():
    for i, e in entries().items():
        block = {k: e["frozen"].get(k) for k in STUDY_BLOCKS[i]}
        assert block == STUDY_BLOCKS[i], i
        extra = set(e["frozen"]) - set(COMMON) - set(STUDY_BLOCKS[i]) - {"hl_evidence"}
        assert not extra, (i, extra)


def test_hl_evidence_is_funding_history():   # C1 option A, spec §11 call 14
    assert {e["frozen"]["hl_evidence"] for e in entries().values()} == {"fundingHistory"}


# sha256 of the O1–O17 list as merged in #237 (canonical JSON). Any edit is an amendment.
O_SHA256 = "bf110894663e6f4a27d6085170e42992969ea4173fff0783dfdce3a401bcbbdf"


def _canon_sha(obj):
    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def test_operationalization_o1_to_o17_pinned():
    for i, e in entries().items():
        ops = e["operationalization"]
        assert [s.split(" ", 1)[0] for s in ops] == ["O%d" % n for n in range(1, 18)], i
        assert _canon_sha(ops) == O_SHA256, i


def _spec_bullets(start, end):
    lines = SPEC.read_text(encoding="utf-8").splitlines()
    a = next(n for n, l in enumerate(lines) if start in l)
    b = next(n for n, l in enumerate(lines) if n > a and end in l)
    return [l for l in lines[a + 1:b] if re.match(r"^\s*- ", l)]


def _clean(line):
    return re.sub(r"^\s*- ", "", line).strip().replace("**", "")


OWN_VENUE = {IDS[0]: "Delisting study (short)", IDS[1]: "Upbit study (long)",
             IDS[2]: "Upbit fade (short)"}
OTHER_EVENTS = {IDS[0]: "Events, both Upbit studies", IDS[1]: "Events, delisting study",
                IDS[2]: "Events, delisting study"}


def test_rules_verbatim_complete():
    phase2 = [_clean(l) for l in _spec_bullets("**Phase 2 — returns", "## 7. Step 0")]
    for i, e in entries().items():
        expected, skipping, in_venues = [], False, False
        for l in _spec_bullets("**Phase 1 — manifest", "**Phase 2 — returns"):
            top = l.startswith("- ")
            if top:
                skipping = OTHER_EVENTS[i] in l
                in_venues = "Execution venues" in l
            if skipping or (in_venues and not top and OWN_VENUE[i] not in l):
                continue
            expected.append(_clean(l))
        assert e["rules_verbatim"]["phase1"] == expected, i
        assert e["rules_verbatim"]["phase2"] == phase2, i


def _norm(s):
    return re.sub(r"\s+", " ", s.replace("**", "")).strip()


def test_rules_verbatim_are_spec_text():
    spec = _norm(SPEC.read_text(encoding="utf-8"))
    for i, e in entries().items():
        rv = e["rules_verbatim"]
        assert rv["phase1"] and rv["phase2"], i
        quoted = [s for v in rv.values() for s in v]
        quoted += e["pass_criteria"] + [e["kill"]] + e["inconclusive"] + [e["hypothesis"]]
        for s in quoted:
            assert _norm(s) in spec, (i, s[:80])
