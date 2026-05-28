#!/usr/bin/env bash
# Price-verified backtest for the Killers VIP copy-trader.
#
# Unlike ft_userdata/insiders_bridge/killers_analyzer.py (which TRUSTS the
# signaler's self-reported "X% Profit" lines), this harness replays each
# signal's entry / TP-ladder / SL against REAL Binance USDT-M futures candles
# and computes what a follower would actually have realized.
#
# Result (run 2026-05-28, 650/674 signals, 173/178 coins, 2024-04..2026-05):
#   - channel self-report:        +2306% / 98% win   (fiction)
#   - real prices, ladder exit:   -$1536 / 30.6% win / -0.220 R/trade
#   - real prices, best exit:     -$227  / 81.7% win / -0.065 R/trade (still <0)
#   - price reaches only 3.3 of 8.3 published targets on avg; 6% full ladder
#   Verdict: no exit/entry/sizing makes it profitable. Edge is ~0, fees negative.
#
# Runs on the VPS (data + Binance access live there). To point at a DIFFERENT
# channel's corpus, edit the path constants at the top of kbt_extract.py
# (BASE = the classifications+messages dir) and the shared work DIR in each
# script. Pipeline writes everything under that work dir.
#
# Pipeline (run in order):
set -euo pipefail
cd "$(dirname "$0")"

echo "[1/4] extract trade specs from corpus -> trades.jsonl"
python3 kbt_extract.py

echo "[2/4] download Binance futures 15m OHLCV for the coin universe -> ohlcv/"
python3 kbt_download.py

echo "[3/4] scenario matrix (laddered exits, breakeven variants)"
python3 kbt_sim.py

echo "[4/4] exit-policy x entry-mode sweep + TP-ladder fill decay"
python3 kbt_exits.py
python3 kbt_depth.py
