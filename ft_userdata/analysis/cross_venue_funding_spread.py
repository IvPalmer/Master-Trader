#!/usr/bin/env python3
"""
Cross-venue funding rate spread analysis: Binance vs Hyperliquid.

Hypothesis (Kris Longmore, Feb 2026): the same carry signal profits on Binance
but loses on Hyperliquid because informed "exit-liquidity" sellers dominate the
DEX. The TRADABLE signal is the SPREAD between venues, not either level alone.

This script:
  1. Loads matched pairs from user_data/data/{binance,hyperliquid}/funding/.
  2. Resamples both to hourly forward-fill (HL is native hourly; Binance 8h
     forward-filled so we're holding the last settled rate in between).
  3. Computes spread = binance_funding - hyperliquid_funding.
  4. Per-pair stats: mean, stddev, %time beyond ±1σ, opposite-sign %.
  5. Naive spread backtest: when spread > +2σ, assume we harvest the full
     Binance-minus-Hyperliquid hourly carry differential for the next hour
     (proxy for long-spot-Binance + short-perp-Hyperliquid). Report P&L,
     Sharpe, drawdown.

Caveats:
  - Spot-hedging Binance carry with a Hyperliquid short is an APPROXIMATION;
    the real PnL includes funding on both legs + basis move. We model only the
    funding differential, which is the dominant slow-moving alpha component.
  - Backtest ignores fees, slippage, and borrow/financing on the Binance spot
    leg. This is a first-pass filter, not a tradable backtest.
  - Hyperliquid's mainnet perps history starts mid-2023; pre-June-2023 data is
    absent, so sample sizes vary per pair.

Outputs:
  CSV: docs/artifacts/cross_venue_funding_spread.csv
  Markdown snippets printed to stdout for the session report.
"""
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
BINANCE_DIR = ROOT / "user_data" / "data" / "binance" / "funding"
HL_DIR = ROOT / "user_data" / "data" / "hyperliquid" / "funding"
OUT_DIR = ROOT.parent / "docs" / "artifacts"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def log(msg):
    print(f"[spread] {msg}", flush=True)


def load_feather(path: Path) -> pd.DataFrame:
    df = pd.read_feather(path)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df.set_index("date").sort_index()


def load_matched_pairs() -> dict:
    """Return {pair: {'binance': df, 'hyperliquid': df}} for pairs present on both venues."""
    matched = {}
    for hl_file in sorted(HL_DIR.glob("*-funding.feather")):
        pair = hl_file.stem.replace("-funding", "")
        binance_file = BINANCE_DIR / f"{pair}-funding.feather"
        if not binance_file.exists():
            continue
        b_df = load_feather(binance_file)
        h_df = load_feather(hl_file)
        if b_df.empty or h_df.empty:
            continue
        matched[pair] = {"binance": b_df, "hyperliquid": h_df}
    return matched


def build_hourly_spread(b_df: pd.DataFrame, h_df: pd.DataFrame) -> pd.DataFrame:
    """
    Resample both series to a shared hourly timeline (intersection of coverage).
    - Binance 8h funding → hourly ffill (we hold the most-recent settled rate).
    - Hyperliquid is already hourly.
    Rates are per-interval. To compare apples-to-apples we convert BOTH to a
    per-hour annualizable rate:
        binance_hourly_equiv = binance_8h_rate / 8
        hyperliquid_hourly = raw (already hourly)
    """
    b_hourly_equiv = (b_df["funding_rate"] / 8.0).resample("1h").ffill()
    h_hourly = h_df["funding_rate"].resample("1h").ffill()

    start = max(b_hourly_equiv.index.min(), h_hourly.index.min())
    end = min(b_hourly_equiv.index.max(), h_hourly.index.max())
    if start >= end:
        return pd.DataFrame()
    idx = pd.date_range(start, end, freq="1h", tz="UTC")
    df = pd.DataFrame({
        "binance": b_hourly_equiv.reindex(idx).ffill(),
        "hyperliquid": h_hourly.reindex(idx).ffill(),
    }).dropna()
    df["spread"] = df["binance"] - df["hyperliquid"]
    return df


