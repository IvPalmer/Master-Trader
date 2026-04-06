# SMB-Inspired Trading Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 7 improvements derived from SMB Capital research — from structural trailing stops to confidence-based sizing, volume capitulation filters, time-of-day analysis, bounce-long mode, AI trade autopsy, and theme-aware pairlists.

**Architecture:** Each task modifies one strategy file or one analysis script. All changes are additive — no existing logic removed, only enhanced. New features gate behind existing patterns (custom_stoploss, custom_stake_amount, populate_indicators). Tests validate each change independently.

**Tech Stack:** Python 3.11, Freqtrade 2024.x, pandas, pytest, Freqtrade API

---

## File Map

| File | Responsibility | Tasks |
|------|---------------|-------|
| `ft_userdata/user_data/strategies/SupertrendStrategy.py` | Trend-following strategy | Task 1 (N-bar trail), Task 4 (confidence sizing) |
| `ft_userdata/user_data/strategies/BollingerBounceV1.py` | Mean-reversion strategy | Task 2 (volume capitulation) |
| `ft_userdata/trade_analyzer.py` | Trade performance analysis | Task 3 (time-of-day analysis) |
| `ft_userdata/user_data/strategies/BearCrashShortV1.py` | Short-only bear regime | Task 5 (bounce-long mode) |
| `ft_userdata/user_data/strategies/market_intelligence.py` | Shared cross-bot module | Task 7 (theme detection helper) |
| `ft_userdata/ai_trade_autopsy.py` | NEW: AI trade review automation | Task 6 |
| `tests/test_supertrend_improvements.py` | Tests for Tasks 1, 4 | Tasks 1, 4 |
| `tests/test_bollinger_improvements.py` | Tests for Task 2 | Task 2 |
| `tests/test_trade_analyzer_sessions.py` | Tests for Task 3 | Task 3 |
| `tests/test_bear_bounce.py` | Tests for Task 5 | Task 5 |
| `tests/test_ai_autopsy.py` | Tests for Task 6 | Task 6 |
| `tests/test_theme_detection.py` | Tests for Task 7 | Task 7 |

---

## Task 1: N-Bar Trailing Stop for SupertrendStrategy

**Priority:** HIGH — directly targets the R:R inversion problem (avg win $0.48 vs avg loss $1.12)

**Concept:** Replace fixed-percentage trailing (2% trail @ 3% offset) with a structure-based trail that uses the lowest low of the last N candles. This adapts to volatility naturally — wide candles = wide stop, tight candles = tight stop — and lets winners run further.

**Files:**
- Modify: `ft_userdata/user_data/strategies/SupertrendStrategy.py` (add `custom_stoploss` method)
- Create: `tests/test_supertrend_improvements.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_supertrend_improvements.py
"""Tests for SupertrendStrategy improvements (N-bar trailing stop, confidence sizing)."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock
from datetime import datetime, timezone

import pytest

STRATEGY_PATH = Path(__file__).parent.parent / "ft_userdata" / "user_data" / "strategies" / "SupertrendStrategy.py"


def _load_strategy_module():
    spec = importlib.util.spec_from_file_location("SupertrendStrategy", STRATEGY_PATH)
    mod = importlib.util.module_from_spec(spec)
    # Mock freqtrade imports
    for name in ["freqtrade.strategy", "freqtrade.strategy.interface", "freqtrade.persistence"]:
        sys.modules.setdefault(name, MagicMock())
    spec.loader.exec_module(mod)
    return mod


class TestNBarTrailingStop:
    """Test the N-bar structure-based trailing stop."""

    def test_custom_stoploss_method_exists(self):
        mod = _load_strategy_module()
        strategy = mod.SupertrendStrategy
        assert hasattr(strategy, 'custom_stoploss'), "custom_stoploss method must exist"

    def test_custom_stoploss_uses_n_bar_logic(self):
        """custom_stoploss source should reference lowest low trailing logic."""
        source = STRATEGY_PATH.read_text()
        assert "custom_stoploss" in source
        # Should reference candle lows for trailing
        assert "low" in source.split("custom_stoploss")[1][:500].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_supertrend_improvements.py::TestNBarTrailingStop -v`
Expected: FAIL — `custom_stoploss` method does not exist yet

- [ ] **Step 3: Implement the N-bar trailing stop**

Add `custom_stoploss` method and `use_custom_stoploss = True` to SupertrendStrategy. The logic:
- For the first 2 candles, use default stoploss (-5%)
- After 2 candles, calculate lowest low of last 3 candles as the trailing stop
- Stop only tightens (moves up), never loosens
- Falls back to default stoploss if N-bar stop would be wider than -5%

Add to `SupertrendStrategy.py` after line ~37 (after trailing_stop settings):

```python
    use_custom_stoploss = True

    # N-bar trailing: use lowest low of last N candles as structure-based stop
    n_bar_lookback = 3
```

Disable the built-in trailing (since custom_stoploss will handle it):

