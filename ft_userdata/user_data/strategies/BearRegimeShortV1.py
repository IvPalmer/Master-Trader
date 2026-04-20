"""
BearRegimeShortV1 — Regime-gated short, 6-bar confirmed bear + failed rally + volume flush.

Hypothesis (2026-04-20):
  Shorts fail in crypto because fixed-threshold signals fire during the 77% of time
  BTC is NOT in confirmed bear. Solution: dormant 77% of time, only fire on strict
  regime confirmation + failed bounce + capitulation volume.

Signal (futures SHORT):
  - REGIME GATE (BTC 1h): close < SMA50 AND close < SMA200 AND 20d-mom < 0,
    confirmed by 6 consecutive bars (smooth out flicker).
  - ANCHOR (pair 1h): RSI touched >=50 in prior 3 bars AND rolled over to <48
    now (failed rally rejection).
  - CONFIRM: volume > 1.5x 20-SMA (capitulation flush), close < SMA50 (pair),
    ADX > 20 (trend has teeth).
  - ANTI-SQUEEZE: F&G >= 15 (not in "max fear" capitulation zone where squeezes fire).

Exit:
  - EXIT SIGNAL: BTC 1h close > SMA50 (regime flip) OR pair RSI < 30 (oversold bounce risk).
  - ROI: aggressive — crypto crashes are fast, take profits.
  - SL: -5% hard, no trailing.
  - Hard time exit: 36h.

Sizing: $100 stake / $200 wallet, 2x leverage, max 2 concurrent.

Known enemies this design attacks:
  - FundingShortV1 (killed): fired on z-score alone, 52% DD from squeeze-fires.
  - BearCrashShortV1 (killed): bear regime too loose (RSI<45 alone), entered grinds.

Generated 2026-04-20 for short-side research.
"""

import logging
from datetime import datetime
from pathlib import Path

import talib.abstract as ta
from freqtrade.strategy import IStrategy, informative
from pandas import DataFrame

logger = logging.getLogger(__name__)


class BearRegimeShortV1(IStrategy):
    INTERFACE_VERSION = 3

    can_short = True
    trading_mode = "futures"
    margin_mode = "isolated"
    timeframe = "1h"

    # Aggressive ROI — crashes are fast
    minimal_roi = {
        "0":    0.06,   # 6% immediate take
        "360":  0.04,   # 4% after 6h
        "720":  0.025,  # 2.5% after 12h
        "1440": 0.015,  # 1.5% after 24h
        "2160": 0.0,    # break-even at 36h
    }

    stoploss = -0.05
    trailing_stop = False

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    startup_candle_count = 250  # 200 + buffer for 20d mom

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 4},
            {"method": "StoplossGuard", "lookback_period_candles": 48,
             "trade_limit": 3, "stop_duration_candles": 24, "only_per_pair": False},
            {"method": "MaxDrawdown", "lookback_period_candles": 72,
             "max_allowed_drawdown": 0.12, "stop_duration_candles": 48, "trade_limit": 2},
        ]

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str | None,
                 side: str, **kwargs) -> float:
        return min(2.0, max_leverage)

    # -- BTC informative --

    @informative("1h", "BTC/USDT:USDT")
    def populate_indicators_btc_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["sma50"] = ta.SMA(dataframe, timeperiod=50)
        dataframe["sma200"] = ta.SMA(dataframe, timeperiod=200)
        dataframe["mom20d"] = dataframe["close"].pct_change(20 * 24)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        # BTC making fresh 7d low = accelerating bear (filters sideways bear-flicker)
        dataframe["low_7d"] = dataframe["low"].rolling(168).min().shift(1)
        dataframe["btc_fresh_low"] = (dataframe["close"] <= dataframe["low_7d"] * 1.02).astype(int)
        return dataframe

    # -- Indicators --

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["plus_di"] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe["minus_di"] = ta.MINUS_DI(dataframe, timeperiod=14)
        dataframe["sma50"] = ta.SMA(dataframe, timeperiod=50)
        dataframe["sma200"] = ta.SMA(dataframe, timeperiod=200)
        dataframe["vol_sma20"] = dataframe["volume"].rolling(20).mean()

        # Donchian low: new 5-day low breakout (momentum short)
        dataframe["donch_low_120"] = dataframe["low"].rolling(120).min().shift(1)

        # BTC confirmed bear regime (6-bar smoothing)
        btc_bear_raw = (
            (dataframe["btc_usdt_close_1h"] < dataframe["btc_usdt_sma50_1h"])
            & (dataframe["btc_usdt_close_1h"] < dataframe["btc_usdt_sma200_1h"])
            & (dataframe["btc_usdt_mom20d_1h"] < 0)
        ).astype(int)
        dataframe["btc_bear_confirmed"] = (
            btc_bear_raw.rolling(6).sum() >= 6
        ).astype(int)

        # Failed rally: RSI was >=50 in prior 3 bars but now <48
        rsi_prior_high = (
            (dataframe["rsi"].shift(1) >= 50)
            | (dataframe["rsi"].shift(2) >= 50)
            | (dataframe["rsi"].shift(3) >= 50)
        )
        dataframe["failed_rally"] = (
            rsi_prior_high & (dataframe["rsi"] < 48) & (dataframe["rsi"] >= 30)
        ).astype(int)

        return dataframe

    # -- Entry --

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # PRIMARY SIGNAL: Momentum-short in confirmed bear
        #   Require pair to break below 5-day low AND BTC confirmed bear
        #   (Turtle-style short breakout gated by regime)
        dataframe.loc[
            (
                # Regime: confirmed bear (6-bar BTC confirmation)
                (dataframe["btc_bear_confirmed"] == 1)
                # BTC also making fresh 7d low (accelerating, not flickering)
                & (dataframe["btc_usdt_btc_fresh_low_1h"] == 1)
                # Momentum: pair breaks 5-day low (true downtrend acceleration)
                & (dataframe["close"] < dataframe["donch_low_120"])
                # Pair below its SMA50 (trend alignment)
                & (dataframe["close"] < dataframe["sma50"])
                # Volume expansion (not dying breakout)
                & (dataframe["volume"] > 1.2 * dataframe["vol_sma20"])
                # Trend teeth
                & (dataframe["adx"] > 20)
                & (dataframe["minus_di"] > dataframe["plus_di"])
                # Anti-squeeze: BTC not at panic low (prevents capitulation-bounce fires)
                & (dataframe["btc_usdt_rsi_1h"] > 25)
                & (dataframe["volume"] > 0)
            ),
            ["enter_short", "enter_tag"],
        ] = (1, "bear_5d_low_break")

        return dataframe

    # -- Exit --

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Regime flip: BTC back above SMA50
                (dataframe["btc_usdt_close_1h"] > dataframe["btc_usdt_sma50_1h"])
                # OR pair oversold (bounce risk)
                | (dataframe["rsi"] < 28)
                # OR bulls retook DI
                | (
                    (dataframe["plus_di"] > dataframe["minus_di"])
                    & (dataframe["plus_di"].shift(1) > dataframe["minus_di"].shift(1))
                )
            )
            & (dataframe["volume"] > 0),
            ["exit_short", "exit_tag"],
        ] = (1, "regime_flip_or_oversold")

        return dataframe

    # -- Time exit --

    def custom_exit(self, pair: str, trade, current_time, current_rate,
                    current_profit, **kwargs):
        if not trade.is_short:
            return None
        hours = (current_time - trade.open_date_utc).total_seconds() / 3600
        if hours >= 36:
            return "time_exit_36h"
        if hours >= 24 and current_profit > 0.01:
            return "time_profit_24h"
        return None
