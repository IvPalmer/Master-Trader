import logging
from datetime import datetime
from numpy.lib import math
from freqtrade.strategy import IStrategy, IntParameter, informative
from freqtrade.persistence import Trade
from pandas import DataFrame
import talib.abstract as ta
import numpy as np
import pandas as pd

from market_intelligence import FearGreedIndex, PositionTracker, MAX_BOTS_PER_PAIR

logger = logging.getLogger(__name__)


class SupertrendStrategy(IStrategy):
    INTERFACE_VERSION: int = 3

    buy_params = {
        "buy_m1": 4, "buy_m2": 7, "buy_m3": 1,
        "buy_p1": 8, "buy_p2": 9, "buy_p3": 8,
    }
    sell_params = {
        "sell_m1": 1, "sell_m2": 3, "sell_m3": 6,
        "sell_p1": 16, "sell_p2": 18, "sell_p3": 18,
    }

    # ROI widened: old 5/3/2/1% was capping winners (avg win $0.48 vs avg loss $1.12)
    # Let trailing stop (2% @ 3% offset) handle profit-taking instead of early ROI exits
    minimal_roi = {
        "0": 0.08, "360": 0.05, "720": 0.03, "1440": 0.02
    }

    stoploss = -0.05  # Data: 0% of trades recover past -7%, 92% of winners never dip past -3%
    # Built-in trailing disabled — replaced by N-bar structure-based trailing in custom_stoploss
    trailing_stop = False
    # trailing_stop_positive = 0.02
    # trailing_stop_positive_offset = 0.03
    # trailing_only_offset_is_reached = True
    use_custom_stoploss = True
    n_bar_lookback = 3
    # Reverted to 1h — the 4h migration killed PF (3.34→1.46). Live 1h performance > 4h backtest.
    timeframe = '1h'
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = True  # Only honor exit signals when trade is profitable
    exit_profit_offset = 0.01  # Minimum +1% profit before exit signal is honored
    ignore_roi_if_entry_signal = False
    startup_candle_count = 200  # BTC SMA200 needs 200 candles

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},  # 2h cooldown
            {"method": "StoplossGuard", "lookback_period_candles": 48, "trade_limit": 2, "stop_duration_candles": 24, "only_per_pair": True},  # 48h lookback, 24h lock
            {"method": "LowProfitPairs", "lookback_period_candles": 288, "trade_limit": 4, "stop_duration_candles": 48, "required_profit": -0.05},  # 12d lookback, 48h lock
            {"method": "MaxDrawdown", "lookback_period_candles": 48, "max_allowed_drawdown": 0.20, "stop_duration_candles": 12, "trade_limit": 1},  # 48h lookback, 12h lock
        ]

    buy_m1 = IntParameter(1, 7, default=4)
    buy_m2 = IntParameter(1, 7, default=4)
    buy_m3 = IntParameter(1, 7, default=4)
    buy_p1 = IntParameter(7, 21, default=14)
    buy_p2 = IntParameter(7, 21, default=14)
    buy_p3 = IntParameter(7, 21, default=14)
    sell_m1 = IntParameter(1, 7, default=4)
    sell_m2 = IntParameter(1, 7, default=4)
    sell_m3 = IntParameter(1, 7, default=4)
    sell_p1 = IntParameter(7, 21, default=14)
    sell_p2 = IntParameter(7, 21, default=14)
    sell_p3 = IntParameter(7, 21, default=14)

    # ── BTC Market Guard (informative pair) ───────────────────────

    @informative('1h', 'BTC/{stake}')
    def populate_indicators_btc_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['sma200'] = ta.SMA(dataframe['close'], timeperiod=200)
        dataframe['sma50'] = ta.SMA(dataframe['close'], timeperiod=50)
        dataframe['adx'] = ta.ADX(dataframe, timeperiod=14)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        new_cols = []
        for multiplier in self.buy_m1.range:
            for period in self.buy_p1.range:
                st = self.supertrend(dataframe, multiplier, period)[['STX']].rename(
                    columns={'STX': f'supertrend_1_buy_{multiplier}_{period}'})
                new_cols.append(st)
        for multiplier in self.buy_m2.range:
            for period in self.buy_p2.range:
                st = self.supertrend(dataframe, multiplier, period)[['STX']].rename(
                    columns={'STX': f'supertrend_2_buy_{multiplier}_{period}'})
                new_cols.append(st)
        for multiplier in self.buy_m3.range:
            for period in self.buy_p3.range:
                st = self.supertrend(dataframe, multiplier, period)[['STX']].rename(
                    columns={'STX': f'supertrend_3_buy_{multiplier}_{period}'})
                new_cols.append(st)
        for multiplier in self.sell_m1.range:
            for period in self.sell_p1.range:
                st = self.supertrend(dataframe, multiplier, period)[['STX']].rename(
                    columns={'STX': f'supertrend_1_sell_{multiplier}_{period}'})
                new_cols.append(st)
        for multiplier in self.sell_m2.range:
            for period in self.sell_p2.range:
                st = self.supertrend(dataframe, multiplier, period)[['STX']].rename(
                    columns={'STX': f'supertrend_2_sell_{multiplier}_{period}'})
                new_cols.append(st)
        for multiplier in self.sell_m3.range:
            for period in self.sell_p3.range:
                st = self.supertrend(dataframe, multiplier, period)[['STX']].rename(
                    columns={'STX': f'supertrend_3_sell_{multiplier}_{period}'})
                new_cols.append(st)
        if new_cols:
            dataframe = pd.concat([dataframe] + new_cols, axis=1)

        # --- Regime Detection ---
        dataframe['regime_atr_14'] = ta.ATR(dataframe, timeperiod=14)
        dataframe['regime_atr_sma_50'] = dataframe['regime_atr_14'].rolling(50).mean()
        dataframe['regime_volatile'] = (dataframe['regime_atr_14'] > 2.0 * dataframe['regime_atr_sma_50']).astype(int)

        dataframe['regime_adx_14'] = ta.ADX(dataframe, timeperiod=14)
        dataframe['regime_trending'] = (dataframe['regime_adx_14'] > 25).astype(int)

        # Volume ratio for confidence scoring
        dataframe['volume_sma_20'] = dataframe['volume'].rolling(window=20).mean()
        dataframe['volume_ratio'] = dataframe['volume'] / (dataframe['volume_sma_20'] + 1e-10)

        # --- BTC Market Guard composite ---
        # SMA50 added as fast regime gate: catches BTC rollovers before SMA200 lags
        # (Mar 16-17: SMA200 lag let 5 trades in that all hit stoploss = -$5.04)
        dataframe['btc_bullish'] = (
            (dataframe['btc_usdt_close_1h'] > dataframe['btc_usdt_sma200_1h'])
            & (dataframe['btc_usdt_close_1h'] > dataframe['btc_usdt_sma50_1h'])
            & (dataframe['btc_usdt_rsi_1h'] > 35)
        ).astype(int)

        # BTC crash detection: block entries if BTC dropped >3% in 24h
        dataframe['btc_crash'] = (
            dataframe['btc_usdt_close_1h'] < dataframe['btc_usdt_close_1h'].shift(24) * 0.97
        ).astype(int)

        return dataframe

    # ── Entry gate: cross-bot + sentiment checks ─────────────────

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag: str | None, side: str, **kwargs) -> bool:
        bot_name = self.config.get('bot_name', 'Supertrend')

        # Cross-bot position check
        other_bots = PositionTracker.count_bots_holding(pair, exclude_bot=bot_name)
        if other_bots >= MAX_BOTS_PER_PAIR:
            logger.info("BLOCKED %s: %d other bots already hold this pair", pair, other_bots)
            return False

        # Fear & Greed: block during extreme greed
        if FearGreedIndex.is_extreme_greed():
            logger.info("BLOCKED %s: Fear & Greed in extreme greed (%d)",
                         pair, FearGreedIndex.get()["value"])
            return False

        PositionTracker.register(bot_name, pair, amount * rate)
        return True

    def confirm_trade_exit(self, pair: str, trade, order_type: str, amount: float,
                           rate: float, time_in_force: str, exit_reason: str,
                           current_time: datetime, **kwargs) -> bool:
        bot_name = self.config.get('bot_name', 'Supertrend')
        PositionTracker.unregister(bot_name, pair)
        return True

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        """
        N-bar trailing stop: trail using lowest low of last N candles.
        Adapts to volatility — wide candles = wide stop, tight candles = tight stop.
        Inspired by Lance Breitstein's 2-bar trailing methodology (SMB Capital).
        """
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return self.stoploss  # -0.05

        trade_candles = len(dataframe.loc[dataframe['date'] >= trade.open_date_utc])

        # Not enough candles yet — use default stoploss
        if trade_candles < self.n_bar_lookback:
            return self.stoploss

        # Lowest low of last N candles
        n_bar_low = dataframe['low'].tail(self.n_bar_lookback).min()

        # Calculate stoploss relative to current rate
        sl_from_current = (n_bar_low / current_rate) - 1.0

        # Never wider than default stoploss (-5%)
        if sl_from_current < self.stoploss:
            return self.stoploss

        # Never return positive (that would close the trade)
        if sl_from_current >= 0:
            return -0.001

        return sl_from_current

    def custom_stake_amount(self, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: float | None,
                            max_stake: float, entry_tag: str | None, side: str,
                            **kwargs) -> float:
        """
        Confidence-based position sizing (Lance Breitstein A/B/C grading).
        Score setup quality from confirming indicators, scale stake accordingly.
        """
        pair = kwargs.get('pair', '')
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return proposed_stake

        last = dataframe.iloc[-1]
        score = 0

        # +1: Strong ADX trend (> 30 vs entry threshold of 25)
        if last.get('regime_adx_14', 0) > 30:
            score += 1

        # +1: Volume spike (> 1.5x average)
        if last.get('volume_ratio', 0) > 1.5:
            score += 1

        # +1: Low volatility (ATR well below danger zone)
        if last.get('regime_volatile', 1) == 0 and last.get('regime_atr_14', 0) < 1.5 * last.get('regime_atr_sma_50', 1):
            score += 1

        # +1: BTC RSI shows strong momentum (> 55, not just above 35 threshold)
        if last.get('btc_usdt_rsi_1h', 0) > 55:
            score += 1

        # Scale stake: score 0-1 = 0.75x, score 2 = 1.0x, score 3-4 = 1.25x
        if score >= 3:
            multiplier = 1.25
        elif score >= 2:
            multiplier = 1.0
        else:
            multiplier = 0.75

        adjusted = proposed_stake * multiplier
        return max(min(adjusted, max_stake), min_stake or 0)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
               (dataframe[f'supertrend_1_buy_{self.buy_m1.value}_{self.buy_p1.value}'] == 'up') &
               (dataframe[f'supertrend_2_buy_{self.buy_m2.value}_{self.buy_p2.value}'] == 'up') &
               (dataframe[f'supertrend_3_buy_{self.buy_m3.value}_{self.buy_p3.value}'] == 'up') &
               (dataframe['volume'] > 0) &
               (dataframe['regime_volatile'] == 0) &  # Don't enter during high volatility
               (dataframe['regime_trending'] == 1) &  # Trend following: only enter in trending markets
               (dataframe['btc_bullish'] == 1) &  # BTC market guard
               (dataframe['btc_crash'] == 0)  # BTC crash detection
            ),
            'enter_long'] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
               (dataframe[f'supertrend_1_sell_{self.sell_m1.value}_{self.sell_p1.value}'] == 'down') &
               (dataframe[f'supertrend_2_sell_{self.sell_m2.value}_{self.sell_p2.value}'] == 'down') &
               (dataframe[f'supertrend_3_sell_{self.sell_m3.value}_{self.sell_p3.value}'] == 'down') &
               (dataframe['volume'] > 0)
            ) |
            (dataframe['regime_atr_14'] > 2.5 * dataframe['regime_atr_sma_50']),  # Exit on volatility spike
            'exit_long'] = 1
        return dataframe

    def supertrend(self, dataframe: pd.DataFrame, multiplier, period):
        df = dataframe.copy()
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        length = len(df)

        tr = ta.TRANGE(df['high'], df['low'], df['close'])
        atr = pd.Series(tr).rolling(period).mean().to_numpy()

        basic_ub = (high + low) / 2 + multiplier * atr
        basic_lb = (high + low) / 2 - multiplier * atr

        final_ub = np.zeros(length)
        final_lb = np.zeros(length)
        for i in range(period, length):
            final_ub[i] = basic_ub[i] if basic_ub[i] < final_ub[i-1] or close[i-1] > final_ub[i-1] else final_ub[i-1]
            final_lb[i] = basic_lb[i] if basic_lb[i] > final_lb[i-1] or close[i-1] < final_lb[i-1] else final_lb[i-1]

        st = np.zeros(length)
        for i in range(period, length):
            if st[i-1] == final_ub[i-1]:
                st[i] = final_ub[i] if close[i] <= final_ub[i] else final_lb[i]
            elif st[i-1] == final_lb[i-1]:
                st[i] = final_lb[i] if close[i] >= final_lb[i] else final_ub[i]

        stx = np.where(st > 0, np.where(close < st, 'down', 'up'), None)
        result = pd.DataFrame({'ST': st, 'STX': stx}, index=df.index)
        result.fillna(0, inplace=True)
        return result
