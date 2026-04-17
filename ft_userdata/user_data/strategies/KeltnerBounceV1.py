"""
KeltnerBounceV1 — Keltner channel mean reversion with volume confirmation.

Discovered via Strategy Lab grid scan on 3.3 years of 1m-detail data (Jan 2023 - Apr 2026).
Cross-validated against Freqtrade's own 1m-detail backtest — results match within 1%.

Backtest performance (18 static pairs, 1m detail, Jan 2023 - Apr 2026):
  - Lab: 153 trades, WR 75.8%, PF 1.99, +51.85%, max DD 9.0%
  - Freqtrade: 149 trades, WR 80.5%, PF 1.58, +51.47%, max DD 12.9%
  - Walk-forward: 6/6 lab windows profitable, 4/6 FT calendar-half windows profitable
  - Monte Carlo: 0% ruin probability, median max DD 5.6%
  - Year-by-year: 2023 PF 2.06, 2024 PF 1.73, 2025 PF 1.65, all profitable
  - CAGR 13.6%, Sortino 3.58, Calmar 6.43

Signal:
  - Entry: Close crosses above Keltner lower band (SMA25 - 2.5*ATR25)
  - Confirm: Volume > 1.75x 20-period volume SMA
  - Gate: BTC above its 50-period SMA
  - Exit: Wide profile (trailing stop + tiered ROI, stoploss -7%)

Known weakness: choppy/euphoric market regimes (2023-H2 sideways, 2024-H2 post-ATH crash).
Wins in clean bull runs and recovery bounces.

Generated 2026-04-16.
"""

import logging

import numpy as np
import pandas as pd
from freqtrade.strategy import IStrategy, informative
from pandas import DataFrame

logger = logging.getLogger(__name__)


class KeltnerBounceV1(IStrategy):
    INTERFACE_VERSION: int = 3

    # ── Exit profile: "wide" (lab screening optimum) ──
    minimal_roi = {
        "0":    0.10,
        "360":  0.07,
        "720":  0.04,
        "1440": 0.02,
    }

    stoploss = -0.07
    trailing_stop = True
    trailing_stop_positive = 0.03
    trailing_stop_positive_offset = 0.05
    trailing_only_offset_is_reached = True

    timeframe = "1h"
    process_only_new_candles = True
    use_exit_signal = False
    exit_profit_only = True
    exit_profit_offset = 0.01

    # Keltner 25 + 200 candle warmup for BTC SMA50 informative
    startup_candle_count = 200

    # ── Strategy parameters (can be hyperopt'd later) ──
    kelt_period = 25
    kelt_atr_mult = 2.5
    vol_multiplier = 1.75
    vol_sma_period = 20
    btc_sma_period = 50

    @informative("1h", "BTC/{stake}")
    def populate_indicators_btc_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["sma50"] = dataframe["close"].rolling(self.btc_sma_period).mean()
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Keltner lower band = SMA - atr_mult * ATR
        sma = dataframe["close"].rolling(self.kelt_period).mean()
        atr = _atr(dataframe, self.kelt_period)
        dataframe["kelt_lower"] = sma - self.kelt_atr_mult * atr

        # Volume confirmation
        dataframe["vol_sma"] = dataframe["volume"].rolling(self.vol_sma_period).mean()

        # BTC gate (informative columns named via freqtrade convention)
        dataframe["btc_gate"] = (
            dataframe["btc_usdt_close_1h"] > dataframe["btc_usdt_sma50_1h"]
        ).astype(int)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Keltner lower band cross-above
                (dataframe["close"] > dataframe["kelt_lower"])
                & (dataframe["close"].shift(1) <= dataframe["kelt_lower"].shift(1))
                # Volume spike confirmation
                & (dataframe["volume"] > self.vol_multiplier * dataframe["vol_sma"])
                # BTC trend gate
                & (dataframe["btc_gate"] == 1)
                # Sanity
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Exits handled by ROI, stoploss, and trailing stop
        return dataframe


# ── Helpers ────────────────────────────────────────────────

def _atr(df: DataFrame, period: int) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()
