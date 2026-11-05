"""Upbit fade forward monitor (#229): eligibility at t0, comparable versus descriptive cohort.

    python3 -m pytest tests/test_upbit_fade_forward_eligibility.py -q
"""
import uff_fakes as f
import uff_report as ur

START_BODY = "<p>거래지원 개시 시점 : 2026년 11월 10일 17:00 예정</p>"     # 08:00Z, after t0
BEFORE_BODY = "<p>거래지원 개시 시점 : 2026년 11월 10일 14:00</p>"         # 05:00Z, before t0


def scenario(tmp_path, body=START_BODY, setup=None, **kw):
    s = f.Scenario(tmp_path, body=body, **kw)
    if setup:
        setup(s)
    s.run(s.t0 - 1000, every_ms=60_000)           # market/all snapshots up to t0
    return s


def detect(s, until=20 * f.MIN, allow=(), **publish):
    s.publish(**publish)
    s.run(s.t0 + until)
    assert [e for e in s.mon.errors if not e.startswith(allow)] == []
    return s


def cohort(s):
    return ur.classify(ur.view(s.mon.ledger, s.rec("event")))


def test_comparable_when_every_rule_holds(tmp_path):
    s = detect(scenario(tmp_path), until=61 * f.MIN)
    assert cohort(s) == ("comparable", [])
    ev = s.rec("event")                                       # a body start at or after t0
    assert ev["trading_start_ms"] >= s.t0 and ev["start_unknown"] is False
    assert ur.start_unknown(ev) is False
    assert s.rec("entry")["status"] == "timely"
    assert s.rec("binance")["market"] == "um" and s.rec("binance")["leaked"] is False
    assert s.rec("bprior")["found"] is False


# --- exclusions ----------------------------------------------------------------------------

def test_token_already_on_upbit_krw_is_excluded_and_never_traded(tmp_path):
    def listed(s):
        s.http.markets_fn = lambda now: ["KRW-BTC", "KRW-CARDS"]
    s = detect(scenario(tmp_path, setup=listed))
    assert s.rec("event")["krw_prior"] is True
    assert cohort(s) == ("excluded", ["already_on_krw"])
    assert s.rec("entry") is None and s.hl.count("l2Book") == 0


def test_market_added_after_t0_does_not_exclude(tmp_path):
    s = scenario(tmp_path)
    s.http.markets_fn = lambda now: ["KRW-BTC"] + (["KRW-CARDS"] if now >= s.t0 else [])
    detect(s)
    assert s.rec("event")["krw_prior"] is False and cohort(s)[0] == "comparable"


def test_no_snapshot_within_15_min_before_t0_is_unknown(tmp_path):
    def down(s):
        s.http.upbit_status = 503                 # every market/all poll fails
    s = detect(scenario(tmp_path, setup=down), until=61 * f.MIN, allow=("_poll_upbit",))
    assert s.rec("event")["krw_prior"] == "unknown"
    assert cohort(s) == ("comparable", ["krw_snapshot"])   # not established: outcome missing
    assert s.rec("entry")["status"] == "timely"            # still measured


def test_binance_listing_notice_in_the_24_h_before_t0_excludes(tmp_path):
    s = scenario(tmp_path)
    s.archive.binance(1, "Binance Will List CollectorCrypt (CARDS)", s.t0 - 23 * f.H, s.t0 - 23 * f.H)
    detect(s)
    assert s.rec("event")["binance_prior"]["ref"] == "binance:1"
    assert cohort(s) == ("excluded", ["binance_listing_prior"])
    assert s.rec("entry") is None


def test_binance_notice_after_t0_or_older_than_24_h_never_excludes(tmp_path):
    s = scenario(tmp_path)
    s.archive.binance(2, "Binance Will List CARDS (CARDS)", s.t0 - 25 * f.H, s.t0 - 25 * f.H)
    s.archive.binance(3, "Binance Will List OTHER (OTHER)", s.t0 - f.H, s.t0 - f.H)
    detect(s, until=f.MIN)
    s.archive.binance(4, "Binance Will List CARDS (CARDS)", s.t0 + 2 * f.MIN, s.t0 + 2 * f.MIN)
    s.run(s.t0 + 61 * f.MIN)
    assert s.rec("bprior")["found"] is False and cohort(s)[0] == "comparable"


