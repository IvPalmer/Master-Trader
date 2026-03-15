# Freqtrade Futures & Leverage Trading: Technical Research Report

> Research date: 2026-03-13
> Context: 7 spot bots running on Binance via Docker, considering adding a futures module

---

## Table of Contents

1. [Futures Mode Configuration](#1-futures-mode-configuration)
2. [Short Selling Implementation](#2-short-selling-implementation)
3. [Leverage Configuration](#3-leverage-configuration)
4. [Funding Rates](#4-funding-rates)
5. [Liquidation Risk & Protection](#5-liquidation-risk--protection)
6. [Isolated vs Cross Margin](#6-isolated-vs-cross-margin)
7. [FreqAI + Futures](#7-freqai--futures)
8. [Docker Setup](#8-docker-setup-alongside-spot-bots)
9. [Binance Futures API](#9-binance-futures-api-specifics)
10. [Common Pitfalls](#10-common-pitfalls--migration-checklist)

---

## 1. Futures Mode Configuration

### Minimum Config Changes

To switch from spot to futures, you need exactly two new config keys:

```json
{
    "trading_mode": "futures",
    "margin_mode": "isolated"
}
```

### Pair Naming Changes

Futures pairs use the **ccxt settle format**: `BASE/QUOTE:SETTLE`

| Mode | Format | Example |
|------|--------|---------|
| Spot | `BASE/QUOTE` | `ETH/USDT` |
| Futures | `BASE/QUOTE:SETTLE` | `ETH/USDT:USDT` |

Your pairlist handler (VolumePairList, StaticPairList) will automatically resolve futures pairs when `trading_mode` is set. **You do NOT need to manually add `:USDT` to your whitelist** -- Freqtrade handles this internally via the exchange layer.

### Pricing Configuration (REQUIRED for Binance Futures)

Binance does **not** provide ticker price data for futures pairs. You **must** use orderbook pricing:

```json
{
    "entry_pricing": {
        "price_side": "same",
        "use_order_book": true,
        "order_book_top": 1
    },
    "exit_pricing": {
        "price_side": "same",
        "use_order_book": true,
        "order_book_top": 1
    }
}
```

### Order Types for Futures

Binance futures supports both stop-limit and stop-market orders:

```json
{
    "order_types": {
        "entry": "limit",
        "exit": "limit",
        "emergency_exit": "market",
        "force_exit": "market",
        "force_entry": "market",
        "stoploss": "market",
        "stoploss_on_exchange": true
    }
}
```

Using `"stoploss": "market"` is recommended for futures to avoid slippage on stop-market orders. `stoploss_on_exchange` is strongly recommended with leverage.

### Binance Account Prerequisites

Before starting the bot, configure these in the Binance web UI:

1. **Position Mode**: Must be set to **"One-way Mode"** (not Hedge Mode)
2. **Asset Mode**: Must be set to **"Single-Asset Mode"**

Freqtrade checks these on startup and will error if misconfigured.

### Complete Futures Config Example

```json
{
    "trading_mode": "futures",
    "margin_mode": "isolated",
    "liquidation_buffer": 0.05,
    "stake_currency": "USDT",
    "stake_amount": 100,
    "max_open_trades": 5,
    "dry_run": true,
    "dry_run_wallet": 1000,
    "entry_pricing": {
        "price_side": "same",
        "use_order_book": true,
        "order_book_top": 1
    },
    "exit_pricing": {
        "price_side": "same",
        "use_order_book": true,
        "order_book_top": 1
    },
    "order_types": {
        "entry": "limit",
        "exit": "limit",
        "emergency_exit": "market",
        "force_exit": "market",
        "force_entry": "market",
        "stoploss": "market",
        "stoploss_on_exchange": true
    },
    "exchange": {
        "name": "binance",
        "key": "",
        "secret": "",
        "pair_whitelist": [],
        "pair_blacklist": [
            "BNB/.*"
        ]
    }
}
```

---

## 2. Short Selling Implementation

### Strategy Class Changes

The **only** required class-level change is:

```python
class MyFuturesStrategy(IStrategy):
    can_short = True  # DEFAULT is False -- must be explicitly enabled
```

**Critical**: Strategies with `can_short = True` will **fail to load on spot markets**. You cannot use the same strategy file for both spot and futures without conditional logic.

### Signal Columns

| Signal Column | Purpose |
|---|---|
| `enter_long` | Open a long position (same as spot `enter_long`) |
| `exit_long` | Close a long position |
| `enter_short` | Open a short position (NEW) |
| `exit_short` | Close a short position (NEW) |
| `enter_tag` | Tag shared by both long and short entries |
| `exit_tag` | Tag shared by both long and short exits |

### Code Example: Long + Short Strategy

```python
class MyFuturesStrategy(IStrategy):
    can_short = True
    stoploss = -0.10  # 10% risk per trade (applies to both directions)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Long entry
        dataframe.loc[
            (
                (qtpylib.crossed_above(dataframe['rsi'], 30)) &
                (dataframe['tema'] <= dataframe['bb_middleband']) &
                (dataframe['tema'] > dataframe['tema'].shift(1)) &
                (dataframe['volume'] > 0)
            ),
            ['enter_long', 'enter_tag']] = (1, 'rsi_cross_up')

        # Short entry
        dataframe.loc[
            (
                (qtpylib.crossed_below(dataframe['rsi'], 70)) &
                (dataframe['tema'] > dataframe['bb_middleband']) &
                (dataframe['tema'] < dataframe['tema'].shift(1)) &
                (dataframe['volume'] > 0)
            ),
            ['enter_short', 'enter_tag']] = (1, 'rsi_cross_down')

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Exit long
        dataframe.loc[
            (
                (qtpylib.crossed_above(dataframe['rsi'], 70)) &
                (dataframe['volume'] > 0)
            ),
            ['exit_long', 'exit_tag']] = (1, 'rsi_too_high')

        # Exit short
        dataframe.loc[
            (
                (qtpylib.crossed_below(dataframe['rsi'], 30)) &
                (dataframe['volume'] > 0)
            ),
            ['exit_short', 'exit_tag']] = (1, 'rsi_too_low')

        return dataframe
```

### Signal Collision Rules

When multiple signals fire on the same candle, Freqtrade applies these rules:
- `enter_long` + `exit_long` on same candle: **entry is ignored**
- `enter_short` + `exit_short` on same candle: **entry is ignored**
- `enter_long` + `enter_short` on same candle: **both are ignored**

You cannot flip from long to short in a single candle. The current position must be exited first, then a new entry on the next candle.

### Custom Callbacks with Short Positions

All callbacks receive `trade.is_short` to differentiate:

```python
def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
    if trade.is_short:
        # Different stoploss logic for shorts
        ...
    else:
        # Long stoploss logic
        ...
```

---

## 3. Leverage Configuration

### Static Leverage (Config-Level)

There is no config-level leverage setting. Leverage is always controlled via the strategy callback.

### Dynamic Leverage via Strategy Callback

```python
def leverage(self, pair: str, current_time: datetime, current_rate: float,
             proposed_leverage: float, max_leverage: float, entry_tag: str | None,
             side: str, **kwargs) -> float:
    """
    Returns leverage between 1.0 and max_leverage.
    Values above max_leverage are automatically clamped.
    If not implemented, defaults to 1.0 (no leverage).
    """
    # Simple: fixed 3x leverage
    return 3.0
```

### Dynamic Leverage Examples

```python
def leverage(self, pair: str, current_time: datetime, current_rate: float,
             proposed_leverage: float, max_leverage: float, entry_tag: str | None,
             side: str, **kwargs) -> float:

    # Per-pair leverage
    if pair in ('BTC/USDT:USDT', 'ETH/USDT:USDT'):
        return 5.0  # Higher leverage for majors
    return 2.0  # Conservative for alts

    # Or: direction-based leverage
    if side == 'short':
        return 2.0  # Less leverage for shorts (more volatile)
    return 3.0
```

### Leverage Impact on Stoploss

**This is the single most important thing to understand.**

Stoploss in Freqtrade represents **risk on the trade**, not price movement. All profit and stoploss calculations include leverage automatically.

| Leverage | Stoploss Setting | Actual Price Move to Trigger |
|----------|-----------------|------------------------------|
| 1x | -10% | 10% price drop |
| 3x | -10% | 3.33% price drop |
| 5x | -10% | 2% price drop |
| 10x | -10% | 1% price drop |

**Formula**: `price_move = stoploss / leverage`

So your existing stoploss settings (-8% to -15%) would trigger **much faster** with leverage:
- MasterTraderV1 at -15% with 3x leverage: triggers at 5% price move
- NASOSv5 at -8% with 3x leverage: triggers at 2.67% price move

### stoploss_from_open with Leverage

The `stoploss_from_open()` helper was fixed in PR #8273 to properly handle leverage. Pass `leverage=trade.leverage`:

```python
stoploss_from_open(0.07, current_profit, is_short=trade.is_short, leverage=trade.leverage)
```

This is critical given your existing stoploss_from_open bug history -- the function now properly accounts for leverage internally.

---

## 4. Funding Rates

### What Are Funding Rates?

Perpetual futures contracts have no expiry date. Instead, funding rates periodically (usually every 8 hours on Binance) transfer money between longs and shorts to keep the contract price anchored to spot:

- **Positive funding rate**: Longs pay shorts (bullish market)
- **Negative funding rate**: Shorts pay longs (bearish market)
- Typical range: -0.01% to +0.03% per 8h period

### How Freqtrade Handles Funding

- Freqtrade **automatically downloads funding rate candles** alongside mark price and regular candles when in futures mode
- Funding costs are **included in profit calculations** during backtesting and live trading
- The `current_profit` value in callbacks **already includes accumulated funding fees**

### Backtesting Caveat

Historical funding rate data may not be available for all pairs/timeranges. When missing:

```json
{
    "futures_funding_rate": 0
}
```

Setting this to 0 means backtesting ignores funding costs for periods without data. Setting it to any other value has **drastic effects on profit calculations** in `custom_stoploss` and `custom_exit`.

### Downloading Futures Data

```bash
freqtrade download-data \
    --exchange binance \
    --pairs ETH/USDT:USDT BTC/USDT:USDT \
    --trading-mode futures \
    --timeframes 5m 1h \
    --timerange 20250101-
```

This automatically downloads:
- Regular OHLCV candles
- Mark price candles
- Funding rate candles

### Binance Funding Rate Changes (2025+)

Binance no longer always uses 8-hour funding rate intervals. Some pairs have shifted to 4-hour intervals, which can cause **gaps in historic data collection** (GitHub issue #12583). Freqtrade handles this, but be aware during backtesting older data.

### Strategy Access to Funding Rates

You cannot directly use funding rates as a feature in `populate_indicators()` without custom data handling. The funding rate is primarily consumed internally by Freqtrade's profit calculations.

---

## 5. Liquidation Risk & Protection

### Liquidation Buffer

Freqtrade provides a configurable safety cushion between your stoploss and the exchange liquidation price:

```json
{
    "liquidation_buffer": 0.05
}
```

**Default: 0.05 (5%)**

Formula:
```
freqtrade_liq_price = liquidation_price ± (abs(open_rate - liquidation_price) * liquidation_buffer)
```

This means Freqtrade will trigger its own stoploss **before** the exchange liquidation price, giving a 5% buffer.

### How Liquidation Interacts with Stoploss

The effective stoploss is the **tighter** of:
1. Your configured stoploss (or custom_stoploss return value)
2. The liquidation buffer price

If your stoploss would trigger after the liquidation price, Freqtrade overrides it with the liquidation buffer price.

### Practical Example

```
Open price: $100
Leverage: 10x
Stoploss: -10%
Exchange liquidation price: ~$91 (varies by fees/maintenance margin)
Liquidation buffer (5%): $91 + ($100 - $91) * 0.05 = $91.45

Stoploss triggers at: $99 (1% move = 10% loss at 10x)
Liquidation at: $91
Buffer at: $91.45

In this case, the stoploss fires well before liquidation. Safe.
```

**Danger scenario:**
```
Open price: $100
Leverage: 10x
Stoploss: -50% (way too loose!)
Exchange liquidation at: ~$91

Stoploss would trigger at: $95 (5% move = 50% loss at 10x)
Wait, that's still before liquidation. But...
```

The real danger is when stoploss is so loose it exceeds the liquidation price. Freqtrade will clamp to the liquidation buffer, but in fast-moving markets with no liquidity, even exchange stop-market orders can miss.

### Best Practices for Liquidation Avoidance

1. **Always use `stoploss_on_exchange: true`** with futures -- this places the stop order on the exchange itself, surviving bot crashes
2. **Keep leverage low** (2x-3x for alts, up to 5x for BTC/ETH)
3. **Keep `liquidation_buffer` at 0.05 or higher**
4. **Never set stoploss looser than what leverage allows** -- e.g., at 10x, a -50% stoploss means a 5% price move, which is well within normal volatility

---

## 6. Isolated vs Cross Margin

### Current Support Status

| Margin Mode | Status | Notes |
|---|---|---|
| `isolated` | **Fully supported** | Recommended for bot trading |
| `cross` | **Supported since 2025.1** | Required for BNFCR (EU), added via PR #11120 |

### Isolated Margin (Recommended)

```json
{ "margin_mode": "isolated" }
```

- Each position has its own collateral
- A losing trade can only lose the margin assigned to that specific position
- **Other positions are unaffected** if one gets liquidated
- Liquidation price is clearly defined per position
- **Best for automated trading** -- limits blast radius of any single bad trade

### Cross Margin

```json
{ "margin_mode": "cross" }
```

- All positions share the account balance as collateral
- A losing position borrows margin from the total account balance
- **One bad trade can liquidate your entire account**
- Liquidation prices shift as other positions move
- Freqtrade cannot fully simulate cross-margin effects in backtesting

### BNFCR Mode (EU Traders Only)

If you're in the EEA, Binance forces BNFCR credits for futures:

```json
{
    "trading_mode": "futures",
    "margin_mode": "cross",
    "proxy_coin": "BNFCR"
}
```

This also requires Multi-Asset Mode enabled on Binance.

### Recommendation for Your Setup

**Use isolated margin.** Since you're not in the EU (Brazil), you have full access to isolated margin on Binance futures. Isolated is the only sane choice for automated trading because:
- Each bot's trades are independently isolated
- A flash crash on one alt won't cascade to all positions
- Risk is predictable and matches backtesting assumptions

---

## 7. FreqAI + Futures

### Compatibility

FreqAI works with futures mode. Your MasterTraderAI bot can be adapted for futures trading.

### Standard ML Models (XGBoost, LightGBM, etc.)

- Work identically in futures mode
- Can predict both long and short signals
- Set `can_short = True` in your FreqAI strategy
- Use `enter_short`/`exit_short` columns based on model predictions
- No special configuration needed beyond the standard futures config

### Reinforcement Learning (RL) Environments

FreqAI provides RL environments with built-in short support:

| Environment | Actions | Short Support |
|---|---|---|
| `Base3ActionRLEnv` | Neutral, Long, Exit | **No** (long only) |
| `Base4ActionRLEnv` | Neutral, Long, Short, Exit | **Yes** (shared exit) |
| `Base5ActionRLEnv` | Neutral, Long, Exit Long, Short, Exit Short | **Yes** (separate exits) |

### Important RL Limitation

The RL training environment is **simplified** and does NOT incorporate:
- `custom_stoploss` callbacks
- `custom_exit` callbacks
- Leverage controls
- Funding rate costs

This means RL models trained in the simplified env may not perform identically in live futures trading where these factors matter. **Custom implementation beyond the standard framework would be required** to properly account for leverage in RL training.

### Recommendation for MasterTraderAI

Since your current MasterTraderAI uses XGBoost (not RL), the transition to futures is straightforward:
1. Add `can_short = True` to the strategy
2. Train the model with features that capture both bullish and bearish setups
3. Map model predictions to both `enter_long` and `enter_short` signals
4. Add the `leverage()` callback (start conservative at 2x)
5. Update the config for futures mode

---

## 8. Docker Setup Alongside Spot Bots

### Architecture Decision: Same docker-compose.yml

You can absolutely add futures bots to your existing `docker-compose.yml`. Each bot is an independent service with its own config. There is **no conflict** between spot and futures bots running side by side.

### Example: Adding a Futures Bot

In your existing `~/ft_userdata/docker-compose.yml`, add a new service:

```yaml
  freqtrade_futures_1:
    image: freqtradeorg/freqtrade:stable
    restart: unless-stopped
    container_name: ft-futures-supertrend
    volumes:
      - ./user_data:/freqtrade/user_data
    ports:
      - "8090:8080"
    command: >
      trade
      --logfile /freqtrade/user_data/logs/futures_supertrend.log
      --db-url sqlite:////freqtrade/user_data/databases/futures_supertrend.sqlite
      --config /freqtrade/user_data/configs/FuturesSupertrend.json
    extra_hosts:
      # Same Binance IP pinning as your spot bots for VPN bypass
      - "api.binance.com:18.141.245.23"
      - "fapi.binance.com:18.141.245.23"
```

### Key Differences from Spot Services

1. **Unique port**: Use 8090+ for futures bots (your spot bots use 8080-8089)
2. **Separate database**: Each bot must have its own `.sqlite` file
3. **Separate config**: The futures config has `trading_mode: futures`
4. **Separate log file**: For debugging
5. **Futures API endpoint**: Note `fapi.binance.com` in extra_hosts -- the futures API uses a different subdomain than spot (`api.binance.com`)
6. **FreqAI image**: If running MasterTraderAI on futures, use `freqtradeorg/freqtrade:stable_freqai`

### Shared Resources

These can be shared between spot and futures bots:
- Strategy files (with `can_short` conditional logic if needed)
- The `user_data` volume mount
- Prometheus metrics exporter (already scraping multiple bots)

### Separate Telegram Bot?

Recommended: use a **different Telegram bot token** for futures bots to keep notifications separate. At minimum, use different `chat_id` groups.

---

## 9. Binance Futures API Specifics

### API Key Requirements

1. **Enable Futures permission** on your API key in Binance settings
2. The API key must have been created **after** the Futures account was activated. If your key was created before enabling Futures, you need a new key.
3. IP whitelisting applies to both spot and futures endpoints

### API Endpoints

| Type | Endpoint |
|------|----------|
| Spot | `api.binance.com` |
| Futures (USD-M) | `fapi.binance.com` |
| Futures (COIN-M) | `dapi.binance.com` |

For your VPN bypass `extra_hosts`, you'll need to add the `fapi.binance.com` IP alongside your existing spot API IPs.

### Rate Limits

| Limit Type | Spot | Futures |
|---|---|---|
| Request weight per IP | 1,200/min | 2,400/min |
| Order rate per account | 10/sec, 100K/day | 300/10sec, 1,200/min |

Futures actually has **more generous** rate limits than spot. Running 7 spot bots + 1-2 futures bots should not hit limits.

### Testnet

Binance has a separate futures testnet at `testnet.binancefuture.com`. Freqtrade supports it via:
```json
{
    "exchange": {
        "name": "binance",
        "urls": {
            "api": "https://testnet.binancefuture.com"
        }
    }
}
```

However, dry-run mode is usually sufficient and more reliable than the testnet.

---

## 10. Common Pitfalls & Migration Checklist

### Pitfall 1: Reusing Spot Strategies Without Adjustment

Your spot strategies (ClucHAnix, NASOSv5, etc.) are tuned for long-only spot trading. Simply flipping `trading_mode` to futures and adding `can_short = True` will likely produce bad results because:
- Entry conditions optimized for buying dips don't work inverted for shorts
- Stoploss values calibrated for spot volatility may be too tight/loose with leverage
- ROI tables need recalibration for leveraged profit magnitudes

**Do**: Create dedicated futures strategies or carefully adapt existing ones with separate long/short logic.

### Pitfall 2: Stoploss Too Loose for Leverage

With leverage, your existing stoplosses become dangerously loose:

| Strategy | Spot Stoploss | At 3x Leverage | At 5x Leverage |
|---|---|---|---|
| MasterTraderV1 | -15% | -45% of capital | -75% of capital |
| ClucHAnix | -10% | -30% of capital | -50% of capital |
| NASOSv5 | -8% | -24% of capital | -40% of capital |

**Do**: Tighten stoplosses proportionally to leverage. A good rule: `new_stoploss = old_stoploss / leverage`.

### Pitfall 3: Ignoring Funding Rates in Backtesting

Backtests without accurate funding rate data show inflated profits. A position held for 3 days in a high-funding environment could lose 0.3-0.9% in funding alone.

**Do**: Download futures data with `--trading-mode futures` (auto-includes funding rates). Set `futures_funding_rate: 0` only as a fallback.

### Pitfall 4: Not Using stoploss_on_exchange

Without `stoploss_on_exchange`, your stoploss only triggers when the bot checks on each candle close. With 5x leverage, a 2% flash crash triggers a 10% loss -- and if the bot is slow to react, it could be worse.

**Do**: Always set `stoploss_on_exchange: true` and use `"stoploss": "market"` for guaranteed fills.

### Pitfall 5: cross_margin with Multiple Bots

If two futures bots trade on the same Binance subaccount with cross margin, their positions share collateral. A catastrophic loss in one bot can liquidate positions from the other.

**Do**: Use isolated margin. If you must use cross, use **separate Binance sub-accounts** per bot.

### Pitfall 6: The stoploss_from_open -0.99 Bug (Your Existing Bug!)

This bug you already found affects futures too. With leverage, the -0.99 return value is even more catastrophic because it effectively removes the stoploss while leverage amplifies losses.

**Do**: Your existing fix (returning HSL directly instead of -0.99) must be applied to any futures strategy using `stoploss_from_open`.

### Pitfall 7: MaxDrawdown Protection is Still Global

Same issue you documented for spot -- `only_per_pair` is silently ignored. With leverage amplifying losses, hitting the MaxDrawdown threshold happens faster.

**Do**: Set MaxDrawdown protection appropriately. Consider lowering the threshold for futures bots (e.g., 15% instead of 20%).

### Pitfall 8: Backtesting Cross-Margin Is Inaccurate

Freqtrade cannot fully simulate cross-margin interactions in backtesting. Liquidation cascades and shared collateral effects are not modeled.

**Do**: Only trust backtesting results for isolated margin strategies.

### Pitfall 9: Position Size with Leverage

With leverage, your actual position size is `stake_amount * leverage`. If you use $100 stake with 5x leverage, you're controlling $500 worth of asset. Make sure your `max_open_trades * stake_amount` doesn't exceed what you're comfortable with in total exposure.

### Pitfall 10: Hyperopt Auto-Export (Your Existing Bug!)

The same `<Strategy>.json` auto-export bug applies to futures strategies. Hyperopt can silently override your carefully tuned leverage and stoploss parameters.

**Do**: Always use `--disable-param-export` with hyperopt.

---

## Migration Checklist

```
[ ] Create new API key with Futures permission enabled (or enable on existing key)
[ ] Set Binance account to One-way Mode + Single-Asset Mode
[ ] Add fapi.binance.com to extra_hosts in docker-compose (VPN bypass)
[ ] Create dedicated futures config (trading_mode, margin_mode, orderbook pricing)
[ ] Create/adapt strategy with can_short = True
[ ] Implement leverage() callback (start at 2x)
[ ] Tighten stoploss proportionally to leverage
[ ] Enable stoploss_on_exchange with market orders
[ ] Download futures data for backtesting
[ ] Backtest with futures mode (verify funding rate handling)
[ ] Start in dry-run mode on a new port (e.g., 8090)
[ ] Add to Grafana monitoring (new bot stat card)
[ ] Add to bot_rotator.py evaluation
[ ] Run dry-run for at least 2 weeks before going live
[ ] Consider separate Telegram bot for futures alerts
```

---

## Recommended Starting Point

Given your current setup and experience:

1. **Pick one strategy to adapt**: MasterTraderV1 is your most consistent -- start with a futures clone
2. **Start with long-only futures at 2x**: Set `can_short = False` initially, just add 2x leverage to amplify your existing edge
3. **Use isolated margin**: Non-negotiable for automated trading
4. **Stoploss**: If your spot stoploss is -15%, use -7.5% at 2x leverage (same dollar risk)
5. **Dry-run first**: Run alongside your spot bots for 2+ weeks
6. **Then add shorts**: Once comfortable with the futures mechanics, enable `can_short = True` with dedicated short logic
7. **Then try higher leverage**: Only after proving profitability at 2x

---

## Sources

- [Freqtrade Short/Leverage Documentation](https://www.freqtrade.io/en/stable/leverage/)
- [Freqtrade Configuration Reference](https://www.freqtrade.io/en/stable/configuration/)
- [Freqtrade Strategy Callbacks](https://www.freqtrade.io/en/stable/strategy-callbacks/)
- [Freqtrade Strategy Customization](https://www.freqtrade.io/en/stable/strategy-customization/)
- [Freqtrade Exchange-Specific Notes (Binance)](https://www.freqtrade.io/en/stable/exchanges/)
- [Freqtrade Stoploss Documentation](https://www.freqtrade.io/en/stable/stoploss/)
- [Freqtrade Data Downloading](https://www.freqtrade.io/en/stable/data-download/)
- [Freqtrade Docker Quickstart](https://www.freqtrade.io/en/stable/docker_quickstart/)
- [FreqAI Reinforcement Learning](https://www.freqtrade.io/en/stable/freqai-reinforcement-learning/)
- [FreqAI Introduction](https://www.freqtrade.io/en/stable/freqai/)
- [GitHub: stoploss_from_open leverage ambiguity (#8129)](https://github.com/freqtrade/freqtrade/issues/8129)
- [GitHub: Cross margin mode implementation (#10562)](https://github.com/freqtrade/freqtrade/issues/10562)
- [GitHub: BNFCR support PR (#11120)](https://github.com/freqtrade/freqtrade/pull/11120)
- [GitHub: Binance funding rate gaps (#12583)](https://github.com/freqtrade/freqtrade/issues/12583)
- [Binance Futures Rate Limits](https://www.binance.com/en/support/faq/rate-limits-on-binance-futures-281596e222414cdd9051664ea621cdc3)
- [Strat.ninja Binance Futures Config Example](https://strat.ninja/config.php?config=binance_USDT_v3_futures)
