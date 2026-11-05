#!/usr/bin/env python3
"""Upbit KRW listing fade live pilot: the trigger (#252).

Tails the paper monitor's ledger (research/upbit_fade_forward/data/ledger.jsonl, read only)
and, for each paper entry of a comparable event, asks the local Freqtrade bot
ft-upbit-fade-hl for one short through POST /api/v1/forceenter. It never signs an order and
never talks to Hyperliquid: the bot does both. Stdlib only.

    python3 live_trigger.py run       # the service (systemd user unit upbit-fade-live-trigger)
    python3 live_trigger.py status    # decisions, open intents, pause state
    python3 live_trigger.py reconcile EVENT_ID --outcome entered|not_entered --by NAME --note TEXT

Rules: prereg upbit-krw-fade-live-pilot-2026-11 (ft_userdata/preregistrations.json).
Runbook: GO-LIVE.md beside this file.

Selection is the paper monitor's own: an entry record whose event `uff_report.classify`
puts in the comparable cohort with every requirement established (the paper keeps an event
with an unestablished requirement comparable, but with a missing outcome; the pilot does not
trade it). The paper entry is the trigger; the live order is sent no later than
t0 + 7 min, the paper's timely-entry bound.

Never a double entry:
- one decision per event id, in an append-only, fsynced ledger (`data/decisions.jsonl`);
- the `intent` record is written before the request is sent, and the request is sent once;
- an intent without a result after a restart is recorded `unknown`, never resent;
- an `unknown` outcome pauses entries, and the pause is made durable (the `data/KILL` file)
  before the outcome is recorded; every start, and every loop, re-engages it while any
  unknown outcome has no recorded reconciliation (`reconcile`, run by the operator after
  checking the bot and Hyperliquid), so deleting the file alone does not resume;
- a failure to persist any record or the pause stops all further entries until restart;
- a process lock keeps a second trigger out;
- the bot enforces the same rules again under Freqtrade's entry lock, just before the order
  (`UpbitFadeLiveV1.confirm_trade_entry`): the entry tag carries the event id and the
  t0 + 7 min deadline, and the bot refuses a late entry, a third open trade, a second trade
  on the pair or on the event, and any entry once realized P&L is at the loss limit.

The loss limit is also latched here on every loop, not only when a paper event arrives.

Timing (amended rule, pending operator approval before go-live): admission is checked by
t0 + 7 min, here and under the bot's entry lock; Freqtrade then prepares margin mode and
leverage (with retries) before it submits, so submission cannot be bounded. For every entry
the trigger reads the entry order back from the bot and records its submission and fill
times against t0 (`timing:` records); a fill after t0 + 10 min, or no fill by then, is an
execution defect that writes the durable pause.
"""
import argparse
import base64
import fcntl
import ipaddress
import json
import logging
import logging.handlers
import os
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAPER_DIR = HERE.parent / "upbit_fade_forward"
if str(PAPER_DIR) not in sys.path:
    sys.path.insert(0, str(PAPER_DIR))

import uff_ledger as ul  # noqa: E402  (the paper monitor's append-only ledger, reused)
import uff_report as ur  # noqa: E402  (the paper monitor's cohort rules, read only)

PREREG_ID = "upbit-krw-fade-live-pilot-2026-11"
PAPER_LEDGER = PAPER_DIR / "data" / "ledger.jsonl"
DATA_DIR = HERE / "data"

# --- the pilot's rules (frozen in the prereg; tests pin them) ----------------------------
SIDE = "short"
STAKE_USDC = 50
LEVERAGE = 1.0
MAX_OPEN = 2
LATEST_ENTRY_MS = 7 * 60_000          # no live entry later than t0 + 7 min
KILL_REALIZED_PNL_USD = -75.0         # pause at or below this cumulative realized P&L
FILL_DEFECT_MS = 10 * 60_000          # a fill after t0 + 10 min is an execution defect
QUOTE = "USDC"
STRATEGY = "UpbitFadeLiveV1"          # the bot FT_API_URL must answer for

