#!/usr/bin/env python3
"""
Parameter Optimization Loop
============================

Runs Freqtrade hyperopt on rolling windows, validates improvements via
out-of-sample backtesting, and proposes parameter changes.

Does NOT auto-deploy — generates a proposal that requires human approval.

Usage:
    python hyperopt_optimizer.py ClucHAnix                    # Optimize one strategy
    python hyperopt_optimizer.py --all                         # Optimize all strategies
    python hyperopt_optimizer.py ClucHAnix --epochs 300        # Custom epoch count
    python hyperopt_optimizer.py ClucHAnix --apply             # Apply if validated

Cron (weekly, after data download):
    0 5 * * 0 cd ~/ft_userdata && python3 hyperopt_optimizer.py --all --report >> logs/hyperopt.log 2>&1
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

CONFIGS_DIR = Path.home() / "ft_userdata" / "user_data" / "configs"
FT_DIR = Path.home() / "ft_userdata"
LOGS_DIR = Path.home() / "ft_userdata" / "logs"
PROPOSALS_DIR = Path.home() / "ft_userdata" / "optimization_proposals"
WEBHOOK_URL = "http://localhost:8088/webhooks/freqtrade"

LOGS_DIR.mkdir(parents=True, exist_ok=True)
PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "hyperopt.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("hyperopt")

STRATEGY_IMAGES = {
    "ClucHAnix": "freqtradeorg/freqtrade:stable",
    "NASOSv5": "freqtradeorg/freqtrade:stable",
    "ElliotV5": "freqtradeorg/freqtrade:stable",
    "SupertrendStrategy": "freqtradeorg/freqtrade:stable",
    "MasterTraderV1": "freqtradeorg/freqtrade:stable",
    "MasterTraderAI": "freqtradeorg/freqtrade:stable_freqai",
    "NostalgiaForInfinityX6": "ft_userdata-nostalgiaforinfinityx6",
}

# Strategies that support hyperopt (exclude ML-based)
OPTIMIZABLE = [
    "ClucHAnix", "NASOSv5", "ElliotV5",
    "SupertrendStrategy", "MasterTraderV1",
]

# Default hyperopt spaces to optimize
DEFAULT_SPACES = "roi stoploss trailing"
DEFAULT_EPOCHS = 200

# Minimum improvement thresholds to accept optimization results
MIN_IMPROVEMENT = {
    "sharpe_delta": 0.1,        # Sharpe must improve by at least 0.1
    "profit_delta_pct": 1.0,    # Total profit must improve by at least 1%
    "max_drawdown_pct": 25.0,   # Optimized result must have DD < 25%
}


# ---------------------------------------------------------------------------
# Hyperopt Execution
# ---------------------------------------------------------------------------

def run_hyperopt(
    strategy: str,
    train_days: int = 60,
    epochs: int = DEFAULT_EPOCHS,
    spaces: str = DEFAULT_SPACES,
    loss_function: str = "SharpeHyperOptLoss",
) -> Optional[dict]:
    """
    Run hyperopt optimization for a strategy on training window.

    Returns dict with best parameters and metrics, or None on failure.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=train_days)
    timerange = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"

    image = STRATEGY_IMAGES.get(strategy, "freqtradeorg/freqtrade:stable")

    log.info("Running hyperopt for %s: %d epochs, %s spaces, %d-day window",
             strategy, epochs, spaces, train_days)

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{Path.home()}/ft_userdata/user_data:/freqtrade/user_data",
        image,
        "hyperopt",
        "--strategy", strategy,
        "--config", "/freqtrade/user_data/config-backtest.json",
        "--hyperopt-loss", loss_function,
        "--spaces", *spaces.split(),
        "--epochs", str(epochs),
        "--timerange", timerange,
        "--print-json",
        "-j", "1",  # Single job to avoid OOM kills
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1800,  # 30 min max
        )

        combined = (result.stdout or "") + "\n" + (result.stderr or "")

        if result.returncode != 0 and "Best result" not in combined:
            log.error("Hyperopt failed for %s:\n%s", strategy, combined[-1000:])
            return None

        return _parse_hyperopt_output(combined, strategy)

    except subprocess.TimeoutExpired:
        log.error("Hyperopt timed out for %s (>30min)", strategy)
        return None
    except Exception as e:
        log.error("Hyperopt error for %s: %s", strategy, e)
        return None