```python
    trailing_stop = False  # Handled by custom_stoploss N-bar logic
    # trailing_stop_positive = 0.02  # Superseded
    # trailing_stop_positive_offset = 0.03  # Superseded
    # trailing_only_offset_is_reached = True  # Superseded
```

Add the method after the existing `confirm_trade_exit` method:

```python
    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        """
        N-bar trailing stop: trail using lowest low of last N candles.
        Adapts to volatility — wide candles = wide stop, tight candles = tight stop.
        Inspired by Lance Breitstein's 2-bar trailing methodology.
        """
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return self.stoploss  # -0.05

        last_candle = dataframe.iloc[-1]
        trade_candles = len(dataframe.loc[dataframe['date'] >= trade.open_date_utc])

        # Not enough candles yet — use default stoploss
        if trade_candles < self.n_bar_lookback:
            return self.stoploss

        # Lowest low of last N candles
        recent_lows = dataframe['low'].tail(self.n_bar_lookback)
        n_bar_low = recent_lows.min()

        # Calculate stoploss relative to current rate
        sl_from_current = (n_bar_low / current_rate) - 1.0

        # Never wider than default stoploss (-5%)
        if sl_from_current < self.stoploss:
            return self.stoploss

        # Never return positive (that would close the trade)
        if sl_from_current >= 0:
            return -0.001  # Extremely tight — close on next tick

        return sl_from_current
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_supertrend_improvements.py::TestNBarTrailingStop -v`
Expected: PASS

- [ ] **Step 5: Run existing strategy tests to confirm no regression**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_strategies.py -v -k supertrend`
Expected: All existing tests pass

- [ ] **Step 6: Commit**

```bash
git add ft_userdata/user_data/strategies/SupertrendStrategy.py tests/test_supertrend_improvements.py
git commit -m "feat(SupertrendStrategy): add N-bar trailing stop to fix R:R inversion

Replace fixed-percentage trailing (2% @ 3% offset) with structure-based
trail using lowest low of last 3 candles. Adapts to volatility naturally.
Inspired by Lance Breitstein's methodology (SMB Capital research).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Volume Capitulation Filter for BollingerBounceV1

**Priority:** HIGH — adds volume confirmation to mean-reversion entries

**Concept:** Add a volume spike indicator (current volume > 2x 20-period SMA of volume) as an entry enhancer. When a Bollinger bounce happens WITH capitulation volume, it's a much higher-probability entry. Without 2x volume, still allow entry but flag it differently.

**Files:**
- Modify: `ft_userdata/user_data/strategies/BollingerBounceV1.py` (lines ~42-64)
- Create: `tests/test_bollinger_improvements.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bollinger_improvements.py
"""Tests for BollingerBounceV1 volume capitulation filter."""
from pathlib import Path

STRATEGY_PATH = Path(__file__).parent.parent / "ft_userdata" / "user_data" / "strategies" / "BollingerBounceV1.py"


class TestVolumeCapitulationFilter:
    """Volume capitulation indicator must be calculated and used in entries."""

    def test_volume_sma_calculated(self):
        source = STRATEGY_PATH.read_text()
        assert "volume_sma" in source, "Must calculate volume SMA for capitulation detection"

    def test_volume_ratio_calculated(self):
        source = STRATEGY_PATH.read_text()
        assert "volume_ratio" in source, "Must calculate volume ratio (current / SMA)"

    def test_entry_uses_volume_capitulation(self):
        source = STRATEGY_PATH.read_text()
        # Entry trend section should reference volume_ratio
        entry_section = source.split("populate_entry_trend")[1][:800]
        assert "volume_ratio" in entry_section, "Entry logic must consider volume ratio"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_bollinger_improvements.py -v`
Expected: FAIL — volume_sma/volume_ratio not in source

- [ ] **Step 3: Implement volume capitulation indicator**

In `BollingerBounceV1.py`, add to `populate_indicators` (after existing indicators around line 49):

```python
        # Volume capitulation detection (Lance Breitstein: 2x volume = capitulation)
        dataframe['volume_sma'] = dataframe['volume'].rolling(window=20).mean()
        dataframe['volume_ratio'] = dataframe['volume'] / (dataframe['volume_sma'] + 1e-10)
```

Modify `populate_entry_trend` to add volume capitulation as a strong preference. Change the entry condition (around line 51-64) to require volume_ratio >= 1.5 (slightly relaxed from 2x to not filter too aggressively on a bot that already had 0 trades at 3-sigma):

```python
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Bollinger lower band bounce
                (dataframe['close'] > dataframe['bb_lower']) &
                (dataframe['close'].shift(1) <= dataframe['bb_lower'].shift(1)) &
                # RSI in mean-reversion zone
                (dataframe['rsi'] >= 30) &
                (dataframe['rsi'] <= 70) &
                # ADX confirms trend strength
                (dataframe['adx'] > 25) &
                # Volume capitulation: require above-average volume on bounce
                (dataframe['volume_ratio'] >= 1.5) &
                # BTC market guard
                (dataframe['btc_gate'] == 1) &
                # Volume sanity
                (dataframe['volume'] > 0)
            ),
            'enter_long'] = 1
        return dataframe
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_bollinger_improvements.py -v`
Expected: PASS

