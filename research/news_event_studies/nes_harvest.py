"""Phase 1 harvesters for the Part C event studies (#229). No prices are read here.

binance: full Binance CMS catalogs (161 delisting, 48 listing) and a scan of catalog 49,
    run on the VPS through Part A's shared BinanceLimiter on the archive's own state file.
    The harvester also keeps OWN_GAP_S between its own requests, so it takes at most one
    slot in three and the archive's polls stay under its outage threshold (plan C5).
upbit: the Upbit trade-notice list and the in-window notice details, run from the
    operator's Mac (Cloudflare answers the VPS IP with 403).

Raw bodies are written as received; harvest_meta.json records each file's sha256, the
request times, suspensions, errors and completeness (O16).
"""
import argparse
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import nes_util
from nes_util import Req, iso_ms, sha256_bytes, write_atomic

import na_fetch
import na_sources

CMS_PAGE_SIZE = 50
OWN_GAP_S = 540
MAX_HARVEST_S = 72 * 3600
MAX_PAGE_FAILURES = 5        # consecutive non-block failures of one page
MAX_PAGES = 1000             # guard against an API that ignores pageNo
SUSPENSION_SAME_S = 60       # suspended_until values this close are one suspension


@dataclass
class CmsPage:
    catalog_id: int
    catalog_name: "str | None"
    total: "int | None"
    articles: list


def cms_url(catalog_id, page_no):
    return na_sources.CMS_URL + "?type=1&pageNo=%d&pageSize=50&catalogId=%d" % (
        page_no, catalog_id)


def parse_cms_page(body):
    j = json.loads(body)
    if not isinstance(j, dict) or j.get("success") is not True:
        raise ValueError("binance cms: success is not true")
    cats = (j.get("data") or {}).get("catalogs") or []
    if not cats or not isinstance(cats[0], dict):
        raise ValueError("binance cms: no catalog in the response")
    c = cats[0]
    total = c.get("total")
    if isinstance(total, bool) or not isinstance(total, int):
        total = None
    arts = [a for a in (c.get("articles") or [])
            if isinstance(a, dict) and a.get("id") is not None]
    return CmsPage(int(c.get("catalogId")), c.get("catalogName"), total, arts)


def merge_articles(pages):
    out = {}
    for p in pages:
        for a in p.articles:
            out.setdefault(str(a["id"]), a)
    return out


def completeness(merged, closing):
    total = closing.total
    unique = len(merged)
    return {"unique": unique, "total": total, "total_reported": total is not None,
            "shortfall": max(0, total - unique) if total is not None else 0}


class HarvestAborted(Exception):
    pass


def _iso_s(t):
    return iso_ms(int(round(t * 1000)))


