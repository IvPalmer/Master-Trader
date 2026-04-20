#!/usr/bin/env python3
"""
Deflated Sharpe Ratio v2 — uses the full persisted lab run.

Improvements over v1 (`dsr_analysis.py`):
  1. Reads the newly-persisted `strategy_lab/results/all_combos_*.csv` +
     `all_trades_*.parquet` (fix to `strategy_lab.py` done in this session).
  2. Computes **effective N** via average pairwise correlation of combo
     daily-aggregated return streams. Uses the Meff formula
     N_eff = 1 + (N - 1) · (1 - avg_rho)   (Bailey-LdP section 5 equivalent).
  3. Reports DSR at a range of plausible effective-N values — both raw N and
     the correlation-adjusted figure.
  4. Keltner + FundingFade are evaluated against ALL trial counts (including
     the honest effective-N figure).

Reference: Bailey & López de Prado (2014), "The Deflated Sharpe Ratio".
"""

import csv
import glob
import json
import math
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

# ── Paths ────────────────────────────────────────────────────
LAB_RESULTS = Path("/Users/palmer/ft_userdata/strategy_lab/results")
KELTNER_ZIP = Path("/Users/palmer/ft_userdata/user_data/backtest_results/"
                   "backtest-result-2026-04-17_00-35-38.zip")
OUT_DIR = Path("/Users/palmer/Work/Dev/master-trader/ft_userdata/analysis")
OUT_CSV = OUT_DIR / "dsr_results_v2.csv"

EULER = 0.5772156649
SAMPLE_YEARS = (pd.Timestamp("2026-04-15") - pd.Timestamp("2023-01-01")).days / 365.25


# ── DSR primitives ──────────────────────────────────────────

def expected_max_sr(n_trials: int, var_across_trials: float = 1.0) -> float:
    if n_trials <= 1:
        return 0.0
    t1 = (1 - EULER) * norm.ppf(1 - 1.0 / n_trials)
    t2 = EULER * norm.ppf(1 - 1.0 / (n_trials * math.e))
    return math.sqrt(var_across_trials) * (t1 + t2)


def sigma_sr(sr_hat: float, skew: float, kurt: float, T: int) -> float:
    var = (1.0 - skew * sr_hat + 0.25 * (kurt - 1.0) * sr_hat ** 2) / max(T - 1, 1)
    return math.sqrt(max(var, 1e-12))


def dsr_prob(sr_hat: float, skew: float, kurt: float, T: int,
             n_trials: int, var_across_trials: float = 1.0) -> dict:
    e_max = expected_max_sr(n_trials, var_across_trials)
    sigma = sigma_sr(sr_hat, skew, kurt, T)
    z = (sr_hat - e_max) / sigma if sigma > 0 else 0.0
    return {"E_SR_max": e_max, "sigma_SR": sigma, "z": z,
            "DSR": float(norm.cdf(z))}


def annualise_sr(sr_per_trade: float, n_trades: int, years: float) -> float:
    tpy = n_trades / max(years, 1e-9)
    return sr_per_trade * math.sqrt(tpy)


# ── Load lab artifacts ──────────────────────────────────────

def latest_lab_artifact() -> tuple:
    csvs = sorted(LAB_RESULTS.glob("all_combos_*.csv"))
    if not csvs:
        raise SystemExit(f"No all_combos_*.csv in {LAB_RESULTS}")
    csv_path = csvs[-1]
    ts = csv_path.stem.replace("all_combos_", "")
    parquet_path = LAB_RESULTS / f"all_trades_{ts}.parquet"
    gz_path = LAB_RESULTS / f"all_trades_{ts}.csv.gz"
    meta_path = LAB_RESULTS / f"all_combos_{ts}.meta.json"
    if parquet_path.exists():
        trades_df = pd.read_parquet(parquet_path)
    elif gz_path.exists():
        trades_df = pd.read_csv(gz_path, compression="gzip")
    else:
        trades_df = None
    combos_df = pd.read_csv(csv_path)
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    return combos_df, trades_df, meta, csv_path


