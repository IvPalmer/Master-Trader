# BearCrashShortV1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a short-only futures bot that profits during bear regimes when long bots are idle.

**Architecture:** Standalone Freqtrade strategy (`can_short=True`) gated by persistent BTC bear regime detection. Uses existing `market_intelligence.py` for Fear & Greed and PositionTracker. File-persisted kill switch for short-specific circuit breaker. Integrates into existing Docker/Prometheus/Grafana stack.

**Tech Stack:** Freqtrade 2026.2, Python, Docker Compose, Prometheus, Grafana, TA-Lib

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Create | `ft_userdata/user_data/strategies/BearCrashShortV1.py` | Short-only strategy |
| Create | `ft_userdata/user_data/configs/BearCrashShortV1.json` | Live config (futures, isolated, $22 stake) |
| Create | `ft_userdata/user_data/configs/backtest-BearCrashShortV1.json` | Backtest config (static pairlist) |
| Modify | `ft_userdata/bots_config.json` | Register new bot |
| Modify | `ft_userdata/docker-compose.yml` | Add service on port 8093 |
| Modify | `ft_userdata/metrics_exporter.py` | Add service name mapping |
| Modify | `tests/test_docker_compose.py` | Add bearcrashshortv1 to expected services |
| Modify | `tests/test_infrastructure.py` | Add to expected services list |
| Create | `tests/test_bear_crash_short.py` | Strategy-specific unit tests |

---

### Task 1: Strategy File — BearCrashShortV1.py

**Files:**
- Create: `ft_userdata/user_data/strategies/BearCrashShortV1.py`
- Create: `tests/test_bear_crash_short.py`

- [ ] **Step 1: Write the strategy file**

