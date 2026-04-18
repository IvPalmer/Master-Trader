"""
Train meta-labeler on MT trades + evaluate vs raw baseline at multiple thresholds.

Split (chronological):
  train: trades with open_date <  2024-07-01
  val:   2024-07-01 .. 2025-07-01
  test:  2025-07-01 ..

Models: LightGBM (primary), RandomForest (fallback check).
Metrics: AUC / precision / recall on val + test.
Then apply thresholds {0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.8} and compute PF,
win-rate, total return, max-DD (equity curve), trade count on TEST set.

Artifacts:
  model.joblib  (best LGBM)
  threshold_sweep.csv
  equity_curves.png  (raw vs best-threshold)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score, precision_score, recall_score, roc_auc_score

import joblib
import lightgbm as lgb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

DIR = Path(__file__).parent
FEATURES = DIR / "features.parquet"

FEATURE_COLS = [
    "btc_sma20_slope",
    "btc_sma50_slope",
    "btc_sma200_slope",
    "btc_rsi14",
    "btc_atr_pct",
    "btc_pos_vs_sma50",
    "btc_pos_vs_sma200",
    "btc_rv_24h",
    "btc_rv_pct_30d",
    "pair_atr_pct",
    "pair_adx14",
    "pair_rsi14",
    "pair_above_sma50",
    "breadth_above_sma50",
    "fng",
    "hour",
    "dow",
]


def pf(profits: np.ndarray) -> float:
    gains = profits[profits > 0].sum()
    losses = -profits[profits < 0].sum()
    return float("inf") if losses == 0 else gains / losses


def max_drawdown(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return 0.0
    peaks = np.maximum.accumulate(equity)
    dd = (equity - peaks) / peaks
    return float(dd.min())


def simulate(df: pd.DataFrame, start_capital: float = 1000.0) -> dict:
    """Sequentially apply trade returns; uniform 10% position sizing."""
    if len(df) == 0:
        return {"trades": 0, "win_rate": 0, "pf": 0, "total_return": 0, "max_dd": 0, "final_equity": start_capital}
    returns = df["profit_ratio"].values  # fractional
    # Fixed-stake: treat each trade as absolute dollars, compound with 10% sizing
    equity = [start_capital]
    for r in returns:
        cap = equity[-1]
        stake = cap * 0.10  # 10% of equity per trade — matches fleet sizing
        pnl = stake * r
        equity.append(cap + pnl)
    equity_arr = np.array(equity)
    total_ret = (equity_arr[-1] - start_capital) / start_capital
    return {
        "trades": int(len(df)),
        "win_rate": float((df["label"] == 1).mean()),
        "pf": pf(df["profit_ratio"].values),
        "total_return": float(total_ret),
        "max_dd": max_drawdown(equity_arr),
        "final_equity": float(equity_arr[-1]),
        "equity_curve": equity_arr,
    }


def main() -> None:
    df = pd.read_parquet(FEATURES).sort_values("open_date").reset_index(drop=True)
    print(f"Total trades: {len(df)}")

    # Chronological split
    t1 = pd.Timestamp("2024-07-01", tz="UTC")
    t2 = pd.Timestamp("2025-07-01", tz="UTC")
    train = df[df["open_date"] < t1]
    val = df[(df["open_date"] >= t1) & (df["open_date"] < t2)]
    test = df[df["open_date"] >= t2]
    print(f"Split: train={len(train)} ({train['label'].mean():.2f}), "
          f"val={len(val)} ({val['label'].mean():.2f}), "
          f"test={len(test)} ({test['label'].mean():.2f})")

    X_train, y_train = train[FEATURE_COLS].values, train["label"].values
    X_val, y_val = val[FEATURE_COLS].values, val["label"].values
    X_test, y_test = test[FEATURE_COLS].values, test["label"].values

    # LightGBM
    lgb_model = lgb.LGBMClassifier(
        n_estimators=300,
        learning_rate=0.03,
        num_leaves=15,
        max_depth=5,
        min_child_samples=10,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        class_weight="balanced",
        random_state=42,
        verbose=-1,
    )
    lgb_model.fit(
        X_train,
        y_train,
        eval_set=[(X_val, y_val)],
        callbacks=[lgb.early_stopping(30, verbose=False)],
    )
    p_val = lgb_model.predict_proba(X_val)[:, 1]
    p_test = lgb_model.predict_proba(X_test)[:, 1]

    # RandomForest comparison
    rf = RandomForestClassifier(
        n_estimators=400,
        max_depth=6,
        min_samples_leaf=10,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    rf.fit(X_train, y_train)
    p_val_rf = rf.predict_proba(X_val)[:, 1]
    p_test_rf = rf.predict_proba(X_test)[:, 1]

    print("\n=== VALIDATION ===")
    print(f"LGBM AUC={roc_auc_score(y_val, p_val):.3f}  AP={average_precision_score(y_val, p_val):.3f}")
    print(f"RF   AUC={roc_auc_score(y_val, p_val_rf):.3f}  AP={average_precision_score(y_val, p_val_rf):.3f}")

    print("\n=== TEST ===")
    print(f"LGBM AUC={roc_auc_score(y_test, p_test):.3f}  AP={average_precision_score(y_test, p_test):.3f}")
    print(f"RF   AUC={roc_auc_score(y_test, p_test_rf):.3f}  AP={average_precision_score(y_test, p_test_rf):.3f}")

    # Feature importance
    fi = pd.Series(lgb_model.feature_importances_, index=FEATURE_COLS).sort_values(ascending=False)
    print("\n=== Top LGBM feature importance ===")
    print(fi.to_string())

    # Baseline (raw MT) metrics on test
    baseline = simulate(test.copy())
    print(f"\n=== RAW MT (test set) ===")
    print(f"trades={baseline['trades']} win_rate={baseline['win_rate']:.3f} pf={baseline['pf']:.3f} "
          f"total_return={baseline['total_return']:.3f} max_dd={baseline['max_dd']:.3f}")

    # Threshold sweep on TEST (using LGBM probabilities)
    thresholds = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
    rows = []
    curves: dict[float, np.ndarray] = {}
    rows.append({
        "threshold": "raw",
        "trades": baseline["trades"],
        "win_rate": baseline["win_rate"],
        "pf": baseline["pf"],
        "total_return": baseline["total_return"],
        "max_dd": baseline["max_dd"],
    })
    for thr in thresholds:
        mask = p_test >= thr
        sub = test.iloc[mask].copy()
        if len(sub) == 0:
            rows.append({"threshold": thr, "trades": 0, "win_rate": 0, "pf": 0, "total_return": 0, "max_dd": 0})
            continue
        sim = simulate(sub)
        rows.append({
            "threshold": thr,
            "trades": sim["trades"],
            "win_rate": sim["win_rate"],
            "pf": sim["pf"],
            "total_return": sim["total_return"],
            "max_dd": sim["max_dd"],
        })
        curves[thr] = sim["equity_curve"]

    sweep = pd.DataFrame(rows)
    sweep.to_csv(DIR / "threshold_sweep.csv", index=False)
    print("\n=== Threshold sweep (LGBM, test set) ===")
    print(sweep.to_string(index=False))

    # RF threshold sweep for robustness
    rows_rf = [{"threshold": "raw", **{k: baseline[k] for k in ["trades", "win_rate", "pf", "total_return", "max_dd"]}}]
    for thr in thresholds:
        mask = p_test_rf >= thr
        sub = test.iloc[mask].copy()
        if len(sub) == 0:
            rows_rf.append({"threshold": thr, "trades": 0, "win_rate": 0, "pf": 0, "total_return": 0, "max_dd": 0})
            continue
        sim = simulate(sub)
        rows_rf.append({
            "threshold": thr,
            "trades": sim["trades"],
            "win_rate": sim["win_rate"],
            "pf": sim["pf"],
            "total_return": sim["total_return"],
            "max_dd": sim["max_dd"],
        })
    sweep_rf = pd.DataFrame(rows_rf)
    sweep_rf.to_csv(DIR / "threshold_sweep_rf.csv", index=False)
    print("\n=== Threshold sweep (RandomForest, test set) ===")
    print(sweep_rf.to_string(index=False))

    # Equity curves plot
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(baseline["equity_curve"], label=f"raw MT  pf={baseline['pf']:.2f}  n={baseline['trades']}", color="red", lw=2)
    for thr, eq in curves.items():
        if len(eq) > 5:
            ax.plot(np.linspace(0, len(baseline["equity_curve"]) - 1, len(eq)), eq, label=f"thr={thr}  n={len(eq)-1}", alpha=0.7)
    ax.set_title("MT meta-labeled equity curves (test set)")
    ax.set_xlabel("trade index (baseline)")
    ax.set_ylabel("equity ($)")
    ax.axhline(1000, color="gray", lw=0.5, ls="--")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(DIR / "equity_curves.png", dpi=110)
    print(f"Saved equity_curves.png")

    # Save best model
    joblib.dump({"model": lgb_model, "features": FEATURE_COLS}, DIR / "model.joblib")
    # Dump summary json
    with open(DIR / "summary.json", "w") as f:
        json.dump(
            {
                "train_size": len(train),
                "val_size": len(val),
                "test_size": len(test),
                "lgbm_val_auc": float(roc_auc_score(y_val, p_val)),
                "lgbm_test_auc": float(roc_auc_score(y_test, p_test)),
                "rf_val_auc": float(roc_auc_score(y_val, p_val_rf)),
                "rf_test_auc": float(roc_auc_score(y_test, p_test_rf)),
                "feature_importance": fi.to_dict(),
                "baseline_test": {k: float(v) if isinstance(v, (int, float, np.floating)) else v for k, v in baseline.items() if k != "equity_curve"},
                "threshold_sweep_lgbm": sweep.to_dict(orient="records"),
                "threshold_sweep_rf": sweep_rf.to_dict(orient="records"),
            },
            f,
            indent=2,
            default=str,
        )
    print(f"Saved model.joblib, summary.json")


if __name__ == "__main__":
    main()