# ── Effective N via equity-curve correlation ────────────────

def compute_effective_n(trades_df: pd.DataFrame,
                        combos_df: pd.DataFrame,
                        min_trades: int = 20,
                        freq: str = "W",
                        max_pairs: int = 200) -> dict:
    """Effective number of trials via average pairwise correlation.

    Method:
      1. For each combo with >= min_trades, aggregate per-trade profit_pct
         into a regular-frequency return series (weekly sums by default —
         weekly is common in eff-N literature because daily is too sparse
         when many combos have only 50-100 trades over 3.3 years).
      2. Align all return series on a common date index, fill missing with 0.
      3. Correlation matrix → average of off-diagonal entries.
      4. Meff = 1 + (N-1) * (1 - avg_rho)

    For large N this is O(N^2·T) memory-heavy; subsample to `max_pairs`
    combos for tractability. The estimate is an unbiased sample.
    """
    eligible = combos_df[combos_df["total_trades"] >= min_trades]["combo"].tolist()
    if len(eligible) < 10:
        return {"error": f"too few eligible combos ({len(eligible)})"}

    # Subsample for tractability
    if len(eligible) > max_pairs:
        rng = np.random.default_rng(42)
        sample = list(rng.choice(eligible, size=max_pairs, replace=False))
    else:
        sample = eligible

    series_map = {}
    t = trades_df[trades_df["combo"].isin(sample)].copy()
    t["ts"] = pd.to_datetime(t["close_ts"], unit="s", errors="coerce")
    t = t.dropna(subset=["ts"])
    for combo_id, grp in t.groupby("combo"):
        s = grp.set_index("ts")["profit_pct"].resample(freq).sum()
        series_map[combo_id] = s

    if not series_map:
        return {"error": "no return series"}

    # Align on union index
    all_idx = sorted(set().union(*[s.index for s in series_map.values()]))
    mat = pd.DataFrame({cid: s.reindex(all_idx).fillna(0.0)
                        for cid, s in series_map.items()})

    # Drop combos with zero variance in this resampled series (would make
    # corr NaN and contaminate the mean).
    var = mat.var()
    mat = mat.loc[:, var > 1e-12]
    if mat.shape[1] < 2:
        return {"error": "insufficient non-constant series"}

    corr = mat.corr()
    # Average off-diagonal
    cvals = corr.values
    mask = ~np.eye(cvals.shape[0], dtype=bool)
    avg_rho = float(np.nanmean(cvals[mask]))
    # Also compute median — robust to outliers
    med_rho = float(np.nanmedian(cvals[mask]))
    # Positive-only mean (crypto strategies should be positively correlated)
    pos_rho = float(np.nanmean(np.clip(cvals[mask], 0, None)))

    # Eff N based on different rho estimates
    N = len(combos_df)

    def meff(rho: float) -> float:
        rho = max(min(rho, 1.0), 0.0)  # clamp to [0,1] for this formula
        return 1 + (N - 1) * (1 - rho)

    return {
        "n_combos": N,
        "n_series_used_for_corr": mat.shape[1],
        "freq": freq,
        "avg_rho": avg_rho,
        "median_rho": med_rho,
        "positive_mean_rho": pos_rho,
        "Neff_avg": meff(avg_rho),
        "Neff_median": meff(med_rho),
        "Neff_positive_mean": meff(pos_rho),
    }


# ── Keltner from backtest zip ───────────────────────────────

