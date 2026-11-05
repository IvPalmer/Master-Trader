"""Part C Phase 2 (#229): returns from a frozen manifest, reports and the mechanical resolution.

    python3 nes_report.py compute --manifest PATH --expect-sha256 HEX --out DIR --code-commit SHA
        [--supplement PATH --supplement-sha256 HEX]
    python3 nes_report.py resolution --results DIR
    python3 nes_report.py verify-resolution --prereg PATH --results DIR

compute exits 2 on a manifest SHA-256 mismatch (before any request) and 3 when the
data.binance.vision files for the last needed day are not published yet.
"""
import argparse
import json
import math
import statistics
import sys
import time
from collections import OrderedDict
from fractions import Fraction
from pathlib import Path

import nes_util as nu
import nes_klines as nk
import nes_manifest as nm
import nes_returns as nr

DIRECTION = {nm.DELISTING: "short", nm.LONG: "long", nm.FADE: "short"}
LABEL = "proxy result"
PUBLISH_LAG_DAYS = 2           # a day's file is read only once two full UTC days have passed
DOWNLOAD_GAP_S = 0.25


class TooEarly(Exception):
    pass


class _Memo:
    """Keeps the last few day files, so overlapping BTC windows are fetched once."""

    def __init__(self, fetcher, keep=32):
        self.fetcher, self.keep, self.cache = fetcher, keep, OrderedDict()

    def __call__(self, req):
        if req.url in self.cache:
            self.cache.move_to_end(req.url)
            return self.cache[req.url]
        resp = self.fetcher(req)
        if resp.status in (200, 404):
            self.cache[req.url] = resp
            if len(self.cache) > self.keep:
                self.cache.popitem(last=False)
        return resp


def _candidates(manifest, study):
    out = []
    for e in manifest["events"]:
        s = nm.study_status(e, study)
        if s.startswith("candidate:"):
            out.append((e, s[len("candidate:"):]))
    return out


def _guard(fetcher, t0s, wall):
    if not t0s:
        return
    last = max(nu.utc_date(t + 5 * nu.DAY_MS) for t in t0s)
    ready_ms = nu.ms_from_iso(last + "T00:00:00+00:00") + PUBLISH_LAG_DAYS * nu.DAY_MS
    if wall() * 1000 < ready_ms:
        raise TooEarly("files through %s are read from %s on" % (last, nu.iso_ms(ready_ms)))
    resp = nk._get(nk.kline_url("um", "BTCUSDT", last), fetcher, lambda s: None)
    if resp.status == 404:
        raise TooEarly("BTCUSDT %s is not published yet" % last)


def _series(key, fetcher, work_dir, disk_ok, sleep):
    market, symbol, t0 = key
    path = work_dir / "series" / ("%s-%s-%d.json" % (market, symbol, t0))
    if path.exists():
        return nk.load_series(path)
    s = nk.fetch_series(market, symbol, t0, fetcher, work_dir, disk_ok, sleep=sleep)
    sleep(DOWNLOAD_GAP_S)
    nk.store_series(path, s)
    return s


def _num(x):
    return None if x is None else float(x)


def _crit(anns):
    """nr.criteria with its values as floats, for presentation; the verdict uses the exact values."""
    c = nr.criteria(anns)
    return {**c, "median": _num(c["median"]), "half_medians": [_num(m) for m in c["half_medians"]],
            "sum": _num(c["sum"]), "top_decile_share": _num(c["top_decile_share"])}


def _stored(obj):
    """Exact returns are stored as rational strings ("-29/10000"), which Fraction reads back,
    so the resolution recomputed from a results file is exact too."""
    if isinstance(obj, Fraction):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _stored(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stored(v) for v in obj]
    return obj


def _pct(values, q):
    vs = sorted(values)
    return vs[max(0, math.ceil(q * len(vs)) - 1)] if vs else None