- [ ] **Step 5: Run existing tests**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_strategies.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add ft_userdata/user_data/strategies/BollingerBounceV1.py tests/test_bollinger_improvements.py
git commit -m "feat(BollingerBounceV1): add volume capitulation filter on entry

Require volume >= 1.5x 20-period SMA on Bollinger bounce entries.
Mean reversion + volume exhaustion = higher probability setup.
Based on Lance Breitstein's 2x volume capitulation heuristic.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Time-of-Day / Session Performance Analysis

**Priority:** HIGH — discover hidden performance patterns by trading session

**Concept:** Add session-based performance breakdown to trade_analyzer.py. Crypto trades 24/7, so break into: Asian (00:00-08:00 UTC), European (08:00-16:00 UTC), US (16:00-00:00 UTC). Also add day-of-week analysis. Jeff Holden's discovery that his edge disappeared after 11:30am saved him $15-20K/year.

**Files:**
- Modify: `ft_userdata/trade_analyzer.py` (add session analysis functions)
- Create: `tests/test_trade_analyzer_sessions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_trade_analyzer_sessions.py
"""Tests for time-of-day and day-of-week performance analysis."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ANALYZER_PATH = Path(__file__).parent.parent / "ft_userdata" / "trade_analyzer.py"


def _load_analyzer():
    spec = importlib.util.spec_from_file_location("trade_analyzer", ANALYZER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("requests", MagicMock())
    sys.modules.setdefault("requests.auth", MagicMock())
    spec.loader.exec_module(mod)
    return mod


class TestSessionAnalysis:
    def test_classify_session_function_exists(self):
        mod = _load_analyzer()
        assert hasattr(mod, 'classify_session'), "classify_session function must exist"

    def test_classify_session_returns_correct_labels(self):
        mod = _load_analyzer()
        assert mod.classify_session(3) == "asian"    # 03:00 UTC
        assert mod.classify_session(10) == "european" # 10:00 UTC
        assert mod.classify_session(20) == "us"       # 20:00 UTC

    def test_analyze_by_session_function_exists(self):
        mod = _load_analyzer()
        assert hasattr(mod, 'analyze_by_session'), "analyze_by_session function must exist"

    def test_analyze_by_day_of_week_function_exists(self):
        mod = _load_analyzer()
        assert hasattr(mod, 'analyze_by_day_of_week'), "analyze_by_day_of_week function must exist"

    def test_analyze_by_session_with_empty_trades(self):
        mod = _load_analyzer()
        result = mod.analyze_by_session([])
        assert isinstance(result, dict)
        assert "asian" in result
        assert "european" in result
        assert "us" in result

    def test_analyze_by_day_of_week_with_empty_trades(self):
        mod = _load_analyzer()
        result = mod.analyze_by_day_of_week([])
        assert isinstance(result, dict)
        assert "Monday" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_trade_analyzer_sessions.py -v`
Expected: FAIL — functions don't exist

- [ ] **Step 3: Implement session analysis functions**

Add these functions to `ft_userdata/trade_analyzer.py` before the `analyze_strategy` function (around line 143):

```python
# ---------------------------------------------------------------------------
# Session & Time Analysis (SMB Capital insight: performance varies by session)
# ---------------------------------------------------------------------------

def classify_session(hour_utc: int) -> str:
    """Classify UTC hour into trading session."""
    if 0 <= hour_utc < 8:
        return "asian"
    elif 8 <= hour_utc < 16:
        return "european"
    else:
        return "us"


def _session_stats(trades: list[dict]) -> dict:
    """Calculate win rate, avg P/L, total P/L for a list of trades."""
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "avg_pnl": 0.0, "total_pnl": 0.0}
    wins = sum(1 for t in trades if t.get("profit_abs", t.get("profit_amount", 0)) > 0)
    pnls = [t.get("profit_abs", t.get("profit_amount", 0)) for t in trades]
    return {
        "trades": len(trades),
        "win_rate": round(wins / len(trades) * 100, 1),
        "avg_pnl": round(sum(pnls) / len(pnls), 4),
        "total_pnl": round(sum(pnls), 4),
    }


def analyze_by_session(closed_trades: list[dict]) -> dict:
    """Break performance down by Asian/European/US session based on entry time."""
    buckets = {"asian": [], "european": [], "us": []}
    for t in closed_trades:
        open_date = parse_date(t.get("open_date"))
        if open_date:
            session = classify_session(open_date.hour)
            buckets[session].append(t)
    return {session: _session_stats(trades) for session, trades in buckets.items()}


def analyze_by_day_of_week(closed_trades: list[dict]) -> dict:
    """Break performance down by day of week based on entry time."""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    buckets = {d: [] for d in days}
    for t in closed_trades:
        open_date = parse_date(t.get("open_date"))
        if open_date:
            day_name = days[open_date.weekday()]
            buckets[day_name].append(t)
    return {day: _session_stats(trades) for day, trades in buckets.items()}
```

