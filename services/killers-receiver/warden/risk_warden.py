#!/usr/bin/env python3
"""Portfolio stop-at-risk warden for the Killers copy-trader (FULL-closes only).

One cron-style run per invocation (NO daemon loop). Each run:

  1. GET /api/v1/status   → open trades (trade_id, pair, amount, current_rate,
                            is_short, leverage).
  2. GET /api/v1/balance  → wallet total (stake currency).
  3. For each open trade, read the posted stop `sl_abs` from the receiver's
     SQLite `positions` table, matched by ft_trade_id AND pair. Freqtrade
     recycles trade_ids after a DB reset, so a row whose pair disagrees with
     the live trade is treated as ft_trade_id-reuse corruption and SKIPPED
     with a WARNING (never price one trade off another trade's stop).
  4. loss_at_stop_i — the ADDITIONAL wallet loss if price moves from the
     CURRENT mark to the posted SL (floating P&L to here is already marked):
         long : max(0, (current_rate - sl_abs)) * remaining_amount
         short: max(0, (sl_abs - current_rate)) * remaining_amount
     Floored at 0: a position that would GAIN on the way to its stop
     contributes no downside, and must not offset another position's risk.
  5. If Σ loss_at_stop > CAP_PCT% * wallet_total, FULL-close (market, no
     amount) the single position with the largest loss_at_stop, then
     re-evaluate. Repeat at most 3 times per run (safety valve).

FULL closes ONLY. The receiver reconciles a fully-gone trade cleanly as
`reconciled_missing`; a PARTIAL close corrupts receiver pct_open/state
accounting, so partials are FORBIDDEN here.

WARDEN_DRY_RUN (default true) logs what it WOULD close without calling
forceexit. The DB is opened read-only.

Env:
  WARDEN_FT_BASE      default http://127.0.0.1:8099
  WARDEN_FT_USER      Freqtrade REST basic-auth user (default freqtrader)
  WARDEN_FT_PASS      Freqtrade REST basic-auth pass (default mastertrader)
  WARDEN_RECEIVER_DB  path to receiver.sqlite (read-only)
  WARDEN_CAP_PCT      cap as percent of wallet total (default 10.0)
  WARDEN_DRY_RUN      "true"/"false" (default true)
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from typing import Optional

MAX_CLOSES_PER_RUN = 3


# ── Config ──────────────────────────────────────────────────────────────────


class WardenConfig:
    def __init__(self):
        self.ft_base = os.environ.get("WARDEN_FT_BASE", "http://127.0.0.1:8099")
        self.ft_user = os.environ.get("WARDEN_FT_USER", "freqtrader")
        self.ft_pass = os.environ.get("WARDEN_FT_PASS", "mastertrader")
        self.db_path = os.environ.get(
            "WARDEN_RECEIVER_DB", "/var/lib/killers/receiver.sqlite")
        self.cap_pct = float(os.environ.get("WARDEN_CAP_PCT", "10.0"))
        self.dry_run = os.environ.get(
            "WARDEN_DRY_RUN", "true").lower() in ("true", "1", "yes")


def _log(msg: str) -> None:
    """Grep-able single-line stdout alert."""
    print(f"[warden] {msg}", flush=True)


# ── Freqtrade REST (stdlib urllib) ──────────────────────────────────────────


def _auth_header(cfg: WardenConfig) -> dict:
    token = base64.b64encode(
        f"{cfg.ft_user}:{cfg.ft_pass}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def http_get_json(cfg: WardenConfig, path: str, timeout: float = 10.0):
    """GET {ft_base}{path} → parsed JSON, or None on any failure."""
    url = f"{cfg.ft_base}{path}"
    req = urllib.request.Request(url, headers=_auth_header(cfg), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as e:
        _log(f"WARNING http_get {path} failed: {e}")
        return None


def http_post_json(cfg: WardenConfig, path: str, body: dict,
                   timeout: float = 10.0):
    """POST JSON to {ft_base}{path} → (status, text)."""
    url = f"{cfg.ft_base}{path}"
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json", **_auth_header(cfg)}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode() if e.fp else str(e)
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e)


def get_open_trades(cfg: WardenConfig) -> Optional[list[dict]]:
    """GET /api/v1/status → list of open-trade dicts, or None on failure."""
    data = http_get_json(cfg, "/api/v1/status")
    if data is None:
        return None
    # Freqtrade returns a bare list for /status.
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("trades"), list):
        return data["trades"]
    return None


def get_wallet_total(cfg: WardenConfig) -> Optional[float]:
    """GET /api/v1/balance → wallet 'total' (stake currency), or None."""
    data = http_get_json(cfg, "/api/v1/balance")
    if not isinstance(data, dict):
        return None
    total = data.get("total")
    try:
        return float(total) if total is not None else None
    except (TypeError, ValueError):
        return None


def forceexit_full(cfg: WardenConfig, trade_id) -> tuple[int, str]:
    """FULL market close (no amount → whole position)."""
    return http_post_json(cfg, "/api/v1/forceexit",
                          {"tradeid": str(trade_id), "ordertype": "market"})


# ── Risk math ───────────────────────────────────────────────────────────────


def load_sl_abs(conn: sqlite3.Connection, ft_trade_id,
                pair: str) -> tuple[Optional[float], str]:
    """Return (sl_abs, reason) for a live trade.

    Guards the known ft_trade_id-reuse corruption: the receiver row must agree
    on pair. reason ∈ {'matched','pair_mismatch','no_row','no_sl'}.
    """
    row = conn.execute(
        "SELECT sl_abs, pair FROM positions WHERE ft_trade_id = ? "
        "ORDER BY (state='open') DESC, open_date DESC LIMIT 1",
        (ft_trade_id,),
    ).fetchone()
    if row is None:
        return None, "no_row"
    row_pair = row[1] if not isinstance(row, sqlite3.Row) else row["pair"]
    sl = row[0] if not isinstance(row, sqlite3.Row) else row["sl_abs"]
    if row_pair != pair:
        return None, "pair_mismatch"
    if sl is None:
        return None, "no_sl"
    try:
        sl_f = float(sl)
    except (TypeError, ValueError):
        return None, "no_sl"
    if sl_f <= 0:
        return None, "no_sl"
    return sl_f, "matched"


def loss_at_stop(trade: dict, sl_abs: float) -> float:
    """Additional wallet loss if price runs from current mark to posted SL.

    Floored at 0 (a stop on the favorable side contributes no downside).
    """
    try:
        amount = float(trade.get("amount") or 0.0)
        current = float(trade.get("current_rate") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if amount <= 0 or current <= 0:
        return 0.0
    is_short = bool(trade.get("is_short"))
    if is_short:
        decline = sl_abs - current
    else:
        decline = current - sl_abs
    return max(0.0, decline) * amount


def _evaluate(conn: sqlite3.Connection,
              trades: list[dict]) -> tuple[float, list[dict]]:
    """Return (total_risk, per_trade) for the given working set of trades.

    per_trade entries carry loss_at_stop; pair-mismatched / SL-less trades are
    skipped (logged) and excluded from the risk sum and from close candidacy.
    """
    per_trade: list[dict] = []
    total = 0.0
    for t in trades:
        tid = t.get("trade_id")
        pair = t.get("pair")
        sl_abs, reason = load_sl_abs(conn, tid, pair)
        if reason != "matched":
            if reason == "pair_mismatch":
                _log(f"WARNING trade_id={tid} pair={pair} SKIPPED — "
                     f"receiver row pair disagrees (ft_trade_id reuse); "
                     f"not pricing off a stale stop")
            else:
                _log(f"WARNING trade_id={tid} pair={pair} SKIPPED — {reason} "
                     f"(no posted SL to bound risk)")
            continue
        risk = loss_at_stop(t, sl_abs)
        per_trade.append({"trade_id": tid, "pair": pair, "sl_abs": sl_abs,
                          "loss_at_stop": risk,
                          "amount": float(t.get("amount") or 0.0)})
        total += risk
    return total, per_trade


# ── Main run ────────────────────────────────────────────────────────────────


def run_once(cfg: WardenConfig,
             conn: Optional[sqlite3.Connection] = None) -> dict:
    """Execute one warden pass. Returns a summary dict."""
    close_conn = False
    if conn is None:
        uri = f"file:{cfg.db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        close_conn = True
    try:
        return _run_once_inner(cfg, conn)
    finally:
        if close_conn:
            conn.close()


def _run_once_inner(cfg: WardenConfig, conn: sqlite3.Connection) -> dict:
    summary = {"wallet_total": None, "cap_usd": None, "initial_risk": None,
               "breached": False, "actions": [], "remaining_risk": None,
               "attempted_failed": [], "dry_run": cfg.dry_run, "status": "ok"}

    trades = get_open_trades(cfg)
    if trades is None:
        _log("WARNING /status unreachable — skipping run (no action)")
        summary["status"] = "ft_unreachable"
        return summary
    wallet = get_wallet_total(cfg)
    if wallet is None or wallet <= 0:
        _log("WARNING /balance total unavailable — skipping run (no action)")
        summary["status"] = "wallet_unavailable"
        return summary

    cap_usd = cfg.cap_pct / 100.0 * wallet
    summary["wallet_total"] = wallet
    summary["cap_usd"] = cap_usd

    working = list(trades)
    total_risk, per_trade = _evaluate(conn, working)
    summary["initial_risk"] = total_risk

    if total_risk <= cap_usd:
        _log(f"OK risk={total_risk:.2f} cap={cap_usd:.2f} "
             f"(cap_pct={cfg.cap_pct} wallet={wallet:.2f}) "
             f"open={len(per_trade)} — no action")
        summary["remaining_risk"] = total_risk
        return summary

    summary["breached"] = True
    _log(f"BREACH risk={total_risk:.2f} > cap={cap_usd:.2f} "
         f"(cap_pct={cfg.cap_pct} wallet={wallet:.2f}) open={len(per_trade)}")

    closes = 0
    attempted_failed: list[dict] = []
    while total_risk > cap_usd and closes < MAX_CLOSES_PER_RUN and per_trade:
        # Largest loss_at_stop first.
        victim = max(per_trade, key=lambda x: x["loss_at_stop"])
        action = {"trade_id": victim["trade_id"], "pair": victim["pair"],
                  "loss_at_stop": victim["loss_at_stop"],
                  "dry_run": cfg.dry_run, "closed": False,
                  "ft_status": None}
        remove_victim = False
        if cfg.dry_run:
            _log(f"WOULD-CLOSE trade_id={victim['trade_id']} pair={victim['pair']} "
                 f"loss_at_stop={victim['loss_at_stop']:.2f} (dry-run)")
            remove_victim = True
        else:
            st, body = forceexit_full(cfg, victim["trade_id"])
            action["ft_status"] = st
            ok = 200 <= st < 300
            action["closed"] = ok
            if ok:
                _log(f"CLOSED trade_id={victim['trade_id']} pair={victim['pair']} "
                     f"loss_at_stop={victim['loss_at_stop']:.2f} ft_status={st}")
                remove_victim = True
            else:
                _log(f"ERROR forceexit trade_id={victim['trade_id']} "
                     f"pair={victim['pair']} ft_status={st} body={body[:200]} — "
                     f"keeping in remaining risk, aborting run (FT state "
                     f"unreliable)")
                attempted_failed.append(
                    {"trade_id": victim["trade_id"], "pair": victim["pair"],
                     "loss_at_stop": victim["loss_at_stop"], "ft_status": st})
        summary["actions"].append(action)

        if not remove_victim:
            # A failed forceexit means the exchange/FT state is unreliable —
            # do NOT attempt further closes this run (another close could act
            # on a stale snapshot). The victim's risk stays in the total so
            # remaining_risk does not under-report; the next run retries.
            break

        # Re-evaluate: drop the victim from the working set (a full close
        # removes its risk). We don't re-fetch /status — one authoritative
        # snapshot per run; the wallet cap is ~constant intra-run. In dry-run
        # we keep simulating removals to report how many closes it would take.
        working = [t for t in working if t.get("trade_id") != victim["trade_id"]]
        total_risk, per_trade = _evaluate(conn, working)
        closes += 1

    summary["remaining_risk"] = total_risk
    summary["attempted_failed"] = attempted_failed
    if attempted_failed:
        _log(f"ABORTED after {closes} close(s): forceexit failed for "
             f"{len(attempted_failed)} trade(s) — remaining_risk={total_risk:.2f} "
             f"> cap={cap_usd:.2f} attempted_failed={attempted_failed}")
    elif total_risk > cap_usd:
        _log(f"STILL-BREACHED after {closes} close(s): "
             f"remaining_risk={total_risk:.2f} > cap={cap_usd:.2f} "
             f"(safety-valve max={MAX_CLOSES_PER_RUN}) "
             f"attempted_failed={attempted_failed}")
    else:
        _log(f"RESOLVED after {closes} close(s): remaining_risk={total_risk:.2f} "
             f"<= cap={cap_usd:.2f} attempted_failed={attempted_failed}")
    return summary


def main():
    cfg = WardenConfig()
    run_once(cfg)


if __name__ == "__main__":
    sys.exit(main())
