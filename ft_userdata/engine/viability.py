"""
Viability Screening — Stage 3
==============================

Kill dead strategies before wasting compute on optimization.
Runs lookahead analysis, recursive analysis, full-period backtest,
and per-pair breakdown.

Classification:
    VIABLE   — passes all checks, worth optimizing
    MARGINAL — borderline metrics or warnings, proceed with caution
    DEAD     — fails kill criteria, stop pipeline
"""

import glob
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

from .registry import FT_DIR, RESULTS_DIR, get_strategy
from .config_builder import build_backtest_config
from .parsers import (
    parse_backtest_output,
    parse_per_pair_results,
    parse_lookahead_output,
    parse_recursive_output,
    parse_trade_export_json,
)

log = logging.getLogger("engine.viability")

# Docker volume mount (host → container)
_VOLUME = f"{Path.home()}/ft_userdata/user_data:/freqtrade/user_data"

# Timeouts (seconds)
_ANALYSIS_TIMEOUT = 900   # lookahead/recursive can be slow
_BACKTEST_TIMEOUT = 600   # full-year backtest


def full_year_timerange() -> str:
    """Generate a 1-year timerange ending today (YYYYMMDD-YYYYMMDD)."""
    from datetime import datetime, timedelta
    end = datetime.utcnow()
    start = end - timedelta(days=365)
    return f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"


# ── Kill / Marginal thresholds ───────────────────────────────────────────

KILL_CRITERIA = {
    "min_trades": 1,           # 0 trades = dead
    "min_pf": 0.5,             # PF < 0.5 = dead
    "max_dd_pct": 50.0,        # DD > 50% = dead
    "min_trades_negative": 10, # <10 trades AND negative P&L = dead
    "min_sharpe": -1.0,        # Sharpe < -1.0 = actively losing risk-adjusted
    "min_win_rate": 20.0,      # WR < 20% = worse than random
}

MARGINAL_CRITERIA = {
    "pf_low": 0.5,
    "pf_high": 0.8,
    "dd_low": 35.0,
    "dd_high": 50.0,
    "trades_low": 10,
    "trades_high": 30,
    "sharpe_low": -1.0,
    "sharpe_high": 0.5,
    "wr_low": 20.0,
    "wr_high": 40.0,
}


# ── Docker helpers ───────────────────────────────────────────────────────

