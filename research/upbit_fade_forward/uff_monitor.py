"""The forward monitor loop (#229): detection, eligibility at t0, paper fills, funding, decision.

One process, one sequential loop, no threads, like news-archive. Each tick runs the
time-critical steps first (archive read, Hyperliquid eligibility, entry, marks, exit, the
hourly oracle observation), then the history reads (Binance klines, the Binance-prior
re-check, Hyperliquid candles and funding records), the market audit and the decision.

Every outcome is a ledger record with a deterministic rid, so a restart replays the ledger
and resumes: an action whose deadline passed while the process was down is recorded
`missing`, and a later recovery is a separate `late` record. state.json only holds the archive
cursors; without it the epoch cursors are used and the idempotent ledger absorbs the replay.
It places no orders and holds no keys.
"""
import json
from contextlib import closing
from decimal import Decimal
from pathlib import Path

import uff_common as uc
import uff_detect as ud
import uff_ledger as ul
import uff_report as ur
import uff_venues as uv
import nes_returns as nr
import nes_util as nu
import nes_venues as nv

ORACLE_RETRY_MS = 5_000


class Monitor:
    def __init__(self, data_dir, archive_path, hl, http, wall_ms, sleep, log=None):
        self.data_dir = Path(data_dir)
        self.archive_path = str(archive_path)
        self.hl, self.http = hl, http
        self.wall_ms, self.sleep = wall_ms, sleep
        self.log = log or (lambda msg: None)
        self.errors = []
        self.ledger = ul.Ledger(self.data_dir / "ledger.jsonl")
        self.markets = ul.Ledger(self.data_dir / "upbit_markets.jsonl")
        self.state_path = self.data_dir / "state.json"
        self.cursor = self._load_cursor()
        self._next = {}
        self._last_archive = None
        polls = self.markets.kind("market_poll")
        self._last_poll = polls[-1] if polls else None
        self._rejects = {}
        for r in self.ledger.kind("reject"):
            self._rejects[r["of"]] = max(self._rejects.get(r["of"], 0), r["n"])
        self._seen = {r["notice_id"]: r["content"] for r in self.ledger.kind("seen")}

    # --- plumbing ------------------------------------------------------------------------

    def _load_cursor(self):
        ep = self.ledger.get("epoch")
        if ep is None:
            return None
        cur = {"items_pk": ep["items_pk"], "rev_pk": ep["rev_pk"]}
        try:
            saved = json.loads(self.state_path.read_text())
        except (FileNotFoundError, ValueError):
            return cur
        return {k: max(cur[k], int(saved.get(k, 0))) for k in cur}

    def _save_cursor(self):
        nu.write_atomic(self.state_path, json.dumps({**self.cursor, "saved_ms": self.wall_ms()},
                                                    sort_keys=True).encode())

    def _due(self, key, gap_ms):
        now = self.wall_ms()
        if now < self._next.get(key, 0):
            return False
        self._next[key] = now + gap_ms
        return True

    def _append(self, rec):
        rec.setdefault("at_ms", self.wall_ms())
        return self.ledger.append(rec)

    def tick(self):
        for step in (self._poll_archive, self._critical, self._oracle, self._poll_upbit,
                     self._history, self._audit, self._decide):
            try:
                step()
            except Exception as e:  # noqa: BLE001 - the loop must never die
                msg = "%s failed: %s: %s" % (step.__name__, type(e).__name__, e)
                self.errors.append(msg)
                self.log(msg)

    def _events(self):
        return [e for e in self.ledger.kind("event") if not e.get("pre_epoch")]

    # --- detection -----------------------------------------------------------------------

    def _poll_archive(self):
        now = self.wall_ms()
        if self._last_archive is not None and now - self._last_archive < uc.ARCHIVE_POLL_MS:
            return
        self._last_archive = now
        if not Path(self.archive_path).exists():
            raise FileNotFoundError(self.archive_path)
        with closing(ud.open_archive(self.archive_path)) as conn:
            if self.cursor is None:
                top = ud.bounds(conn)
                self._append({"rid": "epoch", "kind": "epoch", "start_ms": now,
                              "start": uc.iso(now), "prereg": uc.PREREG_ID, **top})
                self.cursor = dict(top)
                self._save_cursor()
                self.log("epoch %s: archive cursors %s" % (uc.iso(now), top))
                return
            notices, top = ud.read_new(conn, self.cursor)
            for n in notices:
                self._notice(conn, n)
            if top != self.cursor:
                self.cursor = top
                self._save_cursor()

    def _notice(self, conn, n):
        now = self.wall_ms()
        cls = ud.classify(n.title, n.body)
        content = nu.sha256_bytes(json.dumps([n.title, n.body], ensure_ascii=False).encode())
        if self._seen.get(n.notice_id) != content:
            self._seen[n.notice_id] = content
            self._append({"rid": "seen:" + n.ref, "kind": "seen", "notice_id": n.notice_id,
                          "ref": n.ref, "title": n.title, "has_body": bool(n.body),
                          "published_at": n.published_at, "received_at": n.received_at,
                          "detected_ms": now, "class": cls, "content": content})
        if cls["kind"] == "addition":
            for token, krw in cls["krw"].items():
                if krw is True:
                    self._event(conn, n, token, now)
                elif krw is None:
                    self._unclassified(n, "market_unstated", now, token)
        elif cls["kind"] == "unclassified":
            self._unclassified(n, "no_classifier_match", now)

    def _unclassified(self, n, reason, now, token=None):
        rid = "unclassified:%s%s" % (n.notice_id, ":" + token if token else "")
        if self._append({"rid": rid, "kind": "unclassified", "notice_id": n.notice_id,
                         "token": token, "ref": n.ref, "title": n.title, "reason": reason,
                         "published_at": n.published_at, "received_at": n.received_at,
                         "detected_ms": now}):
            self.log("unclassified Upbit notice %s (%s): %s" % (n.notice_id, reason, n.title))

    def _event(self, conn, n, token, now):
        eid = "upbit:%s:%s" % (n.notice_id, token)
        if "event:" + eid in self.ledger:
            return
        t0, timing, why = ud.timing(n.published_at, n.received_at)
        start = ud.trading_start(n.body, token, t0, n.title)
        krw, snapshot = self._krw_prior(token, t0)
        rec = {"rid": "event:" + eid, "kind": "event", "event_id": eid,
               "announcement_id": "upbit:" + n.notice_id, "notice_id": n.notice_id,
               "token": token, "title": n.title, "has_body": bool(n.body), "ref": n.ref,
               "item_pk": n.item_pk, "published_at": n.published_at,
               "received_at": n.received_at, "t0_ms": t0, "t0": uc.iso(t0), "clock": "tree",
               "detected_ms": now, "detected_at": uc.iso(now), "timing": timing,
               "timing_reason": why, "trading_start_ms": start,
               "began_before_notice": start is not None and start < t0,
               "krw_prior": krw, "krw_snapshot_ms": snapshot,
               "binance_prior": ud.binance_prior(conn, token, t0), "pit": ud.pit(conn, n),
               "pre_epoch": t0 < self.ledger.get("epoch")["start_ms"]}
        self._append(rec)
        self.log("event %s: t0 %s (%s), detected %s, krw_prior %s, excluded %s" % (
            eid, rec["t0"], timing, rec["detected_at"], krw, ur.detection_exclusions(rec) or "no"))

    def _krw_prior(self, token, t0):
        """Whether KRW-<token> is in the last market/all snapshot before t0 (15 min at most)."""
        last = None
        for p in self.markets.kind("market_poll"):
            if p["obs_ms"] >= t0:
                break
            last = p
        if last is None or t0 - last["obs_ms"] > uc.KRW_SNAPSHOT_MAX_AGE_MS:
            return "unknown", last and last["obs_ms"]
        return ("KRW-" + token) in self.markets.get("set:" + last["sha256"])["markets"], last["obs_ms"]

    # --- time-critical steps -------------------------------------------------------------

    def _critical(self):
        for ev in self._events():
            eid = ev["event_id"]
            if self.ledger.get("hl:" + eid) is None:
                self._hl_facts(ev)
            hl = self.ledger.get("hl:" + eid)
            if hl is None or hl["status"] != "eligible" or ur.detection_exclusions(ev):
                continue
            if self.ledger.get("entry:" + eid) is None:
                self._entry(ev, hl)
            entry = self.ledger.get("entry:" + eid)
            if not ur.filled(entry):
                continue
            q = Decimal(entry["q"])
            for name, offset in uc.CHECKPOINTS:
                self._book_action(name, ev, hl, entry["obs_ms"] + offset, q)
            self._book_action("exit", ev, hl, entry["obs_ms"] + uc.HOLD_MS, q)

    def _hl_facts(self, ev):
        """Part C Hyperliquid eligibility (nes_venues.hl_facts), plus: the perp is in today's meta.
        An unknown answer is retried until the entry deadline."""
        eid, t0 = ev["event_id"], ev["t0_ms"]
        if not self._due("hl:" + eid, uc.ATTEMPT_GAP_MS):
            return
        meta, index = None, {}
        try:
            meta = self.hl.meta()
            index = nv.hl_meta_index(meta)
            facts = nv.hl_facts(ev["token"], t0, index, self.hl)
        except (nv.VenueAborted, ValueError) as e:
            facts = {"status": "unknown", "coin": ev["token"], "reason": "fetch_failed: %s" % e}
        if facts["status"] == "unknown" and self.wall_ms() <= t0 + uc.ENTRY_OFFSET_MS + uc.DEADLINE_MS:
            return
        coin = facts["coin"]
        hit = index.get(coin.upper())
        in_meta = hit is not None and not hit["delisted"]
        if facts["status"] == "eligible" and not in_meta:
            facts = {**facts, "status": "ineligible", "reason": "not_in_meta"}
        self._append({"rid": "hl:" + eid, "kind": "hl", "event_id": eid, **facts,
                      "in_meta": in_meta, "names": nv.hl_names(ev["token"], index),
                      "sz_decimals": uv.sz_decimals(meta, coin) if in_meta else None})

    def _walk(self, hl, side, q=None, notional=None):
        if hl.get("sz_decimals") is None:
            return None, "no_sz_decimals"
        try:
            book = self.hl.book(hl["coin"])
        except ValueError:
            return None, "fetch_failed"
        return uv.fill(book, side, q=q, notional=notional, decimals=hl["sz_decimals"])

    def _reject(self, rid, eid, why):
        n = self._rejects.get(rid, 0) + 1
        self._rejects[rid] = n
        self._append({"rid": "reject:%s:%d" % (rid, n), "kind": "reject", "of": rid,
                      "event_id": eid, "n": n, "reason": why})

    def _missing(self, rid, kind, eid, nominal, deadline, reason):
        self._append({"rid": rid, "kind": kind, "event_id": eid, "status": "missing",
                      "nominal_ms": nominal, "deadline_ms": deadline,
                      "attempts": self._rejects.get(rid, 0), "reason": reason})
        self.log("%s missing: %s" % (rid, reason))

    def _entry(self, ev, hl):
        """Sell about 100 USDC into the bids at max(t0 + 5 min, detection), freezing q."""
        eid, t0 = ev["event_id"], ev["t0_ms"]
        rid = "entry:" + eid
        nominal = t0 + uc.ENTRY_OFFSET_MS
        deadline = nominal + uc.DEADLINE_MS
        now = self.wall_ms()
        if now > deadline:
            late = " (detected after it)" if ev["detected_ms"] > deadline else ""
            return self._missing(rid, "entry", eid, nominal, deadline, "deadline passed" + late)
        if now < max(nominal, ev["detected_ms"]) or not self._due(rid, uc.ATTEMPT_GAP_MS):
            return None
        rec, why = self._walk(hl, "sell", notional=uc.NOTIONAL_USDC)
        if rec is not None and rec["obs_ms"] > deadline:
            rec, why = None, "after_deadline"
        if rec is None:
            return self._reject(rid, eid, why)
        delay = rec["obs_ms"] - nominal
        self._append({"rid": rid, "kind": "entry", "event_id": eid, "coin": hl["coin"],
                      "status": "timely" if delay <= uc.TIMELY_MS else "delayed",
                      "nominal_ms": nominal, "deadline_ms": deadline, "delay_ms": delay,
                      "attempts": self._rejects.get(rid, 0) + 1, **rec})
        self.log("%s: sold %s %s at %s (delay %.0f s)" % (rid, rec["q"], hl["coin"], rec["vwap"],
                                                          delay / 1000))
        return None

    def _book_action(self, name, ev, hl, nominal, q):
        """A mark (cp30m, cp4h) or the exit: buy back q from the asks within the deadline;
        after a missed deadline, one `late` mark is kept separately."""
        eid = ev["event_id"]
        rid = "%s:%s" % (name, eid)
        deadline = nominal + uc.DEADLINE_MS
        now = self.wall_ms()
        if rid not in self.ledger:
            if now < nominal:
                return
            if now <= deadline:
                if not self._due(rid, uc.ATTEMPT_GAP_MS):
                    return
                rec, why = self._walk(hl, "buy", q=q)
                if rec is not None and rec["obs_ms"] > deadline:
                    rec, why = None, "after_deadline"
                if rec is None:
                    self._reject(rid, eid, why)
                    return
                self._append({"rid": rid, "kind": name, "event_id": eid, "status": "ok",
                              "nominal_ms": nominal, "deadline_ms": deadline,
                              "delay_ms": rec["obs_ms"] - nominal,
                              "attempts": self._rejects.get(rid, 0) + 1, **rec})
                return
            self._missing(rid, name, eid, nominal, deadline, "deadline passed")
        if self.ledger.get(rid)["status"] != "missing":
            return
        lrid = "late:%s:%s" % (name, eid)
        if lrid in self.ledger or now > deadline + uc.LATE_TRY_MS or not self._due(lrid, uc.RETRY_GAP_MS):
            return
        rec, _ = self._walk(hl, "buy", q=q)
        if rec is not None:
            self._append({"rid": lrid, "kind": "late", "action": name, "event_id": eid,
                          "status": "late", "nominal_ms": nominal,
                          "late_by_ms": rec["obs_ms"] - nominal, **rec})

    def _oracle(self):
        """oraclePx of every open position's coin within 60 s after each funding hour."""
        now = self.wall_ms()
        hour = now // uc.HOUR_MS * uc.HOUR_MS
        rid = "oracle:%d" % hour
        if now - hour > uc.ORACLE_TOL_MS or rid in self.ledger:
            return
        coins = set()
        for ev in self._events():
            eid = ev["event_id"]
            entry, ex = self.ledger.get("entry:" + eid), self.ledger.get("exit:" + eid)
            if ur.filled(entry) and entry["obs_ms"] < hour and (
                    ex is None or (ur.filled(ex) and ex["obs_ms"] >= hour)):
                coins.add(entry["coin"])
        if not coins or not self._due(rid, ORACLE_RETRY_MS):
            return
        try:
            px, obs = self.hl.oracle_prices(coins)
        except ValueError:
            return
        if abs(obs - hour) <= uc.ORACLE_TOL_MS:
            self._append({"rid": rid, "kind": "oracle", "hour_ms": hour, "hour": uc.iso(hour),
                          "obs_ms": obs, "coins": sorted(coins), "px": px})

    # --- history reads ---------------------------------------------------------------------

    def _history(self):
        now = self.wall_ms()
        for ev in self._events():
            eid, t0 = ev["event_id"], ev["t0_ms"]
            if self.ledger.get("binance:" + eid) is None:
                self._binance(ev)
            if self.ledger.get("bprior:" + eid) is None and now >= t0 + uc.BINANCE_FINAL_MS:
                self._bprior(ev)
            hl = self.ledger.get("hl:" + eid)
            if hl is None or hl["status"] != "eligible":
                continue
            if self.ledger.get("hlleak:" + eid) is None:
                self._hl_leak(ev, hl)
            entry, ex = self.ledger.get("entry:" + eid), self.ledger.get("exit:" + eid)
            if ur.filled(entry) and ur.filled(ex):
                if self.ledger.get("funding:" + eid) is None:
                    self._funding(ev, hl, entry, ex)
                if self.ledger.get("excursion:" + eid) is None:
                    self._excursion(ev, hl, entry, ex)

    def _binance(self, ev):
        eid = ev["event_id"]
        if not self._due("binance:" + eid, uc.RETRY_GAP_MS):
            return
        facts = uv.binance_facts(ev["token"], ev["t0_ms"], self.http, self.sleep)
        if facts is None:
            if self.wall_ms() <= ev["t0_ms"] + uc.HISTORY_GIVEUP_MS:
                return
            facts = {"market_pre_t0": None, "market": None, "symbol": None, "leaked": None,
                     "reason": "klines unavailable"}
        self._append({"rid": "binance:" + eid, "kind": "binance", "event_id": eid, **facts})

    def _bprior(self, ev):
        """The Binance-prior exclusion re-checked at t0 + 1 h, after the archive's CMS polls."""
        with closing(ud.open_archive(self.archive_path)) as conn:
            found = ud.binance_prior(conn, ev["token"], ev["t0_ms"])
        self._append({"rid": "bprior:" + ev["event_id"], "kind": "bprior",
                      "event_id": ev["event_id"], "stage": "t0+1h", **found})

    def _hl_leak(self, ev, hl):
        """The Part C leak test on Hyperliquid 1m candles (descriptive only)."""
        eid, t0 = ev["event_id"], ev["t0_ms"]
        if not self._due("hlleak:" + eid, uc.RETRY_GAP_MS):
            return
        try:
            rows = self.hl.candles(hl["coin"], uc.floor_minute(t0 - 15 * uc.MINUTE_MS), t0 - 1)
        except ValueError:
            if self.wall_ms() > t0 + uc.HISTORY_GIVEUP_MS:
                self._append({"rid": "hlleak:" + eid, "kind": "hlleak", "event_id": eid,
                              "descriptive": True, "leaked": None, "reason": "candles unavailable"})
            return
        rows = {k: v for k, v in rows.items() if k < t0}
        self._append({"rid": "hlleak:" + eid, "kind": "hlleak", "event_id": eid,
                      "descriptive": True, "leaked": nr.leaked(rows, t0),
                      "close_t0_10m": nr.price_at(rows, t0 + nr.LEAK_FROM_MS),
                      "close_t0_2m": nr.price_at(rows, t0 + nr.LEAK_TO_MS)})

    def _funding(self, ev, hl, entry, ex):
        """Finalized fundingHistory rates x the observed oraclePx, per hour of the hold."""
        eid = ev["event_id"]
        if not self._due("funding:" + eid, uc.RETRY_GAP_MS):
            return
        start, end = entry["obs_ms"], ex["obs_ms"]
        now = self.wall_ms()
        try:
            records = self.hl.funding_history(hl["coin"], start, end + uc.FUNDING_SETTLE_MS)
        except ValueError:
            if now > end + uc.HISTORY_GIVEUP_MS:
                self._append({"rid": "funding:" + eid, "kind": "funding", "event_id": eid,
                              "status": "missing", "estimated": True, "cashflow": None,
                              "reason": "fundingHistory unavailable"})
            return
        rates = uv.rates_by_hour(records)
        if any(h not in rates for h in uv.boundaries(start, end)) and now < end + uc.FUNDING_SETTLE_MS:
            return                           # the last settlement's record may not be out yet
        coin = hl["coin"]
        oracle = {r["hour_ms"]: (r["obs_ms"], r["px"][coin]) for r in self.ledger.kind("oracle")
                  if coin in r["px"] and start < r["hour_ms"] <= end}
        self._append({"rid": "funding:" + eid, "kind": "funding", "event_id": eid, "coin": coin,
                      **uv.funding(Decimal(entry["q"]), start, end, rates, oracle)})

    def _excursion(self, ev, hl, entry, ex):
        eid = ev["event_id"]
        if not self._due("excursion:" + eid, uc.RETRY_GAP_MS):
            return
        start, end = entry["obs_ms"], ex["obs_ms"]
        give_up = self.wall_ms() > end + uc.CANDLE_GIVEUP_MS
        try:
            rec = uv.excursion(self.hl.candles(hl["coin"], start, end), start, end, entry["vwap"])
        except ValueError:
            rec = {"status": "missing", "reason": "candles unavailable"}
        if rec["status"] == "ok" or give_up:
            self._append({"rid": "excursion:" + eid, "kind": "excursion", "event_id": eid, **rec})

    # --- audit and decision ----------------------------------------------------------------

    def _poll_upbit(self):
        """Store a timestamped market/all snapshot every 5 min; new KRW markets are audited."""
        now = self.wall_ms()
        if self._last_poll is not None and now - self._last_poll["obs_ms"] < uc.UPBIT_POLL_MS:
            return
        if not self._due("upbit", uc.RETRY_GAP_MS):
            return
        resp = self.http(uv.upbit_req())
        if resp.status != 200:
            raise RuntimeError("market/all answered HTTP %d" % resp.status)
        markets = uv.parse_markets(resp.body)
        obs = self.wall_ms()
        sha = uv.markets_sha(markets)
        prev = self._last_poll
        self.markets.append({"rid": "set:" + sha, "kind": "market_set", "sha256": sha,
                             "markets": markets, "first_obs_ms": obs})
        poll = {"rid": "poll:%d" % obs, "kind": "market_poll", "obs_ms": obs, "sha256": sha,
                "n": len(markets), "n_krw": len(uv.krw_tokens(markets))}
        self.markets.append(poll)
        self._last_poll = poll
        if prev is not None and prev["sha256"] != sha:
            before = uv.krw_tokens(self.markets.get("set:" + prev["sha256"])["markets"])
            for token in sorted(uv.krw_tokens(markets) - before):
                self.markets.append({"rid": "new:KRW-%s:%d" % (token, obs), "kind": "new_market",
                                     "market": "KRW-" + token, "token": token,
                                     "first_seen_ms": obs, "prev_obs_ms": prev["obs_ms"]})
                self.log("new Upbit market KRW-%s (previous snapshot %s)" % (
                    token, uc.iso(prev["obs_ms"])))

    def _audit(self):
        """A new KRW market with no detected notice in [first seen - 7 d, + 24 h] is a miss."""
        now = self.wall_ms()
        done = {a["new_rid"] for a in self.ledger.kind("audit")}
        for m in self.markets.kind("new_market"):
            if m["rid"] in done:
                continue
            seen = m["first_seen_ms"]
            match = [e["event_id"] for e in self.ledger.kind("event") if e["token"] == m["token"]
                     and seen - uc.AUDIT_BEFORE_MS <= e["t0_ms"] <= seen + uc.AUDIT_AFTER_MS]
            if not match and now <= seen + uc.AUDIT_AFTER_MS:
                continue
            status = "matched" if match else "missed"
            self._append({"rid": "audit:" + m["rid"], "kind": "audit", "new_rid": m["rid"],
                          "market": m["market"], "first_seen_ms": seen, "status": status,
                          "events": match})
            if status == "missed":
                self.log("MISSED detection: %s appeared %s with no matched notice" % (
                    m["market"], uc.iso(seen)))

    def _decide(self):
        """Descriptive reports at 20 and 30 comparable announcements; the single decision at 40
        or on 2027-11-05, recorded once and never recomputed."""
        need = [m for m in uc.MILESTONES if "milestone:%d" % m not in self.ledger]
        if "decision" in self.ledger and not need:
            return
        vs = ur.views(self.ledger)
        now = self.wall_ms()
        if need:
            final = ur.final_comparable(vs)
            for m in need:
                if len(final) >= m:
                    self._append(ur.resolution_record("milestone:%d" % m, "milestone",
                                                      "%d comparable announcements" % m,
                                                      final[:m], now))
        if "decision" not in self.ledger:
            due = ur.decision_due(vs, now)
            if due is not None:
                rec = ur.resolution_record("decision", "decision", due[0], due[1], now)
                self._append(rec)
                self.log("DECISION (%s): %s" % (rec["trigger"], rec["class"]))
