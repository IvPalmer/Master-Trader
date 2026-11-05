"""Upbit fade forward monitor (#229): the preregistration freezes the constants the code runs on.

    python3 -m pytest tests/test_upbit_fade_forward_prereg.py -q
"""
import json

import uff_fakes as f
import uff_common as uc
import uff_detect as ud
import uff_report as ur
import nes_returns as nr
import nes_venues as nv

PREREG = f.ROOT / "ft_userdata" / "preregistrations.json"
SPEC = f.ROOT / "docs" / "superpowers" / "specs" / "2026-11-05-upbit-fade-forward-design.md"


def entry():
    reg = json.loads(PREREG.read_text(encoding="utf-8"))["preregistrations"]
    hits = [e for e in reg if e.get("id") == uc.PREREG_ID]
    assert len(hits) == 1
    return hits[0]


def test_entry_is_open_research_only_and_unresolved():
    e = entry()
    assert e["status"] == "open" and e["bot"] is None and e["resolution"] is None
    assert e["issue"] == "#229" and e["triggers"] == [] and e["amendments"] == []
    assert e["registered"] == "2026-11-05" and e["review_by"] == "2027-11-05"
    assert e["spec"].startswith("docs/superpowers/specs/2026-11-05-upbit-fade-forward-design.md")
    assert SPEC.exists()
    assert "allocation" in " ".join(e["rules"]) and e["frozen"]["places_orders"] is False


def test_frozen_block_matches_the_code():
    fr = entry()["frozen"]
    s = lambda ms: ms // 1000   # noqa: E731
    assert fr["archive_poll_s"] == s(uc.ARCHIVE_POLL_MS)
    assert fr["upbit_market_poll_s"] == s(uc.UPBIT_POLL_MS)
    assert fr["tree_lag_max_s"] == s(uc.TREE_LAG_MAX_MS)
    assert fr["krw_snapshot_max_age_s"] == s(uc.KRW_SNAPSHOT_MAX_AGE_MS)
    assert fr["binance_prior_window_s"] == [-s(uc.BINANCE_PRIOR_MS), 0]
    assert fr["binance_market_window_s"] == [-s(uc.MARKET_WINDOW_MS), 0]
    assert fr["hl_evidence"] == nv.HL_EVIDENCE
    assert fr["hl_eligibility_window_s"] == [s(nv.HL_LOOKBACK_MS), s(nv.HL_LAST_MS)]
    assert fr["leak_window_s"] == [s(nr.LEAK_FROM_MS), s(nr.LEAK_TO_MS)]
    assert fr["leak_abs_drift_le"] == str(nr.LEAK_GT)
    assert fr["entry_offset_s"] == s(uc.ENTRY_OFFSET_MS)
    assert fr["timely_entry_s"] == s(uc.TIMELY_MS)
    assert fr["action_deadline_s"] == s(uc.DEADLINE_MS)
    assert fr["hold_s"] == s(uc.HOLD_MS) == fr["primary_horizon_s"]
    assert fr["checkpoints_s"] == [s(ms) for _, ms in uc.CHECKPOINTS]
    assert fr["notional_usdc"] == int(uc.NOTIONAL_USDC)
    assert fr["book_max_age_s"] == s(uc.BOOK_MAX_AGE_MS)
    assert str(fr["taker_fee_bps_per_side"]) == str(uc.FEE_BPS) and fr["extra_slippage_bps"] == 0
    assert fr["oracle_tolerance_s"] == s(uc.ORACLE_TOL_MS)
    assert fr["ci_level"] == "0.95" and float(uc.CI_LEVEL) == 0.95
    assert fr["bootstrap_resamples"] == nr.BOOT_N and fr["bootstrap_seed"] == nr.BOOT_SEED
    assert fr["decision_announcements"] == uc.DECISION_EVENTS
    assert fr["decision_date_utc"] == uc.iso(uc.DECISION_DATE_MS).replace(".000000+00:00", "Z")
    assert fr["descriptive_reports_at"] == list(uc.MILESTONES)
    assert fr["comparable_requires_known_start"] is False and "trading_start_known" not in ur.CRITERIA
    assert fr["binance_proxy_order"] == ["binance_um_futures", "binance_spot"]
    assert [m for m, _ in nv.binance_candidates("X", 0)][:1] == ["um"]


def test_verbatim_rules_quote_the_spec():
    spec = " ".join(SPEC.read_text(encoding="utf-8").split())
    rv = entry()["rules_verbatim"]
    for phrase in ("A book older than 5 s, or depth below q, is", "No extra slippage term",
                   "One decision", "Tree-clock cohort", "unclassified",
                 "stays comparable with `start_unknown = true`", "It never selects events.",
                 "The decision metric is over the whole comparable"):
        plain = phrase.replace("`", "")
        assert phrase in spec
        assert any(plain in r for rules in rv.values() for r in rules), phrase
    assert ud.UNCLASSIFIED_WORDS == ("거래지원", "마켓")
    assert not any("no body field" in n for n in entry()["notes"])   # the blocker is resolved


def test_part_c_entries_are_untouched():
    reg = json.loads(PREREG.read_text(encoding="utf-8"))["preregistrations"]
    ids = [e["id"] for e in reg]
    for kept in ("listing-short-forward-2026-07", "listing-reaction-study-2026-07",
                 "upbit-krw-listing-fade-2026-11"):
        assert kept in ids
    assert len(ids) == len(set(ids))
