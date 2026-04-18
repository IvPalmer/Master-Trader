"""
Robustness check — try alternative configurations that might salvage meta-labeling:

1. Alternative split: train 2023+2024-H1, val 2024-H2, test 2025+2026  (use more training data)
2. No class_weight (raw calibration)
3. Use profit_ratio as sample weight (reward separating big wins from big losses)
4. Use stringent label: label=1 only if profit_ratio > +0.01 (ignore marginal)

Goal: verify the negative verdict is robust, not a tuning miss.
"""
from __future__ import annotations

from pathlib import Path
import json

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
import lightgbm as lgb

DIR = Path(__file__).parent

FEATURE_COLS = [
    "btc_sma20_slope", "btc_sma50_slope", "btc_sma200_slope",
    "btc_rsi14", "btc_atr_pct", "btc_pos_vs_sma50", "btc_pos_vs_sma200",
    "btc_rv_24h", "btc_rv_pct_30d",
    "pair_atr_pct", "pair_adx14", "pair_rsi14", "pair_above_sma50",
    "breadth_above_sma50", "fng", "hour", "dow",
]

def pf(r): g=r[r>0].sum(); l=-r[r<0].sum(); return np.inf if l==0 else g/l

def simulate(r: np.ndarray, cap=1000.0):
    eq = cap
    peak = cap
    dd_min = 0.0
    for x in r:
        eq += eq * 0.10 * x
        if eq > peak: peak = eq
        d = (eq - peak)/peak
        if d < dd_min: dd_min = d
    return {"n": len(r), "final": eq, "ret": (eq-cap)/cap, "pf": pf(r), "dd": dd_min, "wr": float((r>0).mean()) if len(r) else 0.0}


def fit_eval(X_tr, y_tr, X_va, y_va, X_te, y_te, **lgb_kwargs):
    m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15,
                           max_depth=5, min_child_samples=10, subsample=0.8,
                           colsample_bytree=0.8, reg_lambda=1.0, random_state=42,
                           verbose=-1, **lgb_kwargs)
    m.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], callbacks=[lgb.early_stopping(30, verbose=False)])
    return m, m.predict_proba(X_va)[:,1], m.predict_proba(X_te)[:,1]


def main():
    df = pd.read_parquet(DIR/"features.parquet").sort_values("open_date").reset_index(drop=True)

    experiments = []

    # Experiment A — balanced vs unbalanced, original split
    t1 = pd.Timestamp("2024-07-01", tz="UTC")
    t2 = pd.Timestamp("2025-07-01", tz="UTC")
    tr = df[df.open_date <  t1]; va = df[(df.open_date>=t1)&(df.open_date<t2)]; te = df[df.open_date>=t2]
    for label_def in ("raw", "strict"):
        if label_def == "strict":
            y_tr = (tr["profit_ratio"] > 0.01).astype(int).values
            y_va = (va["profit_ratio"] > 0.01).astype(int).values
            y_te = (te["profit_ratio"] > 0.01).astype(int).values
        else:
            y_tr = tr["label"].values; y_va = va["label"].values; y_te = te["label"].values
        for cw in (None, "balanced"):
            m, p_va, p_te = fit_eval(
                tr[FEATURE_COLS].values, y_tr,
                va[FEATURE_COLS].values, y_va,
                te[FEATURE_COLS].values, y_te,
                class_weight=cw,
            )
            au_v = roc_auc_score(y_va, p_va) if len(set(y_va))>1 else np.nan
            au_t = roc_auc_score(y_te, p_te) if len(set(y_te))>1 else np.nan
            best = None
            for thr in np.arange(0.30, 0.80, 0.02):
                mask = p_te >= thr
                if mask.sum() < 30: continue
                r = te.loc[mask, "profit_ratio"].values
                s = simulate(r)
                if (best is None) or (s["pf"] > best["pf"]):
                    best = {"thr": float(thr), **s}
            experiments.append({
                "label": label_def, "class_weight": str(cw),
                "val_auc": au_v, "test_auc": au_t,
                "best_thr_pf>1_30trades": best,
            })

    # Experiment B — alt split (train 2023+2024-H1, val 2024-H2, test 2025+2026)
    t1b = pd.Timestamp("2024-07-01", tz="UTC")
    t2b = pd.Timestamp("2025-01-01", tz="UTC")
    tr2 = df[df.open_date <  t1b]; va2 = df[(df.open_date>=t1b)&(df.open_date<t2b)]; te2 = df[df.open_date>=t2b]
    y_tr = tr2["label"].values; y_va = va2["label"].values; y_te = te2["label"].values
    m, p_va, p_te = fit_eval(
        tr2[FEATURE_COLS].values, y_tr, va2[FEATURE_COLS].values, y_va, te2[FEATURE_COLS].values, y_te,
        class_weight=None)
    best = None
    for thr in np.arange(0.30, 0.80, 0.02):
        mask = p_te >= thr
        if mask.sum() < 30: continue
        r = te2.loc[mask, "profit_ratio"].values
        s = simulate(r)
        if (best is None) or (s["pf"] > best["pf"]):
            best = {"thr": float(thr), **s}
    experiments.append({
        "label": "raw", "class_weight": "None", "split": "alt_wide_test",
        "val_auc": roc_auc_score(y_va, p_va) if len(set(y_va))>1 else np.nan,
        "test_auc": roc_auc_score(y_te, p_te) if len(set(y_te))>1 else np.nan,
        "test_n": int(len(te2)),
        "best_thr_pf>1_30trades": best,
    })

    # Experiment C — sample weight = |profit_ratio|, original split
    t1 = pd.Timestamp("2024-07-01", tz="UTC")
    t2 = pd.Timestamp("2025-07-01", tz="UTC")
    tr = df[df.open_date <  t1]; va = df[(df.open_date>=t1)&(df.open_date<t2)]; te = df[df.open_date>=t2]
    m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15,
                           max_depth=5, min_child_samples=10, subsample=0.8,
                           colsample_bytree=0.8, reg_lambda=1.0, random_state=42, verbose=-1)
    m.fit(tr[FEATURE_COLS].values, tr["label"].values,
          sample_weight=np.abs(tr["profit_ratio"].values),
          eval_set=[(va[FEATURE_COLS].values, va["label"].values)],
          callbacks=[lgb.early_stopping(30, verbose=False)])
    p_te = m.predict_proba(te[FEATURE_COLS].values)[:,1]
    best = None
    for thr in np.arange(0.30, 0.80, 0.02):
        mask = p_te >= thr
        if mask.sum() < 30: continue
        r = te.loc[mask, "profit_ratio"].values
        s = simulate(r)
        if (best is None) or (s["pf"] > best["pf"]):
            best = {"thr": float(thr), **s}
    experiments.append({"label": "raw", "class_weight": "None", "sample_weight": "abs_pr",
                        "test_auc": roc_auc_score(te["label"].values, p_te),
                        "best_thr_pf>1_30trades": best})

    # Baseline
    base = simulate(te["profit_ratio"].values)

    print("\n=== BASELINE (test, original split) ===")
    print(base)
    print("\n=== EXPERIMENTS ===")
    for e in experiments:
        print(json.dumps(e, default=str, indent=2))

    with open(DIR/"robustness.json", "w") as f:
        json.dump({"baseline": base, "experiments": experiments}, f, default=str, indent=2)
    print("\nSaved robustness.json")

if __name__ == "__main__":
    main()
