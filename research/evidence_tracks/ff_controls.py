"""Pure helpers for the FundingFade causal-funding / price-only control (GH #28).

The deployed FundingFadeV1 entry term is ``funding_below_mean`` (funding rate
below its rolling mean minus one std). These helpers build the *replacement*
columns used by the backtest-only variants in FFCausalResearch.py:

* price-only  - the funding term always passes.
* placebo     - a seeded coin flip per (pair, candle) passing at the pair's own
                unconditional rate of the real term (no hand-picked rate).
* lagged      - the real funding series delayed by ``LAG_BARS`` bars, so the
                funding *distribution and persistence* are kept but its timing
                relative to price is destroyed. Delay only moves information
                into the future of its publication, so it stays causal.
"""
import hashlib

import numpy as np
import pandas as pd

LAG_BARS = 21 * 24        # 21 days of 1h bars
FUNDING_LOOKBACK = 500    # = FundingFadeV1.funding_lookback; asserted in tests
MIN_PERIODS = 50


def funding_term(funding: pd.Series, lookback=FUNDING_LOOKBACK, min_periods=MIN_PERIODS) -> pd.Series:
    """The deployed term, recomputed: funding < rolling mean - rolling std (int 0/1)."""
    mean = funding.rolling(lookback, min_periods=min_periods).mean()
    std = funding.rolling(lookback, min_periods=min_periods).std()
    return (funding < (mean - std)).astype(int)


def price_only_term(index) -> pd.Series:
    return pd.Series(1, index=index)


def lagged_funding_term(funding: pd.Series, lag_bars=LAG_BARS) -> pd.Series:
    """Real term computed on funding delayed by lag_bars; leading bars are NaN -> 0 (fail closed)."""
    return funding_term(funding.shift(lag_bars))


def placebo_term(real_term: pd.Series, pair: str, seed: int) -> pd.Series:
    """Coin flip with the real term's own pass rate on this pair; deterministic per (pair, seed)."""
    valid = real_term.dropna()
    rate = float(valid.mean()) if len(valid) else 0.0
    digest = hashlib.sha256(f"{pair}|{seed}".encode()).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
    flips = rng.random(len(real_term)) < rate
    return pd.Series(flips.astype(int), index=real_term.index)