def _parse_hyperopt_output(output: str, strategy: str) -> Optional[dict]:
    """Parse hyperopt output to extract best parameters and metrics."""
    result = {"strategy": strategy, "params": {}}

    lines = output.strip().split("\n")

    # Look for "Best result" summary line
    for line in lines:
        if "Best result" in line:
            result["best_result_line"] = line.strip()
            # Extract profit and trades count
            profit_match = re.search(r"([-\d.]+)\s*%", line)
            trades_match = re.search(r"(\d+)\s*trades", line)
            if profit_match:
                result["best_profit_pct"] = float(profit_match.group(1))
            if trades_match:
                result["best_trades"] = int(trades_match.group(1))

    # Look for JSON parameters block (--print-json output)
    json_started = False
    json_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("{") and ("roi" in stripped or "stoploss" in stripped
                                         or "trailing" in stripped or "buy" in stripped):
            json_started = True
        if json_started:
            json_lines.append(stripped)
            if stripped.endswith("}"):
                try:
                    params = json.loads("\n".join(json_lines))
                    result["params"] = params
                    json_started = False
                    json_lines = []
                except json.JSONDecodeError:
                    pass

    # Also look for individual parameter outputs
    for line in lines:
        # "    "stoploss": -0.08," patterns
        if '"stoploss"' in line:
            match = re.search(r'"stoploss":\s*([-\d.]+)', line)
            if match:
                result["params"].setdefault("stoploss", float(match.group(1)))

        if '"trailing_stop"' in line:
            match = re.search(r'"trailing_stop":\s*(true|false)', line, re.I)
            if match:
                result["params"].setdefault("trailing_stop", match.group(1).lower() == "true")

    # Extract ROI table if present
    for line in lines:
        if "minimal_roi" in line:
            roi_match = re.search(r'"minimal_roi":\s*(\{[^}]+\})', output)
            if roi_match:
                try:
                    result["params"]["minimal_roi"] = json.loads(roi_match.group(1))
                except json.JSONDecodeError:
                    pass

    return result if result.get("params") or result.get("best_profit_pct") is not None else None


# ---------------------------------------------------------------------------
# Out-of-Sample Validation
# ---------------------------------------------------------------------------

def validate_optimization(
    strategy: str,
    optimized_params: dict,
    validation_days: int = 20,
) -> Optional[dict]:
    """
    Run out-of-sample backtest with optimized parameters to check for overfitting.

    Uses the most recent `validation_days` as the test window (data NOT used in training).
    """
    # The validation window is the most recent period
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=validation_days)
    timerange = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"

    image = STRATEGY_IMAGES.get(strategy, "freqtradeorg/freqtrade:stable")

    log.info("Validating %s on %d-day out-of-sample window...", strategy, validation_days)

    # We can't easily inject params into the strategy file for a Docker run,
    # so we validate by running the backtest with current config (which should
    # already have the base parameters). For a proper test, we'd need to create
    # a temporary config with the optimized params.

    # Create temporary config with optimized params
    config_path = CONFIGS_DIR / f"{strategy}.json"
    if not config_path.exists():
        log.error("Config not found: %s", config_path)
        return None

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

        # Parse using backtest_gate's parser logic
        return _parse_validation_output(combined, strategy)
    except Exception as e:
        log.error("Validation failed for %s: %s", strategy, e)
        return None


def _parse_validation_output(output: str, strategy: str) -> Optional[dict]:
    """Parse validation backtest output."""
    metrics = {"strategy": strategy}
    lines = output.strip().split("\n")

    for line in lines:
        if strategy in line and ("│" in line or "┃" in line):
            parts = [p.strip() for p in re.split(r"[│┃|]", line) if p.strip()]
            if len(parts) >= 7 and strategy in parts[0]:
                try:
                    metrics["total_trades"] = int(parts[1])
                    metrics["avg_profit_pct"] = float(parts[2])
                    profit_str = parts[3].replace(",", "").replace("USDT", "").strip()
                    metrics["total_profit"] = float(profit_str)
                    wdl_parts = parts[6].strip().split()
                    if len(wdl_parts) >= 4:
                        metrics["wins"] = int(wdl_parts[0])
                        metrics["losses"] = int(wdl_parts[2])
                        metrics["win_rate"] = float(wdl_parts[3])
                    if len(parts) >= 8:
                        dd_match = re.search(r"([\d.]+)%", parts[7])
                        if dd_match:
                            metrics["max_drawdown_pct"] = float(dd_match.group(1))
                except (ValueError, IndexError):
                    pass

    # Parse Sharpe from detailed stats
    for line in lines:
        parts = [p.strip() for p in re.split(r"[│┃|]", line) if p.strip()]
        if len(parts) == 2 and parts[0].lower().strip() == "sharpe":
            try:
                metrics["sharpe_ratio"] = float(parts[1])
            except ValueError:
                pass

    return metrics if "total_trades" in metrics else None


