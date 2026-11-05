"""UpbitFadeLiveV1 — live pilot of the Upbit KRW listing fade on Hyperliquid (#252).

The strategy generates no signals. Every entry comes from the host trigger
(research/upbit_fade_live/live_trigger.py) through Freqtrade's REST
`/forceenter`: one short per comparable event of the paper monitor
(research/upbit_fade_forward/, prereg upbit-krw-fade-forward-2026-11), at the
paper entry, t0 + 5 min. Live pilot prereg: upbit-krw-fade-live-pilot-2026-11.

Exits are Freqtrade's own, so they hold without the trigger running:

- **24 h time exit:** `minimal_roi` {"0": 100, "1440": -1}. Freqtrade 2026.7
  `IStrategy.min_roi_reached` takes the largest key <= the trade's age in
  minutes and exits when profit > that value. Before 1440 min the bar is
  +10000%; from 1440 min any profit above -100% exits at market. ROI is
  evaluated on every loop for every open trade (`should_exit`), with or
  without exit signals, so no `custom_exit` is involved (the fleet once ran a
  dead `custom_exit`, see the 2026-08-24 review).
- **Emergency stop:** -0.60, i.e. +60% adverse for a short at 1x, above the
  worst adverse move observed in Part C (+48.7%), so it does not change the
  tested 24 h rule. Exchange-resident when live (`stoploss_on_exchange` is
  switched on by the compose entrypoint only in live mode).

Entry guard (`confirm_trade_entry`, #252 review). Freqtrade 2026.7 runs the
/forceenter max-open and same-pair checks before it takes `_exit_lock`, so two
concurrent calls can both pass them. `execute_entry` calls
`confirm_trade_entry` under that lock, just before the order is created, so the
pilot's rules are enforced there, against the bot's own database. An entry is
refused unless its tag is `upbit-fade:<event id>@<deadline ms>`, the side is
short, the current time is not past the deadline (t0 + 7 min, never more than
7 min ahead), fewer than MAX_OPEN trades are open, the pair has no open trade,
no trade (open or closed) carries the same event id, and the realized P&L of
the closed trades in this database (the live database is the live epoch) is
above KILL_REALIZED_PNL_USD. Any error refuses: Freqtrade's wrapper would
otherwise treat an exception as "confirmed".
"""
import logging
import re
from datetime import datetime
from typing import Optional

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy
from pandas import DataFrame

logger = logging.getLogger(__name__)

# Frozen in prereg upbit-krw-fade-live-pilot-2026-11; tests pin them to the trigger.
TAG_PREFIX = "upbit-fade:"
MAX_OPEN = 2
LATEST_ENTRY_MS = 7 * 60_000
KILL_REALIZED_PNL_USD = -75.0
_TAG = re.compile(r"^upbit-fade:(?P<event_id>[^@\s]+)@(?P<deadline_ms>\d{13})$")


def parse_entry_tag(tag):
    """(event id, deadline ms) from `upbit-fade:<event id>@<deadline ms>`, else None."""
    m = _TAG.match(tag) if isinstance(tag, str) else None
    return (m.group("event_id"), int(m.group("deadline_ms"))) if m else None


def entry_refusal(pair, side, entry_tag, now_ms, trades):
    """Why this entry must not be placed, or None. `trades`: every trade in the bot's
    database (open and closed)."""
    tag = parse_entry_tag(entry_tag)
    if tag is None:
        return "entry tag %r is not upbit-fade:<event id>@<deadline ms>" % (entry_tag,)
    event_id, deadline_ms = tag
    if side != "short":
        return "side %s: the pilot only shorts" % side
    if now_ms > deadline_ms:
        return "past the entry deadline by %.1f s" % ((now_ms - deadline_ms) / 1000)
    if deadline_ms - now_ms > LATEST_ENTRY_MS:
        return "deadline more than 7 min ahead: not a t0 + 7 min deadline"
    open_trades = [t for t in trades if t.is_open]
    if len(open_trades) >= MAX_OPEN:
        return "%d trades open, max %d" % (len(open_trades), MAX_OPEN)
    if any(t.pair == pair for t in open_trades):
        return "a trade on %s is already open" % pair
    for t in trades:
        other = parse_entry_tag(t.enter_tag)
        if other is not None and other[0] == event_id:
            return "event %s already has trade %s" % (event_id, t.id)
    realized = sum(t.close_profit_abs or 0.0 for t in trades if not t.is_open)
    if realized <= KILL_REALIZED_PNL_USD:
        return "realized P&L %.2f USDC is at or below the %.0f limit" % (
            realized, KILL_REALIZED_PNL_USD)
    return None


class UpbitFadeLiveV1(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "5m"        # arbitrary; no indicator is read
    can_short = True
    process_only_new_candles = True

    minimal_roi = {"0": 100, "1440": -1}
    stoploss = -0.60
    trailing_stop = False
    use_custom_stoploss = False
    use_exit_signal = False
    exit_profit_only = False
    position_adjustment_enable = False

    startup_candle_count = 10

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        return df

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["enter_long"] = 0
        df["enter_short"] = 0
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["exit_long"] = 0
        df["exit_short"] = 0
        return df

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        side: str,
        entry_tag: Optional[str] = None,
        **kwargs,
    ) -> float:
        """Always 1x. The trigger also sends leverage 1.0 on /forceenter, which
        Freqtrade uses instead of this callback when present."""
        return 1.0

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> bool:
        try:
            reason = entry_refusal(pair, side, entry_tag, int(current_time.timestamp() * 1000),
                                   list(Trade.get_trades_proxy()))
        except Exception as e:  # noqa: BLE001 - fail closed; FT's wrapper would confirm
            reason = "guard failed: %s: %s" % (type(e).__name__, e)
        if reason is not None:
            logger.warning("UpbitFadeLiveV1 refused entry %s %s: %s", pair, entry_tag, reason)
            return False
        return True
