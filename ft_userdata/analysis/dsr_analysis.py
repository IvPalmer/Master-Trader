#!/usr/bin/env python3
"""
Deflated Sharpe Ratio analysis on Strategy Lab results.

Reference: Bailey & López de Prado (2014), "The Deflated Sharpe Ratio: Correcting
for Selection Bias, Backtest Overfitting, and Non-Normality"
https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

Formulas:
    E[SR_max] ≈ sqrt(V) * ((1 - γ) * Z⁻¹(1 - 1/N) + γ * Z⁻¹(1 - 1/(N*e)))
      where γ = Euler-Mascheroni ≈ 0.5772, V = var(SR across trials)
      (conservative: assume V=1 unless we have true variance across trials)

    σ_SR(SR_hat) = sqrt( (1 - skew*SR_hat + (kurt-1)/4 * SR_hat²) / (T - 1) )

    PSR(SR*) = Φ( (SR_hat - SR*) / σ_SR )

    DSR = PSR(E[SR_max]) = Φ( (SR_hat - E[SR_max]) / σ_SR )
"""

import csv
import io
import json
import math
import re
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

# ── Paths ────────────────────────────────────────────────────
LAB_LOG = Path("/Users/palmer/ft_userdata/lab_output_funding_20260417.txt")
KELTNER_ZIP = Path("/Users/palmer/ft_userdata/user_data/backtest_results/"
                   "backtest-result-2026-04-17_00-35-38.zip")
OUT_DIR = Path("/Users/palmer/Work/Dev/master-trader/ft_userdata/analysis")
OUT_CSV = OUT_DIR / "dsr_results.csv"

# Lab run parameters
N_TRIALS = 6900               # combos generated (log says 6900, not 6864)
TIMERANGE_DAYS = (pd.Timestamp("2026-04-15") - pd.Timestamp("2023-01-01")).days  # 1200
BARS_PER_YEAR_HOURLY = 24 * 365  # 8760
SAMPLE_YEARS = TIMERANGE_DAYS / 365.25  # ~3.28
EULER = 0.5772156649


# ── DSR primitives ──────────────────────────────────────────

def expected_max_sr(n_trials: int, var_across_trials: float = 1.0) -> float:
    """Expected maximum Sharpe under H0 of zero skill across n_trials.

    Bailey & López de Prado 2014 eq.(5):
      E[max_i SR_i] ≈ sqrt(V) * ((1 - γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e)))
    """
    if n_trials <= 1:
        return 0.0
    term1 = (1 - EULER) * norm.ppf(1 - 1.0 / n_trials)
    term2 = EULER * norm.ppf(1 - 1.0 / (n_trials * math.e))
    return math.sqrt(var_across_trials) * (term1 + term2)


def sigma_sr(sr_hat: float, skew: float, kurt: float, T: int) -> float:
    """Standard error of Sharpe estimator with non-normality adjustment.

    From Mertens (2002) / Bailey-LdP:
      σ²(SR) = (1 - γ₃·SR + (γ₄ - 1)/4 · SR²) / (T - 1)
    where γ₃ = skewness, γ₄ = kurtosis (NOT excess — full moment)
    """
    var = (1.0 - skew * sr_hat + 0.25 * (kurt - 1.0) * sr_hat ** 2) / max(T - 1, 1)
    return math.sqrt(max(var, 1e-12))


def dsr(sr_hat: float, skew: float, kurt: float, T: int, n_trials: int,
        var_across_trials: float = 1.0) -> dict:
    """Compute Deflated Sharpe Ratio probability.

    Returns dict with E[SR_max], σ_SR, z-score, DSR probability.
    """
    e_max = expected_max_sr(n_trials, var_across_trials)
    sigma = sigma_sr(sr_hat, skew, kurt, T)
    z = (sr_hat - e_max) / sigma if sigma > 0 else 0.0
    prob = float(norm.cdf(z))
    return {
        "sr_hat": sr_hat,
        "skew": skew,
        "kurt": kurt,
        "T": T,
        "E_SR_max": e_max,
        "sigma_SR": sigma,
        "z": z,
        "DSR": prob,
    }


# ── Reconstruct per-trade returns from PF, WR, N ────────────

