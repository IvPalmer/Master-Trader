#!/usr/bin/env python3
"""Frozen-config paper tracker for prereg hl-carry-shadow-2026-07.

Live forward shadow of the hl-carry-study-2026-07 T1 track (HL perp short + Binance
spot long, $1000/leg). Config is FROZEN by the preregistration and must NOT deviate.
Basis sign convention + sign_check() are copied verbatim from the study script
scripts/carry_sim.py so the shadow's numbers reconcile with the backtest.

State lives in $SH/state.json; every lifecycle event is appended to
$SH/data/episodes.jsonl. Called once per hour (after funding settles) by monitor.py,
same process. Reads settled funding from $SH/data/funding.jsonl and the minute BBO
snapshots from $SH/data/bbo_YYYYMMDD.jsonl.
"""
import gzip
import math
import json
import os
from datetime import datetime, timezone, timedelta

NOTIONAL = 1000.0
ENTER_ANN = 0.40          # trailing-24h annualized funding >= 0.40 -> entry signal
EXIT_ANN = 0.10           # trailing-12h annualized funding < 0.10 -> exit signal
MAX_CONC = 3              # max concurrent episodes (pending + open) fleet-wide
HOURS_YEAR = 24 * 365
TRAIL24_N = 24
TRAIL12_N = 12

# Fees (bps of $1000 notional per FILL). T1 realistic_default from carry_sim.py:
# HL maker 1.5bps entry, HL taker 4.5bps exit (exit crosses), Binance spot taker 7.5bps.
HL_MAKER_BPS = 1.5
HL_TAKER_BPS = 4.5
BN_TAKER_BPS = 7.5
PROVISIONED_PEAK = MAX_CONC * 1.5 * NOTIONAL   # = 4500 (matches study req_cap at max_conc)

FILL_TIMEOUT_H = 6        # cancel + repost maker leg if unfilled within 6h


def paths(sh):
    data = os.path.join(sh, "data")
    return {
        "state": os.path.join(sh, "state.json"),
        "episodes": os.path.join(data, "episodes.jsonl"),
        "funding": os.path.join(data, "funding.jsonl"),
        "weekly": os.path.join(data, "weekly_summary.jsonl"),
        "data": data,
    }


# ---------------------------------------------------------------------------
# sign_check: copied verbatim from scripts/carry_sim.py (prereg requirement)
# ---------------------------------------------------------------------------
def sign_check():
    """basis_drift_frac = -((Pperp_exit - Pspot_exit) - (Pperp_entry - Pspot_entry)) / Pperp_entry
    Case B: perp rallies vs spot -> short perp loses -> negative.
    Case C: perp falls vs spot   -> short perp gains -> positive."""
    def bd(ppe, pse, ppx, psx):
        return -((ppx - psx) - (ppe - pse)) / ppe
    b = bd(100, 100, 110, 100)
    assert b < 0, f"sign-check B failed: {b}"
    c = bd(100, 100, 90, 100)
    assert c > 0, f"sign-check C failed: {c}"
    return {"caseB_perp_rally_vs_spot_frac": b, "caseC_perp_fall_vs_spot_frac": c}


def basis_pnl_usd(perp_entry, spot_entry, perp_exit, spot_exit):
    """Prereg-frozen difference-form basis pnl in $ on NOTIONAL (short-perp+long-spot:
    basis narrowing = gain). Identical to carry_sim.finalize basis_drift."""
    return (-((perp_exit - spot_exit) - (perp_entry - spot_entry)) / perp_entry) * NOTIONAL


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------
def default_state():
    return {
        "open_episodes": {},       # coin -> episode dict
        "prev_trail24": {},        # coin -> last trail24_ann (for rising-edge)
        "last_funding_ts": {},     # coin -> last settled ts(ms) seen (monitor owns)
        "last_weekly_summary": None,
        "episode_seq": 0,
    }


def load_state(sh):
    p = paths(sh)["state"]
    if os.path.exists(p):
        try:
            with open(p) as f:
                s = json.load(f)
            for k, v in default_state().items():
                s.setdefault(k, v)
            return s
        except Exception as exc:
            raise RuntimeError("Cannot read paper state; refusing to reset history") from exc
    return default_state()


def save_state(sh, state):
    p = paths(sh)["state"]
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp, p)


def _append(path, obj):
    obj = dict(obj, accounting_version=2)
    with open(path, "a") as f:
        f.write(json.dumps(obj, default=str) + "\n")


