"""Cohorts, outcomes, the A4 resolution and the status report of the forward monitor (#229).

Pure functions of the ledger. The decision metric, interval and tipping point reuse
nes_returns (announcements, estimate, block_bootstrap_mean_ci at 95%, announcement_parts,
tipping_point) by import; the forward results are written in its result shape.
"""
import statistics

import uff_common as uc
import uff_venues as uv
import nes_returns as nr

ACTIONS = ("hl", "binance", "bprior", "hlleak", "entry", "cp30m", "cp4h", "exit", "funding",
           "excursion")
LATE_ACTIONS = ("cp30m", "cp4h", "exit")
FILLED = ("timely", "delayed", "ok")
TIP_CLASS = {"EDGE": "EDGE (proxy)", "NO EDGE": "NO EDGE"}   # nes_returns' names for the bounds
CRITERIA = ("timing_verified", "krw_snapshot", "hl_eligible", "binance_market_pre_t0",
            "binance_leak_passed", "entry_timely")


def evidence(ledger, eid):
    """The versioned later observations of an event's notice that state a trading start."""
    return [r for r in ledger.kind("evidence") if r["event_id"] == eid]


def effective(ledger, ev):
    """The event as the bot knew it at its entry decision: the latest evidence received before
    that decision sets the trading start (a start before t0 excludes, one at or after t0 is
    known). Evidence after the decision is descriptive and changes nothing."""
    usable = [r for r in evidence(ledger, ev["event_id"]) if r["before_entry"]]
    if not usable:
        return ev
    start = usable[-1]["trading_start_ms"]
    return {**ev, "trading_start_ms": start, "began_before_notice": start < ev["t0_ms"],
            "start_unknown": False, "start_from": usable[-1]["rid"]}


def view(ledger, ev):
    eid = ev["event_id"]
    v = {"event": effective(ledger, ev), "evidence": evidence(ledger, eid)}
    for a in ACTIONS:
        v[a] = ledger.get("%s:%s" % (a, eid))
    v["late"] = {a: ledger.get("late:%s:%s" % (a, eid)) for a in LATE_ACTIONS}
    v["krwseen"] = ledger.get("krwseen:" + eid)      # descriptive only, never read by classify
    return v


def views(ledger):
    evs = sorted(ledger.kind("event"), key=lambda e: (e["t0_ms"], e["event_id"]))
    return [view(ledger, e) for e in evs]


def filled(rec):
    return rec is not None and rec.get("status") in FILLED


# --- cohorts -----------------------------------------------------------------------------

def detection_exclusions(ev):
    """Exclusions known when the event was detected; an excluded event is never traded."""
    out = []
    if ev["krw_prior"] is True:
        out.append("already_on_krw")
    if ev["began_before_notice"]:
        out.append("began_before_notice")
    if (ev.get("binance_prior") or {}).get("found"):
        out.append("binance_listing_prior")
    return out


def exclusions(v):
    """Detection exclusions plus a Binance notice published before t0 that reached the archive
    later (the t0 + 1 h re-check)."""
    out = detection_exclusions(v["event"])
    if "binance_listing_prior" not in out and (v["bprior"] or {}).get("found"):
        out.append("binance_listing_prior")
    return out


def start_unknown(ev):
    """No trading start was read: no body, or none stated in it. A descriptive flag, never a
    requirement (no notice body is readable from the VPS; spec, Claude's call 2026-11-05). A
    stated start before t0 excludes the event (began_before_notice); one at or after t0 is
    known."""
    return ev["trading_start_ms"] is None


def krw_first_seen_ms(v):
    return (v["krwseen"] or {}).get("krw_market_first_seen_ms")


def flags(vs):
    """The start_unknown and krw_market_first_seen counts over the token-events `vs`."""
    return {"token_events": len(vs),
            "start_unknown": sum(1 for v in vs if start_unknown(v["event"])),
            "krw_market_first_seen": sum(1 for v in vs if krw_first_seen_ms(v) is not None)}


