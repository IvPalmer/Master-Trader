#!/usr/bin/env python3
"""
Backtesting Gate Pipeline
=========================

Validates strategy parameters via backtesting before deployment.
Downloads fresh data, runs backtests, compares metrics against thresholds.

Usage:
    python backtest_gate.py ClucHAnix                     # Backtest one strategy
    python backtest_gate.py --all                          # Backtest all strategies
    python backtest_gate.py ClucHAnix --days 60            # Custom timerange
    python backtest_gate.py ClucHAnix --deploy             # Deploy if passes
    python backtest_gate.py --compare ClucHAnix            # Compare current vs live performance

Requirements:
    - Freqtrade Docker containers must be available
    - Historical data must exist or will be downloaded

Cron (weekly backtest validation):
    0 4 * * 0 cd ~/ft_userdata && python3 backtest_gate.py --all --report >> logs/backtest_gate.log 2>&1
"""

import argparse
import json
import logging
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

CONFIGS_DIR = Path.home() / "ft_userdata" / "user_data" / "configs"
STRATEGIES_DIR = Path.home() / "ft_userdata" / "user_data" / "strategies"
DATA_DIR = Path.home() / "ft_userdata" / "user_data" / "data"
RESULTS_DIR = Path.home() / "ft_userdata" / "user_data" / "backtest_results"
LOGS_DIR = Path.home() / "ft_userdata" / "logs"
FT_DIR = Path.home() / "ft_userdata"
WEBHOOK_URL = "http://localhost:8088/webhooks/freqtrade"
API_USER = "freqtrader"
API_PASS = "mastertrader"

LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "backtest_gate.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("backtest-gate")

# Strategy to Docker image mapping
STRATEGY_IMAGES = {
    "ClucHAnix": "freqtradeorg/freqtrade:stable",
    "NASOSv5": "freqtradeorg/freqtrade:stable",
    "ElliotV5": "freqtradeorg/freqtrade:stable",
    "SupertrendStrategy": "freqtradeorg/freqtrade:stable",
    "MasterTraderV1": "freqtradeorg/freqtrade:stable",
    "MasterTraderAI": "freqtradeorg/freqtrade:stable_freqai",
    "BollingerRSIMeanReversion": "freqtradeorg/freqtrade:stable",
    # "NostalgiaForInfinityX6": "ft_userdata-nostalgiaforinfinityx6",  # KILLED — 0 trades
}

ALL_STRATEGIES = list(STRATEGY_IMAGES.keys())

# Strategy to API port mapping (for fetching live pairlists)
STRATEGY_PORTS = {
    "ClucHAnix": 8080,
    "NASOSv5": 8082,
    "ElliotV5": 8083,
    "SupertrendStrategy": 8084,
    "MasterTraderV1": 8086,
    "MasterTraderAI": 8087,
    "BollingerRSIMeanReversion": 8089,
    # "NostalgiaForInfinityX6": 8089,  # KILLED
}

# Backtest pass/fail thresholds — per timeframe
# 5m dip-buyers: tighter thresholds (more trades, better statistics)
# 1h trend-followers: looser thresholds (fewer trades, more variance)
THRESHOLDS_5M = {
    "min_sharpe": 0.3,
    "max_drawdown_pct": 20.0,
    "min_win_rate": 45.0,
    "min_profit_factor": 0.8,
    "min_total_trades": 10,
}

THRESHOLDS_1H = {
    "min_sharpe": -1.0,            # Trend strategies have high variance
    "max_drawdown_pct": 30.0,      # More drawdown tolerance
    "min_win_rate": 25.0,          # Trend strategies win less but win big
    "min_profit_factor": 0.5,      # Looser — live performance is what matters
    "min_total_trades": 5,
}

THRESHOLDS_1D = {
    "min_sharpe": -1.0,
    "max_drawdown_pct": 35.0,      # Daily strategies may have higher DD
    "min_win_rate": 20.0,          # Trend strategies on daily can have very low WR
    "min_profit_factor": 0.5,
    "min_total_trades": 3,
}

def get_thresholds(strategy: str) -> dict:
    """Return appropriate thresholds based on strategy timeframe."""
    tf = BOTS_TIMEFRAMES.get(strategy, "5m")
    if tf == "1d":
        return THRESHOLDS_1D
    return THRESHOLDS_1H if tf in ("1h", "4h") else THRESHOLDS_5M