def load_keltner_stats() -> dict:
    with zipfile.ZipFile(KELTNER_ZIP) as zf:
        jn = [n for n in zf.namelist()
              if n.endswith(".json") and "_config" not in n][0]
        with zf.open(jn) as f:
            d = json.load(f)
    strat_key = list(d["strategy"].keys())[0]
    trades = pd.DataFrame(d["strategy"][strat_key]["trades"])
    stats = d["strategy"][strat_key]
    r = trades["profit_ratio"].values
    n = len(r)
    mu = r.mean()
    sig = r.std(ddof=1)
    sr_pt = mu / sig if sig > 0 else 0
    std = (r - mu) / sig if sig > 0 else r * 0
    skew = float(np.mean(std ** 3))
    kurt = float(np.mean(std ** 4))
    span = (pd.to_datetime(trades["close_date"].max())
            - pd.to_datetime(trades["open_date"].min())).days
    yr = span / 365.25
    sr_ann = annualise_sr(sr_pt, n, yr)
    return {"combo": "KeltnerBounceV1 (real per-trade)",
            "sr_ann": sr_ann, "skew": skew, "kurt": kurt,
            "T": n, "pf": stats.get("profit_factor"),
            "pnl_pct": stats.get("profit_total", 0) * 100,
            "span_years": yr}


