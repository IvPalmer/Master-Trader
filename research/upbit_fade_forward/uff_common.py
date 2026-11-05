"""Frozen constants and shared helpers of the Upbit KRW listing fade paper forward monitor (#229).

Importing this module puts `research/news_event_studies` on sys.path, and through `nes_util`
also `research/news_archive`, so the Part A and Part C modules are reused by import.

Every rule constant below is frozen in preregistration `upbit-krw-fade-forward-2026-11`
(ft_userdata/preregistrations.json); tests/test_upbit_fade_forward_prereg.py pins them to it.
Design: docs/superpowers/specs/2026-11-05-upbit-fade-forward-design.md.
"""
import sys
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
NES_DIR = RESEARCH / "news_event_studies"
if str(NES_DIR) not in sys.path:
    sys.path.insert(0, str(NES_DIR))

import nes_util as nu  # noqa: E402  (also puts research/news_archive on sys.path)

PREREG_ID = "upbit-krw-fade-forward-2026-11"
DATA_DIR = HERE / "data"
ARCHIVE_PATH = RESEARCH / "news_archive" / "data" / "archive.sqlite"

MINUTE_MS, HOUR_MS, DAY_MS = nu.MINUTE_MS, nu.HOUR_MS, nu.DAY_MS

# --- detection and t0 ---------------------------------------------------------------
ARCHIVE_POLL_MS = 15_000              # read the archive cursors every 15 s
UPBIT_POLL_MS = 5 * MINUTE_MS         # market/all audit snapshot every 5 min
TREE_LAG_MAX_MS = 5 * MINUTE_MS       # received_at - published_at above this: timing unverified

# --- eligibility at t0 --------------------------------------------------------------
KRW_SNAPSHOT_MAX_AGE_MS = 15 * MINUTE_MS   # no market/all snapshot this close before t0: unknown
BINANCE_PRIOR_MS = DAY_MS                  # a Binance new-listing notice in [t0 - 24 h, t0] excludes
MARKET_WINDOW_MS = 10 * MINUTE_MS          # Binance 1m klines must show trading in [t0 - 10 min, t0)

# --- paper trade --------------------------------------------------------------------
ENTRY_OFFSET_MS = 5 * MINUTE_MS       # entry at max(t0 + 5 min, detection)
TIMELY_MS = 2 * MINUTE_MS             # comparable only when filled within 2 min of t0 + 5 min
DEADLINE_MS = 10 * MINUTE_MS          # every scheduled book action, after its nominal time
HOLD_MS = DAY_MS                      # exit at entry + 24 h
CHECKPOINTS = (("cp30m", 30 * MINUTE_MS), ("cp4h", 4 * HOUR_MS))   # book-walk marks of q
NOTIONAL_USDC = Decimal("100")
FEE_BPS = Decimal("4.5")              # taker, on each leg's actual notional; no extra slippage
BOOK_MAX_AGE_MS = 5_000               # a book older than 5 s is rejected for that attempt
ORACLE_TOL_MS = 60_000                # oraclePx observed within +-60 s of each funding hour

# --- resolution ---------------------------------------------------------------------
HORIZON = "24h"
CI_LEVEL = Fraction(95, 100)          # passed explicitly; the A4 helper defaults to 98.33%
DECISION_EVENTS = 40
DECISION_DATE_MS = int(datetime(2027, 11, 5, tzinfo=timezone.utc).timestamp() * 1000)
MILESTONES = (20, 30)                 # descriptive reports only

# --- operation (Claude's calls; not rules of the measurement) ------------------------
HL_GAP_S = 1.0                        # at most one Hyperliquid info request per second
HL_BACKOFF_S = 2.0                    # a 429 starts a 2 s, 4 s, ... backoff
HL_BACKOFF_MAX_S = 120.0
ATTEMPT_GAP_MS = 10_000               # spacing of book attempts for one scheduled action
RETRY_GAP_MS = 60_000                 # spacing of retries for history reads
BINANCE_FINAL_MS = HOUR_MS            # the Binance-prior check is repeated at t0 + 1 h
HISTORY_GIVEUP_MS = DAY_MS            # funding, Binance klines, HL leak: retry this long
CANDLE_GIVEUP_MS = 2 * DAY_MS         # Hyperliquid keeps only the last 5000 1m candles
FUNDING_SETTLE_MS = 10 * MINUTE_MS    # wait this long after the exit for the last rate record
LATE_TRY_MS = 6 * HOUR_MS             # a missed mark or exit is recovered as `late` within this
AUDIT_BEFORE_MS = 7 * DAY_MS          # a new KRW market matches a notice in [-7 d, +24 h]
AUDIT_AFTER_MS = DAY_MS


def iso(ms):
    return None if ms is None else nu.iso_ms(ms)


def ms(iso_text):
    return None if iso_text is None else nu.ms_from_iso(iso_text)


def floor_minute(t_ms):
    return t_ms - t_ms % MINUTE_MS
