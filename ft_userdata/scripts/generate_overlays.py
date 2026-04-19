#!/usr/bin/env python3
"""
generate_overlays.py — Build expected-equity CSVs for the Grafana dashboard
overlay from Freqtrade backtest zip exports.

For each active bot, walks closed trades in chronological order and produces
a step-function equity curve starting from the initial wallet. The curves
answer the "what if these bots had been live since day 1 of the backtest?"
question.

Usage:
    python3 scripts/generate_overlays.py

Reads SOURCES below; writes CSVs into ft_userdata/grafana/overlays/.
grafana-bridge serves them at http://grafana-bridge:5555/overlay/<file>.
"""

import csv
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "grafana" / "overlays"
BACKTESTS = BASE / "user_data" / "backtest_results"

SOURCES = [
    {
        "strategy": "KeltnerBounceV1",
        "zip": BACKTESTS / "backtest-result-2026-04-17_00-35-38.zip",
        "initial_wallet": 200.0,
    },
    {
        "strategy": "FundingFadeV1",
        "zip": BACKTESTS / "backtest-result-2026-04-19_00-05-21.zip",
        "initial_wallet": 200.0,
    },
]


def load_trades(zip_path: Path) -> list:
    with zipfile.ZipFile(zip_path) as z:
        main = next(
            n for n in z.namelist()
            if n.endswith(".json") and "config" not in n and "meta" not in n
        )
        data = json.loads(z.read(main))
    strategies = list(data["strategy"].values())
    return strategies[0]["trades"]


def build_curve(trades: list, initial: float) -> list:
    closed = [t for t in trades if not t["is_open"]]
    if not closed:
        return []
    first_open_sec = min(t["open_timestamp"] / 1000 for t in closed)
    ordered = sorted(closed, key=lambda t: t["close_timestamp"])
    points = [(first_open_sec - 86400, initial)]
    eq = initial
    for t in ordered:
        eq += t["profit_abs"]
        points.append((t["close_timestamp"] / 1000, eq))
    points.append((datetime.now(timezone.utc).timestamp(), eq))
    return points


def write_csv(path: Path, curve: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_ms", "equity"])
        for ts, eq in curve:
            w.writerow([int(ts * 1000), round(eq, 4)])


def main():
    all_events = []
    portfolio_initial = 0.0

    for src in SOURCES:
        trades = load_trades(src["zip"])
        curve = build_curve(trades, src["initial_wallet"])
        csv_path = OUT / f"expected_{src['strategy']}.csv"
        write_csv(csv_path, curve)
        print(f"  {src['strategy']}: {len(curve)} points → {csv_path.name}  "
              f"(final ${curve[-1][1]:.2f})")
        portfolio_initial += src["initial_wallet"]
        for t in trades:
            if not t["is_open"]:
                all_events.append((t["close_timestamp"] / 1000, t["profit_abs"]))

    # Combined portfolio curve
    first_open_sec = min(
        t["open_timestamp"] / 1000
        for src in SOURCES
        for t in load_trades(src["zip"])
        if not t["is_open"]
    )
    all_events.sort()
    portfolio = [(first_open_sec - 86400, portfolio_initial)]
    eq = portfolio_initial
    for ts, p in all_events:
        eq += p
        portfolio.append((ts, eq))
    portfolio.append((datetime.now(timezone.utc).timestamp(), eq))
    write_csv(OUT / "expected_portfolio.csv", portfolio)
    print(f"  portfolio: {len(portfolio)} points → expected_portfolio.csv  "
          f"(final ${portfolio[-1][1]:.2f})")


if __name__ == "__main__":
    main()
