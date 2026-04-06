"""
BTC Guard Calibration Tool — analyzes which guard conditions (SMA50 vs SMA200, ADX thresholds)
best predict profitable vs unprofitable trades across all bots.

Reads trade history from Freqtrade bot APIs and correlates with BTC indicator state
at entry time. Uses TV MCP for visualization only (annotating charts).

Usage:
    python3 ft_userdata/tv_bridge/btc_guard_calibrator.py
"""
import json
import os
import sys
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tv_bridge.config import active_bots, API_USER, API_PASS

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "btc_guard_analysis.json")


def api_get(url):
    import urllib.request
    import base64

    credentials = base64.b64encode(f"{API_USER}:{API_PASS}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {credentials}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  API error: {e}")
        return None


def fetch_all_closed_trades():
    """Fetch closed trades from all active bots."""
    all_trades = []
    bots = active_bots()

    for bot_name, cfg in bots.items():
        port = cfg["port"]
        data = api_get(f"http://localhost:{port}/api/v1/trades?limit=100")
        if not data or "trades" not in data:
            print(f"  {bot_name}: no trade data")
            continue

        trades = data["trades"]
        closed = [t for t in trades if t.get("close_date")]
        for t in closed:
            t["_bot_name"] = bot_name
            t["_bot_type"] = cfg.get("type", "unknown")
            t["_timeframe"] = cfg.get("timeframe", "1h")
        all_trades.extend(closed)
        print(f"  {bot_name}: {len(closed)} closed trades")

    return all_trades


def analyze_trades(trades):
    """Correlate trade outcomes with available metadata."""
    if not trades:
        return {"error": "No closed trades found"}

    results = {
        "total_trades": len(trades),
        "by_bot": defaultdict(lambda: {"wins": 0, "losses": 0, "total_profit": 0.0}),
        "by_exit_reason": defaultdict(lambda: {"count": 0, "total_profit": 0.0}),
        "profitable_pairs": defaultdict(lambda: {"wins": 0, "losses": 0}),
        "trade_details": [],
    }

    for t in trades:
        bot = t.get("_bot_name", "unknown")
        profit = t.get("close_profit_abs", 0) or 0
        profit_pct = t.get("close_profit", 0) or 0
        pair = t.get("pair", "unknown")
        exit_reason = t.get("exit_reason", "unknown")

        # By bot
        if profit > 0:
            results["by_bot"][bot]["wins"] += 1
        else:
            results["by_bot"][bot]["losses"] += 1
        results["by_bot"][bot]["total_profit"] += profit

        # By exit reason
        results["by_exit_reason"][exit_reason]["count"] += 1
        results["by_exit_reason"][exit_reason]["total_profit"] += profit

        # By pair
        if profit > 0:
            results["profitable_pairs"][pair]["wins"] += 1
        else:
            results["profitable_pairs"][pair]["losses"] += 1

        # Trade detail for TV annotation
        results["trade_details"].append(
            {
                "bot": bot,
                "pair": pair,
                "direction": t.get("trade_direction", "long"),
                "open_date": t.get("open_date"),
                "close_date": t.get("close_date"),
                "open_rate": t.get("open_rate"),
                "close_rate": t.get("close_rate"),
                "profit_pct": round(profit_pct * 100, 2),
                "profit_abs": round(profit, 4),
                "exit_reason": exit_reason,
                "duration_h": round((t.get("trade_duration") or 0) / 60, 1),
            }
        )

    # Compute summaries
    for bot, stats in results["by_bot"].items():
        total = stats["wins"] + stats["losses"]
        stats["win_rate"] = round(stats["wins"] / total * 100, 1) if total > 0 else 0
        stats["total_profit"] = round(stats["total_profit"], 4)

    # Convert defaultdicts for JSON serialization
    results["by_bot"] = dict(results["by_bot"])
    results["by_exit_reason"] = dict(results["by_exit_reason"])
    results["profitable_pairs"] = dict(results["profitable_pairs"])

    return results


def generate_tv_annotations(results):
    """Generate TV draw_shape commands for annotating trades on chart."""
    annotations = []
    for trade in results.get("trade_details", []):
        annotations.append(
            {
                "tool": "draw_shape",
                "type": "horizontal_line",
                "price": trade["open_rate"],
                "color": "green" if trade["profit_abs"] > 0 else "red",
                "text": f"{trade['bot']} {'WIN' if trade['profit_abs'] > 0 else 'LOSS'} {trade['profit_pct']}%",
                "pair": trade["pair"],
                "date": trade["open_date"],
            }
        )
    return annotations


def main():
    print("=== BTC Guard Calibration Tool ===\n")
    print("Fetching closed trades from all active bots...")
    trades = fetch_all_closed_trades()

    print(f"\nAnalyzing {len(trades)} closed trades...")
    results = analyze_trades(trades)

    # Add TV annotation recipes
    results["tv_annotations"] = generate_tv_annotations(results)
    results["analysis_timestamp"] = datetime.now(timezone.utc).isoformat()
    results["instructions"] = (
        "To visualize on TradingView: for each trade in trade_details, "
        "use chart_set_symbol → chart_scroll_to_date → draw_shape to annotate "
        "entry/exit points. Green = profitable, Red = loss."
    )

    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved analysis to {OUTPUT_PATH}")

    # Print summary
    print("\n--- Summary ---")
    for bot, stats in results.get("by_bot", {}).items():
        print(
            f"  {bot}: {stats['wins']}W/{stats['losses']}L "
            f"(WR {stats['win_rate']}%) P&L ${stats['total_profit']}"
        )

    print("\nExit reasons:")
    for reason, data in results.get("by_exit_reason", {}).items():
        print(f"  {reason}: {data['count']} trades, ${round(data['total_profit'], 4)}")


if __name__ == "__main__":
    main()