# ── Main ────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("DSR v2 analysis")
    print("=" * 70)

    combos_df, trades_df, meta, csv_path = latest_lab_artifact()
    print(f"Loaded {len(combos_df)} combo summaries from {csv_path.name}")
    if trades_df is not None:
        print(f"Loaded {len(trades_df)} per-trade records")
    print(f"Lab meta: {meta}")
    print()

    # ── Annualised Sharpe per combo ──
    combos_df = combos_df.copy()
    combos_df["sr_ann"] = [
        annualise_sr(sr, n, SAMPLE_YEARS)
        for sr, n in zip(combos_df["sr_per_trade"], combos_df["total_trades"])
    ]

    # ── Keltner real trades ──
    kelt = load_keltner_stats()
    print("Keltner (real per-trade):")
    for k, v in kelt.items():
        print(f"  {k}: {v}")

    # ── Effective N ──
    print("\n--- Effective N (equity-curve correlation) ---")
    effn_results = {}
    if trades_df is not None:
        for freq in ("W", "D", "M"):
            res = compute_effective_n(trades_df, combos_df, freq=freq)
            effn_results[freq] = res
            print(f"Freq={freq}: {res}")
    else:
        print("No per-trade data available — skipping correlation eff-N")

    # Pick primary eff-N: weekly, avg rho is the canonical one
    N_raw = len(combos_df)
    eff_scenarios = {
        "raw_N": N_raw,
    }
    if "W" in effn_results and "Neff_avg" in effn_results["W"]:
        eff_scenarios["Neff_week_avg"] = int(effn_results["W"]["Neff_avg"])
        eff_scenarios["Neff_week_median"] = int(effn_results["W"]["Neff_median"])
        eff_scenarios["Neff_week_posmean"] = int(effn_results["W"]["Neff_positive_mean"])

    # Round-number reference points
    for n in (10, 100, 1000):
        eff_scenarios[f"ref_{n}"] = n

    print(f"\nEffective-N scenarios: {eff_scenarios}")

    # ── Build DSR table ──
    rows = []
    # Combos
    for _, r in combos_df.iterrows():
        base = {
            "combo": r["combo"],
            "total_trades": int(r["total_trades"]),
            "profit_factor": float(r["profit_factor"]),
            "win_rate": float(r["win_rate"]),
            "total_pnl_pct": float(r["total_pnl_pct"]),
            "sr_per_trade": float(r["sr_per_trade"]),
            "sr_ann": float(r["sr_ann"]),
            "skew": float(r["skew"]),
            "kurt": float(r["kurt"]),
        }
        for label, N in eff_scenarios.items():
            d = dsr_prob(r["sr_ann"], r["skew"], r["kurt"],
                         int(r["total_trades"]), N)
            base[f"DSR_{label}"] = d["DSR"]
            base[f"E_SR_max_{label}"] = d["E_SR_max"]
        rows.append(base)

    # Keltner
    base = {
        "combo": kelt["combo"],
        "total_trades": kelt["T"],
        "profit_factor": kelt["pf"],
        "win_rate": float("nan"),
        "total_pnl_pct": kelt["pnl_pct"],
        "sr_per_trade": float("nan"),
        "sr_ann": kelt["sr_ann"],
        "skew": kelt["skew"],
        "kurt": kelt["kurt"],
    }
    for label, N in eff_scenarios.items():
        d = dsr_prob(kelt["sr_ann"], kelt["skew"], kelt["kurt"],
                     kelt["T"], N)
        base[f"DSR_{label}"] = d["DSR"]
        base[f"E_SR_max_{label}"] = d["E_SR_max"]
    rows.append(base)

    # ── Write CSV ──
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        # Sort by sr_ann desc for readability
        rows.sort(key=lambda r: -r["sr_ann"])
        for r in rows:
            w.writerow(r)
    print(f"\nWrote {len(rows)} rows → {OUT_CSV}")

    # ── Top 50 + Keltner + FundingFade ──
    # FundingFade candidate: "funding_below_mean" + "adx(25)" + "vol(1.5)"
    # families — pull any matching, plus top-50 by sr_ann
    top = rows[:50]
    fundfade = [r for r in rows if "funding_below_mean" in r["combo"]
                and "adx(25)+vol(1.5)" in r["combo"]]
    kelt_rows = [r for r in rows if r["combo"].startswith("KeltnerBounce")]

    print("\n--- Top 20 by SR_ann ---")
    hdr_labels = [k for k in eff_scenarios.keys()]
    print(f"{'rank':<4}{'SR_ann':>7}{'skew':>7}{'T':>6}{'PF':>6}  "
          f"{'DSR_raw':>8}{'DSR_Neff':>9}  combo")
    neff_key = ("DSR_Neff_week_avg" if "Neff_week_avg" in eff_scenarios
                else "DSR_raw_N")
    for i, r in enumerate(top[:20], 1):
        print(f"{i:<4}{r['sr_ann']:>7.3f}{r['skew']:>7.3f}"
              f"{r['total_trades']:>6}{r['profit_factor']:>6.2f}  "
              f"{r['DSR_raw_N']:>8.4f}{r[neff_key]:>9.4f}  "
              f"{r['combo'][:60]}")

    print("\n--- FundingFade candidates in sample ---")
    for r in fundfade:
        print(f"  {r['combo']}  SR_ann={r['sr_ann']:.3f} "
              f"T={r['total_trades']} DSR_raw={r['DSR_raw_N']:.4f} "
              f"DSR_Neff={r[neff_key]:.4f}")
    if not fundfade:
        print("  (no funding_below_mean+adx(25)+vol(1.5) combo in sample)")

    print("\n--- Keltner rows ---")
    for r in kelt_rows:
        print(f"  {r['combo']}  SR_ann={r['sr_ann']:.3f} "
              f"T={r['total_trades']} DSR_raw={r['DSR_raw_N']:.4f} "
              f"DSR_Neff={r[neff_key]:.4f}")

    # Survivorship at each eff-N
    print("\n--- Survivorship @ DSR > 0.95 ---")
    for label in eff_scenarios:
        k = f"DSR_{label}"
        passes = sum(1 for r in rows if r[k] > 0.95)
        print(f"  {label}: {passes}/{len(rows)} "
              f"({100*passes/len(rows):.1f}%)")

    # Save meta
    report_meta = {
        "lab_csv": str(csv_path),
        "lab_meta": meta,
        "eff_scenarios": eff_scenarios,
        "effn_results": effn_results,
        "keltner": kelt,
        "survivorship": {
            label: sum(1 for r in rows if r[f"DSR_{label}"] > 0.95)
            for label in eff_scenarios
        },
    }
    with open(OUT_DIR / "dsr_results_v2.meta.json", "w") as f:
        json.dump(report_meta, f, indent=2, default=str)

    return rows, report_meta


if __name__ == "__main__":
    main()
