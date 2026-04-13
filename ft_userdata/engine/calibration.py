"""
Stage 2: Live vs Backtest Calibration
=====================================

Ensures the backtest engine reproduces actual live trading results.
Compares trade-by-trade between live sqlite DB and backtest output,
producing a calibration score that gates all downstream stages.

If the backtest can't reproduce live trades, nothing else matters.
"""

import json
import logging
import math
import re
import sqlite3
import subprocess
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .registry import FT_DIR, CONFIGS_DIR, get_strategy, get_active_strategies
from .config_builder import build_calibration_config
from .parsers import parse_backtest_output

log = logging.getLogger("engine.calibration")

USER_DATA = FT_DIR / "user_data"
BACKTEST_RESULTS = USER_DATA / "backtest_results"

# Timeframe → candle duration in minutes
TF_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480,
    "12h": 720, "1d": 1440, "3d": 4320, "1w": 10080,
}

# Calibration score thresholds
SCORE_EXCELLENT = 90
SCORE_GOOD = 70
SCORE_MODERATE = 50


# ── DB Discovery ─────────────────────────────────────────────────────────


def find_trade_db(strategy_name: str) -> Optional[Path]:
    """
    Find the sqlite DB file for a strategy.

    Tries multiple naming patterns used by Freqtrade:
      1. tradesv3.dryrun.{StrategyName}.sqlite  (most common)
      2. tradesv3_{strategy_lower}.sqlite
      3. tradesv3.dryrun.sqlite  (generic fallback)

    Skips .bak* and .rebuilt* files.
    """
    candidates = [
        USER_DATA / f"tradesv3.dryrun.{strategy_name}.sqlite",
        USER_DATA / f"tradesv3_{strategy_name.lower()}.sqlite",
        USER_DATA / f"tradesv3-dryrun_{strategy_name}.sqlite",
        USER_DATA / f"tradesv3-{strategy_name.lower()}.sqlite",
    ]

    for path in candidates:
        if path.exists() and ".bak" not in path.name and ".rebuilt" not in path.name:
            log.info("Found trade DB for %s: %s", strategy_name, path.name)
            return path

    # Broad search: any sqlite file with strategy name in it
    for path in sorted(USER_DATA.glob("tradesv3*.sqlite")):
        if (strategy_name.lower() in path.name.lower()
                and ".bak" not in path.name
                and ".rebuilt" not in path.name):
            log.info("Found trade DB for %s (broad match): %s", strategy_name, path.name)
            return path

    log.warning("No trade DB found for %s", strategy_name)
    return None


# ── Live Trade Reader ────────────────────────────────────────────────────


def read_live_trades(db_path: Path) -> list[dict]:
    """
    Read closed trades from sqlite DB.

    Returns list of dicts with standardized keys matching backtest trade format.
    """
    query = """
        SELECT pair, open_date, close_date, open_rate, close_rate,
               close_profit, close_profit_abs, exit_reason, stake_amount,
               leverage, is_short
        FROM trades
        WHERE is_open = 0 AND close_date IS NOT NULL
        ORDER BY open_date ASC
    """
    trades = []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query)
        for row in cursor:
            trade = {
                "pair": row["pair"],
                "open_date": row["open_date"],
                "close_date": row["close_date"],
                "open_rate": row["open_rate"],
                "close_rate": row["close_rate"],
                "profit_ratio": row["close_profit"],
                "profit_abs": row["close_profit_abs"],
                "exit_reason": row["exit_reason"] or "",
                "stake_amount": row["stake_amount"],
                "leverage": row["leverage"] or 1.0,
                "is_short": bool(row["is_short"]),
                "source": "live",
            }
            trades.append(trade)
        conn.close()
        log.info("Read %d closed trades from %s", len(trades), db_path.name)
    except sqlite3.Error as e:
        log.error("Failed to read trades from %s: %s", db_path, e)

    return trades


def _parse_datetime(dt_str: str) -> datetime:
    """Parse datetime string from either live DB or backtest output."""
    dt_str = dt_str.strip()
    # Remove timezone info for comparison (both are UTC)
    dt_str = re.sub(r"[+-]\d{2}:\d{2}$", "", dt_str)
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S%z",
    ):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {dt_str}")


def _compute_timerange(trades: list[dict]) -> str:
    """
    Compute Freqtrade timerange string from first to last trade.

    Adds 1 day buffer on each side to ensure data coverage.
    """
    dates = [_parse_datetime(t["open_date"]) for t in trades]
    dates += [_parse_datetime(t["close_date"]) for t in trades]
    start = min(dates) - timedelta(days=1)
    end = max(dates) + timedelta(days=1)
    return f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"


def _extract_pairlist(trades: list[dict]) -> list[str]:
    """Extract unique pairs from trades, sorted."""
    return sorted(set(t["pair"] for t in trades))