- [ ] **Step 4: Wire session analysis into analyze_strategy output**

In the `analyze_strategy` function, after the patterns section (around line 202), add:

```python
    # --- Session & Time Analysis ---
    result["session_performance"] = analyze_by_session(closed)
    result["day_of_week_performance"] = analyze_by_day_of_week(closed)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_trade_analyzer_sessions.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ft_userdata/trade_analyzer.py tests/test_trade_analyzer_sessions.py
git commit -m "feat(trade_analyzer): add session and day-of-week performance breakdown

Break trade performance into Asian/European/US sessions and day-of-week.
Jeff Holden (SMB Capital) discovered his edge disappeared after 11:30am
using this type of analysis — saved $15-20K/year.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Confidence-Based Position Sizing for SupertrendStrategy

**Priority:** MEDIUM — size up on high-confluence setups, down on marginal ones

**Concept:** Implement `custom_stake_amount()` that scores setup quality. When multiple confluence signals fire (BTC trending + high ADX + volume spike + tight ATR), use 1.25x stake. When only minimum conditions are met, use 0.75x. Based on Lance Breitstein's A/B/C setup grading.

**Files:**
- Modify: `ft_userdata/user_data/strategies/SupertrendStrategy.py`
- Modify: `tests/test_supertrend_improvements.py` (add new test class)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_supertrend_improvements.py`:

```python
class TestConfidenceSizing:
    """Test confidence-based position sizing."""

    def test_custom_stake_amount_method_exists(self):
        source = STRATEGY_PATH.read_text()
        assert "custom_stake_amount" in source, "custom_stake_amount method must exist"

    def test_confidence_score_logic_present(self):
        source = STRATEGY_PATH.read_text()
        stake_section = source.split("custom_stake_amount")[1][:1500]
        assert "confidence" in stake_section.lower() or "score" in stake_section.lower(), \
            "custom_stake_amount must use a confidence/score system"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_supertrend_improvements.py::TestConfidenceSizing -v`
Expected: FAIL — custom_stake_amount doesn't exist

- [ ] **Step 3: Implement confidence-based sizing**

Add volume SMA to `populate_indicators` in SupertrendStrategy.py (after existing indicators):

```python
        # Volume ratio for confidence scoring
        dataframe['volume_sma_20'] = dataframe['volume'].rolling(window=20).mean()
        dataframe['volume_ratio'] = dataframe['volume'] / (dataframe['volume_sma_20'] + 1e-10)
```

Add the `custom_stake_amount` method after `custom_stoploss`:

```python
    def custom_stake_amount(self, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: float | None,
                            max_stake: float, entry_tag: str | None, side: str,
                            **kwargs) -> float:
        """
        Confidence-based position sizing (Lance Breitstein A/B/C grading).
        Score setup quality from confirming indicators, scale stake accordingly.
        """
        dataframe, _ = self.dp.get_analyzed_dataframe(kwargs.get('pair', ''), self.timeframe)
        if dataframe.empty:
            return proposed_stake

        last = dataframe.iloc[-1]
        score = 0

        # +1: Strong ADX trend (> 30 vs threshold of 25)
        if last.get('adx', 0) > 30:
            score += 1

        # +1: Volume spike (> 1.5x average)
        if last.get('volume_ratio', 0) > 1.5:
            score += 1

        # +1: All 3 supertrend signals strongly aligned (redundant with entry, but confirms strength)
        if (last.get('buy_m1', '') == 'up' and
            last.get('buy_m2', '') == 'up' and
            last.get('buy_m3', '') == 'up'):
            score += 1

        # +1: BTC RSI shows momentum (> 55, not just above 35 threshold)
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
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_supertrend_improvements.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite for regression**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/ -v`
Expected: All existing tests pass

- [ ] **Step 6: Commit**

```bash
git add ft_userdata/user_data/strategies/SupertrendStrategy.py tests/test_supertrend_improvements.py
git commit -m "feat(SupertrendStrategy): add confidence-based position sizing

Score setup quality (ADX strength, volume spike, BTC momentum, ST alignment).
High confidence (3+/4) = 1.25x stake, medium = 1.0x, low = 0.75x.
Based on Lance Breitstein's A/B/C setup grading (SMB Capital).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Bounce-Long Mode for BearCrashShortV1

**Priority:** MEDIUM — capture the high-probability recovery trade after bear regime ends

**Concept:** SMB's 5/5 track record on post-crash recovery bets. When BearCrashShortV1's regime gate flips from bear to bull, enter a long position on the first confirmed reversal. This is a separate entry signal within the same strategy, using `enter_long` alongside existing `enter_short`.

**Important:** BearCrashShortV1 currently has `can_short = True` but is short-only by design. Adding a bounce-long signal means it becomes a dual-direction strategy. The long entries should be rare and only fire on regime transitions.

**Files:**
- Modify: `ft_userdata/user_data/strategies/BearCrashShortV1.py`
- Create: `tests/test_bear_bounce.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bear_bounce.py
"""Tests for BearCrashShortV1 bounce-long mode."""
from pathlib import Path