def reconstruct_moments_from_pfwr(pf: float, wr_pct: float, n_trades: int,
                                  total_return_pct: float) -> dict:
    """Given PF, win-rate, trade count, and total return (%), reconstruct
    an approximate per-trade return stream and compute moments.

    Method:
      - Assume every win has magnitude w, every loss has magnitude -l
      - win_count * w - loss_count * l = total_abs_return_implied
      - (win_count * w) / (loss_count * l) = PF
      - Solve jointly → get w, l
      - Build synthetic trade stream → mean, std, skew, kurt, Sharpe

    This is a two-point approximation. It underestimates variance (real trades
    have within-class dispersion) and consequently OVERSTATES Sharpe. Caveat
    applied in the report.

    Returns dict of moments + synthetic SR (non-annualized, per-trade basis).
    """
    wr = wr_pct / 100.0
    n_win = int(round(n_trades * wr))
    n_loss = n_trades - n_win
    if n_win == 0 or n_loss == 0:
        return None

    # Total return is on wallet ($88). Per-trade position is wallet/max_open = $88/3 ≈ $29.33
    # But profit_factor and WR are based on per-trade profit_pct, so work in percent space.
    # We don't have total_abs_return per trade — we have pnl_pct on wallet.
    # Reconstruction: assume win mag w, loss mag l (both in per-trade %).
    # n_win * w - n_loss * l = total_pnl_pct_wallet × (wallet / stake_per_trade)
    # PF = n_win * w / (n_loss * l)
    #
    # However pnl_pct on wallet aggregates across max_open parallel positions.
    # For DSR purposes we only need the *shape* (skew, kurt) and the SR,
    # which is scale-invariant. So pick any consistent units; absolute return
    # total cancels when computing SR on the trade series.
    #
    # Simplest: set l = 1 (loss = -1 unit), then w = PF * n_loss / n_win.
    l = 1.0
    w = pf * n_loss / n_win

    trades = np.array([w] * n_win + [-l] * n_loss)
    # Mean, std (ddof=1), skew, kurt (Pearson/moment-based, full kurtosis not excess)
    mu = trades.mean()
    sigma = trades.std(ddof=1)
    if sigma == 0:
        return None
    standardised = (trades - mu) / sigma
    g3 = float(np.mean(standardised ** 3))                  # skew
    g4 = float(np.mean(standardised ** 4))                  # full kurtosis (normal = 3)
    sr_per_trade = mu / sigma

    return {
        "n_trades": n_trades,
        "n_wins": n_win,
        "n_losses": n_loss,
        "mu": mu,
        "sigma": sigma,
        "skew": g3,
        "kurt": g4,
        "SR_per_trade": sr_per_trade,
    }


def annualise_sr(sr_per_trade: float, n_trades: int, span_years: float) -> float:
    """Annualise per-trade Sharpe to per-year Sharpe.

    SR_annual = SR_per_trade * sqrt(trades_per_year)
    """
    trades_per_year = n_trades / max(span_years, 1e-6)
    return sr_per_trade * math.sqrt(trades_per_year)


# ── Parse the Lab top-50 text log ───────────────────────────

TOP50_PATTERN = re.compile(
    r"^\s*(\d+)\s+([+-]?\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)%\s+([+-]?\d+\.\d+)%\s+(\d+\.\d+)%\s+(\d+)\s+(.+?)\s*$"
)


def parse_lab_top50(path: Path) -> list:
    combos = []
    in_top50 = False
    seen_combos = set()
    for line in path.read_text().splitlines():
        if "TOP 50 SIGNAL COMBINATIONS" in line:
            in_top50 = True
            continue
        if "QUALITY FILTER PASSES" in line:
            in_top50 = False
            continue
        if not in_top50:
            continue
        m = TOP50_PATTERN.match(line)
        if not m:
            continue
        rank = int(m.group(1))
        score = float(m.group(2))
        pf = float(m.group(3))
        wr = float(m.group(4))
        pnl = float(m.group(5))
        dd = float(m.group(6))
        trades = int(m.group(7))
        combo = m.group(8).strip()
        # Dedupe (gate variants with identical metrics)
        key = (pf, wr, pnl, dd, trades, combo.split("|")[0])
        if key in seen_combos:
            continue
        seen_combos.add(key)
        combos.append({
            "rank": rank, "score": score, "pf": pf, "wr": wr,
            "pnl_pct": pnl, "dd_pct": dd, "trades": trades, "combo": combo,
        })
    return combos


# ── Extract Keltner per-trade returns from backtest zip ─────

