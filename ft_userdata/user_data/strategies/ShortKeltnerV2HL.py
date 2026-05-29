"""
ShortKeltnerV2HL — Hyperliquid (USDC-margined) port of ShortKeltnerV2.

IDENTICAL logic to ShortKeltnerV2 (inverse-Keltner short-side mean-reversion +
BTC daily-200d-MA macro bear guard). ONLY difference: Hyperliquid perps are
USDC-margined (BTC/USDC:USDC), so the BTC macro-gate informatives reference
BTC/USDC:USDC and the generated columns are btc_usdc_* (not btc_usdt_*).

Purpose: FORWARD dry-run measurement instrument on Hyperliquid. Hyperliquid does
NOT serve historical OHLCV (Freqtrade: "does not support downloading ... ohlcv
data"), so this can ONLY be validated forward, not backtested. This is exactly
the on-venue OOS bar codex required before any capital. Dry-run only — no keys,
no capital. See docs/hyperliquid_short_validation_2026-05-29.md.

Generated 2026-05-29.
"""

import logging

import pandas as pd
import talib.abstract as ta
from freqtrade.strategy import IStrategy, informative
from pandas import DataFrame

logger = logging.getLogger(__name__)


class ShortKeltnerV2HL(IStrategy):
    INTERFACE_VERSION = 3

    can_short = True
    trading_mode = "futures"
    margin_mode = "isolated"
    timeframe = "1h"

    minimal_roi = {"0": 0.06, "360": 0.04, "720": 0.025, "1440": 0.015, "2160": 0.0}
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

    @informative("1d", "BTC/USDC:USDC")
    def populate_indicators_btc_1d(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["sma200"] = ta.SMA(dataframe, timeperiod=200)
        return dataframe

    @informative("1h", "BTC/USDC:USDC")
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
            (dataframe["btc_usdc_close_1h"] < dataframe["btc_usdc_sma50_1h"])
            & (dataframe["btc_usdc_close_1h"] < dataframe["btc_usdc_sma200_1h"])
            & (dataframe["btc_usdc_sma50_slope_1h"] < 0)
            & (dataframe["btc_usdc_close_1h"] < dataframe["btc_usdc_sma200_1d"])
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
                    (dataframe["btc_usdc_close_1h"] > dataframe["btc_usdc_sma50_1h"])
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
    high = df["high"]; low = df["low"]; close = df["close"]
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()
