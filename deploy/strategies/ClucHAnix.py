import freqtrade.vendor.qtpylib.indicators as qtpylib
import numpy as np
import talib.abstract as ta
from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import merge_informative_pair, DecimalParameter, stoploss_from_open, stoploss_from_absolute, RealParameter
from pandas import DataFrame, Series
from datetime import datetime

def bollinger_bands(stock_price, window_size, num_of_std):
    rolling_mean = stock_price.rolling(window=window_size).mean()
    rolling_std = stock_price.rolling(window=window_size).std()
    lower_band = rolling_mean - (rolling_std * num_of_std)
    return np.nan_to_num(rolling_mean), np.nan_to_num(lower_band)

def ha_typical_price(bars):
    res = (bars['ha_high'] + bars['ha_low'] + bars['ha_close']) / 3.
    return Series(index=bars.index, data=res)

class ClucHAnix(IStrategy):
    INTERFACE_VERSION = 3

    buy_params = {
        'bbdelta_close': 0.01965,
        'bbdelta_tail': 0.95089,
        'close_bblower': 0.00799,
        'closedelta_close': 0.00556,
        'rocr_1h': 0.54904
    }

    sell_params = {
        "pHSL": -0.08,
        "pPF_1": 0.02,
        "pPF_2": 0.047,
        "pSL_1": 0.02,
        "pSL_2": 0.046,
        'sell-fisher': 0.38414,
        'sell-bbmiddle-close': 1.07634
    }

    minimal_roi = {
        "70": 0
    }

    stoploss = -0.99  # uses custom stoploss
    trailing_stop = False
    timeframe = '5m'  # Changed from 1m for practical backtesting
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    use_custom_stoploss = True
    process_only_new_candles = True
    startup_candle_count = 168

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 5},
            {"method": "StoplossGuard", "lookback_period_candles": 24, "trade_limit": 3, "stop_duration_candles": 12, "only_per_pair": True},
            {"method": "LowProfitPairs", "lookback_period_candles": 72, "trade_limit": 2, "stop_duration_candles": 72, "required_profit": -0.02},
            {"method": "MaxDrawdown", "lookback_period_candles": 576, "max_allowed_drawdown": 0.20, "stop_duration_candles": 72, "trade_limit": 1},
        ]

    order_types = {
        'entry': 'limit',
        'exit': 'limit',
        'emergency_exit': 'limit',
        'force_entry': "limit",
        'force_exit': 'limit',
        'stoploss': 'limit',
        'stoploss_on_exchange': False,
        'stoploss_on_exchange_interval': 60,
        'stoploss_on_exchange_limit_ratio': 0.99
    }

    # buy params
    rocr_1h = RealParameter(0.5, 1.0, default=0.54904, space='buy', optimize=True)
    bbdelta_close = RealParameter(0.0005, 0.02, default=0.01965, space='buy', optimize=True)
    closedelta_close = RealParameter(0.0005, 0.02, default=0.00556, space='buy', optimize=True)
    bbdelta_tail = RealParameter(0.7, 1.0, default=0.95089, space='buy', optimize=True)
    close_bblower = RealParameter(0.0005, 0.02, default=0.00799, space='buy', optimize=True)

    # custom stoploss params
    pHSL = DecimalParameter(-0.500, -0.040, default=-0.08, decimals=3, space='sell', load=True)  # MAE data: winners never dipped below -1.72%, -8% is 4x buffer
    pPF_1 = DecimalParameter(0.008, 0.020, default=0.016, decimals=3, space='sell', load=True)
    pSL_1 = DecimalParameter(0.008, 0.020, default=0.011, decimals=3, space='sell', load=True)
    pPF_2 = DecimalParameter(0.040, 0.100, default=0.080, decimals=3, space='sell', load=True)
    pSL_2 = DecimalParameter(0.020, 0.070, default=0.040, decimals=3, space='sell', load=True)

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        informative_pairs = [(pair, '1h') for pair in pairs]
        return informative_pairs

    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        # --- Time-based exit tightening (5m strategy: 93% of winners close in <50min) ---
        trade_duration = (current_time - trade.open_date_utc).total_seconds() / 3600

        if trade_duration > 8:
            # Force close after 8h — 5m dip thesis is dead
            return -0.001
        elif trade_duration > 4:
            # Tight stop: accept max -3% loss
            time_sl = stoploss_from_open(-0.03, current_profit)
            if time_sl != -0.99:
                return time_sl
        elif trade_duration > 2:
            # Tighten via ATR 2x
            atr_sl = self._atr_stoploss(pair, current_rate, multiplier=2.0)
            if atr_sl is not None:
                return atr_sl

        # --- Original stepped profit-lock stoploss ---
        HSL = self.pHSL.value
        PF_1 = self.pPF_1.value
        SL_1 = self.pSL_1.value
        PF_2 = self.pPF_2.value
        SL_2 = self.pSL_2.value

        if (current_profit > PF_2):
            sl_profit = SL_2 + (current_profit - PF_2)
        elif (current_profit > PF_1):
            sl_profit = SL_1 + ((current_profit - PF_1) * (SL_2 - SL_1) / (PF_2 - PF_1))
        else:
            sl_profit = HSL

        if (sl_profit >= current_profit):
            return -0.99
        return stoploss_from_open(sl_profit, current_profit)

    def _atr_stoploss(self, pair: str, current_rate: float, multiplier: float = 3.0):
        """ATR-based dynamic stoploss."""
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if len(dataframe) < 1:
            return None
        atr = dataframe.iloc[-1]['regime_atr_14']
        if np.isnan(atr) or atr <= 0:
            return None
        stoploss_price = current_rate - (atr * multiplier)
        return stoploss_from_absolute(stoploss_price, current_rate=current_rate,
                                       is_short=False, leverage=1.0)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        heikinashi = qtpylib.heikinashi(dataframe)
        dataframe['ha_open'] = heikinashi['open']
        dataframe['ha_close'] = heikinashi['close']
        dataframe['ha_high'] = heikinashi['high']
        dataframe['ha_low'] = heikinashi['low']

        mid, lower = bollinger_bands(ha_typical_price(dataframe), window_size=40, num_of_std=2)
        dataframe['lower'] = lower
        dataframe['mid'] = mid
        dataframe['bbdelta'] = (mid - dataframe['lower']).abs()
        dataframe['closedelta'] = (dataframe['ha_close'] - dataframe['ha_close'].shift()).abs()
        dataframe['tail'] = (dataframe['ha_close'] - dataframe['ha_low']).abs()
        dataframe['bb_lowerband'] = dataframe['lower']
        dataframe['bb_middleband'] = dataframe['mid']

        dataframe['ema_fast'] = ta.EMA(dataframe['ha_close'], timeperiod=3)
        dataframe['ema_slow'] = ta.EMA(dataframe['ha_close'], timeperiod=50)
        dataframe['volume_mean_slow'] = dataframe['volume'].rolling(window=30).mean()
        dataframe['rocr'] = ta.ROCR(dataframe['ha_close'], timeperiod=28)

        rsi = ta.RSI(dataframe)
        dataframe["rsi"] = rsi
        rsi = 0.1 * (rsi - 50)
        dataframe["fisher"] = (np.exp(2 * rsi) - 1) / (np.exp(2 * rsi) + 1)

        inf_tf = '1h'
        informative = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe=inf_tf)
        inf_heikinashi = qtpylib.heikinashi(informative)
        informative['ha_close'] = inf_heikinashi['close']
        informative['rocr'] = ta.ROCR(informative['ha_close'], timeperiod=168)
        dataframe = merge_informative_pair(dataframe, informative, self.timeframe, inf_tf, ffill=True)

        # --- Regime Detection ---
        # ATR regime — detect crash/high volatility periods
        dataframe['regime_atr_14'] = ta.ATR(dataframe, timeperiod=14)
        dataframe['regime_atr_sma_50'] = dataframe['regime_atr_14'].rolling(50).mean()
        dataframe['regime_volatile'] = (dataframe['regime_atr_14'] > 2.0 * dataframe['regime_atr_sma_50']).astype(int)

        # ADX regime — detect trending vs ranging
        dataframe['regime_adx_14'] = ta.ADX(dataframe, timeperiod=14)
        dataframe['regime_trending'] = (dataframe['regime_adx_14'] > 35).astype(int)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                dataframe['rocr_1h'].gt(self.rocr_1h.value)
            ) &
            ((
                    (dataframe['lower'].shift().gt(0)) &
                    (dataframe['bbdelta'].gt(dataframe['ha_close'] * self.bbdelta_close.value)) &
                    (dataframe['closedelta'].gt(dataframe['ha_close'] * self.closedelta_close.value)) &
                    (dataframe['tail'].lt(dataframe['bbdelta'] * self.bbdelta_tail.value)) &
                    (dataframe['ha_close'].lt(dataframe['lower'].shift())) &
                    (dataframe['ha_close'].le(dataframe['ha_close'].shift()))
            ) |
            (
                    (dataframe['ha_close'] < dataframe['ema_slow']) &
                    (dataframe['ha_close'] < self.close_bblower.value * dataframe['bb_lowerband'])
            )) &
            (dataframe['regime_volatile'] == 0) &  # Don't enter during high volatility
            (dataframe['regime_trending'] == 0),  # Mean reversion: only enter in ranging markets (ADX < 35)
            'enter_long'
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe['fisher'] > self.sell_params['sell-fisher']) &
            (dataframe['ha_high'].le(dataframe['ha_high'].shift(1))) &
            (dataframe['ha_high'].shift(1).le(dataframe['ha_high'].shift(2))) &
            (dataframe['ha_close'].le(dataframe['ha_close'].shift(1))) &
            (dataframe['ema_fast'] > dataframe['ha_close']) &
            ((dataframe['ha_close'] * self.sell_params['sell-bbmiddle-close']) > dataframe['bb_middleband']) &
            (dataframe['volume'] > 0) |
            (dataframe['regime_atr_14'] > 2.5 * dataframe['regime_atr_sma_50']),  # Exit on volatility spike
            'exit_long'
        ] = 1
        return dataframe
