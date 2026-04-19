"""
Grafana Bridge for Freqtrade Bots
Auto-generates a dashboard: one chart per traded pair per bot,
with entry/exit markers embedded in candle data.
"""

import json
import logging
import os
import threading
import time as time_mod
from datetime import datetime, timezone
from collections import defaultdict

import requests
from flask import Flask, Response, jsonify, request, send_from_directory

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BOTS = {
    "KeltnerBounceV1": {"url": "http://keltnerbouncev1:8080", "timeframe": "1h"},
    "FundingFadeV1": {"url": "http://fundingfadev1:8080", "timeframe": "1h"},
}

OVERLAYS_DIR = "/overlays"

API_AUTH = ("freqtrader", "mastertrader")
TIMEOUT = 15
DASHBOARD_PATH = "/dashboards/candlestick-charts.json"


def _fetch(bot_name, path, params=None):
    bot = BOTS.get(bot_name)
    if not bot:
        return None
    try:
        r = requests.get(f"{bot['url']}/api/v1/{path}",
                         auth=API_AUTH, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        logger.warning("%s/%s: %s", bot_name, path, e)
        return None


def _epoch(iso):
    if not iso:
        return 0
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (ValueError, AttributeError):
        return 0


def _get_whitelist(bot_name):
    """Get the bot's current whitelist of pairs it can serve candles for."""
    data = _fetch(bot_name, "whitelist")
    if data:
        return set(data.get("whitelist", []))
    return set()


# ── Candle Proxy with embedded markers ─────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/candles/<bot_name>")
def get_candles(bot_name):
    """Return candle data with optional trade markers embedded."""
    if bot_name not in BOTS:
        return jsonify([])
    pair = request.args.get("pair", "BTC/USDT")
    tf = request.args.get("timeframe", BOTS[bot_name]["timeframe"])
    limit = request.args.get("limit", "500")
    include_markers = request.args.get("markers", "false") == "true"

    data = _fetch(bot_name, "pair_candles",
                  {"pair": pair, "timeframe": tf, "limit": limit})
    if not data:
        return jsonify([])

    cols = data.get("columns", [])
    rows = data.get("data", [])
    ci = {c: i for i, c in enumerate(cols)}
    need = ("date", "open", "high", "low", "close", "volume")
    if not all(k in ci for k in need):
        return jsonify([])

    # Build candle list
    candles = []
    for row in rows:
        try:
            t = row[ci["date"]]
            if isinstance(t, str):
                t = _epoch(t)
            elif isinstance(t, (int, float)):
                t = int(t / 1000) if t > 1e12 else int(t)
            candles.append({
                "time": t,
                "open": float(row[ci["open"]]),
                "high": float(row[ci["high"]]),
                "low": float(row[ci["low"]]),
                "close": float(row[ci["close"]]),
            })
        except (IndexError, ValueError, TypeError):
            continue

    if not include_markers or not candles:
        return jsonify(candles)

    # Get trade markers for this pair
    markers = _get_markers_for_pair(bot_name, pair)
    if not markers:
        return jsonify(candles)

    # Determine candle interval to snap markers to nearest candle
    if len(candles) >= 2:
        interval = candles[1]["time"] - candles[0]["time"]
    else:
        interval = 300  # default 5m

    # Build time index for candles
    candle_times = {c["time"]: c for c in candles}

    for m in markers:
        mt = m["time"]
        # Snap to nearest candle time
        snapped = round(mt / interval) * interval
        # Find closest candle within 2 intervals
        candle = candle_times.get(snapped)
        if not candle:
            for offset in [-interval, interval, -2*interval, 2*interval]:
                candle = candle_times.get(snapped + offset)
                if candle:
                    break
        if candle:
            candle[m["field"]] = m["price"]

    return jsonify(candles)


def _get_markers_for_pair(bot_name, pair):
    """Get entry/exit markers for a specific pair."""
    markers = []

    # Open trades
    open_trades = _fetch(bot_name, "status") or []
    for t in open_trades:
        if t.get("pair") == pair:
            markers.append({
                "time": _epoch(t.get("open_date")),
                "price": float(t.get("open_rate", 0) or 0),
                "field": "BUY",
            })

    # Closed trades
    data = _fetch(bot_name, "trades", {"limit": "50"})
    for t in (data or {}).get("trades", []):
        if t.get("pair") != pair or t.get("is_open"):
            continue
        profit = float(t.get("profit_pct", 0) or 0)
        markers.append({
            "time": _epoch(t.get("open_date")),
            "price": float(t.get("open_rate", 0) or 0),
            "field": "BUY",
        })
        close_rate = t.get("close_rate")
        if close_rate and float(close_rate) > 0:
            markers.append({
                "time": _epoch(t.get("close_date")),
                "price": float(close_rate),
                "field": "WIN" if profit >= 0 else "LOSS",
            })

    return markers


# ── Dashboard Generator ───────────────────────────────────────────

def _has_candles(bot_name, pair):
    """Check if the bot can actually serve candle data for this pair."""
    tf = BOTS[bot_name]["timeframe"]
    data = _fetch(bot_name, "pair_candles",
                  {"pair": pair, "timeframe": tf, "limit": "1"})
    return data is not None and len(data.get("data", [])) > 0


def _get_bot_trade_pairs(bot_name):
    """Get traded pairs, split into open and closed, filtered by candle availability."""
    open_trades = _fetch(bot_name, "status") or []
    trade_data = _fetch(bot_name, "trades", {"limit": "50"})
    closed_trades = [t for t in (trade_data or {}).get("trades", []) if not t.get("is_open")]

    # Cache candle checks to avoid repeated API calls
    candle_cache = {}
    def can_serve(pair):
        if pair not in candle_cache:
            candle_cache[pair] = _has_candles(bot_name, pair)
        return candle_cache[pair]

    open_pairs = {}
    for t in open_trades:
        p = t.get("pair", "")
        if can_serve(p):
            open_pairs[p] = t

    closed_pairs = set()
    for t in closed_trades:
        p = t.get("pair", "")
        if p not in open_pairs and can_serve(p):
            closed_pairs.add(p)

    return open_pairs, closed_pairs


def _panel(pid, title, bot_name, pair, tf, x, y, w, h):
    """Candlestick panel with embedded markers."""
    return {
        "id": pid,
        "title": title,
        "type": "candlestick",
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": {"type": "yesoreyeram-infinity-datasource", "uid": "infinity"},
        "fieldConfig": {
            "defaults": {"custom": {}},
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "BUY"},
                    "properties": [
                        {"id": "custom.drawStyle", "value": "points"},
                        {"id": "custom.pointSize", "value": 14},
                        {"id": "color", "value": {"mode": "fixed", "fixedColor": "#FADE2A"}},
                        {"id": "custom.showPoints", "value": "always"},
                    ]
                },
                {
                    "matcher": {"id": "byName", "options": "WIN"},
                    "properties": [
                        {"id": "custom.drawStyle", "value": "points"},
                        {"id": "custom.pointSize", "value": 14},
                        {"id": "color", "value": {"mode": "fixed", "fixedColor": "#73BF69"}},
                        {"id": "custom.showPoints", "value": "always"},
                    ]
                },
                {
                    "matcher": {"id": "byName", "options": "LOSS"},
                    "properties": [
                        {"id": "custom.drawStyle", "value": "points"},
                        {"id": "custom.pointSize", "value": 14},
                        {"id": "color", "value": {"mode": "fixed", "fixedColor": "#F2495C"}},
                        {"id": "custom.showPoints", "value": "always"},
                    ]
                },
            ],
        },
        "options": {
            "mode": "candles",
            "candleStyle": "candles",
            "colorStrategy": "open-close",
            "colors": {
                "up": "rgba(0, 200, 83, 0.8)",
                "down": "rgba(255, 82, 82, 0.8)",
                "flat": "rgba(158, 158, 158, 0.8)"
            },
            "includeAllFields": True,
        },
        "targets": [{
            "refId": "A",
            "datasource": {"type": "yesoreyeram-infinity-datasource", "uid": "infinity"},
            "type": "json",
            "source": "url",
            "url": f"http://grafana-bridge:5555/candles/{bot_name}?pair={pair}&timeframe={tf}&limit=2000&markers=true",
            "url_options": {"method": "GET"},
            "format": "table",
            "root_selector": "",
            "columns": [
                {"selector": "time", "text": "time", "type": "timestamp_epoch_s"},
                {"selector": "open", "text": "open", "type": "number"},
                {"selector": "high", "text": "high", "type": "number"},
                {"selector": "low", "text": "low", "type": "number"},
                {"selector": "close", "text": "close", "type": "number"},
                {"selector": "BUY", "text": "BUY", "type": "number"},
                {"selector": "WIN", "text": "WIN", "type": "number"},
                {"selector": "LOSS", "text": "LOSS", "type": "number"},
            ]
        }],
    }


