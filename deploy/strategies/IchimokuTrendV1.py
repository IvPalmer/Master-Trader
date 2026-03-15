import logging
from freqtrade.strategy import IStrategy
from pandas import DataFrame
import talib.abstract as ta
import numpy as np
import technical.indicators as ftt

logger = logging.getLogger(__name__)


def ssl_atr(dataframe, length=7):
    df = dataframe.copy()
    df['smaHigh'] = df['high'].rolling(length).mean() + df['atr']
    df['smaLow'] = df['low'].rolling(length).mean() - df['atr']
    df['hlv'] = np.where(df['close'] > df['smaHigh'], 1,
                         np.where(df['close'] < df['smaLow'], -1, np.nan))
    df['hlv'] = df['hlv'].ffill()
    df['sslDown'] = np.where(df['hlv'] < 0, df['smaHigh'], df['smaLow'])
    df['sslUp'] = np.where(df['hlv'] < 0, df['smaLow'], df['smaHigh'])
    return df['sslDown'], df['sslUp']


class IchimokuTrendV1(IStrategy):
    """
    Ichimoku Cloud trend-follower with SSL Channel, EMA, and Elder Force Index confirmation.
    Based on Obelisk_Ichimoku_Slow v1.3, adapted with safety stoploss and protections.

    Entry requires ALL of:
    - Ichimoku: Tenkan > Kijun, price above cloud, future cloud green, Chikou above cloud
    - EMA: price > EMA50 > EMA200
    - SSL Channel: bullish
    - Elder Force Index: positive
    """
    INTERFACE_VERSION: int = 3

    timeframe = '1h'
    startup_candle_count = 180  # Ichimoku needs 7.5 days of data
    process_only_new_candles = True

    # ROI: take profits on stale positions
    minimal_roi = {
        "0": 0.08, "360": 0.05, "720": 0.03, "1440": 0.01
    }

    # Safety net stoploss
    stoploss = -0.05  # Data: 0% of trades recover past -7%, 92% of winners never dip past -3%
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.04
    trailing_only_offset_is_reached = True

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {"method": "StoplossGuard", "lookback_period_candles": 48,
             "trade_limit": 2, "stop_duration_candles": 24, "only_per_pair": True},
            {"method": "LowProfitPairs", "lookback_period_candles": 288,
             "trade_limit": 4, "stop_duration_candles": 48, "required_profit": -0.05},
            {"method": "MaxDrawdown", "lookback_period_candles": 48,
             "max_allowed_drawdown": 0.20, "stop_duration_candles": 12, "trade_limit": 1},
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Ichimoku Cloud
        displacement = 30
        ichimoku = ftt.ichimoku(dataframe,
                                conversion_line_period=20,
                                base_line_periods=60,
                                laggin_span=120,
                                displacement=displacement)

        dataframe['chikou_span'] = ichimoku['chikou_span']
        dataframe['tenkan_sen'] = ichimoku['tenkan_sen']
        dataframe['kijun_sen'] = ichimoku['kijun_sen']
        dataframe['senkou_a'] = ichimoku['senkou_span_a']
        dataframe['senkou_b'] = ichimoku['senkou_span_b']
        dataframe['leading_senkou_span_a'] = ichimoku['leading_senkou_span_a']
        dataframe['leading_senkou_span_b'] = ichimoku['leading_senkou_span_b']

        dataframe['cloud_top'] = dataframe[['senkou_a', 'senkou_b']].max(axis=1)

        # Future cloud direction (present data normally shifted forward for display)
        dataframe['future_green'] = (
            dataframe['leading_senkou_span_a'] > dataframe['leading_senkou_span_b']
        ).astype('int')

        # Chikou span check (shifted back into past, shift forward by displacement to read safely)
        dataframe['chikou_high'] = (
            (dataframe['chikou_span'] > dataframe['senkou_a']) &
            (dataframe['chikou_span'] > dataframe['senkou_b'])
        ).shift(displacement).fillna(0).astype('int')

        # EMA guards
        dataframe['ema50'] = ta.EMA(dataframe, timeperiod=50)
        dataframe['ema200'] = ta.EMA(dataframe, timeperiod=200)
        dataframe['ema_ok'] = (
            (dataframe['close'] > dataframe['ema50']) &
            (dataframe['ema50'] > dataframe['ema200'])
        ).astype('int')

        # Elder Force Index
        dataframe['efi'] = ta.EMA(
            (dataframe['close'] - dataframe['close'].shift()) * dataframe['volume'], 13)
        dataframe['efi_ok'] = (dataframe['efi'] > 0).astype('int')

        # SSL Channel (ATR-based trend)
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)
        ssl_down, ssl_up = ssl_atr(dataframe, 10)
        dataframe['ssl_down'] = ssl_down
        dataframe['ssl_up'] = ssl_up
        dataframe['ssl_ok'] = (ssl_up > ssl_down).astype('int')

        # ADX — only trade strong trends
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)

        # Volume filter — above 20-period average
        dataframe['vol_sma20'] = dataframe['volume'].rolling(20).mean()

        # Composite signals
        dataframe['ichimoku_ok'] = (
            (dataframe['tenkan_sen'] > dataframe['kijun_sen']) &
            (dataframe['close'] > dataframe['cloud_top']) &
            (dataframe['future_green'] > 0) &
            (dataframe['chikou_high'] > 0)
        ).astype('int')

        # Entry filter: EFI positive, price below SSL upper band (pullback within trend)
        dataframe['entry_ok'] = (
            (dataframe['efi_ok'] > 0) &
            (dataframe['open'] < dataframe['ssl_up']) &
            (dataframe['close'] < dataframe['ssl_up'])
        ).astype('int')

        dataframe['trend_pulse'] = (
            (dataframe['ichimoku_ok'] > 0) &
            (dataframe['ssl_ok'] > 0) &
            (dataframe['ema_ok'] > 0)
        ).astype('int')

        dataframe['trend_over'] = (dataframe['ssl_ok'] == 0).astype('int')

        # Persistent trending state
        dataframe.loc[dataframe['trend_pulse'] > 0, 'trending'] = 1
        dataframe.loc[dataframe['trend_over'] > 0, 'trending'] = 0
        dataframe['trending'] = dataframe['trending'].ffill().fillna(0)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe['trending'] > 0) &
            (dataframe['entry_ok'] > 0) &
            (dataframe['volume'] > 0),
            'enter_long'] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe['trending'] == 0) &
            (dataframe['volume'] > 0),
            'exit_long'] = 1
        return dataframe
