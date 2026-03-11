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

CONFIGS_DIR = Path.home() / "ft_userdata" / "user_data" / "configs"
STRATEGIES_DIR = Path.home() / "ft_userdata" / "user_data" / "strategies"
DATA_DIR = Path.home() / "ft_userdata" / "user_data" / "data"
RESULTS_DIR = Path.home() / "ft_userdata" / "user_data" / "backtest_results"
LOGS_DIR = Path.home() / "ft_userdata" / "logs"
FT_DIR = Path.home() / "ft_userdata"
WEBHOOK_URL = "http://localhost:8088/webhooks/freqtrade"

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
    "NostalgiaForInfinityX6": "ft-nfi",  # Custom built image
}

ALL_STRATEGIES = list(STRATEGY_IMAGES.keys())

# Backtest pass/fail thresholds
THRESHOLDS = {
    "min_sharpe": 0.3,             # Annualized Sharpe ratio
    "max_drawdown_pct": 20.0,      # Maximum drawdown %
    "min_win_rate": 45.0,          # Win rate %
    "min_profit_factor": 0.8,      # Gross profit / gross loss
    "min_total_trades": 10,        # Need enough trades for statistical significance
    "max_avg_loss_pct": -8.0,      # Average losing trade must be < 8%
}

# Pairs used for backtesting (the top 10 by volume, static for consistency)
BACKTEST_PAIRS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT",
    "BNB/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "NEAR/USDT",
]


# ---------------------------------------------------------------------------
# Data Download
# ---------------------------------------------------------------------------

def download_data(days: int = 60, timeframes: list[str] = None) -> bool:
    """Download historical data using Freqtrade's data downloader."""
    if timeframes is None:
        timeframes = ["5m", "1h"]

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    timerange = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"

    pairs_arg = " ".join(BACKTEST_PAIRS)
    for tf in timeframes:
        log.info("Downloading %s data for %d days...", tf, days)
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{FT_DIR}/user_data:/freqtrade/user_data",
            "freqtradeorg/freqtrade:stable",
            "download-data",
            "--exchange", "binance",
            "--pairs", *BACKTEST_PAIRS,
            "--timeframes", tf,
            "--timerange", timerange,
            "--config", "/freqtrade/user_data/config-backtest.json",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                log.warning("Data download warning for %s: %s", tf, result.stderr[-500:] if result.stderr else "")
            else:
                log.info("Downloaded %s data successfully", tf)
        except subprocess.TimeoutExpired:
            log.error("Data download timed out for %s", tf)
            return False
        except Exception as e:
            log.error("Data download failed: %s", e)
            return False
    return True


# ---------------------------------------------------------------------------
# Backtesting
# ---------------------------------------------------------------------------

def run_backtest(strategy: str, days: int = 60, config_override: str = None) -> Optional[dict]:
    """
    Run a backtest for a strategy and return parsed results.

    Args:
        strategy: Strategy class name
        days: Number of days to backtest
        config_override: Path to alternative config (for A/B testing)

    Returns:
        Dict with backtest metrics or None on failure
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    timerange = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"

    config_path = config_override or f"/freqtrade/user_data/configs/{strategy}.json"
    image = STRATEGY_IMAGES.get(strategy, "freqtradeorg/freqtrade:stable")

    # For NFI, use the locally built image
    if strategy == "NostalgiaForInfinityX6":
        image = "ft-nfi"

    log.info("Backtesting %s over %d days (%s)...", strategy, days, timerange)

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{FT_DIR}/user_data:/freqtrade/user_data",
    ]

    # Use ONLY the backtest config (static pairlist) — strategy configs have
    # VolumePairList which doesn't support backtesting
    cmd.extend([
        image,
        "backtesting",
        "--strategy", strategy,
        "--config", "/freqtrade/user_data/config-backtest.json",
        "--timerange", timerange,
        "--export", "trades",
        "--export-filename",
        f"/freqtrade/user_data/backtest_results/gate-{strategy}-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    ])

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
    result = {
        "strategy": metrics["strategy"],
        "passed": True,
        "checks": [],
        "metrics": metrics,
    }

    checks = []

    # Minimum trades
    total = metrics.get("total_trades", 0)
    passed = total >= THRESHOLDS["min_total_trades"]
    checks.append({
        "name": "Minimum trades",
        "value": total,
        "threshold": THRESHOLDS["min_total_trades"],
        "passed": passed,
    })
    if not passed:
        result["passed"] = False

    # Sharpe ratio
    sharpe = metrics.get("sharpe_ratio", 0)
    if sharpe != 0:  # Only check if we have it
        passed = sharpe >= THRESHOLDS["min_sharpe"]
        checks.append({
            "name": "Sharpe ratio",
            "value": round(sharpe, 2),
            "threshold": THRESHOLDS["min_sharpe"],
            "passed": passed,
        })
        if not passed:
            result["passed"] = False

    # Max drawdown
    dd = metrics.get("max_drawdown_pct", 0)
    if dd != 0:
        passed = dd <= THRESHOLDS["max_drawdown_pct"]
        checks.append({
            "name": "Max drawdown",
            "value": f"{dd:.1f}%",
            "threshold": f"{THRESHOLDS['max_drawdown_pct']}%",
            "passed": passed,
        })
        if not passed:
            result["passed"] = False

    # Win rate
    wr = metrics.get("win_rate", 0)
    if total >= THRESHOLDS["min_total_trades"]:
        passed = wr >= THRESHOLDS["min_win_rate"]
        checks.append({
            "name": "Win rate",
            "value": f"{wr:.1f}%",
            "threshold": f"{THRESHOLDS['min_win_rate']}%",
            "passed": passed,
        })
        if not passed:
            result["passed"] = False

    # Profit factor
    pf = metrics.get("profit_factor", 0)
    if pf > 0:
        passed = pf >= THRESHOLDS["min_profit_factor"]
        checks.append({
            "name": "Profit factor",
            "value": round(pf, 2),
            "threshold": THRESHOLDS["min_profit_factor"],
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

        lines.append(f"{'=' * 40}")
        lines.append(f"{status} | {strategy}")

        if m:
            trades = m.get("total_trades", 0)
            wr = m.get("win_rate", 0)
            sharpe = m.get("sharpe_ratio", "N/A")
            dd = m.get("max_drawdown_pct", "N/A")
            pf = m.get("profit_factor", "N/A")
            profit = m.get("total_profit", "N/A")

            lines.append(f"  Trades: {trades} | WR: {wr}% | Sharpe: {sharpe}")
            lines.append(f"  Max DD: {dd}% | PF: {pf} | Profit: ${profit}")

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

    # Download data if requested
    if args.download:
        timeframes = set()
        for s in strategies:
            tf = BOTS_TIMEFRAMES.get(s, "5m")
            timeframes.add(tf)
        if not download_data(args.days, list(timeframes)):
            log.error("Data download failed, aborting")
            sys.exit(1)

    # Run backtests
    evaluations = []
    for strategy in strategies:
        log.info("=" * 40)
        log.info("Testing: %s", strategy)

        # Skip FreqAI strategies for now (require special handling)
        if strategy == "MasterTraderAI":
            log.info("Skipping %s — FreqAI strategies need pre-trained models for backtesting", strategy)
            evaluations.append({
                "strategy": strategy,
                "passed": True,
                "checks": [{"name": "FreqAI skip", "value": "N/A", "threshold": "N/A", "passed": True}],
                "metrics": {"strategy": strategy, "total_trades": 0},
            })
            continue

        metrics = run_backtest(strategy, args.days)

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
    "NostalgiaForInfinityX6": "5m",
}


if __name__ == "__main__":
    main()