```python
"""
BearCrashShortV1 - Bear Regime Short-Only Strategy
====================================================

SHORT-ONLY. Zero long entries. Activates exclusively during confirmed bear regimes.

Entry pattern: "Failed Rally Short" — trend-following shorts on dead cat bounces
- BTC must be in confirmed bear regime (below SMA200, ADX>25, RSI<50) for 3+ candles
- Pair: -DI > +DI, ADX > 30, RSI 45-65 (bear "overbought"), MACD bearish
- Anti-squeeze: skip if RSI < 25, skip if Fear & Greed < 10

Exit: RSI < 25, +DI crosses -DI, BTC flips bullish, volatility spike, or time-based
Risk: -5% stoploss on exchange, 2% trail at 3%, 48h hard exit, $22 stake, 2x leverage
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from freqtrade.strategy import IStrategy, informative
from pandas import DataFrame
import talib.abstract as ta

from market_intelligence import FearGreedIndex, PositionTracker, MAX_BOTS_PER_PAIR

logger = logging.getLogger(__name__)

KILL_SWITCH_FILE = Path("/freqtrade/user_data/kill_switch_BearCrashShortV1.json")
DAILY_LOSS_LIMIT = 0.03  # 3% of wallet
CONSECUTIVE_LOSS_LIMIT = 3


class BearCrashShortV1(IStrategy):
    INTERFACE_VERSION = 3

    can_short = True
    timeframe = "1h"

    # Tighter ROI for shorts — crypto crashes are fast, take profits early
    minimal_roi = {
        "0": 0.08,     # 8% — grab big moves immediately
        "720": 0.05,   # 5% after 12h
        "1440": 0.03,  # 3% after 24h
        "2160": 0.01,  # 1% after 36h
        "2880": 0.0,   # Break-even at 48h — hard exit
    }

    stoploss = -0.05  # -5% hard stop (tighter than longs due to squeeze risk)

    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    startup_candle_count = 200  # BTC SMA200

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 3},  # 3h cooldown between shorts
            {"method": "StoplossGuard", "lookback_period_candles": 48,
             "trade_limit": 2, "stop_duration_candles": 24, "only_per_pair": True},
            {"method": "MaxDrawdown", "lookback_period_candles": 48,
             "max_allowed_drawdown": 0.15, "stop_duration_candles": 24, "trade_limit": 1},
        ]

    # ── BTC informative pair ────────────────────────────────────────

    @informative("1h", "BTC/{stake}")
    def populate_indicators_btc_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["sma200"] = ta.SMA(dataframe["close"], timeperiod=200)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["plus_di"] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe["minus_di"] = ta.MINUS_DI(dataframe, timeperiod=14)
        return dataframe

    # ── Indicators ──────────────────────────────────────────────────

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # DMI / ADX
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["plus_di"] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe["minus_di"] = ta.MINUS_DI(dataframe, timeperiod=14)

        # RSI
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # MACD
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]

        # SMA 200 for pair-level trend
        dataframe["sma200"] = ta.SMA(dataframe["close"], timeperiod=200)

        # ATR for volatility spike exits
        dataframe["atr_14"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_sma_50"] = dataframe["atr_14"].rolling(50).mean()

        # ── BTC Bear Regime Detection (3-candle persistence) ────────
        btc_bear_single = (
            (dataframe["btc_usdt_close_1h"] < dataframe["btc_usdt_sma200_1h"])
            & (dataframe["btc_usdt_adx_1h"] > 25)
            & (dataframe["btc_usdt_rsi_1h"] < 50)
        ).astype(int)

        # Require 3 consecutive bear candles
        dataframe["btc_bear_confirmed"] = (
            (btc_bear_single == 1)
            & (btc_bear_single.shift(1) == 1)
            & (btc_bear_single.shift(2) == 1)
        ).astype(int)

        return dataframe

    # ── Kill Switch ─────────────────────────────────────────────────

    def _read_kill_switch(self) -> dict:
        try:
            if KILL_SWITCH_FILE.exists():
                return json.loads(KILL_SWITCH_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
        return {
            "daily_loss": 0.0,
            "daily_loss_date": datetime.now().strftime("%Y-%m-%d"),
            "consecutive_losses": 0,
            "killed": False,
        }

    def _write_kill_switch(self, data: dict):
        try:
            KILL_SWITCH_FILE.parent.mkdir(parents=True, exist_ok=True)
            KILL_SWITCH_FILE.write_text(json.dumps(data, indent=2))
        except OSError as e:
            logger.warning("Kill switch write failed: %s", e)

    def _is_killed(self) -> bool:
        ks = self._read_kill_switch()
        today = datetime.now().strftime("%Y-%m-%d")
        # Reset daily counters on new day
        if ks.get("daily_loss_date") != today:
            ks["daily_loss"] = 0.0
            ks["daily_loss_date"] = today
            ks["killed"] = False
            ks["consecutive_losses"] = 0
            self._write_kill_switch(ks)
            return False
        return ks.get("killed", False)

    def _record_trade_result(self, profit_ratio: float):
        ks = self._read_kill_switch()
        today = datetime.now().strftime("%Y-%m-%d")
        if ks.get("daily_loss_date") != today:
            ks = {"daily_loss": 0.0, "daily_loss_date": today,
                  "consecutive_losses": 0, "killed": False}

        if profit_ratio < 0:
            ks["daily_loss"] = ks.get("daily_loss", 0.0) + abs(profit_ratio)
            ks["consecutive_losses"] = ks.get("consecutive_losses", 0) + 1
        else:
            ks["consecutive_losses"] = 0

        # Check kill conditions
        if ks["daily_loss"] >= DAILY_LOSS_LIMIT:
            ks["killed"] = True
            logger.warning("KILL SWITCH: Daily loss %.1f%% >= %.1f%% limit",
                          ks["daily_loss"] * 100, DAILY_LOSS_LIMIT * 100)
        if ks["consecutive_losses"] >= CONSECUTIVE_LOSS_LIMIT:
            ks["killed"] = True
            logger.warning("KILL SWITCH: %d consecutive losses", ks["consecutive_losses"])

        self._write_kill_switch(ks)

    # ── Entry Gate ──────────────────────────────────────────────────

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag: str | None, side: str, **kwargs) -> bool:
        # Kill switch check
        if self._is_killed():
            logger.info("BLOCKED %s: Kill switch active", pair)
            return False

        bot_name = self.config.get("bot_name", "BearCrashShort")

        # Cross-bot position check
        other_bots = PositionTracker.count_bots_holding(pair, exclude_bot=bot_name)
        if other_bots >= MAX_BOTS_PER_PAIR:
            logger.info("BLOCKED %s: %d other bots already hold this pair", pair, other_bots)
            return False

        # Anti-squeeze: don't short during extreme fear (crowded short side)
        if FearGreedIndex.is_extreme_fear():
            logger.info("BLOCKED %s: Fear & Greed extreme fear (%d) — squeeze risk",
                        pair, FearGreedIndex.get()["value"])
            return False

        PositionTracker.register(bot_name, pair, amount * rate)
        return True

    def confirm_trade_exit(self, pair: str, trade, order_type: str, amount: float,
                           rate: float, time_in_force: str, exit_reason: str,
                           current_time: datetime, **kwargs) -> bool:
        bot_name = self.config.get("bot_name", "BearCrashShort")
        PositionTracker.unregister(bot_name, pair)

        # Record result for kill switch
        if trade.close_profit is not None:
            self._record_trade_result(trade.close_profit)

        return True

    # ── Entry Signal ────────────────────────────────────────────────

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # SHORT ONLY — no long entries ever
        dataframe.loc[
            (
                # ── BTC REGIME GATE (persistent bear) ──
                (dataframe["btc_bear_confirmed"] == 1)

                # ── PAIR-LEVEL SIGNALS ──
                & (dataframe["minus_di"] > dataframe["plus_di"])  # Bears dominating
                & (dataframe["adx"] > 30)                         # Strong trend
                & (dataframe["rsi"] > 45) & (dataframe["rsi"] < 65)  # Bear "overbought"
                & (dataframe["close"] < dataframe["sma200"])      # Below SMA200
                & (dataframe["macd"] < dataframe["macdsignal"])   # MACD bearish

                # ── ANTI-SQUEEZE FILTERS ──
                & (dataframe["rsi"] > 25)                         # Not oversold (squeeze risk)
                & (dataframe["btc_usdt_rsi_1h"] > 20)            # BTC not at floor

                # ── VOLUME ──
                & (dataframe["volume"] > 0)
            ),
            "enter_short",
        ] = 1

        return dataframe

    # ── Exit Signal ─────────────────────────────────────────────────

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Bear regime ending
                (dataframe["btc_usdt_close_1h"] > dataframe["btc_usdt_sma200_1h"])
                # OR bulls taking over pair
                | (dataframe["plus_di"] > dataframe["minus_di"])
                # OR extremely oversold (bounce imminent)
                | (dataframe["rsi"] < 25)
                # OR volatility spike (exit on chaos)
                | (dataframe["atr_14"] > 2.5 * dataframe["atr_sma_50"])
            )
            & (dataframe["volume"] > 0),
            "exit_short",
        ] = 1

        return dataframe

    # ── Time-Based Exit ─────────────────────────────────────────────

    def custom_exit(self, pair: str, trade, current_time, current_rate,
                    current_profit, **kwargs):
        if not trade.is_short:
            return None

        hours = (current_time - trade.open_date_utc).total_seconds() / 3600

        # Hard exit at 48h regardless
        if hours >= 48:
            return "time_exit_48h"

        # Take 2%+ profit after 24h
        if hours >= 24 and current_profit > 0.02:
            return "time_profit_24h"

        # Break-even exit after 36h
        if hours >= 36 and current_profit > 0:
            return "time_breakeven_36h"

        return None

    # ── Leverage ────────────────────────────────────────────────────

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str | None,
                 side: str, **kwargs) -> float:
        return 2.0  # Fixed 2x for shorts
```

