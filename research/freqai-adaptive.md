# FreqAI - Adaptive Machine Learning for Trading

> Research date: 2026-03-11
> Sources: Official FreqAI docs, Emergent Methods blog, GitHub repos, academic papers

---

## 1. Architecture & How FreqAI Works

### Core Concept

FreqAI is Freqtrade's built-in ML module that automates training predictive models to generate
market forecasts. It sits on top of Freqtrade's strategy system and adds an adaptive ML layer.

### Training/Prediction Cycle

1. **You define base indicators** (RSI, EMA, etc.) in `feature_engineering_*` functions
2. **You define target labels** (future price change) in `set_freqai_targets()`
3. **FreqAI trains a model** per pair to predict targets from indicators
4. **Models retrain periodically** via a sliding window to adapt to market conditions
5. **Predictions feed back** into your strategy's `populate_entry_signal()` / `populate_exit_signal()`

### Data Flow

```
Historical OHLCV Data
    -> Feature Engineering (your indicators, expanded across timeframes/periods/pairs)
    -> Train/Test Split (chronological, no shuffle)
    -> Model Training (LightGBM/XGBoost/PyTorch/RL)
    -> Prediction on live candles
    -> Strategy uses prediction as signal confirmation
    -> Periodic retraining on new data (sliding window)
```

### Key Components

- **FreqaiDataDrawer**: Persistent storage of models, metadata, historic predictions (stays in memory)
- **FreqaiDataKitchen**: Data processing, feature expansion, train/test splitting
- **Threading**: Model retraining runs on a separate thread from bot trade operations
- **Per-pair models**: Each coin pair gets its own model, trained sequentially

### Retraining

- In **live/dry mode**: FreqAI maintains an internal queue, keeping all models equally up-to-date
- Always uses the **most recently trained model** for predictions
- Controlled by `live_retrain_hours` (minimum hours between retrains)
- `expiration_hours` blocks predictions from stale models

---

## 2. Supported Models

### Gradient Boosted Trees (Primary, Recommended)

| Model | Status | Notes |
|-------|--------|-------|
| **LightGBM** | Active, recommended | Fast training, CPU-friendly, good default |
| **XGBoost** | Active, recommended | Proven in real-time tests, 7% profit in 3-week test |
| **CatBoost** | **Deprecated since 2025.12** | Too slow for real-time retraining on 5m data |

Each supports: **Regression**, **Classification**, and **Multi-target** variants.

FreqAI provides **18 pre-configured prediction models** out of the box.

### PyTorch (Deep Learning)

- Custom neural networks (LSTM, etc.)
- Configurable via `model_kwargs` and `trainer_kwargs`
- Default learning_rate: 3e-4, batch_size: 64, n_epochs: 10
- Community example: FreqAI-LSTM with dynamic weighting achieved >90% accuracy on 120-day backtest

### Reinforcement Learning (stable-baselines3)

Supported algorithms:
- **PPO** (Proximal Policy Optimization) - most commonly used
- **A2C** (Advantage Actor-Critic)
- **DQN** (Deep Q-Network)
- **TRPO** (Trust Region Policy Optimization)
- **ARS** (Augmented Random Search)

Action spaces:
- **Base3Action**: Hold, Long, Short
- **Base4Action**: Enter Long, Enter Short, Hold, Exit
- **Base5Action**: Enter Long, Enter Short, Hold, Exit Long, Exit Short

---

## 3. XGBoost vs CatBoost: Real-World Head-to-Head

**Emergent Methods ran a 3-week live test** (Feb 16 - Mar 12) with FreqAI:
- 19 coin pairs (/USDT), 5-minute candles
- Identical servers (12-core Xeon X5660, 64GB DDR3)

### Results