def _run_docker(image: str, args: list[str], timeout: int = _BACKTEST_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a Freqtrade command inside Docker."""
    cmd = [
        "docker", "run", "--rm",
        "-v", _VOLUME,
        image,
    ] + args

    log.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    if result.returncode != 0:
        log.warning("Docker command exited %d. stderr: %s",
                    result.returncode, result.stderr[-500:] if result.stderr else "(empty)")

    return result


def _export_dir(strategy_name: str) -> str:
    """Container-internal path for trade export results."""
    return f"/freqtrade/user_data/backtest_results/viability-{strategy_name}"


def _host_export_dir(strategy_name: str) -> Path:
    """Host path for trade export results."""
    return FT_DIR / "user_data" / "backtest_results" / f"viability-{strategy_name}"


# ── Stage 3a: Lookahead Analysis ─────────────────────────────────────────

def run_lookahead_analysis(
    strategy_name: str,
    timerange: str,
    config_path: str,
) -> dict:
    """
    Run Freqtrade lookahead-analysis to detect future data usage.

    Args:
        strategy_name: Strategy class name
        timerange: Freqtrade timerange string (e.g. "20250401-20260401")
        config_path: Container-internal config path

    Returns:
        dict with: passed (bool), flagged_indicators (list), raw (str)
    """
    strat = get_strategy(strategy_name)
    image = strat["image"]

    args = [
        "lookahead-analysis",
        "--strategy", strategy_name,
        "--config", config_path,
        "--timerange", timerange,
    ]

    try:
        result = _run_docker(image, args, timeout=_ANALYSIS_TIMEOUT)
        combined = (result.stdout or "") + "\n" + (result.stderr or "")
        parsed = parse_lookahead_output(combined)
        log.info("Lookahead analysis for %s: passed=%s, flagged=%s",
                 strategy_name, parsed["passed"], parsed["flagged_indicators"])
        return parsed

    except subprocess.TimeoutExpired:
        log.error("Lookahead analysis timed out for %s", strategy_name)
        return {
            "passed": False,
            "flagged_indicators": ["TIMEOUT — analysis did not complete"],
            "raw": "Timed out after %ds" % _ANALYSIS_TIMEOUT,
        }
    except Exception as e:
        log.error("Lookahead analysis failed for %s: %s", strategy_name, e)
        return {
            "passed": False,
            "flagged_indicators": [f"ERROR: {e}"],
            "raw": str(e),
        }


# ── Stage 3b: Recursive Analysis ────────────────────────────────────────

def run_recursive_analysis(
    strategy_name: str,
    timerange: str,
    config_path: str,
) -> dict:
    """
    Run Freqtrade recursive-analysis to detect dataset-length dependency.

    Args:
        strategy_name: Strategy class name
        timerange: Freqtrade timerange string
        config_path: Container-internal config path

    Returns:
        dict with: warning (bool), flagged_indicators (list), raw (str)
    """
    strat = get_strategy(strategy_name)
    image = strat["image"]

    args = [
        "recursive-analysis",
        "--strategy", strategy_name,
        "--config", config_path,
        "--timerange", timerange,
    ]

    try:
        result = _run_docker(image, args, timeout=_ANALYSIS_TIMEOUT)
        combined = (result.stdout or "") + "\n" + (result.stderr or "")
        parsed = parse_recursive_output(combined)
        log.info("Recursive analysis for %s: warning=%s, flagged=%s",
                 strategy_name, parsed["warning"], parsed["flagged_indicators"])
        return parsed

    except subprocess.TimeoutExpired:
        log.error("Recursive analysis timed out for %s", strategy_name)
        return {
            "warning": True,
            "flagged_indicators": ["TIMEOUT — analysis did not complete"],
            "raw": "Timed out after %ds" % _ANALYSIS_TIMEOUT,
        }
    except Exception as e:
        log.error("Recursive analysis failed for %s: %s", strategy_name, e)
        return {
            "warning": True,
            "flagged_indicators": [f"ERROR: {e}"],
            "raw": str(e),
        }


# ── Stage 3c: Full-Period Backtest ───────────────────────────────────────

def _viability_strategy_name(strategy_name: str) -> str:
    """
    Use viability wrapper if it exists, otherwise base strategy.

    Viability wrappers apply runtime filters (dynamic pairlist, F&G)
    that the base strategy checks in confirm_trade_entry at runtime.
    """
    from pathlib import Path
    wrapper = f"{strategy_name}Viability"
    wrapper_file = FT_DIR / "user_data" / "strategies" / f"{wrapper}.py"
    if wrapper_file.exists():
        log.info("Using viability wrapper: %s", wrapper)
        return wrapper
    return strategy_name


def run_full_backtest(
    strategy_name: str,
    timerange: str,
    config_path: str,
) -> dict:
    """
    Run full-year backtest and parse metrics.

    Args:
        strategy_name: Strategy class name
        timerange: Freqtrade timerange string
        config_path: Container-internal config path

    Returns:
        Parsed metrics dict (trades, PF, WR, DD, Sharpe, Sortino, Calmar, etc.)
        or empty dict with error key on failure.
    """
    import time as _time
    strat = get_strategy(strategy_name)
    image = strat["image"]

    # Use viability wrapper if available (applies runtime filters)
    bt_strategy = _viability_strategy_name(strategy_name)

    start_ts = _time.time()

    args = [
        "backtesting",
        "--strategy", bt_strategy,
        "--config", config_path,
        "--timerange", timerange,
        "--export", "trades",
    ]

    try:
        result = _run_docker(image, args, timeout=_BACKTEST_TIMEOUT)
        combined = (result.stdout or "") + "\n" + (result.stderr or "")

        # Try both wrapper name and base name for parsing
        metrics = parse_backtest_output(combined, bt_strategy)
        if metrics is None:
            metrics = parse_backtest_output(combined, strategy_name)
        if metrics is None:
            log.warning("Could not parse backtest output for %s", strategy_name)
            return {"error": "unparseable output", "raw": combined[-1000:]}

        # Find the result file created after we started (for pair analysis later)
        bt_dir = FT_DIR / "user_data" / "backtest_results"
        result_files = sorted(
            [f for f in bt_dir.glob("backtest-result-*.zip")
             if f.stat().st_mtime >= start_ts],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if result_files:
            metrics["_result_file"] = str(result_files[0])

        log.info("Backtest %s: %d trades, PF=%.2f, DD=%.1f%%",
                 strategy_name,
                 metrics.get("total_trades", 0),
                 metrics.get("profit_factor", 0),
                 metrics.get("max_drawdown_pct", 0))
        return metrics

    except subprocess.TimeoutExpired:
        log.error("Backtest timed out for %s", strategy_name)
        return {"error": "timeout", "raw": "Timed out after %ds" % _BACKTEST_TIMEOUT}
    except Exception as e:
        log.error("Backtest failed for %s: %s", strategy_name, e)
        return {"error": str(e)}


# ── Stage 3d: Per-Pair Analysis ──────────────────────────────────────────

def analyze_pairs(
    strategy_name: str,
    timerange: str,
    config_path: str,
    backtest_metrics: dict = None,
) -> dict:
    """
    Analyze per-pair performance from backtest trade export.

    Expects run_full_backtest to have already run (uses its trade export).
    Falls back to re-running backtest if export not found.

    Returns:
        dict with: pairs (list), top_5 (list), bottom_5 (list),
        concentration_risk (bool), concentration_details (str),
        total_pairs_traded (int)
    """
    result = {
        "pairs": [],
        "top_5": [],
        "bottom_5": [],
        "concentration_risk": False,
        "concentration_details": "",
        "total_pairs_traded": 0,
    }

    # Find the exported trades from the most recent backtest result
    # The result file path is stashed in backtest_metrics by run_full_backtest
    result_file = backtest_metrics.get("_result_file") if backtest_metrics else None

    if not result_file:
        # Fallback: find most recent result zip
        bt_dir = FT_DIR / "user_data" / "backtest_results"
        zips = sorted(bt_dir.glob("backtest-result-*.zip"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        if zips:
            result_file = str(zips[0])

    if not result_file:
        log.warning("No backtest result file found for %s pair analysis", strategy_name)
        result["error"] = "no backtest result file found"
        return result

    # Extract trades from zip
    import zipfile
    trades = []
    try:
        with zipfile.ZipFile(result_file) as zf:
            for name in zf.namelist():
                if name.endswith(".json") and not name.endswith("_config.json"):
                    import json as _json
                    data = _json.loads(zf.read(name))
                    if isinstance(data, dict) and "strategy" in data:
                        for sname, sdata in data["strategy"].items():
                            if sname == strategy_name:
                                trades = sdata.get("trades", [])
                                break
                    break
    except Exception as e:
        log.error("Failed to read trades from %s: %s", result_file, e)
        result["error"] = str(e)
        return result
    if not trades:
        log.warning("No trades parsed from export for %s", strategy_name)
        result["error"] = "no trades in export"
        return result

    # Group by pair
    pair_stats: dict[str, dict] = {}
    for trade in trades:
        pair = trade.get("pair", "UNKNOWN")
        if pair not in pair_stats:
            pair_stats[pair] = {
                "pair": pair,
                "trades": 0,
                "total_profit": 0.0,
                "wins": 0,
                "losses": 0,
            }
        ps = pair_stats[pair]
        ps["trades"] += 1
        profit = trade.get("profit_abs", 0.0) or trade.get("profit_amount", 0.0) or 0.0
        ps["total_profit"] += profit
        if profit > 0:
            ps["wins"] += 1
        elif profit < 0:
            ps["losses"] += 1

    # Compute win rates
    for ps in pair_stats.values():
        ps["win_rate"] = round(ps["wins"] / ps["trades"] * 100, 1) if ps["trades"] > 0 else 0.0

    pairs_list = sorted(pair_stats.values(), key=lambda x: x["total_profit"], reverse=True)
    result["pairs"] = pairs_list
    result["total_pairs_traded"] = len(pairs_list)

    # Top 5 / Bottom 5
    result["top_5"] = pairs_list[:5]
    result["bottom_5"] = pairs_list[-5:] if len(pairs_list) > 5 else pairs_list

    # Concentration risk: >50% profit from top 1-2 pairs
    total_profit = sum(p["total_profit"] for p in pairs_list if p["total_profit"] > 0)
    if total_profit > 0 and len(pairs_list) >= 3:
        top_2_profit = sum(p["total_profit"] for p in pairs_list[:2] if p["total_profit"] > 0)
        concentration_pct = (top_2_profit / total_profit) * 100
        if concentration_pct > 50:
            result["concentration_risk"] = True
            top_names = [p["pair"] for p in pairs_list[:2]]
            result["concentration_details"] = (
                f"{concentration_pct:.0f}% of profit from top 2 pairs: "
                f"{', '.join(top_names)}"
            )
            log.warning("Concentration risk for %s: %s",
                        strategy_name, result["concentration_details"])

    return result


# ── Classification ───────────────────────────────────────────────────────

def classify_viability(
    metrics: dict,
    lookahead: dict,
    recursive: dict,
    pair_analysis: dict,
) -> tuple[str, list[str]]:
    """
    Classify strategy viability based on all sub-results.

    Args:
        metrics: Parsed backtest metrics
        lookahead: Lookahead analysis result
        recursive: Recursive analysis result
        pair_analysis: Per-pair analysis result

    Returns:
        Tuple of (classification, reasons) where classification is
        "VIABLE", "MARGINAL", or "DEAD".
    """
    reasons: list[str] = []

    # ── DEAD checks (any one = kill) ─────────────────────────────────

    # Lookahead bias = immediate kill
    if not lookahead.get("passed", True):
        reasons.append(
            f"KILL: Lookahead bias detected — indicators: "
            f"{', '.join(lookahead.get('flagged_indicators', ['unknown']))}"
        )
        return "DEAD", reasons

    # Backtest error = can't evaluate
    if "error" in metrics:
        reasons.append(f"KILL: Backtest failed — {metrics['error']}")
        return "DEAD", reasons

    total_trades = metrics.get("total_trades", 0)
    pf = metrics.get("profit_factor", 0.0)
    dd = metrics.get("max_drawdown_pct", 0.0)
    total_profit = metrics.get("total_profit", 0.0)
    sharpe = metrics.get("sharpe")
    win_rate = metrics.get("win_rate", 0.0)

    # Zero trades
    if total_trades == 0:
        reasons.append("KILL: Zero trades in full-year backtest")
        return "DEAD", reasons

    # PF too low
    if pf < KILL_CRITERIA["min_pf"]:
        reasons.append(f"KILL: Profit factor {pf:.2f} < {KILL_CRITERIA['min_pf']}")
        return "DEAD", reasons

    # Drawdown too high
    if dd > KILL_CRITERIA["max_dd_pct"]:
        reasons.append(f"KILL: Max drawdown {dd:.1f}% > {KILL_CRITERIA['max_dd_pct']}%")
        return "DEAD", reasons

    # Sharpe too low
    if sharpe is not None and sharpe < KILL_CRITERIA["min_sharpe"]:
        reasons.append(f"KILL: Sharpe ratio {sharpe:.2f} < {KILL_CRITERIA['min_sharpe']}")
        return "DEAD", reasons

    # Win rate too low (with sufficient trades)
    if total_trades >= 10 and win_rate < KILL_CRITERIA["min_win_rate"]:
        reasons.append(f"KILL: Win rate {win_rate:.1f}% < {KILL_CRITERIA['min_win_rate']}%")
        return "DEAD", reasons

    # Few trades + negative P&L
    if total_trades < KILL_CRITERIA["min_trades_negative"] and total_profit < 0:
        reasons.append(
            f"KILL: Only {total_trades} trades with negative P&L (${total_profit:.2f})"
        )
        return "DEAD", reasons

    # ── MARGINAL checks ──────────────────────────────────────────────

    is_marginal = False

    # PF in marginal range
    if MARGINAL_CRITERIA["pf_low"] <= pf < MARGINAL_CRITERIA["pf_high"]:
        reasons.append(f"MARGINAL: Profit factor {pf:.2f} in warning range "
                       f"({MARGINAL_CRITERIA['pf_low']}-{MARGINAL_CRITERIA['pf_high']})")
        is_marginal = True

    # DD in marginal range
    if MARGINAL_CRITERIA["dd_low"] <= dd < MARGINAL_CRITERIA["dd_high"]:
        reasons.append(f"MARGINAL: Max drawdown {dd:.1f}% in warning range "
                       f"({MARGINAL_CRITERIA['dd_low']}-{MARGINAL_CRITERIA['dd_high']}%)")
        is_marginal = True

    # Low trade count with marginal P&L
    if (MARGINAL_CRITERIA["trades_low"] <= total_trades < MARGINAL_CRITERIA["trades_high"]
            and total_profit <= 0):
        reasons.append(
            f"MARGINAL: Only {total_trades} trades with non-positive P&L (${total_profit:.2f})"
        )
        is_marginal = True

    # Recursive analysis warning
    if recursive.get("warning", False):
        flagged = recursive.get("flagged_indicators", [])
        reasons.append(
            f"MARGINAL: Recursive analysis warning — indicators may depend on dataset length"
            + (f": {', '.join(flagged)}" if flagged else "")
        )
        is_marginal = True

    # Sharpe in marginal range
    if sharpe is not None and MARGINAL_CRITERIA["sharpe_low"] <= sharpe < MARGINAL_CRITERIA["sharpe_high"]:
        reasons.append(f"MARGINAL: Sharpe ratio {sharpe:.2f} in warning range "
                       f"({MARGINAL_CRITERIA['sharpe_low']}-{MARGINAL_CRITERIA['sharpe_high']})")
        is_marginal = True

    # Win rate in marginal range (with sufficient trades)
    if total_trades >= 10 and MARGINAL_CRITERIA["wr_low"] <= win_rate < MARGINAL_CRITERIA["wr_high"]:
        reasons.append(f"MARGINAL: Win rate {win_rate:.1f}% in warning range "
                       f"({MARGINAL_CRITERIA['wr_low']}-{MARGINAL_CRITERIA['wr_high']}%)")
        is_marginal = True

    # Concentration risk (warning, not kill)
    if pair_analysis.get("concentration_risk", False):
        reasons.append(
            f"MARGINAL: Pair concentration risk — {pair_analysis['concentration_details']}"
        )
        is_marginal = True

    if is_marginal:
        return "MARGINAL", reasons

    # ── VIABLE ───────────────────────────────────────────────────────

    reasons.append(
        f"VIABLE: {total_trades} trades, PF {pf:.2f}, "
        f"DD {dd:.1f}%, P&L ${total_profit:.2f}"
    )
    return "VIABLE", reasons


# ── Main Entry Point ─────────────────────────────────────────────────────

def run_viability_stage(
    strategy_name: str,
    pairs: list[str],
    timerange: str,
) -> dict:
    """
    Main entry point for Stage 3: Viability Screening.

    Runs all sub-analyses and returns a comprehensive result.

    Args:
        strategy_name: Strategy class name
        pairs: Pair whitelist for backtesting
        timerange: Freqtrade timerange string (e.g. "20250401-20260401")

    Returns:
        dict with:
            strategy: strategy name
            classification: VIABLE / MARGINAL / DEAD
            reasons: list of classification reasons
            lookahead: lookahead analysis result
            recursive: recursive analysis result
            metrics: backtest metrics
            pair_analysis: per-pair breakdown
    """
    log.info("=" * 60)
    log.info("Stage 3: Viability Screening — %s", strategy_name)
    log.info("Pairs: %d, Timerange: %s", len(pairs), timerange)
    log.info("=" * 60)

    # Ensure results directory exists
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Build config
    config_path = build_backtest_config(strategy_name, pairs)
    log.info("Config: %s", config_path)

    # 3a: Lookahead analysis
    log.info("--- 3a: Lookahead Analysis ---")
    lookahead = run_lookahead_analysis(strategy_name, timerange, config_path)

    # Early exit: lookahead bias = dead, skip everything else
    if not lookahead.get("passed", True):
        classification = "DEAD"
        reasons = [
            f"KILL: Lookahead bias detected — "
            f"{', '.join(lookahead.get('flagged_indicators', ['unknown']))}"
        ]
        result = {
            "strategy": strategy_name,
            "classification": classification,
            "reasons": reasons,
            "lookahead": lookahead,
            "recursive": {"warning": False, "flagged_indicators": [], "skipped": True},
            "metrics": {"skipped": True},
            "pair_analysis": {"skipped": True},
        }
        _save_result(strategy_name, result)
        log.info("RESULT: %s — %s", classification, "; ".join(reasons))
        return result

    # 3b: Recursive analysis
    log.info("--- 3b: Recursive Analysis ---")
    recursive = run_recursive_analysis(strategy_name, timerange, config_path)

    # 3c: Full-period backtest
    log.info("--- 3c: Full-Period Backtest ---")
    metrics = run_full_backtest(strategy_name, timerange, config_path)

    # 3d: Per-pair analysis (uses trade export from 3c)
    log.info("--- 3d: Per-Pair Analysis ---")
    pair_analysis = analyze_pairs(strategy_name, timerange, config_path, backtest_metrics=metrics)

    # Classify
    classification, reasons = classify_viability(metrics, lookahead, recursive, pair_analysis)

    result = {
        "strategy": strategy_name,
        "classification": classification,
        "reasons": reasons,
        "lookahead": lookahead,
        "recursive": recursive,
        "metrics": metrics,
        "pair_analysis": pair_analysis,
    }

    _save_result(strategy_name, result)

    log.info("RESULT: %s — %s", classification, "; ".join(reasons))
    return result


def _save_result(strategy_name: str, result: dict) -> None:
    """Save viability result to disk for later stages."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"viability-{strategy_name}.json"

    # Strip raw output to keep file size reasonable
    sanitized = _strip_raw_fields(result)

    try:
        with open(out_path, "w") as f:
            json.dump(sanitized, f, indent=2, default=str)
        log.info("Saved viability result: %s", out_path)
    except Exception as e:
        log.error("Failed to save viability result: %s", e)


def _strip_raw_fields(obj: dict, max_raw_len: int = 500) -> dict:
    """Recursively truncate 'raw' fields to keep JSON output manageable."""
    result = {}
    for k, v in obj.items():
        if k == "raw" and isinstance(v, str) and len(v) > max_raw_len:
            result[k] = v[:max_raw_len] + "... (truncated)"
        elif isinstance(v, dict):
            result[k] = _strip_raw_fields(v, max_raw_len)
        else:
            result[k] = v
    return result