- [ ] **Step 2: Write strategy unit tests**

Create `tests/test_bear_crash_short.py`:

```python
"""
BearCrashShortV1 strategy validation tests.

Run with: pytest tests/test_bear_crash_short.py -v
"""

import ast
import json
import re
from pathlib import Path

import pytest

FT_DIR = Path(__file__).parent.parent / "ft_userdata"
STRATEGY_FILE = FT_DIR / "user_data" / "strategies" / "BearCrashShortV1.py"
CONFIG_FILE = FT_DIR / "user_data" / "configs" / "BearCrashShortV1.json"
BACKTEST_CONFIG = FT_DIR / "user_data" / "configs" / "backtest-BearCrashShortV1.json"


class TestStrategyFile:
    """Validate strategy Python file structure."""

    @pytest.fixture
    def source(self):
        return STRATEGY_FILE.read_text()

    @pytest.fixture
    def tree(self, source):
        return ast.parse(source)

    def test_file_exists(self):
        assert STRATEGY_FILE.exists(), "BearCrashShortV1.py not found"

    def test_parses_as_valid_python(self, tree):
        assert tree is not None

    def test_class_exists(self, tree):
        classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        assert "BearCrashShortV1" in classes

    def test_interface_version_3(self, source):
        assert "INTERFACE_VERSION = 3" in source

    def test_can_short_enabled(self, source):
        assert "can_short = True" in source

    def test_timeframe_declared(self, source):
        assert re.search(r'timeframe\s*=\s*["\']1h["\']', source)

    def test_has_required_methods(self, tree):
        methods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                methods.add(node.name)
        required = {
            "populate_indicators",
            "populate_entry_trend",
            "populate_exit_trend",
            "confirm_trade_entry",
            "confirm_trade_exit",
            "custom_exit",
            "leverage",
        }
        missing = required - methods
        assert not missing, f"Missing methods: {missing}"

    def test_no_enter_long_signal(self, source):
        """Short-only strategy must NEVER set enter_long."""
        assert "enter_long" not in source, "Short-only strategy must not have enter_long signals"

    def test_stoploss_not_worse_than_minus_5_pct(self, source):
        match = re.search(r'stoploss\s*=\s*(-[\d.]+)', source)
        assert match, "stoploss not found"
        sl = float(match.group(1))
        assert sl >= -0.05, f"Stoploss {sl} is worse than -5% — too risky for shorts"

    def test_no_stoploss_negative_099_bug(self, source):
        """Must not contain the -0.99 stoploss bug."""
        assert "-0.99" not in source, "Contains -0.99 stoploss bug pattern"

    def test_kill_switch_file_persisted(self, source):
        assert "kill_switch" in source.lower(), "Kill switch not implemented"
        assert "KILL_SWITCH_FILE" in source, "Kill switch file path not defined"

    def test_leverage_returns_2(self, source):
        assert "return 2.0" in source, "Leverage should return 2.0"

    def test_anti_squeeze_filters(self, source):
        """Must have anti-squeeze protection."""
        assert "rsi" in source.lower() and "25" in source, "Missing RSI floor anti-squeeze"
        assert "is_extreme_fear" in source, "Missing Fear & Greed anti-squeeze filter"

    def test_time_exit_48h(self, source):
        assert "48" in source and "time_exit" in source, "Missing 48h time exit"


class TestLiveConfig:
    """Validate live trading config."""

    @pytest.fixture
    def config(self):
        return json.loads(CONFIG_FILE.read_text())

    def test_file_exists(self):
        assert CONFIG_FILE.exists()

    def test_futures_mode(self, config):
        assert config["trading_mode"] == "futures"

    def test_isolated_margin(self, config):
        assert config["margin_mode"] == "isolated"

    def test_dry_run(self, config):
        assert config["dry_run"] is True, "Must start in dry-run mode"

    def test_wallet_size(self, config):
        assert config["dry_run_wallet"] == 22, "Wallet should be $22 (25% of $88)"

    def test_max_open_trades(self, config):
        assert config["max_open_trades"] == 2

    def test_stoploss_on_exchange(self, config):
        assert config["order_types"]["stoploss_on_exchange"] is True

    def test_bot_name_set(self, config):
        assert config["bot_name"] == "BearCrashShort"

    def test_no_api_keys(self, config):
        assert config["exchange"]["key"] == ""
        assert config["exchange"]["secret"] == ""


class TestBacktestConfig:
    """Validate backtest config."""

    @pytest.fixture
    def config(self):
        return json.loads(BACKTEST_CONFIG.read_text())

    def test_file_exists(self):
        assert BACKTEST_CONFIG.exists()

    def test_static_pairlist(self, config):
        methods = [p["method"] for p in config["pairlists"]]
        assert "StaticPairList" in methods, "Backtest config must use StaticPairList"

    def test_futures_pairs_format(self, config):
        """Futures pairs must have :USDT suffix."""
        pairs = config["exchange"]["pair_whitelist"]
        for pair in pairs:
            assert pair.endswith(":USDT"), f"Futures pair {pair} missing :USDT suffix"


class TestBotsConfig:
    """Validate bots_config.json registration."""

    @pytest.fixture
    def config(self):
        return json.loads((FT_DIR / "bots_config.json").read_text())

    def test_bot_registered(self, config):
        assert "BearCrashShortV1" in config["bots"]

    def test_port_8093(self, config):
        assert config["bots"]["BearCrashShortV1"]["port"] == 8093

    def test_marked_active(self, config):
        assert config["bots"]["BearCrashShortV1"]["active"] is True

    def test_futures_mode(self, config):
        assert config["bots"]["BearCrashShortV1"]["trading_mode"] == "futures"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_bear_crash_short.py -v`