STRATEGY_PATH = Path(__file__).parent.parent / "ft_userdata" / "user_data" / "strategies" / "BearCrashShortV1.py"


class TestBounceLongMode:
    def test_bounce_long_signal_exists(self):
        source = STRATEGY_PATH.read_text()
        assert "enter_long" in source, "Strategy must have enter_long signal for bounce mode"

    def test_bounce_requires_regime_flip(self):
        """Bounce long should only fire when bear regime was recently active then flipped."""
        source = STRATEGY_PATH.read_text()
        assert "regime_flip" in source or "bear_to_bull" in source, \
            "Bounce long must detect regime transition"

    def test_bounce_has_volume_confirmation(self):
        source = STRATEGY_PATH.read_text()
        # Find the enter_long section
        long_section = source[source.index("enter_long"):][:500]
        assert "volume" in long_section.lower(), "Bounce long must confirm with volume"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_bear_bounce.py -v`
Expected: FAIL — enter_long not in source

- [ ] **Step 3: Implement bounce-long mode**

In `BearCrashShortV1.py`, add regime flip detection to `populate_indicators` (after the existing btc_bear_confirmed calculation):

```python
        # Regime flip detection: bear was confirmed but just flipped to bullish
        dataframe['btc_was_bear'] = dataframe['btc_bear_confirmed'].shift(1).fillna(0)
        dataframe['btc_now_bull'] = (
            (dataframe['close_btc'] > dataframe['sma200_btc']) &
            (dataframe['rsi_btc'] > 45)
        ).astype(int)
        dataframe['bear_to_bull'] = (
            (dataframe['btc_was_bear'] == 1) &
            (dataframe['btc_now_bull'] == 1)
        ).astype(int)

        # Volume capitulation on bounce (2x average = high conviction)
        dataframe['volume_sma_20'] = dataframe['volume'].rolling(window=20).mean()
        dataframe['volume_ratio'] = dataframe['volume'] / (dataframe['volume_sma_20'] + 1e-10)
```

In `populate_entry_trend`, add the bounce-long signal AFTER the existing short entry block:

```python
        # === BOUNCE LONG: Post-bear recovery (SMB Capital 5/5 track record) ===
        # Only fires on regime transition from bear to bull
        dataframe.loc[
            (
                # Regime just flipped from bear to bull
                (dataframe['bear_to_bull'] == 1) &
                # Pair showing strength: RSI recovering
                (dataframe['rsi'] > 40) &
                (dataframe['rsi'] < 70) &
                # Plus DI taking over (bulls winning)
                (dataframe['plus_di'] > dataframe['minus_di']) &
                # Volume confirmation on the bounce
                (dataframe['volume_ratio'] >= 1.5) &
                # Volume sanity
                (dataframe['volume'] > 0)
            ),
            'enter_long'] = 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_bear_bounce.py -v`
Expected: PASS

- [ ] **Step 5: Update existing bear crash tests to allow enter_long**

The existing test `test_bear_crash_short.py` has a check that `enter_long` must NOT appear. This needs updating to allow the bounce-long signal. Read the test file and update the assertion to permit `enter_long` as part of the bounce mode while still requiring short-only as the primary mode.

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add ft_userdata/user_data/strategies/BearCrashShortV1.py tests/test_bear_bounce.py tests/test_bear_crash_short.py
git commit -m "feat(BearCrashShortV1): add bounce-long mode on bear-to-bull regime flip

When bear regime flips to bullish, enter long on confirmed reversal with
volume confirmation. SMB Capital has 5/5 track record on post-crash
recovery bets. Bounce entries are rare (regime transitions only).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: AI Trade Autopsy Automation

**Priority:** LOW — automated post-trade Claude analysis

**Concept:** Script that pulls closed trades from Freqtrade API, formats them into SMB's structured autopsy template, and outputs JSON ready for Claude analysis. Integrates with existing Telegram scheduled jobs.

**Files:**
- Create: `ft_userdata/ai_trade_autopsy.py`
- Create: `tests/test_ai_autopsy.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ai_autopsy.py
"""Tests for AI trade autopsy automation."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

AUTOPSY_PATH = Path(__file__).parent.parent / "ft_userdata" / "ai_trade_autopsy.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("ai_trade_autopsy", AUTOPSY_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("requests", MagicMock())
    sys.modules.setdefault("requests.auth", MagicMock())
    spec.loader.exec_module(mod)
    return mod


class TestAutopsyFormat:
    def test_module_exists(self):
        assert AUTOPSY_PATH.exists(), "ai_trade_autopsy.py must exist"

    def test_format_trade_autopsy_exists(self):
        mod = _load_module()
        assert hasattr(mod, 'format_trade_autopsy')

    def test_format_trade_autopsy_output(self):
        mod = _load_module()
        trade = {
            "pair": "ETH/USDT",
            "open_date": "2026-04-01 10:00:00",
            "close_date": "2026-04-01 14:00:00",
            "open_rate": 1800.0,
            "close_rate": 1850.0,
            "profit_abs": 2.5,
            "profit_ratio": 0.028,
            "exit_reason": "trailing_stop_loss",
            "enter_tag": "enter_long",
            "stake_amount": 88.0,
        }
        strategy_rules = {
            "entry": "3x Supertrend up + BTC bullish + ADX > 25",
            "exit": "3x Supertrend down or volatility spike",
            "stoploss": "-5%",
            "trailing": "N-bar lowest low of 3 candles",
        }
        result = mod.format_trade_autopsy(trade, "SupertrendStrategy", strategy_rules)
        assert "ETH/USDT" in result
        assert "SupertrendStrategy" in result
        assert "trailing_stop_loss" in result

    def test_generate_autopsy_prompt_exists(self):
        mod = _load_module()
        assert hasattr(mod, 'generate_autopsy_prompt')

    def test_generate_autopsy_prompt_output(self):
        mod = _load_module()
        autopsies = ["Trade 1: ETH/USDT won", "Trade 2: BTC/USDT lost"]
        prompt = mod.generate_autopsy_prompt(autopsies)
        assert "most important" in prompt.lower()
        assert "pattern" in prompt.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_ai_autopsy.py -v`
Expected: FAIL — file doesn't exist

- [ ] **Step 3: Implement the autopsy script**

```python
# ft_userdata/ai_trade_autopsy.py
#!/usr/bin/env python3
"""
AI Trade Autopsy — Structured Post-Trade Analysis for Claude
=============================================================

