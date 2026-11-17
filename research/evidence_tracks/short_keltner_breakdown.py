"""Bear-breakdown short redesign: frozen signal + first-touch scorer (GH #28).

SEPARATE from ShortKeltnerV2HL (its dry curve stays intact as lineage). Spec frozen in
preregistration `shortkeltner-breakdown-eval-2026-10-12` before any scoring:

  gate    : unchanged btc_bear (BTC 1h close < SMA50 and < SMA200, SMA50 slope(24) < 0,
            BTC close < daily SMA200). Passed in as a boolean column; NOT loosened.
  trigger : close crosses DOWN through the lower Keltner band (SMA25 - 2.5*ATR25)
            on volume > 1.75 * SMA20(volume).
  entry   : next candle open (causal: signal known at candle close).
  exits   : stop entry + 2.0*ATR25(signal bar); target entry - 2R (R = stop distance);
            time exit at close of the 72nd bar; whichever is first. Same-bar stop+target
            is scored as the stop. No parameter is swept; one exit design is evaluated.
  costs   : primary 10 bps/side, zero funding carry (HL short carry is a tailwind that is
            NOT credited); sensitivity 5/10/20 bps/side.
  null    : seeded random masks over gate-open candles with the signal's own pass rate.
Frequency is not evidence of profitability; the report refuses a profit claim below
MIN_TRADES.
"""
import numpy as np
import pandas as pd

KELT_PERIOD, ATR_MULT, VOL_MULT, VOL_SMA = 25, 2.5, 1.75, 20
STOP_ATR, TARGET_R, MAX_HOLD = 2.0, 2.0, 72
COST_BPS_GRID = (5, 10, 20)
PRIMARY_BPS = 10
MIN_TRADES = 30


def _atr(df, period):
    tr = pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(),
                    (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    sma = df["close"].rolling(KELT_PERIOD).mean()
    df["atr"] = _atr(df, KELT_PERIOD)
    df["kelt_lower"] = sma - ATR_MULT * df["atr"]
    df["vol_ok"] = df["volume"] > VOL_MULT * df["volume"].rolling(VOL_SMA).mean()
    return df


def breakdown_signal(df: pd.DataFrame, btc_bear: pd.Series) -> pd.Series:
    """Boolean signal at candle close. btc_bear must be aligned to df.index."""
    cross = (df["close"] < df["kelt_lower"]) & (df["close"].shift(1) >= df["kelt_lower"].shift(1))
    return (cross & df["vol_ok"] & btc_bear.astype(bool) & (df["volume"] > 0)).fillna(False)


def score_signal(df: pd.DataFrame, i: int):
    """Short opened at open of bar i+1. Returns (R multiple gross of costs, exit_reason, hold bars, risk_frac)
    or None if the entry bar or ATR is unavailable. Costs are applied by net_r()."""
    if i + 1 >= len(df) or not np.isfinite(df["atr"].iloc[i]):
        return None
    entry = df["open"].iloc[i + 1]
    risk = STOP_ATR * df["atr"].iloc[i]
    if not (entry > 0 and risk > 0):
        return None
    stop, target = entry + risk, entry - TARGET_R * risk
    last = min(i + MAX_HOLD, len(df) - 1)       # bar 72 counted from the entry bar
    for j in range(i + 1, last + 1):
        hi, lo = df["high"].iloc[j], df["low"].iloc[j]
        if hi >= stop:                           # stop first on any ambiguity
            return (-1.0, "stop", j - i, risk / entry)
        if lo <= target:
            return (TARGET_R, "target", j - i, risk / entry)
    if last - i < MAX_HOLD:                      # data ended before the time exit
        return None
    return ((entry - df["close"].iloc[last]) / risk, "time", last - i, risk / entry)


def net_r(gross_r, risk_frac, bps):
    """Round-trip cost in R: 2 * bps/1e4 of notional, divided by risk as fraction of notional."""
    return gross_r - 2 * bps / 1e4 / risk_frac


def evaluate(df: pd.DataFrame, btc_bear: pd.Series, min_gap=MAX_HOLD):
    """Score every signal, skipping signals that fire while a prior one would still be open
    (one position per pair). Returns list of dicts."""
    df = add_indicators(df)
    sig = breakdown_signal(df, btc_bear)
    trades, busy_until = [], -1
    for i in np.flatnonzero(sig.to_numpy()):
        if i <= busy_until:
            continue
        s = score_signal(df, int(i))
        if s is None:
            continue
        gross, reason, hold, risk_frac = s
        trades.append({"i": int(i), "date": df["date"].iloc[i], "gross_r": gross, "reason": reason,
                       "hold": hold, "risk_frac": risk_frac})
        busy_until = i + hold
    return trades


def placebo_trades(df: pd.DataFrame, btc_bear: pd.Series, rate: float, seed: int):
    """Same scorer on a seeded random mask over gate-open candles at the signal's pass rate."""
    df = add_indicators(df)
    rng = np.random.default_rng(seed)
    eligible = btc_bear.astype(bool).to_numpy() & (df["volume"] > 0).to_numpy()
    mask = eligible & (rng.random(len(df)) < rate)
    trades, busy_until = [], -1
    for i in np.flatnonzero(mask):
        if i <= busy_until:
            continue
        s = score_signal(df, int(i))
        if s is None:
            continue
        trades.append({"i": int(i), "gross_r": s[0], "reason": s[1], "hold": s[2], "risk_frac": s[3]})
        busy_until = i + s[2]
    return trades


def summarize(trades, bps=PRIMARY_BPS):
    r = [net_r(t["gross_r"], t["risk_frac"], bps) for t in trades]
    out = {"n": len(r), "mean_net_r": round(float(np.mean(r)), 4) if r else None,
           "win_rate": round(float(np.mean([x > 0 for x in r])), 3) if r else None,
           "bps_per_side": bps}
    out["profit_claim"] = "none: below MIN_TRADES" if len(r) < MIN_TRADES else "descriptive only"
    return out


def report(df, btc_bear, n_placebo=200):
    trades = evaluate(df, btc_bear)
    gate_candles = int((btc_bear.astype(bool) & (df["volume"] > 0)).sum())
    rate = len(trades) / gate_candles if gate_candles else 0.0
    placebo = [summarize(placebo_trades(df, btc_bear, rate, s))["mean_net_r"] for s in range(1, n_placebo + 1)]
    placebo = sorted(p for p in placebo if p is not None)
    real = summarize(trades)
    return {"signals_scored": len(trades), "by_cost": {b: summarize(trades, b) for b in COST_BPS_GRID},
            "exit_reasons": {k: sum(t["reason"] == k for t in trades) for k in ("stop", "target", "time")},
            "placebo_mean_net_r_p90": placebo[int(0.9 * (len(placebo) - 1))] if placebo else None,
            "beats_placebo_p90": bool(placebo and real["mean_net_r"] is not None
                                      and real["mean_net_r"] > placebo[int(0.9 * (len(placebo) - 1))]),
            "primary": real}