def test_binance_notice_published_before_t0_but_archived_later_excludes_post_hoc(tmp_path):
    s = scenario(tmp_path)
    detect(s)                                      # traded: nothing in the archive yet
    s.archive.binance(5, "Binance Will List CARDS (CARDS)", s.t0 - 2 * f.MIN, s.t0 + 20 * f.MIN)
    s.run(s.t0 + 61 * f.MIN)                       # the t0 + 1 h re-check finds it
    assert s.rec("entry")["status"] == "timely"
    assert s.rec("bprior")["found"] is True
    assert cohort(s) == ("excluded", ["binance_listing_prior"])


def test_body_saying_trading_began_before_the_notice_excludes(tmp_path):
    s = detect(scenario(tmp_path, body=BEFORE_BODY))
    assert s.rec("event")["began_before_notice"] is True
    assert s.rec("event")["trading_start_ms"] < s.t0 and s.rec("event")["start_unknown"] is False
    assert cohort(s) == ("excluded", ["began_before_notice"]) and s.rec("entry") is None


# --- Hyperliquid eligibility (Part C rule, reused) --------------------------------------------

def test_no_funding_record_in_the_last_hour_is_ineligible(tmp_path):
    s = scenario(tmp_path)
    s.hl.funding["CARDS"] = [(s.t0 - 3 * f.H + 7, "0.0001")]
    detect(s)
    assert s.rec("hl")["status"] == "ineligible" and s.rec("hl")["reason"] == "no_recent_funding"
    assert cohort(s) == ("ineligible", ["no_recent_funding"]) and s.rec("entry") is None


def test_perp_not_in_meta_is_ineligible(tmp_path):
    s = scenario(tmp_path)
    s.hl.universe = [u for u in s.hl.universe if u["name"] != "CARDS"]
    detect(s)
    hl = s.rec("hl")
    assert hl["status"] == "ineligible" and hl["reason"] == "not_in_meta" and hl["in_meta"] is False
    assert s.rec("entry") is None


def test_k_prefixed_perp_is_found(tmp_path):
    s = scenario(tmp_path)
    s.hl.universe.append({"name": "kCARDS", "szDecimals": 0})
    s.hl.universe = [u for u in s.hl.universe if u["name"] != "CARDS"]
    s.hl.funding["kCARDS"] = s.hl.funding.pop("CARDS")
    s.hl.mid["kCARDS"] = "1.0"
    detect(s)
    assert s.rec("hl")["coin"] == "kCARDS" and s.rec("entry")["coin"] == "kCARDS"


def test_hyperliquid_unreachable_until_the_entry_deadline_is_unknown(tmp_path):
    s = scenario(tmp_path)
    s.hl.fail.add("meta")
    detect(s)
    assert s.rec("hl")["status"] == "unknown"
    assert s.rec("hl")["at_ms"] > s.t0 + 15 * f.MIN          # retried until the deadline
    assert cohort(s) == ("comparable", ["hl_eligible", "entry_timely"])
    assert s.rec("entry") is None


# --- comparable-cohort requirements -------------------------------------------------------------

def test_no_body_or_no_stated_start_is_comparable_with_start_unknown(tmp_path):
    s = detect(scenario(tmp_path, body=None), until=61 * f.MIN)   # Tree items carry no body
    ev = s.rec("event")
    assert ev["has_body"] is False and ev["trading_start_ms"] is None
    assert ev["start_unknown"] is True and ev["began_before_notice"] is False
    assert cohort(s) == ("comparable", [])                   # a flag, not a missing requirement
    assert s.rec("entry")["status"] == "timely"
    s2 = detect(scenario(tmp_path / "b", body="<p>입출금 일정은 추후 안내</p>"), until=61 * f.MIN)
    assert s2.rec("event")["start_unknown"] is True and cohort(s2) == ("comparable", [])


