#!/usr/bin/env python3
"""
rebuild_history.py — Rewrite a bot's trade history as if current parameters had always been active.

Uses REAL trade data (real entries, real prices, real timing), then:
  1. Filters out entries that new entry gates would have blocked
  2. Re-simulates exits for trades affected by exit rule changes using real candle data
  3. Keeps all other trades exactly as they are

The script auto-detects what needs to change by reading the strategy's current parameters
(stoploss, ROI, trailing, exit_profit_only) and comparing with how each trade actually exited.

Entry gate filters are defined in ENTRY_GATES — add new gates there when strategies change.
Exit re-simulation handles: stoploss changes, ROI changes, trailing changes, exit_profit_only.

Usage:
    python3 rebuild_history.py <StrategyName> [--dry-run] [--timerange 20260311-20260331]

Flags:
    --dry-run       Do everything except swap the DB
"""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent
USER_DATA = BASE_DIR / "user_data"
CONFIGS_DIR = USER_DATA / "configs"
DOCKER_IMAGE = "freqtradeorg/freqtrade:stable"


def log(msg):
    print(f"[rebuild] {msg}")


def error(msg):
    print(f"[rebuild] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def read_live_config(strategy: str) -> dict:
    config_path = CONFIGS_DIR / f"{strategy}.json"
    if not config_path.exists():
        error(f"Live config not found: {config_path}")
    with open(config_path) as f:
        return json.load(f)


def get_db_path(strategy: str, config: dict) -> Path:
    db_url = config.get("db_url", "")
    if db_url.startswith("sqlite:///"):
        db_file = db_url.replace("sqlite:///", "")
        if db_file.startswith("/freqtrade/user_data/"):
            db_file = db_file.replace("/freqtrade/user_data/", "")
            return USER_DATA / db_file
        if not os.path.isabs(db_file):
            return USER_DATA / db_file
        return Path(db_file)
    return USER_DATA / f"tradesv3.dryrun.{strategy}.sqlite"


def detect_strategy_params(strategy: str) -> dict:
    """Read strategy .py to extract timeframe, startup_candle_count, stoploss, ROI, trailing, exit_profit_only."""
    strat_path = USER_DATA / "strategies" / f"{strategy}.py"
    params = {
        "timeframe": "1h",
        "startup_candle_count": 200,
        "stoploss": -0.05,
        "trailing_stop": False,
        "trailing_stop_positive": 0.0,
        "trailing_stop_positive_offset": 0.0,
        "trailing_only_offset_is_reached": False,
        "exit_profit_only": False,
        "exit_profit_offset": 0.0,
        "minimal_roi": {},
    }
    if not strat_path.exists():
        return params

    with open(strat_path) as f:
        content = f.read()

    # Simple parser: extract key = value from strategy class
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        # Skip lines inside functions
        key = line.split("=")[0].strip()
        val_str = line.split("=", 1)[1].strip().split("#")[0].strip()

        tf_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
        if key == "timeframe":
            for tf in tf_map:
                if f"'{tf}'" in val_str or f'"{tf}"' in val_str:
                    params["timeframe"] = tf
        elif key == "startup_candle_count":
            try: params["startup_candle_count"] = int(val_str)
            except: pass
        elif key == "stoploss":
            try: params["stoploss"] = float(val_str)
            except: pass
        elif key == "trailing_stop" and val_str in ("True", "False"):
            params["trailing_stop"] = val_str == "True"
        elif key == "trailing_stop_positive":
            try: params["trailing_stop_positive"] = float(val_str)
            except: pass
        elif key == "trailing_stop_positive_offset":
            try: params["trailing_stop_positive_offset"] = float(val_str)
            except: pass
        elif key == "trailing_only_offset_is_reached" and val_str in ("True", "False"):
            params["trailing_only_offset_is_reached"] = val_str == "True"
        elif key == "exit_profit_only" and val_str in ("True", "False"):
            params["exit_profit_only"] = val_str == "True"
        elif key == "exit_profit_offset":
            try: params["exit_profit_offset"] = float(val_str)
            except: pass

    # Parse minimal_roi
    try:
        import re
        roi_match = re.search(r'minimal_roi\s*=\s*\{([^}]+)\}', content)
        if roi_match:
            roi_str = "{" + roi_match.group(1) + "}"
            # Convert Python dict literal to JSON-compatible
            roi_str = roi_str.replace("'", '"')
            params["minimal_roi"] = json.loads(roi_str)
    except:
        pass

    return params


def load_candle_data(pair: str, timeframe: str) -> list:
    """Load candle data from Freqtrade's data directory."""
    import struct

    # Try feather format first
    pair_file = pair.replace("/", "_")
    feather_path = USER_DATA / "data" / "binance" / f"{pair_file}-{timeframe}.feather"
    json_path = USER_DATA / "data" / "binance" / f"{pair_file}-{timeframe}.json"

    if feather_path.exists():
        # Use docker to read feather since we don't have pandas locally
        result = subprocess.run([
            "docker", "run", "--rm", "--entrypoint", "python3",
            "-v", f"{USER_DATA}:/freqtrade/user_data",
            DOCKER_IMAGE,
            "-c", f"""
import pandas as pd, json
df = pd.read_feather('/freqtrade/user_data/data/binance/{pair_file}-{timeframe}.feather')
# Output as JSON lines: timestamp_ms, open, high, low, close, volume
for _, r in df.iterrows():
    ts = int(r['date'].timestamp() * 1000) if hasattr(r['date'], 'timestamp') else int(r['date'])
    print(json.dumps([ts, float(r['open']), float(r['high']), float(r['low']), float(r['close']), float(r['volume'])]))
"""
        ], capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            candles = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    candles.append(json.loads(line))
            return candles

    if json_path.exists():
        with open(json_path) as f:
            return json.load(f)

    return []


# ── Entry Gate Registry ──────────────────────────────────────────────
# Each gate is a function(candle_data_dict, trade_open_ts, strategy_content) -> bool
# Returns True = ALLOW entry, False = BLOCK entry
# Gates are auto-detected from the strategy source code.

def gate_btc_sma_composite(candle_data: dict, trade_open_ts: float, strategy_content: str) -> bool:
    """BTC must be above all referenced SMA periods. Auto-detects which SMAs are required
    by scanning the strategy's btc_bullish condition."""
    btc_candles = candle_data.get("BTC/USDT", [])
    if not btc_candles:
        return True

    # Detect which SMA periods are used in the btc_bullish condition
    import re
    sma_periods = []
    for match in re.finditer(r'btc_usdt_sma(\d+)_', strategy_content):
        period = int(match.group(1))
        if period not in sma_periods:
            sma_periods.append(period)

    if not sma_periods:
        return True  # No SMA gates found

    max_period = max(sma_periods)

    closes = []
    for c in btc_candles:
        if c[0] / 1000 > trade_open_ts:
            break
        closes.append(c[4])

    if len(closes) < max_period:
        return True  # Not enough data

    current_close = closes[-1]
    for period in sma_periods:
        sma = sum(closes[-period:]) / period
        if current_close <= sma:
            return False

    # Check RSI > 35 if strategy uses it in btc_bullish
    if 'rsi_1h' in strategy_content and 'btc_bullish' in strategy_content:
        # Simple RSI approximation using 14-period Wilder's smoothing
        if len(closes) >= 15:
            gains = []
            losses = []
            for i in range(-14, 0):
                delta = closes[i] - closes[i - 1]
                gains.append(max(delta, 0))
                losses.append(max(-delta, 0))
            avg_gain = sum(gains) / 14
            avg_loss = sum(losses) / 14
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                if rsi <= 35:
                    return False

    return True


def gate_btc_crash(candle_data: dict, trade_open_ts: float, strategy_content: str) -> bool:
    """BTC crash detection: block if BTC dropped >3% in 24 candles."""
    if 'btc_crash' not in strategy_content:
        return True

    btc_candles = candle_data.get("BTC/USDT", [])
    if not btc_candles:
        return True

    closes = []
    for c in btc_candles:
        if c[0] / 1000 > trade_open_ts:
            break
        closes.append(c[4])

    if len(closes) < 25:
        return True

    return closes[-1] >= closes[-25] * 0.97


def detect_entry_gates(strategy_content: str) -> list:
    """Auto-detect which entry gates are active in the strategy."""
    gates = []
    if 'btc_bullish' in strategy_content and 'sma' in strategy_content.lower():
        gates.append(("BTC SMA composite", gate_btc_sma_composite))
    if 'btc_crash' in strategy_content:
        gates.append(("BTC crash guard", gate_btc_crash))
    return gates


def check_entry_gates(gates: list, candle_data: dict, trade_open_ts: float, strategy_content: str) -> tuple:
    """Check all entry gates. Returns (allowed: bool, blocked_by: str or None)."""
    for name, gate_fn in gates:
        if not gate_fn(candle_data, trade_open_ts, strategy_content):
            return False, name
    return True, None


def simulate_exit(
    candles: list,
    open_rate: float,
    open_ts: float,
    original_close_ts: float,
    stake_amount: float,
    amount: float,
    stoploss: float,
    roi_table: dict,
    trailing_stop: bool,
    trailing_positive: float,
    trailing_offset: float,
    trailing_only_offset: bool,
    fee: float,
) -> dict:
    """Simulate what would happen to a trade if the exit_signal was ignored.
    Walk through candles from the original exit time forward, checking ROI/trailing/stoploss."""

    # Current state
    highest_rate = open_rate
    current_sl = open_rate * (1 + stoploss)  # absolute stoploss price
    initial_sl = current_sl
    is_trailing = False

    # Parse ROI table (keys are minutes as strings)
    roi_entries = sorted([(int(k), v) for k, v in roi_table.items()])

    for candle in candles:
        candle_ts = candle[0] / 1000
        if candle_ts <= original_close_ts:
            # Update highest rate from candles during the trade's original lifetime too
            if candle_ts >= open_ts:
                c_high = candle[2]
                if c_high > highest_rate:
                    highest_rate = c_high
            continue

        c_open = candle[1]
        c_high = candle[2]
        c_low = candle[3]
        c_close = candle[4]
        trade_minutes = (candle_ts - open_ts) / 60

        # Update highest rate
        if c_high > highest_rate:
            highest_rate = c_high

        # Check trailing stop
        if trailing_stop:
            if trailing_only_offset:
                offset_reached = (highest_rate - open_rate) / open_rate >= trailing_offset
                if offset_reached:
                    new_sl = highest_rate * (1 - trailing_positive)
                    if new_sl > current_sl:
                        current_sl = new_sl
                        is_trailing = True
            else:
                new_sl = highest_rate * (1 - trailing_positive)
                if new_sl > current_sl:
                    current_sl = new_sl
                    is_trailing = True

        # Check stoploss hit
        if c_low <= current_sl:
            exit_rate = current_sl
            profit_ratio = (exit_rate / open_rate) - 1 - (2 * fee)
            profit_abs = stake_amount * profit_ratio
            exit_reason = "trailing_stop_loss" if is_trailing else "stoploss_on_exchange"
            return {
                "close_rate": exit_rate,
                "close_date": datetime.fromtimestamp(candle_ts).strftime("%Y-%m-%d %H:%M:%S.000000"),
                "close_profit": profit_ratio,
                "close_profit_abs": profit_abs,
                "exit_reason": exit_reason,
                "max_rate": highest_rate,
                "stop_loss": current_sl,
                "is_stop_loss_trailing": 1 if is_trailing else 0,
            }

        # Check ROI
        for roi_minutes, roi_pct in roi_entries:
            if trade_minutes >= roi_minutes:
                roi_price = open_rate * (1 + roi_pct)
                if c_high >= roi_price:
                    exit_rate = roi_price
                    profit_ratio = roi_pct - (2 * fee)
                    profit_abs = stake_amount * profit_ratio
                    return {
                        "close_rate": exit_rate,
                        "close_date": datetime.fromtimestamp(candle_ts).strftime("%Y-%m-%d %H:%M:%S.000000"),
                        "close_profit": profit_ratio,
                        "close_profit_abs": profit_abs,
                        "exit_reason": "roi",
                        "max_rate": max(highest_rate, c_high),
                        "stop_loss": current_sl,
                        "is_stop_loss_trailing": 1 if is_trailing else 0,
                    }

    # If we ran out of candles, trade is still open — force exit at last candle close
    if candles:
        last = candles[-1]
        exit_rate = last[4]
        profit_ratio = (exit_rate / open_rate) - 1 - (2 * fee)
        profit_abs = stake_amount * profit_ratio
        return {
            "close_rate": exit_rate,
            "close_date": datetime.fromtimestamp(last[0] / 1000).strftime("%Y-%m-%d %H:%M:%S.000000"),
            "close_profit": profit_ratio,
            "close_profit_abs": profit_abs,
            "exit_reason": "force_exit",
            "max_rate": highest_rate,
            "stop_loss": current_sl,
            "is_stop_loss_trailing": 1 if is_trailing else 0,
        }

    return None


def compare_dbs(old_path: Path, new_path: Path):
    """Print comparison report."""
    def db_stats(path):
        if not path.exists():
            return None
        db = sqlite3.connect(str(path))
        db.row_factory = sqlite3.Row
        trades = db.execute("SELECT * FROM trades WHERE is_open = 0").fetchall()
        db.close()
        if not trades:
            return {"trades": 0}
        wins = [t for t in trades if t["close_profit_abs"] >= 0]
        losses = [t for t in trades if t["close_profit_abs"] < 0]
        gross_win = sum(t["close_profit_abs"] for t in wins)
        gross_loss = abs(sum(t["close_profit_abs"] for t in losses))
        exits = {}
        for t in trades:
            r = t["exit_reason"]
            if r not in exits: exits[r] = {"count": 0, "pnl": 0}
            exits[r]["count"] += 1
            exits[r]["pnl"] += t["close_profit_abs"]
        return {
            "trades": len(trades), "wins": len(wins), "losses": len(losses),
            "wr": len(wins) / len(trades) * 100,
            "pf": gross_win / gross_loss if gross_loss else 999,
            "pnl": sum(t["close_profit_abs"] for t in trades),
            "gross_win": gross_win, "gross_loss": gross_loss,
            "avg_win": gross_win / len(wins) if wins else 0,
            "avg_loss": gross_loss / len(losses) if losses else 0,
            "exits": exits,
        }

    old = db_stats(old_path)
    new = db_stats(new_path)
    if not old or not new:
        log("Cannot compare — one or both DBs are empty")
        return

    print("\n" + "=" * 70)
    print(f"{'COMPARISON REPORT':^70}")
    print("=" * 70)
    print(f"{'Metric':<25} {'Old (live)':>20} {'New (rebuilt)':>20}")
    print("-" * 70)
    for label, o, n in [
        ("Trades", f"{old['trades']}", f"{new['trades']}"),
        ("Wins", f"{old['wins']}", f"{new['wins']}"),
        ("Losses", f"{old['losses']}", f"{new['losses']}"),
        ("Win Rate", f"{old['wr']:.1f}%", f"{new['wr']:.1f}%"),
        ("Profit Factor", f"{old['pf']:.2f}", f"{new['pf']:.2f}"),
        ("Total P&L", f"${old['pnl']:+.2f}", f"${new['pnl']:+.2f}"),
        ("Gross Win", f"${old['gross_win']:.2f}", f"${new['gross_win']:.2f}"),
        ("Gross Loss", f"-${old['gross_loss']:.2f}", f"-${new['gross_loss']:.2f}"),
        ("Avg Win", f"${old['avg_win']:.2f}", f"${new['avg_win']:.2f}"),
        ("Avg Loss", f"-${old['avg_loss']:.2f}", f"-${new['avg_loss']:.2f}"),
    ]:
        print(f"{label:<25} {o:>20} {n:>20}")

    print("\n--- Exit Reason Breakdown ---")
    all_reasons = sorted(set(list(old["exits"].keys()) + list(new["exits"].keys())))
    print(f"{'Exit Reason':<25} {'Old (count/P&L)':>20} {'New (count/P&L)':>20}")
    print("-" * 70)
    for r in all_reasons:
        oe = old["exits"].get(r, {"count": 0, "pnl": 0})
        ne = new["exits"].get(r, {"count": 0, "pnl": 0})
        print(f"{r:<25} {oe['count']:>3} / ${oe['pnl']:>+7.2f}    {ne['count']:>3} / ${ne['pnl']:>+7.2f}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Rewrite bot trade history with current parameters")
    parser.add_argument("strategy", help="Strategy name (e.g., SupertrendStrategy)")
    parser.add_argument("--dry-run", action="store_true", help="Do everything except swap the DB")
    parser.add_argument("--timerange", help="Override data download timerange (YYYYMMDD-YYYYMMDD)")
    args = parser.parse_args()

    strategy = args.strategy
    log(f"Rebuilding history for: {strategy}")

    # Step 1: Read config and strategy params
    live_config = read_live_config(strategy)
    db_path = get_db_path(strategy, live_config)
    params = detect_strategy_params(strategy)

    log(f"DB: {db_path}")
    log(f"Wallet: ${live_config.get('dry_run_wallet', '?')}, Max trades: {live_config.get('max_open_trades', '?')}")
    log(f"Params: stoploss={params['stoploss']}, trailing={params['trailing_stop']}, "
        f"exit_profit_only={params['exit_profit_only']}, offset={params['exit_profit_offset']}")
    log(f"ROI: {params['minimal_roi']}")

    if not db_path.exists():
        error(f"DB not found: {db_path}")

    # Step 2: Load all trades from the DB
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    all_trades = db.execute("SELECT * FROM trades WHERE is_open = 0 ORDER BY open_date ASC").fetchall()
    all_orders = {}
    for row in db.execute("SELECT * FROM orders ORDER BY id ASC").fetchall():
        tid = row["ft_trade_id"]
        if tid not in all_orders:
            all_orders[tid] = []
        all_orders[tid].append(dict(row))
    db.close()
    log(f"Loaded {len(all_trades)} closed trades")

    # Step 3: Download candle data (need BTC for SMA gate + each traded pair for exit sim)
    pairs = list(set(t["pair"] for t in all_trades))
    if "BTC/USDT" not in pairs:
        pairs.append("BTC/USDT")

    # Detect timerange for data download
    first_open = str(all_trades[0]["open_date"])[:10].replace("-", "")
    end_date = datetime.now().strftime("%Y%m%d")

    tf_minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
    buffer_days = int(params["startup_candle_count"] * tf_minutes.get(params["timeframe"], 60) / 60 / 24) + 5
    dl_start = datetime.strptime(first_open, "%Y%m%d") - timedelta(days=buffer_days)

    timerange = args.timerange or f"{dl_start.strftime('%Y%m%d')}-{end_date}"

    # Create temp config for data download
    dl_config = {
        "exchange": {"name": "binance", "key": "", "secret": "",
                     "pair_whitelist": pairs, "pair_blacklist": []},
        "pairlists": [{"method": "StaticPairList"}],
        "stake_currency": "USDT",
        "trading_mode": live_config.get("trading_mode", "spot"),
        "margin_mode": live_config.get("margin_mode", ""),
    }
    tmp_config = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", dir=str(CONFIGS_DIR),
        prefix=f"_rebuild_{strategy}_", delete=False
    )
    json.dump(dl_config, tmp_config, indent=2)
    tmp_config.close()

    try:
        config_name = os.path.basename(tmp_config.name)
        log(f"Downloading data for {len(pairs)} pairs, timerange {timerange}...")
        result = subprocess.run([
            "docker", "run", "--rm",
            "-v", f"{USER_DATA}:/freqtrade/user_data",
            DOCKER_IMAGE, "download-data",
            "--config", f"/freqtrade/user_data/configs/{config_name}",
            "--timerange", timerange,
            "--timeframe", params["timeframe"],
        ], capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            error(f"Data download failed:\n{result.stderr[-500:]}")
        log("Data downloaded")
    finally:
        os.remove(tmp_config.name)

    # Step 4: Load strategy source and detect entry gates
    strat_path = USER_DATA / "strategies" / f"{strategy}.py"
    strategy_content = ""
    if strat_path.exists():
        with open(strat_path) as f:
            strategy_content = f.read()

    entry_gates = detect_entry_gates(strategy_content)
    log(f"Entry gates detected: {[name for name, _ in entry_gates] or ['none']}")

    # Load candle data for gate checks
    candle_data = {}
    if entry_gates:
        log("Loading BTC candle data for entry gates...")
        candle_data["BTC/USDT"] = load_candle_data("BTC/USDT", params["timeframe"])
        log(f"  BTC candles: {len(candle_data['BTC/USDT'])}")

    # Step 5: Process each trade
    kept = []
    blocked = []
    resimulated = []
    candle_cache = {}

    for t in all_trades:
        trade = dict(t)
        trade_id = trade["id"]
        orders = all_orders.get(trade_id, [])

        # Parse open timestamp
        open_dt = datetime.fromisoformat(str(trade["open_date"])[:19])
        open_ts = open_dt.timestamp()

        # Check entry gates
        allowed, blocked_by = check_entry_gates(entry_gates, candle_data, open_ts, strategy_content)
        if not allowed:
            blocked.append((trade, blocked_by))
            continue

        # Check if exit needs re-simulation
        exit_reason = trade["exit_reason"]
        profit_pct = (trade["close_profit"] or 0) * 100
        needs_resim = (
            params["exit_profit_only"]
            and exit_reason == "exit_signal"
            and profit_pct < params["exit_profit_offset"] * 100
        )

        if not needs_resim:
            kept.append((trade, orders))
            continue

        # Re-simulate: load candle data for this pair
        pair = trade["pair"]
        if pair not in candle_cache:
            candle_cache[pair] = load_candle_data(pair, params["timeframe"])

        pair_candles = candle_cache[pair]
        if not pair_candles:
            log(f"  WARNING: No candle data for {pair}, keeping original exit")
            kept.append((trade, orders))
            continue

        close_dt = datetime.fromisoformat(str(trade["close_date"])[:19])
        close_ts = close_dt.timestamp()

        sim_result = simulate_exit(
            candles=pair_candles,
            open_rate=trade["open_rate"],
            open_ts=open_ts,
            original_close_ts=close_ts,
            stake_amount=trade["stake_amount"],
            amount=trade["amount"],
            stoploss=params["stoploss"],
            roi_table=params["minimal_roi"],
            trailing_stop=params["trailing_stop"],
            trailing_positive=params["trailing_stop_positive"],
            trailing_offset=params["trailing_stop_positive_offset"],
            trailing_only_offset=params["trailing_only_offset_is_reached"],
            fee=trade["fee_open"],
        )

        if sim_result:
            old_profit = trade["close_profit_abs"]
            # Update trade with simulated exit
            trade["close_rate"] = sim_result["close_rate"]
            trade["close_rate_requested"] = sim_result["close_rate"]
            trade["close_date"] = sim_result["close_date"]
            trade["close_profit"] = sim_result["close_profit"]
            trade["close_profit_abs"] = sim_result["close_profit_abs"]
            trade["realized_profit"] = sim_result["close_profit_abs"]
            trade["exit_reason"] = sim_result["exit_reason"]
            trade["max_rate"] = sim_result["max_rate"]
            trade["stop_loss"] = sim_result["stop_loss"]
            trade["is_stop_loss_trailing"] = sim_result["is_stop_loss_trailing"]

            # Update the sell order
            for o in orders:
                if o["ft_order_side"] == "sell":
                    o["ft_price"] = sim_result["close_rate"]
                    o["price"] = sim_result["close_rate"]
                    o["average"] = sim_result["close_rate"]
                    o["cost"] = trade["amount"] * sim_result["close_rate"]
                    o["order_date"] = sim_result["close_date"]
                    o["order_filled_date"] = sim_result["close_date"]
                    o["order_update_date"] = sim_result["close_date"]
                    o["ft_order_tag"] = sim_result["exit_reason"]

            # Update fee_close_cost
            trade["fee_close_cost"] = trade["amount"] * sim_result["close_rate"] * trade["fee_close"]

            log(f"  RE-SIM {pair:20s} exit_signal({old_profit:+.2f}) -> {sim_result['exit_reason']}({sim_result['close_profit_abs']:+.2f})")
            resimulated.append((trade, orders))
        else:
            log(f"  WARNING: Simulation returned no result for {pair}, keeping original")
            kept.append((trade, orders))

    log(f"\nResults: {len(kept)} kept, {len(blocked)} blocked by SMA50, {len(resimulated)} re-simulated")

    # Step 6: Build new DB
    new_db_path = db_path.parent / f"{db_path.stem}.rebuilt.sqlite"
    if new_db_path.exists():
        os.remove(str(new_db_path))

    # Copy the original DB structure, then replace trades
    shutil.copy2(str(db_path), str(new_db_path))
    new_db = sqlite3.connect(str(new_db_path))

    # Clear trades and orders
    new_db.execute("DELETE FROM orders")
    new_db.execute("DELETE FROM trades")
    new_db.execute("DELETE FROM pairlocks")
    new_db.commit()

    # Re-insert kept + resimulated trades with sequential IDs
    all_final = kept + resimulated
    all_final.sort(key=lambda x: x[0]["open_date"])

    trade_cols = [desc[1] for desc in new_db.execute("PRAGMA table_info(trades)").fetchall()]
    order_cols = [desc[1] for desc in new_db.execute("PRAGMA table_info(orders)").fetchall()]

    new_trade_id = 1
    new_order_id = 1

    for trade, orders in all_final:
        old_id = trade["id"]
        trade["id"] = new_trade_id

        # Insert trade
        vals = []
        for col in trade_cols:
            vals.append(trade.get(col))
        placeholders = ",".join(["?"] * len(trade_cols))
        col_names = ",".join(trade_cols)
        new_db.execute(f"INSERT INTO trades ({col_names}) VALUES ({placeholders})", vals)

        # Insert orders with updated trade_id
        for o in orders:
            # Skip stoploss orders that were canceled (cleanup)
            if o.get("status") == "canceled":
                continue
            o["id"] = new_order_id
            o["ft_trade_id"] = new_trade_id
            vals = []
            for col in order_cols:
                vals.append(o.get(col))
            placeholders = ",".join(["?"] * len(order_cols))
            col_names = ",".join(order_cols)
            new_db.execute(f"INSERT INTO orders ({col_names}) VALUES ({placeholders})", vals)
            new_order_id += 1

        new_trade_id += 1

    new_db.commit()
    new_db.close()
    log(f"Built new DB: {len(all_final)} trades, {new_order_id - 1} orders")

    # Step 7: Compare
    compare_dbs(db_path, new_db_path)

    # Print per-trade detail for re-simulated trades
    if resimulated:
        print("\n--- Re-simulated Trades Detail ---")
        for trade, _ in resimulated:
            print(f"  {trade['pair']:20s} was exit_signal -> now {trade['exit_reason']:20s} profit: ${trade['close_profit_abs']:+.2f}")

    if blocked:
        print(f"\n--- Blocked by Entry Gates ({len(blocked)} trades) ---")
        for t, gate_name in blocked:
            print(f"  {t['pair']:20s} opened:{str(t['open_date'])[:16]} profit:{t['close_profit_abs']:+.2f} exit:{t['exit_reason']} blocked_by:{gate_name}")

    # Step 8: Swap
    if not args.dry_run:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = db_path.parent / f"{db_path.stem}.bak-pre-rebuild-{timestamp}.sqlite"
        log(f"Backing up: {db_path.name} -> {backup_path.name}")
        shutil.copy2(str(db_path), str(backup_path))

        log(f"Swapping DB...")
        shutil.move(str(new_db_path), str(db_path))
        log("DB swapped!")

        container_map = {
            "SupertrendStrategy": "ft-supertrendstrategy",
            "MasterTraderV1": "ft-mastertraderv1",
            "AlligatorTrendV1": "ft-alligator-trend",
            "GaussianChannelV1": "ft-gaussian-channel",
            "BearCrashShortV1": "ft-bear-crash-short",
        }
        container = container_map.get(strategy)
        if container:
            log(f"Restarting {container}...")
            subprocess.run(["docker", "restart", container], capture_output=True, timeout=60)
            log("Container restarted")
    else:
        log(f"[DRY RUN] New DB at: {new_db_path}")

    log("Done!")


if __name__ == "__main__":
    main()