class CmsHarvester:
    def __init__(self, limiter, fetcher, wall, sleep, out_dir):
        self.limiter, self.fetcher = limiter, fetcher
        self.wall, self.sleep = wall, sleep
        self.out = Path(out_dir)
        self.meta_path = self.out / "harvest_meta.json"
        if self.meta_path.exists():
            self.meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        else:
            self.meta = {"first_request": None, "first_request_s": None, "suspensions": [],
                         "suspended_until_s": [], "aborted": None, "catalogs": {}}
        self.meta["aborted"] = None
        for c in self.meta["catalogs"].values():
            c["aborted"] = None
        self.last_own = None

    # -- bookkeeping ---------------------------------------------------------------
    def _cat(self, cid):
        c = self.meta["catalogs"].setdefault(str(cid), {
            "catalog_name": None, "pages": [], "completeness": None, "requests": [],
            "suspensions": [], "errors": [], "aborted": None, "files": {}})
        return c

    def _save(self):
        write_atomic(self.meta_path, json.dumps(self.meta, indent=1, sort_keys=True).encode())

    def _abort(self, cid, reason):
        self.meta["aborted"] = reason
        self._cat(cid)["aborted"] = reason
        self._save()
        raise HarvestAborted(reason)

    def _count_suspension(self, cid, until):
        seen = self.meta["suspended_until_s"]
        if any(abs(until - u) <= SUSPENSION_SAME_S for u in seen):
            return
        seen.append(until)
        self.meta["suspensions"].append(_iso_s(until))
        self._cat(cid)["suspensions"].append(_iso_s(until))
        self._save()
        if len(seen) >= 2:
            self._abort(cid, "second suspension")

    # -- requests ------------------------------------------------------------------
    def _wait_slot(self, cid):
        while True:
            now = self.wall()
            first = self.meta["first_request_s"]
            if first is not None and now - first > MAX_HARVEST_S:
                self._abort(cid, "72 h without completing")
            until = self.limiter.suspended_until(now)
            if until is not None:
                self._count_suspension(cid, until)
                self.sleep(until - now + 1)
                continue
            if self.last_own is not None and now - self.last_own < OWN_GAP_S:
                self.sleep(OWN_GAP_S - (now - self.last_own))
                continue
            if self.limiter.try_acquire(now):
                return now
            self.sleep(1)

    def _request(self, cid, url):
        """One attempt. Returns (body, CmsPage), or None after a block or an error."""
        cat = self._cat(cid)
        t = self._wait_slot(cid)
        if self.meta["first_request_s"] is None:
            self.meta["first_request_s"] = t
            self.meta["first_request"] = _iso_s(t)
        self.last_own = t
        cat["requests"].append(_iso_s(t))
        try:
            resp = self.fetcher(Req("GET", url, None, na_sources.BINANCE_HEADERS))
        except na_fetch.FetchError as e:
            cat["errors"].append({"at": _iso_s(t), "url": url, "error": str(e)[:200]})
            self._save()
            return None
        if na_fetch.is_block_signal(resp):
            self.limiter.suspend(self.wall())
            cat["errors"].append({"at": _iso_s(t), "url": url, "block": resp.status})
            self._save()
            return "block"
        try:
            if resp.status != 200:
                raise ValueError("HTTP %d" % resp.status)
            page = parse_cms_page(resp.body)
        except ValueError as e:
            cat["errors"].append({"at": _iso_s(t), "url": url, "error": str(e)[:200]})
            self._save()
            return None
        self._save()
        return resp.body, page

    def _fetch(self, cid, page_no, fname):
        failures = 0
        while True:
            got = self._request(cid, cms_url(cid, page_no))
            if got == "block":
                continue                      # the suspension count decides
            if got is None:
                failures += 1
                if failures >= MAX_PAGE_FAILURES:
                    self._abort(cid, "page errors")
                continue
            body, page = got
            rel = "cat%d/%s" % (cid, fname)
            write_atomic(self.out / rel, body)
            cat = self._cat(cid)
            cat["files"][rel] = sha256_bytes(body)
            self._save()
            return page

    def _page(self, cid, page_no):
        fname = "page-%04d.json" % page_no
        path = self.out / ("cat%d" % cid) / fname
        cat = self._cat(cid)
        if path.exists():
            body = path.read_bytes()
            cat["files"]["cat%d/%s" % (cid, fname)] = sha256_bytes(body)
            page = parse_cms_page(body)
        else:
            page = self._fetch(cid, page_no, fname)
        if page_no not in cat["pages"]:
            cat["pages"].append(page_no)
        if page.catalog_name and not cat["catalog_name"]:
            cat["catalog_name"] = page.catalog_name
        return page

    # -- public --------------------------------------------------------------------
    def harvest(self, catalog_id):
        """Every page of the catalog, then a fresh closing page 1 (O16)."""
        p1 = self._page(catalog_id, 1)
        n_pages = math.ceil(p1.total / CMS_PAGE_SIZE) if p1.total is not None else None
        pages, page_no = [p1], 1
        while True:
            more = (n_pages is not None and page_no < n_pages) or (
                len(pages[-1].articles) >= CMS_PAGE_SIZE)
            if not more:
                break
            page_no += 1
            if page_no > MAX_PAGES:
                self._abort(catalog_id, "page cap")
            pages.append(self._page(catalog_id, page_no))
        closing = self._fetch(catalog_id, 1, "closing.json")
        comp = completeness(merge_articles(pages + [closing]), closing)
        cat = self._cat(catalog_id)
        cat["completeness"] = comp
        if closing.catalog_name:
            cat["catalog_name"] = closing.catalog_name
        self._save()
        return {"catalog_id": catalog_id, "catalog_name": cat["catalog_name"],
                "pages": len(pages), "completeness": comp}

    def scan(self, catalog_id, stop_before_ms):
        """Pages from 1 until the first page whose oldest article predates stop_before_ms."""
        page_no, oldest = 0, None
        while True:
            page_no += 1
            if page_no > MAX_PAGES:
                self._abort(catalog_id, "page cap")
            page = self._page(catalog_id, page_no)
            dates = [a.get("releaseDate") for a in page.articles
                     if isinstance(a.get("releaseDate"), int)]
            if dates:
                oldest = min(dates)
            if not dates or oldest < stop_before_ms or len(page.articles) < CMS_PAGE_SIZE:
                break
        cat = self._cat(catalog_id)
        self._save()
        return {"catalog_id": catalog_id, "catalog_name": cat["catalog_name"],
                "pages": page_no, "oldest_ms": oldest}