# ---------------------------------------------------------------------------
# data loading
# ---------------------------------------------------------------------------
def load_funding(sh):
    """coin -> sorted list of (ts_settle_ms, rate)."""
    p = paths(sh)["funding"]
    out = {}
    if not os.path.exists(p):
        return out
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                out.setdefault(r["coin"], []).append((int(r["ts_settle"]), float(r["rate"])))
            except Exception:
                continue
    for c in out:
        out[c].sort()
    return out


def trail_ann(rates, n):
    """Annualized trailing mean of last n settled hourly rates; None if < n settlements."""
    if len(rates) < n:
        return None
    last = [r for _, r in rates[-n:]]
    return (sum(last) / n) * HOURS_YEAR


def load_bbo_snaps(sh, now_dt, lookback_s=3700):
    """Return (latest_by_coin, past_hour_by_coin).
    Reads today's and (if near midnight) yesterday's bbo file. ts field = epoch seconds."""
    data = paths(sh)["data"]
    now_s = now_dt.timestamp()
    cutoff = now_s - lookback_s
    files = []
    for d in (now_dt, now_dt - timedelta(days=1)):
        fp = os.path.join(data, "bbo_%s.jsonl" % d.strftime("%Y%m%d"))
        if os.path.exists(fp):
            files.append(fp)
        elif os.path.exists(fp + ".gz"):
            files.append(fp + ".gz")
    latest = {}
    past = {}
    for fp in files:
        with (gzip.open(fp, "rt") if fp.endswith(".gz") else open(fp)) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                c = r.get("coin")
                ts = r.get("ts")
                if c is None or ts is None or not cutoff < ts <= now_s:
                    continue
                cur = latest.get(c)
                if cur is None or ts >= cur["ts"]:
                    latest[c] = r
                if ts > cutoff:
                    past.setdefault(c, []).append(r)
    for c in past:
        past[c].sort(key=lambda r: r["ts"])
    latest = {c: s for c, s in latest.items() if now_s - s["ts"] <= 120}
    return latest, past


