#!/usr/bin/env python3
"""
Walk-Forward Validation System
===============================

The gold standard for preventing overfitting in trading strategies.

How it works:
1. Split historical data into rolling windows: train on months 1-3, test on month 4
2. Optimize parameters on training window (via hyperopt)
3. Validate on the test window (out-of-sample backtest)
4. Slide the window forward and repeat
5. Aggregate all out-of-sample results for true strategy assessment

If a strategy is profitable across ALL out-of-sample windows, it's robust.
If it only works in-sample, it's overfitted.

Usage:
    python walk_forward.py SupertrendStrategy              # Walk-forward one strategy
    python walk_forward.py --all                            # All eligible strategies
    python walk_forward.py SupertrendStrategy --windows 4   # Custom number of windows
    python walk_forward.py SupertrendStrategy --train 60 --test 20  # Custom window sizes

Cron (monthly):
    0 6 1 * * cd ~/ft_userdata && python3 walk_forward.py --all --report >> logs/walk_forward.log 2>&1
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

FT_DIR = Path.home() / "ft_userdata"
LOGS_DIR = FT_DIR / "logs"
RESULTS_DIR = FT_DIR / "walk_forward_results"
WEBHOOK_URL = "http://localhost:8088/webhooks/freqtrade"

LOGS_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "walk_forward.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("walk-forward")

STRATEGY_IMAGES = {
    "ClucHAnix": "freqtradeorg/freqtrade:stable",
    "NASOSv5": "freqtradeorg/freqtrade:stable",
    "ElliotV5": "freqtradeorg/freqtrade:stable",
    "SupertrendStrategy": "freqtradeorg/freqtrade:stable",
    "MasterTraderV1": "freqtradeorg/freqtrade:stable",
}

# Walk-forward defaults
DEFAULT_TRAIN_DAYS = 60   # 2 months training
DEFAULT_TEST_DAYS = 20    # ~3 weeks testing
DEFAULT_WINDOWS = 3       # 3 rolling windows
DEFAULT_EPOCHS = 150      # Hyperopt epochs per window


# ---------------------------------------------------------------------------
# Window Generation
# ---------------------------------------------------------------------------

def generate_windows(
    total_days: int = None,
    train_days: int = DEFAULT_TRAIN_DAYS,
    test_days: int = DEFAULT_TEST_DAYS,
    num_windows: int = DEFAULT_WINDOWS,
) -> list[dict]:
    """
    Generate rolling train/test windows ending at today.

    Returns list of {train_start, train_end, test_start, test_end} datetime pairs.
    Window N is the most recent.
    """
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    windows = []

    for i in range(num_windows):
        # Work backwards from today
        test_end = end - timedelta(days=i * test_days)
        test_start = test_end - timedelta(days=test_days)
        train_end = test_start
        train_start = train_end - timedelta(days=train_days)

        windows.append({
            "window": num_windows - i,
            "train_start": train_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
            "train_range": f"{train_start.strftime('%Y%m%d')}-{train_end.strftime('%Y%m%d')}",
            "test_range": f"{test_start.strftime('%Y%m%d')}-{test_end.strftime('%Y%m%d')}",
        })

    windows.reverse()  # Chronological order
    return windows


# ---------------------------------------------------------------------------
# Hyperopt on Training Window
# ---------------------------------------------------------------------------

def run_hyperopt_window(
    strategy: str,
    timerange: str,
    epochs: int = DEFAULT_EPOCHS,
) -> Optional[dict]:
    """Run hyperopt on a specific time window."""
    image = STRATEGY_IMAGES.get(strategy, "freqtradeorg/freqtrade:stable")

    log.info("  Hyperopt %s on %s (%d epochs)...", strategy, timerange, epochs)

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{FT_DIR}/user_data:/freqtrade/user_data",
        image,
        "hyperopt",
        "--strategy", strategy,
        "--config", "/freqtrade/user_data/config-backtest.json",
        "--hyperopt-loss", "SharpeHyperOptLoss",
        "--spaces", "roi", "stoploss", "trailing",
        "--epochs", str(epochs),
        "--timerange", timerange,
        "--print-json",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        combined = (result.stdout or "") + "\n" + (result.stderr or "")

        if "Best result" not in combined and result.returncode != 0:
            log.warning("  Hyperopt failed on %s", timerange)
            return None

        # Parse best result
        best = {}
        for line in combined.split("\n"):
            if "Best result" in line:
                profit_match = re.search(r"([-\d.]+)\s*%", line)
                trades_match = re.search(r"(\d+)\s*trades", line)
                if profit_match:
                    best["profit_pct"] = float(profit_match.group(1))
                if trades_match:
                    best["trades"] = int(trades_match.group(1))

            # Look for JSON params
            if line.strip().startswith("{") and "stoploss" in line:
                try:
                    best["params"] = json.loads(line.strip())
                except json.JSONDecodeError:
                    pass

        return best if best else None

    except subprocess.TimeoutExpired:
        log.warning("  Hyperopt timed out on %s", timerange)
        return None
    except Exception as e:
        log.error("  Hyperopt error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Backtest on Test Window
# ---------------------------------------------------------------------------

def run_backtest_window(strategy: str, timerange: str) -> Optional[dict]:
    """Run backtest on a specific test window."""
    image = STRATEGY_IMAGES.get(strategy, "freqtradeorg/freqtrade:stable")

    log.info("  Backtest %s on %s...", strategy, timerange)

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{FT_DIR}/user_data:/freqtrade/user_data",
        image,
        "backtesting",
        "--strategy", strategy,
        "--config", "/freqtrade/user_data/config-backtest.json",
        "--timerange", timerange,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        combined = (result.stdout or "") + "\n" + (result.stderr or "")

        # Parse results
        metrics = {"strategy": strategy, "timerange": timerange}

        for line in combined.split("\n"):
            if strategy in line and ("│" in line or "┃" in line):
                parts = [p.strip() for p in re.split(r"[│┃|]", line) if p.strip()]
                if len(parts) >= 7 and strategy in parts[0]:
                    try:
                        metrics["trades"] = int(parts[1])
                        metrics["avg_profit_pct"] = float(parts[2])
                        profit_str = parts[3].replace(",", "").replace("USDT", "").strip()
                        metrics["total_profit"] = float(profit_str)
                        wdl = parts[6].strip().split()
                        if len(wdl) >= 4:
                            metrics["wins"] = int(wdl[0])
                            metrics["losses"] = int(wdl[2])
                            metrics["win_rate"] = float(wdl[3])
                        if len(parts) >= 8:
                            dd_match = re.search(r"([\d.]+)%", parts[7])
                            if dd_match:
                                metrics["drawdown_pct"] = float(dd_match.group(1))
                    except (ValueError, IndexError):
                        pass

            # Sharpe
            parts = [p.strip() for p in re.split(r"[│┃|]", line) if p.strip()]
            if len(parts) == 2 and parts[0].lower().strip() == "sharpe":
                try:
                    metrics["sharpe"] = float(parts[1])
                except ValueError:
                    pass

        return metrics if "trades" in metrics else None

    except Exception as e:
        log.error("  Backtest error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Walk-Forward Execution
# ---------------------------------------------------------------------------

def run_walk_forward(
    strategy: str,
    train_days: int = DEFAULT_TRAIN_DAYS,
    test_days: int = DEFAULT_TEST_DAYS,
    num_windows: int = DEFAULT_WINDOWS,
    epochs: int = DEFAULT_EPOCHS,
) -> dict:
    """
    Execute full walk-forward validation for a strategy.

    Returns aggregated results across all windows.
    """
    windows = generate_windows(
        train_days=train_days,
        test_days=test_days,
        num_windows=num_windows,
    )

    log.info("Walk-forward validation for %s", strategy)
    log.info("  %d windows: %d-day train / %d-day test", num_windows, train_days, test_days)

    results = {
        "strategy": strategy,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "train_days": train_days,
            "test_days": test_days,
            "num_windows": num_windows,
            "epochs": epochs,
        },
        "windows": [],
        "summary": {},
    }

    total_oos_profit = 0.0
    total_oos_trades = 0
    total_oos_wins = 0
    total_oos_losses = 0
    profitable_windows = 0

    for w in windows:
        log.info("")
        log.info("--- Window %d ---", w["window"])
        log.info("  Train: %s | Test: %s", w["train_range"], w["test_range"])

        window_result = {
            "window": w["window"],
            "train_range": w["train_range"],
            "test_range": w["test_range"],
        }

        # Step 1: Optimize on training window
        hyperopt = run_hyperopt_window(strategy, w["train_range"], epochs)
        if hyperopt:
            window_result["train_profit_pct"] = hyperopt.get("profit_pct")
            window_result["train_trades"] = hyperopt.get("trades")
            window_result["optimized_params"] = hyperopt.get("params", {})
            log.info("  Train result: %.1f%% (%d trades)",
                     hyperopt.get("profit_pct", 0), hyperopt.get("trades", 0))
        else:
            window_result["train_profit_pct"] = None
            window_result["train_trades"] = 0
            log.warning("  Training failed")

        # Step 2: Test on out-of-sample window (using current strategy params)
        # Note: We test with CURRENT params, not optimized ones — this shows
        # if the base strategy is robust. To test optimized params, we'd need
        # to inject them into the config (future enhancement).
        backtest = run_backtest_window(strategy, w["test_range"])
        if backtest:
            window_result["test_trades"] = backtest.get("trades", 0)
            window_result["test_profit"] = backtest.get("total_profit", 0)
            window_result["test_win_rate"] = backtest.get("win_rate", 0)
            window_result["test_drawdown"] = backtest.get("drawdown_pct", 0)
            window_result["test_sharpe"] = backtest.get("sharpe", 0)

            total_oos_profit += backtest.get("total_profit", 0)
            total_oos_trades += backtest.get("trades", 0)
            total_oos_wins += backtest.get("wins", 0)
            total_oos_losses += backtest.get("losses", 0)
            if backtest.get("total_profit", 0) > 0:
                profitable_windows += 1

            log.info("  Test result: $%.2f (%.0f%% WR, %.1f%% DD)",
                     backtest.get("total_profit", 0),
                     backtest.get("win_rate", 0),
                     backtest.get("drawdown_pct", 0))
        else:
            window_result["test_trades"] = 0
            window_result["test_profit"] = 0
            log.warning("  Test failed")

        results["windows"].append(window_result)

    # Aggregate summary
    oos_win_rate = (total_oos_wins / (total_oos_wins + total_oos_losses) * 100
                    if (total_oos_wins + total_oos_losses) > 0 else 0)

    results["summary"] = {
        "total_oos_profit": round(total_oos_profit, 2),
        "total_oos_trades": total_oos_trades,
        "oos_win_rate": round(oos_win_rate, 1),
        "profitable_windows": profitable_windows,
        "total_windows": num_windows,
        "robustness_pct": round(profitable_windows / num_windows * 100, 0) if num_windows > 0 else 0,
        "verdict": _compute_verdict(profitable_windows, num_windows, total_oos_profit),
    }

    # Save results
    filename = f"{strategy}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filepath = RESULTS_DIR / filename
    with open(filepath, "w") as f:
        json.dump(results, f, indent=2, default=str)
    log.info("Results saved: %s", filepath)

    return results


def _compute_verdict(profitable_windows: int, total_windows: int, total_profit: float) -> str:
    """Determine walk-forward verdict."""
    if total_windows == 0:
        return "INSUFFICIENT DATA"

    robustness = profitable_windows / total_windows

    if robustness >= 0.75 and total_profit > 0:
        return "ROBUST — strategy is validated"
    elif robustness >= 0.5 and total_profit > 0:
        return "MARGINAL — strategy works but not consistently"
    elif total_profit > 0:
        return "WEAK — profitable overall but inconsistent across windows"
    else:
        return "FAILED — strategy is not profitable out-of-sample"


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_report(all_results: list[dict]) -> str:
    lines = []
    lines.append("WALK-FORWARD VALIDATION REPORT")
    lines.append(f"{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC")
    lines.append("")

    for r in all_results:
        strategy = r["strategy"]
        summary = r.get("summary", {})

        lines.append(f"{'=' * 40}")
        lines.append(f"{strategy}: {summary.get('verdict', '?')}")
        lines.append(f"  OOS Profit: ${summary.get('total_oos_profit', 0):+.2f}")
        lines.append(f"  OOS Trades: {summary.get('total_oos_trades', 0)}")
        lines.append(f"  OOS Win Rate: {summary.get('oos_win_rate', 0):.0f}%")
        lines.append(f"  Profitable Windows: {summary.get('profitable_windows', 0)}/{summary.get('total_windows', 0)}")
        lines.append(f"  Robustness: {summary.get('robustness_pct', 0):.0f}%")
        lines.append("")

        for w in r.get("windows", []):
            train_p = w.get("train_profit_pct")
            test_p = w.get("test_profit", 0)
            train_str = f"{train_p:+.1f}%" if train_p is not None else "N/A"
            lines.append(f"  W{w['window']}: Train {train_str} | "
                         f"Test ${test_p:+.2f} (WR:{w.get('test_win_rate', 0):.0f}%) | "
                         f"DD:{w.get('test_drawdown', 0):.1f}%")

    lines.append("")
    lines.append("Results saved to ~/ft_userdata/walk_forward_results/")

    return "\n".join(lines)


def send_telegram(message: str) -> bool:
    import requests
    try:
        payload = {"type": "status", "status": message}
        resp = requests.post(WEBHOOK_URL, data=payload, timeout=10)
        return resp.status_code in (200, 201, 204)
    except Exception as e:
        log.error("Failed to send report: %s", e)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Walk-Forward Validation System")
    parser.add_argument("strategy", nargs="?", help="Strategy name")
    parser.add_argument("--all", action="store_true", help="Validate all eligible strategies")
    parser.add_argument("--train", type=int, default=DEFAULT_TRAIN_DAYS, help=f"Training window days (default: {DEFAULT_TRAIN_DAYS})")
    parser.add_argument("--test", type=int, default=DEFAULT_TEST_DAYS, help=f"Test window days (default: {DEFAULT_TEST_DAYS})")
    parser.add_argument("--windows", type=int, default=DEFAULT_WINDOWS, help=f"Number of windows (default: {DEFAULT_WINDOWS})")
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS, help=f"Hyperopt epochs per window (default: {DEFAULT_EPOCHS})")
    parser.add_argument("--report", action="store_true", help="Send Telegram report")
    parser.add_argument("--stdout", action="store_true", help="Print to stdout only")
    args = parser.parse_args()

    if not args.strategy and not args.all:
        parser.error("Specify a strategy name or use --all")

    strategies = list(STRATEGY_IMAGES.keys()) if args.all else [args.strategy]

    log.info("=" * 50)
    log.info("Walk-Forward Validation - %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("Strategies: %s", ", ".join(strategies))
    log.info("Config: %d-day train / %d-day test / %d windows / %d epochs",
             args.train, args.test, args.windows, args.epochs)
    log.info("=" * 50)

    all_results = []
    for strategy in strategies:
        if strategy not in STRATEGY_IMAGES:
            log.error("Unknown strategy: %s", strategy)
            continue

        result = run_walk_forward(
            strategy, args.train, args.test, args.windows, args.epochs,
        )
        all_results.append(result)

        verdict = result.get("summary", {}).get("verdict", "?")
        log.info("")
        log.info("VERDICT for %s: %s", strategy, verdict)

    report = format_report(all_results)

    if args.stdout:
        print(report)
    else:
        print(report)

    if args.report:
        send_telegram(report)

    log.info("Walk-forward validation complete.")


if __name__ == "__main__":
    main()