def _estimates(events):
    est = lambda **kw: {h: nr.estimate(nr.announcements(events, h, **kw)) for h in nr.HORIZONS_MS}  # noqa: E731
    return {"base": est(), "stress": est(key="net_stress"), "no_halt": est(allow_halted=False),
            "leak_included": est(include_leaked=True), "btc_adjusted": est(key="btc_adj_net")}


def _by_year(events, horizon=nr.PRIMARY):
    anns = nr.announcements(events, horizon)
    years = sorted({nu.utc_date(a[0])[:4] for a in anns})
    return {y: nr.estimate([a for a in anns if nu.utc_date(a[0])[:4] == y]) for y in years}


def _summary(results, study, manifest, counts):
    events = results
    primary = {h: _crit(nr.announcements(events, h)) for h in nr.HORIZONS_MS}
    cls, cls_reasons = nr.classify(events)
    out = {"classification": cls, "classification_reasons": cls_reasons,
           "estimates": _estimates(events), "by_year_4h": _by_year(events),
           "missing_announcements_4h": len(nr.missing_announcements(events)),
           "primary": primary,
           "leak_included": {h: _crit(nr.announcements(events, h, include_leaked=True))
                             for h in nr.HORIZONS_MS},
           "stress": {h: _crit(nr.announcements(events, h, key="net_stress"))
                      for h in nr.HORIZONS_MS},
           "btc_adjusted_median": {h: _crit(nr.announcements(events, h, key="btc_adj_net"))["median"]
                                   for h in nr.HORIZONS_MS},
           "bootstrap_ci_4h": [_num(x) for x in nr.bootstrap_median_ci(
               [a[2] for a in nr.announcements(events, nr.PRIMARY)])],
           "t60_median": {}}
    group_key = "venue" if study == nm.LONG else ("kind" if study == nm.DELISTING else None)
    if group_key:
        groups = sorted({r[group_key] for r in events})
        out["by_" + group_key] = {g: {h: _crit(nr.announcements(
            [r for r in events if r[group_key] == g], h)) for h in nr.HORIZONS_MS} for g in groups}
    for h in nr.HORIZONS_MS:
        t60 = [{**r, "horizons": {h: {"net": r["t60"].get(h), "exit_status": "ok"}}}
               for r in events if r["t60"]]
        out["t60_median"][h] = _crit(nr.announcements(t60, h))["median"]
    if DIRECTION[study] == "short":
        out["mae"] = {}
        for h in nr.HORIZONS_MS:
            vals = [r["horizons"][h]["mae"] for r in events if nr._usable(r) and not r["leaked"]
                    and r["horizons"][h]["mae"] is not None]
            out["mae"][h] = {"n": len(vals), "p50": _pct(vals, 0.5), "p90": _pct(vals, 0.9),
                             "max": max(vals) if vals else None}
    if any(r.get("supplement") for r in events):
        frozen = [r for r in events if not r.get("supplement")]
        fcls, freasons = nr.classify(frozen)
        out["frozen_only"] = {"classification": fcls, "classification_reasons": freasons,
                              "estimate_4h": nr.estimate(nr.announcements(frozen, nr.PRIMARY))}
        out["supplement_events"] = sum(bool(r.get("supplement")) for r in events)
    statuses = [r["status"] for r in events]
    out["status_counts"] = {s: statuses.count(s) for s in ("ok", "halted", "missing", "unresolved")}
    out["status_counts"]["leaked"] = sum(bool(r["leaked"]) for r in events)
    return out


def _load_checked(path, expect_sha256):
    body = Path(path).read_bytes()
    sha = nu.sha256_bytes(body)
    if sha != expect_sha256:
        raise ValueError("%s sha256 %s != expected %s" % (Path(path).name, sha, expect_sha256))
    return json.loads(body), sha