def criteria(v):
    """The comparable-cohort requirements: True, False, or None when not (yet) established."""
    ev, hl, bn, entry = v["event"], v["hl"], v["binance"], v["entry"]
    leak = None if bn is None or bn.get("leaked") is None else not bn["leaked"]
    return {
        "timing_verified": ev["timing"] == "verified",
        "krw_snapshot": None if ev["krw_prior"] == "unknown" else True,
        "hl_eligible": {"eligible": True, "ineligible": False}.get(hl and hl["status"]),
        "binance_market_pre_t0": None if bn is None else bn.get("market_pre_t0"),
        "binance_leak_passed": leak,
        "entry_timely": (None if entry is None or entry["status"] == "missing"
                         else entry["status"] == "timely"),
    }


def classify(v):
    """(cohort, reasons). Cohorts: pre_epoch, excluded, ineligible, descriptive (a requirement
    failed), comparable (reasons = requirements not established; its outcome is then missing)."""
    ev = v["event"]
    if ev.get("pre_epoch"):
        return "pre_epoch", ["t0 before the monitor's epoch"]
    ex = exclusions(v)
    if ex:
        return "excluded", ex
    if v["hl"] is not None and v["hl"]["status"] == "ineligible":
        return "ineligible", [v["hl"].get("reason")]
    c = criteria(v)
    failed = [k for k in CRITERIA if c[k] is False]
    if failed:
        return "descriptive", failed
    return "comparable", [k for k in CRITERIA if c[k] is None]


def tradeable(v):
    return (v["hl"] is not None and v["hl"]["status"] == "eligible"
            and not detection_exclusions(v["event"]) and not v["event"].get("pre_epoch"))


def pending(v):
    """True while a record that decides the cohort or the 24 h outcome is still due."""
    if v["event"].get("pre_epoch"):
        return False
    if v["hl"] is None or v["binance"] is None or v["bprior"] is None:
        return True
    if tradeable(v) and v["entry"] is None:
        return True
    if filled(v["entry"]) and v["exit"] is None:
        return True
    return filled(v["exit"]) and v["funding"] is None


def outcome(v):
    """("resolved" | "missing" | "pending", net record or None) of the 24 h short."""
    if pending(v):
        return "pending", None
    if filled(v["entry"]) and filled(v["exit"]):
        n = uv.net(v["entry"], v["exit"], v["funding"])
        return ("resolved" if n["net_return"] is not None else "missing"), n
    return "missing", None


# --- resolution ----------------------------------------------------------------------------

def results(vs):
    """Final comparable token-events in nes_returns' result shape. A token-event is usable only
    when every requirement is established and the net (book fills, fees, funding) is complete;
    otherwise it is missing. `net_stress` equals `net`: the book walk is the slippage."""
    out = []
    for v in vs:
        cohort, unknown = classify(v)
        if cohort != "comparable":
            continue
        status, n = outcome(v)
        if status == "pending":
            continue
        ev = v["event"]
        value = n["net_return"] if status == "resolved" and not unknown else None
        out.append({"t0_ms": ev["t0_ms"], "announcement_id": ev["announcement_id"],
                    "event_id": ev["event_id"], "leaked": False if value is not None else None,
                    "horizons": {uc.HORIZON: {"exit_status": "ok" if value is not None else "missing",
                                              "net": value, "net_stress": value}}})
    return out


def resolve(res, level=uc.CI_LEVEL):
    """The A4 class at `level` on the announcement-level mean net 24 h return."""
    anns = nr.announcements(res, uc.HORIZON)
    est = nr.estimate(anns)
    lo, hi = nr.block_bootstrap_mean_ci(anns, level=level)
    parts = nr.announcement_parts(res, uc.HORIZON)
    missing = {"token_events": sum(p[4] for p in parts), "announcements": len(parts),
               "announcements_fully_missing": sum(1 for p in parts if p[3] == 0 and p[4] > 0)}
    if lo is None:
        cls, reason = "NOT DETERMINABLE", "fewer than two calendar months with a 24 h outcome"
    elif lo > 0:
        cls, reason = "EDGE", "95% interval above zero"
    elif hi <= 0:
        cls, reason = "NO EDGE", "95% interval at or below zero"
    else:
        cls, reason = "NOT DETERMINABLE", "95% interval spans zero"
    tip = None
    if cls in TIP_CLASS and missing["token_events"]:
        tip = nr.tipping_point(res, TIP_CLASS[cls], uc.HORIZON, level=level)
        if tip is not None:
            tip = {**tip, "note": tip["note"].replace(TIP_CLASS[cls], cls)}
    return {"class": cls, "reason": reason, "ci_level": str(float(level)), "ci": [lo, hi],
            "n_announcements": est["n"], "months": est["months"], "mean": est["mean"],
            "median": est["median"], "win_rate": est["win_rate"], "token_events": len(res),
            "missing": missing, "tipping_point": tip}


