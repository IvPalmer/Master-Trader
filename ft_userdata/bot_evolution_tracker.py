#!/usr/bin/env python3
"""
Bot Evolution Tracker — Records strategy snapshots, parameter changes, and health checkpoints.

Usage:
    python3 bot_evolution_tracker.py snapshot              # Record current state of all bots
    python3 bot_evolution_tracker.py snapshot --note "tightened SL to 5%"
    python3 bot_evolution_tracker.py changelog BOT "what changed"  # Log a manual change
    python3 bot_evolution_tracker.py history BOT            # Show evolution timeline
    python3 bot_evolution_tracker.py compare BOT ID1 ID2    # Compare two snapshots
    python3 bot_evolution_tracker.py peak BOT               # Show peak performance snapshot
    python3 bot_evolution_tracker.py dashboard              # Overview of all bots
    python3 bot_evolution_tracker.py graduation             # Report v4 graduation facts (no verdicts)
"""

import argparse
import json
import os
import sqlite3
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("MT_EVOLUTION_DIR") or Path(__file__).parent / "evolution")
STRATEGY_DIR = Path(__file__).parent / "user_data" / "strategies"
CONFIG_DIR = Path(__file__).parent / "user_data" / "configs"
TRADE_DB_DIR = Path(__file__).parent / "user_data"

def _load_active_bots() -> list[str]:
    """Load active bot names from shared config, fall back to hardcoded defaults."""
    config_path = Path(__file__).parent / "bots_config.json"
    try:
        with open(config_path) as f:
            data = json.load(f)
        return [name for name, info in data["bots"].items() if info.get("active", True)]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return [
            "SupertrendStrategy",
            "MasterTraderV1",
            "BollingerRSIMeanReversion",
            "FuturesSniperV1",
            "AlligatorTrendV1",
            "GaussianChannelV1",
            "BearCrashShortV1",
            "BollingerBounceV1",
        ]

ACTIVE_BOTS = _load_active_bots()


def _load_runtime_configs() -> dict[str, str]:
    """Config filename each bot is deployed from, where bots_config.json records one."""
    config_path = Path(__file__).parent / "bots_config.json"
    try:
        with open(config_path) as f:
            data = json.load(f)
        return {name: info["runtime_config"] for name, info in data["bots"].items()
                if info.get("runtime_config")}
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return {}

RUNTIME_CONFIGS = _load_runtime_configs()


def config_filename(bot_name):
    """The deployed config's filename: runtime_config when recorded, else <name>.json."""
    return RUNTIME_CONFIGS.get(bot_name) or f"{bot_name}.json"

# Trade database the metrics are read from: the dry-run (paper) database, so
# every figure this tracker prints is a paper-trading measurement.
TRADE_DB_NAME = "tradesv3.dryrun.{bot}.sqlite"

# ── Graduation criteria v4 (GRADUATION_CRITERIA.md, revised 2026-05-10) ──────
# Only the thresholds v4 states as plain numbers are recorded here. v4 makes
# every tier-up an explicit operator decision (GRADUATION_CRITERIA.md:52, :58,
# :211), so this tracker reports these as reference facts next to the raw
# metrics and never labels a bot as passing or failing them. The v1 absolute
# gates this file used to hold (PF >= 2.0, WR >= 55%, max loss < 5%,
# max DD < 15%, consec losses <= 4) were discarded 2026-04-20
# (GRADUATION_CRITERIA.md:298-302) and are not used.
# Line numbers refer to both copies (repo root and ft_userdata/), which match.

# Pilot -> Scale: "at least 30 closed trades" (GRADUATION_CRITERIA.md:58)
V4_PILOT_TO_SCALE_MIN_CLOSED_TRADES = 30

# Probe -> Pilot post-flip minimums by strategy class (GRADUATION_CRITERIA.md:116-120).
# The class comes from backtest cadence, which this tracker does not know.
V4_PROBE_TO_PILOT_MINIMUMS = [
    ("Active (>100 trades/yr backtest)", {"min_days": 14, "min_closed_trades": 15, "min_pairs": 4}),
    ("Sparse (40-100/yr backtest)", {"min_days": 30, "min_closed_trades": 8, "min_pairs": 3}),
    ("Very sparse (<40/yr backtest)", {"min_days": 45, "min_closed_trades": 5, "min_pairs": 2}),
]