# ---------------------------------------------------------------------------
# hourly step
# ---------------------------------------------------------------------------
def run_hourly(sh, now_dt=None, log=None):
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)
    if log is None:
        log = lambda m: None
    sign_check()  # fail-fast if convention ever drifts
    p = paths(sh)
    state = load_state(sh)
    state["accounting_version"] = 2
    funding = {c: sorted({ts: rate for ts, rate in rates if ts <= now_dt.timestamp() * 1000}.items())
               for c, rates in load_funding(sh).items()}
    latest, past = load_bbo_snaps(sh, now_dt)
    now_s = now_dt.timestamp()
    now_ms = int(now_s * 1000)
    open_eps = state["open_episodes"]

    def snap_num(snap, key):
        v = snap.get(key)
        return float(v) if v is not None and math.isfinite(float(v)) and float(v) > 0 else None

    # ---- (A) process pending HL maker fills / reposts -------------------
    for coin, ep in list(open_eps.items()):
        if ep.get("status") != "pending_fill":
            continue
        posted_ask = ep["posted_ask"]
        fill_snap = None
        for s in past.get(coin, []):
            hl_bid = snap_num(s, "hl_bid")
            if (ep["post_ts"] < s["ts"] <= ep["post_ts"] + FILL_TIMEOUT_H * 3600
                    and hl_bid is not None and hl_bid >= posted_ask
                    and snap_num(s, "bn_ask") is not None):
                fill_snap = s
                break
        if fill_snap is not None:
            fill_ts = fill_snap["ts"]
            perp_entry = posted_ask
            spot_entry = snap_num(fill_snap, "bn_ask")
            if spot_entry is None:
                continue  # can't price spot leg yet; retry next hour
            ep.update({
                "status": "open",
                "fill_ts": fill_ts,
                "perp_entry": perp_entry,
                "spot_entry": spot_entry,
                "entry_fee_hl": HL_MAKER_BPS / 1e4 * NOTIONAL,
                "entry_fee_bn": BN_TAKER_BPS / 1e4 * NOTIONAL,
                "entry_exec_basis": perp_entry - spot_entry,
                "accrual_start_ts": int(fill_ts * 1000),
            })
            _append(p["episodes"], {
                "event": "fill", "ts": now_ms, "coin": coin, "ep_id": ep["ep_id"],
                "fill_ts": fill_ts, "fill_delay_h": round((fill_ts - ep["signal_ts"]) / 3600, 4),
                "perp_entry": perp_entry, "spot_entry": spot_entry,
                "entry_exec_basis": ep["entry_exec_basis"], "n_reposts": ep.get("n_reposts", 0),
                "hl_bid_at_fill": snap_num(fill_snap, "hl_bid"),
            })
            log("FILL %s perp_entry=%.6g spot_entry=%.6g" % (coin, perp_entry, spot_entry))
        else:
            # not filled: repost at current best ask if 6h elapsed since last post
            age_s = now_s - ep["post_ts"]
            if age_s >= FILL_TIMEOUT_H * 3600:
                snap = latest.get(coin)
                new_ask = snap_num(snap, "hl_ask") if snap else None
                if new_ask is not None:
                    old = ep["posted_ask"]
                    ep["posted_ask"] = new_ask
                    ep["post_ts"] = now_s
                    ep["n_reposts"] = ep.get("n_reposts", 0) + 1
                    _append(p["episodes"], {
                        "event": "repost", "ts": now_ms, "coin": coin, "ep_id": ep["ep_id"],
                        "old_posted_ask": old, "new_posted_ask": new_ask,
                        "n_reposts": ep["n_reposts"],
                    })
                    log("REPOST %s %.6g -> %.6g" % (coin, old, new_ask))

    # ---- (B) exits: trail12 < 0.10 on open episodes --------------------
    for coin, ep in list(open_eps.items()):
        if ep.get("status") != "open":
            continue
        t12 = trail_ann(funding.get(coin, []), TRAIL12_N)
        if t12 is None or t12 >= EXIT_ANN:
            continue
        snap = latest.get(coin)
        if snap is None:
            continue
        perp_exit = snap_num(snap, "hl_ask")   # Buy to cover the short crosses the ask
        spot_exit = snap_num(snap, "bn_bid")   # Binance taker sell hits bid
        if perp_exit is None or spot_exit is None:
            continue
        exit_ts_ms = int(snap["ts"] * 1000)
        # settled funding accrued in (fill, exit]; short perp receives when rate>0
        seg = [r for (ts, r) in funding.get(coin, [])
               if ep["accrual_start_ts"] < ts <= exit_ts_ms]
        funding_received = sum(seg) * NOTIONAL
        b_pnl = basis_pnl_usd(ep["perp_entry"], ep["spot_entry"], perp_exit, spot_exit)
        exit_fee_hl = HL_TAKER_BPS / 1e4 * NOTIONAL
        exit_fee_bn = BN_TAKER_BPS / 1e4 * NOTIONAL
        total_fees = ep["entry_fee_hl"] + ep["entry_fee_bn"] + exit_fee_hl + exit_fee_bn
        net = funding_received + b_pnl - total_fees
        dur_h = (snap["ts"] - ep["fill_ts"]) / 3600.0
        _append(p["episodes"], {
            "event": "exit", "ts": now_ms, "coin": coin, "ep_id": ep["ep_id"],
            "signal_ts": ep["signal_ts"], "fill_ts": ep["fill_ts"], "exit_ts": snap["ts"],
            "trail24_at_signal": ep["trail24_at_signal"], "trail12_at_exit": t12,
            "duration_h": dur_h, "n_funding_settlements": len(seg),
            "perp_entry": ep["perp_entry"], "spot_entry": ep["spot_entry"],
            "perp_exit": perp_exit, "spot_exit": spot_exit,
            "entry_exec_basis": ep["entry_exec_basis"], "exit_exec_basis": perp_exit - spot_exit,
            "funding_received": funding_received, "basis_pnl": b_pnl,
            "entry_fee_hl": ep["entry_fee_hl"], "entry_fee_bn": ep["entry_fee_bn"],
            "exit_fee_hl": exit_fee_hl, "exit_fee_bn": exit_fee_bn,
            "total_fees": total_fees, "net": net,
            "n_reposts": ep.get("n_reposts", 0),
        })
        log("EXIT %s net=%.4f (funding=%.4f basis=%.4f fees=%.4f)" %
            (coin, net, funding_received, b_pnl, total_fees))
        del open_eps[coin]

    # ---- (C) entries: rising-edge cross of trail24 through 0.40 --------
    candidates = []
    new_prev = dict(state["prev_trail24"])
    for coin, rates in funding.items():
        t24 = trail_ann(rates, TRAIL24_N)
        pv = state["prev_trail24"].get(coin)
        if coin not in open_eps and t24 is not None and t24 >= ENTER_ANN and (pv is None or pv < ENTER_ANN):
            candidates.append((coin, t24))
        new_prev[coin] = t24
    candidates.sort(key=lambda x: -x[1])
    for coin, t24 in candidates:
        if len(open_eps) < MAX_CONC:
            snap = latest.get(coin)
            posted_ask = snap_num(snap, "hl_ask") if snap else None
            if posted_ask is None:
                _append(p["episodes"], {"event": "skip", "ts": now_ms, "coin": coin,
                                        "trail24": t24, "reason": "no_hl_ask_snapshot"})
                continue
            state["episode_seq"] += 1
            ep_id = "ep%06d" % state["episode_seq"]
            open_eps[coin] = {
                "ep_id": ep_id, "coin": coin, "status": "pending_fill",
                "signal_ts": now_s, "trail24_at_signal": t24,
                "posted_ask": posted_ask, "post_ts": now_s, "n_reposts": 0,
            }
            _append(p["episodes"], {
                "event": "signal", "ts": now_ms, "coin": coin, "ep_id": ep_id,
                "trail24_at_signal": t24, "posted_ask": posted_ask,
            })
            log("SIGNAL %s trail24=%.4f posted_ask=%.6g" % (coin, t24, posted_ask))
        else:
            _append(p["episodes"], {"event": "skip", "ts": now_ms, "coin": coin,
                                    "trail24": t24, "reason": "max_concurrent"})
            log("SKIP %s trail24=%.4f (max_concurrent)" % (coin, t24))

    state["prev_trail24"] = new_prev
    save_state(sh, state)

    # ---- (D) weekly summary on Sunday 00:xx ----------------------------
    if now_dt.weekday() == 6 and now_dt.hour == 0:
        today = now_dt.strftime("%Y-%m-%d")
        if state.get("last_weekly_summary") != today:
            weekly_summary(sh, now_dt)
            state["last_weekly_summary"] = today
            save_state(sh, state)

    return {"open": len(open_eps), "candidates": len(candidates)}