def compute(manifest_path, expect_sha256, out_dir, fetcher, work_dir, disk_ok, code_commit,
            wall=time.time, sleep=time.sleep, supplement=None):
    """`supplement` = (path, sha256) of the A4 Upbit supplement manifest: events O11 excluded
    only through a Binance notice published after t0. They join the Upbit decision sets."""
    manifest, sha = _load_checked(manifest_path, expect_sha256)
    supp, supp_sha = _load_checked(*supplement) if supplement else (None, None)
    out_dir, work_dir = Path(out_dir), Path(work_dir)
    per_study = {s: _candidates(manifest, s) for s in manifest["studies"]}
    if supp:
        for s in per_study:
            if s in supp["studies"]:
                per_study[s] += [({**e, "supplement": True}, v) for e, v in _candidates(supp, s)]
    t0s = {e["t0_ms"] for c in per_study.values() for e, _ in c}
    memo = _Memo(fetcher)
    _guard(memo, t0s, wall)
    keys = set()
    for cands in per_study.values():
        for e, _ in cands:
            p = e["binance"]["proxy"]
            keys |= {(p["market"], p["symbol"], e["t0_ms"]), ("um", "BTCUSDT", e["t0_ms"])}
    loaded = {k: _series(k, memo, work_dir, disk_ok, sleep) for k in sorted(keys, key=lambda k: (k[2], k))}
    computed_at = nu.iso_ms(int(wall() * 1000))
    docs = {}
    for study, cands in per_study.items():
        events = []
        for e, venue in cands:
            p = e["binance"]["proxy"]
            events.append(nr.evaluate(e, loaded[(p["market"], p["symbol"], e["t0_ms"])],
                                      loaded[("um", "BTCUSDT", e["t0_ms"])], DIRECTION[study], venue))
        counts = nm.manifest_counts(manifest, study)
        legacy, legacy_reasons = nr.verdict(counts, events)
        summary = _summary(events, study, manifest, counts)
        doc = {"study": study, "label": LABEL, "direction": DIRECTION[study],
               "verdict": summary["classification"], "reasons": summary["classification_reasons"],
               "legacy_gates": {"verdict": legacy, "reasons": legacy_reasons},
               "counts": counts, "coverage": float(nr.coverage(counts, events)),
               "manifest_sha256": sha, "supplement_sha256": supp_sha,
               "manifest_code_commit": manifest.get("code_commit"),
               "code_commit": code_commit, "computed_at": computed_at,
               **summary, "events": events}
        nu.write_atomic(out_dir / ("results-%s.json" % study), nu.canonical_bytes(_stored(doc)))
        nu.write_atomic(out_dir / ("report-%s.md" % study), report_md(doc).encode("utf-8"))
        docs[study] = doc
    return docs


# --- report --------------------------------------------------------------------------

def _f(x):
    return "n/a" if x is None else "%+.4f" % x


def _crit_line(name, c):
    halves = ", ".join(_f(m) for m in c["half_medians"])
    share = "n/a" if c["top_decile_share"] is None else "%.3f" % c["top_decile_share"]
    return "| %s | %d | %s | %s | %s |" % (name, c["n"], _f(c["median"]), halves, share)