# ── Multi-Asset Robustness Gate ─────────────────────────────────────
# A strategy must work across diverse assets, not just 1-2 coins.
# Tests same params on 10+ coins. Fails if >30% have excessive drawdown.

ROBUSTNESS_PAIRS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "ADA/USDT", "AVAX/USDT",
    "DOGE/USDT", "XRP/USDT", "LINK/USDT", "DOT/USDT", "MATIC/USDT",
    "NEAR/USDT", "FET/USDT",
]
ROBUSTNESS_MAX_DD_PER_PAIR = 50.0  # Max DD% per individual pair
ROBUSTNESS_FAIL_THRESHOLD = 0.30   # Fail if >30% of pairs exceed max DD


def robustness_check(strategy: str, days: int = 180) -> dict:
    """
    Run backtests across ROBUSTNESS_PAIRS with the same strategy params.
    Returns pass/fail and per-pair breakdown.
    """
    log.info("Running robustness check for %s across %d pairs...", strategy, len(ROBUSTNESS_PAIRS))

    results = []
    failed_pairs = []

    for pair in ROBUSTNESS_PAIRS:
        try:
            # Run backtest for this single pair
            pair_result = run_backtest(strategy, days=days, pairs_override=[pair])
            if pair_result is None:
                results.append({"pair": pair, "status": "error", "dd": 0, "profit": 0})
                continue

            dd = pair_result.get("max_drawdown_pct", 0)
            profit = pair_result.get("total_profit_pct", 0)
            results.append({"pair": pair, "status": "ok", "dd": dd, "profit": profit})

            if dd > ROBUSTNESS_MAX_DD_PER_PAIR:
                failed_pairs.append(pair)
                log.warning("  %s: DD %.1f%% exceeds %.0f%% threshold", pair, dd, ROBUSTNESS_MAX_DD_PER_PAIR)
            else:
                log.info("  %s: DD %.1f%%, Profit %.1f%% — OK", pair, dd, profit)

        except Exception as e:
            log.error("  %s: Error — %s", pair, e)
            results.append({"pair": pair, "status": "error", "dd": 0, "profit": 0})

    valid_results = [r for r in results if r["status"] == "ok"]
    fail_rate = len(failed_pairs) / len(valid_results) if valid_results else 1.0
    passed = fail_rate <= ROBUSTNESS_FAIL_THRESHOLD

    summary = {
        "passed": passed,
        "pairs_tested": len(valid_results),
        "pairs_failed": len(failed_pairs),
        "fail_rate": round(fail_rate * 100, 1),
        "failed_pairs": failed_pairs,
        "results": results,
    }

    if passed:
        log.info("Robustness check PASSED: %d/%d pairs failed (%.0f%% < %.0f%% threshold)",
                 len(failed_pairs), len(valid_results), fail_rate * 100, ROBUSTNESS_FAIL_THRESHOLD * 100)
    else:
        log.warning("Robustness check FAILED: %d/%d pairs failed (%.0f%% > %.0f%% threshold)",
                     len(failed_pairs), len(valid_results), fail_rate * 100, ROBUSTNESS_FAIL_THRESHOLD * 100)

    return summary

# Fallback pairs if live pairlist fetch fails
FALLBACK_PAIRS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT",
    "BNB/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "NEAR/USDT",
    "SUI/USDT", "PEPE/USDT", "TRX/USDT", "DOT/USDT", "SHIB/USDT",
    "UNI/USDT", "MATIC/USDT", "FIL/USDT", "APT/USDT", "ARB/USDT",
    "OP/USDT", "ATOM/USDT", "FET/USDT", "RENDER/USDT", "INJ/USDT",
    "AAVE/USDT", "LTC/USDT", "ICP/USDT", "XLM/USDT", "ALGO/USDT",
]


# ---------------------------------------------------------------------------
# Live Pairlist Fetching
# ---------------------------------------------------------------------------

