"""Part C preregistrations (#229): the three retrospective event studies.

The entries freeze every rule before any Phase 1 code touches real data. Later tasks
test their constants against `frozen`, so these tests pin that block and check that the
verbatim rule strings really are spec text.

    python3 -m pytest tests/test_news_event_studies_prereg.py -q
"""
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


def test_hl_evidence_identical_and_known():
    values = {e["frozen"]["hl_evidence"] for e in entries().values()}
    assert len(values) == 1 and values <= {"fundingHistory", "candleSnapshot_1h"}


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