# Any auto-action on a wallet movement below $5 is suppressed (GRADUATION_CRITERIA.md:215)
V4_AUTO_ACTION_DOLLAR_FLOOR = 5.0

# Fleet-wide kill trigger: force_exit/emergency_exit 3 times in 24h
# (GRADUATION_CRITERIA.md:177). This tracker counts force/emergency exits over
# the whole history, not per 24h, so it cannot evaluate this trigger.
V4_FLEET_FORCE_EXITS_PER_24H = 3

# Per-bot demotion triggers that map onto metrics this tracker computes
# (GRADUATION_CRITERIA.md:150-172). Percentage-drawdown triggers are left out:
# they need a capital basis this tracker does not have.
V4_DEMOTION_REFERENCE = {
    "FundingFadeV1": [
        "pause: any single closed trade < -7% (GRADUATION_CRITERIA.md:153)",
        "DD pause dollar floor $10 (GRADUATION_CRITERIA.md:154)",
        "kill: 3 consecutive emergency exits (GRADUATION_CRITERIA.md:157)",
    ],
    "KeltnerBounceV1": [
        "pause: any single closed trade < -10% (GRADUATION_CRITERIA.md:160)",
        "DD pause dollar floor $10 (GRADUATION_CRITERIA.md:161)",
        "kill: 6 consecutive losses (GRADUATION_CRITERIA.md:164)",
    ],
    "CascadeFaderV1": [
        "pause: any single closed trade < -12% (GRADUATION_CRITERIA.md:167)",
        "DD pause dollar floor $5 (GRADUATION_CRITERIA.md:169)",
        "kill: 7 consecutive losses (GRADUATION_CRITERIA.md:172)",
    ],
}


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for bot in ACTIVE_BOTS:
        (DATA_DIR / bot).mkdir(exist_ok=True)