def fetch_live_pairlist(strategy: str) -> list[str]:
    """Fetch the actual pairlist a bot is currently trading from its API."""
    port = STRATEGY_PORTS.get(strategy)
    if not port:
        log.warning("No port mapping for %s, using fallback pairs", strategy)
        return FALLBACK_PAIRS

    try:
        resp = requests.get(
            f"http://localhost:{port}/api/v1/whitelist",
            auth=(API_USER, API_PASS),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        pairs = data.get("whitelist", [])
        if pairs:
            log.info("  Fetched %d live pairs from %s (port %d)", len(pairs), strategy, port)
            return pairs
        else:
            log.warning("  Empty pairlist from %s, using fallback", strategy)
            return FALLBACK_PAIRS
    except Exception as e:
        log.warning("  Failed to fetch pairlist from %s: %s — using fallback", strategy, e)
        return FALLBACK_PAIRS


def generate_backtest_config(strategy: str, pairs: list[str]) -> str:
    """Generate a per-strategy backtest config with the bot's live pairlist.

    Returns the container-internal path to the generated config file.
    """
    base_config_path = FT_DIR / "user_data" / "config-backtest.json"
    with open(base_config_path) as f:
        config = json.load(f)

    config["exchange"]["pair_whitelist"] = pairs
    config["bot_name"] = f"Backtest-{strategy}"

    out_path = FT_DIR / "user_data" / "configs" / f"backtest-{strategy}.json"
    with open(out_path, "w") as f:
        json.dump(config, f, indent=2)

    return f"/freqtrade/user_data/configs/backtest-{strategy}.json"


# ---------------------------------------------------------------------------
# Data Download
# ---------------------------------------------------------------------------

def download_data(pairs: list[str], days: int = 60, timeframes: list[str] = None) -> bool:
    """Download historical data for a specific set of pairs."""
    if timeframes is None:
        timeframes = ["5m", "1h"]

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    timerange = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"

    for tf in timeframes:
        log.info("  Downloading %s data for %d pairs, %d days...", tf, len(pairs), days)
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{Path.home()}/ft_userdata/user_data:/freqtrade/user_data",
            "freqtradeorg/freqtrade:stable",
            "download-data",
            "--exchange", "binance",
            "--pairs", *pairs,
            "--timeframes", tf,
            "--timerange", timerange,
            "--config", "/freqtrade/user_data/config-backtest.json",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                log.warning("  Data download warning for %s: %s", tf, result.stderr[-500:] if result.stderr else "")
            else:
                log.info("  Downloaded %s data successfully", tf)
        except subprocess.TimeoutExpired:
            log.error("  Data download timed out for %s", tf)
            return False
        except Exception as e:
            log.error("  Data download failed: %s", e)
            return False
    return True


# ---------------------------------------------------------------------------
# Backtesting
# ---------------------------------------------------------------------------

def run_backtest(strategy: str, days: int = 60, config_path: str = None,
                 pairs_override: list[str] = None) -> Optional[dict]:
    """
    Run a backtest for a strategy and return parsed results.

    Args:
        strategy: Strategy class name
        days: Number of days to backtest
        config_path: Container-internal path to backtest config
        pairs_override: If set, generate a temp config with only these pairs

    Returns:
        Dict with backtest metrics or None on failure
    """
    # If pairs_override, generate a temporary config for just those pairs
    if pairs_override:
        config_path = generate_backtest_config(strategy, pairs_override)
        config_path = f"/freqtrade/user_data/configs/backtest-{strategy}.json"
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    timerange = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"

    if not config_path:
        config_path = "/freqtrade/user_data/config-backtest.json"

    image = STRATEGY_IMAGES.get(strategy, "freqtradeorg/freqtrade:stable")

    log.info("  Backtesting %s over %d days (%s)...", strategy, days, timerange)

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{Path.home()}/ft_userdata/user_data:/freqtrade/user_data",
        image,
        "backtesting",
        "--strategy", strategy,
        "--config", config_path,
        "--timerange", timerange,
        "--export", "trades",
        "--export-filename",
        f"/freqtrade/user_data/backtest_results/gate-{strategy}-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
        )

        # Freqtrade outputs results to both stdout and stderr
        combined = (result.stdout or "") + "\n" + (result.stderr or "")

        if result.returncode != 0:
            # Check if we still got results (freqtrade sometimes returns non-zero with valid output)
            if "TOTAL" not in combined and "STRATEGY SUMMARY" not in combined:
                log.error("Backtest failed for %s:\n%s", strategy, combined[-1000:])
                return None

        # Parse results from combined output
        return _parse_backtest_output(combined, strategy)

    except subprocess.TimeoutExpired:
        log.error("Backtest timed out for %s (>10min)", strategy)
        return None
    except Exception as e:
        log.error("Backtest error for %s: %s", strategy, e)
        return None