| Metric | XGBoost | CatBoost |
|--------|---------|----------|
| **Profit** | **+7%** | +2% |
| **Training speed** | Fast | Slow (couldn't keep up with 5m data) |
| **Model freshness** | Always current | Sometimes stale (training too slow) |

**Verdict**: XGBoost clearly won. CatBoost's slow training meant models weren't always using the most recent data. This is critical for adaptive systems.

---

## 4. Configuration

### Minimum Config

```json
{
    "freqai": {
        "enabled": true,
        "purge_old_models": 2,
        "train_period_days": 30,
        "backtest_period_days": 7,
        "identifier": "unique-id",
        "feature_parameters": {
            "include_timeframes": ["5m", "15m", "4h"],
            "include_corr_pairlist": ["ETH/USD", "LINK/USD", "BNB/USD"],
            "label_period_candles": 24,
            "include_shifted_candles": 2,
            "indicator_periods_candles": [10, 20]
        },
        "data_split_parameters": {
            "test_size": 0.25
        }
    }
}
```

### Full Working Config (Adapted from Official Example)

```json
{
    "trading_mode": "spot",
    "margin_mode": "isolated",
    "max_open_trades": 5,
    "stake_currency": "USDT",
    "stake_amount": 200,
    "dry_run": true,
    "dry_run_wallet": 1000,
    "timeframe": "5m",

    "freqai": {
        "enabled": true,
        "purge_old_models": 4,
        "train_period_days": 30,
        "backtest_period_days": 7,
        "identifier": "lightgbm-spot-v1",
        "live_retrain_hours": 8,
        "expiration_hours": 16,
        "continual_learning": false,
        "fit_live_predictions_candles": 300,

        "feature_parameters": {
            "include_timeframes": ["5m", "15m", "1h"],
            "include_corr_pairlist": ["BTC/USDT", "ETH/USDT"],
            "label_period_candles": 20,
            "include_shifted_candles": 2,
            "indicator_periods_candles": [10, 20],
            "weight_factor": 0.9,
            "principal_component_analysis": false,
            "use_SVM_to_remove_outliers": true,
            "DI_threshold": 0.9,
            "use_DBSCAN_to_remove_outliers": false,
            "noise_standard_deviation": 0.05,
            "outlier_protection_percentage": 30,
            "reverse_train_test_order": false,
            "shuffle_after_split": false,
            "buffer_train_data_candles": 0
        },

        "data_split_parameters": {
            "test_size": 0.25,
            "shuffle": false
        },

        "model_training_parameters": {
            "n_estimators": 800,
            "learning_rate": 0.02,
            "n_jobs": -1
        }
    }
}
```

### Key Parameters Explained

| Parameter | Recommended | Why |
|-----------|-------------|-----|
| `train_period_days` | 15-60 | Too short = not enough data; too long = stale patterns |
| `backtest_period_days` | 5-10 | How often to retrain during backtest simulation |
| `live_retrain_hours` | 4-24 | Lower = more adaptive but more CPU; 8h is a good start |
| `expiration_hours` | 2x retrain hours | Block predictions from stale models |
| `indicator_periods_candles` | [10, 20] | Expand indicators across these periods |
| `include_timeframes` | ["5m","15m","1h"] | Multi-timeframe features |
| `label_period_candles` | 12-24 | How far into the future the target looks |
| `weight_factor` | 0.9 | Recent data weighted more (exponential decay) |
| `noise_standard_deviation` | 0.01-0.05 | Gaussian noise to prevent overfitting |
| `use_SVM_to_remove_outliers` | true | Helps clean training data |
| `test_size` | 0.25 | 25% of data for validation |

### Reinforcement Learning Config Addition

```json
"rl_config": {
    "train_cycles": 25,
    "add_state_info": true,
    "max_trade_duration_candles": 300,
    "max_training_drawdown_pct": 0.02,
    "cpu_count": 8,
    "model_type": "PPO",
    "policy_type": "MlpPolicy",
    "net_arch": [128, 128],
    "randomize_starting_position": true,
    "model_reward_parameters": {
        "rr": 1,
        "profit_aim": 0.025
    }
}
```

---

## 5. Feature Engineering

### Function Hierarchy

```python
# 1. Expanded across ALL config dimensions (timeframes, periods, pairs, shifts)
def feature_engineering_expand_all(self, dataframe, period, metadata, **kwargs):
    dataframe["%-rsi-period"] = ta.RSI(dataframe, timeperiod=period)
    dataframe["%-mfi-period"] = ta.MFI(dataframe, timeperiod=period)
    dataframe["%-adx-period"] = ta.ADX(dataframe, timeperiod=period)
    dataframe["%-sma-period"] = ta.SMA(dataframe, timeperiod=period)
    dataframe["%-ema-period"] = ta.EMA(dataframe, timeperiod=period)
    dataframe["%-roc-period"] = ta.ROC(dataframe, timeperiod=period)
    bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=period, stds=2.2)
    dataframe["%-bb_width-period"] = (
        bollinger["upper"] - bollinger["lower"]
    ) / bollinger["mid"]
    dataframe["%-relative_volume-period"] = (
        dataframe["volume"] / dataframe["volume"].rolling(period).mean()
    )
    return dataframe

# 2. Expanded across timeframes, shifts, pairs (NOT periods)
def feature_engineering_expand_basic(self, dataframe, metadata, **kwargs):
    dataframe["%-pct-change"] = dataframe["close"].pct_change()
    dataframe["%-raw_volume"] = dataframe["volume"]
    dataframe["%-raw_price"] = dataframe["close"]
    return dataframe

# 3. Standard features (no expansion, base timeframe only)
def feature_engineering_standard(self, dataframe, metadata, **kwargs):
    dataframe["%-day_of_week"] = (dataframe["date"].dt.dayofweek + 1) / 7
    dataframe["%-hour_of_day"] = (dataframe["date"].dt.hour + 1) / 25
    return dataframe

# 4. Target labels (what the model predicts)
def set_freqai_targets(self, dataframe, metadata, **kwargs):
    dataframe["&-s_close"] = (
        dataframe["close"]
        .shift(-self.freqai_info["feature_parameters"]["label_period_candles"])
        .rolling(self.freqai_info["feature_parameters"]["label_period_candles"])
        .mean()
        / dataframe["close"]
        - 1
    )
    return dataframe
```

### Feature Naming Rules

- **`%-`** prefix = feature (input to model)
- **`&-`** prefix = target/label (what model predicts)
- `-period` suffix = auto-replaced with each `indicator_periods_candles` value

### Feature Expansion Math

With config: 2 periods x 3 timeframes x 3 corr pairs x 2 shifted candles = **36x multiplier per feature**

If you define 8 features in `feature_engineering_expand_all`, you get **288 features** automatically.

### Recommended Features for Crypto

**Core (expand_all):**
- RSI, MFI, ADX (momentum/trend strength)
- SMA, EMA (trend direction)
- Bollinger Band width (volatility)
- ROC (rate of change)
- Relative volume

**Basic (expand_basic):**
- Price percent change
- Raw volume
- Raw close price

**Standard (no expansion):**
- Day of week (normalized 0-1)
- Hour of day (normalized 0-1)

**For RL, also add:**
- `%-raw_close`, `%-raw_open`, `%-raw_high`, `%-raw_low` (required)

---

## 6. Common Pitfalls

### 1. Overfitting

**The #1 killer.** FreqAI models that look amazing in backtesting but fail live.

Prevention:
- Use `noise_standard_deviation: 0.01-0.05` to add Gaussian noise during training
- Use `use_SVM_to_remove_outliers: true` to clean training data
- Keep feature count reasonable (sample-to-feature ratio >= 10:1, ideally 20:1)
- Don't over-optimize `model_training_parameters` - simpler is better
- Use `weight_factor: 0.9` so recent data matters more

### 2. Look-Ahead Bias

**Silent and devastating.** Creates illusion of success, guarantees production failure.

Prevention:
- **Never shuffle time-series data** (`shuffle: false` in data_split_parameters)
- Targets naturally look ahead (that's their job), but features must NOT
- Don't use future values in feature calculations
- Ensure rolling calculations only use past data
- FreqAI handles train/test splitting chronologically, but your custom features can still leak

### 3. Feature Engineering Mistakes

- **Too many features**: More features != better. Increases noise, overfitting risk
- **Correlated features**: Multiple similar indicators add noise, not signal
- **Non-stationary features**: Raw price levels are poor features; use returns/changes instead
- **Forgetting `%-` prefix**: Features without `%` prefix are invisible to FreqAI

### 4. Retraining Too Frequently or Infrequently

- **Too frequent**: Model never stabilizes, excessive CPU usage
- **Too infrequent**: Model becomes stale, can't adapt to regime changes
- **Sweet spot**: 4-24 hours for live trading (depends on timeframe)

### 5. RL-Specific Pitfalls

- RL agents can find "cheats" to maximize reward without profitable trades
- The training environment is simplified (no `custom_exit`, `custom_stoploss`, etc.)
- RL requires much more tuning than supervised learning
- `calculate_reward()` design is critical and non-trivial
- Bad reward functions lead to agents that exploit edge cases

### 6. CatBoost Training Speed

- CatBoost is too slow for real-time adaptive retraining (proven in Emergent Methods test)
- **CatBoost deprecated in FreqAI since 2025.12** - use LightGBM or XGBoost instead

---

## 7. Supervised Learning vs Reinforcement Learning

### Supervised (Regression/Classification) - Recommended for Starting

**Pros:**
- Simpler to implement and debug
- Faster training (LightGBM/XGBoost)
- More stable predictions
- Less prone to exploitation/cheating
- Academic research shows supervised can match or outperform RL for crypto
- Better suited for CPU-only training (Mac Studio)

**Cons:**
- Requires explicit target definition (you decide what to predict)
- Less adaptive to changing market conditions

### Reinforcement Learning

**Pros:**
- Self-discovers optimal entry/exit timing
- More adaptive to market regime changes
- Doesn't need pre-defined targets
- PPO achieved 103% cumulative return in one study

**Cons:**
- Much more complex to configure correctly
- Agents can learn to "cheat" (maximize reward without profiting)
- Slower training (PyTorch-based, needs more compute)
- Training environment is simplified vs real market
- Harder to debug when things go wrong
- Poor Apple Silicon GPU utilization (known issue #12364)

### Recommendation

**Start with LightGBM or XGBoost regression.** Get comfortable with the system, validate
your features, then experiment with RL later. Supervised learning is more practical for a
first deployment and works well on CPU-only hardware.

---

## 8. CPU vs GPU: Mac Studio Considerations

### The Good News

- **LightGBM and XGBoost are CPU-native** - they don't need GPU at all
- Mac Studio's multi-core CPU is well-suited for gradient boosted trees
- LightGBM uses all available CPU cores by default
- Training a model on 30 days of 5m data takes seconds to minutes, not hours

### The Bad News

- **Apple Silicon GPU (Metal) is NOT well supported** by FreqAI's RL training
- Known issue: M3 Max training speed not significantly faster than Intel Mac Mini for RL (#12364)
- PyTorch MPS (Metal Performance Shaders) backend has limitations:
  - No multi-GPU distributed training
  - FP16 support incomplete
  - Some operations fall back to CPU
- LightGBM GPU training also doesn't work on Apple Silicon (#6189)

### Performance Tips for Mac Studio

1. **Use LightGBM or XGBoost** (not PyTorch/RL) for best performance
2. Set `OMP_WAIT_POLICY=active` for M2+ chips (~1.6x speedup)
3. Ensure packages are ARM64 native (not Rosetta)
4. Set `n_jobs: -1` in model_training_parameters to use all cores
5. Use `data_kitchen_thread_count` to control data processing threads
6. For RL, set `cpu_count: 8` (or your core count) in rl_config
7. Keep `train_period_days` reasonable (15-30) to limit training data size

### Practical Expectations

| Model Type | Training Time (30d, 5m, 19 pairs) | Hardware Fit |
|------------|-------------------------------------|-------------|
| LightGBM | Seconds per pair | Excellent on Mac Studio |
| XGBoost | Seconds per pair | Excellent on Mac Studio |
| PyTorch LSTM | Minutes per pair | OK (CPU), poor GPU utilization |
| RL (PPO) | Minutes-hours per pair | Poor on Apple Silicon |

---

## 9. Notable Community Projects

### FreqAI-LSTM (Netanelshoshan)
- LSTM with dynamic weighting and aggregate scoring
- Combines: MA, MACD, ROC, RSI, Bollinger, CCI, Momentum, Stochastic, ATR, OBV
- Z-score normalization for fair indicator weighting
- Market regime filter + volatility adjustment
- Config: learning_rate 3e-3, LSTM 3 layers, hidden_dim 128, dropout 0.4
- https://github.com/Netanelshoshan/freqAI-LSTM

### Project Litmus (markdregan)
- Implements Marcos Lopez de Prado's "Advances in Financial Machine Learning"
- Fractional differentiation, purged cross-validation
- No longer actively developed but code available
- https://github.com/markdregan/FreqAI-Marcos-Lopez-De-Prado

### KDog FreqAI Strategies (kyrypto)
- Multiple FreqAI strategies
- https://github.com/kyrypto/kdog-freqai-strats

### Awesome Freqtrade (just-nilux)
- Curated list of FreqAI resources, code snippets, strategies
- Dynamic pairlist helper for ML
- https://github.com/just-nilux/awesome-freqtrade

---

## 10. Practical Recommendations for Our Setup

### Phase 1: Start Simple (Supervised Learning)

```
Model: LightGBM Regressor
Timeframe: 5m
Training window: 30 days
Retraining: Every 8 hours
Target: Mean price change over next 20 candles
Features: RSI, MFI, ADX, EMA, SMA, BB width, ROC, relative volume
Timeframes: 5m, 15m, 1h
Correlation pairs: BTC/USDT, ETH/USDT
Outlier removal: SVM enabled
```

### Phase 2: Multi-Target Classification

```
Model: LightGBM Classifier
Targets: Up (>1%), Down (<-1%), Neutral
Add: Day of week, hour of day features
Add: DBSCAN outlier removal
Tune: indicator_periods_candles, label_period_candles
```

### Phase 3: Experiment with RL (Optional)

```
Model: PPO with MlpPolicy
Only if supervised learning is stable and profitable
Focus on reward function design
Expect longer training times on Mac Studio
```

### What NOT to Do

1. Don't start with RL - it's a rabbit hole
2. Don't use CatBoost (deprecated, too slow)
3. Don't add 50 features - start with 8-10 core indicators
4. Don't retrain every hour - 8-24h is fine for 5m data
5. Don't trust backtesting results alone - validate in dry-run
6. Don't skip outlier removal (SVM or DBSCAN)
7. Don't use raw prices as features (use returns/changes)

---

## 11. Key Links

- [FreqAI Introduction](https://www.freqtrade.io/en/stable/freqai/)
- [FreqAI Configuration](https://www.freqtrade.io/en/stable/freqai-configuration/)
- [FreqAI Feature Engineering](https://www.freqtrade.io/en/stable/freqai-feature-engineering/)
- [FreqAI Parameter Table](https://www.freqtrade.io/en/stable/freqai-parameter-table/)
- [FreqAI Reinforcement Learning](https://www.freqtrade.io/en/stable/freqai-reinforcement-learning/)
- [FreqAI Running Guide](https://www.freqtrade.io/en/stable/freqai-running/)
- [Config Example (GitHub)](https://github.com/freqtrade/freqtrade/blob/develop/config_examples/config_freqai.example.json)
- [Example Strategy (GitHub)](https://github.com/freqtrade/freqtrade/blob/develop/freqtrade/templates/FreqaiExampleStrategy.py)
- [XGBoost vs CatBoost Real-Time Test](https://emergentmethods.medium.com/real-time-head-to-head-adaptive-modeling-of-financial-market-data-using-xgboost-and-catboost-995a115a7495)
- [FreqAI JOSS Paper](https://www.theoj.org/joss-papers/joss.04864/10.21105.joss.04864.pdf)
- [FreqAI-LSTM Project](https://github.com/Netanelshoshan/freqAI-LSTM)
- [Marcos Lopez de Prado Implementation](https://github.com/markdregan/FreqAI-Marcos-Lopez-De-Prado)
- [Awesome Freqtrade Resources](https://github.com/just-nilux/awesome-freqtrade)
- [Freqtrade Discord](https://discord.com/invite/T7SmVvQ8sD)
- [FreqAI Discord](https://discord.com/invite/hYuzJYKFjz)
- [Mac Studio Training Speed Issue](https://github.com/freqtrade/freqtrade/issues/12364)