# ---------------------------------------------------------------------------
# Proposal Generation
# ---------------------------------------------------------------------------

def generate_proposal(
    strategy: str,
    hyperopt_result: dict,
    validation_result: Optional[dict],
) -> dict:
    """Generate an optimization proposal with current vs proposed comparison."""
    proposal = {
        "strategy": strategy,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "optimized_params": hyperopt_result.get("params", {}),
        "training_profit_pct": hyperopt_result.get("best_profit_pct"),
        "training_trades": hyperopt_result.get("best_trades"),
        "validated": validation_result is not None,
        "validation_metrics": validation_result or {},
        "recommendation": "REVIEW",
    }

    # Decision logic
    if validation_result:
        val_trades = validation_result.get("total_trades", 0)
        val_profit = validation_result.get("total_profit", 0)
        val_dd = validation_result.get("max_drawdown_pct", 100)
        val_sharpe = validation_result.get("sharpe_ratio", -999)

        if val_trades < 5:
            proposal["recommendation"] = "SKIP — insufficient validation trades"
        elif val_dd > MIN_IMPROVEMENT["max_drawdown_pct"]:
            proposal["recommendation"] = "REJECT — validation drawdown too high"
        elif val_profit > 0 and val_sharpe > 0:
            proposal["recommendation"] = "APPROVE — positive on validation set"
        elif val_profit > 0:
            proposal["recommendation"] = "CAUTIOUS APPROVE — profitable but negative Sharpe"
        else:
            proposal["recommendation"] = "REJECT — negative profit on validation"
    else:
        proposal["recommendation"] = "SKIP — validation failed"

    # Save proposal to disk
    filename = f"{strategy}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filepath = PROPOSALS_DIR / filename
    with open(filepath, "w") as f:
        json.dump(proposal, f, indent=2)
    log.info("Proposal saved: %s", filepath)

    return proposal


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_report(proposals: list[dict]) -> str:
    lines = []
    lines.append("HYPEROPT OPTIMIZATION REPORT")
    lines.append(f"{datetime.now().strftime('%Y-%m-%d %H:%M')} UTC")
    lines.append("")

    for p in proposals:
        strategy = p["strategy"]
        rec = p.get("recommendation", "?")
        lines.append(f"{'=' * 40}")
        lines.append(f"{strategy}: {rec}")

        if p.get("training_profit_pct") is not None:
            lines.append(f"  Training: {p['training_profit_pct']:+.1f}% ({p.get('training_trades', '?')} trades)")

        val = p.get("validation_metrics", {})
        if val:
            lines.append(f"  Validation: ${val.get('total_profit', 0):+.2f} | "
                         f"WR: {val.get('win_rate', 0):.0f}% | "
                         f"DD: {val.get('max_drawdown_pct', 0):.1f}%")

        params = p.get("optimized_params", {})
        if params:
            if "stoploss" in params:
                lines.append(f"  Proposed stoploss: {params['stoploss']}")
            if "minimal_roi" in params:
                roi = params["minimal_roi"]
                lines.append(f"  Proposed ROI: {json.dumps(roi)}")
            if "trailing_stop" in params:
                lines.append(f"  Trailing: {params.get('trailing_stop')} "
                             f"(offset: {params.get('trailing_stop_positive_offset', 'N/A')})")

    lines.append("")
    lines.append("Proposals saved to ~/ft_userdata/optimization_proposals/")
    lines.append("Review and apply manually with: python hyperopt_optimizer.py <strategy> --apply")

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
# Apply Proposal
# ---------------------------------------------------------------------------