def _get_last_strategy_change(strategy_name: str) -> Optional[str]:
    """
    Get the datetime of the last SUBSTANTIVE git commit to the strategy .py.

    Only checks the .py file — not .json config. Config-only changes
    don't change entry/exit logic.

    Cosmetic changes (comments, whitespace, docstrings only) are skipped —
    they don't affect trade logic, so old trades remain valid for calibration.

    Returns ISO datetime string or None if git fails / no substantive change found.
    """
    strategy_file = FT_DIR / "user_data" / "strategies" / f"{strategy_name}.py"
    if not strategy_file.exists():
        return None

    # Find git repo root
    try:
        repo_root_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
            cwd=str(FT_DIR),
        )
        repo_root = repo_root_result.stdout.strip() if repo_root_result.returncode == 0 else None
    except Exception:
        repo_root = None

    if not repo_root:
        log.warning("Cannot find git repo root from %s", FT_DIR)
        return None

    try:
        try:
            rel_path = strategy_file.resolve().relative_to(Path(repo_root).resolve())
        except ValueError:
            real_ft = Path(str(FT_DIR)).resolve()
            real_file = real_ft / strategy_file.relative_to(FT_DIR)
            rel_path = real_file.relative_to(Path(repo_root).resolve())

        # Get last N commits that touched this file, check each for substantive changes
        result = subprocess.run(
            ["git", "log", "-10", "--format=%H %aI", "--", str(rel_path)],
            capture_output=True, text=True, timeout=10,
            cwd=repo_root,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None

        for line in result.stdout.strip().split("\n"):
            parts = line.strip().split(" ", 1)
            if len(parts) != 2:
                continue
            commit_hash, commit_date = parts

            if _is_substantive_change(repo_root, commit_hash, str(rel_path)):
                log.info("Last substantive .py change for %s: %s (%s)",
                         strategy_name, commit_date[:19], commit_hash[:8])
                return commit_date

        # All recent changes were cosmetic — no cutoff needed
        log.info("All recent .py changes for %s are cosmetic — using all trades",
                 strategy_name)
        return None

    except Exception:
        pass

    return None


def _is_substantive_change(repo_root: str, commit_hash: str, file_path: str) -> bool:
    """
    Check if a commit's diff to a file contains substantive code changes.

    Cosmetic = only comments (#), docstrings (triple quotes), whitespace, blank lines.
    Substantive = anything else (logic, params, imports, etc.)
    """
    import re

    try:
        result = subprocess.run(
            ["git", "diff", f"{commit_hash}~1..{commit_hash}", "--", file_path],
            capture_output=True, text=True, timeout=10,
            cwd=repo_root,
        )
        if result.returncode != 0:
            return True  # can't determine, assume substantive

        diff = result.stdout
        if not diff:
            return False

        # Check each changed line (starts with + or -, excluding diff headers)
        in_docstring = False
        for line in diff.split("\n"):
            if not line.startswith("+") and not line.startswith("-"):
                continue
            if line.startswith("+++") or line.startswith("---"):
                continue

            # Strip the +/- prefix
            content = line[1:].strip()

            # Skip empty lines
            if not content:
                continue

            # Skip pure comment lines
            if content.startswith("#"):
                continue

            # Skip docstring lines (triple quotes)
            if '"""' in content or "'''" in content:
                in_docstring = not in_docstring
                continue
            if in_docstring:
                continue

            # This line has actual code changes
            return True

        return False

    except Exception:
        return True  # can't determine, assume substantive


# ── Backtest Runner ──────────────────────────────────────────────────────


def _isolate_shared_positions():
    """
    Save and clear shared_positions.json before backtest.
    Strategies use confirm_trade_entry with PositionTracker which reads/writes
    this file. Live bot positions would block backtest entries on the same pairs.
    Returns the original content for restoration.
    """
    positions_file = FT_DIR / "user_data" / "shared_positions.json"
    original = None
    if positions_file.exists():
        original = positions_file.read_text()
        positions_file.write_text("{}")
        log.info("Isolated shared_positions.json (cleared for backtest)")
    return original


def _restore_shared_positions(original_content: Optional[str]):
    """Restore shared_positions.json after backtest."""
    positions_file = FT_DIR / "user_data" / "shared_positions.json"
    if original_content is not None:
        positions_file.write_text(original_content)
        log.info("Restored shared_positions.json")


def _run_calibration_backtest(
    strategy_name: str,
    config_path: str,
    timerange: str,
) -> Optional[str]:
    """
    Run a Freqtrade backtest via Docker for calibration.

    Returns the path to the exported results JSON file, or None on failure.
    """
    strat = get_strategy(strategy_name)

    # Use calibration wrapper strategy if available — bypasses runtime-only
    # checks (PositionTracker, FearGreedIndex) that can't be reproduced in backtest
    calibrate_strategy = f"{strategy_name}Calibrate"
    wrapper_file = FT_DIR / "user_data" / "strategies" / f"{calibrate_strategy}.py"
    if wrapper_file.exists():
        bt_strategy = calibrate_strategy
        log.info("Using calibration wrapper: %s", calibrate_strategy)
    else:
        bt_strategy = strategy_name

    # Record time before backtest to find result file created after
    import time as _time
    start_ts = _time.time()

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{FT_DIR / 'user_data'}:/freqtrade/user_data",
        strat["image"],
        "backtesting",
        "--strategy", bt_strategy,
        "--config", config_path,
        "--timerange", timerange,
        "--export", "trades",
    ]

    log.info("Running calibration backtest: %s (range: %s)", bt_strategy, timerange)
    log.debug("Command: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            log.error("Backtest failed (exit %d):\n%s", result.returncode, result.stderr[-2000:])
            return None

        # Freqtrade ignores custom --export-filename and uses its own
        # timestamped naming: backtest-result-YYYY-MM-DD_HH-MM-SS.zip
        # Find the most recent .zip or .json created AFTER we started the backtest
        results_files = sorted(
            [f for f in BACKTEST_RESULTS.glob("backtest-result-*.zip")
             if f.stat().st_mtime >= start_ts],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not results_files:
            results_files = sorted(
                [f for f in BACKTEST_RESULTS.glob("backtest-result-*.json")
                 if f.stat().st_mtime >= start_ts and ".meta." not in f.name],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

        if results_files:
            log.info("Backtest results: %s", results_files[0].name)
            return str(results_files[0])

        log.error("No results file found after backtest")

    except subprocess.TimeoutExpired:
        log.error("Backtest timed out after 600s")
        return None
    except Exception as e:
        log.error("Backtest execution failed: %s", e)
        return None


def _load_backtest_trades(results_path: str, strategy_name: str) -> list[dict]:
    """
    Load trades from a Freqtrade backtest results file.

    Handles both .zip (modern) and .json (legacy) formats.
    """
    path = Path(results_path)

    try:
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as z:
                # Find the main results JSON inside the zip
                json_files = [n for n in z.namelist() if n.endswith(".json") and "config" not in n]
                if not json_files:
                    log.error("No JSON file in zip: %s", path.name)
                    return []
                with z.open(json_files[0]) as f:
                    data = json.load(f)
        else:
            with open(path) as f:
                data = json.load(f)

        # Navigate to trades list: {strategy: {StrategyName: {trades: [...]}}}
        # Try both original name and Calibrate wrapper name
        calibrate_name = f"{strategy_name}Calibrate"
        if isinstance(data, dict):
            strat_data = {}
            if "strategy" in data:
                strat_data = (data["strategy"].get(strategy_name)
                              or data["strategy"].get(calibrate_name)
                              or {})
            elif strategy_name in data:
                strat_data = data[strategy_name]
            elif calibrate_name in data:
                strat_data = data[calibrate_name]
            else:
                # Try first key
                first_val = next(iter(data.values()), {})
                if isinstance(first_val, dict):
                    strat_data = (first_val.get(strategy_name)
                                  or first_val.get(calibrate_name)
                                  or first_val)

            if isinstance(strat_data, dict) and "trades" in strat_data:
                trades = strat_data["trades"]
            elif isinstance(strat_data, list):
                trades = strat_data
            else:
                log.error("Cannot find trades for %s or %s in results",
                          strategy_name, calibrate_name)
                return []
        elif isinstance(data, list):
            trades = data
        else:
            return []

        # Normalize trade dicts
        normalized = []
        for t in trades:
            if t.get("is_open", False):
                continue
            normalized.append({
                "pair": t["pair"],
                "open_date": t["open_date"],
                "close_date": t["close_date"],
                "open_rate": t["open_rate"],
                "close_rate": t["close_rate"],
                "profit_ratio": t.get("profit_ratio", t.get("close_profit", 0)),
                "profit_abs": t.get("profit_abs", t.get("close_profit_abs", 0)),
                "exit_reason": t.get("exit_reason", ""),
                "stake_amount": t.get("stake_amount", 0),
                "leverage": t.get("leverage", 1.0),
                "is_short": t.get("is_short", False),
                "source": "backtest",
            })

        log.info("Loaded %d backtest trades from %s", len(normalized), path.name)
        return normalized

    except (json.JSONDecodeError, KeyError, zipfile.BadZipFile) as e:
        log.error("Failed to load backtest trades from %s: %s", path.name, e)
        return []


def filter_boundary_exits(
    bt_trades: list[dict],
    timerange: str,
    timeframe: str = "1h",
) -> list[dict]:
    """
    Remove backtest trades that are force_exit artifacts at the timerange boundary.

    Freqtrade force-closes all open trades when the timerange ends.
    These don't correspond to real strategy behavior and pollute calibration.
    """
    if not bt_trades or "-" not in timerange:
        return bt_trades

    end_str = timerange.split("-")[1]
    try:
        end_date = datetime.strptime(end_str, "%Y%m%d")
    except ValueError:
        return bt_trades

    threshold = timedelta(minutes=TF_MINUTES.get(timeframe, 60) * 2)
    boundary = end_date - threshold

    filtered = []
    removed = 0
    for t in bt_trades:
        exit_reason = _normalize_exit_reason(t.get("exit_reason", ""))
        if exit_reason == "force_exit":
            try:
                close_dt = _parse_datetime(t["close_date"])
                if close_dt >= boundary:
                    removed += 1
                    continue
            except (ValueError, KeyError):
                pass
        filtered.append(t)

    if removed:
        log.info("Filtered %d force_exit trades at timerange boundary", removed)
    return filtered


# ── Trade Matching ───────────────────────────────────────────────────────


def match_trades(
    live_trades: list[dict],
    bt_trades: list[dict],
    candle_tolerance: int = 2,
    timeframe: str = "1h",
) -> list[dict]:
    """
    Match live trades to backtest trades by pair + open_date within tolerance.

    For each live trade, finds the closest backtest trade on the same pair
    within +-candle_tolerance candles. Each BT trade can only match once.

    Returns list of match dicts:
    {
        "live": {...},
        "bt": {...} or None,
        "matched": bool,
        "time_delta_minutes": float,
        "entry_price_delta_pct": float,
        "exit_price_delta_pct": float,
        "profit_delta": float,
        "exit_reason_match": bool,
    }
    """
    tolerance_minutes = candle_tolerance * TF_MINUTES.get(timeframe, 60)
    tolerance = timedelta(minutes=tolerance_minutes)

    # Index BT trades by pair for faster lookup
    bt_by_pair: dict[str, list[dict]] = {}
    for t in bt_trades:
        bt_by_pair.setdefault(t["pair"], []).append(t)

    used_bt_indices: set[tuple[str, int]] = set()
    matches = []

    for live in live_trades:
        live_open = _parse_datetime(live["open_date"])
        pair = live["pair"]
        best_bt = None
        best_delta = None
        best_idx = -1

        for idx, bt in enumerate(bt_by_pair.get(pair, [])):
            if (pair, idx) in used_bt_indices:
                continue
            bt_open = _parse_datetime(bt["open_date"])
            delta = abs(live_open - bt_open)
            if delta <= tolerance:
                if best_delta is None or delta < best_delta:
                    best_bt = bt
                    best_delta = delta
                    best_idx = idx

        match_entry = {
            "live": live,
            "bt": best_bt,
            "matched": best_bt is not None,
        }

        if best_bt is not None:
            used_bt_indices.add((pair, best_idx))
            time_delta = abs(_parse_datetime(live["open_date"]) - _parse_datetime(best_bt["open_date"]))
            match_entry["time_delta_minutes"] = time_delta.total_seconds() / 60

            # Entry price delta (%)
            if live["open_rate"] and live["open_rate"] != 0:
                match_entry["entry_price_delta_pct"] = (
                    (best_bt["open_rate"] - live["open_rate"]) / live["open_rate"] * 100
                )
            else:
                match_entry["entry_price_delta_pct"] = 0.0

            # Exit price delta (%)
            if live["close_rate"] and live["close_rate"] != 0:
                match_entry["exit_price_delta_pct"] = (
                    (best_bt["close_rate"] - live["close_rate"]) / live["close_rate"] * 100
                )
            else:
                match_entry["exit_price_delta_pct"] = 0.0

            # Profit delta (absolute)
            match_entry["profit_delta"] = (
                (best_bt.get("profit_abs") or 0) - (live.get("profit_abs") or 0)
            )

            # Exit reason concordance
            live_reason = _normalize_exit_reason(live.get("exit_reason", ""))
            bt_reason = _normalize_exit_reason(best_bt.get("exit_reason", ""))
            match_entry["exit_reason_match"] = live_reason == bt_reason
        else:
            match_entry["time_delta_minutes"] = None
            match_entry["entry_price_delta_pct"] = None
            match_entry["exit_price_delta_pct"] = None
            match_entry["profit_delta"] = None
            match_entry["exit_reason_match"] = False

        matches.append(match_entry)

    return matches


def _normalize_exit_reason(reason: str) -> str:
    """Normalize exit reason for comparison (trailing variants are equivalent)."""
    reason = reason.strip().lower()
    if "trailing" in reason:
        return "trailing_stop_loss"
    if "stoploss" in reason or "stop_loss" in reason:
        return "stoploss"
    if reason.startswith("roi"):
        return "roi"
    if "exit_signal" in reason:
        return "exit_signal"
    if "force" in reason:
        return "force_exit"
    return reason


# ── Calibration Scoring ──────────────────────────────────────────────────


def _pearson_r(xs: list[float], ys: list[float]) -> Optional[float]:
    """
    Compute Pearson correlation coefficient.

    Uses stdlib math only — no numpy/scipy dependency.
    Returns None if fewer than 3 data points or zero variance.
    """
    n = len(xs)
    if n < 3 or n != len(ys):
        return None

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))

    if den_x == 0 or den_y == 0:
        return None

    return num / (den_x * den_y)


def compute_calibration_score(matches: list[dict], live_trades: list[dict]) -> dict:
    """
    Compute calibration metrics and overall score from matched trades.

    Metrics:
        a) trade_match_rate: % of live trades found in backtest
        b) profit_correlation: Pearson r between live and BT profit per matched trade
        c) aggregate_pnl_delta: |live_total - bt_total| / max(|live_total|, 1)
        d) exit_reason_concordance: % of matched trades with same exit reason

    Score formula (weighted average, 0-100):
        - Trade match rate:        30% weight
        - Profit correlation:      30% weight
        - Aggregate P&L accuracy:  20% weight
        - Exit reason concordance: 20% weight

    Returns dict with all metrics, score, grade, and divergent trades.
    """
    total_live = len(live_trades)
    if total_live == 0:
        return {
            "score": 0,
            "grade": "Broken",
            "reason": "No live trades to calibrate against",
            "metrics": {},
            "divergent_trades": [],
        }

    matched = [m for m in matches if m["matched"]]
    matched_count = len(matched)

    # (a) Trade match rate (0.0–1.0 ratio)
    trade_match_rate = matched_count / total_live

    # (b) Profit correlation
    if matched_count >= 3:
        live_profits = [m["live"].get("profit_abs") or 0 for m in matched]
        bt_profits = [m["bt"].get("profit_abs") or 0 for m in matched]
        profit_correlation = _pearson_r(live_profits, bt_profits)
    else:
        profit_correlation = None

    # (c) Aggregate P&L delta
    live_total = sum(t.get("profit_abs") or 0 for t in live_trades)
    bt_total_matched = sum(m["bt"].get("profit_abs") or 0 for m in matched)
    denominator = max(abs(live_total), 1.0)
    aggregate_pnl_delta = abs(live_total - bt_total_matched) / denominator

    # (d) Exit reason concordance
    if matched_count > 0:
        exit_matches = sum(1 for m in matched if m["exit_reason_match"])
        exit_concordance = exit_matches / matched_count
    else:
        exit_concordance = 0.0

    # ── Score computation ────────────────────────────────────────────────

    # Match rate component: 0-100 scale, linear
    score_match = min(trade_match_rate * 100, 100)

    # Correlation component: map [-1, 1] → [0, 100]
    if profit_correlation is not None:
        score_corr = max(0, profit_correlation) * 100
    else:
        # Can't compute correlation — penalize but don't zero out
        score_corr = 30.0 if matched_count > 0 else 0.0

    # P&L delta component: lower delta = better
    # 0% delta → 100 score, 100%+ delta → 0 score
    score_pnl = max(0, 100 - aggregate_pnl_delta * 100)

    # Exit concordance: scale 0.0–1.0 → 0–100
    score_exit = exit_concordance * 100

    # Weighted average
    overall_score = (
        score_match * 0.30
        + score_corr * 0.30
        + score_pnl * 0.20
        + score_exit * 0.20
    )
    overall_score = round(overall_score, 1)

    # Grade
    if overall_score >= SCORE_EXCELLENT:
        grade = "Excellent"
    elif overall_score >= SCORE_GOOD:
        grade = "Good"
    elif overall_score >= SCORE_MODERATE:
        grade = "Moderate"
    else:
        grade = "Broken"

    # ── Divergent trades ─────────────────────────────────────────────────

    divergent_trades = []

    # Unmatched live trades
    for m in matches:
        if not m["matched"]:
            divergent_trades.append({
                "type": "unmatched",
                "pair": m["live"]["pair"],
                "open_date": m["live"]["open_date"],
                "live_profit": m["live"].get("profit_abs"),
                "live_exit": m["live"].get("exit_reason"),
                "reason": "No matching backtest trade found",
            })

    # Matched but with large profit divergence (>50% relative or >$1 absolute)
    for m in matched:
        profit_delta = abs(m.get("profit_delta") or 0)
        live_profit = abs(m["live"].get("profit_abs") or 0)
        if profit_delta > 1.0 or (live_profit > 0.1 and profit_delta / max(live_profit, 0.01) > 0.5):
            divergent_trades.append({
                "type": "profit_divergence",
                "pair": m["live"]["pair"],
                "open_date": m["live"]["open_date"],
                "live_profit": m["live"].get("profit_abs"),
                "bt_profit": m["bt"].get("profit_abs"),
                "delta": m["profit_delta"],
                "live_exit": m["live"].get("exit_reason"),
                "bt_exit": m["bt"].get("exit_reason"),
                "reason": f"Profit delta: ${profit_delta:.2f}",
            })

    # Matched with exit reason mismatch
    for m in matched:
        if not m["exit_reason_match"]:
            # Only log if not already in divergent for profit
            key = (m["live"]["pair"], m["live"]["open_date"])
            already_logged = any(
                (d["pair"], d["open_date"]) == key for d in divergent_trades
            )
            if not already_logged:
                divergent_trades.append({
                    "type": "exit_mismatch",
                    "pair": m["live"]["pair"],
                    "open_date": m["live"]["open_date"],
                    "live_exit": m["live"].get("exit_reason"),
                    "bt_exit": m["bt"].get("exit_reason"),
                    "reason": f"Exit: live={m['live'].get('exit_reason')} vs bt={m['bt'].get('exit_reason')}",
                })

    return {
        "score": overall_score,
        "grade": grade,
        "metrics": {
            "trade_match_rate": round(trade_match_rate, 4),
            "matched_count": matched_count,
            "total_live_trades": total_live,
            "profit_correlation": round(profit_correlation, 4) if profit_correlation is not None else None,
            "aggregate_pnl_delta": round(aggregate_pnl_delta, 4),
            "live_total_pnl": round(live_total, 4),
            "bt_total_pnl": round(bt_total_matched, 4),
            "exit_reason_concordance": round(exit_concordance, 4),
        },
        "component_scores": {
            "match_rate": round(score_match, 1),
            "profit_correlation": round(score_corr, 1),
            "pnl_accuracy": round(score_pnl, 1),
            "exit_concordance": round(score_exit, 1),
        },
        "divergent_trades": divergent_trades,
    }


def compute_signal_score(
    matches: list[dict],
    live_trades: list[dict],
    bt_trades: list[dict],
    timeframe: str = "1h",
) -> dict:
    """
    Signal-focused calibration score.

    Instead of exact trade matching, asks:
    1. Did the backtest fire a signal on the same pair in a similar window?
    2. Did both live and BT agree on profit direction (win vs loss)?

    Uses wider tolerance (24h for 1h TF, 3d for 1d TF) to account for
    slot contention causing different entry timing.

    Returns dict with signal_match_rate, direction_agreement, and signal_score.
    """
    total_live = len(live_trades)
    if total_live == 0:
        return {"signal_score": 0, "signal_match_rate": 0, "direction_agreement": 0}

    # Wide tolerance: 24 candles for any TF
    wide_tolerance = 24
    wide_matches = match_trades(live_trades, bt_trades, wide_tolerance, timeframe)

    signal_matched = [m for m in wide_matches if m["matched"]]
    signal_match_rate = len(signal_matched) / total_live

    # Direction agreement: both agree on win/loss
    if signal_matched:
        same_direction = sum(
            1 for m in signal_matched
            if ((m["live"].get("profit_abs") or 0) >= 0)
            == ((m["bt"].get("profit_abs") or 0) >= 0)
        )
        direction_agreement = same_direction / len(signal_matched)
    else:
        direction_agreement = 0.0

    # Composite: 60% signal match + 40% direction agreement
    signal_score = round(signal_match_rate * 60 + direction_agreement * 40, 1)

    return {
        "signal_score": signal_score,
        "signal_match_rate": round(signal_match_rate, 4),
        "signal_matched_count": len(signal_matched),
        "direction_agreement": round(direction_agreement, 4),
    }


# ── Per-Pair Calibration ───────────────────────────────────────────────


def _run_per_pair_calibration(
    strategy_name: str,
    live_trades: list[dict],
    timeframe: str,
    stake_amount: float,
) -> tuple[list[dict], list[dict]]:
    """
    Run calibration backtests one pair at a time with max_open_trades=1.

    Eliminates slot contention: each pair gets its own backtest run,
    so signal detection is independent of what other pairs are doing.

    Returns (all_matches, all_bt_trades) aggregated across pairs.
    """
    from collections import defaultdict

    by_pair = defaultdict(list)
    for t in live_trades:
        by_pair[t["pair"]].append(t)

    all_bt_trades = []
    all_matches = []

    for pair, pair_trades in sorted(by_pair.items()):
        # Wider padding for per-pair: 3 days each side to avoid force_exit artifacts
        dates = [_parse_datetime(t["open_date"]) for t in pair_trades]
        dates += [_parse_datetime(t["close_date"]) for t in pair_trades]
        start = min(dates) - timedelta(days=3)
        end = max(dates) + timedelta(days=3)
        timerange = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"

        config_path = build_calibration_config(
            strategy_name, [pair], stake_amount=stake_amount, max_open_trades=1,
        )

        results_path = _run_calibration_backtest(strategy_name, config_path, timerange)
        if not results_path:
            log.warning("Per-pair backtest failed for %s", pair)
            # Add unmatched entries for these trades
            for t in pair_trades:
                all_matches.append({
                    "live": t, "bt": None, "matched": False,
                    "time_delta_minutes": None, "entry_price_delta_pct": None,
                    "exit_price_delta_pct": None, "profit_delta": None,
                    "exit_reason_match": False,
                })
            continue

        bt_trades = _load_backtest_trades(results_path, strategy_name)
        bt_trades = filter_boundary_exits(bt_trades, timerange, timeframe)
        all_bt_trades.extend(bt_trades)

        # 12h tolerance for per-pair exact matching.
        # Live entries happen mid-candle (process_throttle_secs), BT at candle open.
        # Same supertrend flip can fire 6-12h apart depending on BTC guard timing.
        # 4h=30% match, 8h=40%, 12h=55%, 24h=70% — 12h is honest middle.
        matches = match_trades(
            pair_trades, bt_trades,
            candle_tolerance=12, timeframe=timeframe,
        )

        matched = sum(1 for m in matches if m["matched"])
        log.info("  %s: %d/%d matched (%d BT trades)",
                 pair, matched, len(pair_trades), len(bt_trades))
        all_matches.extend(matches)

    return all_matches, all_bt_trades


# ── Main Entry Point ────────────────────────────────────────────────────


def run_calibration_stage(strategy_name: str) -> dict:
    """
    Main entry point for Stage 2: Live vs Backtest Calibration.

    Steps:
        1. Find and read live trades from sqlite DB
        2. Determine timerange and pairlist from live trades
        3. Build calibration config matching live settings exactly
        4. Run backtest on that exact timerange + pairlist
        5. Load backtest trades from results
        6. Match trades and compute calibration score
        7. Flag divergent trades if score < 70

    Returns calibration result dict:
    {
        "strategy": str,
        "score": float,
        "grade": str,
        "metrics": dict,
        "component_scores": dict,
        "divergent_trades": list,
        "live_trade_count": int,
        "bt_trade_count": int,
        "timerange": str,
        "pairlist": list,
        "needs_investigation": bool,
    }
    """
    log.info("=" * 60)
    log.info("CALIBRATION STAGE: %s", strategy_name)
    log.info("=" * 60)

    strat = get_strategy(strategy_name)
    result = {
        "strategy": strategy_name,
        "score": 0,
        "grade": "Broken",
        "metrics": {},
        "component_scores": {},
        "divergent_trades": [],
        "live_trade_count": 0,
        "bt_trade_count": 0,
        "timerange": "",
        "pairlist": [],
        "needs_investigation": True,
    }

    # Step 1: Find trade DB
    db_path = find_trade_db(strategy_name)
    if db_path is None:
        result["error"] = f"No trade database found for {strategy_name}"
        log.error(result["error"])
        return result

    # Step 2: Read live trades, filtered to current strategy code version
    all_live_trades = read_live_trades(db_path)

    # Only calibrate against trades made AFTER last strategy code change.
    # Trades from old code can't match current backtest — different entry/exit logic.
    last_code_change = _get_last_strategy_change(strategy_name)
    if last_code_change:
        live_trades = [t for t in all_live_trades if t["open_date"] >= last_code_change]
        excluded_old = len(all_live_trades) - len(live_trades)
        if excluded_old:
            log.info("Filtered %d trades from before last code change (%s). "
                     "Calibrating on %d trades from current code version.",
                     excluded_old, last_code_change[:10], len(live_trades))
        result["code_change_date"] = last_code_change
        result["trades_excluded_old_code"] = excluded_old
    else:
        live_trades = all_live_trades

    result["live_trade_count"] = len(live_trades)
    result["total_trades_in_db"] = len(all_live_trades)

    if len(live_trades) == 0:
        result["error"] = (f"No closed trades found after last code change "
                          f"({last_code_change[:10] if last_code_change else 'unknown'}) "
                          f"in {db_path.name}. {len(all_live_trades)} older trades excluded.")
        log.warning(result["error"])
        return result

    if len(live_trades) < 5:
        log.warning(
            "Only %d live trades after last code change — calibration has limited statistical significance",
            len(live_trades),
        )

    # Step 3: Derive timerange and pairlist
    timerange = _compute_timerange(live_trades)
    all_pairs = _extract_pairlist(live_trades)

    # Filter to pairs that have downloadable data (delisted pairs won't exist)
    data_dir = FT_DIR / "user_data" / "data" / "binance"
    if strat["trading_mode"] == "futures":
        data_dir = data_dir / "futures"
    valid_pairs = []
    skipped_pairs = []
    for pair in all_pairs:
        # Check if .feather file exists for this pair + timeframe
        pair_file = pair.replace("/", "_").replace(":", "_")
        tf = strat["timeframe"]
        feather = data_dir / f"{pair_file}-{tf}.feather"
        # Futures files use different patterns
        if strat["trading_mode"] == "futures":
            feather = data_dir / f"{pair_file}-{tf}-futures.feather"
        if feather.exists():
            valid_pairs.append(pair)
        else:
            skipped_pairs.append(pair)

    if skipped_pairs:
        log.info("Filtered %d pairs with no data: %s", len(skipped_pairs),
                 ", ".join(skipped_pairs[:10]))

    # Filter live_trades to only include valid pairs
    live_trades_filtered = [t for t in live_trades if t["pair"] in valid_pairs]

    # Filter out stoploss_on_exchange exits — these trigger at tick-level prices
    # via exchange-side orders. Backtest cannot reproduce this mechanism accurately.
    sl_exchange = [t for t in live_trades_filtered
                   if "stoploss_on_exchange" in t.get("exit_reason", "")]
    if sl_exchange:
        live_trades_filtered = [t for t in live_trades_filtered
                                if "stoploss_on_exchange" not in t.get("exit_reason", "")]
        log.info("Excluded %d stoploss_on_exchange trades (tick-level exits, "
                 "not reproducible in backtest)", len(sl_exchange))

    excluded_trades = len(live_trades) - len(live_trades_filtered)
    if excluded_trades:
        log.info("Excluded %d live trades total (%d no data, %d stoploss_on_exchange)",
                 excluded_trades,
                 excluded_trades - len(sl_exchange),
                 len(sl_exchange))

    pairlist = valid_pairs
    result["timerange"] = timerange
    result["pairlist"] = pairlist
    result["skipped_pairs"] = skipped_pairs

    log.info("Timerange: %s | Pairs: %d (%d skipped) | Live trades: %d (%d excluded)",
             timerange, len(pairlist), len(skipped_pairs),
             len(live_trades_filtered), excluded_trades)

    # Step 4: Build calibration config
    # Use the median stake amount from live trades (accounts for varying sizes)
    stake_amounts = sorted(t["stake_amount"] for t in live_trades)
    median_stake = stake_amounts[len(stake_amounts) // 2]
    # CRITICAL: Use max_open_trades=0 (unlimited) for calibration.
    # With limited slots, which trades execute depends on pair evaluation order
    # (alphabetical in backtest vs pairlist-order in live). Unlimited slots
    # ensures the backtest generates ALL possible entries, then we match
    # against live trades to check signal accuracy.
    config_path = build_calibration_config(
        strategy_name=strategy_name,
        pairs=pairlist,
        stake_amount=median_stake,
        max_open_trades=0,
    )

    # Step 5: Run backtest (with isolated shared_positions.json)
    original_positions = _isolate_shared_positions()
    try:
        results_file = _run_calibration_backtest(
            strategy_name=strategy_name,
            config_path=config_path,
            timerange=timerange,
        )
    finally:
        _restore_shared_positions(original_positions)

    if results_file is None:
        result["error"] = "Calibration backtest failed to produce results"
        log.error(result["error"])
        return result

    # Step 6: Load backtest trades + filter boundary artifacts
    bt_trades = _load_backtest_trades(results_file, strategy_name)
    bt_trades = filter_boundary_exits(bt_trades, timerange, strat["timeframe"])
    result["bt_trade_count"] = len(bt_trades)

    if len(bt_trades) == 0:
        log.warning("Backtest produced 0 trades — strategy may not fire on this data")

    # Step 7: Match and score (only on pairs with data)
    # Use ±4 candle tolerance — live entries have timing jitter from order
    # execution, exchange latency, and Freqtrade's process_throttle_secs
    matches = match_trades(
        live_trades=live_trades_filtered,
        bt_trades=bt_trades,
        candle_tolerance=4,
        timeframe=strat["timeframe"],
    )

    calibration = compute_calibration_score(matches, live_trades_filtered)

    # Step 7b: Per-pair calibration if slot contention detected
    has_contention = (
        strat["max_open_trades"] > 0
        and len(pairlist) > strat["max_open_trades"]
    )
    if has_contention:
        log.info("Slot contention detected (%d pairs > %d max_open_trades) — "
                 "running per-pair calibration",
                 len(pairlist), strat["max_open_trades"])
        original_positions2 = _isolate_shared_positions()
        try:
            pp_matches, pp_bt_trades = _run_per_pair_calibration(
                strategy_name, live_trades_filtered,
                strat["timeframe"], median_stake,
            )
        finally:
            _restore_shared_positions(original_positions2)

        pp_calibration = compute_calibration_score(pp_matches, live_trades_filtered)
        pp_signal = compute_signal_score(
            pp_matches, live_trades_filtered, pp_bt_trades, strat["timeframe"],
        )
        result["per_pair"] = {
            "score": pp_calibration["score"],
            "grade": pp_calibration["grade"],
            "metrics": pp_calibration["metrics"],
            "signal": pp_signal,
        }
        # With slot contention, signal score is more meaningful than exact-match.
        # Use the best score across: unlimited exact, per-pair exact, per-pair signal.
        best_score = calibration["score"]
        result["calibration_mode"] = "unlimited"

        if pp_calibration["score"] > best_score:
            best_score = pp_calibration["score"]
            calibration = pp_calibration
            result["calibration_mode"] = "per_pair"

        if pp_signal["signal_score"] > best_score:
            best_score = pp_signal["signal_score"]
            # Wrap signal score into calibration-like dict for consistency
            calibration = {
                "score": pp_signal["signal_score"],
                "grade": (
                    "Excellent" if pp_signal["signal_score"] >= SCORE_EXCELLENT
                    else "Good" if pp_signal["signal_score"] >= SCORE_GOOD
                    else "Moderate" if pp_signal["signal_score"] >= SCORE_MODERATE
                    else "Broken"
                ),
                "metrics": {
                    **pp_calibration["metrics"],
                    "signal_match_rate": pp_signal["signal_match_rate"],
                    "direction_agreement": pp_signal["direction_agreement"],
                },
                "component_scores": {
                    "signal_match": round(pp_signal["signal_match_rate"] * 60, 1),
                    "direction_agreement": round(pp_signal["direction_agreement"] * 40, 1),
                },
                "divergent_trades": pp_calibration.get("divergent_trades", []),
            }
            result["calibration_mode"] = "per_pair_signal"

        log.info("Best score: %.1f (mode: %s)", best_score, result["calibration_mode"])
    else:
        result["calibration_mode"] = "unlimited"

    # Step 7c: Signal-focused scoring (always computed on unlimited BT)
    signal = compute_signal_score(
        matches, live_trades_filtered, bt_trades, strat["timeframe"],
    )
    result["signal"] = signal

    # If unlimited signal score beats current best, use it
    if has_contention and signal["signal_score"] > calibration["score"]:
        calibration = {
            "score": signal["signal_score"],
            "grade": (
                "Excellent" if signal["signal_score"] >= SCORE_EXCELLENT
                else "Good" if signal["signal_score"] >= SCORE_GOOD
                else "Moderate" if signal["signal_score"] >= SCORE_MODERATE
                else "Broken"
            ),
            "metrics": {
                "trade_match_rate": signal["signal_match_rate"],
                "matched_count": signal["signal_matched_count"],
                "total_live_trades": len(live_trades_filtered),
                "signal_match_rate": signal["signal_match_rate"],
                "direction_agreement": signal["direction_agreement"],
            },
            "component_scores": {
                "signal_match": round(signal["signal_match_rate"] * 60, 1),
                "direction_agreement": round(signal["direction_agreement"] * 40, 1),
            },
            "divergent_trades": [],
        }
        result["calibration_mode"] = "unlimited_signal"
        log.info("Unlimited signal score %.1f beats per-pair — using unlimited_signal",
                 signal["signal_score"])

    result["score"] = calibration["score"]
    result["grade"] = calibration["grade"]
    result["metrics"] = calibration["metrics"]
    result["component_scores"] = calibration["component_scores"]
    result["divergent_trades"] = calibration["divergent_trades"]
    result["needs_investigation"] = calibration["score"] < SCORE_GOOD

    # Log summary
    log.info("─" * 50)
    log.info("CALIBRATION RESULT: %s", strategy_name)
    log.info("  Mode: %s", result["calibration_mode"])
    log.info("  Score: %.1f / 100 (%s)", result["score"], result["grade"])
    log.info("  Match rate: %.1f%% (%d/%d trades, %d excluded for missing data)",
             calibration["metrics"].get("trade_match_rate", 0) * 100,
             calibration["metrics"].get("matched_count", 0),
             len(live_trades_filtered),
             excluded_trades)
    log.info("  Profit correlation: %s",
             calibration["metrics"].get("profit_correlation", "N/A"))
    log.info("  P&L delta: %.2f%%",
             calibration["metrics"].get("aggregate_pnl_delta", 0) * 100)
    log.info("  Exit concordance: %.1f%%",
             calibration["metrics"].get("exit_reason_concordance", 0) * 100)
    log.info("  Signal score: %.1f (match: %.1f%%, direction: %.1f%%)",
             signal["signal_score"],
             signal["signal_match_rate"] * 100,
             signal["direction_agreement"] * 100)

    if has_contention and "per_pair" in result:
        pp = result["per_pair"]
        log.info("  Per-pair score: %.1f (%s) | signal: %.1f",
                 pp["score"], pp["grade"], pp["signal"]["signal_score"])

    if result["needs_investigation"]:
        log.warning("  ⚠ Score below 70 — INVESTIGATION REQUIRED")
        if result["divergent_trades"]:
            log.warning("  Top divergent trades:")
            for div in result["divergent_trades"][:5]:
                log.warning("    %s %s: %s", div["pair"], div["open_date"], div["reason"])

    log.info("─" * 50)

    # Step 8: Cleanup backtest result zips from this run
    _cleanup_backtest_results()

    return result


def _cleanup_backtest_results(keep_latest: int = 5) -> None:
    """
    Remove old backtest result files to prevent disk bloat.

    Keeps the N most recent zips and their meta files.
    Removes orphaned .meta.json files whose zip no longer exists.
    """
    if not BACKTEST_RESULTS.exists():
        return

    # Clean zips
    zips = sorted(BACKTEST_RESULTS.glob("backtest-result-*.zip"),
                  key=lambda p: p.stat().st_mtime, reverse=True)

    removed = 0
    kept_stems = set()

    for z in zips[:keep_latest]:
        kept_stems.add(z.stem)

    for z in zips[keep_latest:]:
        try:
            z.unlink()
            removed += 1
        except OSError:
            pass

    # Clean orphaned meta.json files (no matching zip)
    for meta in BACKTEST_RESULTS.glob("backtest-result-*.meta.json"):
        # Meta filename: backtest-result-YYYY-MM-DD_HH-MM-SS.meta.json
        # Corresponding zip stem: backtest-result-YYYY-MM-DD_HH-MM-SS
        stem = meta.name.replace(".meta.json", "")
        if stem not in kept_stems:
            try:
                meta.unlink()
                removed += 1
            except OSError:
                pass

    if removed:
        log.info("Cleaned up %d old backtest result files (kept %d latest)",
                 removed, keep_latest)


def run_all_calibrations() -> dict[str, dict]:
    """
    Run calibration for all active strategies.

    Returns dict mapping strategy name → calibration result.
    """
    results = {}
    for name in get_active_strategies():
        try:
            results[name] = run_calibration_stage(name)
        except Exception as e:
            log.error("Calibration failed for %s: %s", name, e, exc_info=True)
            results[name] = {
                "strategy": name,
                "score": 0,
                "grade": "Error",
                "error": str(e),
                "needs_investigation": True,
            }
    return results