def groups(vs):
    """[(t0, announcement id, [views])] in t0 order, pre-epoch events left out."""
    g = {}
    for v in vs:
        ev = v["event"]
        if not ev.get("pre_epoch"):
            g.setdefault((ev["t0_ms"], ev["announcement_id"]), []).append(v)
    return [(k[0], k[1], g[k]) for k in sorted(g)]


def _comparable(group):
    return any(classify(v)[0] == "comparable" for v in group[2])


def final_comparable(vs):
    """Comparable announcements with every token-event final, in t0 order, up to the first
    announcement still pending, so a decision set never skips an earlier event."""
    out = []
    for g in groups(vs):
        if any(pending(v) for v in g[2]):
            break
        if _comparable(g):
            out.append(g)
    return out


def decision_due(vs, now_ms):
    """(trigger, announcement groups) once the single decision is due, else None: the first 40
    final comparable announcements, or on 2027-11-05 every comparable announcement with t0
    before it (once all are final), whichever comes first."""
    final = final_comparable(vs)
    if len(final) >= uc.DECISION_EVENTS and final[uc.DECISION_EVENTS - 1][0] < uc.DECISION_DATE_MS:
        return "%d comparable announcements" % uc.DECISION_EVENTS, final[:uc.DECISION_EVENTS]
    if now_ms >= uc.DECISION_DATE_MS:
        before = [g for g in groups(vs) if g[0] < uc.DECISION_DATE_MS]
        if any(pending(v) for g in before for v in g[2]):
            return None
        return "deadline %s" % uc.iso(uc.DECISION_DATE_MS)[:10], [g for g in before if _comparable(g)]
    return None


def report(chosen):
    """The A4 class over the whole comparable cohort of the chosen announcements, with the
    flag counts and, descriptive only, the same resolution on its start_unknown = false subset."""
    comparable = [v for g in chosen for v in g[2] if classify(v)[0] == "comparable"]
    known = [v for v in comparable if not start_unknown(v["event"])]
    return {**resolve(results(comparable)), "flags": flags(comparable),
            "start_known_subset": {"descriptive_only": True, **resolve(results(known))}}


def resolution_record(rid, kind, trigger, chosen, now_ms):
    return {"rid": rid, "kind": kind, "trigger": trigger, "at_ms": now_ms, "at": uc.iso(now_ms),
            "prereg": uc.PREREG_ID, "announcements": [g[1] for g in chosen],
            "descriptive_only": kind != "decision", **report(chosen)}


# --- status ------------------------------------------------------------------------------

def _median_max(values):
    values = [x for x in values if x is not None]
    if not values:
        return None
    return {"n": len(values), "median": statistics.median(values), "max": max(values)}