Expected: Multiple FAIL (files don't exist yet)

- [ ] **Step 4: Create the strategy file with the code from Step 1**

Write to: `ft_userdata/user_data/strategies/BearCrashShortV1.py`

- [ ] **Step 5: Run strategy tests to verify they pass (before config tests)**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_bear_crash_short.py::TestStrategyFile -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add ft_userdata/user_data/strategies/BearCrashShortV1.py tests/test_bear_crash_short.py
git commit -m "feat: add BearCrashShortV1 strategy — short-only bear regime bot"
```

---

### Task 2: Config Files

**Files:**
- Create: `ft_userdata/user_data/configs/BearCrashShortV1.json`
- Create: `ft_userdata/user_data/configs/backtest-BearCrashShortV1.json`
- Modify: `ft_userdata/bots_config.json`

- [ ] **Step 1: Create live config**

Base on `FuturesSniperV1.json` (proven futures template) with these changes:
- `dry_run_wallet`: 22 (25% of $88)
- `max_open_trades`: 2
- `bot_name`: "BearCrashShort"
- `db_url`: "sqlite:////freqtrade/user_data/tradesv3.dryrun.BearCrashShortV1.sqlite"
- `CORS_origins`: includes localhost:8093
- `jwt_secret_key`: "bear-crash-short-dev-key-change-for-prod"
- Add stablecoin blacklist entries: `USD1/USDT:USDT`, `XUSD/USDT:USDT`, `U/USDT:USDT`, `EUR/USDT:USDT`
- `webhook.enabled`: true (match other active bots)

- [ ] **Step 2: Create backtest config**

Based on `backtest-SupertrendStrategy.json` template:
- `trading_mode`: "futures"
- `margin_mode`: "isolated"
- `liquidation_buffer`: 0.05
- `dry_run_wallet`: 1000
- `max_open_trades`: 5
- Static pairlist with top-20 futures pairs (`:USDT` suffix):
  `BTC/USDT:USDT, ETH/USDT:USDT, SOL/USDT:USDT, XRP/USDT:USDT, BNB/USDT:USDT, DOGE/USDT:USDT, ADA/USDT:USDT, AVAX/USDT:USDT, LINK/USDT:USDT, NEAR/USDT:USDT, SUI/USDT:USDT, TRX/USDT:USDT, DOT/USDT:USDT, UNI/USDT:USDT, FIL/USDT:USDT, APT/USDT:USDT, ATOM/USDT:USDT, FET/USDT:USDT, LTC/USDT:USDT, RENDER/USDT:USDT`

- [ ] **Step 3: Register in bots_config.json**

Add to `bots` object:
```json
"BearCrashShortV1": {"port": 8093, "timeframe": "1h", "type": "bear-short", "active": true, "trading_mode": "futures"}
```

- [ ] **Step 4: Run config tests**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_bear_crash_short.py::TestLiveConfig tests/test_bear_crash_short.py::TestBacktestConfig tests/test_bear_crash_short.py::TestBotsConfig -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add ft_userdata/user_data/configs/BearCrashShortV1.json ft_userdata/user_data/configs/backtest-BearCrashShortV1.json ft_userdata/bots_config.json
git commit -m "feat: add BearCrashShortV1 configs and register in bots_config"
```

---

### Task 3: Docker Compose Integration

**Files:**
- Modify: `ft_userdata/docker-compose.yml`

- [ ] **Step 1: Add bearcrashshortv1 service**

Add after the `gaussianchannelv1` service block, before the grafana-bridge block. Use the same pattern as other active bots:

```yaml
  # ── Bear Crash Short (futures, short-only during bear regimes) ────
  bearcrashshortv1:
    image: freqtradeorg/freqtrade:stable
    restart: always
    container_name: ft-bear-crash-short
    extra_hosts: *binance-hosts
    volumes:
      - "./user_data:/freqtrade/user_data"
    ports:
      - "127.0.0.1:8093:8080"
    healthcheck: *bot-healthcheck
    deploy:
      resources:
        limits:
          memory: 768M
    entrypoint: ["/bin/sh", "-c", "sleep 45 && exec freqtrade trade --logfile /freqtrade/user_data/logs/BearCrashShortV1.log --config /freqtrade/user_data/configs/BearCrashShortV1.json --strategy BearCrashShortV1"]
```

Also add `bearcrashshortv1` to the `grafana-bridge` `depends_on` list.

- [ ] **Step 2: Run docker compose validation**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader/ft_userdata && docker compose config --quiet`
Expected: Exit code 0, no errors

- [ ] **Step 3: Commit**

```bash
git add ft_userdata/docker-compose.yml
git commit -m "feat: add BearCrashShortV1 to docker-compose (port 8093)"
```

---

### Task 4: Metrics Exporter Integration

**Files:**
- Modify: `ft_userdata/metrics_exporter.py:40-49` (service_map dict)
- Modify: `ft_userdata/metrics_exporter.py:68` (INITIAL_CAPITAL)

- [ ] **Step 1: Add service name mapping**

Add to `service_map` dict in `_load_bots_config()`:
```python
"BearCrashShortV1": "bearcrashshortv1",
```

- [ ] **Step 2: Update initial capital**

Update `INITIAL_CAPITAL` from 528.0 to 550.0 ($528 existing + $22 new short bot).
This affects the circuit breaker threshold calculation.

- [ ] **Step 3: Commit**

```bash
git add ft_userdata/metrics_exporter.py
git commit -m "feat: add BearCrashShortV1 to metrics exporter"
```

---

### Task 5: Update Existing Tests

**Files:**
- Modify: `tests/test_docker_compose.py:46-49`
- Modify: `tests/test_infrastructure.py:105-113`

- [ ] **Step 1: Add to docker compose test**

In `test_restart_policy`, add `"bearcrashshortv1"` to the `active_services` list.

- [ ] **Step 2: Add to infrastructure test**

In `test_all_containers_running`, add `"bearcrashshortv1"` to the `expected_services` list.

- [ ] **Step 3: Run all existing tests (offline)**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/test_docker_compose.py tests/test_bear_crash_short.py -v -k "not live"`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_docker_compose.py tests/test_infrastructure.py
git commit -m "test: add BearCrashShortV1 to docker and infrastructure tests"
```

---

### Task 6: Backtest Validation

**Files:** None (validation only, no code changes)

- [ ] **Step 1: Download futures data for backtest period**

```bash
cd ~/ft_userdata && docker run --rm \
  -v ./user_data:/freqtrade/user_data \
  -v ./user_data/configs/backtest-BearCrashShortV1.json:/freqtrade/config.json \
  freqtradeorg/freqtrade:stable download-data \
  --timerange 20260101-20260323 --timeframe 1h 5m \
  --config /freqtrade/config.json --trading-mode futures
```

Note: Download both 1h and 5m data. 5m is needed for `--timeframe-detail 5m` accuracy.

- [ ] **Step 2: Run backtest on bear period (Feb 22 - Mar 1, market -1.22%)**

```bash
cd ~/ft_userdata && docker run --rm \
  -v ./user_data:/freqtrade/user_data \
  -v ./user_data/configs/backtest-BearCrashShortV1.json:/freqtrade/config.json \
  freqtradeorg/freqtrade:stable backtesting \
  --strategy BearCrashShortV1 \
  --timerange 20260222-20260301 \
  --timeframe 1h \
  --timeframe-detail 5m \
  --config /freqtrade/config.json
```

Expected: Should see SHORT trades (not long). Verify:
- `enter_short` signals present (not zero)
- No `enter_long` signals
- Profit factor > 1.0 in this bear period
- Check exit reasons include time_exit_48h, trailing_stop_loss, exit_signal

- [ ] **Step 3: Run backtest on bull period (Mar 11-16, market +5%)**

```bash
cd ~/ft_userdata && docker run --rm \
  -v ./user_data:/freqtrade/user_data \
  -v ./user_data/configs/backtest-BearCrashShortV1.json:/freqtrade/config.json \
  freqtradeorg/freqtrade:stable backtesting \
  --strategy BearCrashShortV1 \
  --timerange 20260311-20260316 \
  --timeframe 1h \
  --timeframe-detail 5m \
  --config /freqtrade/config.json
```

Expected: ZERO or near-zero trades (regime gate should block entries during bull market).

- [ ] **Step 4: Run backtest on current crash (Mar 18-23, market -10%)**

```bash
cd ~/ft_userdata && docker run --rm \
  -v ./user_data:/freqtrade/user_data \
  -v ./user_data/configs/backtest-BearCrashShortV1.json:/freqtrade/config.json \
  freqtradeorg/freqtrade:stable backtesting \
  --strategy BearCrashShortV1 \
  --timerange 20260318-20260323 \
  --timeframe 1h \
  --timeframe-detail 5m \
  --config /freqtrade/config.json
```

Expected: Should see profitable short trades during the crash our long bots sat out.

- [ ] **Step 5: Run full 3-month backtest**

```bash
cd ~/ft_userdata && docker run --rm \
  -v ./user_data:/freqtrade/user_data \
  -v ./user_data/configs/backtest-BearCrashShortV1.json:/freqtrade/config.json \
  freqtradeorg/freqtrade:stable backtesting \
  --strategy BearCrashShortV1 \
  --timerange 20260101-20260323 \
  --timeframe 1h \
  --timeframe-detail 5m \
  --config /freqtrade/config.json
```

Expected: Strategy should be profitable overall with low drawdown. Most trades should occur during the identified bear periods. Bull periods should show near-zero activity.

---

### Task 7: Deploy and Verify

- [ ] **Step 1: Start the new container**

```bash
cd ~/ft_userdata && docker compose up -d bearcrashshortv1
```

- [ ] **Step 2: Verify container health**

```bash
docker compose ps bearcrashshortv1
docker compose logs --tail=20 bearcrashshortv1
```

Expected: Container running, healthy, heartbeats showing, no errors.

- [ ] **Step 3: Verify API responds**

```bash
curl -s -u freqtrader:mastertrader http://localhost:8093/api/v1/show_config | python3 -m json.tool | head -10
```

Expected: JSON response with `strategy: BearCrashShortV1`, `state: running`, `trading_mode: futures`.

- [ ] **Step 4: Verify metrics exporter picks it up**

```bash
docker compose restart metrics-exporter && sleep 10
curl -s http://localhost:9090/metrics | grep -i bearcr
```

Expected: `freqtrade_bot_up{strategy="BearCrashShortV1"} 1`

- [ ] **Step 5: Run full test suite (live)**

Run: `cd /Users/palmer/Work/Dev/Master\ Trader && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: BearCrashShortV1 deployed — short-only bear regime bot on port 8093"
```
