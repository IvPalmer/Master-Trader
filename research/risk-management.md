# Risk Management & Stop Loss Strategies for Multi-Bot Crypto Trading

> Research compiled 2026-03-11 for the Master Trader 8-bot Freqtrade setup.

---

## Table of Contents

1. [Ranked Recommendations (TL;DR)](#ranked-recommendations)
2. [Portfolio-Level Risk Management](#1-portfolio-level-risk-management)
3. [Stop Loss Strategies for Dip-Buying Bots](#2-stop-loss-strategies-for-dip-buying-bots)
4. [Freqtrade-Specific Risk Features](#3-freqtrade-specific-risk-features)
5. [Anti-Correlation / Duplicate Exposure Prevention](#4-anti-correlation--duplicate-exposure-prevention)

---

## Ranked Recommendations

Ordered by **impact x ease of implementation** for our specific 8-bot setup:

| # | Action | Impact | Effort | Priority |
|---|--------|--------|--------|----------|
| 1 | Add Protections to ALL strategy configs (StoplossGuard + MaxDrawdown + CooldownPeriod) | HIGH | LOW (config only) | DO NOW |
| 2 | Add LowProfitPairs protection to dip-buying bots | HIGH | LOW (config only) | DO NOW |
| 3 | Implement time-based custom_stoploss on all strategies (tighten after 24-48h) | HIGH | MEDIUM (code) | THIS WEEK |
| 4 | Build cross-bot exposure monitor into tournament_manager.py | HIGH | MEDIUM (code) | THIS WEEK |
| 5 | Add ATR-based dynamic stoploss to ClucHAnix, CombinedBinH, NASOSv5 | HIGH | MEDIUM (code) | THIS WEEK |
| 6 | Implement DCA-out / partial profit taking on best performers | MEDIUM | MEDIUM (code) | NEXT WEEK |
| 7 | Add portfolio-wide circuit breaker to tournament_manager.py | HIGH | MEDIUM (code) | NEXT WEEK |
| 8 | Diversify pairlists across bots (reduce overlap) | MEDIUM | LOW (config) | NEXT WEEK |
| 9 | Enable Edge module on 1-2 bots experimentally | MEDIUM | LOW (config) | LATER |
| 10 | Build shared position tracker with per-pair caps | HIGH | HIGH (new service) | LATER |

---

## 1. Portfolio-Level Risk Management

### 1.1 Max Portfolio Drawdown Limits

**The problem**: With 8 bots x $1,000 USDT each = $8,000 total exposure, a correlated crash can hit all bots simultaneously.

**Recommended thresholds**:
- **Per-bot max drawdown**: 20% ($200 per bot) -- use Freqtrade's MaxDrawdown protection
- **Portfolio-wide daily drawdown**: 7% ($560 across all bots) -- needs external monitor
- **Portfolio-wide weekly drawdown**: 15% ($1,200) -- trigger full pause

**Implementation -- per-bot (config only)**:
```json
{
    "protections": [
        {
            "method": "MaxDrawdown",
            "calculation_mode": "equity",
            "lookback_period_candles": 48,
            "trade_limit": 4,
            "stop_duration_candles": 12,
            "max_allowed_drawdown": 0.20
        }
    ]
}
```

**Implementation -- portfolio-wide (add to tournament_manager.py)**:
```python
def check_portfolio_circuit_breaker(bots: dict, max_daily_dd: float = 0.07) -> bool:
    """Query all bots via API, sum P&L, pause all if threshold breached."""
    total_profit = 0
    total_capital = 0

    for name, bot in bots.items():
        try:
            resp = requests.get(
                f"http://localhost:{bot['port']}/api/v1/profit",
                headers={"Authorization": f"Bearer {get_token(bot['port'])}"}
            )
            data = resp.json()
            total_profit += data.get("profit_all_coin", 0)
            total_capital += 1000  # dry-run stake per bot
        except Exception:
            continue

    daily_dd = total_profit / total_capital if total_capital > 0 else 0

    if daily_dd < -max_daily_dd:
        # Pause all bots via API
        for name, bot in bots.items():
            requests.post(
                f"http://localhost:{bot['port']}/api/v1/stop",
                headers={"Authorization": f"Bearer {get_token(bot['port'])}"}
            )
        send_telegram_alert(f"CIRCUIT BREAKER: Portfolio down {daily_dd:.1%}, all bots paused")
        return True
    return False
```

### 1.2 Position Sizing Relative to Portfolio

**Rule of thumb for 8-bot setup**:
- Each bot gets 12.5% of total capital ($1,000 of $8,000)
- Within each bot, `max_open_trades` x `stake_amount` should not exceed the bot's allocation
- For dip-buying bots using DCA: reserve 50% of capital for safety orders

**Current config recommendation per bot**:
```json
{
    "stake_amount": "unlimited",
    "tradable_balance_ratio": 0.99,
    "max_open_trades": 5,
    "stake_currency": "USDT",
    "dry_run_wallet": 1000
}
```

With `stake_amount: "unlimited"` and `max_open_trades: 5`, each trade gets ~$200. If using DCA with `max_entry_position_adjustment: 2`, use `custom_stake_amount` to reserve funds:

```python
def custom_stake_amount(self, pair, current_time, current_rate,
                        proposed_stake, min_stake, max_stake,
                        leverage, entry_tag, side, **kwargs):
    # Reserve 60% for DCA orders (up to 2 additional entries)
    return proposed_stake * 0.4
```

---

## 2. Stop Loss Strategies for Dip-Buying Bots

### 2.1 Why Simple % Stoploss Fails for Mean-Reversion

Our dip-buying bots (ClucHAnix, CombinedBinH, NASOSv5, ElliotV5) buy when price drops below Bollinger Bands or EWO signals oversold. A fixed -10% stoploss has two problems:

1. **Gets triggered during normal dip depth** -- The strategy buys BECAUSE price is dropping. A -10% stoploss fires precisely when the strategy expects a bounce, creating a lose-lose: either stoploss is too tight (constant stops) or too loose (catastrophic when wrong).

2. **Ignores volatility regime** -- A -10% move on BTC in a low-vol market is catastrophic; the same move during a crash is noise. Fixed stops don't adapt.

3. **No time dimension** -- A trade down 8% after 2 hours might recover; the same trade down 8% after 3 days is probably wrong.

### 2.2 ATR-Based Dynamic Stoploss

ATR (Average True Range) automatically adapts stop distance to current volatility.

```python
class DipBuyerWithATRStop(IStrategy):
    use_custom_stoploss = True
    stoploss = -0.25  # Hard emergency stoploss (never removed)

    def populate_indicators(self, dataframe, metadata):
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)
        # ... other indicators
        return dataframe

    def custom_stoploss(self, pair, trade, current_time, current_rate,
                        current_profit, after_fill, **kwargs):
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if len(dataframe) < 1:
            return None

        candle = dataframe.iloc[-1].squeeze()
        atr = candle['atr']

        # Stop at 3x ATR below current price (wider for mean-reversion)
        # For 5m candles, ATR ~0.5-1.5% of price, so 3x = 1.5-4.5%
        stoploss_price = current_rate - (atr * 3)

        return stoploss_from_absolute(
            stoploss_price,
            current_rate=current_rate,
            is_short=trade.is_short,
            leverage=trade.leverage
        )
```

**Why 3x ATR for dip-buyers**: Standard trend-following uses 2x ATR. Dip-buyers need wider stops because they're buying into downward momentum. 3x ATR gives the trade room to find a bottom while still protecting against trend continuation.

### 2.3 Time-Based Exits (Max Hold Duration)

Dip-buying strategies expect a bounce within hours, not days. If a trade hasn't recovered after a set time, the thesis is likely wrong.

```python
def custom_stoploss(self, pair, trade, current_time, current_rate,
                    current_profit, after_fill, **kwargs):
    # Calculate hold time
    trade_duration = (current_time - trade.open_date_utc).total_seconds() / 3600  # hours

    # Phase 1: First 12 hours -- wide stop (ATR-based, let it work)
    if trade_duration < 12:
        return self._atr_stoploss(pair, current_rate, trade, multiplier=3.0)

    # Phase 2: 12-24 hours -- tighten stop
    elif trade_duration < 24:
        return self._atr_stoploss(pair, current_rate, trade, multiplier=2.0)

    # Phase 3: 24-48 hours -- tight stop, give up if not recovering
    elif trade_duration < 48:
        # Accept up to -3% loss
        return stoploss_from_open(-0.03, current_profit,
                                  is_short=trade.is_short,
                                  leverage=trade.leverage)

    # Phase 4: After 48 hours -- force close at market
    else:
        # Return a stoploss at current price (triggers immediate exit)
        return -0.001  # ~0.1% -- effectively a market exit

def _atr_stoploss(self, pair, current_rate, trade, multiplier=3.0):
    dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
    if len(dataframe) < 1:
        return None
    atr = dataframe.iloc[-1].squeeze()['atr']
    stoploss_price = current_rate - (atr * multiplier)
    return stoploss_from_absolute(stoploss_price, current_rate=current_rate,
                                   is_short=trade.is_short, leverage=trade.leverage)
```

**Recommended max hold times by strategy type**:
| Strategy Type | Max Hold | Rationale |
|---------------|----------|-----------|
| BB dip-buyer (5m) | 24-48h | Mean reversion should happen within ~50-200 candles |
| EWO reversal (5m) | 12-24h | Momentum signals decay fast |
| Supertrend (1h) | 72-120h | Trend-following needs more time |
| FreqAI adaptive | 24-48h | Model predictions degrade beyond training horizon |

### 2.4 Partial Position Closing / DCA-Out

Instead of all-or-nothing exits, scale out as price recovers:

```python
class DipBuyerWithDCAOut(IStrategy):
    position_adjustment_enable = True
    max_entry_position_adjustment = 2  # Up to 2 DCA entries

    def adjust_trade_position(self, trade, current_time, current_rate,
                               current_profit, min_stake, max_stake,
                               current_entry_rate, current_exit_rate,
                               current_entry_profit, current_exit_profit,
                               **kwargs):
        if trade.has_open_orders:
            return None

        # === DCA-IN: Buy more on deeper dips ===
        if current_profit < -0.04 and trade.nr_of_successful_entries == 1:
            # First DCA: price dropped 4%+ from entry
            return trade.stake_amount * 1.0, "dca_1_minus4pct"

        if current_profit < -0.08 and trade.nr_of_successful_entries == 2:
            # Second DCA: price dropped 8%+ from entry
            return trade.stake_amount * 0.5, "dca_2_minus8pct"

        # === DCA-OUT: Take partial profits ===
        if current_profit > 0.03 and trade.nr_of_successful_exits == 0:
            # Take 33% profit at +3%
            return -(trade.stake_amount / 3), "partial_tp_3pct"

        if current_profit > 0.06 and trade.nr_of_successful_exits == 1:
            # Take another 33% at +6%
            return -(trade.stake_amount / 3), "partial_tp_6pct"

        # Let remaining 33% ride with trailing stop
        return None
```

---

## 3. Freqtrade-Specific Risk Features

### 3.1 Complete Protections Config (Recommended for ALL Bots)

Add this to every strategy config file:

```json
{
    "protections": [
        {
            "method": "CooldownPeriod",
            "stop_duration_candles": 2
        },
        {
            "method": "StoplossGuard",
            "lookback_period_candles": 24,
            "trade_limit": 3,
            "stop_duration_candles": 12,
            "required_profit": 0.0,
            "only_per_pair": false
        },
        {
            "method": "MaxDrawdown",
            "calculation_mode": "equity",
            "lookback_period_candles": 48,
            "trade_limit": 4,
            "stop_duration_candles": 12,
            "max_allowed_drawdown": 0.20
        },
        {
            "method": "LowProfitPairs",
            "lookback_period_candles": 72,
            "trade_limit": 2,
            "stop_duration_candles": 24,
            "required_profit": -0.05,
            "only_per_pair": true
        }
    ]
}
```

**What this does**:
- **CooldownPeriod**: Waits 2 candles before re-entering the same pair (avoids whipsaw re-entries)
- **StoplossGuard**: If 3+ trades hit stoploss in last 24 candles, pause ALL trading for 12 candles
- **MaxDrawdown**: If equity drops 20%+ over last 48 candles, pause for 12 candles
- **LowProfitPairs**: If a specific pair loses >5% over last 72 candles across 2+ trades, lock that pair for 24 candles

### 3.2 Custom Stoploss Best Practices

**Rules**:
1. Always set a hard `stoploss` as emergency floor (e.g., `-0.25`). Custom stoploss cannot go below this.
2. `custom_stoploss` can only tighten, never loosen. Once stoploss moves up, it stays there.
3. Return `None` to keep current stoploss unchanged. Return a negative float to set new stoploss.
4. Use `stoploss_from_absolute()` when working with price levels, `stoploss_from_open()` when working with percentages from entry.
5. Always set `use_custom_stoploss = True` on the strategy class.
6. Consider `stoploss_on_exchange = True` for live trading (places actual stop order on exchange).

**Template combining ATR + time + profit trailing**:
```python
def custom_stoploss(self, pair, trade, current_time, current_rate,
                    current_profit, after_fill, **kwargs):
    # After DCA fill, reset stoploss relative to new average
    if after_fill:
        return stoploss_from_open(-0.10, current_profit,
                                  is_short=trade.is_short,
                                  leverage=trade.leverage)

    trade_duration_hours = (current_time - trade.open_date_utc).total_seconds() / 3600

    # Profitable: trail with tight stop
    if current_profit > 0.06:
        return stoploss_from_open(0.03, current_profit,
                                  is_short=trade.is_short,
                                  leverage=trade.leverage)
    if current_profit > 0.03:
        return stoploss_from_open(0.01, current_profit,
                                  is_short=trade.is_short,
                                  leverage=trade.leverage)

    # Losing: time-based tightening
    if trade_duration_hours > 48:
        return -0.005  # Force exit
    elif trade_duration_hours > 24:
        return -0.03
    elif trade_duration_hours > 12:
        return -0.07

    # Default: ATR-based
    return self._atr_stoploss(pair, current_rate, trade, multiplier=3.0)
```

### 3.3 Edge Module

Edge calculates optimal stoploss per pair using historical win-rate and expectancy analysis.

```json
{
    "edge": {
        "enabled": true,
        "process_throttle_secs": 3600,
        "calculate_since_number_of_days": 14,
        "allowed_risk": 0.01,
        "stoploss_range_min": -0.01,
        "stoploss_range_max": -0.1,
        "stoploss_range_step": -0.01,
        "minimum_winrate": 0.60,
        "minimum_expectancy": 0.20,
        "min_trade_number": 10,
        "max_trade_duration_minute": 1440
    }
}
```

**Caveat**: Edge overrides your strategy's stoploss and position sizing. It's powerful but opinionated. Recommended to test on 1-2 bots first (e.g., NASOSv5 which has enough trade volume). Edge does NOT work well with DCA strategies since it doesn't account for position adjustments.

---

## 4. Anti-Correlation / Duplicate Exposure Prevention

### 4.1 The Problem

With 7 active bots all trading overlapping pairs, it's possible for 5+ bots to simultaneously hold positions in XAI/USDT or PIXEL/USDT. During a crash, all lose simultaneously -- the portfolio isn't truly diversified.

**Real risk with our setup**:
- ClucHAnix, CombinedBinH, NASOSv5, ElliotV5 all use 5m BB/EWO dip-buying
- They watch similar pairs and respond to similar signals
- A sudden BTC dump triggers buys across ALL dip-buying bots on the same coins

### 4.2 Strategy 1: Diversified Pairlists (Easiest)

Split the universe of pairs so bots don't overlap heavily:

```
# ClucHAnix + NASOSv5: Top 20 by volume (BTC, ETH, SOL, etc.)
# ElliotV5: Pairs ranked 21-40 by volume
# SupertrendStrategy: Only large-cap (BTC, ETH, BNB, SOL, XRP)
# NostalgiaForInfinity: Its own 60-pair list (already configured)
# MasterTraderAI: FreqAI pairs (can overlap, ML adapts)
```

Config approach using VolumePairList with offset:
```json
{
    "pairlists": [
        {"method": "VolumePairList", "number_assets": 20, "sort_key": "quoteVolume"},
        {"method": "AgeFilter", "min_days_listed": 30}
    ]
}
```

For the second group (offset):
```json
{
    "pairlists": [
        {"method": "VolumePairList", "number_assets": 40, "sort_key": "quoteVolume"},
        {"method": "OffsetFilter", "offset": 20, "number_assets": 20},
        {"method": "AgeFilter", "min_days_listed": 30}
    ]
}
```

### 4.3 Strategy 2: Cross-Bot Exposure Monitor (Add to Tournament Manager)

Query all bot APIs, detect overlap, alert or force-close:

```python
def check_cross_bot_exposure(bots: dict, max_per_pair: int = 3) -> dict:
    """Detect when too many bots hold the same pair."""
    pair_exposure = {}  # pair -> list of bot names

    for name, bot in bots.items():
        try:
            resp = requests.get(
                f"http://localhost:{bot['port']}/api/v1/status",
                headers={"Authorization": f"Bearer {get_token(bot['port'])}"}
            )
            trades = resp.json()
            for trade in trades:
                pair = trade['pair']
                if pair not in pair_exposure:
                    pair_exposure[pair] = []
                pair_exposure[pair].append({
                    'bot': name,
                    'stake': trade['stake_amount'],
                    'profit_pct': trade['profit_pct']
                })
        except Exception:
            continue

    alerts = {}
    for pair, positions in pair_exposure.items():
        if len(positions) >= max_per_pair:
            total_stake = sum(p['stake'] for p in positions)
            alerts[pair] = {
                'count': len(positions),
                'total_stake': total_stake,
                'bots': [p['bot'] for p in positions],
                'avg_profit': sum(p['profit_pct'] for p in positions) / len(positions)
            }

    if alerts:
        msg = "EXPOSURE ALERT:\n"
        for pair, info in alerts.items():
            msg += f"  {pair}: {info['count']} bots, ${info['total_stake']:.0f} total\n"
            msg += f"    Bots: {', '.join(info['bots'])}\n"
        send_telegram_alert(msg)

    return alerts
```

Run this every 5 minutes via the tournament manager or a separate cron:
```
*/5 * * * * cd ~/ft_userdata && python3 -c "from tournament_manager import check_cross_bot_exposure, BOTS; check_cross_bot_exposure(BOTS)" >> logs/exposure.log 2>&1
```

### 4.4 Strategy 3: Shared Position Tracker (Full Solution)

A lightweight Redis/SQLite service that all bots query before entering trades. This requires custom strategy code using `confirm_trade_entry`:

```python
import sqlite3
from pathlib import Path

EXPOSURE_DB = Path.home() / "ft_userdata" / "shared_exposure.db"
MAX_BOTS_PER_PAIR = 3
MAX_PAIR_STAKE = 500  # Max total $ across all bots for one pair

def _get_db():
    db = sqlite3.connect(str(EXPOSURE_DB))
    db.execute("""CREATE TABLE IF NOT EXISTS positions (
        bot TEXT, pair TEXT, stake REAL, opened_at TEXT,
        PRIMARY KEY (bot, pair)
    )""")
    return db

class SharedExposureStrategy(IStrategy):
    """Mixin -- add to any strategy's confirm_trade_entry."""

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                             current_time, entry_tag, side, **kwargs):
        db = _get_db()

        # Count how many bots already hold this pair
        row = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(stake), 0) FROM positions WHERE pair = ?",
            (pair,)
        ).fetchone()

        bot_count, total_stake = row[0], row[1]

        if bot_count >= MAX_BOTS_PER_PAIR:
            logger.warning(f"BLOCKED: {pair} already held by {bot_count} bots")
            return False

        if total_stake >= MAX_PAIR_STAKE:
            logger.warning(f"BLOCKED: {pair} total stake ${total_stake:.0f} exceeds limit")
            return False

        # Register our position
        db.execute(
            "INSERT OR REPLACE INTO positions VALUES (?, ?, ?, ?)",
            (self.__class__.__name__, pair, amount * rate, str(current_time))
        )
        db.commit()
        return True

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate,
                            time_in_force, exit_reason, current_time, **kwargs):
        # Remove from shared tracker
        db = _get_db()
        db.execute(
            "DELETE FROM positions WHERE bot = ? AND pair = ?",
            (self.__class__.__name__, pair)
        )
        db.commit()
        return True
```

### 4.5 Strategy 4: Producer/Consumer for Signal Deduplication

Freqtrade's built-in producer/consumer mode allows bots to share analyzed dataframes via websocket. While designed for indicator sharing, you can use it to coordinate:

```json
{
    "external_message_consumer": {
        "enabled": true,
        "producers": [
            {
                "name": "exposure_tracker",
                "host": "127.0.0.1",
                "port": 8080,
                "ws_token": "your_secret_token"
            }
        ]
    }
}
```

This is more useful for sharing computed indicators than for position tracking, but worth exploring as Freqtrade evolves.

---

## Implementation Checklist

### Phase 1: Config-Only Changes (Do Today)

- [ ] Add protections block to all 7 active strategy configs
- [ ] Verify `stoploss` is set to reasonable emergency floor (-0.20 to -0.25) on all bots
- [ ] Set `max_open_trades: 5` on all bots (prevent over-deployment)
- [ ] Add CooldownPeriod to prevent whipsaw re-entries

### Phase 2: Strategy Code Changes (This Week)

- [ ] Add ATR calculation to `populate_indicators()` on all strategies
- [ ] Implement `custom_stoploss()` with ATR + time-based logic
- [ ] Add time-based exit tightening (48h max for 5m strategies)
- [ ] Test with `freqtrade backtesting` on 90 days of data

### Phase 3: Portfolio Infrastructure (Next Week)

- [ ] Add `check_cross_bot_exposure()` to tournament_manager.py
- [ ] Add `check_portfolio_circuit_breaker()` to tournament_manager.py
- [ ] Set up 5-minute cron for exposure monitoring
- [ ] Diversify pairlists across bot groups
- [ ] Implement shared SQLite position tracker

### Phase 4: Advanced (Later)

- [ ] DCA-out with partial profit taking on NASOSv5 and ClucHAnix
- [ ] Edge module experiment on NASOSv5
- [ ] Producer/consumer setup for indicator sharing
- [ ] Grafana dashboard for cross-bot exposure visualization

---

## Sources

- [Freqtrade Plugins/Protections Documentation](https://www.freqtrade.io/en/stable/plugins/)
- [Freqtrade Strategy Callbacks (custom_stoploss, adjust_trade_position)](https://www.freqtrade.io/en/stable/strategy-callbacks/)
- [Freqtrade Stoploss Documentation](https://www.freqtrade.io/en/stable/stoploss/)
- [Freqtrade Edge Positioning](https://www.freqtrade.io/en/2020.12/edge/)
- [Freqtrade Producer/Consumer Mode](https://www.freqtrade.io/en/2024.4/producer-consumer/)
- [Freqtrade Configuration Reference](https://www.freqtrade.io/en/stable/configuration/)
- [AI Trading Bot Risk Management Guide 2025 (3Commas)](https://3commas.io/blog/ai-trading-bot-risk-management-guide-2025)
- [Multi-Bot Controller Discussion (GitHub #5485)](https://github.com/freqtrade/freqtrade/issues/5485)
- [ATR-Based Risk/Reward in Freqtrade (GitHub #9895)](https://github.com/freqtrade/freqtrade/issues/9895)
- [MaxDrawdown Protection Discussion (GitHub #9545)](https://github.com/freqtrade/freqtrade/issues/9545)
- [Time-Based Exit Discussion (GitHub #8463)](https://github.com/freqtrade/freqtrade/issues/8463)
