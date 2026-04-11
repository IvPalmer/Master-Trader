"""
Freqtrade Output Parsers — Shared
==================================

Parsing logic for backtest, hyperopt, lookahead-analysis, and recursive-analysis
output from Freqtrade Docker runs. Used by multiple pipeline stages.
"""

import json
import re
import logging
from typing import Optional

log = logging.getLogger("engine.parsers")


def parse_backtest_output(output: str, strategy: str) -> Optional[dict]:
    """
    Parse Freqtrade backtest text output into metrics dict.

    Handles both stdout and stderr combined output. Parses:
    - STRATEGY SUMMARY table (trades, profit, WR, DD)
    - Detailed stats (Sharpe, Sortino, Calmar, PF)
    - Per-pair breakdown if present

    Returns dict with metrics or None if unparseable.
    """
    metrics = {"strategy": strategy}
    lines = output.strip().split("\n")

    # Parse STRATEGY SUMMARY table row
    for line in lines:
        if strategy in line and ("│" in line or "┃" in line):
            parts = [p.strip() for p in re.split(r"[│┃|]", line) if p.strip()]
            if len(parts) >= 7 and strategy in parts[0]:
                try:
                    metrics["total_trades"] = int(parts[1])
                    metrics["avg_profit_pct"] = float(parts[2])
                    profit_str = parts[3].replace(",", "").replace("USDT", "").strip()
                    metrics["total_profit"] = float(profit_str)
                    metrics["total_profit_pct"] = float(parts[4])
                    wdl_parts = parts[6].strip().split()
                    if len(wdl_parts) >= 4:
                        metrics["wins"] = int(wdl_parts[0])
                        metrics["draws"] = int(wdl_parts[1])
                        metrics["losses"] = int(wdl_parts[2])
                        metrics["win_rate"] = float(wdl_parts[3])
                    if len(parts) >= 8:
                        dd_match = re.search(r"([\d.]+)%", parts[7])
                        if dd_match:
                            metrics["max_drawdown_pct"] = float(dd_match.group(1))
                except (ValueError, IndexError) as e:
                    log.warning("Failed to parse strategy summary: %s", e)

    # Parse detailed stats (key-value pairs in box-drawing rows)
    for line in lines:
        parts = [p.strip() for p in re.split(r"[│┃|]", line) if p.strip()]
        if len(parts) != 2:
            continue

        key, value = parts[0].lower().strip(), parts[1].strip()

        try:
            if key == "sharpe":
                metrics["sharpe"] = float(value)
            elif key == "sortino":
                metrics["sortino"] = float(value)
            elif key == "calmar":
                metrics["calmar"] = float(value)
            elif "profit factor" in key:
                metrics["profit_factor"] = float(value)
            elif "max % of account underwater" in key:
                metrics["max_drawdown_pct"] = float(value.replace("%", ""))
            elif "absolute drawdown" in key:
                dd_match = re.search(r"([\d.]+)%", value)
                if dd_match:
                    metrics.setdefault("max_drawdown_pct", float(dd_match.group(1)))
            elif "avg. stake amount" in key:
                metrics["avg_stake"] = float(value.replace("USDT", "").strip())
            elif "total trade volume" in key:
                metrics["total_volume"] = float(value.replace("USDT", "").replace(",", "").strip())
        except ValueError:
            pass

    # Compute win_rate if not already set
    total = metrics.get("total_trades", 0)
    wins = metrics.get("wins", 0)
    if total > 0 and "win_rate" not in metrics:
        metrics["win_rate"] = round(wins / total * 100, 1)

    return metrics if "total_trades" in metrics else None


def parse_per_pair_results(output: str) -> list[dict]:
    """
    Parse per-pair breakdown from backtest output.

    Returns list of dicts with: pair, trades, avg_profit, total_profit, win_rate, avg_duration.
    """
    pairs = []
    lines = output.strip().split("\n")

    in_pair_table = False
    for line in lines:
        # Detect pair table start (has TOTAL row at the end)
        if "/USDT" in line and ("│" in line or "┃" in line):
            parts = [p.strip() for p in re.split(r"[│┃|]", line) if p.strip()]
            if len(parts) >= 7 and "/USDT" in parts[0]:
                try:
                    pair_data = {
                        "pair": parts[0],
                        "trades": int(parts[1]),
                        "avg_profit_pct": float(parts[2]),
                        "total_profit": float(parts[3].replace(",", "").replace("USDT", "").strip()),
                    }
                    wdl_parts = parts[6].strip().split()
                    if len(wdl_parts) >= 4:
                        pair_data["wins"] = int(wdl_parts[0])
                        pair_data["losses"] = int(wdl_parts[2])
                        pair_data["win_rate"] = float(wdl_parts[3])
                    pairs.append(pair_data)
                except (ValueError, IndexError):
                    pass

    return pairs