def generate_dashboard():
    panels = []
    y = 0
    pid = 1

    for bot_name, config in BOTS.items():
        tf = config["timeframe"]
        open_pairs, closed_pairs = _get_bot_trade_pairs(bot_name)

        # If no trades at all, show top whitelist pairs so the bot is visible
        watching_pairs = []
        if not open_pairs and not closed_pairs:
            whitelist = _get_whitelist(bot_name)
            # Show top 3 whitelist pairs as "watching" charts
            watching_pairs = sorted(whitelist)[:3]
            if not watching_pairs:
                continue

        n_open = len(open_pairs)
        n_closed = len(closed_pairs)

        # ── Open trades row ──
        if open_pairs:
            header = f"{bot_name}  \u2014  {n_open} open  [{tf}]"

            # Collapse when filter is "Closed"
            panels.append({
                "type": "row",
                "title": header,
                "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
                "collapsed": False,
                "id": pid,
                "panels": [],
                "repeat": None,
            })
            pid += 1
            y += 1

            i = 0
            for pair, trade in open_pairs.items():
                title = f"\u25cf {pair}"
                w = 24 if n_open == 1 else 12
                h = 12 if n_open == 1 else 10
                x = (i % 2) * 12 if n_open > 1 else 0
                if i > 0 and i % 2 == 0:
                    y += 10
                panels.append(_panel(pid, title, bot_name, pair, tf, x, y, w, h))
                pid += 1
                i += 1
            y += (12 if n_open == 1 else 10)

        # ── Closed trades row (separate, collapsed by default) ──
        if closed_pairs:
            header = f"{bot_name}  \u2014  {n_closed} closed  [{tf}]"
            closed_panels_list = []

            # Build closed panels with relative positioning (for collapsed row)
            ci = 0
            cy = 0
            for pair in sorted(closed_pairs):
                title = f"{pair}  (closed)"
                cx = (ci % 2) * 12
                if ci > 0 and ci % 2 == 0:
                    cy += 8
                closed_panels_list.append(
                    _panel(pid, title, bot_name, pair, tf, cx, cy, 12, 8))
                pid += 1
                ci += 1

            panels.append({
                "type": "row",
                "title": header,
                "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
                "collapsed": True,
                "id": pid,
                "panels": closed_panels_list,
            })
            pid += 1
            y += 1

        # ── Watching row (bots with no trades yet) ──
        if watching_pairs:
            header = f"{bot_name}  \u2014  watching {len(watching_pairs)} pairs  [{tf}]"
            panels.append({
                "type": "row",
                "title": header,
                "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
                "collapsed": False,
                "id": pid,
                "panels": [],
                "repeat": None,
            })
            pid += 1
            y += 1

            for wi, pair in enumerate(watching_pairs):
                title = f"\u25cb {pair}  (no trades)"
                w = 24 if len(watching_pairs) == 1 else 12
                h = 10
                x = (wi % 2) * 12 if len(watching_pairs) > 1 else 0
                if wi > 0 and wi % 2 == 0:
                    y += 10
                panels.append(_panel(pid, title, bot_name, pair, tf, x, y, w, h))
                pid += 1
            y += 10

        y += 1  # spacer

    # Filter variable
    filter_var = {
        "current": {"selected": True, "text": "Open", "value": "Open"},
        "name": "filter",
        "label": "Show Trades",
        "type": "custom",
        "query": "Open,Closed,All",
        "options": [
            {"text": "Open", "value": "Open", "selected": True},
            {"text": "Closed", "value": "Closed", "selected": False},
            {"text": "All", "value": "All", "selected": False},
        ],
        "includeAll": False,
        "multi": False,
        "description": "Filter which trade charts to display. Expand/collapse rows to show or hide sections."
    }

    return {
        "uid": "ft-candlesticks",
        "title": "Freqtrade Live Trades",
        "tags": ["freqtrade", "trading", "live"],
        "timezone": "browser",
        "editable": True,
        "graphTooltip": 1,
        "refresh": "",
        "liveNow": True,
        "schemaVersion": 39,
        "templating": {"list": [filter_var]},
        "time": {"from": "now-7d", "to": "now"},
        "timepicker": {"refresh_intervals": ["1m", "5m", "15m"]},
        "panels": panels,
        "annotations": {"list": []},
        "links": [],
    }


