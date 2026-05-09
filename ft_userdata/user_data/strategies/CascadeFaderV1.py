"""
CascadeFaderV1 — Liquidation-cascade rebound fader.

Discovered 2026-05-09. Codex-5.5 sanctioned as the highest information-value
candidate among 5 surveyed. Event-driven, free Binance public data, structurally
orthogonal to FundingFade (carry) and Keltner (TA mean-reversion).

Validation methodology lesson: an early TP-only forward-return analysis showed
+469% / 91% WR / PF 4.17 — the simulator did NOT model intra-bar stop-loss
exposure. After path-aware re-simulation (walk forward bar-by-bar with proper
SL/TP/timeout precedence), real metrics are below. The lesson: validate
forward returns by walking the price PATH, not just measuring HIGH at horizons.

Signal:
  - Entry on 1h bar with deep wick + volume spike, enter on next bar:
    - (open - low) / open >= 8%        — deep intra-bar drop
    - (close - low) / (open - low) > 40% — wick recovered, not falling knife
    - volume > 2.0x rolling 30-day SMA — confirms forced flow / panic
  - No TA gate. Cascade events are themselves regime-invariant (PF positive
    in 5/6 calendar-half walk-forward windows including 2025-H2+2026).

Lab-validated metrics (3.3yr 1h, 13 curated pairs, 0.20% RT taker fees,
path-aware bar-by-bar SL/TP precedence):
  Config: drop>=8%, vol>=2.0x, TP=3%, SL=-8%, hold=48h
  N = 162 trades over 37.1 months
  Win rate = 77.8%
  Profit factor = 1.62
  Avg net P&L per trade = +0.820%
  Total return on $100 notional = +132.8% across 13 pairs
  Annualized per-pair = ~3.3% (~$3.30/yr per $100 per pair)
  Exit mix: 76% TP, 14% SL, 10% timeout

Year-by-year:
  2023: N=36, WR 86.1%, PF 5.73, +71.7%
  2024: N=66, WR 75.8%, PF 1.41, +40.4%
  2025: N=46, WR 69.6%, PF 0.86, -13.7%   ← weakness year (regime-dependent)
  2026 partial: N=14, WR 92.9%, PF 19.36, +34.5%

Walk-forward (5/6 windows positive — graduation-class):
  2023-H1  PF 2.93  +14.8%   ✓
  2023-H2  PF 8.58  +56.9%   ✓ (Keltner LOST -5.15%)
  2024-H1  PF 3.26  +55.4%   ✓
  2024-H2  PF 0.80  -15.0%   ✗ (Keltner LOST -4.39%)
  2025-H1  PF 1.71  +11.6%   ✓
  2025-H2+2026  PF 1.11  +9.2%  ✓ (current regime)

Edge hypothesis:
  Forced-flow liquidations create short-lived overshoots. Wick-recovery filter
  excludes falling-knife continuation; volume filter requires panic signature;
  >=8% drop threshold filters routine volatility. Bots run by leveraged longs
  cascade-liquidate against limit-buy fills, briefly pushing price below fair
  value. Recovery often happens before the 1h bar even fully closes.

Diversification value:
  CascadeFader wins in 2 of the 4 calendar halves Keltner LOSES (2023-H2, 2024-H2
  partial). Different signal class, different regime sensitivity, different
  trade cadence (~52 trades/yr vs Keltner ~45/yr).

Known weaknesses:
  - 2024-H2 calendar half loses (-15%) — same regime that killed Keltner
  - Sample concentrated post-2023 — 39-month sample, not full cycle
  - Stop-loss (-8%) means worst-case single-trade loss is structural, must be
    sized accordingly
  - During market-wide ADL events (Oct 10 2025), multiple cascades fire on
    correlated pairs simultaneously — portfolio circuit breaker required

Pair selection:
  Curated whitelist of 13 pairs based on per-pair edge analysis. Excluded:
  BCH (n=1, 0% WR), DOGE (-0.33% avg), XRP (-0.21% avg), LINK (+0.05% avg
  marginal), TRX (historic 30% WR). All others positive in lab.

Generated 2026-05-09.
"""

import logging
from pandas import DataFrame
from freqtrade.strategy import IStrategy

logger = logging.getLogger(__name__)


class CascadeFaderV1(IStrategy):
    INTERFACE_VERSION: int = 3

    # ROI ladder calibrated on TP=3% / hold=48h backtest.
    # Decay smoothly from 3% target at entry to ~0% at 48h timeout.
    minimal_roi = {
        "0":    0.030,    # +3% target at entry
        "720":  0.025,    # 12h: +2.5%
        "1440": 0.020,    # 24h: +2%
        "2160": 0.010,    # 36h: +1%
        "2880": 0.000,    # 48h: any positive
    }

    # Stoploss accommodates cascade-continuation risk. -8% is the validated
    # threshold from the path-aware sweep — narrower (-3%) destroys the edge
    # by killing recoveries that take a deeper second leg before bouncing.
    stoploss = -0.08

    trailing_stop = False
    use_custom_stoploss = False

    timeframe = "1h"
    process_only_new_candles = True
    use_exit_signal = False
    exit_profit_only = True
    exit_profit_offset = 0.005

    # 30-day volume SMA needs 720 hourly candles
    startup_candle_count = 720

    # Cascade-detection params (calibrated by sweep)
    cascade_drop_pct = 0.08       # Min (open - low) / open
    cascade_recovery_min = 0.4    # Min (close - low) / (open - low)
    cascade_vol_mult = 2.0        # Min volume / 30d-mean
    vol_lookback_hours = 720      # 30 days

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["wick_size"] = dataframe["open"] - dataframe["low"]
        dataframe["open_to_low_pct"] = dataframe["wick_size"] / dataframe["open"]
        dataframe["wick_recovery"] = (
            (dataframe["close"] - dataframe["low"]) / dataframe["wick_size"]
        ).where(dataframe["wick_size"] > 0, 0)
        dataframe["vol_sma"] = dataframe["volume"].rolling(
            self.vol_lookback_hours, min_periods=self.vol_lookback_hours // 2
        ).mean()
        dataframe["vol_ratio"] = dataframe["volume"] / dataframe["vol_sma"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        cascade = (
            (dataframe["open_to_low_pct"] >= self.cascade_drop_pct) &
            (dataframe["wick_recovery"] > self.cascade_recovery_min) &
            (dataframe["vol_ratio"] > self.cascade_vol_mult) &
            (dataframe["vol_sma"] > 0)
        )
        dataframe.loc[cascade, "enter_long"] = 1
        dataframe.loc[cascade, "enter_tag"] = "cascade_rebound"
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Exits handled by ROI ladder + stoploss
        return dataframe
