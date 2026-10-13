"""KeltnerBounceV1 gate-conditional setup frequency (GH #28). Frequency only:
no P&L, no exit model, no threshold sweep. Mirrors the deployed entry term by term
so the funnel says which term binds, before anyone proposes changing a filter.

    python3 keltner_setup_frequency.py pairs.json > funnel.json
    # pairs.json: {"ADA/USDT": "ada.csv", ..., "BTC/USDT": "btc.csv"}; CSV columns
    # date(ms or ISO),open,high,low,close,volume  (1h candles)
"""
import json
import sys

import pandas as pd

KELT_PERIOD, ATR_MULT, VOL_MULT, VOL_SMA, BTC_SMA = 25, 2.5, 1.75, 20, 50  # == KeltnerBounceV1


def _atr(df, period):
    tr = pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(),
                    (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def terms(df: pd.DataFrame, btc: pd.DataFrame) -> pd.DataFrame:
    """Boolean entry terms per candle. BTC gate uses the same-timestamp BTC close/SMA50
    (the candle's own close, as the deployed informative merge does)."""
    lower = df["close"].rolling(KELT_PERIOD).mean() - ATR_MULT * _atr(df, KELT_PERIOD)
    cross = (df["close"] > lower) & (df["close"].shift(1) <= lower.shift(1))
    vol = df["volume"] > VOL_MULT * df["volume"].rolling(VOL_SMA).mean()
    b = btc.set_index("date")["close"]
    gate = (b > b.rolling(BTC_SMA).mean()).reindex(df["date"]).fillna(False).to_numpy()
    out = pd.DataFrame({"date": df["date"], "cross": cross.fillna(False), "volume": vol.fillna(False),
                        "btc_gate": gate})
    out["setup"] = out["cross"] & out["volume"] & out["btc_gate"]
    return out


def funnel(pair_terms: dict) -> dict:
    """Per-pair and fleet counts: raw cross -> +volume -> +BTC gate, with per-month rates."""
    rows, total_months = {}, 0.0
    for pair, t in pair_terms.items():
        if t.empty:
            continue
        months = (t["date"].iloc[-1] - t["date"].iloc[0]).total_seconds() / (86400 * 30.4375)
        cv = t["cross"] & t["volume"]
        rows[pair] = {"candles": int(len(t)), "months": round(months, 2), "cross": int(t["cross"].sum()),
                      "cross_volume": int(cv.sum()), "setup": int(t["setup"].sum()),
                      "gate_open_share": round(float(t["btc_gate"].mean()), 4),
                      "gate_blocked_cross_volume": int((cv & ~t["btc_gate"]).sum())}
        total_months = max(total_months, months)
    fleet_setup = sum(r["setup"] for r in rows.values())
    cv_total = sum(r["cross_volume"] for r in rows.values())
    return {"pairs": rows, "fleet_setups": fleet_setup, "fleet_cross_volume": cv_total,
            "setups_per_month": round(fleet_setup / total_months, 2) if total_months else None,
            "binding_term": ("btc_gate" if cv_total and fleet_setup / cv_total < 0.5 else "cross_or_volume")
            if rows else None}


def monthly(t: pd.DataFrame) -> dict:
    s = t.loc[t["setup"], "date"].dt.strftime("%Y-%m").value_counts().sort_index()
    return {k: int(v) for k, v in s.items()}


def load_csv(path):
    df = pd.read_csv(path)
    d = df["date"]
    df["date"] = pd.to_datetime(d, unit="ms", utc=True) if pd.api.types.is_numeric_dtype(d) else pd.to_datetime(d, utc=True)
    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    spec = json.load(open(sys.argv[1]))
    btc = load_csv(spec["BTC/USDT"])
    res = {p: terms(load_csv(f), btc) for p, f in spec.items()}
    out = funnel(res)
    out["monthly_setups"] = {p: monthly(t) for p, t in res.items()}
    print(json.dumps(out, indent=2))