Pulls closed trades from Freqtrade API, formats into SMB Capital's
autopsy template, outputs structured text for Claude analysis.

Usage:
    python ai_trade_autopsy.py                    # All bots, last 24h
    python ai_trade_autopsy.py --bot SupertrendStrategy
    python ai_trade_autopsy.py --hours 48         # Last 48 hours
    python ai_trade_autopsy.py --prompt           # Generate Claude super-prompt
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

# Strategy rules reference for autopsy context
STRATEGY_RULES = {
    "SupertrendStrategy": {
        "entry": "3x Supertrend uptrend + BTC above SMA200 & SMA50 + RSI > 35 + ADX > 25 + not volatile",
        "exit": "3x Supertrend downtrend OR ATR > 2.5x rolling mean (volatility spike)",
        "stoploss": "-5% (N-bar trailing: lowest low of last 3 candles)",
        "trailing": "Structure-based: lowest low of 3 candles, adapts to volatility",
    },
    "MasterTraderV1": {
        "entry": "Proprietary multi-indicator confluence",
        "exit": "Signal-based + 48h force exit",
        "stoploss": "-5% with 1% trail @ 2% offset",
        "trailing": "Fixed percentage: 1% trail activated at 2% profit",
    },
    "BollingerBounceV1": {
        "entry": "BB lower band bounce + RSI 30-70 + ADX > 25 + volume >= 1.5x SMA + BTC > SMA200",
        "exit": "Signal-based",
        "stoploss": "-5% with 2% trail @ 3% offset",
        "trailing": "Fixed percentage: 2% trail activated at 3% profit",
    },
    "BearCrashShortV1": {
        "entry": "SHORT: Failed rally in confirmed bear regime (4/6 rolling BTC bear gate). LONG: Bounce on bear-to-bull regime flip",
        "exit": "RSI < 25, DI crossover (2-bar confirm), BTC flips bullish, volatility spike, 48h hard exit",
        "stoploss": "-5% with 2% trail @ 3% offset",
        "trailing": "Fixed percentage: 2% trail activated at 3% profit",
    },
}