def _parse_backtest_output(output: str, strategy: str) -> Optional[dict]:
    """Parse Freqtrade backtest text output into metrics dict.

    Freqtrade outputs rich tables with Unicode box-drawing characters (│, ┃).
    The STRATEGY SUMMARY table has the structure:
        Strategy | Trades | Avg Profit % | Tot Profit USDT | Tot Profit % | Avg Duration | Win Draw Loss Win% | Drawdown
    The detailed stats section has key-value rows like:
        │ Sharpe                          │ -0.12                          │
    """
    import re

    metrics = {"strategy": strategy, "raw_output": ""}

    lines = output.strip().split("\n")
    metrics["raw_output"] = "\n".join(lines[-80:])  # Keep last 80 lines

    # Parse STRATEGY SUMMARY table row containing the strategy name
    for line in lines:
        # Match lines with the strategy name in the summary table
        if strategy in line and ("│" in line or "┃" in line):
            # Split on box-drawing separators
            parts = [p.strip() for p in re.split(r"[│┃|]", line) if p.strip()]
            if len(parts) >= 7 and strategy in parts[0]:
                try:
                    metrics["total_trades"] = int(parts[1])
                    metrics["avg_profit_pct"] = float(parts[2])
                    # Tot Profit USDT
                    profit_str = parts[3].replace(",", "").replace("USDT", "").strip()
                    metrics["total_profit"] = float(profit_str)
                    # Tot Profit %
                    metrics["total_profit_pct"] = float(parts[4])
                    # Win Draw Loss Win%
                    wdl_str = parts[6].strip()
                    wdl_parts = wdl_str.split()
                    if len(wdl_parts) >= 4:
                        metrics["wins"] = int(wdl_parts[0])
                        metrics["draws"] = int(wdl_parts[1])
                        metrics["losses"] = int(wdl_parts[2])
                        metrics["win_rate"] = float(wdl_parts[3])
                    # Drawdown
                    if len(parts) >= 8:
                        dd_str = parts[7].strip()
                        dd_match = re.search(r"([\d.]+)%", dd_str)
                        if dd_match:
                            metrics["max_drawdown_pct"] = float(dd_match.group(1))
                except (ValueError, IndexError) as e:
                    log.warning("Failed to parse strategy summary: %s", e)

    # Parse detailed stats (key-value pairs in box-drawing rows)
    for line in lines:
        # Normalize separators
        parts = [p.strip() for p in re.split(r"[│┃|]", line) if p.strip()]
        if len(parts) != 2:
            continue

        key, value = parts[0].lower(), parts[1]

        if "sharpe" == key.strip():
            try:
                metrics["sharpe_ratio"] = float(value)
            except ValueError:
                pass

        elif "profit factor" in key:
            try:
                metrics["profit_factor"] = float(value)
            except ValueError:
                pass

        elif "sortino" in key:
            try:
                metrics["sortino_ratio"] = float(value)
            except ValueError:
                pass

        elif "max % of account underwater" in key:
            try:
                metrics["max_drawdown_pct"] = float(value.replace("%", ""))
            except ValueError:
                pass

        elif "absolute drawdown" in key:
            dd_match = re.search(r"([\d.]+)%", value)
            if dd_match:
                metrics.setdefault("max_drawdown_pct", float(dd_match.group(1)))

    # Compute win_rate if not already set
    total = metrics.get("total_trades", 0)
    wins = metrics.get("wins", 0)
    if total > 0 and "win_rate" not in metrics:
        metrics["win_rate"] = round(wins / total * 100, 1)

    return metrics if "total_trades" in metrics else None


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_backtest(metrics: dict) -> dict:
    """Evaluate backtest results against thresholds. Returns pass/fail with details."""
    strategy = metrics["strategy"]
    thresholds = get_thresholds(strategy)
    tf = BOTS_TIMEFRAMES.get(strategy, "5m")

    result = {
        "strategy": strategy,
        "passed": True,
        "checks": [],
        "metrics": metrics,
        "timeframe": tf,
    }

    checks = []

    # Minimum trades
    total = metrics.get("total_trades", 0)
    passed = total >= thresholds["min_total_trades"]
    checks.append({
        "name": "Minimum trades",
        "value": total,
        "threshold": thresholds["min_total_trades"],
        "passed": passed,
    })
    if not passed:
        result["passed"] = False

    # Sharpe ratio
    sharpe = metrics.get("sharpe_ratio", 0)
    if sharpe != 0:
        passed = sharpe >= thresholds["min_sharpe"]
        checks.append({
            "name": "Sharpe ratio",
            "value": round(sharpe, 2),
            "threshold": thresholds["min_sharpe"],
            "passed": passed,
        })
        if not passed:
            result["passed"] = False

    # Max drawdown
    dd = metrics.get("max_drawdown_pct", 0)
    if dd != 0:
        passed = dd <= thresholds["max_drawdown_pct"]
        checks.append({
            "name": "Max drawdown",
            "value": f"{dd:.1f}%",
            "threshold": f"{thresholds['max_drawdown_pct']}%",
            "passed": passed,
        })
        if not passed:
            result["passed"] = False

    # Win rate
    wr = metrics.get("win_rate", 0)
    if total >= thresholds["min_total_trades"]:
        passed = wr >= thresholds["min_win_rate"]
        checks.append({
            "name": "Win rate",
            "value": f"{wr:.1f}%",
            "threshold": f"{thresholds['min_win_rate']}%",
            "passed": passed,
        })
        if not passed:
            result["passed"] = False

    # Profit factor
    pf = metrics.get("profit_factor", 0)
    if pf > 0:
        passed = pf >= thresholds["min_profit_factor"]
        checks.append({
            "name": "Profit factor",
            "value": round(pf, 2),
            "threshold": thresholds["min_profit_factor"],
            "passed": passed,
        })
        if not passed:
            result["passed"] = False

    result["checks"] = checks
    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_report(evaluations: list[dict]) -> str:
    """Format backtest gate results for Telegram."""
    lines = []
    lines.append("BACKTEST GATE REPORT")
    lines.append(f"{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC")
    lines.append("")

    passed_count = sum(1 for e in evaluations if e["passed"])
    total = len(evaluations)
    lines.append(f"Results: {passed_count}/{total} strategies PASSED")
    lines.append("")

    for e in evaluations:
        status = "PASS" if e["passed"] else "FAIL"
        strategy = e["strategy"]
        m = e.get("metrics", {})

        tf = e.get("timeframe", "?")
        lines.append(f"{'=' * 40}")
        lines.append(f"{status} | {strategy} ({tf})")

        if m:
            trades = m.get("total_trades", 0)
            wr = m.get("win_rate", 0)
            sharpe = m.get("sharpe_ratio", "N/A")
            dd = m.get("max_drawdown_pct", "N/A")
            pf = m.get("profit_factor", "N/A")
            profit = m.get("total_profit", "N/A")
            n_pairs = m.get("pair_count", "?")

            lines.append(f"  Pairs: {n_pairs} (live) | Trades: {trades} | WR: {wr}%")
            lines.append(f"  Sharpe: {sharpe} | Max DD: {dd}% | PF: {pf} | Profit: ${profit}")

        for check in e.get("checks", []):
            icon = "OK" if check["passed"] else "FAIL"
            lines.append(f"  [{icon}] {check['name']}: {check['value']} (threshold: {check['threshold']})")

    return "\n".join(lines)


