"""
Trade Decision Logger — captures TradingView chart state when bots open/close trades.

Polls Freqtrade APIs every 30s, diffs against known state, and logs indicator snapshots.
Designed to run as a background daemon or via cron.

Usage:
    python3 ft_userdata/tv_bridge/trade_logger.py          # run once
    python3 ft_userdata/tv_bridge/trade_logger.py --daemon  # poll loop
"""
import json
import os
import sys
import time
import logging
import argparse
from datetime import datetime, timezone

# Add parent dir for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tv_bridge.config import active_bots, API_USER, API_PASS, TRADE_LOGS_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [TradeLogger] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

POLL_INTERVAL = 30  # seconds
STATE_FILE = os.path.join(os.path.dirname(__file__), ".trade_logger_state.json")


def api_get(url):
    """GET from Freqtrade API with basic auth."""
    import urllib.request
    import base64

    credentials = base64.b64encode(f"{API_USER}:{API_PASS}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {credentials}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.warning(f"API error {url}: {e}")
        return None


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def get_open_trades(port):
    return api_get(f"http://localhost:{port}/api/v1/status") or []


def get_closed_trades(port, limit=10):
    return api_get(f"http://localhost:{port}/api/v1/trades?limit={limit}") or {}


def log_trade_event(bot_name, trade, event_type):
    """Log a trade entry/exit event with context for later TV analysis."""
    trade_id = trade.get("trade_id", "unknown")
    pair = trade.get("pair", "unknown")

    log_dir = os.path.join(TRADE_LOGS_DIR, bot_name)
    os.makedirs(log_dir, exist_ok=True)

    context = {
        "bot": bot_name,
        "trade_id": trade_id,
        "event": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pair": pair,
        "stake_amount": trade.get("stake_amount"),
        "open_rate": trade.get("open_rate"),
        "open_date": trade.get("open_date"),
        "trade_direction": trade.get("trade_direction", "long"),
        # TV analysis fields — populated later by Claude when reviewing
        "tv_indicator_snapshot": None,
        "tv_ohlcv_summary": None,
        "tv_screenshot_path": None,
    }

    if event_type == "exit":
        context.update(
            {
                "close_rate": trade.get("close_rate"),
                "close_date": trade.get("close_date"),
                "close_profit": trade.get("close_profit"),
                "close_profit_abs": trade.get("close_profit_abs"),
                "exit_reason": trade.get("exit_reason"),
                "duration": trade.get("trade_duration"),
            }
        )

    filename = f"{trade_id}_{event_type}.json"
    filepath = os.path.join(log_dir, filename)
    with open(filepath, "w") as f:
        json.dump(context, f, indent=2)

    log.info(f"[{bot_name}] {event_type.upper()} {pair} #{trade_id} → {filepath}")
    return filepath


def poll_once():
    """Single poll cycle across all active bots."""
    state = load_state()
    bots = active_bots()
    events = []

    for bot_name, bot_cfg in bots.items():
        port = bot_cfg["port"]
        bot_state_key = f"{bot_name}_{port}"

        if bot_state_key not in state:
            state[bot_state_key] = {"open_trade_ids": [], "closed_trade_ids": []}

        # Check open trades
        open_trades = get_open_trades(port)
        if open_trades is None:
            continue

        current_open_ids = {t["trade_id"] for t in open_trades}
        prev_open_ids = set(state[bot_state_key]["open_trade_ids"])

        # New entries
        new_entries = current_open_ids - prev_open_ids
        for trade in open_trades:
            if trade["trade_id"] in new_entries:
                path = log_trade_event(bot_name, trade, "entry")
                events.append(("entry", bot_name, trade["pair"], path))

        # Check closed trades for exits
        closed_data = get_closed_trades(port)
        closed_trades = closed_data.get("trades", []) if isinstance(closed_data, dict) else []
        prev_closed_ids = set(state[bot_state_key]["closed_trade_ids"])

        for trade in closed_trades:
            tid = trade.get("trade_id")
            if tid and tid not in prev_closed_ids and tid in prev_open_ids:
                path = log_trade_event(bot_name, trade, "exit")
                events.append(("exit", bot_name, trade.get("pair"), path))

        # Update state
        state[bot_state_key]["open_trade_ids"] = list(current_open_ids)
        state[bot_state_key]["closed_trade_ids"] = list(
            prev_closed_ids | {t.get("trade_id") for t in closed_trades if t.get("trade_id")}
        )

    save_state(state)
    return events


def daemon_loop():
    """Continuous polling loop."""
    log.info(f"Starting trade logger daemon (poll every {POLL_INTERVAL}s)")
    log.info(f"Monitoring {len(active_bots())} active bots")
    log.info(f"Logs → {TRADE_LOGS_DIR}")

    while True:
        try:
            events = poll_once()
            if events:
                for ev_type, bot, pair, path in events:
                    log.info(f"  Event: {ev_type} {bot} {pair}")
        except KeyboardInterrupt:
            log.info("Shutting down")
            break
        except Exception as e:
            log.error(f"Poll error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trade Decision Logger")
    parser.add_argument("--daemon", action="store_true", help="Run as continuous daemon")
    args = parser.parse_args()

    if args.daemon:
        daemon_loop()
    else:
        events = poll_once()
        if events:
            for ev_type, bot, pair, path in events:
                print(f"{ev_type}: {bot} {pair} → {path}")
        else:
            print("No new trade events.")
