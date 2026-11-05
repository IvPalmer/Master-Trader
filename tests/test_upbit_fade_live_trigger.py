"""Upbit fade live pilot (#252): the trigger that turns paper entries into /forceenter calls.

The paper ledger is produced by the real paper monitor on the network-free fakes of
tests/uff_fakes.py; the Freqtrade REST API is an in-memory fake behind urllib's opener.

    python3 -m pytest tests/test_upbit_fade_live_trigger.py -q
"""
import base64
import importlib.util
import io
import json
import socket
import sys
import urllib.error
import urllib.parse

import pytest

import uff_fakes as f

ROOT = f.ROOT
LIVE = ROOT / "research" / "upbit_fade_live"
spec = importlib.util.spec_from_file_location("live_trigger", LIVE / "live_trigger.py")
lt = importlib.util.module_from_spec(spec)
sys.modules["live_trigger"] = lt
spec.loader.exec_module(lt)

BODY = "<p>거래지원 개시 시점 : 2026년 11월 10일 17:00 예정</p>"            # after t0
URL = "http://127.0.0.1:8105"


class Resp(io.BytesIO):
    def __init__(self, status, body):
        super().__init__(body if isinstance(body, bytes) else json.dumps(body).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakeFt:
    """Freqtrade's REST API as urllib's opener: show_config, profit, status, markets,
    forceenter. `enter` is (status, body) or an exception to raise."""

    def __init__(self):
        self.requests = []
        self.config = {"state": "running", "strategy": "UpbitFadeLiveV1", "dry_run": True}
        self.realized = 0.0
        self.open = []
        self.markets = {"CARDS/USDC:USDC": {"symbol": "CARDS/USDC:USDC", "base": "CARDS",
                                            "quote": "USDC", "spot": False, "swap": True,
                                            "active": True}}
        self.enter = (200, {"trade_id": 7, "pair": "CARDS/USDC:USDC", "open_rate": 1.0,
                            "amount": 50.0, "is_short": True})
        self.down = False
        self.clock = None               # wall ms; set by trigger()
        self.fill_after_ms = 400        # the entry order fills this long after submission
        self.trades = {}                # trade id -> /trade/<id> answer
        self.trade_error = None         # an exception or HTTP status for /trade/<id> reads

    def __call__(self, req, timeout):
        url = urllib.parse.urlsplit(req.full_url)
        body = json.loads(req.data) if req.data else None
        self.requests.append({"method": req.get_method(), "path": url.path, "query": url.query,
                              "auth": req.get_header("Authorization"), "body": body,
                              "timeout": timeout})
        if self.down:
            raise urllib.error.URLError(ConnectionRefusedError(111, "refused"))
        path = url.path.removeprefix("/api/v1/")
        if path == "show_config":
            return Resp(200, self.config)
        if path == "profit":
            return Resp(200, {"profit_closed_coin": self.realized})
        if path == "status":
            return Resp(200, self.open)
        if path == "markets":
            q = dict(urllib.parse.parse_qsl(url.query))
            return Resp(200, {"markets": {k: v for k, v in self.markets.items()
                                          if v["base"] == q.get("base")}, "exchange_id": "hyperliquid"})
        if path == "forceenter":
            if isinstance(self.enter, BaseException):
                raise self.enter
            status, payload = self.enter
            if status != 200:
                raise urllib.error.HTTPError(req.full_url, status, "err", {},
                                             io.BytesIO(json.dumps(payload).encode()))
            self.open.append(payload)
            sub = self.clock()
            filled = self.fill_after_ms is not None
            self.trades[payload["trade_id"]] = {"trade_id": payload["trade_id"], "orders": [
                {"order_id": "0xe1", "ft_order_side": "sell", "ft_order_tag": body["entry_tag"],
                 "status": "closed" if filled else "open", "filled": 50.0 if filled else 0.0,
                 "order_timestamp": sub,
                 "order_filled_timestamp": sub + self.fill_after_ms if filled else None},
                {"order_id": "0xs1", "ft_order_side": "stoploss", "ft_order_tag": None,
                 "status": "open", "filled": 0.0, "order_timestamp": sub + 60_000,
                 "order_filled_timestamp": None}]}
            return Resp(200, payload)
        if path.startswith("trade/"):
            if isinstance(self.trade_error, BaseException):
                raise self.trade_error
            if self.trade_error is not None:
                raise urllib.error.HTTPError(req.full_url, self.trade_error, "err", {},
                                             io.BytesIO(b'{"detail": "Trade not found."}'))
            return Resp(200, self.trades[int(path.split("/")[1])])
        raise AssertionError("unexpected request %s" % path)

    def posts(self):
        return [r for r in self.requests if r["path"].endswith("/forceenter")]


def paper(tmp_path, until=5 * f.MIN + 30_000):
    """A real paper ledger: the CARDS listing, run to t0 + 5.5 min (entry written)."""
    s = f.Scenario(tmp_path / "paper", body=BODY)
    s.run(s.t0 - 1000, every_ms=60_000)
    s.publish()
    s.run(s.t0 + until, every_ms=10_000)
    assert s.mon.errors == []
    return s


def trigger(s, tmp_path, ft=None, notes=None):
    ft = ft or FakeFt()
    ft.clock = s.clock.wall_ms
    api = lt.FtApi(URL, "ft_user", "s3cret", opener=ft)
    notes = [] if notes is None else notes
    trig = lt.Trigger(s.data / "ledger.jsonl", tmp_path / "live", api, s.clock.wall_ms,
                      notify=lambda text: notes.append(text) or True)
    trig.recover()
    return trig, ft, notes


def test_a_comparable_paper_entry_is_entered_once_with_the_pilot_order(tmp_path):
    s = paper(tmp_path)
    entry = s.rec("entry")
    assert entry["status"] == "timely"
    trig, ft, notes = trigger(s, tmp_path)
    trig.poll()
    (post,) = ft.posts()
    assert post["method"] == "POST"
    assert post["body"] == {"pair": "CARDS/USDC:USDC", "side": "short", "stakeamount": 50,
                            "leverage": 1.0, "ordertype": "market",
                            "entry_tag": "upbit-fade:%s@%d" % (s.eid(), s.t0 + 7 * f.MIN)}
    res = trig.decisions.get("result:" + s.eid())
    assert res["status"] == "entered" and res["trade_id"] == 7
    intent = trig.decisions.get("intent:" + s.eid())
    assert intent["paper_entry_obs_ms"] == entry["obs_ms"] and intent["bot_dry_run"] is True
    assert intent["at_ms"] <= s.t0 + lt.LATEST_ENTRY_MS
    for _ in range(3):
        trig.poll()
    s.run(s.t0 + 40 * f.MIN)                    # the paper ledger keeps growing (cp30m)
    trig.poll()
    assert len(ft.posts()) == 1 and notes == []


def test_a_restart_never_re_enters_a_decided_event(tmp_path):
    s = paper(tmp_path)
    trig, ft, _ = trigger(s, tmp_path)
    trig.poll()
    again, ft2, _ = trigger(s, tmp_path)       # a new process on the same data dir
    again.poll()
    assert len(ft.posts()) == 1 and ft2.posts() == []


def test_a_crash_between_intent_and_result_is_unknown_and_never_resent(tmp_path):
    s = paper(tmp_path)
    ft = FakeFt()
    ft.enter = KeyboardInterrupt()             # the process dies while the request is out
    trig, _, _ = trigger(s, tmp_path, ft)
    with pytest.raises(KeyboardInterrupt):
        trig.poll()
    assert "intent:" + s.eid() in trig.decisions and "result:" + s.eid() not in trig.decisions
    ft2 = FakeFt()
    again, _, notes = trigger(s, tmp_path, ft2)    # recover() runs at start
    again.poll()
    res = again.decisions.get("result:" + s.eid())
    assert res["status"] == "unknown" and ft2.posts() == []
    assert again.killed() and "kill switch engaged" in notes[0]


def test_a_timed_out_forceenter_is_unknown_and_engages_the_kill_switch(tmp_path):
    s = paper(tmp_path)
    ft = FakeFt()
    ft.enter = urllib.error.URLError(socket.timeout("timed out"))
    trig, _, notes = trigger(s, tmp_path, ft)
    trig.poll()
    trig.poll()
    assert len(ft.posts()) == 1
    assert trig.decisions.get("result:" + s.eid())["status"] == "unknown"
    assert trig.killed() and json.loads(trig.kill_path.read_text())["reason"].startswith(
        "forceenter outcome unknown")
    assert any("kill switch engaged" in n for n in notes)


# --- #252 review, P1 1: the pause for an ambiguous entry is durable -------------------------

def test_a_crash_while_pausing_for_an_unknown_outcome_still_pauses_after_restart(tmp_path,
                                                                                monkeypatch):
    """The process dies while it engages the pause for a timed-out /forceenter. The restart
    must be paused and must not resend, whatever was already on disk."""
    s = paper(tmp_path)
    ft = FakeFt()
    ft.enter = urllib.error.URLError(socket.timeout("timed out"))
    trig, _, _ = trigger(s, tmp_path, ft)
    real = lt.Trigger.engage_kill

    def crash(self, reason):
        raise KeyboardInterrupt("power cut while pausing")

    monkeypatch.setattr(lt.Trigger, "engage_kill", crash)
    with pytest.raises(KeyboardInterrupt):
        trig.poll()
    monkeypatch.setattr(lt.Trigger, "engage_kill", real)
    ft2 = FakeFt()
    again, _, _ = trigger(s, tmp_path, ft2)
    again.tick()
    assert again.killed() and again.kill_path.exists()
    assert again.decisions.get("result:" + s.eid())["status"] == "unknown"
    assert ft2.posts() == [] and len(ft.posts()) == 1


def test_removing_the_pause_file_without_a_reconciliation_does_not_resume(tmp_path):
    s = paper(tmp_path)
    ft = FakeFt()
    ft.enter = urllib.error.URLError(socket.timeout("timed out"))
    trig, _, _ = trigger(s, tmp_path, ft)
    trig.poll()
    trig.kill_path.unlink()
    assert trig.killed() and trig.unresolved() == [s.eid()]
    trig.tick()                                  # every loop puts the file back
    assert trig.kill_path.exists()
    trig.kill_path.unlink()
    again, _, _ = trigger(s, tmp_path, FakeFt())  # and so does a restart
    assert again.killed() and again.kill_path.exists()


def test_reconcile_records_the_checked_outcome_then_the_file_can_go(tmp_path, capsys):
    s = paper(tmp_path)
    ft = FakeFt()
    ft.enter = urllib.error.URLError(socket.timeout("timed out"))
    trig, _, _ = trigger(s, tmp_path, ft)
    trig.poll()
    live = str(tmp_path / "live")
    args = ["--data-dir", live, "reconcile", s.eid(), "--by", "palmer", "--note", "no trade on HL"]
    assert lt.main(args[:4] + ["--outcome", "entered"] + args[4:]) == 2      # needs --trade-id
    with lt.process_lock(live):                                             # service running
        assert lt.main(args[:4] + ["--outcome", "not_entered"] + args[4:]) == 3
    assert lt.main(args[:4] + ["--outcome", "not_entered"] + args[4:]) == 0
    assert lt.main(args[:4] + ["--outcome", "not_entered"] + args[4:]) == 2  # once only
    again, ft2, _ = trigger(s, tmp_path, FakeFt())
    rec = again.decisions.get("reconcile:" + s.eid())
    assert rec["outcome"] == "not_entered" and rec["by"] == "palmer"
    assert again.unresolved() == [] and again.killed()                      # the file stays
    again.kill_path.unlink()
    again.tick()
    assert not again.killed() and ft2.posts() == []                         # never resent
    capsys.readouterr()
    assert lt.main(["--data-dir", live, "status"]) == 0
    out = capsys.readouterr().out
    assert "unreconciled unknown outcomes: none" in out and "reconciled " + s.eid() in out


def test_a_failed_write_halts_every_further_entry(tmp_path, monkeypatch):
    s = paper(tmp_path)
    trig, ft, _ = trigger(s, tmp_path)
    real = trig.decisions.append
    calls = []

    def flaky(rec):
        calls.append(rec["rid"])
        if len(calls) == 1:
            raise OSError(28, "No space left on device")
        return real(rec)

    monkeypatch.setattr(trig.decisions, "append", flaky)
    with pytest.raises(OSError):
        trig.poll()                              # the intent could not be written
    assert trig.halted and trig.killed() and trig.kill_path.exists()
    trig.poll()                                  # the disk is back: still no entry
    assert ft.posts() == []
    assert trig.decisions.get("skip:" + s.eid())["reason"] == "kill_switch"


# --- #252 review, P1 4: the loss limit is latched every loop ------------------------------

def test_the_loss_limit_is_latched_every_loop_without_a_paper_event(tmp_path):
    ft = FakeFt()
    api = lt.FtApi(URL, "ft_user", "s3cret", opener=ft)
    trig = lt.Trigger(tmp_path / "no-paper" / "ledger.jsonl", tmp_path / "live", api,
                      lambda: 1_800_000_000_000)
    trig.recover()
    trig.tick()
    assert not trig.killed()
    ft.realized = -75.01
    trig.tick()
    assert trig.killed() and trig.kill_path.exists()
    assert trig.decisions.kind("kill")[0]["reason"].startswith("cumulative realized pilot P&L -75.01")
    assert ft.posts() == []


# --- #252 review round 2: submission and fill timing are measured -----------------------

def test_entry_timing_is_recorded_against_t0(tmp_path):
    s = paper(tmp_path)
    trig, ft, _ = trigger(s, tmp_path)
    trig.tick()                                  # enters
    trig.tick()                                  # reads the entry order back
    t = trig.decisions.get("timing:" + s.eid())
    intent = trig.decisions.get("intent:" + s.eid())
    assert t["defect"] is False and t["order_id"] == "0xe1" and t["trade_id"] == 7
    assert t["submitted_ms"] == intent["at_ms"] and t["filled_ms"] == intent["at_ms"] + 400
    assert t["fill_after_t0_s"] == (intent["at_ms"] + 400 - s.t0) / 1000
    assert t["fill_after_paper_entry_s"] == (intent["at_ms"] + 400 - intent["paper_entry_obs_ms"]) / 1000
    assert t["fill_limit_ms"] == s.t0 + 10 * f.MIN and not trig.killed()
    reads = [r for r in ft.requests if r["path"].endswith("/trade/7")]
    trig.tick()
    assert len([r for r in ft.requests if r["path"].endswith("/trade/7")]) == len(reads)


def test_a_fill_after_t0_plus_10_min_pauses_the_pilot(tmp_path):
    s = paper(tmp_path)
    ft = FakeFt()
    ft.fill_after_ms = 10 * f.MIN               # Freqtrade's margin/leverage retries ran long
    trig, _, notes = trigger(s, tmp_path, ft)
    trig.tick()
    trig.tick()
    t = trig.decisions.get("timing:" + s.eid())
    assert t["defect"] is True and t["filled_ms"] > s.t0 + lt.FILL_DEFECT_MS
    assert trig.killed() and trig.kill_path.exists()
    assert "execution defect" in json.loads(trig.kill_path.read_text())["reason"]
    assert any("execution defect" in n for n in notes)


def test_no_fill_by_t0_plus_10_min_pauses_the_pilot(tmp_path):
    s = paper(tmp_path)
    ft = FakeFt()
    ft.fill_after_ms = None
    trig, _, _ = trigger(s, tmp_path, ft)
    trig.tick()
    trig.tick()
    assert "timing:" + s.eid() not in trig.decisions and not trig.killed()   # still in time
    s.clock.to(s.t0 + lt.FILL_DEFECT_MS + 1)
    trig.tick()
    t = trig.decisions.get("timing:" + s.eid())
    assert t["defect"] is True and t["filled_ms"] is None and t["order_status"] == "open"
    assert trig.killed()


@pytest.mark.parametrize("error", [500, 404, urllib.error.URLError(socket.timeout("timed out"))])
def test_an_unreadable_trade_past_t0_plus_10_min_pauses_the_pilot(tmp_path, error):
    """Codex round 3: with every trade-detail read failing, nothing paused at t0 + 700 s."""
    s = paper(tmp_path)
    ft = FakeFt()
    ft.trade_error = error
    trig, _, notes = trigger(s, tmp_path, ft)
    trig.tick()                                  # enters; the read-back fails
    trig.tick()
    assert "timing:" + s.eid() not in trig.decisions and not trig.killed()   # still in time
    s.clock.to(s.t0 + 700_000)
    trig.tick()
    t = trig.decisions.get("timing:" + s.eid())
    assert t["defect"] is True and t["filled_ms"] is None and t["read_error"]
    assert trig.killed() and trig.kill_path.exists()
    assert "trade unreadable" in json.loads(trig.kill_path.read_text())["reason"]
    assert any("execution defect" in n for n in notes)


def test_a_trade_without_its_entry_order_past_t0_plus_10_min_pauses_the_pilot(tmp_path):
    s = paper(tmp_path)
    trig, ft, _ = trigger(s, tmp_path)
    trig.tick()
    ft.trades[7]["orders"] = [o for o in ft.trades[7]["orders"] if o["ft_order_side"] == "stoploss"]
    s.clock.to(s.t0 + 700_000)
    trig.tick()
    t = trig.decisions.get("timing:" + s.eid())
    assert t["defect"] is True and t["order_id"] is None and trig.killed()
    assert "no entry order" in json.loads(trig.kill_path.read_text())["reason"]


def test_a_reconciled_entry_is_measured_too(tmp_path):
    s = paper(tmp_path)
    ft = FakeFt()
    ft.enter = urllib.error.URLError(socket.timeout("timed out"))
    trig, _, _ = trigger(s, tmp_path, ft)
    trig.poll()
    live = str(tmp_path / "live")
    assert lt.main(["--data-dir", live, "reconcile", s.eid(), "--outcome", "entered",
                    "--trade-id", "7", "--by", "palmer", "--note", "trade 7 on HL"]) == 0
    ft2 = FakeFt()
    ft2.clock = s.clock.wall_ms
    ft2.trades[7] = {"trade_id": 7, "orders": [
        {"order_id": "0xe9", "ft_order_side": "sell",
         "ft_order_tag": trig.decisions.get("intent:" + s.eid())["entry_tag"], "status": "closed",
         "filled": 50.0, "order_timestamp": s.t0 + 5 * f.MIN + 20_000,
         "order_filled_timestamp": s.t0 + 5 * f.MIN + 21_000}]}
    again, _, _ = trigger(s, tmp_path, ft2)
    again.tick()
    t = again.decisions.get("timing:" + s.eid())
    assert t["order_id"] == "0xe9" and t["fill_after_t0_s"] == 321.0 and t["defect"] is False


def test_max_open_asks_the_bot_and_skips(tmp_path):
    s = paper(tmp_path)
    ft = FakeFt()
    ft.open = [{"trade_id": 1, "pair": "AAA/USDC:USDC"}, {"trade_id": 2, "pair": "BBB/USDC:USDC"}]
    trig, _, notes = trigger(s, tmp_path, ft)
    trig.poll()
    assert ft.posts() == []
    skip = trig.decisions.get("skip:" + s.eid())
    assert skip["reason"] == "max_open" and skip["open_trades"] == 2
    assert any("max_open" in n for n in notes)
    assert any(r["path"].endswith("/status") for r in ft.requests)


def test_the_kill_switch_file_stops_entries_without_touching_the_bot(tmp_path):
    s = paper(tmp_path)
    trig, ft, _ = trigger(s, tmp_path)
    trig.kill_path.parent.mkdir(parents=True, exist_ok=True)
    trig.kill_path.write_text("operator\n")
    trig.poll()
    assert ft.requests == []
    assert trig.decisions.get("skip:" + s.eid())["reason"] == "kill_switch"


def test_realized_pnl_at_the_limit_engages_the_kill_switch(tmp_path):
    s = paper(tmp_path)
    ft = FakeFt()
    ft.realized = -75.0
    trig, _, _ = trigger(s, tmp_path, ft)
    trig.poll()
    assert ft.posts() == [] and trig.killed()
    assert trig.decisions.get("skip:" + s.eid())["reason"] == "kill_pnl"
    assert trig.decisions.kind("kill")[0]["reason"].startswith("cumulative realized pilot P&L -75.00")


def test_a_stale_record_is_skipped_no_later_than_t0_plus_7_min(tmp_path):
    s = paper(tmp_path)
    s.clock.to(s.t0 + lt.LATEST_ENTRY_MS + 1)  # the trigger was down through the window
    trig, ft, notes = trigger(s, tmp_path)
    trig.poll()
    assert ft.requests == [] and notes == []
    skip = trig.decisions.get("skip:" + s.eid())
    assert skip["reason"] == "stale" and skip["cutoff_ms"] == s.t0 + 7 * f.MIN


def test_an_unavailable_pair_is_skipped_and_logged(tmp_path):
    s = paper(tmp_path)
    ft = FakeFt()
    ft.markets = {}
    trig, _, notes = trigger(s, tmp_path, ft)
    trig.poll()
    assert ft.posts() == []
    skip = trig.decisions.get("skip:" + s.eid())
    assert skip["reason"] == "unavailable_pair" and skip["pair"] == "CARDS/USDC:USDC"
    assert any("not an active perp" in n for n in notes)
    (q,) = [r["query"] for r in ft.requests if r["path"].endswith("/markets")]
    assert dict(urllib.parse.parse_qsl(q)) == {"base": "CARDS", "quote": "USDC"}


def test_freqtrade_rejecting_the_symbol_is_final_and_never_retried(tmp_path):
    s = paper(tmp_path)
    ft = FakeFt()
    ft.enter = (502, {"error": "Error querying /api/v1/forceenter: Symbol does not exist or "
                               "market is not active."})
    trig, _, _ = trigger(s, tmp_path, ft)
    trig.poll()
    trig.poll()
    assert len(ft.posts()) == 1 and not trig.killed()
    assert trig.decisions.get("result:" + s.eid())["status"] == "unavailable_pair"


def test_other_freqtrade_rejections_are_final(tmp_path):
    s = paper(tmp_path)
    ft = FakeFt()
    ft.enter = (502, {"error": "Error querying /api/v1/forceenter: Maximum number of trades "
                               "is reached."})
    trig, _, notes = trigger(s, tmp_path, ft)
    trig.poll()
    trig.poll()
    res = trig.decisions.get("result:" + s.eid())
    assert res["status"] == "rejected" and "Maximum number" in res["error"]
    assert len(ft.posts()) == 1 and notes and not trig.killed()


def test_an_unreachable_bot_is_retried_until_the_window_closes(tmp_path):
    s = paper(tmp_path, until=5 * f.MIN + 10_000)
    ft = FakeFt()
    ft.down = True
    trig, _, notes = trigger(s, tmp_path, ft)
    trig.poll()
    assert not trig.decided(s.eid())
    ft.down = False
    trig.poll()
    assert trig.decisions.get("result:" + s.eid())["status"] == "entered"
    ft2 = FakeFt()
    ft2.down = True
    s2 = paper(tmp_path / "b")
    t2, _, notes2 = trigger(s2, tmp_path / "b", ft2)
    t2.poll()
    s2.clock.to(s2.t0 + lt.LATEST_ENTRY_MS + 1)
    t2.poll()
    skip = t2.decisions.get("skip:" + s2.eid())
    assert skip["reason"] == "stale" and skip["waited_for"].startswith("bot unreachable")
    assert ft2.posts() == [] and any("missed" in n for n in notes2)


def test_requirements_not_yet_established_wait_and_never_trade_unknowns(tmp_path):
    """USD-M klines answer 500: the Binance requirements stay unestablished, so the paper
    keeps the event comparable with a missing outcome; the pilot does not trade it."""
    s = f.Scenario(tmp_path / "paper", body=BODY)
    s.http.klines[("um", "CARDSUSDT")] = 500
    s.run(s.t0 - 1000, every_ms=60_000)
    s.publish()
    s.run(s.t0 + 5 * f.MIN + 30_000, every_ms=10_000)
    assert s.rec("entry")["status"] == "timely" and s.rec("binance") is None
    trig, ft, _ = trigger(s, tmp_path)
    trig.poll()
    assert ft.requests == [] and not trig.decided(s.eid())
    s.clock.to(s.t0 + lt.LATEST_ENTRY_MS + 1)
    trig.poll()
    skip = trig.decisions.get("skip:" + s.eid())
    assert skip["reason"] == "stale" and "binance_market_pre_t0" in skip["waited_for"]


def test_a_descriptive_event_is_never_entered(tmp_path):
    """A Binance pre-t0 drift above 2% (the leak test) makes the event descriptive."""
    s = f.Scenario(tmp_path / "paper", body=BODY)
    t0 = s.t0
    s.http.klines[("um", "CARDSUSDT")] = lambda t: "1.0" if t < t0 - 5 * f.MIN else "1.05"
    s.run(s.t0 - 1000, every_ms=60_000)
    s.publish()
    s.run(s.t0 + 5 * f.MIN + 30_000, every_ms=10_000)
    assert s.rec("binance")["leaked"] is True and s.rec("entry") is not None
    trig, ft, _ = trigger(s, tmp_path)
    trig.poll()
    skip = trig.decisions.get("skip:" + s.eid())
    assert skip["reason"] == "not_comparable" and skip["cohort"] == "descriptive"
    assert ft.requests == []


def test_a_bot_answering_for_another_strategy_is_refused(tmp_path):
    s = paper(tmp_path)
    ft = FakeFt()
    ft.config["strategy"] = "KillersScalpV1"
    trig, _, _ = trigger(s, tmp_path, ft)
    trig.poll()
    assert ft.posts() == [] and trig.killed()
    assert trig.decisions.get("skip:" + s.eid())["reason"] == "wrong_bot"


def test_every_request_carries_basic_auth_to_the_loopback_bot(tmp_path):
    s = paper(tmp_path)
    trig, ft, _ = trigger(s, tmp_path)
    trig.poll()
    expected = "Basic " + base64.b64encode(b"ft_user:s3cret").decode()
    assert ft.requests and all(r["auth"] == expected for r in ft.requests)
    assert {r["path"].rsplit("/", 1)[0] for r in ft.requests} == {"/api/v1"}
    assert lt.basic_auth("a", "b") == "Basic YTpi"
    for bad in ("http://10.0.0.5:8105", "http://ft-upbit-fade-hl:8080", "https://example.com"):
        with pytest.raises(ValueError):
            lt.FtApi(bad, "u", "p")
    for host in ("http://localhost:8105", "http://[::1]:8105"):
        lt.FtApi(host, "u", "p")
    with pytest.raises(ValueError):
        lt.FtApi(URL, "", "p")
    with pytest.raises(ValueError):
        lt.Notifier("http://198.51.100.1:8088/test/notify", "t")


def test_the_notifier_sends_the_token_and_never_raises(tmp_path):
    sent = []

    def opener(req, timeout):
        sent.append((req.full_url, req.get_header("X-notify-token"), json.loads(req.data)))
        return Resp(200, {"ok": True})

    n = lt.Notifier("http://127.0.0.1:8088/test/notify", "tok", opener=opener)
    assert n("hello") is True
    assert sent == [("http://127.0.0.1:8088/test/notify", "tok", {"text": "[upbit-fade-live] hello"})]

    def broken(req, timeout):
        raise OSError("down")

    assert lt.Notifier("http://127.0.0.1:8088/test/notify", "", opener=broken)("x") is False
    assert lt.Notifier(None, None)("x") is False


def test_hyperliquid_k_prefixed_coins_map_to_the_ccxt_symbol(tmp_path):
    assert lt.ft_pair("kPEPE") == "KPEPE/USDC:USDC"
    assert lt.ft_pair("CARDS") == "CARDS/USDC:USDC"


def test_the_trigger_reads_the_paper_ledger_and_never_writes_it(tmp_path):
    s = paper(tmp_path)
    before = {p.name: p.read_bytes() for p in s.data.iterdir()}
    trig, _, _ = trigger(s, tmp_path)
    trig.poll()
    assert {p.name: p.read_bytes() for p in s.data.iterdir()} == before
    assert (tmp_path / "live" / "decisions.jsonl").exists()


def test_status_lists_intents_and_the_kill_switch(tmp_path, capsys):
    s = paper(tmp_path)
    trig, _, _ = trigger(s, tmp_path)
    trig.poll()
    assert lt.main(["--data-dir", str(tmp_path / "live"), "status"]) == 0
    out = capsys.readouterr().out
    assert "kill switch: off" in out and '"entered": 1' in out and s.eid() in out


def test_the_unit_has_the_monitor_caps_and_no_bytecode():
    def directives(path):
        return {line.split("=", 1)[0]: line.split("=", 1)[1] for line in path.read_text().splitlines()
                if "=" in line and not line.startswith("#")}

    unit = directives(LIVE / "upbit-fade-live-trigger.service")
    monitor = directives(ROOT / "research" / "upbit_fade_forward" / "upbit-fade-forward.service")
    for key in ("MemoryMax", "CPUQuota", "Nice", "IOSchedulingClass", "Restart", "RestartSec",
                "StartLimitIntervalSec", "StartLimitBurst"):
        assert unit[key] == monitor[key], key
    assert unit["Environment"] == "PYTHONDONTWRITEBYTECODE=1"
    assert unit["ExecStart"].startswith("/usr/bin/python3 -B ")
    assert unit["ExecStart"].endswith("research/upbit_fade_live/live_trigger.py run")
    assert unit["EnvironmentFile"] == "%h/.config/upbit-fade-live/trigger.env"
    assert (LIVE / ".gitignore").read_text().split() == ["data/"]
    example = (LIVE / "trigger.env.example").read_text()
    for line in example.splitlines():
        if line.startswith(("FT_API_USER=", "FT_API_PASS=", "TRADE_WEBHOOK_NOTIFY_TOKEN=")):
            assert line.endswith("="), "the template must not carry a credential"
