"""oracle.py — PointInTimeFeed + Slice + PriceOracle (the bounded window onto the world).

This module is the single source of truth for time conversion and the ONLY component that
reads the raw message / candle files. Every read path enforces invariant I1 (no future data
reachable) under the default `closed_minute` policy:

    a candle with open-time `t` is observable at decision time T (epoch-ms) iff
        t + 60000 <= T_ms
    i.e. ONLY fully-closed minutes are visible. Any query that would return or depend on a
    candle that violates this RAISES CausalityViolation — it does not return None, does not
    clamp, does not warn-and-continue.

Imports nothing in-package (per the §10 import DAG).
"""

from __future__ import annotations

import bisect
import datetime
import glob
import json
import os
from typing import Optional

MINUTE_MS = 60_000


# --------------------------------------------------------------------------- #
# Time helper — single source of truth for datetime|epoch-ms -> epoch-ms.     #
# --------------------------------------------------------------------------- #
def to_ms(T) -> int:
    """Convert a tz-aware datetime, an ISO-8601 string, OR an epoch-ms int/float to epoch-ms.

    The ONE conversion helper referenced by every module API (SPEC §1 time convention). ISO
    strings are accepted because the on-disk message `date` fields are ISO-8601 with +00:00 and
    flow straight from the feed into `at(T)`.
    """
    if isinstance(T, datetime.datetime):
        if T.tzinfo is None:
            raise ValueError("datetime T must be timezone-aware (UTC)")
        return int(T.timestamp() * 1000)
    if isinstance(T, str):
        dt = datetime.datetime.fromisoformat(T)
        if dt.tzinfo is None:
            raise ValueError("ISO string T must carry a timezone (e.g. +00:00)")
        return int(dt.timestamp() * 1000)
    if isinstance(T, bool):  # guard: bool is an int subclass
        raise TypeError("T must be datetime, ISO string, or epoch-ms number, got bool")
    if isinstance(T, (int, float)):
        return int(T)
    raise TypeError(f"T must be datetime, ISO string, or epoch-ms number, got {type(T)!r}")


def iso_of_ms(t_ms: int) -> str:
    """epoch-ms -> ISO-8601 UTC with +00:00 (for record/digest readability)."""
    return (
        datetime.datetime.fromtimestamp(t_ms / 1000, tz=datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "+00:00")
    )


# --------------------------------------------------------------------------- #
# Exceptions                                                                  #
# --------------------------------------------------------------------------- #
class CausalityViolation(Exception):
    """Raised on ANY attempt to read data at t > T (i.e. t + 60000 > T_ms).

    Carries (symbol, venue, requested_t_ms, T_ms) for forensics.
    """

    def __init__(self, symbol: str, venue: str, requested_t_ms: int, T_ms: int, detail: str = ""):
        self.symbol = symbol
        self.venue = venue
        self.requested_t_ms = requested_t_ms
        self.T_ms = T_ms
        msg = (
            f"CausalityViolation: {symbol}.{venue} requested candle open-time {requested_t_ms} "
            f"(closes at {requested_t_ms + MINUTE_MS}) but T_ms={T_ms}; "
            f"requires t+60000<=T_ms."
        )
        if detail:
            msg += f" [{detail}]"
        super().__init__(msg)


