"""
ShortKeltnerV1 — Inverse-Keltner short-side mean-reversion (bear-regime gated).

Thesis (2026-05-28):
  Every short we killed (BearRegime, BearCrash, FundingShort) was TREND-FOLLOWING
  — it shorted breakdowns / fresh lows and got squeezed out by relief rallies.
  Post-mortem verdict: "entries happen at local-low prices that are about to
  mean-revert." This strategy shorts the OTHER side of that: it fades the relief
  RALLY. In a confirmed BTC downtrend, when a pair pokes above its upper Keltner
  band (overbought extreme) and rolls back below it, short the rejection.

  Structural inverse of the validated KeltnerBounceV1 long (FT-native PF 1.58,
  +51% / 3.3yr): the long enters on a cross *above* the lower band; this short
  enters on a cross *below* the upper band.

Regime gate (v1.1, 2026-05-28): raw gate (close<SMA50 & <SMA200) was breakeven
  in the 2024/2025 bull because it shorted bull-market dips that ripped back.
  Added BTC SMA50 slope<0 (downtrend has direction) — true only in sustained
  downtrends, not bull pullbacks. Same slope filter as FundingFade gate-v2.

Signal (futures SHORT):
  - REGIME GATE (BTC 1h): close < SMA50 AND close < SMA200 AND SMA50 sloping down
    (24h).
  - ENTRY: close crosses back below upper Keltner band (SMA25 + 2.5*ATR25) after
    poking above it (rally rejection). Confirm: volume > 1.75x vol_SMA20 AND RSI
    overbought (>60) within the prior 2 bars.
  - EXIT: fast ROI ladder + SL -5% + 36h time-stop + regime-flip (BTC reclaims
    SMA50) + pair oversold (RSI < 30).

Sizing: 2x isolated leverage; stake / max_open from config.

Generated 2026-05-28.
"""

import logging

import pandas as pd
import talib.abstract as ta
from freqtrade.strategy import IStrategy, informative
from pandas import DataFrame

logger = logging.getLogger(__name__)


class ShortKeltnerV1(IStrategy):
    INTERFACE_VERSION = 3

    can_short = True
    trading_mode = "futures"
    margin_mode = "isolated"
    timeframe = "1h"

    minimal_roi = {
        "0": 0.06,
        "360": 0.04,
        "720": 0.025,
        "1440": 0.015,
        "2160": 0.0,
    }

    stoploss = -0.05
    trailing_stop = False

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    startup_candle_count = 250

    kelt_period = 25
    kelt_atr_mult = 2.5
    vol_multiplier = 1.75
    vol_sma_period = 20
    rsi_overbought = 60
    btc_slope_lookback = 24

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 4},
            {"method": "StoplossGuard", "lookback_period_candles": 48,
             "trade_limit": 3, "stop_duration_candles": 24, "only_per_pair": False},
            {"method": "MaxDrawdown", "lookback_period_candles": 72,
             "max_allowed_drawdown": 0.12, "stop_duration_candles": 48, "trade_limit": 2},
        ]

    def leverage(self, pair, current_time, current_rate, proposed_leverage,
                 max_leverage, entry_tag, side, **kwargs) -> float:
        return min(2.0, max_leverage)

    @informative("1h", "BTC/USDT:USDT")
    def populate_indicators_btc_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["sma50"] = ta.SMA(dataframe, timeperiod=50)
        dataframe["sma200"] = ta.SMA(dataframe, timeperiod=200)
        dataframe["sma50_slope"] = dataframe["sma50"] - dataframe["sma50"].shift(self.btc_slope_lookback)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        sma = dataframe["close"].rolling(self.kelt_period).mean()
        atr = _atr(dataframe, self.kelt_period)
        dataframe["kelt_upper"] = sma + self.kelt_atr_mult * atr
        dataframe["vol_sma"] = dataframe["volume"].rolling(self.vol_sma_period).mean()
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        dataframe["btc_bear"] = (
            (dataframe["btc_usdt_close_1h"] < dataframe["btc_usdt_sma50_1h"])
            & (dataframe["btc_usdt_close_1h"] < dataframe["btc_usdt_sma200_1h"])
            & (dataframe["btc_usdt_sma50_slope_1h"] < 0)
        ).astype(int)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        rsi_was_overbought = (
            (dataframe["rsi"].shift(1) > self.rsi_overbought)
            | (dataframe["rsi"].shift(2) > self.rsi_overbought)
        )
        dataframe.loc[
            (
                (dataframe["close"] < dataframe["kelt_upper"])
                & (dataframe["close"].shift(1) >= dataframe["kelt_upper"].shift(1))
                & (dataframe["volume"] > self.vol_multiplier * dataframe["vol_sma"])
                & rsi_was_overbought
                & (dataframe["btc_bear"] == 1)
                & (dataframe["volume"] > 0)
            ),
            ["enter_short", "enter_tag"],
        ] = (1, "kelt_upper_reject")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (
                    (dataframe["btc_usdt_close_1h"] > dataframe["btc_usdt_sma50_1h"])
                    | (dataframe["rsi"] < 30)
                )
                & (dataframe["volume"] > 0)
            ),
            ["exit_short", "exit_tag"],
        ] = (1, "regime_flip_or_oversold")
        return dataframe

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        if not trade.is_short:
            return None
        hours = (current_time - trade.open_date_utc).total_seconds() / 3600
        if hours >= 36:
            return "time_exit_36h"
        return None


def _atr(df: DataFrame, period: int) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()
