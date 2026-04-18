"""
Sanity check: can we identify WHICH regime MT wins in, and how often does it occur?

Group trades by quarter and report PF. Then check which BTC-regime features
best separate winning-quarter trades from losing-quarter trades.
"""
from pathlib import Path
import pandas as pd
import numpy as np

DIR = Path(__file__).parent

def pf(r):
    g = r[r > 0].sum(); l = -r[r < 0].sum()
    return float("inf") if l == 0 else g / l

def main():
    df = pd.read_parquet(DIR/"features.parquet")
    df["quarter"] = df["open_date"].dt.to_period("Q")
    q = df.groupby("quarter").agg(
        n=("label", "size"),
        win_rate=("label", "mean"),
        pf=("profit_ratio", pf),
        mean_ret=("profit_ratio", "mean"),
    )
    print("\n=== Quarterly MT performance ===")
    print(q.to_string())

    # Mark quarters as winning (PF>1.1) vs losing
    win_q = q[q["pf"] > 1.1].index.tolist()
    print(f"\nWinning quarters (PF>1.1): {win_q}")
    print(f"Losing quarters: {len(q) - len(win_q)} / {len(q)}")

    # Split by whether trade occurred in winning quarter
    df["in_win_q"] = df["quarter"].isin(win_q).astype(int)

    feat_cols = [c for c in df.columns if c not in ("pair","open_date","label","profit_ratio","quarter","in_win_q")]
    print(f"\n=== Feature differences: winning-quarter trades vs losing-quarter trades ===")
    summary = []
    for c in feat_cols:
        a = df.loc[df.in_win_q==1, c]; b = df.loc[df.in_win_q==0, c]
        if len(a) < 5 or len(b) < 5: continue
        summary.append({
            "feature": c,
            "mean_win_q": a.mean(), "mean_lose_q": b.mean(),
            "std_pooled": df[c].std(),
            "zdiff": (a.mean()-b.mean()) / (df[c].std() + 1e-9),
        })
    s = pd.DataFrame(summary).sort_values("zdiff", key=lambda x: x.abs(), ascending=False)
    print(s.to_string(index=False))

if __name__ == "__main__":
    main()