def test_unverified_tree_timing_is_descriptive(tmp_path):
    s = detect(scenario(tmp_path), received_ms=f.T0 + 6 * f.MIN)
    assert s.rec("event")["timing"] == "unverified"
    assert "timing_verified" in cohort(s)[1] and cohort(s)[0] == "descriptive"


def test_no_binance_market_before_t0_is_descriptive(tmp_path):
    s = scenario(tmp_path)
    del s.http.klines[("um", "CARDSUSDT")]
    detect(s)
    b = s.rec("binance")
    assert b["market_pre_t0"] is False and len(b["tried"]) == 7          # 4 USDⓈ-M + 3 spot
    assert cohort(s) == ("descriptive", ["binance_market_pre_t0"])


def test_spot_is_the_fallback_only_when_no_usdm_market_exists(tmp_path):
    s = scenario(tmp_path)
    del s.http.klines[("um", "CARDSUSDT")]
    s.http.klines[("spot", "CARDSUSDT")] = f.flat("2.0")
    detect(s)
    assert (s.rec("binance")["market"], s.rec("binance")["symbol"]) == ("spot", "CARDSUSDT")
    assert cohort(s)[0] == "comparable"


def test_a_failed_usdm_read_is_retried_not_replaced_by_spot(tmp_path):
    s = scenario(tmp_path)
    s.http.klines[("um", "CARDSUSDT")] = 500
    s.http.klines[("spot", "CARDSUSDT")] = f.flat("2.0")
    detect(s, until=3 * f.MIN)
    assert s.rec("binance") is None and s.http.count("//api.binance.com") == 0
    s.http.klines[("um", "CARDSUSDT")] = f.flat("1.0")
    s.run(s.t0 + 5 * f.MIN)
    assert s.rec("binance")["market"] == "um"


def test_binance_leak_test(tmp_path):
    leak = lambda t: "1.03" if t >= f.T0 - 3 * f.MIN else "1.00"        # noqa: E731  +3%
    s = scenario(tmp_path)
    s.http.klines[("um", "CARDSUSDT")] = leak
    detect(s)
    assert s.rec("binance")["leaked"] is True
    assert cohort(s) == ("descriptive", ["binance_leak_passed"])
    calm = lambda t: "1.015" if t >= f.T0 - 3 * f.MIN else "1.00"       # noqa: E731  +1.5%
    s2 = scenario(tmp_path / "b")
    s2.http.klines[("um", "CARDSUSDT")] = calm
    detect(s2)
    assert s2.rec("binance")["leaked"] is False and cohort(s2)[0] == "comparable"


def test_market_opening_inside_the_leak_window_leaves_the_leak_test_unrun(tmp_path):
    s = scenario(tmp_path)
    s.http.listed_from["CARDSUSDT"] = f.T0 - 5 * f.MIN - f.T0 % f.MIN
    detect(s)
    b = s.rec("binance")
    assert b["market_pre_t0"] is True and b["leaked"] is None
    assert cohort(s) == ("comparable", ["binance_leak_passed"])    # not established: missing


def test_delayed_entry_is_descriptive(tmp_path):
    s = scenario(tmp_path)
    nominal = f.T0 + 5 * f.MIN
    s.hl.book_fn = lambda coin, now: f.book(coin, now, age_ms=6_000 if now < nominal + 3 * f.MIN else 0)
    detect(s)
    entry = s.rec("entry")
    assert entry["status"] == "delayed" and entry["delay_ms"] > 2 * f.MIN
    rejects = s.mon.ledger.kind("reject")
    assert rejects and {r["reason"] for r in rejects} == {"stale_book"}
    assert cohort(s) == ("descriptive", ["entry_timely"])


def test_hyperliquid_leak_test_is_descriptive_only(tmp_path):
    s = detect(scenario(tmp_path))
    assert s.rec("hlleak")["descriptive"] is True and s.rec("hlleak")["leaked"] is False
    assert "hlleak" not in ur.criteria(ur.view(s.mon.ledger, s.rec("event")))