def event_row(v):
    ev = v["event"]
    cohort, reasons = classify(v)
    status, n = outcome(v)
    marks = {}
    for cp in ("cp30m", "cp4h"):
        rec = v[cp] if filled(v[cp]) else v["late"][cp]
        if filled(v["entry"]) and rec is not None:
            marks[cp] = {"status": v[cp]["status"] if v[cp] else None,
                         "late": rec.get("status") == "late",
                         "net_ex_funding": uv.mark_return(v["entry"], rec)}
    return {"event_id": ev["event_id"], "token": ev["token"], "t0": ev["t0"],
            "cohort": cohort, "reasons": reasons, "outcome": status,
            "start_unknown": start_unknown(ev), "krw_market_first_seen_ms": krw_first_seen_ms(v),
            "timing": ev["timing"], "hl": (v["hl"] or {}).get("status"),
            "coin": (v["hl"] or {}).get("coin"),
            "entry": (v["entry"] or {}).get("status"), "exit": (v["exit"] or {}).get("status"),
            "funding": (v["funding"] or {}).get("status"),
            "net_return": n and n["net_return"], "net_ex_funding_return": n and n["net_ex_funding_return"],
            "funding_usdc": n and n["funding"], "marks": marks,
            "exit_late": v["late"]["exit"] is not None,
            "mae": (v["excursion"] or {}).get("mae"), "mfe": (v["excursion"] or {}).get("mfe"),
            "excursion": _excursion_label(v["excursion"]),
            "evidence": [{"version": r["version"], "effect": r["effect"],
                          "trading_start_ms": r["trading_start_ms"]} for r in v["evidence"]],
            "detect_latency_ms": ev["detected_ms"] - ev["t0_ms"],
            "tree_lag_ms": (None if ev["published_at"] is None
                            else uc.ms(ev["received_at"]) - uc.ms(ev["published_at"])),
            "entry_delay_ms": (v["entry"] or {}).get("delay_ms")}


def _excursion_label(rec):
    """`ok`, or the partial / missing status with its candle counts: partial extrema are kept
    under partial_* names and never shown as the MAE / MFE."""
    if rec is None:
        return None
    if rec["status"] == "ok":
        return "ok"
    out = "%s %d/%d candles" % (rec["status"], rec.get("candles", 0), rec.get("expected", 0))
    if rec["status"] == "partial":
        out += ", partial MAE %s, partial MFE %s" % (_pct(rec["partial_mae"]), _pct(rec["partial_mfe"]))
    return out


def _missing_actions(v):
    out = [a for a in ("entry", "cp30m", "cp4h", "exit") if (v[a] or {}).get("status") == "missing"]
    if (v["funding"] or {}).get("status") == "missing":
        out.append("funding")
    if (v["excursion"] or {}).get("status") in ("missing", "partial"):
        out.append("excursion_" + v["excursion"]["status"])
    for a in ("hl", "binance"):
        rec = v[a] or {}
        if rec and (rec.get("status") == "unknown" or (a == "binance" and rec.get("market_pre_t0") is None)):
            out.append(a + "_unknown")
    return out


def summarize(ledger, markets, now_ms, health=None):
    vs = views(ledger)
    rows = [event_row(v) for v in vs]
    cohorts = {}
    for r in rows:
        c = cohorts.setdefault(r["cohort"], {"n": 0, "reasons": {}})
        c["n"] += 1
        for reason in r["reasons"]:
            c["reasons"][reason] = c["reasons"].get(reason, 0) + 1
    open_pos = [r for r, v in zip(rows, vs) if filled(v["entry"]) and v["exit"] is None]
    closed = [r for r, v in zip(rows, vs) if filled(v["entry"]) and v["exit"] is not None]
    events = {r["event_id"] for r in rows}
    noticed = {e["notice_id"] for e in ledger.kind("event")}
    unclassified = [u for u in ledger.kind("unclassified") if u["notice_id"] not in noticed]
    audits = ledger.kind("audit")
    audited = {a["new_rid"] for a in audits}
    polls = markets.kind("market_poll")
    final = final_comparable(vs)
    live = [r for r in rows if r["cohort"] not in ("pre_epoch",)]
    live_vs = [v for v in vs if not v["event"].get("pre_epoch")]
    return {
        "now": uc.iso(now_ms), "prereg": uc.PREREG_ID, "epoch": ledger.get("epoch"),
        "records": len(ledger), "skipped_lines": ledger.skipped + markets.skipped,
        "archive": health,
        "upbit": {"last_poll": polls[-1]["obs_ms"] if polls else None,
                  "last_n_krw": polls[-1]["n_krw"] if polls else None,
                  "polls_24h": sum(p["obs_ms"] >= now_ms - uc.DAY_MS for p in polls)},
        "events": rows, "n_events": len(events), "cohorts": cohorts,
        "flags": {"all": flags(live_vs),
                  "comparable": flags([v for v in live_vs if classify(v)[0] == "comparable"])},
        "open_positions": open_pos, "closed": closed,
        "latency": {"detection_ms": _median_max([r["detect_latency_ms"] for r in live]),
                    "tree_lag_ms": _median_max([r["tree_lag_ms"] for r in live]),
                    "entry_delay_ms": _median_max([r["entry_delay_ms"] for r in live])},
        "misses": {"outcomes": [{"event_id": v["event"]["event_id"], "missing": _missing_actions(v)}
                                for v in vs if _missing_actions(v)],
                   "missed_markets": [a for a in audits if a["status"] == "missed"],
                   "pending_audits": [m["market"] for m in markets.kind("new_market")
                                      if m["rid"] not in audited]},
        "unclassified": [{"notice_id": u["notice_id"], "title": u["title"], "reason": u["reason"],
                          "received_at": u["received_at"]} for u in unclassified],
        "resolution": {"final_comparable_announcements": len(final),
                       "interim": report(final) if final else None,
                       "milestones": [ledger.get("milestone:%d" % m) for m in uc.MILESTONES
                                      if ledger.get("milestone:%d" % m)],
                       "decision": ledger.get("decision")},
    }