# --- operation (Claude's calls) ----------------------------------------------------------
POLL_S = 2.0
READ_TIMEOUT_S = 5
ENTER_TIMEOUT_S = 15
NOTIFY_TIMEOUT_S = 5
TAG_PREFIX = "upbit-fade:"            # entry tag: upbit-fade:<event id>@<deadline ms>
DEFAULT_FT_URL = "http://127.0.0.1:8105"
NOTIFY_PREFIX = "[upbit-fade-live] "

LOG = logging.getLogger("upbit-fade-live")


class FtError(Exception):
    """The bot could not be read (transport failure, non-200 or a body that is not JSON)."""


def _require_loopback(url):
    host = urllib.parse.urlsplit(url).hostname or ""
    if host == "localhost":
        return url
    try:
        if ipaddress.ip_address(host).is_loopback:
            return url
    except ValueError:
        pass
    raise ValueError("refusing non-loopback URL %r: the trigger talks only to the local bot" % url)


def basic_auth(user, password):
    token = base64.b64encode(("%s:%s" % (user, password)).encode("utf-8")).decode("ascii")
    return "Basic " + token


class FtApi:
    """The local Freqtrade REST API with HTTP Basic auth. `opener(request, timeout)` is
    urllib.request.urlopen in production and a fake in the tests."""

    def __init__(self, base_url, user, password, opener=urllib.request.urlopen):
        if not user or not password:
            raise ValueError("FT_API_USER and FT_API_PASS are required")
        self.base = _require_loopback(base_url).rstrip("/") + "/api/v1/"
        self._auth = basic_auth(user, password)
        self.opener = opener

    def _request(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Authorization", self._auth)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        return req

    def get(self, path):
        try:
            with self.opener(self._request("GET", path), timeout=READ_TIMEOUT_S) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            raise FtError("GET %s: HTTP %d" % (path.split("?")[0], e.code)) from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise FtError("GET %s: %s" % (path.split("?")[0], type(e).__name__)) from None
        if status != 200:
            raise FtError("GET %s: HTTP %d" % (path.split("?")[0], status))
        try:
            return json.loads(raw)
        except ValueError:
            raise FtError("GET %s: body is not JSON" % path.split("?")[0]) from None

    def force_enter(self, body):
        """POST /forceenter once. (HTTP status, body text); transport failures raise."""
        try:
            with self.opener(self._request("POST", "forceenter", body), timeout=ENTER_TIMEOUT_S) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")


class Notifier:
    """Best-effort ops message through trade-webhook /test/notify (loopback). Never raises."""

    def __init__(self, url, token, opener=urllib.request.urlopen):
        self.url = _require_loopback(url) if url else None
        self.token, self.opener = token, opener

    def __call__(self, text):
        if not self.url:
            return False
        req = urllib.request.Request(self.url, data=json.dumps({"text": NOTIFY_PREFIX + text}).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
        if self.token:
            req.add_header("X-Notify-Token", self.token)
        try:
            with self.opener(req, timeout=NOTIFY_TIMEOUT_S) as r:
                return r.status == 200
        except Exception as e:  # noqa: BLE001 - a lost alert never blocks the trigger
            LOG.warning("notify failed: %s", type(e).__name__)
            return False


def entry_tag(event_id, deadline_ms):
    """The tag the bot's confirm_trade_entry parses: event id and the t0 + 7 min deadline."""
    return "%s%s@%d" % (TAG_PREFIX, event_id, deadline_ms)


def ft_pair(coin):
    """The CCXT perp symbol Freqtrade uses for a Hyperliquid coin: ccxt 4.5.68
    `hyperliquid.parse_market` builds base = safe_currency_code(name), which upper-cases
    (kPEPE -> KPEPE/USDC:USDC). The bot's own /markets answer is what confirms it."""
    return "%s/%s:%s" % (coin.upper(), QUOTE, QUOTE)


class Trigger:
    def __init__(self, paper_ledger, data_dir, api, wall_ms, notify=None, kill_path=None):
        self.paper_path = Path(paper_ledger)
        self.data_dir = Path(data_dir)
        self.api = api
        self.wall_ms = wall_ms
        self.notify = notify or (lambda text: False)
        self.kill_path = Path(kill_path) if kill_path else self.data_dir / "KILL"
        self.decisions = ul.Ledger(self.data_dir / "decisions.jsonl")
        self.paper = None
        self._paper_sig = None
        self._waiting = {}              # event id -> why it is not decided yet
        self.halted = None              # why state could not be persisted (until restart)
        self._loss_seen = None          # last loss-latch read problem, logged once
        self._timing_seen = {}          # event id -> last trade-read problem, logged once

    # --- plumbing -----------------------------------------------------------------------

    def _append(self, rec):
        rec.setdefault("at_ms", self.wall_ms())
        rec.setdefault("prereg", PREREG_ID)
        try:
            return self.decisions.append(rec)
        except Exception as e:
            self._halt("could not write %s to %s: %s: %s" % (
                rec.get("rid"), self.decisions.path, type(e).__name__, e))
            raise

    def _halt(self, reason):
        """Persisting state failed: no further entry from this process. The pause file is
        attempted too, so a restart stays paused if it could be written."""
        if self.halted is None:
            self.halted = reason
            LOG.error("HALTED, no further entries: %s", reason)
            try:
                self._write_kill_file("halted: " + reason)
            except Exception as e:  # noqa: BLE001 - the in-memory halt still holds
                LOG.error("could not write the pause file either: %s: %s", type(e).__name__, e)
            self.notify("halted, no further entries: %s" % reason)

    def decided(self, eid):
        return "intent:" + eid in self.decisions or "skip:" + eid in self.decisions

    def unresolved(self):
        """Event ids whose /forceenter outcome is unknown and not yet reconciled."""
        return [r["event_id"] for r in self.decisions.kind("result")
                if r.get("status") == "unknown" and "reconcile:" + r["event_id"] not in self.decisions]

    def pause_reasons(self):
        reasons = []
        if self.halted:
            reasons.append("halted: " + self.halted)
        open_unknown = self.unresolved()
        if open_unknown:
            reasons.append("unreconciled unknown outcome: " + ", ".join(open_unknown))
        if self.kill_path.exists():
            reasons.append("kill switch file " + str(self.kill_path))
        return reasons

    def killed(self):
        return bool(self.pause_reasons())

    def _write_kill_file(self, reason):
        self.kill_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.kill_path.with_name(self.kill_path.name + ".tmp")
        with open(tmp, "w") as f:
            f.write(json.dumps({"at_ms": self.wall_ms(), "reason": reason}) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.kill_path)
        dfd = os.open(str(self.kill_path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)

    def engage_kill(self, reason):
        """The durable pause first (the KILL file), then its ledger record."""
        if not self.kill_path.exists():
            try:
                self._write_kill_file(reason)
            except Exception as e:
                self._halt("could not write the pause file %s: %s: %s" % (
                    self.kill_path, type(e).__name__, e))
                raise
        n = len(self.decisions.kind("kill")) + 1
        self._append({"rid": "kill:%d" % n, "kind": "kill", "reason": reason})
        LOG.error("KILL SWITCH ENGAGED: %s (%s)", reason, self.kill_path)
        self.notify("kill switch engaged: %s. Entries paused; see GO-LIVE.md (kill switch)." % (
            reason,))

    def latch(self):
        """Re-engage the pause file while an unknown outcome is unreconciled, and latch the
        loss limit from the bot's realized P&L. Runs every loop."""
        open_unknown = self.unresolved()
        if open_unknown and not self.kill_path.exists():
            self.engage_kill("unreconciled unknown forceenter outcome for %s: run "
                             "`live_trigger.py reconcile` after checking the bot and "
                             "Hyperliquid" % ", ".join(open_unknown))
        if self.kill_path.exists():
            return
        try:
            realized = float(self.api.get("profit")["profit_closed_coin"])
        except (FtError, KeyError, TypeError, ValueError) as e:
            if self._loss_seen != str(e):
                LOG.warning("loss latch: cannot read the bot's realized P&L: %s", e)
                self._loss_seen = str(e)
            return
        self._loss_seen = None
        if realized <= KILL_REALIZED_PNL_USD:
            self.engage_kill("cumulative realized pilot P&L %.2f USDC <= %.0f" % (
                realized, KILL_REALIZED_PNL_USD))

    def tick(self):
        """One loop of the service: the latches, the entry timing, then the paper ledger."""
        self.latch()
        self.measure()
        self.poll()

    # --- entry timing -------------------------------------------------------------------

    def _measurable(self):
        """(event id, trade id, entry tag) of every entry, sent by the trigger or reconciled
        as entered, that has no timing record yet."""
        out = [(r["event_id"], r["trade_id"], r.get("entry_tag"))
               for r in self.decisions.kind("result") if r.get("status") == "entered"]
        out += [(r["event_id"], r["trade_id"], r.get("entry_tag"))
                for r in self.decisions.kind("reconcile")
                if r.get("outcome") == "entered" and r.get("trade_id") is not None]
        return [x for x in out if "timing:" + x[0] not in self.decisions]

    @staticmethod
    def _entry_order(trade, tag):
        orders = [o for o in trade.get("orders") or [] if isinstance(o, dict)
                  and o.get("ft_order_side") != "stoploss"]
        mine = [o for o in orders if o.get("ft_order_tag") == tag] or \
               [o for o in orders if o.get("ft_order_side") == "sell"]       # a short's entry
        mine.sort(key=lambda o: o.get("order_timestamp") or 0)
        return mine[0] if mine else None

    def measure(self):
        """Record each entry order's submission and fill time against t0; a fill after
        t0 + 10 min (or none by then) pauses the pilot."""
        for eid, trade_id, tag in self._measurable():
            intent = self.decisions.get("intent:" + eid) or {}
            t0 = intent.get("t0_ms")
            if t0 is None:
                continue
            try:
                trade = self.api.get("trade/%d" % int(trade_id))
            except (FtError, TypeError, ValueError) as e:
                if self._timing_seen.get(eid) != str(e):
                    LOG.warning("timing %s: cannot read trade %s: %s", eid, trade_id, e)
                    self._timing_seen[eid] = str(e)
                continue
            order = self._entry_order(trade if isinstance(trade, dict) else {}, tag)
            filled = order is not None and (order.get("filled") or 0) > 0 \
                and order.get("order_filled_timestamp") is not None
            limit = t0 + FILL_DEFECT_MS
            if not filled and self.wall_ms() <= limit:
                continue                                   # not filled yet; still in time
            submitted_ms = order.get("order_timestamp") if order else None
            filled_ms = order.get("order_filled_timestamp") if filled else None
            defect = filled_ms is None or filled_ms > limit

            def after(ms, ref):
                return None if ms is None or ref is None else round((ms - ref) / 1000, 3)

            rec = {"rid": "timing:" + eid, "kind": "timing", "event_id": eid,
                   "trade_id": trade_id, "order_id": order.get("order_id") if order else None,
                   "order_status": order.get("status") if order else None,
                   "t0_ms": t0, "deadline_ms": intent.get("deadline_ms"),
                   "paper_entry_obs_ms": intent.get("paper_entry_obs_ms"),
                   "intent_ms": intent.get("at_ms"), "submitted_ms": submitted_ms,
                   "filled_ms": filled_ms, "submit_after_t0_s": after(submitted_ms, t0),
                   "fill_after_t0_s": after(filled_ms, t0),
                   "fill_after_paper_entry_s": after(filled_ms, intent.get("paper_entry_obs_ms")),
                   "fill_limit_ms": limit, "defect": defect}
            if defect:
                # The durable pause before the record, as for an unknown outcome.
                self.engage_kill("execution defect: entry %s (trade %s) %s" % (
                    eid, trade_id, "filled %.1f s after t0, later than t0 + 10 min" % (
                        (filled_ms - t0) / 1000) if filled_ms is not None
                    else "not filled by t0 + 10 min"))
            self._append(rec)
            LOG.info("timing %s: submitted %+.1f s, filled %s after t0%s", eid,
                     rec["submit_after_t0_s"] or 0.0,
                     "%+.1f s" % rec["fill_after_t0_s"] if filled_ms is not None else "never",
                     " (DEFECT)" if defect else "")

    def _skip(self, eid, reason, **detail):
        self._waiting.pop(eid, None)
        self._append({"rid": "skip:" + eid, "kind": "skip", "event_id": eid, "reason": reason,
                      **detail})
        LOG.info("skip %s: %s %s", eid, reason, json.dumps(detail, sort_keys=True))

    def _wait(self, eid, why):
        if self._waiting.get(eid) != why:
            LOG.info("waiting on %s: %s", eid, why)
        self._waiting[eid] = why

    # --- startup ------------------------------------------------------------------------

    def recover(self):
        """An intent without a result: the request may or may not have reached the bot.
        Pause first, then record it unknown; never resend. Any unknown outcome without a
        recorded reconciliation keeps (or puts back) the pause."""
        for intent in list(self.decisions.kind("intent")):
            eid = intent["event_id"]
            if "result:" + eid in self.decisions:
                continue
            self.engage_kill("forceenter outcome unknown for %s (%s): check the bot's /status "
                             "for entry tag %s" % (eid, intent["pair"], intent["entry_tag"]))
            self._append({"rid": "result:" + eid, "kind": "result", "event_id": eid,
                          "status": "unknown", "entry_tag": intent["entry_tag"],
                          "reason": "restart after the request was written; outcome not observed"})
        open_unknown = self.unresolved()
        if open_unknown and not self.kill_path.exists():
            self.engage_kill("unreconciled unknown forceenter outcome for %s" % ", ".join(open_unknown))

    # --- the paper ledger, read only ----------------------------------------------------

    def _reload(self):
        try:
            st = self.paper_path.stat()
        except FileNotFoundError:
            self.paper = None
            return False
        sig = (st.st_size, st.st_mtime_ns)
        if sig != self._paper_sig or self.paper is None:
            self.paper = ul.Ledger(self.paper_path)
            self._paper_sig = sig
        return True

    def poll(self):
        if not self._reload():
            return
        for entry in self.paper.kind("entry"):
            eid = entry["event_id"]
            if not self.decided(eid):
                self.consider(entry)

    # --- one paper entry ----------------------------------------------------------------

    def consider(self, entry):
        eid = entry["event_id"]
        ev = self.paper.get("event:" + eid)
        if ev is None:
            return self._wait(eid, "no event record")
        t0 = ev["t0_ms"]
        cutoff = t0 + LATEST_ENTRY_MS
        if not ur.filled(entry):
            return self._skip(eid, "paper_entry_not_filled", paper_status=entry.get("status"))
        if self.wall_ms() > cutoff:
            waited = self._waiting.get(eid)
            self._skip(eid, "stale", t0_ms=t0, cutoff_ms=cutoff, waited_for=waited)
            if waited:
                self.notify("missed %s: not entered by t0 + 7 min (%s)" % (eid, waited))
            return None
        cohort, unknown = ur.classify(ur.view(self.paper, ev))
        if cohort != "comparable":
            return self._skip(eid, "not_comparable", cohort=cohort, reasons=unknown)
        if unknown:
            return self._wait(eid, "requirements not established: " + ", ".join(unknown))
        if self.killed():
            return self._missed(eid, "kill_switch", pause=self.pause_reasons())
        try:
            config = self.api.get("show_config")
            realized = float(self.api.get("profit")["profit_closed_coin"])
            open_trades = self.api.get("status")
        except (FtError, KeyError, TypeError, ValueError) as e:
            return self._wait(eid, "bot unreachable: %s" % e)
        if config.get("strategy") != STRATEGY:
            self.engage_kill("FT_API_URL answers for strategy %r, not %s" % (
                config.get("strategy"), STRATEGY))
            return self._missed(eid, "wrong_bot", strategy=config.get("strategy"))
        if config.get("state") != "running":
            return self._missed(eid, "bot_not_running", state=config.get("state"))
        if realized <= KILL_REALIZED_PNL_USD:
            self.engage_kill("cumulative realized pilot P&L %.2f USDC <= %.0f" % (
                realized, KILL_REALIZED_PNL_USD))
            return self._missed(eid, "kill_pnl", realized_pnl=realized)
        if len(open_trades) >= MAX_OPEN:
            return self._missed(eid, "max_open", open_trades=len(open_trades))
        coin = entry["coin"]
        pair = ft_pair(coin)
        try:
            markets = self.api.get("markets?" + urllib.parse.urlencode(
                {"base": coin.upper(), "quote": QUOTE}))["markets"]
        except (FtError, KeyError, TypeError) as e:
            return self._wait(eid, "bot unreachable: %s" % e)
        market = markets.get(pair) if isinstance(markets, dict) else None
        if not market or not market.get("swap") or not market.get("active"):
            self._skip(eid, "unavailable_pair", coin=coin, pair=pair)
            self.notify("skipped %s: %s is not an active perp on the bot" % (eid, pair))
            return None
        if self.wall_ms() > cutoff:                       # the reads took time
            return self._skip(eid, "stale", t0_ms=t0, cutoff_ms=cutoff, waited_for="bot reads")
        if self.killed():
            return self._missed(eid, "kill_switch", pause=self.pause_reasons())
        return self._enter(eid, ev, entry, pair, config, realized, len(open_trades))

    def _missed(self, eid, reason, **detail):
        self._skip(eid, reason, **detail)
        self.notify("missed %s: %s %s" % (eid, reason, json.dumps(detail, sort_keys=True)
                                           if detail else ""))

    def _enter(self, eid, ev, entry, pair, config, realized, n_open):
        deadline = ev["t0_ms"] + LATEST_ENTRY_MS
        tag = entry_tag(eid, deadline)
        body = {"pair": pair, "side": SIDE, "stakeamount": STAKE_USDC, "leverage": LEVERAGE,
                "ordertype": "market", "entry_tag": tag}
        self._append({"rid": "intent:" + eid, "kind": "intent", "event_id": eid,
                      "t0_ms": ev["t0_ms"], "paper_entry_obs_ms": entry["obs_ms"],
                      "coin": entry["coin"], "pair": pair, "request": body, "entry_tag": tag,
                      "deadline_ms": deadline,
                      "bot_dry_run": bool(config.get("dry_run", True)),
                      "open_trades_before": n_open, "realized_pnl_before": realized})
        self._waiting.pop(eid, None)
        try:
            status, text = self.api.force_enter(body)
        except Exception as e:  # noqa: BLE001 - the outcome is unknown, never retried
            status, text = None, "%s: %s" % (type(e).__name__, e)
        rec = {"rid": "result:" + eid, "kind": "result", "event_id": eid, "entry_tag": tag,
               "http_status": status}
        try:
            parsed = json.loads(text) if status is not None else None
        except ValueError:
            parsed = None
        if status == 200 and isinstance(parsed, dict) and parsed.get("trade_id") is not None:
            rec.update(status="entered", trade_id=parsed["trade_id"],
                       open_rate=parsed.get("open_rate"), amount=parsed.get("amount"))
        elif status == 502 and isinstance(parsed, dict) and isinstance(parsed.get("error"), str):
            # Freqtrade's RPCException handler: a validation error raised before any order
            # (pair not tradable, max trades, pair already open, trader not running) or a
            # failed entry; nothing to reconcile, and the event is never retried.
            unavailable = "Symbol does not exist or market is not active" in parsed["error"]
            rec.update(status="unavailable_pair" if unavailable else "rejected",
                       error=parsed["error"][:300])
        else:
            rec.update(status="unknown", error=(text or "")[:300])
            # The durable pause before the outcome record: a crash in between leaves an
            # intent without a result, which recover() also turns into a pause.
            self.engage_kill("forceenter outcome unknown for %s (%s, HTTP %s): check the bot's "
                             "/status for entry tag %s" % (eid, pair, status, tag))
        self._append(rec)
        if rec["status"] == "entered":
            LOG.info("entered %s: %s short, stake %s, trade %s (dry_run %s)", eid, pair,
                     STAKE_USDC, rec["trade_id"], config.get("dry_run"))
        elif rec["status"] == "unknown":
            pass
        else:
            LOG.warning("%s %s: %s", rec["status"], eid, rec["error"])
            self.notify("%s %s (%s): %s" % (rec["status"], eid, pair, rec["error"]))
        return rec


# --- CLI ------------------------------------------------------------------------------------

class LockHeld(Exception):
    pass


@contextmanager
def process_lock(data_dir):
    with open(os.path.join(data_dir, "trigger.lock"), "a") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LockHeld(data_dir) from None
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def setup_logging(log_file):
    LOG.setLevel(logging.INFO)
    LOG.propagate = False
    for h in list(LOG.handlers):
        LOG.removeHandler(h)
        h.close()
    fmt = logging.Formatter("%(asctime)s [upbit-fade-live] %(levelname)s %(message)s",
                            "%Y-%m-%dT%H:%M:%SZ")
    fmt.converter = time.gmtime
    fh = logging.handlers.TimedRotatingFileHandler(log_file, when="midnight", backupCount=14,
                                                   utc=True)
    for h in (fh, logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        LOG.addHandler(h)


def _unresolved(decisions):
    return [r["event_id"] for r in decisions.kind("result")
            if r.get("status") == "unknown" and "reconcile:" + r["event_id"] not in decisions]


def status(data_dir, kill_path):
    decisions = ul.Ledger(os.path.join(data_dir, "decisions.jsonl"))
    kill = Path(kill_path)
    print("prereg %s" % PREREG_ID)
    print("kill switch: %s" % (("ENGAGED " + kill.read_text().strip()) if kill.exists() else "off"))
    open_unknown = _unresolved(decisions)
    print("unreconciled unknown outcomes: %s" % (", ".join(open_unknown) if open_unknown else "none"))
    for r in decisions.kind("reconcile"):
        print("  reconciled %s: %s (trade %s) by %s: %s" % (
            r["event_id"], r["outcome"], r.get("trade_id"), r["by"], r["note"]))
    for r in decisions.kind("timing"):
        print("  timing %s: submitted %s s, filled %s s after t0%s" % (
            r["event_id"], r["submit_after_t0_s"], r["fill_after_t0_s"],
            " DEFECT" if r["defect"] else ""))
    counts = {}
    for r in decisions.kind("result"):
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    for r in decisions.kind("skip"):
        counts["skip:" + r["reason"]] = counts.get("skip:" + r["reason"], 0) + 1
    print("decisions: %s" % (json.dumps(counts, sort_keys=True) if counts else "none"))
    for i in decisions.kind("intent"):
        res = decisions.get("result:" + i["event_id"]) or {}
        print("  %s %s %s dry_run=%s -> %s %s" % (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(i["at_ms"] / 1000)), i["event_id"],
            i["pair"], i["bot_dry_run"], res.get("status", "NO RESULT"),
            res.get("trade_id", res.get("error", ""))))
    return 0


def reconcile(data_dir, kill_path, event_id, outcome, by, note, trade_id, wall_ms):
    """Record the operator's check of an unknown /forceenter outcome. Needs the trigger
    stopped (its lock), so the service never misses the record."""
    path = os.path.join(data_dir, "decisions.jsonl")
    with process_lock(data_dir):
        decisions = ul.Ledger(path)
        res = decisions.get("result:" + event_id)
        if res is None or res.get("status") != "unknown":
            print("no unknown outcome recorded for %s" % event_id)
            return 2
        if "reconcile:" + event_id in decisions:
            print("%s is already reconciled" % event_id)
            return 2
        if outcome == "entered" and trade_id is None:
            print("--trade-id is required when the outcome is entered")
            return 2
        decisions.append({"rid": "reconcile:" + event_id, "kind": "reconcile",
                          "event_id": event_id, "outcome": outcome, "trade_id": trade_id,
                          "entry_tag": res.get("entry_tag"), "by": by, "note": note,
                          "at_ms": wall_ms(), "prereg": PREREG_ID})
        left = _unresolved(decisions)
        print("reconciled %s: %s" % (event_id, outcome))
        print("unreconciled unknown outcomes left: %s" % (", ".join(left) if left else "none"))
        if Path(kill_path).exists():
            print("the kill switch file %s stays until you remove it" % kill_path)
    return 0


def _term(signum, frame):
    raise SystemExit(0)


def main(argv=None):
    p = argparse.ArgumentParser(prog="live_trigger.py",
                                description="Upbit KRW listing fade live-pilot trigger (#252)")
    p.add_argument("--data-dir", default=str(DATA_DIR))
    p.add_argument("--paper-ledger", default=str(PAPER_LEDGER))
    p.add_argument("--kill-file", default=None, help="default: <data-dir>/KILL")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="the trigger loop (systemd)")
    sub.add_parser("status", help="decisions, open intents, pause state")
    rc = sub.add_parser("reconcile", help="record the checked outcome of an unknown entry "
                                          "(stop the service first)")
    rc.add_argument("event_id")
    rc.add_argument("--outcome", required=True, choices=["entered", "not_entered"])
    rc.add_argument("--trade-id", type=int, default=None, help="the bot's trade id, if entered")
    rc.add_argument("--by", required=True)
    rc.add_argument("--note", required=True)
    args = p.parse_args(argv)
    kill_path = args.kill_file or os.path.join(args.data_dir, "KILL")
    if args.cmd == "status":
        return status(args.data_dir, kill_path)
    if args.cmd == "reconcile":
        os.makedirs(args.data_dir, exist_ok=True)
        try:
            return reconcile(args.data_dir, kill_path, args.event_id, args.outcome, args.by,
                             args.note, args.trade_id, lambda: int(time.time() * 1000))
        except LockHeld:
            print("upbit-fade-live: the trigger is running; stop upbit-fade-live-trigger first")
            return 3
    os.makedirs(args.data_dir, exist_ok=True)
    setup_logging(os.path.join(args.data_dir, "trigger.log"))
    api = FtApi(os.environ.get("FT_API_URL", DEFAULT_FT_URL), os.environ.get("FT_API_USER"),
                os.environ.get("FT_API_PASS"))
    notify = Notifier(os.environ.get("NOTIFY_URL"), os.environ.get("TRADE_WEBHOOK_NOTIFY_TOKEN"))
    try:
        with process_lock(args.data_dir):
            trig = Trigger(args.paper_ledger, args.data_dir, api, lambda: int(time.time() * 1000),
                           notify=notify, kill_path=kill_path)
            trig.recover()
            LOG.info("start: prereg %s, paper ledger %s, bot %s, %d decisions, pause: %s",
                     PREREG_ID, args.paper_ledger, api.base, len(trig.decisions),
                     "; ".join(trig.pause_reasons()) or "off")
            signal.signal(signal.SIGTERM, _term)
            try:
                while True:
                    try:
                        trig.tick()
                    except Exception as e:  # noqa: BLE001 - the loop must never die
                        LOG.error("loop failed: %s: %s", type(e).__name__, e)
                    time.sleep(POLL_S)
            finally:
                LOG.info("stopping")
    except LockHeld:
        print("upbit-fade-live: another trigger holds %s/trigger.lock" % args.data_dir)
        return 3


if __name__ == "__main__":
    sys.exit(main())