def _get_current_filter():
    """Read the current filter variable value from Grafana."""
    try:
        r = requests.get(
            "http://grafana:3000/api/dashboards/uid/ft-candlesticks",
            timeout=5)
        if r.status_code == 200:
            dash = r.json().get("dashboard", {})
            for v in dash.get("templating", {}).get("list", []):
                if v.get("name") == "filter":
                    return v.get("current", {}).get("text", "Open")
    except Exception:
        pass
    return "Open"


def write_dashboard():
    try:
        current_filter = _get_current_filter()
        d = generate_dashboard()

        # Apply filter: control row collapse state
        for p in d["panels"]:
            if p.get("type") != "row":
                continue
            title = p.get("title", "")
            is_open_row = "open" in title and "closed" not in title
            is_closed_row = "closed" in title

            if current_filter == "Open":
                if is_closed_row:
                    p["collapsed"] = True
                elif is_open_row:
                    p["collapsed"] = False
            elif current_filter == "Closed":
                if is_open_row:
                    p["collapsed"] = True
                elif is_closed_row:
                    p["collapsed"] = False
            else:  # All
                p["collapsed"] = False

            # Preserve the selected filter value
            for v in d.get("templating", {}).get("list", []):
                if v.get("name") == "filter":
                    v["current"] = {"selected": True, "text": current_filter, "value": current_filter}
                    for opt in v.get("options", []):
                        opt["selected"] = (opt["text"] == current_filter)

        new_json = json.dumps(d, indent=2)

        # Only write if content changed to avoid Grafana reload flicker
        try:
            with open(DASHBOARD_PATH, "r") as f:
                old_json = f.read()
        except FileNotFoundError:
            old_json = ""

        if new_json != old_json:
            with open(DASHBOARD_PATH, "w") as f:
                f.write(new_json)
            logger.info("Dashboard updated: %d panels (filter=%s)", len(d["panels"]), current_filter)
        else:
            logger.debug("Dashboard unchanged, skipping write")
    except Exception as e:
        logger.error("Dashboard gen failed: %s", e)


def _loop():
    time_mod.sleep(10)
    while True:
        write_dashboard()
        time_mod.sleep(60)


@app.route("/refresh_dashboard", methods=["GET", "POST"])
def refresh():
    write_dashboard()
    return jsonify({"status": "ok"})


@app.route("/overlay/<path:name>")
def overlay(name):
    """Serve static equity-curve CSVs for Grafana's Infinity datasource.

    Files live in /overlays (bind-mounted from ft_userdata/grafana/overlays).
    Produced by scripts/generate_overlays.py from backtest zip exports.
    """
    if ".." in name or name.startswith("/"):
        return "", 400
    path = os.path.join(OVERLAYS_DIR, name)
    if not os.path.isfile(path):
        return "", 404
    return send_from_directory(OVERLAYS_DIR, name, mimetype="text/csv")


threading.Thread(target=_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5555, debug=False)