def _pct(x):
    return "-" if x is None else "%+.2f%%" % (100 * float(x))


def _s(ms_value):
    return "-" if ms_value is None else "%.0f s" % (ms_value / 1000)


def _res_line(r):
    lo, hi = r["ci"]
    ci = "-" if lo is None else "[%s, %s]" % (_pct(lo), _pct(hi))
    tip = (r.get("tipping_point") or {}).get("note")
    return ("%s (%s): %d announcements over %d months, mean %s, median %s, win %s, 95%% CI %s;"
            " missing token-events %d%s" % (
                r["class"], r["reason"], r["n_announcements"], r["months"], _pct(r["mean"]),
                _pct(r["median"]), "-" if r["win_rate"] is None else "%.0f%%" % (100 * r["win_rate"]),
                ci, r["missing"]["token_events"], "; tipping point: " + tip if tip else ""))


def _flag_line(f):
    return "start_unknown %d, krw_market_first_seen %d (of %d token-events)" % (
        f["start_unknown"], f["krw_market_first_seen"], f["token_events"])


def _res_lines(head, r):
    """The decision metric over the whole comparable cohort, then the descriptive subset."""
    out = [head + _res_line(r)]
    if r.get("flags"):
        out.append("    flags: " + _flag_line(r["flags"]))
    if r.get("start_known_subset"):
        out.append("    start_unknown=false subset (descriptive only): "
                   + _res_line(r["start_known_subset"]))
    return out


