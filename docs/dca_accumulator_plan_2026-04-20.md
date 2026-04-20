# DCA Accumulator V1 — Implementation Plan

> **Status**: Planned, not implemented. Drafted 2026-04-20.
> **Type**: Future work — regime-gated BTC/ETH accumulation overlay.
> **Not a trading bot**: zero alpha claims, pure long-drift capture with a trend filter.

## Problem this solves

The current fleet (Keltner + FundingFade) is 100% long mean-reversion, BTC-gated. Both
bots are structurally silent during strong BTC uptrends — they wait for pullbacks that
don't come. The result: idle capital during exactly the regime where buy-and-hold would
have made money. This plan captures trend drift without requiring a validated trading
signal, using the $200 freed from the FundingShort kill.

This is **NOT** a replacement for Keltner/FundingFade or the pending trend-strategy
research. It's a regime-complementary overlay.

## Design

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Capital | $200 | Freed from FundingShort kill, currently HOLD |
| Allocation | 60% BTC ($120), 40% ETH ($80) | BTC lead, ETH for beta |
| Cadence | $10 buy every Sunday 00:00 UTC | ~20 weeks runway; weekly is reasonable granularity |
| Regime gate | `BTC_close > BTC_50day_SMA` | Accumulate in uptrends only, pause in downtrends |
| Exit rule | **None** | Pure accumulation; bot never sells |
| Stoploss | `-1.0` (effectively off) | Positions never auto-close |
| ROI ladder | `{}` | No ROI exits |
| Max open trades | 1 at a time | Sequential accumulation, not simultaneous |
| Pair alternation | BTC on even Sundays, ETH on odd Sundays | Simple 60/40 approximation over ~20 weeks |

## Implementation

### New Freqtrade bot
- **Name**: `DCAAccumulatorV1`
- **Port**: 8097 (Keltner=8095, FundingFade=8096)
- **Strategy file**: `ft_userdata/user_data/strategies/DCAAccumulatorV1.py`
- **Config**: `ft_userdata/user_data/configs/DCAAccumulatorV1.json`
- **Docker compose service**: `dcaaccumulatorv1` (modeled on keltnerbouncev1)

### Strategy pseudocode
```python
class DCAAccumulatorV1(IStrategy):
    timeframe = "1d"
    stoploss = -1.0
    minimal_roi = {}
    use_exit_signal = False

    @informative("1d", "BTC/{stake}")
    def populate_indicators_btc_1d(self, dataframe, metadata):
        dataframe["sma50"] = dataframe["close"].rolling(50).mean()
        return dataframe

    def populate_indicators(self, dataframe, metadata):
        dataframe["btc_trend_ok"] = (
            dataframe["btc_usdt_close_1d"] > dataframe["btc_usdt_sma50_1d"]
        ).astype(int)
        dataframe["is_sunday"] = (dataframe["date"].dt.dayofweek == 6).astype(int)
        dataframe["week_number"] = dataframe["date"].dt.isocalendar().week
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        pair = metadata["pair"]
        # Alternate: BTC on even weeks, ETH on odd weeks
        week_parity_match = (
            (dataframe["week_number"] % 2 == 0) if pair == "BTC/USDT"
            else (dataframe["week_number"] % 2 == 1)
        )
        dataframe.loc[
            (dataframe["is_sunday"] == 1)
            & (dataframe["btc_trend_ok"] == 1)
            & week_parity_match,
            "enter_long"
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        return dataframe  # Never exit
```

### Config highlights
```json
{
  "dry_run": true,
  "dry_run_wallet": 200,
  "stake_amount": 10,
  "max_open_trades": 1,
  "trading_mode": "spot",
  "exchange": {
    "name": "binance",
    "pair_whitelist": ["BTC/USDT", "ETH/USDT"]
  },
  "pairlists": [{"method": "StaticPairList"}],
  "bot_name": "DCAAccumulator"
}
```

### Docker compose entry
```yaml
dcaaccumulatorv1:
  image: freqtradeorg/freqtrade:stable
  restart: always
  container_name: ft-dca-accumulator
  extra_hosts: *binance-hosts
  volumes:
    - "./user_data:/freqtrade/user_data"
  ports:
    - "127.0.0.1:8097:8080"
  healthcheck: *bot-healthcheck
  deploy:
    resources:
      limits:
        memory: 512M
  entrypoint: ["/bin/sh", "-c", "sleep 80 && exec freqtrade trade --logfile /freqtrade/user_data/logs/DCAAccumulatorV1.log --config /freqtrade/user_data/configs/DCAAccumulatorV1.json --strategy DCAAccumulatorV1"]
```

## Not required (explicit non-features)

- **No graduation**: DCA is not subject to Phase 5 gates. This is spot accumulation, not alpha.
- **No backtest**: BTC is up ~180% over the 3.3yr backtest window; any regime-filtered DCA with trend gate is positive-expectancy by construction. Running a backtest to "validate" adds no signal.
- **No stop-loss**: positions held through drawdowns like any BTC/ETH holder.
- **No kill switch**: worst case is you end up holding BTC+ETH during a bear — which is what BTC+ETH owners do anyway.

## Monitoring

Grafana panel: `DCA Accumulator` showing:
- Cumulative accumulated value (current holdings × spot price)
- Comparison line: pure buy-and-hold same capital (no regime gate)
- Comparison line: pure DCA no filter (every Sunday regardless of regime)

Purpose: confirm the regime filter adds value (or at least doesn't hurt meaningfully).

## Decision points

Before implementing, confirm:
- [ ] Do we want to spend the $200 on accumulation vs reserving it for micro-live on
      Keltner+FundingFade (Path A)? These are mutually exclusive uses of the same capital.
- [ ] Weekly cadence acceptable, or prefer bi-weekly ($20/buy, 10-week runway)?
- [ ] BTC-only vs BTC+ETH split? ETH beta could help or hurt — pick based on beliefs.
- [ ] Regime gate on BTC 50-day SMA — tighter (50+200 SMA alignment) or looser (just 50)?

## Implementation effort

~1 hour: write strategy, write config, add compose service, restart stack, verify dry-run.
No data download needed, no backtest needed.

## When to kill this overlay

- If BTC enters a multi-year bear (BTC < 200-day SMA for 90+ days): regime gate
  will have already paused buys; review whether to exit accumulated position manually.
- If freed capital is needed for a validated trading bot graduating to live: redirect.
- If Freqtrade exposes a structural bug with "never-exit" strategies: migrate to a
  standalone cron job.

## Why this is in plans rather than shipped

The capital decision matters: same $200 can go here (drift capture) or toward Path A
(micro-live on validated bots). Separate implementation from that decision.