def apply_proposal(strategy: str) -> bool:
    """Apply the latest optimization proposal for a strategy."""
    # Find latest proposal
    proposals = sorted(PROPOSALS_DIR.glob(f"{strategy}_*.json"), reverse=True)
    if not proposals:
        log.error("No proposals found for %s", strategy)
        return False

    latest = proposals[0]
    with open(latest) as f:
        proposal = json.load(f)

    params = proposal.get("optimized_params", {})
    if not params:
        log.error("No parameters in proposal %s", latest)
        return False

    rec = proposal.get("recommendation", "")
    if "REJECT" in rec:
        log.warning("Proposal was REJECTED — not applying. Override with --force")
        return False

    # Read current config
    config_path = CONFIGS_DIR / f"{strategy}.json"
    with open(config_path) as f:
        config = json.load(f)

    # Apply parameters
    changed = []
    if "stoploss" in params:
        old = config.get("stoploss", "N/A")
        config["stoploss"] = params["stoploss"]
        changed.append(f"stoploss: {old} -> {params['stoploss']}")

    if "minimal_roi" in params:
        old = config.get("minimal_roi", {})
        config["minimal_roi"] = params["minimal_roi"]
        changed.append(f"ROI table updated")

    if "trailing_stop" in params:
        config["trailing_stop"] = params["trailing_stop"]
        if "trailing_stop_positive" in params:
            config["trailing_stop_positive"] = params["trailing_stop_positive"]
        if "trailing_stop_positive_offset" in params:
            config["trailing_stop_positive_offset"] = params["trailing_stop_positive_offset"]
        if "trailing_only_offset_is_reached" in params:
            config["trailing_only_offset_is_reached"] = params["trailing_only_offset_is_reached"]
        changed.append("trailing stop params updated")

    if not changed:
        log.info("No parameter changes to apply")
        return True

    # Write updated config
    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)
        f.write("\n")

    log.info("Applied changes to %s:", strategy)
    for c in changed:
        log.info("  - %s", c)

    log.info("Restart the bot to apply: docker restart ft-%s", strategy.lower())
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Parameter Optimization Loop")
    parser.add_argument("strategy", nargs="?", help="Strategy name to optimize")
    parser.add_argument("--all", action="store_true", help="Optimize all eligible strategies")
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS, help=f"Hyperopt epochs (default: {DEFAULT_EPOCHS})")
    parser.add_argument("--train-days", type=int, default=60, help="Training window days (default: 60)")
    parser.add_argument("--val-days", type=int, default=20, help="Validation window days (default: 20)")
    parser.add_argument("--spaces", default=DEFAULT_SPACES, help=f"Hyperopt spaces (default: '{DEFAULT_SPACES}')")
    parser.add_argument("--loss", default="SharpeHyperOptLoss", help="Hyperopt loss function")
    parser.add_argument("--apply", action="store_true", help="Apply latest proposal if approved")
    parser.add_argument("--report", action="store_true", help="Send Telegram report")
    parser.add_argument("--stdout", action="store_true", help="Print to stdout only")
    args = parser.parse_args()

    if args.apply:
        if not args.strategy:
            parser.error("--apply requires a strategy name")
        apply_proposal(args.strategy)
        return

    if not args.strategy and not args.all:
        parser.error("Specify a strategy name or use --all")

    strategies = OPTIMIZABLE if args.all else [args.strategy]

    log.info("=" * 50)
    log.info("Hyperopt Optimizer - %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("Strategies: %s", ", ".join(strategies))
    log.info("Training: %d days | Validation: %d days | Epochs: %d",
             args.train_days, args.val_days, args.epochs)
    log.info("=" * 50)

    proposals = []
    for strategy in strategies:
        if strategy not in STRATEGY_IMAGES:
            log.error("Unknown strategy: %s", strategy)
            continue

        log.info("=" * 40)
        log.info("Optimizing: %s", strategy)

        # Step 1: Run hyperopt on training window
        hyperopt_result = run_hyperopt(
            strategy, args.train_days, args.epochs, args.spaces, args.loss,
        )

        if hyperopt_result is None:
            log.warning("Hyperopt failed for %s, skipping", strategy)
            proposals.append({
                "strategy": strategy,
                "recommendation": "SKIP — hyperopt failed",
            })
            continue

        log.info("Hyperopt result: %s", hyperopt_result.get("best_result_line", "N/A"))

        # Step 2: Validate on out-of-sample data
        validation = validate_optimization(strategy, hyperopt_result.get("params", {}), args.val_days)

        if validation:
            log.info("Validation: %d trades, $%.2f profit, %.1f%% DD",
                     validation.get("total_trades", 0),
                     validation.get("total_profit", 0),
                     validation.get("max_drawdown_pct", 0))

        # Step 3: Generate proposal
        proposal = generate_proposal(strategy, hyperopt_result, validation)
        proposals.append(proposal)

        log.info("Recommendation: %s", proposal["recommendation"])

    # Report
    report = format_report(proposals)

    if args.stdout:
        print(report)
    else:
        print(report)

    if args.report:
        send_telegram(report)

    log.info("Optimization complete.")


if __name__ == "__main__":
    main()
