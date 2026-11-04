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
    args = ap.parse_args(argv)
    fetcher = fetcher or na_fetch.fetch
    if args.cmd == "binance":
        return _binance(args, fetcher, wall, sleep)
    return 1


if __name__ == "__main__":
    sys.exit(main())