def per_pair_stats(pair: str, df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 24 * 30:
        return {"pair": pair, "n_hours": len(df), "coverage_days": len(df) / 24}
    mu = df["spread"].mean()
    sd = df["spread"].std()
    pct_above_1sd = float((df["spread"] > mu + sd).mean() * 100)
    pct_below_1sd = float((df["spread"] < mu - sd).mean() * 100)
    opposite_sign = float(
        ((df["binance"] > 0) & (df["hyperliquid"] < 0) |
         (df["binance"] < 0) & (df["hyperliquid"] > 0)).mean() * 100
    )
    return {
        "pair": pair,
        "n_hours": len(df),
        "coverage_days": len(df) / 24,
        "start": str(df.index.min().date()),
        "end": str(df.index.max().date()),
        "mean_spread": mu,
        "std_spread": sd,
        "binance_mean": df["binance"].mean(),
        "hl_mean": df["hyperliquid"].mean(),
        "pct_binance_premium_1sd": pct_above_1sd,
        "pct_hl_premium_1sd": pct_below_1sd,
        "pct_opposite_sign": opposite_sign,
    }


def naive_spread_backtest(pair_dfs: dict) -> dict:
    """
    For each pair, compute the per-hour pnl of a signal:
      - When spread_t > mean + 2*std (rolling 30d): enter long-Binance / short-HL.
        Hourly pnl = binance_hourly - hyperliquid_hourly   (what you earn + save)
        Sign note: you collect Binance funding if long spot and short perp on
        Binance — but here we proxy by using the FUNDING DIFFERENTIAL directly
        as a first-pass estimate.
      - Else: flat (pnl = 0).
    Aggregate across all pairs as equal-weight portfolio.
    """
    WINDOW = 24 * 30  # 30-day rolling
    portfolio_pnls = []
    pair_metrics = []
    for pair, df in pair_dfs.items():
        if len(df) < WINDOW * 2:
            continue
        mu = df["spread"].rolling(WINDOW).mean()
        sd = df["spread"].rolling(WINDOW).std()
        signal = (df["spread"] > mu + 2 * sd).astype(int)
        # pnl = signal * spread (hourly). Positive spread = we capture it.
        hourly_pnl = (signal.shift(1) * df["spread"]).fillna(0)
        total = hourly_pnl.sum()
        n_active = int(signal.sum())
        if n_active == 0:
            continue
        sharpe = float(hourly_pnl.mean() / (hourly_pnl.std() + 1e-12) *
                       math.sqrt(24 * 365))
        equity = hourly_pnl.cumsum()
        dd = float((equity - equity.cummax()).min())
        pair_metrics.append({
            "pair": pair,
            "n_active_hours": n_active,
            "pct_active": 100.0 * n_active / len(df),
            "total_return": float(total),
            "sharpe": sharpe,
            "max_dd": dd,
        })
        portfolio_pnls.append(hourly_pnl.rename(pair))

    if not portfolio_pnls:
        return {"per_pair": [], "portfolio": None}
    port = pd.concat(portfolio_pnls, axis=1).fillna(0).mean(axis=1)
    total = float(port.sum())
    sharpe = float(port.mean() / (port.std() + 1e-12) * math.sqrt(24 * 365))
    equity = port.cumsum()
    dd = float((equity - equity.cummax()).min())
    return {
        "per_pair": pair_metrics,
        "portfolio": {
            "n_pairs": len(portfolio_pnls),
            "n_hours": len(port),
            "total_return": total,
            "sharpe": sharpe,
            "max_dd": dd,
            "start": str(port.index.min().date()),
            "end": str(port.index.max().date()),
        },
    }


def main():
    log("Loading matched pairs...")
    matched = load_matched_pairs()
    log(f"  {len(matched)} pairs present on BOTH Binance and Hyperliquid")

    pair_dfs, stats = {}, []
    for pair, data in matched.items():
        df = build_hourly_spread(data["binance"], data["hyperliquid"])
        pair_dfs[pair] = df
        stats.append(per_pair_stats(pair, df))

    stats_df = pd.DataFrame(stats).sort_values(
        "mean_spread", key=lambda s: s.abs(), ascending=False, na_position="last"
    )
    out_csv = OUT_DIR / "cross_venue_funding_spread.csv"
    stats_df.to_csv(out_csv, index=False)
    log(f"  wrote {out_csv}")

    useful = stats_df.dropna(subset=["mean_spread"]).copy()
    log("")
    log(f"=== Top 10 pairs by |mean spread| (Binance - HL, per-hour units) ===")
    cols = ["pair", "n_hours", "mean_spread", "std_spread",
            "pct_binance_premium_1sd", "pct_hl_premium_1sd", "pct_opposite_sign"]
    print(useful.head(10)[cols].to_string(index=False, float_format="%.6f"))

    log("")
    log(f"=== Pairs with opposite funding sign ≥ 30% of the time ===")
    opp = useful[useful["pct_opposite_sign"] >= 30].sort_values(
        "pct_opposite_sign", ascending=False
    )
    if opp.empty:
        log("  none — Binance/HL funding rates move in lockstep most of the time")
    else:
        print(opp[["pair", "pct_opposite_sign", "mean_spread",
                   "binance_mean", "hl_mean", "n_hours"]]
              .to_string(index=False, float_format="%.6f"))

    log("")
    log("=== Naive spread backtest (signal: spread > mean+2σ, 30d rolling) ===")
    bt = naive_spread_backtest(pair_dfs)
    if bt["portfolio"]:
        p = bt["portfolio"]
        log(f"  Portfolio ({p['n_pairs']} pairs, {p['start']} → {p['end']}):")
        log(f"    total return (hourly-funding-diff units): {p['total_return']:.6f}")
        log(f"    Sharpe (ann):  {p['sharpe']:.2f}")
        log(f"    max drawdown: {p['max_dd']:.6f}")
    log("")
    log("Top-10 per-pair backtest (sorted by Sharpe):")
    per_pair_df = pd.DataFrame(bt["per_pair"]).sort_values("sharpe", ascending=False)
    if not per_pair_df.empty:
        print(per_pair_df.head(10).to_string(index=False, float_format="%.6f"))
        per_pair_df.to_csv(OUT_DIR / "cross_venue_funding_spread_backtest.csv",
                           index=False)


if __name__ == "__main__":
    main()