def status_lines(s):
    ep = s["epoch"]
    lines = ["upbit-fade-forward status at %s (prereg %s). PAPER ONLY: no orders, no keys." % (
        s["now"], s["prereg"]),
        "t0 is Tree's published_at: a Tree-clock cohort, checked only for plausibility against"
        " Upbit's clock. Funding cashflows are estimated (oraclePx observed, not a receipt).",
        "epoch %s; ledger %d records%s" % (
            uc.iso(ep["start_ms"]) if ep else "not started", s["records"],
            ", %d unreadable line(s) skipped" % s["skipped_lines"] if s["skipped_lines"] else "")]
    for source, h in (s["archive"] or {}).items():
        lines.append("archive %-16s last OK poll %s; open gaps %d; gaps in 7 d %d" % (
            source, h["last_ok"] or "never", len(h["open_gaps"]), h["gaps_7d"]))
        for reason, start, detail in h["open_gaps"]:
            lines.append("  gap open: %s since %s %s" % (reason, start, detail or ""))
    up = s["upbit"]
    lines.append("upbit market/all: last snapshot %s (%s KRW markets), %d snapshots in 24 h" % (
        uc.iso(up["last_poll"]) if up["last_poll"] else "never",
        "-" if up["last_n_krw"] is None else up["last_n_krw"], up["polls_24h"]))
    lines.append("")
    lines.append("OPEN PAPER POSITIONS (%d)" % len(s["open_positions"]))
    for r in s["open_positions"]:
        lines.append("  %s %s cohort %s, entry %s (delay %s), marks %s" % (
            r["event_id"], r["coin"], r["cohort"], r["entry"], _s(r["entry_delay_ms"]),
            ", ".join("%s %s%s" % (k, _pct(m["net_ex_funding"]), " late" if m["late"] else "")
                      for k, m in r["marks"].items()) or "-"))
    lines.append("CLOSED (%d)" % len(s["closed"]))
    for r in s["closed"]:
        lines.append("  %s %s cohort %s: net %s (ex funding %s, funding %s USDC %s), exit %s%s,"
                     " +30m %s, +4h %s, MAE %s, MFE %s (excursion %s)" % (
                         r["event_id"], r["coin"], r["cohort"], _pct(r["net_return"]),
                         _pct(r["net_ex_funding_return"]), r["funding_usdc"] or "-",
                         r["funding"] or "-", r["exit"], " (late mark kept)" if r["exit_late"] else "",
                         _pct((r["marks"].get("cp30m") or {}).get("net_ex_funding")),
                         _pct((r["marks"].get("cp4h") or {}).get("net_ex_funding")),
                         _pct(r["mae"]), _pct(r["mfe"]), r["excursion"] or "pending"))
    lines.append("COHORTS (%d token-events)" % s["n_events"])
    for name in ("comparable", "descriptive", "excluded", "ineligible", "pre_epoch"):
        c = s["cohorts"].get(name)
        if c:
            reasons = ", ".join("%s %d" % kv for kv in sorted(c["reasons"].items()))
            lines.append(("  %-11s %d" % (name, c["n"])) + ("  " + reasons if reasons else ""))
    fl = s["flags"]
    lines.append("  flags (descriptive): all %s; comparable %s" % (
        _flag_line(fl["all"]), _flag_line(fl["comparable"])))
    for r in s["events"]:
        seen = r["krw_market_first_seen_ms"]
        lines.append("  %s t0 %s %s %s, outcome %s, detected +%s, Tree lag %s, start %s, KRW market"
                     " first seen %s" % (
                         r["event_id"], r["t0"], r["cohort"], r["timing"], r["outcome"],
                         _s(r["detect_latency_ms"]), _s(r["tree_lag_ms"]),
                         "unknown" if r["start_unknown"] else "known",
                         "-" if seen is None else uc.iso(seen)))
    lat = s["latency"]
    lines.append("LATENCY " + "; ".join(
        "%s median %s max %s (n %d)" % (k, _s(v["median"]), _s(v["max"]), v["n"]) if v else "%s -" % k
        for k, v in lat.items()))
    m = s["misses"]
    lines.append("MISSES: %d event(s) with missing records, %d missed market addition(s), %d audit(s)"
                 " pending" % (len(m["outcomes"]), len(m["missed_markets"]), len(m["pending_audits"])))
    for o in m["outcomes"]:
        lines.append("  %s: %s" % (o["event_id"], ", ".join(o["missing"])))
    for a in m["missed_markets"]:
        lines.append("  missed: %s first seen %s with no matched notice" % (
            a["market"], uc.iso(a["first_seen_ms"])))
    lines.append("UNCLASSIFIED (%d, never traded)" % len(s["unclassified"]))
    for u in s["unclassified"]:
        lines.append("  %s %s (%s) %s" % (u["received_at"], u["notice_id"], u["reason"], u["title"]))
    res = s["resolution"]
    lines.append("RESOLUTION (comparable cohort, 24 h net, A4 calendar-month block bootstrap at 95%%):"
                 " %d final comparable announcement(s); decision at %d or on %s" % (
                     res["final_comparable_announcements"], uc.DECISION_EVENTS,
                     uc.iso(uc.DECISION_DATE_MS)[:10]))
    if res["interim"]:
        lines += _res_lines("  interim, not the decision: ", res["interim"])
    for ms_rec in res["milestones"]:
        lines += _res_lines("  %s report (descriptive only, %s): " % (ms_rec["trigger"], ms_rec["at"]),
                            ms_rec)
    if res["decision"]:
        d = res["decision"]
        lines += _res_lines("  DECISION (%s, %s), whole comparable cohort: " % (d["trigger"], d["at"]), d)
    else:
        lines.append("  decision: not yet taken")
    return lines