def report_md(doc):
    study = doc["study"]
    L = ["# %s: %s" % (study, LABEL), "",
         "**Verdict (%s, A4): %s**" % (LABEL, doc["verdict"]), ""]
    L += ["- %s" % r for r in doc["reasons"]]
    L += ["- legacy gates (diagnostic only, A4): %s (%s)" % (doc["legacy_gates"]["verdict"],
                                                         "; ".join(doc["legacy_gates"]["reasons"]))]
    if "frozen_only" in doc:
        fo = doc["frozen_only"]
        L += ["- frozen candidates only (without the %d supplement events): %s, +4h mean %s"
              % (doc["supplement_events"], fo["classification"], _f(fo["estimate_4h"]["mean"]))]
    L += ["", "## Announcement-level mean net return (A4; interval %.2f%%, calendar-month blocks)"
          % (100 * float(nr.CI_LEVEL)), "",
          "| set | horizon | n | months | mean | interval | median | win rate |",
          "|---|---|---|---|---|---|---|---|"]
    for name, by_h in doc["estimates"].items():
        for h, e in by_h.items():
            L.append("| %s | +%s | %d | %d | %s | [%s, %s] | %s | %s |" % (
                name, h, e["n"], e["months"], _f(e["mean"]), _f(e["ci"][0]), _f(e["ci"][1]),
                _f(e["median"]), "n/a" if e["win_rate"] is None else "%.0f%%" % (100 * e["win_rate"])))
    L += ["", "## By year (+4h, base cost)", "", "| year | n | mean | median | win rate |",
          "|---|---|---|---|---|"]
    for y, e in doc["by_year_4h"].items():
        L.append("| %s | %d | %s | %s | %.0f%% |" % (y, e["n"], _f(e["mean"]), _f(e["median"]),
                                                     100 * e["win_rate"]))
    L += ["", "- announcements with no usable +4h return: %d" % doc["missing_announcements_4h"], ""]
    c, sc = doc["counts"], doc["status_counts"]
    L += ["## Counts", "",
          "- candidates %d; unknown %d; Phase 1 missing %d; harvest shortfall %d; harvest complete %s"
          % (c["candidates"], c["unknown"], c["missing"], c["harvest_shortfall"], c["harvest_complete"]),
          "- Phase 2: ok %d, halted %d, missing %d, unresolved %d, leaked %d"
          % (sc["ok"], sc["halted"], sc["missing"], sc["unresolved"], sc["leaked"]),
          "- coverage (O13) %.4f" % doc["coverage"]]
    L += ["- excluded:%s %d" % kv for kv in c["excluded"].items()] + [""]
    table = ["| set | n | median | half medians | top-decile share |", "|---|---|---|---|---|"]
    L += ["## Announcement-level net returns (primary set: leak-excluded, 10 bps)", ""] + table
    L += [_crit_line("+%s" % h, doc["primary"][h]) for h in nr.HORIZONS_MS] + [""]
    for key in ("by_venue", "by_kind"):
        if key in doc:
            L += ["## By %s" % key[3:], ""] + table
            for g, hs in doc[key].items():
                L += [_crit_line("%s +%s" % (g, h), hs[h]) for h in nr.HORIZONS_MS]
            L.append("")
    L += ["## Sensitivities", ""] + table
    L += [_crit_line("leak included +%s" % h, doc["leak_included"][h]) for h in nr.HORIZONS_MS]
    L += [_crit_line("25 bps +%s" % h, doc["stress"][h]) for h in nr.HORIZONS_MS] + [""]
    lo, hi = doc["bootstrap_ci_4h"]
    L += ["- bootstrap 95%% CI of the +4 h median (10,000 resamples, seed 229): [%s, %s]" % (_f(lo), _f(hi)),
          "- BTC-adjusted medians: " + ", ".join("+%s %s" % (h, _f(v)) for h, v in
                                                 doc["btc_adjusted_median"].items()),
          "- t+60 s entry (descriptive): " + ", ".join("+%s %s" % (h, _f(v)) for h, v in
                                                       doc["t60_median"].items()), ""]
    if "mae" in doc:
        L += ["## MAE: maximum adverse excursion from 1m highs (descriptive)", "",
              "| horizon | n | p50 | p90 | max |", "|---|---|---|---|---|"]
        L += ["| +%s | %d | %s | %s | %s |" % (h, m["n"], _f(m["p50"]), _f(m["p90"]), _f(m["max"]))
              for h, m in doc["mae"].items()] + [""]
    L += ["## Limitations", "",
          "- Events come from notice titles, read from the current CMS versions; later edits cannot be ruled out.",
          "- Hyperliquid funding is not modelled.",
          "- An intra-file candle gap is read as a halt; the no_halt row drops those exits.",
          "- Binance proxies are chosen by which day files exist through t0+2 d (measurement source,"
          " not event selection).",
          "- Returns are Binance proxy prices, not Hyperliquid or venue fills: a %s." % LABEL,
          "- The Upbit notices were harvested from the operator's Mac."]
    if study in (nm.LONG, nm.FADE):
        L += ["- The Upbit long and fade share their Hyperliquid events; on that subset the fade is the"
              " long's gross return with the sign flipped, minus costs. A failed long plus a passed fade"
              " is one finding, not two confirmations (spec §6.2)."]
    return "\n".join(L) + "\n"


