"""
Extract MasterTraderV1 trades from Freqtrade backtest zip and save as parquet.

Input:  /Users/palmer/ft_userdata/user_data/backtest_results/backtest-result-2026-04-18_21-27-27.zip
Output: trades.parquet  (one row per MT entry with pair, open_date, profit_ratio, label)
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd

BT_ZIP = Path(
    "/Users/palmer/ft_userdata/user_data/backtest_results/backtest-result-2026-04-18_21-27-27.zip"
)
OUT = Path(__file__).parent / "trades.parquet"


def main() -> None:
    with zipfile.ZipFile(BT_ZIP) as z:
        jfile = [n for n in z.namelist() if n.endswith(".json") and "config" not in n][0]
        with z.open(jfile) as fh:
            data = json.load(fh)

    skey = [k for k in data["strategy"] if "Master" in k][0]
    trades = data["strategy"][skey]["trades"]
    df = pd.DataFrame(trades)

    df["open_date"] = pd.to_datetime(df["open_date"], utc=True)
    df["close_date"] = pd.to_datetime(df["close_date"], utc=True)
    df["label"] = (df["profit_ratio"] > 0).astype(int)

    keep = [
        "pair",
        "open_date",
        "close_date",
        "open_rate",
        "close_rate",
        "profit_ratio",
        "profit_abs",
        "trade_duration",
        "exit_reason",
        "label",
    ]
    df = df[keep].sort_values("open_date").reset_index(drop=True)

    print(f"Total trades: {len(df)}")
    print(f"Win rate: {df['label'].mean():.3f}")
    print(f"Date range: {df['open_date'].min()} -> {df['open_date'].max()}")
    print(f"Pairs: {df['pair'].nunique()}")
    print(f"Mean profit_ratio: {df['profit_ratio'].mean():.4f}")
    print(f"Total profit_abs: {df['profit_abs'].sum():.2f}")

    df.to_parquet(OUT, index=False)
    print(f"Saved {len(df)} rows -> {OUT}")


if __name__ == "__main__":
    main()
