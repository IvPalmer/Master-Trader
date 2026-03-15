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
    python3 bot_evolution_tracker.py graduation             # Check graduation gate status
"""

import argparse
import json
import os
import sqlite3
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent / "evolution"
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
            "IchimokuTrendV1",
            "EMACrossoverV1",
            "FuturesSniperV1",
        ]

ACTIVE_BOTS = _load_active_bots()

GRADUATION = {
    "min_trades": 30,
    "min_days": 14,
    "min_pairs": 8,
    "min_pf": 2.0,
    "min_wr": 55,
    "max_single_loss_pct": 5.0,
    "max_drawdown_pct": 15.0,
    "max_consec_losses": 4,
    "max_force_exits": 0,
}


def ensure_dirs():
    DATA_DIR.mkdir(exist_ok=True)
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


def extract_config_params(bot_name):
    """Extract key parameters from config .json file."""
    config_file = CONFIG_DIR / f"{bot_name}.json"
    if not config_file.exists():
        return {}

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
        TRADE_DB_DIR / f"tradesv3.dryrun.{bot_name}.sqlite",
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

    print(f"  {'Bot':<28} {'Trades':>6} {'WR%':>5} {'PF':>6} {'P/L$':>9} {'Peak PF':>8} {'Changes':>8} {'Status'}")
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

            # Status based on graduation gates
            if trades < GRADUATION["min_trades"]:
                status = f"GATE1 ({trades}/{GRADUATION['min_trades']} trades)"
            elif pf < GRADUATION["min_pf"]:
                status = f"GATE2 (PF {pf}<{GRADUATION['min_pf']})"
            elif wr < GRADUATION["min_wr"]:
                status = f"GATE2 (WR {wr}<{GRADUATION['min_wr']})"
            elif pnl <= 0:
                status = "GATE2 (negative P/L)"
            else:
                status = "CANDIDATE"

            print(
                f"  {bot:<28} {trades:>6} {wr:>4.0f}% {pf:>5.1f}x ${pnl:>+8.2f} "
                f"{peak_pf:>8} {changes:>8}  {status}"
            )
        else:
            print(f"  {bot:<28} {'0':>6} {'—':>5} {'—':>6} {'—':>9} {peak_pf:>8} {changes:>8}  NO DATA")

    print()


def check_graduation():
    """Check each bot against graduation gates."""
    print(f"\n{'=' * 80}")
    print(f"  GRADUATION GATE CHECK — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 80}\n")

    for bot in ACTIVE_BOTS:
        m = get_trade_metrics(bot)
        trades = m.get("total_trades", 0)

        print(f"  {bot}")
        print(f"  {'─' * 40}")

        if trades == 0:
            print(f"    GATE 1: FAIL — 0 trades (need {GRADUATION['min_trades']})")
            print()
            continue

        # Gate 1
        g1_trades = trades >= GRADUATION["min_trades"]
        g1_days = m.get("days_running", 0) >= GRADUATION["min_days"]
        g1_pairs = m.get("unique_pairs", 0) >= GRADUATION["min_pairs"]
        g1 = g1_trades and g1_days and g1_pairs

        print(f"    GATE 1 (Sample Size):  {'PASS' if g1 else 'FAIL'}")
        print(f"      Trades:  {trades}/{GRADUATION['min_trades']} {'OK' if g1_trades else 'NEED MORE'}")
        print(f"      Days:    {m.get('days_running', 0)}/{GRADUATION['min_days']} {'OK' if g1_days else 'NEED MORE'}")
        print(f"      Pairs:   {m.get('unique_pairs', 0)}/{GRADUATION['min_pairs']} {'OK' if g1_pairs else 'NEED MORE'}")

        if not g1:
            print()
            continue

        # Gate 2
        g2_pf = m["profit_factor"] >= GRADUATION["min_pf"]
        g2_wr = m["win_rate"] >= GRADUATION["min_wr"]
        g2_pnl = m["total_pnl"] > 0
        g2_loss = abs(m.get("worst_loss_pct", 0)) <= GRADUATION["max_single_loss_pct"]
        g2_dd = m["max_drawdown"] <= (GRADUATION["max_drawdown_pct"] / 100 * 1000)  # 15% of $1000
        g2_consec = m["max_consec_losses"] <= GRADUATION["max_consec_losses"]
        g2_force = m.get("force_exits", 0) <= GRADUATION["max_force_exits"]
        g2 = all([g2_pf, g2_wr, g2_pnl, g2_loss, g2_dd, g2_consec, g2_force])

        print(f"    GATE 2 (Metrics):      {'PASS' if g2 else 'FAIL'}")
        print(f"      PF:         {m['profit_factor']:.2f}x >= {GRADUATION['min_pf']}x {'OK' if g2_pf else 'FAIL'}")
        print(f"      WR:         {m['win_rate']:.0f}% >= {GRADUATION['min_wr']}% {'OK' if g2_wr else 'FAIL'}")
        print(f"      P/L:        ${m['total_pnl']:+.2f} > $0 {'OK' if g2_pnl else 'FAIL'}")
        print(f"      Max Loss:   {abs(m.get('worst_loss_pct', 0)):.1f}% <= {GRADUATION['max_single_loss_pct']}% {'OK' if g2_loss else 'FAIL'}")
        print(f"      Max DD:     ${m['max_drawdown']:.2f} <= ${GRADUATION['max_drawdown_pct'] / 100 * 1000:.0f} {'OK' if g2_dd else 'FAIL'}")
        print(f"      Consec L:   {m['max_consec_losses']} <= {GRADUATION['max_consec_losses']} {'OK' if g2_consec else 'FAIL'}")
        print(f"      Force Exit: {m.get('force_exits', 0)} <= {GRADUATION['max_force_exits']} {'OK' if g2_force else 'FAIL'}")

        if g2:
            print(f"    GATE 3 (Consistency):  (manual review required)")
            print(f"    GATE 4 (Technical):    (checklist in GRADUATION_CRITERIA.md)")
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
    sub.add_parser("graduation", help="Check graduation gates")

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
