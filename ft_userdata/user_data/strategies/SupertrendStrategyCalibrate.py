"""
Calibration wrapper — bypasses runtime-only checks for live-vs-backtest comparison.

Calibration asks: does the backtest reproduce the same trades as live?
Since live trades already passed all filters, the backtest should too.
Only PositionTracker needs bypassing (no cross-bot state in backtest).

BTC guard: already in populate_entry_trend, works natively.
F&G gate: 0 extreme greed days since Apr 2025, not a factor.
Pairlist filter: NOT applied here — belongs in viability wrapper.
"""
from SupertrendStrategy import SupertrendStrategy


class SupertrendStrategyCalibrate(SupertrendStrategy):

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                            current_time, entry_tag, side, **kwargs):
        return True

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate,
                           time_in_force, exit_reason, current_time, **kwargs):
        return True