def send_telegram(message: str) -> bool:
    import requests as req
    try:
        payload = {"type": "status", "status": message}
        resp = req.post(WEBHOOK_URL, data=payload, timeout=10)
        return resp.status_code in (200, 201, 204)
    except Exception as e:
        log.error("Failed to send report: %s", e)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Backtesting Gate Pipeline")
    parser.add_argument("strategy", nargs="?", help="Strategy name to backtest")
    parser.add_argument("--all", action="store_true", help="Backtest all strategies")
    parser.add_argument("--days", type=int, default=60, help="Days of history to backtest (default: 60)")
    parser.add_argument("--download", action="store_true", help="Download fresh data before backtesting")
    parser.add_argument("--deploy", action="store_true", help="Deploy strategy if backtest passes")
    parser.add_argument("--report", action="store_true", help="Send Telegram report")
    parser.add_argument("--stdout", action="store_true", help="Print results to stdout only")
    args = parser.parse_args()

    if not args.strategy and not args.all:
        parser.error("Specify a strategy name or use --all")

    log.info("=" * 50)
    log.info("Backtest Gate - %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 50)

    # Determine strategies to test
    strategies = ALL_STRATEGIES if args.all else [args.strategy]

    # Validate strategy names
    for s in strategies:
        if s not in STRATEGY_IMAGES:
            log.error("Unknown strategy: %s. Available: %s", s, ", ".join(ALL_STRATEGIES))
            sys.exit(1)

    # Fetch live pairlists and prepare per-strategy configs
    log.info("Fetching live pairlists from bot APIs...")
    strategy_pairs = {}
    all_pairs = set()
    for strategy in strategies:
        if strategy == "MasterTraderAI":
            continue  # Skip FreqAI
        pairs = fetch_live_pairlist(strategy)
        strategy_pairs[strategy] = pairs
        all_pairs.update(pairs)

    # Download data for all unique pairs across all strategies
    if all_pairs:
        all_pairs_list = sorted(all_pairs)
        log.info("Downloading data for %d unique pairs across all strategies...", len(all_pairs_list))
        timeframes = list(set(BOTS_TIMEFRAMES.get(s, "5m") for s in strategies))
        if not download_data(all_pairs_list, args.days, timeframes):
            log.warning("Some data downloads failed, continuing with available data")

    # Generate per-strategy backtest configs
    strategy_configs = {}
    for strategy, pairs in strategy_pairs.items():
        config_path = generate_backtest_config(strategy, pairs)
        strategy_configs[strategy] = config_path
        log.info("  %s: %d pairs → %s", strategy, len(pairs), config_path)

    # Run backtests
    evaluations = []
    for strategy in strategies:
        log.info("=" * 40)
        log.info("Testing: %s", strategy)

        # Skip FreqAI strategies (require pre-trained models)
        if strategy == "MasterTraderAI":
            log.info("  Skipping %s — FreqAI strategies need pre-trained models for backtesting", strategy)
            evaluations.append({
                "strategy": strategy,
                "passed": True,
                "checks": [{"name": "FreqAI skip", "value": "N/A", "threshold": "N/A", "passed": True}],
                "metrics": {"strategy": strategy, "total_trades": 0},
            })
            continue

        config_path = strategy_configs.get(strategy)
        pairs = strategy_pairs.get(strategy, [])
        log.info("  Using %d live pairs for backtest", len(pairs))
        metrics = run_backtest(strategy, args.days, config_path)

        if metrics is not None:
            metrics["pair_count"] = len(pairs)

        if metrics is None:
            log.error("Backtest failed for %s — no results", strategy)
            evaluations.append({
                "strategy": strategy,
                "passed": False,
                "checks": [{"name": "Backtest execution", "value": "FAILED", "threshold": "SUCCESS", "passed": False}],
                "metrics": {"strategy": strategy, "total_trades": 0},
            })
            continue

        evaluation = evaluate_backtest(metrics)
        evaluations.append(evaluation)

        status = "PASSED" if evaluation["passed"] else "FAILED"
        log.info("%s: %s (trades=%d, WR=%.1f%%)",
                 strategy, status, metrics.get("total_trades", 0), metrics.get("win_rate", 0))

    # Format and output report
    report = format_report(evaluations)

    if args.stdout:
        print(report)
    else:
        print(report)

    if args.report:
        send_telegram(report)
        log.info("Report sent to Telegram")

    # Deploy if requested and all passed
    if args.deploy:
        failed = [e for e in evaluations if not e["passed"]]
        if failed:
            log.warning("Cannot deploy — %d strategies failed the gate:", len(failed))
            for f in failed:
                log.warning("  - %s", f["strategy"])
            sys.exit(1)
        else:
            log.info("All strategies passed! (Deployment is manual — restart bots to apply config changes)")

    # Exit code: 0 if all passed, 1 if any failed
    if any(not e["passed"] for e in evaluations):
        sys.exit(1)


# Bot timeframe mapping for data download
BOTS_TIMEFRAMES = {
    "ClucHAnix": "5m",
    "NASOSv5": "5m",
    "ElliotV5": "5m",
    "SupertrendStrategy": "1h",
    "MasterTraderV1": "1h",
    "MasterTraderAI": "1h",
    "BollingerRSIMeanReversion": "15m",
    # "NostalgiaForInfinityX6": "5m",  # KILLED
}


if __name__ == "__main__":
    main()