def extract_strategy_params(bot_name):
    """Extract key parameters from strategy .py file."""
    py_file = STRATEGY_DIR / f"{bot_name}.py"
    if not py_file.exists():
        return {}

    content = py_file.read_text()
    params = {}

    # Extract key numeric parameters
    patterns = {
        "stoploss": r"stoploss\s*=\s*(-?[\d.]+)",
        "trailing_stop": r"trailing_stop\s*=\s*(True|False)",
        "trailing_stop_positive": r"trailing_stop_positive\s*=\s*([\d.]+)",
        "trailing_stop_positive_offset": r"trailing_stop_positive_offset\s*=\s*([\d.]+)",
        "timeframe": r"timeframe\s*=\s*['\"](\w+)['\"]",
        "can_short": r"can_short\s*=\s*(True|False)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, content)
        if match:
            val = match.group(1)
            try:
                params[key] = float(val)
            except ValueError:
                params[key] = val

    # Extract minimal_roi
    roi_match = re.search(r"minimal_roi\s*=\s*\{([^}]+)\}", content)
    if roi_match:
        params["minimal_roi"] = roi_match.group(1).strip()

    # Hash the full strategy file for change detection
    params["_file_hash"] = hashlib.md5(content.encode()).hexdigest()[:12]

    return params


def extract_config_params(bot_name, config_name=None):
    """Extract key parameters from the config file the bot is deployed from."""
    config_file = CONFIG_DIR / (config_name or config_filename(bot_name))
    if not config_file.exists():
        # Recorded rather than returned empty: a snapshot cannot be backfilled, so an
        # absent config has to be distinguishable from one that held no values.
        # A recorded runtime_config that is absent does not fall back to <name>.json:
        # that file, if it exists, is not what the bot runs.
        print(f"  WARNING: {bot_name} has no {config_file.name}; snapshot records no config")
        return {"_config_missing": config_file.name}

    with open(config_file) as f:
        config = json.load(f)

    return {
        "dry_run": config.get("dry_run"),
        "dry_run_wallet": config.get("dry_run_wallet"),
        "max_open_trades": config.get("max_open_trades"),
        "stake_amount": config.get("stake_amount"),
        "stoploss_on_exchange": config.get("order_types", {}).get("stoploss_on_exchange"),
        "trading_mode": config.get("trading_mode"),
    }


def get_trade_metrics(bot_name):
    """Pull comprehensive metrics from trade database."""
    db_patterns = [
        TRADE_DB_DIR / TRADE_DB_NAME.format(bot=bot_name),
    ]

    db_path = None
    for p in db_patterns:
        if p.exists():
            db_path = p
            break

    if not db_path:
        return {"error": "no database found"}

    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    # Closed trades
    c.execute("""
        SELECT close_profit * 100, close_profit_abs, exit_reason,
               open_date, close_date, min_rate, open_rate, max_rate, pair
        FROM trades WHERE is_open = 0 AND close_profit IS NOT NULL
        ORDER BY open_date
    """)
    closed = c.fetchall()

    # Open trades
    c.execute("SELECT COUNT(*), SUM(stake_amount) FROM trades WHERE is_open = 1")
    open_row = c.fetchone()
    open_count = open_row[0] or 0
    open_stake = open_row[1] or 0

    conn.close()

    if not closed:
        return {
            "total_trades": 0,
            "open_trades": open_count,
            "open_stake": round(open_stake, 2),
        }

    winners = [t for t in closed if t[1] > 0]
    losers = [t for t in closed if t[1] <= 0]

    wr = len(winners) / len(closed) * 100
    avg_win = sum(t[1] for t in winners) / len(winners) if winners else 0
    avg_loss = sum(abs(t[1]) for t in losers) / len(losers) if losers else 0
    rr = avg_win / avg_loss if avg_loss > 0 else 0

    gross_profit = sum(t[1] for t in winners)
    gross_loss = sum(abs(t[1]) for t in losers)
    pf = gross_profit / gross_loss if gross_loss > 0 else 0

    total_pnl = sum(t[1] for t in closed)
    worst_loss = min(t[1] for t in closed)
    worst_loss_pct = min(t[0] for t in closed)

    # Unique pairs
    pairs = set(t[8] for t in closed)

    # Days running
    first = closed[0][3]
    last = closed[-1][4]
    try:
        d1 = datetime.strptime(first[:19], "%Y-%m-%d %H:%M:%S")
        d2 = datetime.strptime(last[:19], "%Y-%m-%d %H:%M:%S")
        days = max(1, (d2 - d1).days)
    except Exception:
        days = 0

    # Consecutive losses
    results = [1 if t[1] > 0 else 0 for t in closed]
    max_consec_loss = 0
    streak = 0
    for r in results:
        if r == 0:
            streak += 1
            max_consec_loss = max(max_consec_loss, streak)
        else:
            streak = 0

    # Max drawdown
    cumulative = 0
    peak = 0
    max_dd = 0
    for t in closed:
        cumulative += t[1]
        peak = max(peak, cumulative)
        dd = peak - cumulative
        max_dd = max(max_dd, dd)

    # Exit reasons
    reasons = {}
    for t in closed:
        r = t[2] or "unknown"
        reasons[r] = reasons.get(r, 0) + 1

    force_exits = sum(1 for t in closed if t[2] and ("force" in t[2] or "emergency" in t[2]))

    return {
        "total_trades": len(closed),
        "open_trades": open_count,
        "open_stake": round(open_stake, 2),
        "winners": len(winners),
        "losers": len(losers),
        "win_rate": round(wr, 1),
        "profit_factor": round(pf, 2),
        "risk_reward": round(rr, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "total_pnl": round(total_pnl, 2),
        "worst_loss_abs": round(worst_loss, 2),
        "worst_loss_pct": round(worst_loss_pct, 1),
        "max_drawdown": round(max_dd, 2),
        "max_consec_losses": max_consec_loss,
        "unique_pairs": len(pairs),
        "days_running": days,
        "exit_reasons": reasons,
        "force_exits": force_exits,
        "trades_per_day": round(len(closed) / max(1, days), 1),
    }


def take_snapshot(note=None):
    """Take a snapshot of all active bots."""
    ensure_dirs()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snap_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    results = {}
    for bot in ACTIVE_BOTS:
        params = extract_strategy_params(bot)
        config = extract_config_params(bot)
        metrics = get_trade_metrics(bot)

        snapshot = {
            "id": snap_id,
            "timestamp": ts,
            "note": note,
            "parameters": params,
            "config": config,
            "metrics": metrics,
        }

        # Save individual snapshot
        snap_file = DATA_DIR / bot / f"{snap_id}.json"
        with open(snap_file, "w") as f:
            json.dump(snapshot, f, indent=2)

        # Check if this is a new peak
        if metrics.get("total_trades", 0) >= 10:
            peak_file = DATA_DIR / bot / "peak.json"
            is_peak = False
            if peak_file.exists():
                with open(peak_file) as f:
                    old_peak = json.load(f)
                old_pf = old_peak.get("metrics", {}).get("profit_factor", 0)
                old_pnl = old_peak.get("metrics", {}).get("total_pnl", 0)
                # Peak = highest PF with positive P/L
                if metrics["profit_factor"] > old_pf and metrics["total_pnl"] > 0:
                    is_peak = True
            elif metrics["total_pnl"] > 0:
                is_peak = True

            if is_peak:
                snapshot["_peak_reason"] = f"New peak PF: {metrics['profit_factor']}x"
                with open(peak_file, "w") as f:
                    json.dump(snapshot, f, indent=2)
                print(f"  ** NEW PEAK for {bot}: PF={metrics['profit_factor']}x, P/L=${metrics['total_pnl']}")

        results[bot] = snapshot

        # Print summary
        m = metrics
        trades = m.get("total_trades", 0)
        if trades > 0:
            print(
                f"  {bot:<30} {trades:>3} trades | "
                f"WR={m['win_rate']:>4}% | PF={m['profit_factor']:>5.2f}x | "
                f"P/L=${m['total_pnl']:>+8.2f} | DD=${m['max_drawdown']:>6.2f}"
            )
        else:
            print(f"  {bot:<30}   0 trades | (no data)")

    # Save combined snapshot
    combined = {
        "id": snap_id,
        "timestamp": ts,
        "note": note,
        "bots": {b: r["metrics"] for b, r in results.items()},
    }
    combined_file = DATA_DIR / f"snapshot_{snap_id}.json"
    with open(combined_file, "w") as f:
        json.dump(combined, f, indent=2)

    print(f"\nSnapshot {snap_id} saved.")
    return snap_id


def log_change(bot_name, description):
    """Log a manual changelog entry for a bot."""
    ensure_dirs()
    changelog_file = DATA_DIR / bot_name / "changelog.json"

    entries = []
    if changelog_file.exists():
        with open(changelog_file) as f:
            entries = json.load(f)

    # Get current params for before/after tracking
    params = extract_strategy_params(bot_name)

    entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "description": description,
        "params_after": params,
        "file_hash": params.get("_file_hash", "unknown"),
    }
    entries.append(entry)

    with open(changelog_file, "w") as f:
        json.dump(entries, f, indent=2)

    print(f"Logged change for {bot_name}: {description}")


def show_history(bot_name):
    """Show full evolution timeline for a bot."""
    bot_dir = DATA_DIR / bot_name
    if not bot_dir.exists():
        print(f"No history for {bot_name}")
        return

    # Load changelog
    changelog_file = bot_dir / "changelog.json"
    changelog = []
    if changelog_file.exists():
        with open(changelog_file) as f:
            changelog = json.load(f)

    # Load snapshots
    snapshots = []
    for f in sorted(bot_dir.glob("2*.json")):
        with open(f) as fh:
            snapshots.append(json.load(fh))

    # Load peak
    peak_file = bot_dir / "peak.json"
    peak = None
    if peak_file.exists():
        with open(peak_file) as f:
            peak = json.load(f)

    # Merge into timeline
    timeline = []
    for s in snapshots:
        timeline.append(("snapshot", s["timestamp"], s))
    for c in changelog:
        timeline.append(("change", c["timestamp"], c))

    timeline.sort(key=lambda x: x[1])

    print(f"\n{'=' * 80}")
    print(f"  EVOLUTION TIMELINE: {bot_name}")
    print(f"{'=' * 80}\n")

    if peak:
        pm = peak.get("metrics", {})
        print(f"  PEAK PERFORMANCE (saved {peak['timestamp'][:10]}):")
        print(
            f"    PF={pm.get('profit_factor', '?')}x | WR={pm.get('win_rate', '?')}% | "
            f"P/L=${pm.get('total_pnl', '?')} | {pm.get('total_trades', '?')} trades"
        )
        print(f"    Params: SL={peak['parameters'].get('stoploss', '?')}, "
              f"hash={peak['parameters'].get('_file_hash', '?')}")
        print()

    prev_hash = None
    for kind, ts, data in timeline:
        date = ts[:10]
        time = ts[11:16]

        if kind == "change":
            print(f"  [{date} {time}] CHANGE: {data['description']}")
            print(f"    {'file_hash=' + data.get('file_hash', '?')}")
            print()

        elif kind == "snapshot":
            m = data.get("metrics", {})
            p = data.get("parameters", {})
            cur_hash = p.get("_file_hash", "")
            hash_changed = prev_hash and cur_hash != prev_hash
            prev_hash = cur_hash

            trades = m.get("total_trades", 0)
            note = f" — {data['note']}" if data.get("note") else ""

            if trades > 0:
                print(
                    f"  [{date} {time}] SNAPSHOT{note}"
                    f"{'  ** PARAMS CHANGED **' if hash_changed else ''}"
                )
                print(
                    f"    {trades} trades | WR={m.get('win_rate', '?')}% | "
                    f"PF={m.get('profit_factor', '?')}x | "
                    f"R:R={m.get('risk_reward', '?')} | "
                    f"P/L=${m.get('total_pnl', '?')}"
                )
                print(
                    f"    MaxDD=${m.get('max_drawdown', '?')} | "
                    f"ConsecL={m.get('max_consec_losses', '?')} | "
                    f"SL={p.get('stoploss', '?')}"
                )
            else:
                print(f"  [{date} {time}] SNAPSHOT{note} — no trades")
            print()


def compare_snapshots(bot_name, id1, id2):
    """Compare two snapshots side by side."""
    bot_dir = DATA_DIR / bot_name

    def load_snap(snap_id):
        # Find matching file
        for f in bot_dir.glob(f"{snap_id}*.json"):
            if f.name != "peak.json" and f.name != "changelog.json":
                with open(f) as fh:
                    return json.load(fh)
        return None

    s1 = load_snap(id1)
    s2 = load_snap(id2)

    if not s1 or not s2:
        print(f"Could not find snapshots {id1} and/or {id2}")
        return

    print(f"\n{'=' * 70}")
    print(f"  COMPARISON: {bot_name}")
    print(f"  {s1['timestamp'][:16]}  vs  {s2['timestamp'][:16]}")
    print(f"{'=' * 70}\n")

    m1 = s1.get("metrics", {})
    m2 = s2.get("metrics", {})

    metrics_to_compare = [
        ("Total Trades", "total_trades", False),
        ("Win Rate %", "win_rate", True),
        ("Profit Factor", "profit_factor", True),
        ("Risk:Reward", "risk_reward", True),
        ("Total P/L $", "total_pnl", True),
        ("Avg Win $", "avg_win", True),
        ("Avg Loss $", "avg_loss", False),
        ("Max Drawdown $", "max_drawdown", False),
        ("Max Consec Losses", "max_consec_losses", False),
        ("Worst Loss %", "worst_loss_pct", False),
        ("Trades/Day", "trades_per_day", True),
    ]

    print(f"  {'Metric':<22} {'Before':>10} {'After':>10} {'Delta':>10}")
    print(f"  {'-' * 54}")

    for label, key, higher_better in metrics_to_compare:
        v1 = m1.get(key, 0) or 0
        v2 = m2.get(key, 0) or 0
        delta = v2 - v1

        if delta > 0:
            arrow = "+" if higher_better else "+"
            color = "BETTER" if higher_better else "WORSE"
        elif delta < 0:
            color = "WORSE" if higher_better else "BETTER"
        else:
            color = ""

        print(f"  {label:<22} {v1:>10.2f} {v2:>10.2f} {delta:>+10.2f}  {color}")

    # Parameter changes
    p1 = s1.get("parameters", {})
    p2 = s2.get("parameters", {})

    changed = []
    for k in set(list(p1.keys()) + list(p2.keys())):
        if k.startswith("_"):
            continue
        if p1.get(k) != p2.get(k):
            changed.append((k, p1.get(k, "—"), p2.get(k, "—")))

    if changed:
        print(f"\n  Parameter Changes:")
        for k, v1, v2 in changed:
            print(f"    {k}: {v1} → {v2}")

    hash1 = p1.get("_file_hash", "?")
    hash2 = p2.get("_file_hash", "?")
    if hash1 != hash2:
        print(f"\n  Strategy file changed: {hash1} → {hash2}")


def show_peak(bot_name):
    """Show peak performance snapshot."""
    peak_file = DATA_DIR / bot_name / "peak.json"
    if not peak_file.exists():
        print(f"No peak recorded for {bot_name} (need 10+ trades and positive P/L)")
        return

    with open(peak_file) as f:
        peak = json.load(f)

    m = peak.get("metrics", {})
    p = peak.get("parameters", {})

    print(f"\n  PEAK PERFORMANCE: {bot_name}")
    print(f"  Recorded: {peak['timestamp'][:16]}")
    print(f"  {peak.get('_peak_reason', '')}\n")

    print(f"  Trades: {m.get('total_trades')} | WR: {m.get('win_rate')}% | PF: {m.get('profit_factor')}x")
    print(f"  R:R: {m.get('risk_reward')} | P/L: ${m.get('total_pnl')}")
    print(f"  MaxDD: ${m.get('max_drawdown')} | Consec Losses: {m.get('max_consec_losses')}")
    print(f"\n  Parameters at peak:")
    for k, v in sorted(p.items()):
        if not k.startswith("_"):
            print(f"    {k}: {v}")
    print(f"  File hash: {p.get('_file_hash', '?')}")


def show_dashboard():
    """Show overview of all bots with trend arrows."""
    ensure_dirs()
    print(f"\n{'=' * 90}")
    print(f"  BOT EVOLUTION DASHBOARD — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 90}\n")

    print(f"  Source: {TRADE_DB_NAME.format(bot='<bot>')} (dry-run / paper trades)\n")
    print(f"  {'Bot':<28} {'Trades':>6} {'WR%':>5} {'PF':>6} {'P/L$':>9} {'Peak PF':>8} {'Changes':>8} {'Days':>5} {'Pairs':>5}")
    print(f"  {'-' * 85}")

    for bot in ACTIVE_BOTS:
        metrics = get_trade_metrics(bot)
        bot_dir = DATA_DIR / bot

        # Count snapshots and changes
        snaps = len(list(bot_dir.glob("2*.json"))) if bot_dir.exists() else 0
        changelog_file = bot_dir / "changelog.json"
        changes = 0
        if changelog_file.exists():
            with open(changelog_file) as f:
                changes = len(json.load(f))

        # Peak
        peak_pf = "—"
        peak_file = bot_dir / "peak.json"
        if peak_file.exists():
            with open(peak_file) as f:
                peak = json.load(f)
            peak_pf = f"{peak['metrics'].get('profit_factor', 0):.1f}x"

        trades = metrics.get("total_trades", 0)
        if trades > 0:
            wr = metrics["win_rate"]
            pf = metrics["profit_factor"]
            pnl = metrics["total_pnl"]
            days = metrics.get("days_running", 0)
            pairs = metrics.get("unique_pairs", 0)

            # Raw facts only: graduation is an operator decision under v4
            # (see check_graduation), so no gate status is derived here.
            print(
                f"  {bot:<28} {trades:>6} {wr:>4.0f}% {pf:>5.1f}x ${pnl:>+8.2f} "
                f"{peak_pf:>8} {changes:>8} {days:>5} {pairs:>5}"
            )
        else:
            print(f"  {bot:<28} {'0':>6} {'—':>5} {'—':>6} {'—':>9} {peak_pf:>8} {changes:>8}  NO DATA")

    print()
    print("  Graduation facts (v4, no verdicts): bot_evolution_tracker.py graduation")
    print()


def _print_v4_reference():
    """The numeric thresholds v4 defines, as reference text (no comparisons)."""
    print("  v4 numeric thresholds (GRADUATION_CRITERIA.md), for reference:")
    print("    Probe -> Pilot post-flip minimums, by strategy class (:116-120):")
    for label, mins in V4_PROBE_TO_PILOT_MINIMUMS:
        print(
            f"      {label:<34} {mins['min_days']} days, "
            f"{mins['min_closed_trades']} closed trades, {mins['min_pairs']} pairs"
        )
    print(
        f"    Pilot -> Scale: at least {V4_PILOT_TO_SCALE_MIN_CLOSED_TRADES} closed trades, "
        "plus >=1 regime transition and no kill-trigger events (:58)"
    )
    print(
        f"    Dollar floor: auto-actions on wallet movements < ${V4_AUTO_ACTION_DOLLAR_FLOOR:.0f} "
        "are suppressed (:215)"
    )
    print(
        f"    Fleet kill trigger: force/emergency exit {V4_FLEET_FORCE_EXITS_PER_24H} times "
        "in 24h (:177; not evaluated here, exits are counted all-time)"
    )
    print()


def check_graduation():
    """Report the facts v4 graduation decisions are made from, with no verdicts.

    GRADUATION_CRITERIA.md v4 makes every tier-up an explicit operator decision
    and defines only a few numeric thresholds. This prints those thresholds as
    reference and each bot's raw metrics, without PASS/FAIL/OK labels.
    """
    print(f"\n{'=' * 80}")
    print(f"  GRADUATION FACTS (criteria v4) — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 80}\n")
    print("  Tier-ups (Probe -> Pilot -> Scale) are an explicit operator decision under v4")
    print("  (GRADUATION_CRITERIA.md:211). This report lists facts; it does not grade bots.")
    print(f"  Source: {TRADE_DB_NAME.format(bot='<bot>')} (dry-run / paper trades).")
    print("  v4 tier minimums count closed LIVE trades after the probe flip, so these")
    print("  paper figures are context for that decision, not the count it uses.\n")

    _print_v4_reference()

    for bot in ACTIVE_BOTS:
        m = get_trade_metrics(bot)
        trades = m.get("total_trades", 0)

        print(f"  {bot}")
        print(f"  {'─' * 40}")

        if m.get("error"):
            print(f"    No trade data: {m['error']}")
        elif trades == 0:
            print("    Closed trades:        0")
        else:
            print(f"    Closed trades:        {trades}")
            print(f"    Days running:         {m.get('days_running', 0)}")
            print(f"    Pairs traded:         {m.get('unique_pairs', 0)}")
            print(f"    Profit factor:        {m['profit_factor']:.2f}")
            print(f"    Win rate:             {m['win_rate']:.1f}%")
            print(f"    Net P/L:              ${m['total_pnl']:+.2f}")
            print(
                f"    Max single loss:      ${m.get('worst_loss_abs', 0):+.2f} "
                f"({m.get('worst_loss_pct', 0):+.1f}%)"
            )
            print(f"    Max drawdown:         ${m['max_drawdown']:.2f} (closed-trade P/L, peak to trough)")
            print(f"    Max consecutive losses: {m['max_consec_losses']}")
            print(f"    Force/emergency exits (all-time): {m.get('force_exits', 0)}")

        for line in V4_DEMOTION_REFERENCE.get(bot, []):
            print(f"    v4 per-bot trigger:   {line}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Bot Evolution Tracker")
    sub = parser.add_subparsers(dest="command")

    snap_p = sub.add_parser("snapshot", help="Take snapshot of all bots")
    snap_p.add_argument("--note", "-n", help="Note for this snapshot")

    change_p = sub.add_parser("changelog", help="Log a change")
    change_p.add_argument("bot", help="Bot name")
    change_p.add_argument("description", help="What changed")

    hist_p = sub.add_parser("history", help="Show bot timeline")
    hist_p.add_argument("bot", help="Bot name")

    comp_p = sub.add_parser("compare", help="Compare two snapshots")
    comp_p.add_argument("bot", help="Bot name")
    comp_p.add_argument("id1", help="First snapshot ID (or prefix)")
    comp_p.add_argument("id2", help="Second snapshot ID (or prefix)")

    peak_p = sub.add_parser("peak", help="Show peak performance")
    peak_p.add_argument("bot", help="Bot name")

    sub.add_parser("dashboard", help="Overview of all bots")
    sub.add_parser("graduation", help="Report v4 graduation facts (no pass/fail verdicts)")

    args = parser.parse_args()

    if args.command == "snapshot":
        take_snapshot(note=args.note)
    elif args.command == "changelog":
        log_change(args.bot, args.description)
    elif args.command == "history":
        show_history(args.bot)
    elif args.command == "compare":
        compare_snapshots(args.bot, args.id1, args.id2)
    elif args.command == "peak":
        show_peak(args.bot)
    elif args.command == "dashboard":
        show_dashboard()
    elif args.command == "graduation":
        check_graduation()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