def format_trade_autopsy(trade: dict, strategy: str, strategy_rules: dict) -> str:
    """Format a single trade into SMB autopsy template."""
    pair = trade.get("pair", "Unknown")
    open_date = trade.get("open_date", "Unknown")
    close_date = trade.get("close_date", "Unknown")
    open_rate = trade.get("open_rate", 0)
    close_rate = trade.get("close_rate", 0)
    profit_abs = trade.get("profit_abs", trade.get("profit_amount", 0))
    profit_pct = trade.get("profit_ratio", trade.get("profit_pct", 0))
    if isinstance(profit_pct, (int, float)) and abs(profit_pct) < 1:
        profit_pct = profit_pct * 100
    exit_reason = trade.get("exit_reason", trade.get("sell_reason", "Unknown"))
    enter_tag = trade.get("enter_tag", "Unknown")
    stake = trade.get("stake_amount", 0)
    duration = trade.get("trade_duration", "Unknown")

    return f"""## Trade Autopsy: {pair} ({strategy})
- **Entry**: {open_date} @ ${open_rate:.4f} (tag: {enter_tag})
- **Exit**: {close_date} @ ${close_rate:.4f} (reason: {exit_reason})
- **Duration**: {duration} minutes
- **Stake**: ${stake:.2f}
- **P/L**: ${profit_abs:.4f} ({profit_pct:.2f}%)

### Strategy Rules
- Entry: {strategy_rules.get('entry', 'N/A')}
- Exit: {strategy_rules.get('exit', 'N/A')}
- Stoploss: {strategy_rules.get('stoploss', 'N/A')}
- Trailing: {strategy_rules.get('trailing', 'N/A')}

### Questions
1. Did the entry meet the strategy's rules based on the exit reason?
2. Was the exit optimal or premature/late?
3. What pattern does this trade show (trend capture, whipsaw, stoploss hit, etc.)?
4. What could be improved in this strategy's logic based on this trade?
"""


def generate_autopsy_prompt(autopsies: list[str]) -> str:
    """Generate a Claude super-prompt from multiple autopsy reports."""
    trades_text = "\n---\n".join(autopsies)
    return f"""Analyze these {len(autopsies)} trade autopsy reports from my automated crypto trading bots.

{trades_text}

---

Based on ALL trades above (not just one), help me understand:
1. What patterns do you see across these trades?
2. Which strategy is performing best/worst and why?
3. Are there any exit reasons that are consistently suboptimal?
4. What is the ONE most important thing I should focus on improving?
5. Are there any time-of-day or pair-specific patterns?

Be specific and reference individual trades when making points."""


def _load_bots_config() -> dict:
    config_path = Path(__file__).parent / "bots_config.json"
    try:
        with open(config_path) as f:
            data = json.load(f)
        return {
            name: info for name, info in data["bots"].items()
            if info.get("active", True)
        }
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return {}


def fetch_recent_trades(port: int, hours: int = 24) -> list[dict]:
    """Fetch closed trades from the last N hours."""
    try:
        resp = requests.get(
            f"http://127.0.0.1:{port}/api/v1/trades?limit=500",
            auth=HTTPBasicAuth("freqtrader", "freqtrader"),
            timeout=10,
        )
        resp.raise_for_status()
        trades = resp.json().get("trades", [])
    except Exception:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent = []
    for t in trades:
        close_str = t.get("close_date")
        if close_str and not t.get("is_open"):
            try:
                close_dt = datetime.fromisoformat(close_str.replace("Z", "+00:00"))
                if close_dt >= cutoff:
                    recent.append(t)
            except (ValueError, TypeError):
                continue
    return recent


def main():
    parser = argparse.ArgumentParser(description="AI Trade Autopsy Generator")
    parser.add_argument("--bot", help="Analyze specific bot only")
    parser.add_argument("--hours", type=int, default=24, help="Look back N hours (default 24)")
    parser.add_argument("--prompt", action="store_true", help="Output Claude super-prompt")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    bots = _load_bots_config()
    if args.bot:
        bots = {k: v for k, v in bots.items() if k == args.bot}

    all_autopsies = []
    for name, info in bots.items():
        port = info.get("port")
        if not port:
            continue
        trades = fetch_recent_trades(port, args.hours)
        rules = STRATEGY_RULES.get(name, {"entry": "Unknown", "exit": "Unknown", "stoploss": "Unknown", "trailing": "Unknown"})
        for t in trades:
            all_autopsies.append(format_trade_autopsy(t, name, rules))

    if not all_autopsies:
        print(f"No closed trades in the last {args.hours} hours.", file=sys.stderr)
        sys.exit(0)

    if args.prompt:
        print(generate_autopsy_prompt(all_autopsies))
    elif args.json:
        print(json.dumps({"autopsies": all_autopsies, "count": len(all_autopsies)}, indent=2))
    else:
        for a in all_autopsies:
            print(a)
            print("---")
        print(f"\nTotal: {len(all_autopsies)} trades analyzed")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_ai_autopsy.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ft_userdata/ai_trade_autopsy.py tests/test_ai_autopsy.py
git commit -m "feat: add AI trade autopsy script for structured post-trade analysis

Pulls closed trades from Freqtrade API, formats into SMB Capital's
autopsy template with strategy rules context, generates Claude
super-prompt for pattern detection across all trades.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Theme-Aware Pairlist Helper

**Priority:** LOW — detect which crypto sector is "in play"

**Concept:** Add a helper to market_intelligence.py that classifies pairs by sector (AI tokens, L2, DeFi, meme) and tracks which sectors have the most volume/momentum. Lance's principle: "find the broken slot machine" — trade what's moving. This is a helper module; pairlist integration comes later.