# --------------------------------------------------------------------------- #
# PriceOracle — bounded reader for one Slice/T.                               #
# --------------------------------------------------------------------------- #
class PriceOracle:
    """Bounded price reader. Constructed by PointInTimeFeed via a Slice; knows its own T_ms.

    Answers ONLY for candles whose minute has closed at/before T. Future RAISES.
    Holds a reference to the immutable per-(symbol,venue) candle arrays loaded once by the feed;
    it never re-reads files and never mutates them.
    """

    def __init__(self, feed: "PointInTimeFeed", T_ms: int):
        self._feed = feed
        self._T_ms = int(T_ms)

    # -- helpers ----------------------------------------------------------- #
    def _arr(self, symbol: str, venue: str):
        key = (symbol, venue)
        arr = self._feed._candles.get(key)
        if arr is None:
            raise KeyError(f"no candle file loaded for {symbol}.{venue}")
        return arr  # (times list ascending, rows list parallel)

    def _max_causal_open(self) -> int:
        """Greatest candle open-time that is fully closed at T: floor(T/60000)*60000 - 60000."""
        return (self._T_ms // MINUTE_MS) * MINUTE_MS - MINUTE_MS

    # -- public API -------------------------------------------------------- #
    def candle_at(self, symbol: str, t_ms: int, venue: str = "weex") -> dict:
        """Exact 1m candle whose open time == t_ms.

        RAISES CausalityViolation if t_ms + 60000 > T_ms (future / in-progress).
        RAISES KeyError if the minute is in-range but missing from the file (gap).
        """
        t_ms = int(t_ms)
        if t_ms + MINUTE_MS > self._T_ms:
            raise CausalityViolation(symbol, venue, t_ms, self._T_ms, "candle_at future/in-progress")
        times, rows = self._arr(symbol, venue)
        i = bisect.bisect_left(times, t_ms)
        if i < len(times) and times[i] == t_ms:
            return dict(rows[i])
        raise KeyError(f"{symbol}.{venue}: no candle at open-time {t_ms} (gap, in-range)")

    def last_candle(self, symbol: str, venue: str = "weex") -> dict:
        """Most recent CAUSAL candle (max t with t+60000 <= T_ms). RAISES LookupError if none."""
        times, rows = self._arr(symbol, venue)
        ceiling = self._max_causal_open()
        # rightmost open-time <= ceiling
        i = bisect.bisect_right(times, ceiling) - 1
        if i < 0:
            raise LookupError(f"{symbol}.{venue}: no causal candle at/before T_ms={self._T_ms}")
        return dict(rows[i])

    def last_price(self, symbol: str, venue: str = "weex") -> float:
        """Convenience: last_candle(...)['c'] — the 'current price snapshot <= T'."""
        return float(self.last_candle(symbol, venue)["c"])

    def window(self, symbol: str, a_ms: int, b_ms: int, venue: str = "weex") -> list:
        """Candles with a_ms <= t <= b_ms, ascending.

        RAISES CausalityViolation if b_ms + 60000 > T_ms (window extends into the future —
        refuse the WHOLE call, do not silently truncate). Empty list if the in-range slice
        has no candles.
        """
        a_ms = int(a_ms)
        b_ms = int(b_ms)
        if b_ms + MINUTE_MS > self._T_ms:
            raise CausalityViolation(symbol, venue, b_ms, self._T_ms, "window upper bound in future")
        times, rows = self._arr(symbol, venue)
        lo = bisect.bisect_left(times, a_ms)
        hi = bisect.bisect_right(times, b_ms)
        return [dict(rows[i]) for i in range(lo, hi)]

    def touched(self, symbol: str, level: float, side: str, since_ms: int, venue: str = "weex"):
        """First candle (ascending) in the causal window whose [l,h] range crosses `level`.

        Window = open-times in [since_ms, t_causal] where t_causal is the last CLOSED minute
        (the in-progress bar is excluded). `side` selects the crossing rule for a stop/target:
          - 'above' / short-SL / long-TP-up : touched iff h >= level
          - 'below' / long-SL / short-TP-down: touched iff l <= level
        Returns the crossing candle's open-time, or None if untouched in-window.
        RAISES CausalityViolation if since_ms + 60000 > T_ms (caller's start is in the future).
        """
        since_ms = int(since_ms)
        if since_ms + MINUTE_MS > self._T_ms:
            raise CausalityViolation(symbol, venue, since_ms, self._T_ms, "touched since_ms in future")
        ceiling = self._max_causal_open()
        if since_ms > ceiling:
            return None
        times, rows = self._arr(symbol, venue)
        lo = bisect.bisect_left(times, since_ms)
        hi = bisect.bisect_right(times, ceiling)
        up = side in ("above", "up", "short_sl", "long_tp")
        down = side in ("below", "down", "long_sl", "short_tp")
        if not (up or down):
            raise ValueError(f"unknown side {side!r} for touched()")
        for i in range(lo, hi):
            row = rows[i]
            if up and float(row["h"]) >= level:
                return int(row["t"])
            if down and float(row["l"]) <= level:
                return int(row["t"])
        return None

    @property
    def T_ms(self) -> int:
        return self._T_ms

    @property
    def t_causal_ms(self) -> int:
        """Open-time of the last fully-closed candle at T (max t with t+60000 <= T_ms).

        RAISES LookupError if no candle has closed yet (T before the grid starts).
        """
        c = self._max_causal_open()
        if c < 0:
            raise LookupError(f"no closed candle at T_ms={self._T_ms}")
        return c

    @property
    def symbols(self) -> list:
        return self._feed.symbols


# --------------------------------------------------------------------------- #
# Slice — immutable bounded view at one T.                                    #
# --------------------------------------------------------------------------- #
class Slice:
    """Immutable bounded view at T. The harness passes THIS — never the raw feed — downstream."""

    def __init__(self, feed: "PointInTimeFeed", T_ms: int, decision_msg_id: Optional[int]):
        self._feed = feed
        self._T_ms = int(T_ms)
        self._decision_msg_id = decision_msg_id
        self._oracle = PriceOracle(feed, T_ms)

    @property
    def T_ms(self) -> int:
        return self._T_ms

    @property
    def decision_msg_id(self):
        return self._decision_msg_id

    def messages(self, last_n: Optional[int] = None, within_ms: Optional[int] = None) -> list:
        """All messages with date < T, PLUS same-second messages (date == T) whose export-order
        index _idx <= the decision message's _idx. Ascending; each dict is the raw message PLUS an
        injected '_idx'. When decision_msg_id is set, that message is the LAST element returned and
        no same-second message posted after it leaks in. A message strictly after T is absent.

        Reproduces gen_fixtures.py INVARIANTS 1-3.

        WINDOWING (cost control, does NOT affect causality): `last_n` caps the result to the most
        recent N messages (the decision message always remains last); `within_ms` keeps only
        messages with date >= T - within_ms. Both are applied AFTER the strict <=T gate, so the
        window can only ever SHRINK the causal set — never add future data. The full (un-windowed)
        set is still what audit.py uses to verify cited ids; the window is purely what the prompt
        SHOWS the model, because the harness-owned ledger snapshot already carries older state.
        """
        msgs = self._feed._messages  # list of (date_ms, idx, msg-with-_idx) ascending by (date_ms, idx)
        T = self._T_ms
        out = []
        dec_idx = None
        if self._decision_msg_id is not None:
            dec_idx = self._feed._idx_by_id.get(self._decision_msg_id)
            if dec_idx is None:
                raise KeyError(f"decision_msg_id {self._decision_msg_id} not in feed")
        for date_ms, idx, m in msgs:
            if date_ms < T:
                out.append(m)
            elif date_ms == T:
                if dec_idx is None:
                    # no decision pin: include all same-second (pure price-loop step)
                    out.append(m)
                elif idx <= dec_idx:
                    out.append(m)
                # idx > dec_idx at the same second: excluded (INVARIANT 2)
            else:
                break  # ascending; nothing further can satisfy date <= T
        # INVARIANT 3: decision message is exactly the last element.
        if dec_idx is not None:
            if not out or out[-1]["id"] != self._decision_msg_id:
                raise AssertionError(
                    f"decision msg {self._decision_msg_id} is not the last element of the slice"
                )
        # --- windowing (post-gate; can only shrink the causal set) ---
        if within_ms is not None:
            cutoff = T - int(within_ms)
            kept = [m for m in out
                    if to_ms(datetime.datetime.fromisoformat(m["date"])) >= cutoff]
            # never drop the pinned decision message
            if dec_idx is not None and out and (not kept or kept[-1]["id"] != self._decision_msg_id):
                kept.append(out[-1])
            out = kept
        if last_n is not None and len(out) > last_n:
            tail = out[-last_n:]
            if dec_idx is not None and tail and tail[-1]["id"] != self._decision_msg_id:
                tail.append(out[-1])
            out = tail
        return out

    def prices(self) -> PriceOracle:
        return self._oracle


# --------------------------------------------------------------------------- #
# PointInTimeFeed — loads everything ONCE, immutable after load.              #
# --------------------------------------------------------------------------- #
class PointInTimeFeed:
    """Loads messages + per-(symbol,venue) candle arrays ONCE, sorted ascending. Immutable.

    No module-level mutable state: two concurrent Slices at different T do not interfere.
    """

    def __init__(self, messages_path: str, prices_dir: str, as_of_policy: str = "closed_minute"):
        if as_of_policy not in ("closed_minute", "open_minute"):
            raise ValueError(f"unknown as_of_policy {as_of_policy!r}")
        self.as_of_policy = as_of_policy
        self.messages_path = messages_path
        self.prices_dir = prices_dir

        # --- messages ---
        raw = json.load(open(messages_path))
        # inject _idx = export order; build (date_ms, idx, msg) sorted ascending by (date_ms, idx)
        enriched = []
        self._idx_by_id = {}
        for idx, m in enumerate(raw):
            m2 = dict(m)
            m2["_idx"] = idx
            self._idx_by_id[m["id"]] = idx
            date_ms = to_ms(datetime.datetime.fromisoformat(m["date"]))
            enriched.append((date_ms, idx, m2))
        enriched.sort(key=lambda x: (x[0], x[1]))
        self._messages = enriched
        self._msg_by_id = {m["id"]: m for (_, _, m) in enriched}

        # --- candles ---  key (symbol, venue) -> (times[], rows[])
        self._candles = {}
        self._symbols = set()
        for path in sorted(glob.glob(os.path.join(prices_dir, "*.jsonl"))):
            base = os.path.basename(path)
            stem = base[: -len(".jsonl")]
            # tolerate ".partial-tail" suffix: SYM.venue.partial-tail
            stem = stem.replace(".partial-tail", "")
            parts = stem.split(".")
            if len(parts) != 2:
                continue
            symbol, venue = parts
            rows = []
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rows.append(json.loads(line))
            rows.sort(key=lambda c: c["t"])
            times = [int(c["t"]) for c in rows]
            self._candles[(symbol, venue)] = (times, rows)
            self._symbols.add(symbol)

    @property
    def symbols(self) -> list:
        return sorted(self._symbols)

    def msg(self, msg_id: int) -> dict:
        return self._msg_by_id[msg_id]

    def at(self, T, decision_msg_id: Optional[int] = None) -> Slice:
        """Returns a Slice bound to T (datetime or epoch-ms). The ONLY way to get data.

        For the lenient `open_minute` policy, T is bumped so the bar CONTAINING T is visible
        (diagnostics only — forbidden in the acceptance/unit tests). Under the default
        `closed_minute`, T_ms is used as-is so only fully-closed minutes are visible.
        """
        T_ms = to_ms(T)
        if self.as_of_policy == "open_minute":
            # make the bar containing T visible: shift the effective T to that bar's close.
            T_ms = ((T_ms // MINUTE_MS) + 1) * MINUTE_MS
        return Slice(self, T_ms, decision_msg_id)
