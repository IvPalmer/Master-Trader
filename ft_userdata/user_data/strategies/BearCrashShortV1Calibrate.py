"""Calibration wrapper — bypasses runtime checks that differ between live/backtest."""
from BearCrashShortV1 import BearCrashShortV1


class BearCrashShortV1Calibrate(BearCrashShortV1):

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                            current_time, entry_tag, side, **kwargs):
        return True

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate,
                           time_in_force, exit_reason, current_time, **kwargs):
        return True