# ---- Upbit (operator's Mac) ----------------------------------------------------------

UPBIT_GAP_S = 10.0
# Probe on #229 (2026-11-04): the plain detail URL returns JSON with the text in data.body.
UPBIT_DETAIL_URL = "https://api-manager.upbit.com/api/v1/announcements/%d"
UPBIT_BODY_KEY = "body"


@dataclass
class UpbitPage:
    total_count: "int | None"
    total_pages: "int | None"
    notices: list


def _int_or_none(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def parse_upbit_page(body):
    j = json.loads(body)
    if not isinstance(j, dict) or j.get("success") is not True:
        raise ValueError("upbit: success is not true")
    d = j.get("data") or {}
    notices = [n for n in (d.get("notices") or [])
               if isinstance(n, dict) and n.get("id") is not None]
    return UpbitPage(_int_or_none(d.get("total_count")), _int_or_none(d.get("total_pages")),
                     notices)


def parse_upbit_detail(body):
    j = json.loads(body)
    if not isinstance(j, dict) or j.get("success") is not True:
        raise ValueError("upbit detail: success is not true")
    d = j.get("data") or {}
    text = d.get(UPBIT_BODY_KEY)
    if d.get("id") is None or not isinstance(text, str):
        raise ValueError("upbit detail: no id or body")
    return {"id": d["id"], "title": d.get("title"), "body": text,
            "first_listed_at": d.get("first_listed_at"), "listed_at": d.get("listed_at")}


def notice_ms(n):
    """Publish time (O1: first_listed_at, KST) as epoch ms, or None."""
    iso = na_sources.to_utc(n.get("first_listed_at") or n.get("listed_at"), "kst")
    return nes_util.ms_from_iso(iso) if iso else None


class HarvestBlocked(Exception):
    pass


class UpbitHarvester:
    """Single attempt per request, at least UPBIT_GAP_S apart. A block signal or any
    other failure writes the meta and stops the run; a rerun skips saved files."""

    def __init__(self, fetcher, wall, sleep, out_dir, host_label):
        self.fetcher, self.wall, self.sleep = fetcher, wall, sleep
        self.out = Path(out_dir)
        self.meta_path = self.out / "harvest_meta.json"
        if self.meta_path.exists():
            self.meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        else:
            self.meta = {"files": {}, "runs": []}
        self.meta.update(host_label=host_label, blocked=None, finished_at=None,
                         started_at=_iso_s(wall()))
        self.last = None

    def _save(self):
        write_atomic(self.meta_path, json.dumps(self.meta, indent=1, sort_keys=True,
                                                ensure_ascii=False).encode())

    def _stop(self, reason):
        self.meta["blocked"] = reason
        self._save()
        raise HarvestBlocked(reason)

    def _get(self, url, rel, parse):
        if self.last is not None:
            wait = UPBIT_GAP_S - (self.wall() - self.last)
            if wait > 0:
                self.sleep(wait)
        self.last = self.wall()
        try:
            resp = self.fetcher(Req("GET", url, None, na_sources.JSON_HEADERS))
        except na_fetch.FetchError as e:
            self._stop("error: %s: %s" % (url, str(e)[:200]))
        if na_fetch.is_block_signal(resp):
            self._stop("block: HTTP %d %s" % (resp.status, url))
        try:
            if resp.status != 200:
                raise ValueError("HTTP %d" % resp.status)
            parsed = parse(resp.body)
        except ValueError as e:
            self._stop("error: %s: %s" % (url, e))
        write_atomic(self.out / rel, resp.body)
        self.meta["files"][rel] = sha256_bytes(resp.body)
        self._save()
        return parsed

    def _saved_or_get(self, url, rel, parse):
        path = self.out / rel
        if path.exists():
            body = path.read_bytes()
            self.meta["files"][rel] = sha256_bytes(body)
            return parse(body)
        return self._get(url, rel, parse)

    def run(self, detail_from_ms, detail_to_ms):
        p1 = self._saved_or_get(na_sources.UPBIT_URL % 1, "list/page-01.json",
                                parse_upbit_page)
        pages = [p1]
        for n in range(2, (p1.total_pages or 1) + 1):
            pages.append(self._saved_or_get(na_sources.UPBIT_URL % n,
                                            "list/page-%02d.json" % n, parse_upbit_page))
        closing = self._get(na_sources.UPBIT_URL % 1, "list/closing.json", parse_upbit_page)
        notices = {}
        for p in pages + [closing]:
            for n in p.notices:
                notices.setdefault(str(n["id"]), n)
        total = closing.total_count
        self.meta["list"] = {"unique": len(notices), "total": total,
                             "total_reported": total is not None,
                             "shortfall": max(0, total - len(notices)) if total is not None
                             else 0}
        wanted = [k for k, n in notices.items()
                  if (notice_ms(n) is not None
                      and detail_from_ms <= notice_ms(n) < detail_to_ms)]
        self.meta["detail_ids"] = wanted
        self._save()
        for k in wanted:
            self._saved_or_get(UPBIT_DETAIL_URL % int(k), "detail/%s.json" % k,
                               parse_upbit_detail)
        self.meta["finished_at"] = _iso_s(self.wall())
        self._save()
        return {"list": self.meta["list"], "detail_ids": wanted,
                "host_label": self.meta["host_label"]}


def _ids(s):
    return [int(x) for x in s.split(",") if x.strip()] if s else []


def _binance(args, fetcher, wall, sleep):
    state = Path(args.limiter_state)
    if not state.parent.is_dir():
        print("refusing: limiter state directory %s does not exist; the harvester must "
              "share the archive's limiter" % state.parent, file=sys.stderr)
        return 2
    limiter = na_fetch.BinanceLimiter(str(state))
    h = CmsHarvester(limiter, fetcher, wall, sleep, Path(args.out))
    results = []
    try:
        for cid in _ids(args.harvest):
            results.append(h.harvest(cid))
            print(json.dumps(results[-1]), flush=True)
        for cid in _ids(args.scan):
            results.append(h.scan(cid, nes_util.WINDOW_START_MS))
            print(json.dumps(results[-1]), flush=True)
    except HarvestAborted as e:
        print("harvest aborted: %s" % e, file=sys.stderr)
        return 4
    return 0


def main(argv=None, fetcher=None, wall=time.time, sleep=time.sleep):
    ap = argparse.ArgumentParser(prog="nes_harvest.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("binance")
    b.add_argument("--harvest", default="")
    b.add_argument("--scan", default="")
    b.add_argument("--out", required=True)
    b.add_argument("--limiter-state", default=str(nes_util.ARCHIVE_LIMITER_STATE))
    u = sub.add_parser("upbit")
    u.add_argument("--out", required=True)
    u.add_argument("--host-label", required=True)
    args = ap.parse_args(argv)
    fetcher = fetcher or na_fetch.fetch
    if args.cmd == "binance":
        return _binance(args, fetcher, wall, sleep)
    h = UpbitHarvester(fetcher, wall, sleep, Path(args.out), args.host_label)
    try:
        res = h.run(nes_util.WINDOW_START_MS - nes_util.DAY_MS,
                    nes_util.WINDOW_END_MS + nes_util.DAY_MS)
    except HarvestBlocked as e:
        print("upbit harvest stopped: %s" % e, file=sys.stderr)
        return 3
    print(json.dumps({"list": res["list"], "details": len(res["detail_ids"])}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
