"""A4 supplement (#229): Upbit KRW additions that O11 dropped because of a later Binance notice.

O11 excludes an Upbit addition when a Binance new-listing notice (catalog 48) for the token
falls within 24 h either side of t0. When that notice was published after t0, a bot acting at
t0 could not have known of it, so the exclusion uses future information. Those events are
added back with their venue facts resolved exactly as Phase 1 resolves them (no price is read).
Events whose matching notice preceded t0 stay excluded: a bot can apply that rule.

    python3 nes_supplement.py build --manifest data/manifests/upbit-manifest.json \\
        --expect-sha256 HEX --cms data/binance_raw --out data/manifests --code-commit SHA
"""
import argparse
import json
import sys
import time
from pathlib import Path

import nes_harvest as nh
import nes_manifest as nm
import nes_util as nu
import nes_venues as nv

NAME = "upbit-supplement-manifest.json"


def readded(manifest, cms48):
    """The overlap-excluded events whose matching catalog-48 notice was published after t0."""
    release = {"binance:%s" % a["id"]: nm._release(a) for a in cms48}
    out = []
    for e in manifest["events"]:
        if e.get("exclusion") != "binance48_overlap":
            continue
        t = release.get(e["exclusion_ref"])
        if t is None:
            raise ValueError("%s: overlap notice %s not in the harvest" % (e["announcement_id"],
                                                                         e["exclusion_ref"]))
        if t <= e["t0_ms"]:
            continue
        start = e.get("trading_start_ms")
        exclusion = "began_before_notice" if start is not None and start < e["t0_ms"] else None
        out.append({**e, "exclusion": exclusion, "exclusion_ref": None, "binance": None, "hl": None,
                    "a4_readded_from": e["exclusion_ref"]})
    return out


def build(manifest_path, expect_sha256, cms_dir, hl_client, probe, code_commit):
    body = Path(manifest_path).read_bytes()
    sha = nu.sha256_bytes(body)
    if sha != expect_sha256:
        raise ValueError("manifest sha256 %s != expected %s" % (sha, expect_sha256))
    base = json.loads(body)
    cms = nm.load_cms(cms_dir)
    events = readded(base, cms["catalogs"][48]["articles"])
    nm._add_facts(events, nv.hl_meta_index(hl_client.meta()), hl_client, probe)
    m = nm._manifest(base["studies"], events, {"base_manifest_sha256": sha},
                     base["harvest_complete"], base["harvest_shortfall"], code_commit)
    m["a4_supplement"] = True
    return m


def main(argv=None, hl_client=None, probe=None):
    ap = argparse.ArgumentParser(prog="nes_supplement.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    for flag in ("--manifest", "--expect-sha256", "--cms", "--out", "--code-commit"):
        b.add_argument(flag, required=True)
    args = ap.parse_args(argv)
    hl_client = hl_client or nv.HlClient(nh._bounded_fetch, time.sleep, time.time)
    probe = probe or nv.FileProbe(nh._bounded_fetch, time.sleep)
    try:
        m = build(Path(args.manifest), args.expect_sha256, Path(args.cms), hl_client, probe,
                  args.code_commit)
    except ValueError as e:
        print("refusing: %s" % e, file=sys.stderr)
        return 2
    except (nv.VenueAborted, nv.ProbeError) as e:
        print("build stopped: %s" % e, file=sys.stderr)
        return 6
    body = nu.canonical_bytes(m)
    nu.write_atomic(Path(args.out) / NAME, body)
    for study in m["studies"]:
        statuses = [nm.study_status(e, study) for e in m["events"]]
        print("%s: %d re-added, %d candidates" % (study, len(statuses),
                                                 sum(s.startswith("candidate:") for s in statuses)))
    print("%s sha256 %s" % (NAME, nu.sha256_bytes(body)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
