"""
Delta-Neutral FundingFade PoC simulation.

Hypothesis: Replace directional SPOT long with SPOT long + PERP SHORT (same size).
Payoff collapses to funding-rate carry over hold period, minus fees + slippage.

Assumptions (documented honestly — every simplification affects credibility):

1. DELTA-NEUTRAL: spot price move is exactly cancelled by short-perp move.
   Ignores spot-perp basis drift. In the Oct 10-11 2025 ADL cascade, real
   delta-neutral funds lost because ADL tore the hedge — we explicitly cannot
   simulate ADL since we don't have liquidation data.
2. FUNDING CARRY: spot side receives nothing (spot pays/receives no funding);
   perp SHORT side RECEIVES funding when funding > 0 (shorts paid by longs),
   and PAYS funding when < 0 (rare but happens in bear). So:
      pnl_funding = -sum(funding_rate) over hold period (negative of what FundingFade long perp would earn)
   Wait — re-check: FundingFade goes SPOT long. Spot doesn't earn funding.
   The directional bet profits from price mean-reversion after crowded-short
   sentiment. Delta-neutral REPLACES the directional spot-long with a carry
   trade. Since entry is triggered when funding < mean - 1σ (crowded short,
   i.e., funding is typically NEGATIVE or very low), a SHORT perp pays funding
   (funding < 0 means shorts pay longs). So delta-neutral at FundingFade
   triggers systematically HAEMORRHAGES on carry. The HF-desk version would
   instead do spot-short / perp-long to collect when funding < 0 — but that
   reverses the directional thesis.
   For this PoC we simulate the literal translation:
      LEG: SPOT long + PERP short (same notional).
      Funding PnL = -sum_of_funding_payments_during_hold (because perp short pays when funding<0).
   This is the expected answer: the trade loses the funding-carry edge when
   entry signals fire at funding-low.
3. Funding settles every 8h on Binance (00:00, 08:00, 16:00 UTC). We compute
   funding received/paid per settlement that occurs within the hold window.
4. Fees: 0.04% taker × 4 legs (spot buy, spot sell, perp sell, perp buy) = 0.16%
   round-trip. Slippage: 0.02% × 4 legs = 0.08% round-trip.
5. Entry signal: we reuse FundingFadeV1 indicators — funding < rolling_mean - 1σ
   (500-period window), ADX > 25, volume > 1.5× 20-SMA, BTC > SMA50 AND SMA200.
   All computed on 1h spot candles (matches live).
6. Exit: ROI schedule collapsed to: "hold for fixed H hours" — since price is
   hedged, ROI rules based on price can't fire. We use the directional strategy's
   observed mean holding period (~12h from ROI 360-720min band) as proxy.
   Sensitivity sweep: test 8h, 16h, 24h, 48h.
7. Pairlist: static whitelist of 19 non-BTC pairs (BTC is macro gate only).
   NOT running full DynamicPairlistMixin — we accept minor over-counting of
   illiquid-pair trades. Whitelist comes from live config.
8. Regime period: 2023-01-01 to 2026-04-16 (end of aligned data).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Try talib; fallback to minimal ADX impl if unavailable outside container
try:
    import talib
    HAS_TALIB = True
except ImportError:
    HAS_TALIB = False


DATA = Path("/Users/palmer/ft_userdata/user_data/data/binance")
OUT = Path("/Users/palmer/ft_userdata/delta_neutral_poc")

PAIRS = [
    "ADA_USDT", "ARB_USDT", "AVAX_USDT", "BCH_USDT", "BNB_USDT", "DOGE_USDT",
    "ENA_USDT", "ETH_USDT", "HBAR_USDT", "LINK_USDT", "LTC_USDT", "NEAR_USDT",
    "SOL_USDT", "SUI_USDT", "TAO_USDT", "TRX_USDT", "UNI_USDT", "XRP_USDT",
    "ZEC_USDT",
]

# Config
FUNDING_LOOKBACK = 500
ADX_THR = 25
VOL_MULT = 1.5
VOL_SMA = 20
FEE_PER_LEG = 0.0004
SLIP_PER_LEG = 0.0002
ROUNDTRIP_COST = 4 * (FEE_PER_LEG + SLIP_PER_LEG)  # 0.24% total
HOLD_HOURS_VARIANTS = [8, 16, 24, 48]
MAX_OPEN = 3
STAKE_USD = 200.0 / MAX_OPEN  # mirror live $200/3 = $66.67 per position
START_EQUITY = 200.0


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if HAS_TALIB:
        return pd.Series(
            talib.ADX(df["high"].values, df["low"].values, df["close"].values, timeperiod=period),
            index=df.index,
        )
    # Wilder ADX fallback
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def load_spot_1h(pair: str) -> pd.DataFrame:
    p = DATA / f"{pair}-1h.feather"
    df = pd.read_feather(p)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df.set_index("date").sort_index()


def load_funding(pair: str) -> pd.Series:
    """Returns funding rate indexed by settlement datetime (8h cadence)."""
    p = DATA / "funding" / f"{pair}-funding.feather"
    df = pd.read_feather(p)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    # Clean accidental .008s offset
    df["date"] = df["date"].dt.floor("h")
    df = df.drop_duplicates("date").sort_values("date")
    return df.set_index("date")["funding_rate"]


def build_pair_frame(pair: str, btc_gate: pd.Series) -> pd.DataFrame:
    spot = load_spot_1h(pair)
    fund = load_funding(pair)
    # Align funding forward-fill to 1h grid
    spot["funding_rate"] = fund.reindex(spot.index, method="ffill")
    roll_m = spot["funding_rate"].rolling(FUNDING_LOOKBACK, min_periods=50).mean()
    roll_s = spot["funding_rate"].rolling(FUNDING_LOOKBACK, min_periods=50).std()
    spot["funding_below"] = spot["funding_rate"] < (roll_m - roll_s)
    spot["adx"] = adx(spot, 14)
    spot["vol_sma"] = spot["volume"].rolling(VOL_SMA).mean()
    spot = spot.join(btc_gate, how="left")
    spot["btc_gate"] = spot["btc_gate"].ffill().fillna(0).astype(bool)
    spot["entry"] = (
        spot["funding_below"]
        & (spot["adx"] > ADX_THR)
        & (spot["volume"] > VOL_MULT * spot["vol_sma"])
        & spot["btc_gate"]
        & (spot["volume"] > 0)
    )
    return spot


def build_btc_gate() -> pd.Series:
    btc = load_spot_1h("BTC_USDT")
    btc["sma50"] = btc["close"].rolling(50).mean()
    btc["sma200"] = btc["close"].rolling(200).mean()
    gate = (btc["close"] > btc["sma50"]) & (btc["close"] > btc["sma200"])
    return gate.rename("btc_gate")


def simulate_delta_neutral(pair_frames: dict[str, pd.DataFrame], hold_hours: int) -> pd.DataFrame:
    """Scan all pairs chronologically with global MAX_OPEN enforcement.

    For each candidate entry time, compute:
      - Sum of funding rates that settle in (entry_time, entry_time + hold_hours]
      - Perp short PnL from funding = -sum_funding * stake (pay when >0, receive when <0)
      - Spot long directional PnL cancels with perp short directional PnL (delta-neutral)
      - Net = funding_pnl - ROUNDTRIP_COST * stake
    """
    # Build a flat (time, pair, entry) list
    events = []
    for pair, df in pair_frames.items():
        sig = df[df["entry"]].index
        for ts in sig:
            events.append((ts, pair))
    events.sort()

    open_slots = []  # list of (close_time, pair)
    trades = []

    for ts, pair in events:
        # Retire slots that have closed
        open_slots = [(ct, p) for ct, p in open_slots if ct > ts]
        if len(open_slots) >= MAX_OPEN:
            continue
        # Avoid duplicate on same pair concurrently
        if any(p == pair for _, p in open_slots):
            continue

        close_time = ts + pd.Timedelta(hours=hold_hours)
        df = pair_frames[pair]
        # Sum funding rates whose settlement falls in (ts, close_time]
        # Funding rate series: we use the rate at each 8h settlement boundary
        fund_series = df["funding_rate"]
        # The funding_rate column was ffilled to 1h; get raw 8h settlements
        # A settlement happens at hours 00, 08, 16 UTC. Rate effective at that settlement.
        settlement_mask = fund_series.index.hour.isin([0, 8, 16])
        settlements = fund_series[settlement_mask]
        in_window = settlements[(settlements.index > ts) & (settlements.index <= close_time)]
        funding_sum = in_window.sum()
        # Perp SHORT receives when funding>0, pays when <0
        funding_pnl_pct = -funding_sum  # short-perp carry
        net_pct = funding_pnl_pct - ROUNDTRIP_COST
        trades.append({
            "entry_time": ts,
            "exit_time": close_time,
            "pair": pair,
            "hold_hours": hold_hours,
            "funding_sum": funding_sum,
            "n_settlements": len(in_window),
            "funding_pnl_pct": funding_pnl_pct,
            "fee_slip_pct": ROUNDTRIP_COST,
            "net_pct": net_pct,
            "net_usd": net_pct * STAKE_USD,
        })
        open_slots.append((close_time, pair))

    return pd.DataFrame(trades)


def simulate_directional(pair_frames: dict[str, pd.DataFrame], hold_hours: int) -> pd.DataFrame:
    """Baseline: directional SPOT long with same entry signal, fixed hold period.

    PnL = spot_close(t+H) / spot_close(t) - 1 - 2*(FEE+SLIP)
    Approximates FundingFadeV1 — not exact (live uses ROI ladder) but same
    regime-sensitivity profile.
    """
    events = []
    for pair, df in pair_frames.items():
        sig = df[df["entry"]].index
        for ts in sig:
            events.append((ts, pair))
    events.sort()
    open_slots = []
    trades = []
    for ts, pair in events:
        open_slots = [(ct, p) for ct, p in open_slots if ct > ts]
        if len(open_slots) >= MAX_OPEN:
            continue
        if any(p == pair for _, p in open_slots):
            continue
        close_time = ts + pd.Timedelta(hours=hold_hours)
        df = pair_frames[pair]
        try:
            entry_px = df.loc[ts, "close"]
            # Find nearest close price at/before close_time
            exit_slice = df.loc[:close_time]
            if len(exit_slice) == 0:
                continue
            exit_px = exit_slice["close"].iloc[-1]
        except (KeyError, IndexError):
            continue
        if entry_px <= 0:
            continue
        price_pct = exit_px / entry_px - 1.0
        net_pct = price_pct - 2 * (FEE_PER_LEG + SLIP_PER_LEG)  # 2 legs for spot-only
        trades.append({
            "entry_time": ts,
            "exit_time": close_time,
            "pair": pair,
            "hold_hours": hold_hours,
            "price_pct": price_pct,
            "net_pct": net_pct,
            "net_usd": net_pct * STAKE_USD,
        })
        open_slots.append((close_time, pair))
    return pd.DataFrame(trades)


def compute_metrics(trades: pd.DataFrame, start_equity: float = START_EQUITY) -> dict:
    if trades.empty:
        return {"trades": 0}
    t = trades.sort_values("exit_time").reset_index(drop=True)
    t["equity"] = start_equity + t["net_usd"].cumsum()
    wins = t[t["net_usd"] > 0]["net_usd"].sum()
    losses = -t[t["net_usd"] < 0]["net_usd"].sum()
    pf = wins / losses if losses > 0 else float("inf")
    ret_pct = t["equity"].iloc[-1] / start_equity - 1
    # Drawdown
    peak = t["equity"].cummax()
    dd_series = (t["equity"] - peak) / peak
    max_dd = dd_series.min()
    # Sharpe (daily resample)
    daily = t.set_index("exit_time")["net_usd"].resample("1D").sum() / start_equity
    if daily.std() > 0:
        sharpe = daily.mean() / daily.std() * np.sqrt(365)
    else:
        sharpe = 0.0
    # Sortino
    dn = daily[daily < 0]
    sortino = daily.mean() / dn.std() * np.sqrt(365) if len(dn) and dn.std() > 0 else 0.0
    # Calmar
    years = (t["exit_time"].max() - t["entry_time"].min()).days / 365.25
    cagr = (1 + ret_pct) ** (1 / years) - 1 if years > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd < 0 else 0
    months = max(years * 12, 1)
    return {
        "trades": len(t),
        "wr": (t["net_usd"] > 0).mean(),
        "pf": pf,
        "total_return_pct": ret_pct * 100,
        "cagr_pct": cagr * 100,
        "max_dd_pct": max_dd * 100,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "trades_per_month": len(t) / months,
        "avg_trade_pct": t["net_pct"].mean() * 100,
        "median_trade_pct": t["net_pct"].median() * 100,
        "final_equity": t["equity"].iloc[-1],
    }


def funding_regime_label(ts: pd.Timestamp, btc_30d_fund: pd.Series) -> str:
    try:
        v = btc_30d_fund.asof(ts)
        if pd.isna(v):
            return "unknown"
        return "positive" if v > 0 else "negative"
    except Exception:
        return "unknown"


def build_btc_30d_funding() -> pd.Series:
    """BTC 30d rolling mean funding — regime classifier."""
    bf = load_funding("BTC_USDT")
    # 30d mean across 8h settlements (90 settlements ~= 30d)
    return bf.rolling(90, min_periods=10).mean()


def main():
    print("Building BTC gate + 30d regime series...")
    btc_gate = build_btc_gate()
    btc_30d = build_btc_30d_funding()

    print(f"Loading {len(PAIRS)} pairs...")
    frames = {}
    for p in PAIRS:
        try:
            frames[p] = build_pair_frame(p, btc_gate)
        except Exception as e:
            print(f"  skip {p}: {e}")

    print(f"Loaded {len(frames)} pair frames")

    # Range clip
    start = pd.Timestamp("2023-01-01", tz="UTC")
    end = pd.Timestamp("2026-04-16", tz="UTC")
    for p in frames:
        frames[p] = frames[p].loc[start:end]

    results = {}
    for H in HOLD_HOURS_VARIANTS:
        print(f"\n=== Hold = {H}h ===")
        dn = simulate_delta_neutral(frames, H)
        dd = simulate_directional(frames, H)
        dn.to_csv(OUT / f"trades_delta_neutral_{H}h.csv", index=False)
        dd.to_csv(OUT / f"trades_directional_{H}h.csv", index=False)

        # Tag regime
        if not dn.empty:
            dn["regime"] = dn["entry_time"].apply(lambda t: funding_regime_label(t, btc_30d))
        if not dd.empty:
            dd["regime"] = dd["entry_time"].apply(lambda t: funding_regime_label(t, btc_30d))

        m_dn = compute_metrics(dn)
        m_dd = compute_metrics(dd)
        print("Delta-neutral:", json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in m_dn.items()}, default=str))
        print("Directional:  ", json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in m_dd.items()}, default=str))

        # Regime breakdown
        regime_split_dn = {}
        regime_split_dd = {}
        for reg in ["positive", "negative", "unknown"]:
            sub_dn = dn[dn.get("regime") == reg] if not dn.empty else dn
            sub_dd = dd[dd.get("regime") == reg] if not dd.empty else dd
            regime_split_dn[reg] = compute_metrics(sub_dn)
            regime_split_dd[reg] = compute_metrics(sub_dd)

        # Oct 10-11 2025 window
        adl_start = pd.Timestamp("2025-10-08", tz="UTC")
        adl_end = pd.Timestamp("2025-10-15", tz="UTC")
        dn_adl = dn[(dn["entry_time"] >= adl_start) & (dn["entry_time"] <= adl_end)] if not dn.empty else dn
        dd_adl = dd[(dd["entry_time"] >= adl_start) & (dd["entry_time"] <= adl_end)] if not dd.empty else dd

        results[f"H{H}"] = {
            "delta_neutral": m_dn,
            "directional": m_dd,
            "regime_delta_neutral": regime_split_dn,
            "regime_directional": regime_split_dd,
            "adl_oct_2025": {
                "delta_neutral": compute_metrics(dn_adl),
                "directional": compute_metrics(dd_adl),
                "dn_trade_count": len(dn_adl),
                "dd_trade_count": len(dd_adl),
            },
        }

    with open(OUT / "results.json", "w") as f:
        json.dump(results, f, default=str, indent=2)

    print(f"\nResults written to {OUT / 'results.json'}")


if __name__ == "__main__":
    main()