**Files:**
- Modify: `ft_userdata/user_data/strategies/market_intelligence.py`
- Create: `tests/test_theme_detection.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_theme_detection.py
"""Tests for crypto sector/theme detection helper."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

MI_PATH = Path(__file__).parent.parent / "ft_userdata" / "user_data" / "strategies" / "market_intelligence.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("market_intelligence", MI_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("requests", MagicMock())
    sys.modules.setdefault("requests.auth", MagicMock())
    spec.loader.exec_module(mod)
    return mod


class TestThemeDetection:
    def test_sector_map_exists(self):
        mod = _load_module()
        assert hasattr(mod, 'SECTOR_MAP'), "SECTOR_MAP constant must exist"

    def test_sector_map_has_categories(self):
        mod = _load_module()
        assert "ai" in mod.SECTOR_MAP
        assert "l2" in mod.SECTOR_MAP
        assert "defi" in mod.SECTOR_MAP

    def test_classify_pair_sector(self):
        mod = _load_module()
        assert hasattr(mod, 'classify_pair_sector')
        assert mod.classify_pair_sector("FET/USDT") == "ai"
        assert mod.classify_pair_sector("UNKNOWN/USDT") == "other"

    def test_score_sector_momentum(self):
        mod = _load_module()
        assert hasattr(mod, 'score_sector_momentum')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_theme_detection.py -v`
Expected: FAIL — SECTOR_MAP doesn't exist

- [ ] **Step 3: Implement sector classification**

Add to `ft_userdata/user_data/strategies/market_intelligence.py` at the bottom:

```python
# ---------------------------------------------------------------------------
# Sector / Theme Detection (Lance Breitstein: "find the broken slot machine")
# ---------------------------------------------------------------------------

SECTOR_MAP = {
    "ai": [
        "FET", "RENDER", "TAO", "OCEAN", "AGIX", "NMR", "ALI",
        "AKT", "RNDR", "GRT", "NEAR",
    ],
    "l2": [
        "ARB", "OP", "MATIC", "MANTA", "STRK", "ZK", "METIS",
        "BASE", "SCROLL", "BLAST", "IMX",
    ],
    "defi": [
        "UNI", "AAVE", "MKR", "COMP", "CRV", "SUSHI", "SNX",
        "LDO", "PENDLE", "GMX", "DYDX", "1INCH",
    ],
    "meme": [
        "DOGE", "SHIB", "PEPE", "BONK", "FLOKI", "WIF", "MEME",
        "TURBO", "BRETT", "NEIRO",
    ],
    "infra": [
        "LINK", "DOT", "ATOM", "AVAX", "SOL", "ADA", "TIA",
        "SEI", "SUI", "APT", "INJ",
    ],
}

# Reverse lookup: token -> sector
_TOKEN_TO_SECTOR = {}
for sector, tokens in SECTOR_MAP.items():
    for token in tokens:
        _TOKEN_TO_SECTOR[token] = sector


def classify_pair_sector(pair: str) -> str:
    """Classify a trading pair into its crypto sector."""
    base = pair.split("/")[0].split(":")[0].upper()
    return _TOKEN_TO_SECTOR.get(base, "other")


def score_sector_momentum(pair_volumes: dict[str, float]) -> dict[str, dict]:
    """
    Given a dict of {pair: 24h_volume}, score each sector's momentum.
    Returns {sector: {pairs: int, total_volume: float, avg_volume: float}}.
    """
    sector_data: dict[str, list[float]] = {s: [] for s in SECTOR_MAP}
    sector_data["other"] = []

    for pair, volume in pair_volumes.items():
        sector = classify_pair_sector(pair)
        sector_data[sector].append(volume)

    return {
        sector: {
            "pairs": len(volumes),
            "total_volume": round(sum(volumes), 2),
            "avg_volume": round(sum(volumes) / len(volumes), 2) if volumes else 0,
        }
        for sector, volumes in sector_data.items()
    }
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_theme_detection.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add ft_userdata/user_data/strategies/market_intelligence.py tests/test_theme_detection.py
git commit -m "feat(market_intelligence): add crypto sector classification and momentum scoring

Classify pairs into sectors (AI, L2, DeFi, meme, infra) and score
sector momentum by volume. Foundation for theme-aware pairlist rotation.
Based on Lance Breitstein's 'find the broken slot machine' principle.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Execution Order

Tasks are independent and can be parallelized, but recommended order:

1. **Task 1** (N-bar trailing) — highest impact, fixes known R:R problem
2. **Task 2** (volume capitulation) — simple, high-value filter
3. **Task 3** (session analysis) — quick win, immediate insight
4. **Task 4** (confidence sizing) — builds on Task 1's indicators
5. **Task 5** (bounce long) — conceptually clean but needs careful testing
6. **Task 6** (AI autopsy) — standalone script, no strategy changes
7. **Task 7** (theme detection) — foundation for future pairlist work

Tasks 1+4 share a file (SupertrendStrategy.py) so should run sequentially.
Tasks 2, 3, 5, 6, 7 are fully independent and can run in parallel.