def weekly_summary(sh, now_dt):
    """Append one weekly rollup line. Yields on BOTH avg-deployed and provisioned-peak."""
    p = paths(sh)
    events = []
    if os.path.exists(p["episodes"]):
        with open(p["episodes"]) as f:
            events = [json.loads(line) for line in f if line.strip()]
    end_ms = int(now_dt.timestamp() * 1000)
    week_start_ms = int((now_dt - timedelta(days=7)).timestamp() * 1000)
    exits = {e["ep_id"]: e for e in events if e["event"] == "exit" and e["ts"] <= end_ms}
    fills = [e for e in events if e["event"] == "fill" and e["ts"] <= end_ms]
    wk_exits = [e for e in exits.values() if week_start_ms < e["ts"] <= end_ms]
    wk_fills = [e for e in fills if week_start_ms < e["ts"] <= end_ms]
    n_closed = len(wk_exits)
    # Realized cash P&L is reported separately; it is not a calendar-week total return.
    total_net = sum(e["net"] for e in wk_exits)
    active_hours = sum(max(0, min(end_ms / 1000, exits.get(e["ep_id"], {}).get("exit_ts", end_ms / 1000))
                          - max(week_start_ms / 1000, e["fill_ts"])) / 3600 for e in fills)
    first_try = sum(1 for e in wk_fills if e.get("n_reposts", 0) == 0)
    fill_success = (first_try / len(wk_fills)) if wk_fills else None
    avg_fill_delay = (sum(e["fill_delay_h"] for e in wk_fills) / len(wk_fills)) if wk_fills else None

    week_years = 7.0 / 365.0
    avg_concurrent = active_hours / (7 * 24)
    avg_deployed = avg_concurrent * 1.5 * NOTIONAL
    # A closed episode's full-life P&L cannot be annualized against one week's
    # exposure. Weekly total return needs boundary marks for both legs and funding.
    yield_deployed = yield_peak = None

    summary = {
        "accounting_version": 2,
        "yield_status": "unavailable: weekly boundary marks required",
        "ts": int(now_dt.timestamp() * 1000), "week_ending": now_dt.strftime("%Y-%m-%d"),
        "episodes_closed": n_closed, "total_net": total_net,
        "active_position_hours": active_hours,
        "maker_fill_success_rate": None,
        "first_post_fraction_among_fills": fill_success, "avg_fill_delay_h": avg_fill_delay,
        "avg_deployed_capital": avg_deployed,
        "yield_on_avg_deployed_annual_pct": yield_deployed,
        "yield_on_provisioned_peak_annual_pct": yield_peak,
        "provisioned_peak_capital": PROVISIONED_PEAK,
    }
    _append(p["weekly"], summary)
    return summary


if __name__ == "__main__":
    print(sign_check())
