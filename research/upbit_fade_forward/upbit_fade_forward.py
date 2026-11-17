#!/usr/bin/env python3
"""Upbit KRW listing fade: paper forward monitor (#229). It places no orders and holds no keys.

    python3 upbit_fade_forward.py run              # the service (systemd user unit)
    python3 upbit_fade_forward.py status [--json]  # positions, results, cohorts, latency,
                                                   # misses, unclassified notices, resolution

Rules: preregistration upbit-krw-fade-forward-2026-11 (ft_userdata/preregistrations.json);
design: docs/superpowers/specs/2026-11-05-upbit-fade-forward-design.md. Stdlib only.
"""
import argparse
import fcntl
import gzip
import json
import logging
import logging.handlers
import os
import shutil
import signal
import sqlite3
import sys
import time
from contextlib import closing, contextmanager

import uff_common as uc
import uff_detect as ud
import uff_ledger as ul
import uff_monitor as um
import uff_report as ur
import uff_venues as uv

TICK_S = 5.0
LOG = logging.getLogger("upbit-fade-forward")


class WriterLockHeld(Exception):
    pass


@contextmanager
def writer_lock(data_dir):
    with open(os.path.join(data_dir, "monitor.lock"), "a") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WriterLockHeld(data_dir) from None
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _gzip_rotator(source, dest):
    with open(source, "rb") as fi, gzip.open(dest, "wb") as fo:
        shutil.copyfileobj(fi, fo)
    os.remove(source)


def setup_logging(log_file):
    LOG.setLevel(logging.INFO)
    LOG.propagate = False
    for h in list(LOG.handlers):
        LOG.removeHandler(h)
        h.close()
    fmt = logging.Formatter("%(asctime)s [upbit-fade-forward] %(message)s", "%Y-%m-%dT%H:%M:%SZ")
    fmt.converter = time.gmtime
    fh = logging.handlers.TimedRotatingFileHandler(log_file, when="midnight", backupCount=14,
                                                   utc=True)
    fh.namer = lambda name: name + ".gz"
    fh.rotator = _gzip_rotator
    for h in (fh, logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        LOG.addHandler(h)


def build(data_dir, archive):
    hl = uv.Hyperliquid(uv.bounded_fetch, time.sleep, time.time)
    return um.Monitor(data_dir, archive, hl, uv.bounded_fetch, lambda: int(time.time() * 1000),
                      time.sleep, log=LOG.info)


def status(data_dir, archive, as_json=False):
    ledger = ul.Ledger(os.path.join(data_dir, "ledger.jsonl"))
    markets = ul.Ledger(os.path.join(data_dir, "upbit_markets.jsonl"))
    now = int(time.time() * 1000)
    health = None
    if os.path.exists(archive):
        try:
            with closing(ud.open_archive(archive)) as conn:
                health = ud.health(conn, now)
        except sqlite3.Error as e:
            print("archive unreadable: %s" % e)
    summary = ur.summarize(ledger, markets, now, health)
    if as_json:
        print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print("\n".join(ur.status_lines(summary)))
    return 0


def _term(signum, frame):
    raise SystemExit(0)


def main(argv=None):
    p = argparse.ArgumentParser(prog="upbit_fade_forward.py",
                                description="Upbit KRW listing fade paper forward monitor (#229)")
    p.add_argument("--data-dir", default=str(uc.DATA_DIR))
    p.add_argument("--archive", default=str(uc.ARCHIVE_PATH))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="the monitor loop (systemd)")
    st = sub.add_parser("status", help="positions, results, cohorts, latency, misses, resolution")
    st.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    if args.cmd == "status":
        return status(args.data_dir, args.archive, args.json)
    os.makedirs(args.data_dir, exist_ok=True)
    setup_logging(os.path.join(args.data_dir, "monitor.log"))
    try:
        with writer_lock(args.data_dir):
            mon = build(args.data_dir, args.archive)
            ep = mon.ledger.get("epoch")
            LOG.info("start: prereg %s, epoch %s, %d ledger records, archive %s" % (
                uc.PREREG_ID, ep["start"] if ep else "not yet", len(mon.ledger), args.archive))
            signal.signal(signal.SIGTERM, _term)
            try:
                while True:
                    mon.tick()
                    time.sleep(TICK_S)
            finally:
                LOG.info("stopping")
    except WriterLockHeld:
        print("upbit-fade-forward: another monitor holds %s/monitor.lock" % args.data_dir)
        return 3


if __name__ == "__main__":
    sys.exit(main())
