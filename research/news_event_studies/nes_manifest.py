"""Part C Phase 1 (#229): outcome-blind event manifests. No prices are read here.

    python3 nes_manifest.py build --cms DIR --upbit DIR --out DIR --code-commit SHA

Writes delisting-manifest.json and upbit-manifest.json (canonical bytes) and
build-report.txt, and prints both SHA-256s. Exit 5: titles need an operator decision
(nothing is written); exit 6: a venue source failed and the build stopped.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

import nes_util as nu
import na_sources
import nes_classify as nc
import nes_harvest as nh
import nes_venues as nv

STUDIES = ("binance-delisting-reaction-2026-11", "upbit-krw-listing-reaction-2026-11",
           "upbit-krw-listing-fade-2026-11")
DELISTING, LONG, FADE = STUDIES
WINDOW_UTC = ["2023-01-01T00:00:00Z", "2026-11-01T00:00:00Z"]
OVERLAP_MS = nu.DAY_MS          # O12
BINANCE48_MS = nu.DAY_MS        # O11, inclusive


class NeedsReview(Exception):
    def __init__(self, items):
        super().__init__("%d title(s) need an operator decision" % len(items))
        self.items = items


# --- loaders -------------------------------------------------------------------------

def _meta(raw_dir):
    return json.loads((raw_dir / "harvest_meta.json").read_text(encoding="utf-8"))


def _verified(raw_dir, files):
    """Every file listed in harvest_meta.json, checked against its recorded sha256."""
    out = {}
    for rel, sha in sorted(files.items()):
        path = raw_dir / rel
        if not path.is_file():
            raise ValueError("%s is listed in harvest_meta.json but missing" % rel)
        body = path.read_bytes()
        if nu.sha256_bytes(body) != sha:
            raise ValueError("%s does not match its sha256 in harvest_meta.json" % rel)
        out[rel] = body
    return out


def _release(a):
    t = a.get("releaseDate")
    return t if isinstance(t, int) and not isinstance(t, bool) else None


def _closing_order(rel):
    name = rel.rsplit("/", 1)[-1]
    return 1 if name == "closing.json" else int(name[len("closing-"):-len(".json")])


def _upbit_t0(n):
    """O1: Upbit t0 is `first_listed_at` (KST); `listed_at` moves on edits and is not used."""
    iso = na_sources.to_utc(n.get("first_listed_at"), "kst")
    return nu.ms_from_iso(iso) if iso else None


def _page_no(rel):
    return int(rel.rsplit("page-", 1)[1][:-len(".json")])


def _scan_complete(pages):
    """Pages 1..k reach before the window, or the last page by total (else a short page)."""
    total = pages[1].total if 1 in pages else None
    n = 0
    while n + 1 in pages:
        n += 1
        page = pages[n]
        if any(_release(a) is not None and _release(a) < nu.WINDOW_START_MS for a in page.articles):
            return True
        if total is not None and n >= math.ceil(total / nh.CMS_PAGE_SIZE):
            return True
        if total is None and len(page.articles) < nh.CMS_PAGE_SIZE:
            return True
    return False


def load_cms(raw_dir):
    raw_dir = Path(raw_dir)
    meta = _meta(raw_dir)
    catalogs, files = {}, {}
    for cid, cat in sorted(meta.get("catalogs", {}).items()):
        bodies = _verified(raw_dir, cat.get("files", {}))
        files.update({rel: nu.sha256_bytes(b) for rel, b in bodies.items()})
        numbered = {_page_no(r): nh.parse_cms_page(bodies[r]) for r in bodies if "/page-" in r}
        pages = [numbered[k] for k in sorted(numbered)]
        closing_rels = sorted((r for r in bodies if "/closing" in r), key=_closing_order)
        closings = [nh.parse_cms_page(bodies[r]) for r in closing_rels]
        merged = nh.merge_articles(pages + closings)
        catalogs[int(cid)] = {
            "name": cat.get("catalog_name"), "aborted": cat.get("aborted"),
            "articles": sorted(merged.values(), key=lambda a: (_release(a) or 0, str(a["id"]))),
            "completeness": nh.completeness(merged, closings[0]) if closings else None,
            "scan_complete": _scan_complete(numbered)}
    return {"catalogs": catalogs, "aborted": meta.get("aborted"), "files": files}


def load_upbit(raw_dir):
    raw_dir = Path(raw_dir)
    meta = _meta(raw_dir)
    bodies = _verified(raw_dir, meta.get("files", {}))
    pages = [nh.parse_upbit_page(bodies[r]) for r in sorted(bodies) if r.startswith("list/page-")]
    closing = nh.parse_upbit_page(bodies["list/closing.json"]) if "list/closing.json" in bodies else None
    notices = {}
    for p in pages + ([closing] if closing else []):
        for n in p.notices:
            notices.setdefault(str(n["id"]), n)
    details = {}
    for rel in sorted(bodies):
        if rel.startswith("detail/"):
            d = nh.parse_upbit_detail(bodies[rel])
            details[str(d["id"])] = d
    total = closing.total_count if closing else None
    completeness = {"unique": len(notices), "total": total, "total_reported": total is not None,
                    "shortfall": max(0, total - len(notices)) if total is not None else 0}
    complete = (closing is not None and total is not None and not meta.get("blocked")
                and bool(meta.get("finished_at")))
    return {"notices": sorted(notices.values(), key=lambda n: (_upbit_t0(n) or 0, str(n["id"]))),
            "details": details, "completeness": completeness, "complete": complete,
            "host_label": meta.get("host_label"),
            "files": {rel: nu.sha256_bytes(b) for rel, b in bodies.items()}}


# --- events --------------------------------------------------------------------------

def _in_window(t0):
    return nu.WINDOW_START_MS <= t0 < nu.WINDOW_END_MS


def _event(aid, t0, title, kind, token, exclusion=None, ref=None, start=None):
    return {"announcement_id": aid, "t0_ms": t0, "t0": nu.iso_ms(t0), "title": title,
            "kind": kind, "token": token, "exclusion": exclusion, "exclusion_ref": ref,
            "trading_start_ms": start, "hl": None, "binance": None}


def _review(ref, t0, title, reason, **extra):
    return {"ref": ref, "t0": nu.iso_ms(t0) if t0 is not None else None, "title": title,
            "reason": reason, **extra}


def _sorted(events):
    return sorted(events, key=lambda e: (e["t0_ms"], e["announcement_id"], e["token"]))


def delisting_events(articles161, scan49):
    """Catalog-161 events: classify, O12 overlap over the full harvest, then the window."""
    review, rows = [], []
    for a in sorted(articles161, key=lambda a: (_release(a) or 0, int(a["id"]))):
        t0, title, aid = _release(a), a.get("title") or "", "binance:%s" % a["id"]
        if t0 is None:
            review.append(_review(aid, None, title, "no_release_date"))
            continue
        cls = nc.classify_binance(title)
        if cls.kind == "unclassified":
            if _in_window(t0):
                review.append(_review(aid, t0, title, "unclassified_title"))
            continue
        if cls.kind.startswith("excluded:"):
            continue
        rows += [(t0, aid, title, cls.kind, tok) for tok in cls.tokens]
    last_kept, events = {}, []
    for t0, aid, title, kind, tok in rows:
        prev = last_kept.get(tok)
        if prev is not None and t0 - prev[0] <= OVERLAP_MS:
            ev = _event(aid, t0, title, kind, tok, "same_token_overlap", prev[1])
        else:
            last_kept[tok] = (t0, aid)
            ev = _event(aid, t0, title, kind, tok)
        if _in_window(t0):
            events.append(ev)
    in161 = {str(a["id"]) for a in articles161}
    for a in scan49:                                                      # O17
        t0, title = _release(a), a.get("title") or ""
        if t0 is not None and _in_window(t0) and "Monitoring Tag" in title:
            review.append(_review("binance:%s" % a["id"], t0, title, "monitoring_tag_in_catalog_49",
                                  also_in_catalog_161=str(a["id"]) in in161))
    if review:
        raise NeedsReview(review)
    return _sorted(events)


def _binance48(cms48, token, t0):
    for a in sorted(cms48, key=lambda a: (_release(a) or 0, int(a["id"]))):
        t = _release(a)
        if t is not None and abs(t - t0) <= BINANCE48_MS and nc.mentions_token(a.get("title") or "", token):
            return "binance:%s" % a["id"]
    return None


def upbit_events(notices, details, cms48):
    """KRW additions: O8 and O9 replayed over the full history, then the window, O11, O10."""
    review, events, on_krw = [], [], {}
    rows = []
    for n in notices:
        t0 = _upbit_t0(n)
        if t0 is None:
            review.append(_review("upbit:%s" % n["id"], None, n.get("title") or "", "no_publish_time"))
            continue
        rows.append((t0, int(n["id"]), n))
    for t0, nid, n in sorted(rows, key=lambda r: (r[0], r[1])):
        title, aid = n.get("title") or "", "upbit:%d" % nid
        adds, ends = nc.upbit_addition(title), nc.upbit_end(title)
        for tok in ends or ():
            on_krw.pop(tok, None)
        if not adds:
            if _in_window(t0) and nc.upbit_needs_review(title):
                review.append(_review(aid, t0, title, "upbit_title_needs_review"))
            continue
        detail = details.get(str(nid))
        body = detail.get("body") if detail else None
        krw = nc.upbit_krw_membership(title, body)
        for tok in adds:
            if krw.get(tok) is not True:       # O8 per token: not shown to join KRW
                if krw.get(tok) is None and _in_window(t0):
                    review.append(_review(aid, t0, title, "upbit_market_unstated", token=tok))
                continue
            prior = on_krw.get(tok)
            if prior is None:
                on_krw[tok] = aid
            if not _in_window(t0):
                continue
            start = nc.upbit_trading_start_ms(body, tok, t0, title) if body is not None else None
            exclusion, ref = None, None
            if prior is not None:
                exclusion, ref = "already_on_krw", prior
            elif _binance48(cms48, tok, t0):
                exclusion, ref = "binance48_overlap", _binance48(cms48, tok, t0)
            elif start is not None and start < t0:
                exclusion = "began_before_notice"
            events.append(_event(aid, t0, title, "krw_addition", tok, exclusion, ref, start))
    if review:
        raise NeedsReview(review)
    return _sorted(events)


# --- status --------------------------------------------------------------------------

def _reaches_venues(e):
    return not e["exclusion"] and not (e["kind"] == "krw_addition" and e["trading_start_ms"] is None)


def study_status(event, study):
    if study not in STUDIES:
        raise ValueError("unknown study %r" % study)
    if event["exclusion"]:
        return "excluded:" + event["exclusion"]
    upbit = event["kind"] == "krw_addition"
    if upbit and event["trading_start_ms"] is None:
        return "unknown"
    b = event["binance"] or {}
    if upbit and not b.get("on_binance_pre_t0"):
        return "excluded:not_on_binance"
    hl = (event["hl"] or {}).get("status")
    if hl not in ("eligible", "ineligible"):
        return "unknown"
    spot = b.get("spot_symbol_pre_t0")
    if hl == "eligible":
        venue = "hyperliquid"
    elif study == DELISTING:
        return "excluded:no_hl"
    elif study == FADE:
        return "excluded:spot_only" if spot else "excluded:no_hl"
    elif spot:
        venue = "binance_spot"
    else:
        return "excluded:futures_only"
    if not b.get("proxy"):
        return "missing"
    return "candidate:" + venue


def manifest_counts(manifest, study):
    if study not in manifest["studies"]:
        raise ValueError("%s is not in this manifest" % study)
    statuses = [study_status(e, study) for e in manifest["events"]]
    excluded = {}
    for s in statuses:
        if s.startswith("excluded:"):
            excluded[s[len("excluded:"):]] = excluded.get(s[len("excluded:"):], 0) + 1
    return {"candidates": sum(s.startswith("candidate:") for s in statuses),
            "unknown": statuses.count("unknown"), "missing": statuses.count("missing"),
            "excluded": dict(sorted(excluded.items())),
            "harvest_shortfall": manifest["harvest_shortfall"],
            "harvest_complete": manifest["harvest_complete"]}


# --- build ---------------------------------------------------------------------------

def _add_facts(events, index, hl_client, probe):
    for e in events:
        if not _reaches_venues(e):
            continue
        e["binance"] = nv.binance_facts(e["token"], e["t0_ms"], probe)
        if e["kind"] == "krw_addition" and not e["binance"]["on_binance_pre_t0"]:
            continue
        e["hl"] = nv.hl_facts(e["token"], e["t0_ms"], index, hl_client)


def _manifest(studies, events, inputs, complete, shortfall, code_commit):
    return {"manifest_version": 1, "studies": list(studies), "window_utc": WINDOW_UTC,
            "code_commit": code_commit, "hl_evidence": nv.HL_EVIDENCE, "inputs": inputs,
            "harvest_complete": complete, "harvest_shortfall": shortfall,
            "events": _sorted(events)}


def build(cms_dir, upbit_dir, hl_client, probe, code_commit):
    cms, up = load_cms(cms_dir), load_upbit(upbit_dir)
    cats = cms["catalogs"]
    arts = lambda cid: cats[cid]["articles"] if cid in cats else []   # noqa: E731
    review = []
    try:
        dev = delisting_events(arts(161), arts(49))
    except NeedsReview as e:
        review += e.items
    try:
        uev = upbit_events(up["notices"], up["details"], arts(48))
    except NeedsReview as e:
        review += e.items
    if review:
        raise NeedsReview(review)
    meta_body = hl_client.meta()
    _add_facts(dev + uev, nv.hl_meta_index(meta_body), hl_client, probe)

    comp = lambda cid: cats[cid]["completeness"] if cid in cats else None   # noqa: E731
    full = lambda cid: bool(comp(cid) and comp(cid)["total_reported"])     # noqa: E731
    shortfall = lambda cid: comp(cid)["shortfall"] if comp(cid) else 0     # noqa: E731
    cms_ok = not cms["aborted"] and not any(c.get("aborted") for c in cats.values())
    completeness = {"binance:%d" % cid: comp(cid) for cid in (161, 48) if cid in cats}
    common = {"binance_cms_files": cms["files"], "hl_meta_sha256": nu.sha256_bytes(meta_body),
              "completeness": completeness}
    scanned49 = 49 in cats and cats[49]["scan_complete"]
    completeness["binance:49_scanned"] = scanned49
    dm = _manifest([DELISTING], dev, common, cms_ok and full(161) and scanned49,
                   shortfall(161), code_commit)
    up_inputs = {**common, "upbit_files": up["files"], "upbit_host_label": up["host_label"],
                 "completeness": {**completeness, "upbit:list": up["completeness"]}}
    um = _manifest([LONG, FADE], uev, up_inputs, cms_ok and full(48) and up["complete"],
                   shortfall(48) + up["completeness"]["shortfall"], code_commit)
    return dm, um


# --- report and CLI ------------------------------------------------------------------

def _report_lines(e, studies):
    statuses = {study_status(e, s) for s in studies}
    tag = "%s %s" % (e["token"], e["announcement_id"])
    out = []
    if e["exclusion"]:
        line = "%s %s" % (e["exclusion"], tag)
        if e["exclusion_ref"]:
            line += " (%s)" % e["exclusion_ref"]
        if e["exclusion"] == "began_before_notice":
            line += " start=%s" % nu.iso_ms(e["trading_start_ms"])
        out.append(line)
    if (e["hl"] or {}).get("reason") == "never_in_meta":
        out.append("never_in_meta %s" % tag)
    if "excluded:not_on_binance" in statuses:
        out.append("not_on_binance %s" % tag)
    if "missing" in statuses:
        out.append("missing %s" % tag)
    if "unknown" in statuses:
        why = "no_start" if e["trading_start_ms"] is None and e["kind"] == "krw_addition" \
            else (e["hl"] or {}).get("reason", "no_hl_facts")
        out.append("unknown %s %s" % (tag, why))
    return ["%s  %s" % (line, e["title"]) for line in out]


def build_report(dm, um):
    lines = ["Part C Phase 1 build report (#229). Counts and identifiers only; no prices.", ""]
    for m in (dm, um):
        for study in m["studies"]:
            c = manifest_counts(m, study)
            lines.append("%s: candidates %d, unknown %d, missing %d, harvest_shortfall %d, "
                         "harvest_complete %s" % (study, c["candidates"], c["unknown"], c["missing"],
                                                  c["harvest_shortfall"], c["harvest_complete"]))
            lines += ["  excluded:%s %d" % kv for kv in c["excluded"].items()]
    lines += ["", "completeness: " + json.dumps(um["inputs"]["completeness"], sort_keys=True),
              "upbit host: %s" % um["inputs"]["upbit_host_label"]]
    for m in (dm, um):
        lines += ["", "events to check (%s):" % ", ".join(m["studies"])]
        for e in m["events"]:
            lines += ["  " + line for line in _report_lines(e, m["studies"])]
    return "\n".join(lines) + "\n"


def main(argv=None, hl_client=None, probe=None):
    ap = argparse.ArgumentParser(prog="nes_manifest.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    for flag in ("--cms", "--upbit", "--out", "--code-commit"):
        b.add_argument(flag, required=True)
    args = ap.parse_args(argv)
    hl_client = hl_client or nv.HlClient(nh._bounded_fetch, time.sleep, time.time)
    probe = probe or nv.FileProbe(nh._bounded_fetch, time.sleep)
    try:
        dm, um = build(Path(args.cms), Path(args.upbit), hl_client, probe, args.code_commit)
    except NeedsReview as e:
        print("needs review: %d title(s); no manifest written" % len(e.items))
        for it in e.items:
            print("  %s %s %s  %s" % (it["reason"], it["ref"], it["t0"], it["title"]))
        return 5
    except (nv.VenueAborted, nv.ProbeError) as e:
        print("build stopped: %s" % e, file=sys.stderr)
        return 6
    out = Path(args.out)
    for name, m in (("delisting-manifest.json", dm), ("upbit-manifest.json", um)):
        body = nu.canonical_bytes(m)
        nu.write_atomic(out / name, body)
        print("%s sha256 %s" % (name, nu.sha256_bytes(body)))
    nu.write_atomic(out / "build-report.txt", build_report(dm, um).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