# --- resolution ----------------------------------------------------------------------

def resolution(results):
    """Recomputed from the stored events only (the mechanical resolution, A4 rule)."""
    events = results["events"]
    verdict, reasons = nr.classify(events)
    e = nr.estimate(nr.announcements(events, nr.PRIMARY))
    return {"verdict": verdict, "reasons": reasons, "label": LABEL,
            "primary_4h": {k: e[k] for k in ("n", "mean", "ci", "median", "win_rate")},
            "manifest_sha256": results["manifest_sha256"], "code_commit": results["code_commit"],
            "computed_at": results["computed_at"]}


def _results(results_dir, study):
    p = Path(results_dir) / ("results-%s.json" % study)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def verify_resolution(prereg_path, results_dir):
    reg = json.loads(Path(prereg_path).read_text(encoding="utf-8"))["preregistrations"]
    problems, checked = [], 0
    for study in nm.STUDIES:
        results = _results(results_dir, study)
        entry = next((e for e in reg if e.get("id") == study), None)
        if results is None:
            if entry and entry.get("resolution") is not None:
                problems.append("%s: resolution recorded but no results file" % study)
            continue
        checked += 1
        expected = resolution(results)
        if results["verdict"] != expected["verdict"]:
            problems.append("%s: stored verdict %s != recomputed %s"
                            % (study, results["verdict"], expected["verdict"]))
        got = entry.get("resolution") if entry else None
        if got != json.loads(json.dumps(expected)):
            problems.append("%s: prereg resolution differs from the results" % study)
    if not checked:
        problems.append("no results files in %s" % results_dir)
    return problems


def main(argv=None, fetcher=None, wall=time.time, sleep=time.sleep):
    ap = argparse.ArgumentParser(prog="nes_report.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compute")
    for flag in ("--manifest", "--expect-sha256", "--out", "--code-commit"):
        c.add_argument(flag, required=True)
    c.add_argument("--work")
    c.add_argument("--supplement")
    c.add_argument("--supplement-sha256")
    r = sub.add_parser("resolution")
    r.add_argument("--results", required=True)
    v = sub.add_parser("verify-resolution")
    v.add_argument("--prereg", required=True)
    v.add_argument("--results", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "compute":
        work = Path(args.work) if args.work else Path(args.out) / "work"
        try:
            docs = compute(Path(args.manifest), args.expect_sha256, Path(args.out),
                           fetcher or nk.kline_fetch, work, lambda: nu.disk_ok(work),
                           args.code_commit, wall=wall, sleep=sleep,
                           supplement=((args.supplement, args.supplement_sha256)
                                       if args.supplement else None))
        except ValueError as e:
            print("refusing: %s" % e, file=sys.stderr)
            return 2
        except TooEarly as e:
            print("too early: %s" % e, file=sys.stderr)
            return 3
        for study, doc in docs.items():
            print("%s: %s (%s)" % (study, doc["verdict"], "; ".join(doc["reasons"])))
        return 0
    if args.cmd == "resolution":
        for study in nm.STUDIES:
            results = _results(args.results, study)
            if results is not None:
                print(json.dumps({study: resolution(results)}, ensure_ascii=False, indent=1))
        return 0
    problems = verify_resolution(Path(args.prereg), Path(args.results))
    for p in problems:
        print(p)
    if problems:
        return 1
    print("resolution matches the results")
    return 0


if __name__ == "__main__":
    sys.exit(main())