def load_keltner_trades(zip_path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as zf:
        json_name = [n for n in zf.namelist() if n.endswith(".json")
                     and "_config" not in n][0]
        with zf.open(json_name) as f:
            d = json.load(f)
    strat_key = list(d["strategy"].keys())[0]
    trades = pd.DataFrame(d["strategy"][strat_key]["trades"])
    return trades, d["strategy"][strat_key]


# ── Main analysis ───────────────────────────────────────────

def analyse_combo_from_pfwr(row: dict) -> dict:
    """Build a DSR record from text-log summary stats."""
    m = reconstruct_moments_from_pfwr(row["pf"], row["wr"], row["trades"],
                                      row["pnl_pct"])
    if m is None:
        return None
    sr_ann = annualise_sr(m["SR_per_trade"], row["trades"], SAMPLE_YEARS)
    # For DSR, use T = n_trades (sample is over trade count, not days, for
    # trade-based Sharpe stability — Bailey-LdP applies formula on any freq).
    res = dsr(sr_hat=sr_ann, skew=m["skew"], kurt=m["kurt"],
              T=row["trades"], n_trials=N_TRIALS)
    res.update({"combo": row["combo"], "pf": row["pf"], "wr": row["wr"],
                "pnl_pct": row["pnl_pct"], "dd_pct": row["dd_pct"],
                "trades": row["trades"], "SR_ann": sr_ann,
                "SR_per_trade": m["SR_per_trade"]})
    return res


def analyse_keltner_from_trades() -> list:
    """Analyse Keltner with TWO Sharpe definitions:
      (A) per-trade annualised (same method as the reconstructed combos)
      (B) daily-return annualised (matches Freqtrade's reported Sharpe)
    Returns both records so DSR is comparable across methodologies.
    """
    trades, stats = load_keltner_trades(KELTNER_ZIP)
    r = trades["profit_ratio"].values
    n = len(r)
    mu = r.mean()
    sigma = r.std(ddof=1)
    sr_per_trade = mu / sigma
    standardised = (r - mu) / sigma
    g3 = float(np.mean(standardised ** 3))
    g4 = float(np.mean(standardised ** 4))
    span_days = (pd.to_datetime(trades["close_date"].max())
                 - pd.to_datetime(trades["open_date"].min())).days
    span_years = span_days / 365.25

    # (A) Per-trade annualised
    sr_ann_tr = annualise_sr(sr_per_trade, n, span_years)
    a = dsr(sr_hat=sr_ann_tr, skew=g3, kurt=g4, T=n, n_trials=N_TRIALS)
    a.update({
        "combo": "KeltnerBounceV1 [per-trade ann SR]",
        "pf": stats.get("profit_factor"), "trades": n,
        "freqtrade_reported_sharpe": stats.get("sharpe"),
        "SR_ann": sr_ann_tr, "SR_per_trade": sr_per_trade,
        "span_years": span_years,
        "pnl_pct": stats.get("profit_total", 0) * 100,
    })

    # (B) Daily-return Sharpe (Freqtrade style)
    td = trades.copy()
    td["close_date"] = pd.to_datetime(td["close_date"])
    td["day"] = td["close_date"].dt.floor("D")
    daily = td.groupby("day")["profit_ratio"].sum()
    # Fill calendar days with 0
    idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(idx, fill_value=0.0)
    d_mu = daily.mean()
    d_sig = daily.std(ddof=1)
    sr_ann_d = (d_mu / d_sig) * math.sqrt(365) if d_sig > 0 else 0
    d_std = (daily - d_mu) / d_sig if d_sig > 0 else daily * 0
    d_g3 = float(np.mean(d_std ** 3))
    d_g4 = float(np.mean(d_std ** 4))
    b = dsr(sr_hat=sr_ann_d, skew=d_g3, kurt=d_g4, T=len(daily),
            n_trials=N_TRIALS)
    b.update({
        "combo": "KeltnerBounceV1 [daily-return ann SR, Freqtrade-style]",
        "pf": stats.get("profit_factor"), "trades": n,
        "freqtrade_reported_sharpe": stats.get("sharpe"),
        "SR_ann": sr_ann_d, "SR_per_trade": None,
        "span_years": span_years,
        "pnl_pct": stats.get("profit_total", 0) * 100,
    })
    return [a, b]


# ── Sanity checks ───────────────────────────────────────────

def sanity_checks():
    """Verify implementation against known points."""
    print("\n=== SANITY CHECKS ===")
    # 1. E[SR_max] for N=1 should be 0
    e1 = expected_max_sr(1)
    print(f"E[SR_max | N=1] = {e1:.4f} (expected ~0)")
    # 2. E[SR_max] grows ~sqrt(2 log N) asymptotically
    for n in [10, 100, 1000, 6900]:
        em = expected_max_sr(n)
        asy = math.sqrt(2 * math.log(n))
        print(f"N={n:>5}: E[SR_max]={em:.4f}, asymptote sqrt(2 log N)={asy:.4f}")
    # 3. Normal returns, T large, skew=0, kurt=3 → σ_SR ≈ sqrt(1/(T-1)) at SR=0
    s = sigma_sr(0.0, 0.0, 3.0, 1000)
    print(f"σ_SR(0, T=1000, normal) = {s:.4f} (expected ~{math.sqrt(1/999):.4f})")
    # 4. PSR of SR_hat == SR* should be 0.5
    r = dsr(1.0, 0, 3, 1000, 1)  # N=1 so E[SR_max]=0, and SR_hat=1>0 → DSR>0.5
    print(f"DSR(SR=1, T=1000, N=1) = {r['DSR']:.4f} (>0.5 expected, N=1 has no deflation)")


# ── Entry ───────────────────────────────────────────────────

def main():
    sanity_checks()
    print(f"\nN_TRIALS = {N_TRIALS}")
    print(f"Sample span = {SAMPLE_YEARS:.2f} years ({TIMERANGE_DAYS} days)")
    print(f"E[SR_max] (N={N_TRIALS}, V=1) = {expected_max_sr(N_TRIALS):.3f}")

    # Top-50 from lab log
    print("\n=== PARSING LAB TOP-50 LOG ===")
    combos = parse_lab_top50(LAB_LOG)
    print(f"Parsed {len(combos)} unique combos from top-50 log")

    records = []
    for row in combos:
        r = analyse_combo_from_pfwr(row)
        if r:
            records.append(r)

    # FundingFade — live bot signal is row 14 in top50:
    # funding_below_mean+adx(25)+vol(1.5)|btc_sma50+sma200|roi_only
    # Will appear in records already.

    # Keltner from backtest zip (real per-trade returns)
    print("\n=== KELTNER FROM BACKTEST ZIP ===")
    keltner_records = analyse_keltner_from_trades()
    for k in keltner_records:
        records.append(k)
        print(f"{k['combo']}")
        print(f"  SR={k['SR_ann']:.3f} (Freqtrade reported: "
              f"{k['freqtrade_reported_sharpe']:.3f}), "
              f"skew={k['skew']:.3f}, kurt={k['kurt']:.3f}, T={k['T']}")
        print(f"  E[SR_max]={k['E_SR_max']:.3f}, σ={k['sigma_SR']:.3f}, "
              f"z={k['z']:.3f}, DSR={k['DSR']:.4f}")

    # Rank by DSR
    records.sort(key=lambda r: -r["DSR"])

    # Write CSV
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fields = ["combo", "pf", "wr", "trades", "pnl_pct", "dd_pct",
              "SR_per_trade", "SR_ann", "skew", "kurt", "T",
              "E_SR_max", "sigma_SR", "z", "DSR"]
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in records:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"\nWrote {len(records)} rows to {OUT_CSV}")

    # Print top 20 + FundingFade + Keltner
    print("\n=== TOP 20 BY DSR ===")
    print(f"{'rank':<4}{'DSR':>7}{'SR_ann':>8}{'skew':>7}{'kurt':>7}"
          f"{'T':>6}{'PF':>6}  combo")
    for i, r in enumerate(records[:20], 1):
        print(f"{i:<4}{r['DSR']:>7.4f}{r['SR_ann']:>8.3f}"
              f"{r['skew']:>7.3f}{r['kurt']:>7.3f}{r['T']:>6}"
              f"{r.get('pf', 0):>6.2f}  {r['combo'][:70]}")

    # Survivorship rate
    passed = sum(1 for r in records if r["DSR"] > 0.95)
    print(f"\n=== SURVIVORSHIP ===")
    print(f"Combos analysed: {len(records)} (of 6900 — only top-50 log persisted)")
    print(f"DSR > 0.95: {passed} ({100*passed/len(records):.1f}% of analysed)")

    # Break-even SR for DSR > 0.95 at various effective N
    print("\n=== BREAK-EVEN SR FOR DSR > 0.95 ===")
    # Using typical sample params from Keltner: T=139, skew=-1.3, kurt=3.5
    for eff_n in [1, 10, 100, 1000, 6900]:
        em = expected_max_sr(eff_n)
        # For skew=-1.3, kurt=3.5, T=139:
        # sigma_SR = sqrt((1 - (-1.3)*SR + (3.5-1)/4 * SR^2) / 138)
        # Need SR such that (SR - em)/sigma_SR >= 1.645 (z for 0.95)
        # Solve numerically
        target_z = 1.645
        sr_search = em + 0.01
        for _ in range(100000):
            s = sigma_sr(sr_search, -1.3, 3.5, 139)
            if (sr_search - em) / s >= target_z:
                break
            sr_search += 0.001
        print(f"  Eff N={eff_n:>5}: E[SR_max]={em:.3f}, "
              f"SR needed (T=139, skew=-1.3, kurt=3.5) ≈ {sr_search:.3f}")

    # Live strategies
    print("\n=== LIVE STRATEGY CHECK ===")
    for r in records:
        if "Keltner" in r["combo"]:
            print(f"[Keltner real data] DSR={r['DSR']:.4f}, SR_ann={r['SR_ann']:.3f}, "
                  f"E[SR_max]={r['E_SR_max']:.3f}")
        if "funding_below_mean" in r["combo"] and "adx(25)+vol(1.5)" in r["combo"]:
            print(f"[FundingFade lab]   DSR={r['DSR']:.4f}, SR_ann={r['SR_ann']:.3f}, "
                  f"E[SR_max]={r['E_SR_max']:.3f}  combo={r['combo']}")

    return records


if __name__ == "__main__":
    main()
