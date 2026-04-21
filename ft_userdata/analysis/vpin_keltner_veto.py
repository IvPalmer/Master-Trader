"""
VPIN veto analysis on KeltnerBounceV1 backtest trades.

Loads the most recent Keltner backtest (zip with per-trade records),
looks up the VPIN value at each trade's entry timestamp (strictly past-
computable via the minute-level mapping from vpin_pipeline.py), and:

  Part 2: Quintile partition — PF, WR, avg P/L per VPIN quintile.
  Part 3: Retrospective veto — re-simulate profit ignoring trades whose entry
          VPIN exceeds each candidate threshold. Report total profit, PF, DD,
          Sharpe, trade count for each threshold.
  Part 4: Walk-forward robustness — 6 equal halves (halves => 6 windows), does
          the best-threshold veto improve each half?
          Also applies an out-of-sample test: choose threshold on first half,
          evaluate on second half.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd


BACKTEST_ZIP = Path(
    "/Users/palmer/Work/Dev/master-trader/ft_userdata/user_data/backtest_results/"
    "backtest-result-2026-04-20_22-46-25.zip"
)
CACHE_DIR = Path("/Users/palmer/Work/Dev/master-trader/ft_userdata/analysis/vpin_cache")


def load_trades() -> pd.DataFrame:
    with zipfile.ZipFile(BACKTEST_ZIP) as zf:
        json_name = [n for n in zf.namelist() if n.endswith(".json") and "config" not in n][0]
        with zf.open(json_name) as fh:
            data = json.load(fh)
    trades = data["strategy"]["KeltnerBounceV1"]["trades"]
    df = pd.DataFrame(trades)
    df["open_date"] = pd.to_datetime(df["open_date"], utc=True)
    df["close_date"] = pd.to_datetime(df["close_date"], utc=True)
    df["symbol"] = df["pair"].str.replace("/USDT", "", regex=False)
    return df


def attach_vpin(trades: pd.DataFrame) -> pd.DataFrame:
    out = []
    for sym, grp in trades.groupby("symbol"):
        path = CACHE_DIR / f"{sym}_vpin_minute.parquet"
        if not path.exists():
            print(f"WARN: no VPIN for {sym}, skipping {len(grp)} trades")
            continue
        vpin_min = pd.read_parquet(path).sort_values("date")
        vpin_min["date"] = pd.to_datetime(vpin_min["date"], utc=True).astype("datetime64[ns, UTC]")
        g = grp.sort_values("open_date")
        left = g[["open_date"]].rename(columns={"open_date": "date"}).copy()
        left["date"] = left["date"].astype("datetime64[ns, UTC]")
        merged = pd.merge_asof(
            left,
            vpin_min,
            on="date",
            direction="backward",
        )
        g = g.reset_index(drop=True)
        g["vpin_entry"] = merged["vpin"].values
        out.append(g)
    res = pd.concat(out, ignore_index=True)
    return res


def compute_stats(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"n": 0, "profit_total_ratio": 0.0, "profit_abs": 0.0, "pf": float("nan"),
                "wr": float("nan"), "mean_profit_ratio": float("nan"), "sharpe": float("nan"),
                "sortino": float("nan"), "max_dd": float("nan")}
    profits_abs = trades["profit_abs"].to_numpy()
    profits_ratio = trades["profit_ratio"].to_numpy()

    wins = profits_abs[profits_abs > 0].sum()
    losses = -profits_abs[profits_abs < 0].sum()
    pf = wins / losses if losses > 0 else float("inf")
    wr = (profits_abs > 0).mean()

    # Equity curve (chronological) for drawdown + Sharpe
    ch = trades.sort_values("close_date").reset_index(drop=True)
    eq = ch["profit_abs"].cumsum().to_numpy()
    # Drawdown against running peak (starting balance = initial stake baseline implicit)
    peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))
    dd_abs = peak[1:] - eq
    max_dd_abs = float(dd_abs.max()) if len(dd_abs) else 0.0

    # Sharpe/Sortino on per-trade profit_ratio
    pr_mean = profits_ratio.mean()
    pr_std = profits_ratio.std(ddof=1) if len(profits_ratio) > 1 else float("nan")
    neg = profits_ratio[profits_ratio < 0]
    downside = neg.std(ddof=1) if len(neg) > 1 else float("nan")
    sharpe = pr_mean / pr_std * np.sqrt(len(profits_ratio)) if pr_std and pr_std > 0 else float("nan")
    sortino = pr_mean / downside * np.sqrt(len(profits_ratio)) if downside and downside > 0 else float("nan")

    return {
        "n": int(len(trades)),
        "profit_total_ratio": float(profits_ratio.sum()),
        "profit_abs": float(profits_abs.sum()),
        "pf": float(pf),
        "wr": float(wr),
        "mean_profit_ratio": float(pr_mean),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "max_dd_abs": max_dd_abs,
    }


def quintile_analysis(trades: pd.DataFrame) -> pd.DataFrame:
    t = trades.dropna(subset=["vpin_entry"]).copy()
    t["quintile"] = pd.qcut(t["vpin_entry"], 5, labels=["Q1 low", "Q2", "Q3", "Q4", "Q5 high"])
    rows = []
    for q, grp in t.groupby("quintile"):
        stats = compute_stats(grp)
        stats["quintile"] = q
        stats["vpin_min"] = float(grp["vpin_entry"].min())
        stats["vpin_max"] = float(grp["vpin_entry"].max())
        rows.append(stats)
    df = pd.DataFrame(rows).sort_values("quintile")
    return df


def veto_sweep(trades: pd.DataFrame, percentile_thresholds=(0.90, 0.80, 0.70, 0.60, 0.50)) -> pd.DataFrame:
    """Try veto on trades whose entry VPIN is above percentile threshold,
    AND the inverted case (veto trades BELOW a bottom threshold)."""
    t = trades.dropna(subset=["vpin_entry"]).copy()
    baseline = compute_stats(t)
    rows = [{"threshold": "NONE (baseline)", "pct_of_universe": 1.0, "vpin_cutoff": float("nan"), **baseline}]
    # Top-veto (hypothesis)
    for pct in percentile_thresholds:
        cutoff = float(np.quantile(t["vpin_entry"], pct))
        kept = t[t["vpin_entry"] <= cutoff]
        s = compute_stats(kept)
        rows.append({"threshold": f"veto top {int((1-pct)*100)}%",
                     "pct_of_universe": float(len(kept) / len(t)),
                     "vpin_cutoff": cutoff, **s})
    # Bottom-veto (inverted based on quintile finding)
    for pct in (0.10, 0.20, 0.30, 0.40, 0.50):
        cutoff = float(np.quantile(t["vpin_entry"], pct))
        kept = t[t["vpin_entry"] >= cutoff]
        s = compute_stats(kept)
        rows.append({"threshold": f"veto bottom {int(pct*100)}%",
                     "pct_of_universe": float(len(kept) / len(t)),
                     "vpin_cutoff": cutoff, **s})
    return pd.DataFrame(rows)


def walk_forward(trades: pd.DataFrame, n_windows: int = 6, mode: str = "top") -> pd.DataFrame:
    """Split by chronological entry date into n_windows equal-trade halves.
    mode='top' -> veto trades with vpin > 80th pctile (original hypothesis).
    mode='bottom' -> veto trades with vpin < 20th pctile (inverted hypothesis).
    Cutoff is computed from the WHOLE sample (honest OOS would use rolling,
    but with only 169 trades we do not have the density).
    """
    t = trades.dropna(subset=["vpin_entry"]).copy().sort_values("open_date").reset_index(drop=True)
    if mode == "top":
        cutoff = float(np.quantile(t["vpin_entry"], 0.80))
        keep_fn = lambda df: df[df["vpin_entry"] <= cutoff]
    else:
        cutoff = float(np.quantile(t["vpin_entry"], 0.20))
        keep_fn = lambda df: df[df["vpin_entry"] >= cutoff]

    bounds = np.linspace(0, len(t), n_windows + 1).astype(int)
    rows = []
    for i in range(n_windows):
        win = t.iloc[bounds[i]:bounds[i+1]]
        if win.empty:
            continue
        base = compute_stats(win)
        veto_win = compute_stats(keep_fn(win))
        rows.append({
            "window": i + 1,
            "mode": mode,
            "cutoff": cutoff,
            "start": win["open_date"].min(),
            "end": win["open_date"].max(),
            "n": base["n"],
            "base_profit_ratio": base["profit_total_ratio"],
            "base_pf": base["pf"],
            "veto_profit_ratio": veto_win["profit_total_ratio"],
            "veto_pf": veto_win["pf"],
            "veto_n": veto_win["n"],
            "improvement_abs": veto_win["profit_abs"] - base["profit_abs"],
        })
    return pd.DataFrame(rows)


def oos_test(trades: pd.DataFrame, mode: str = "top") -> dict:
    """Pick VPIN cutoff on first half (find best percentile), apply to second half.
    mode='top' - keep trades below cutoff (veto high VPIN).
    mode='bottom' - keep trades above cutoff (veto low VPIN).
    """
    t = trades.dropna(subset=["vpin_entry"]).copy().sort_values("open_date").reset_index(drop=True)
    mid = len(t) // 2
    train = t.iloc[:mid]
    test = t.iloc[mid:]

    best_pct, best_profit, best_cutoff = None, -np.inf, None
    if mode == "top":
        pcts = [min(p, 1.0) for p in np.arange(0.50, 1.001, 0.05)]
        keep_fn_factory = lambda c: (lambda df: df[df["vpin_entry"] <= c])
    else:
        pcts = [max(0.0, p) for p in np.arange(0.00, 0.501, 0.05)]
        keep_fn_factory = lambda c: (lambda df: df[df["vpin_entry"] >= c])

    for pct in pcts:
        cutoff = float(np.quantile(train["vpin_entry"], pct))
        kept = keep_fn_factory(cutoff)(train)
        profit = kept["profit_abs"].sum()
        if profit > best_profit:
            best_profit = profit
            best_pct = float(pct)
            best_cutoff = cutoff

    keep_fn = keep_fn_factory(best_cutoff)
    base_test = compute_stats(test)
    veto_test = compute_stats(keep_fn(test))
    return {
        "mode": mode,
        "best_pct_on_train": best_pct,
        "cutoff_from_train": best_cutoff,
        "train_baseline": compute_stats(train),
        "train_veto": compute_stats(keep_fn(train)),
        "test_baseline": base_test,
        "test_veto": veto_test,
        "test_improvement_abs": veto_test["profit_abs"] - base_test["profit_abs"],
    }


def main():
    trades = load_trades()
    print(f"Loaded {len(trades)} trades from {BACKTEST_ZIP.name}")
    t2 = attach_vpin(trades)
    print(f"Attached VPIN for {t2['vpin_entry'].notna().sum()}/{len(t2)} trades")

    print("\n=== Baseline ===")
    base = compute_stats(t2)
    for k, v in base.items():
        print(f"  {k}: {v}")

    print("\n=== Quintile analysis ===")
    q = quintile_analysis(t2)
    print(q.to_string(index=False))

    print("\n=== Veto threshold sweep ===")
    sweep = veto_sweep(t2)
    print(sweep.to_string(index=False))

    print("\n=== Walk-forward TOP mode (veto high VPIN, global 80th pctile) ===")
    wf_top = walk_forward(t2, n_windows=6, mode="top")
    print(wf_top.to_string(index=False))

    print("\n=== Walk-forward BOTTOM mode (veto low VPIN, global 20th pctile) ===")
    wf_bot = walk_forward(t2, n_windows=6, mode="bottom")
    print(wf_bot.to_string(index=False))

    print("\n=== OOS top-mode (train first half, test second) ===")
    oos_top = oos_test(t2, mode="top")
    print(json.dumps(oos_top, indent=2, default=str))

    print("\n=== OOS bottom-mode (train first half, test second) ===")
    oos_bot = oos_test(t2, mode="bottom")
    print(json.dumps(oos_bot, indent=2, default=str))

    # Save artifacts
    out = Path("/Users/palmer/Work/Dev/master-trader/ft_userdata/analysis/vpin_keltner_results")
    out.mkdir(exist_ok=True)
    t2.to_parquet(out / "trades_with_vpin.parquet", index=False)
    q.to_csv(out / "quintile.csv", index=False)
    sweep.to_csv(out / "veto_sweep.csv", index=False)
    wf_top.to_csv(out / "walk_forward_top.csv", index=False)
    wf_bot.to_csv(out / "walk_forward_bottom.csv", index=False)
    with open(out / "oos.json", "w") as fh:
        json.dump({"top": oos_top, "bottom": oos_bot}, fh, indent=2, default=str)
    print(f"\nArtifacts written to {out}")


if __name__ == "__main__":
    main()