def parse_hyperopt_output(output: str) -> Optional[dict]:
    """
    Parse hyperopt output to extract best parameters and metrics.

    Returns dict with: best_profit_pct, best_trades, params (roi, stoploss, trailing).
    """
    result = {"params": {}}
    lines = output.strip().split("\n")

    for line in lines:
        if "Best result" in line:
            result["best_result_line"] = line.strip()
            profit_match = re.search(r"([-\d.]+)\s*%", line)
            trades_match = re.search(r"(\d+)\s*trades", line)
            if profit_match:
                result["best_profit_pct"] = float(profit_match.group(1))
            if trades_match:
                result["best_trades"] = int(trades_match.group(1))

    # Look for JSON params block (--print-json output)
    json_started = False
    json_lines = []
    brace_depth = 0
    for line in lines:
        stripped = line.strip()
        if not json_started and stripped.startswith("{") and (
            "roi" in stripped or "stoploss" in stripped or "trailing" in stripped
        ):
            json_started = True

        if json_started:
            json_lines.append(stripped)
            brace_depth += stripped.count("{") - stripped.count("}")
            if brace_depth <= 0:
                try:
                    result["params"] = json.loads("\n".join(json_lines))
                except json.JSONDecodeError:
                    pass
                json_started = False
                json_lines = []
                brace_depth = 0

    return result if result.get("params") or result.get("best_profit_pct") is not None else None


def parse_lookahead_output(output: str) -> dict:
    """
    Parse Freqtrade lookahead-analysis output.

    Returns dict with: passed (bool), indicators (list of flagged indicators).
    """
    result = {"passed": True, "flagged_indicators": [], "raw": ""}
    lines = output.strip().split("\n")
    result["raw"] = "\n".join(lines[-40:])

    for line in lines:
        lower = line.lower()
        if "lookahead bias" in lower and ("found" in lower or "detected" in lower):
            result["passed"] = False
        if "indicator" in lower and ("bias" in lower or "future" in lower):
            # Extract indicator name
            parts = [p.strip() for p in re.split(r"[│┃|]", line) if p.strip()]
            if parts:
                result["flagged_indicators"].append(parts[0])

    return result


def parse_recursive_output(output: str) -> dict:
    """
    Parse Freqtrade recursive-analysis output.

    Returns dict with: warning (bool), flagged_indicators (list).
    """
    result = {"warning": False, "flagged_indicators": [], "raw": ""}
    lines = output.strip().split("\n")
    result["raw"] = "\n".join(lines[-40:])

    for line in lines:
        lower = line.lower()
        if "recursive" in lower and ("issue" in lower or "depend" in lower or "found" in lower):
            result["warning"] = True
        if "/USDT" not in line:
            parts = [p.strip() for p in re.split(r"[│┃|]", line) if p.strip()]
            if len(parts) >= 2 and any(kw in line.lower() for kw in ["differ", "change", "unstable"]):
                result["flagged_indicators"].append(parts[0])

    return result


def parse_trade_export_json(filepath: str) -> list[dict]:
    """
    Parse exported trades JSON from Freqtrade backtest.

    Returns list of trade dicts with: pair, open_date, close_date, profit_abs, etc.
    """
    try:
        with open(filepath) as f:
            data = json.load(f)

        # Freqtrade exports as {strategy_name: {trades: [...]}}
        if isinstance(data, dict):
            for strategy_name, strategy_data in data.items():
                if isinstance(strategy_data, dict) and "trades" in strategy_data:
                    return strategy_data["trades"]
                elif isinstance(strategy_data, list):
                    return strategy_data

        if isinstance(data, list):
            return data

        return []
    except (json.JSONDecodeError, FileNotFoundError) as e:
        log.error("Failed to parse trade export %s: %s", filepath, e)
        return []
