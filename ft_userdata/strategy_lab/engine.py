"""
Fast screening engine for Strategy Lab.

Precomputes all indicators once, then rapidly evaluates signal combinations
by simulating trades on precomputed data.
"""

import json
import os
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from strategy_lab.signals import (
    EXIT_PROFILES,
    adx_trending,
    bollinger_bounce,
    btc_above_sma,
    btc_no_crash,
    btc_rsi_floor,
    bullish_engulfing,
    donchian_breakout,
    ema_crossover,
    funding_below_mean,
    funding_extreme_negative,
    funding_negative,
    ichimoku_bullish,
    keltner_bounce,
    macd_crossover,
    price_above_sma,
    rsi_range,
    stoch_oversold,
    supertrend,
    supertrend_all,
    volatility_regime,
    volume_spike,
    vwap_reclaim,
)

USER_DATA = Path(__file__).parent.parent / "user_data"
DOCKER_IMAGE = "freqtradeorg/freqtrade:stable"


# ── Data Types ──────────────────────────────────────────────

@dataclass
class SignalCombo:
    """A complete signal combination to test."""
    name: str
    entry_fn: Callable  # (pair_df) -> Series[bool]
    gate_fn: Callable   # (btc_df) -> Series[bool]
    exit_profile: str   # key into EXIT_PROFILES
    entry_desc: str = ""
    gate_desc: str = ""

    @property
    def label(self):
        return f"{self.entry_desc}|{self.gate_desc}|{self.exit_profile}"


@dataclass
class TradeResult:
    pair: str
    open_idx: int
    close_idx: int
    open_rate: float
    close_rate: float
    profit_pct: float
    profit_abs: float
    exit_reason: str


@dataclass
class ComboResult:
    combo: SignalCombo
    trades: list
    total_pnl: float = 0
    total_pnl_pct: float = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0
    profit_factor: float = 0
    max_drawdown_pct: float = 0
    score: float = -999

    def compute_metrics(self, wallet: float):
        if not self.trades:
            return
        self.wins = sum(1 for t in self.trades if t.profit_abs >= 0)
        self.losses = len(self.trades) - self.wins
        self.total_pnl = sum(t.profit_abs for t in self.trades)
        self.total_pnl_pct = self.total_pnl / wallet * 100
        self.win_rate = self.wins / len(self.trades) * 100

        gross_win = sum(t.profit_abs for t in self.trades if t.profit_abs >= 0)
        gross_loss = abs(sum(t.profit_abs for t in self.trades if t.profit_abs < 0))
        self.profit_factor = gross_win / gross_loss if gross_loss > 0 else 999

        # Max drawdown
        running = 0
        peak = 0
        max_dd = 0
        for t in self.trades:
            running += t.profit_abs
            if running > peak:
                peak = running
            dd = peak - running
            if dd > max_dd:
                max_dd = dd
        self.max_drawdown_pct = max_dd / wallet * 100

        # Score: PF * profit/DD * trade_penalty
        trade_mult = min(1.0, len(self.trades) / 50)
        dd = max(self.max_drawdown_pct, 0.1)
        self.score = self.profit_factor * (self.total_pnl_pct / dd) * trade_mult
        if self.profit_factor < 1.0:
            self.score *= 0.3
        if self.max_drawdown_pct > 30:
            self.score *= 0.5


# ── Detail Data (1m candles for accurate trade simulation) ──

@dataclass
class DetailData:
    """Pre-indexed 1m candle data for a single pair."""
    close: np.ndarray
    high: np.ndarray
    low: np.ndarray
    ts: np.ndarray          # unix timestamps (seconds), sorted

    def find_idx(self, target_ts: float) -> int:
        """Find 1m index for a given timestamp via binary search.
        Returns index if exact match within 1s, else -1."""
        idx = np.searchsorted(self.ts, target_ts)
        if idx < len(self.ts) and abs(self.ts[idx] - target_ts) < 1.0:
            return int(idx)
        if idx > 0 and abs(self.ts[idx - 1] - target_ts) < 1.0:
            return int(idx - 1)
        return -1


def load_detail_data(pairs: list) -> dict:
    """Load 1m candle data for all pairs. Returns {pair: DetailData}.

    Only keeps OHLC arrays + timestamp index — no DataFrame overhead.
    """
    detail = {}
    for pair in pairs:
        pair_file = pair.replace("/", "_")
        path = USER_DATA / "data" / "binance" / f"{pair_file}-1m.feather"
        if not path.exists():
            continue
        df = pd.read_feather(path)
        if "date" in df.columns:
            ts = df["date"].values.astype("int64") // 10**9  # nanoseconds -> seconds
        else:
            ts = df["timestamp"].values
            if ts[0] > 1e12:
                ts = ts // 1000
        ts = ts.astype(np.float64)
        detail[pair] = DetailData(
            close=df["close"].values.astype(np.float64),
            high=df["high"].values.astype(np.float64),
            low=df["low"].values.astype(np.float64),
            ts=ts,
        )
    return detail


# ── Data Loading ────────────────────────────────────────────

def load_candle_data(pair: str, timeframe: str = "1h") -> pd.DataFrame:
    """Load candle data from Freqtrade's data directory."""
    pair_file = pair.replace("/", "_")
    feather_path = USER_DATA / "data" / "binance" / f"{pair_file}-{timeframe}.feather"

    if feather_path.exists():
        df = pd.read_feather(feather_path)
        # Normalize column names
        if "date" in df.columns:
            df = df.rename(columns={"date": "timestamp"})
        if "timestamp" in df.columns and hasattr(df["timestamp"].iloc[0], "timestamp"):
            df["ts"] = df["timestamp"].apply(lambda x: x.timestamp())
        else:
            df["ts"] = df["timestamp"] / 1000 if df["timestamp"].iloc[0] > 1e12 else df["timestamp"]
        return df

    json_path = USER_DATA / "data" / "binance" / f"{pair_file}-{timeframe}.json"
    if json_path.exists():
        with open(json_path) as f:
            data = json.load(f)
        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["ts"] = df["timestamp"] / 1000
        return df

    return pd.DataFrame()


def load_all_pairs(pairs: list, timeframe: str = "1h") -> dict:
    """Load candle data for all pairs. Returns {pair: DataFrame}."""
    data = {}
    for pair in pairs:
        df = load_candle_data(pair, timeframe)
        if not df.empty:
            data[pair] = df
    return data


def get_available_pairs(timeframe: str = "1h", require_detail: bool = False) -> list:
    """List all pairs with available data.
    If require_detail=True, only returns pairs with both timeframe AND 1m data."""
    data_dir = USER_DATA / "data" / "binance"
    pairs = []
    for f in data_dir.iterdir():
        if f.suffix == ".feather" and f"-{timeframe}" in f.name:
            pair = f.name.replace(f"-{timeframe}.feather", "").replace("_", "/")
            if require_detail:
                detail_path = data_dir / f"{pair.replace('/', '_')}-1m.feather"
                if not detail_path.exists():
                    continue
            pairs.append(pair)
    return sorted(pairs)


# ── Trade Simulation ────────────────────────────────────────

def simulate_trade(
    candles_close: np.ndarray,
    candles_high: np.ndarray,
    candles_low: np.ndarray,
    entry_idx: int,
    open_rate: float,
    stoploss: float,
    roi_table: dict,
    trailing_positive: float,
    trailing_offset: float,
    fee: float = 0.001,
    max_candles: int = 200,
    candle_minutes: int = 60,
) -> TradeResult:
    """Simulate a single trade forward from entry.

    candle_minutes: 1 for 1m detail data, 60 for 1h (default).
    When using 1m detail, entry_idx points into the 1m array and
    max_candles is scaled by the caller (200h = 12000 1m candles).
    """
    length = len(candles_close)
    end_idx = min(entry_idx + max_candles, length)

    sl_price = open_rate * (1 + stoploss)
    highest = open_rate
    is_trailing = False

    # Parse ROI: sorted by minutes descending so we check longest first
    roi_entries = sorted([(int(k), v) for k, v in roi_table.items()], reverse=True)

    for i in range(entry_idx + 1, end_idx):
        candle_high = candles_high[i]
        candle_low = candles_low[i]
        candle_close = candles_close[i]
        elapsed_minutes = (i - entry_idx) * candle_minutes

        # Update highest
        if candle_high > highest:
            highest = candle_high

        # Trailing stop
        if trailing_offset > 0 and (highest - open_rate) / open_rate >= trailing_offset:
            new_sl = highest * (1 - trailing_positive)
            if new_sl > sl_price:
                sl_price = new_sl
                is_trailing = True

        # Check stoploss
        if candle_low <= sl_price:
            exit_rate = sl_price
            profit_pct = (exit_rate / open_rate) - 1 - (2 * fee)
            exit_reason = "trailing_stop_loss" if is_trailing else "stoploss"
            return TradeResult(
                pair="", open_idx=entry_idx, close_idx=i,
                open_rate=open_rate, close_rate=exit_rate,
                profit_pct=profit_pct, profit_abs=0,
                exit_reason=exit_reason,
            )

        # Check ROI (check all tiers, use the one with the smallest required profit)
        for roi_minutes, roi_pct in roi_entries:
            if elapsed_minutes >= roi_minutes:
                roi_price = open_rate * (1 + roi_pct)
                if candle_high >= roi_price:
                    profit_pct = roi_pct - (2 * fee)
                    return TradeResult(
                        pair="", open_idx=entry_idx, close_idx=i,
                        open_rate=open_rate, close_rate=roi_price,
                        profit_pct=profit_pct, profit_abs=0,
                        exit_reason="roi",
                    )
                break  # Only check the first applicable ROI tier

    # Force exit at end
    exit_rate = candles_close[end_idx - 1] if end_idx > entry_idx else open_rate
    profit_pct = (exit_rate / open_rate) - 1 - (2 * fee)
    return TradeResult(
        pair="", open_idx=entry_idx, close_idx=end_idx - 1,
        open_rate=open_rate, close_rate=exit_rate,
        profit_pct=profit_pct, profit_abs=0,
        exit_reason="force_exit",
    )


# ── Combo Screening ─────────────────────────────────────────

def screen_combo(
    combo: SignalCombo,
    pair_data: dict,
    btc_df: pd.DataFrame,
    wallet: float,
    max_open: int = 3,
    timerange_start: float = 0,
    timerange_end: float = float("inf"),
    detail_data: dict = None,
) -> ComboResult:
    """Screen a single signal combo across all pairs.

    Collects all candidate entries across pairs, then processes them
    chronologically with a global max_open constraint (mirrors Freqtrade).
    If detail_data is provided, trade simulation runs on 1m candles.
    """
    exit_params = EXIT_PROFILES[combo.exit_profile]

    # Compute BTC gate once
    btc_gate = combo.gate_fn(btc_df)
    btc_ts = btc_df["ts"].values
    btc_gate_vals = btc_gate.values

    # ── Collect all candidate entries across pairs ──
    candidates = []  # list of (ts, pair, idx, open_rate)

    for pair, df in pair_data.items():
        if pair == "BTC/USDT" and "btc" in combo.gate_desc.lower():
            continue

        # Attach pair for signals that need it (e.g. funding rate)
        df.attrs["pair"] = pair

        try:
            entry_signal = combo.entry_fn(df)
        except Exception:
            continue

        pair_ts = df["ts"].values
        close = df["close"].values

        gate_mapped = np.interp(pair_ts, btc_ts, btc_gate_vals.astype(float)) > 0.5
        combined = entry_signal.values & gate_mapped

        for idx in np.where(combined)[0]:
            ts = pair_ts[idx]
            if ts < timerange_start or ts > timerange_end:
                continue
            open_rate = close[idx]
            if open_rate <= 0:
                continue
            candidates.append((ts, pair, idx, open_rate))

    # Sort all candidates chronologically
    candidates.sort(key=lambda c: c[0])

    # ── Simulate trades with global max_open + per-pair cooldown ──
    stake_per_trade = wallet / max_open
    all_trades = []
    open_exit_times = []        # sorted list of pending exit timestamps (global)
    pair_last_exit = {}         # {pair: last_exit_ts}  — prevents re-entry on same pair

    for ts, pair, idx, open_rate in candidates:
        # Prune expired open trades
        open_exit_times = [t for t in open_exit_times if t > ts]

        # Global concurrency cap
        if len(open_exit_times) >= max_open:
            continue

        # Per-pair cooldown (no re-entry until prior trade on this pair exits)
        if ts <= pair_last_exit.get(pair, 0):
            continue

        df = pair_data[pair]
        close = df["close"].values
        high = df["high"].values
        low = df["low"].values
        pair_ts = df["ts"].values

        det = detail_data.get(pair) if detail_data else None

        trade = None
        if det is not None:
            # 1h signal fires on close of bar at ts. Entry executes at start of
            # next 1h bar — find 1m idx at ts, then skip 60 min to reach end-of-hour.
            detail_hour_start = det.find_idx(ts)
            detail_entry_idx = detail_hour_start + 60 if detail_hour_start >= 0 else -1

            if 0 <= detail_entry_idx < len(det.ts):
                trade = simulate_trade(
                    candles_close=det.close,
                    candles_high=det.high,
                    candles_low=det.low,
                    entry_idx=detail_entry_idx,
                    open_rate=open_rate,
                    stoploss=exit_params["stoploss"],
                    roi_table=exit_params["minimal_roi"],
                    trailing_positive=exit_params["trailing_stop_positive"],
                    trailing_offset=exit_params["trailing_stop_positive_offset"],
                    max_candles=72 * 60,
                    candle_minutes=1,
                )
                exit_ts = det.ts[trade.close_idx] if trade.close_idx < len(det.ts) else det.ts[-1]

        if trade is None:
            # Fallback 1h simulation
            trade = simulate_trade(
                candles_close=close,
                candles_high=high,
                candles_low=low,
                entry_idx=idx,
                open_rate=open_rate,
                stoploss=exit_params["stoploss"],
                roi_table=exit_params["minimal_roi"],
                trailing_positive=exit_params["trailing_stop_positive"],
                trailing_offset=exit_params["trailing_stop_positive_offset"],
                candle_minutes=60,
            )
            exit_ts = pair_ts[min(trade.close_idx, len(pair_ts) - 1)]

        trade.pair = pair
        trade.profit_abs = stake_per_trade * trade.profit_pct
        all_trades.append(trade)
        open_exit_times.append(exit_ts)
        pair_last_exit[pair] = exit_ts

    result = ComboResult(combo=combo, trades=all_trades)
    result.compute_metrics(wallet)
    return result


# ── Combo Generation ────────────────────────────────────────

def generate_combos() -> list:
    """Generate all signal combinations to test."""
    combos = []

    # ── Anchor signals with param variants ──
    anchors = [
        # Trend-following
        ("st(3,10)", lambda df: supertrend(df, 3, 10)),
        ("st(4,8)", lambda df: supertrend(df, 4, 8)),
        ("st(5,14)", lambda df: supertrend(df, 5, 14)),
        ("st(2,7)", lambda df: supertrend(df, 2, 7)),
        ("st_all(4,8+1,8)", lambda df: supertrend_all(df, [(4, 8), (1, 8)])),
        ("ema(9,21)", lambda df: ema_crossover(df, 9, 21)),
        ("ema(12,26)", lambda df: ema_crossover(df, 12, 26)),
        ("ema(5,21)", lambda df: ema_crossover(df, 5, 21)),
        ("macd", lambda df: macd_crossover(df)),
        # Mean reversion
        ("bb(20,2)", lambda df: bollinger_bounce(df, 20, 2)),
        ("bb(20,3)", lambda df: bollinger_bounce(df, 20, 3)),
        ("kelt(20,2)", lambda df: keltner_bounce(df, 20, 2.0)),
        ("kelt(20,2.5)", lambda df: keltner_bounce(df, 20, 2.5)),
        # Breakout
        ("donch(20)", lambda df: donchian_breakout(df, 20)),
        ("donch(55)", lambda df: donchian_breakout(df, 55)),
        # Multi-indicator
        ("ichi", lambda df: ichimoku_bullish(df)),
        # Volume-weighted
        ("vwap(20)", lambda df: vwap_reclaim(df, 20)),
        ("vwap(50)", lambda df: vwap_reclaim(df, 50)),
        # Price action
        ("engulf", lambda df: bullish_engulfing(df)),
        # Funding rate — pure funding-based entries (non-TA)
        ("funding_neg", lambda df: funding_negative(df)),
        ("funding_p5", lambda df: funding_extreme_negative(df, 0.05, 1000)),
        ("funding_p10", lambda df: funding_extreme_negative(df, 0.10, 1000)),
        ("funding_below_mean", lambda df: funding_below_mean(df, 500)),
    ]

    # ── Confirmation filters (0-2 added) ──
    confirms = [
        ("", lambda df: pd.Series(True, index=df.index)),
        ("rsi(30,70)", lambda df: rsi_range(df, 30, 70)),
        ("rsi(25,65)", lambda df: rsi_range(df, 25, 65)),
        ("rsi(35,75)", lambda df: rsi_range(df, 35, 75)),
        ("vol(1.5)", lambda df: volume_spike(df, 1.5)),
        ("vol(2.0)", lambda df: volume_spike(df, 2.0)),
        ("adx(20)", lambda df: adx_trending(df, 20)),
        ("adx(25)", lambda df: adx_trending(df, 25)),
        ("adx(30)", lambda df: adx_trending(df, 30)),
        ("stoch(20)", lambda df: stoch_oversold(df, 20)),
        ("rsi(30,70)+vol(1.5)", lambda df: rsi_range(df, 30, 70) & volume_spike(df, 1.5)),
        ("rsi(30,70)+adx(25)", lambda df: rsi_range(df, 30, 70) & adx_trending(df, 25)),
        ("adx(25)+vol(1.5)", lambda df: adx_trending(df, 25) & volume_spike(df, 1.5)),
        # Funding-rate confirmations: require funding to be extreme-negative at entry
        ("funding_neg", lambda df: funding_negative(df)),
        ("funding_p10", lambda df: funding_extreme_negative(df, 0.10, 1000)),
    ]

    # ── Regime gates ──
    gates = [
        ("btc_sma50", lambda df: btc_above_sma(df, 50)),
        ("btc_sma50+nc24", lambda df: btc_above_sma(df, 50) & btc_no_crash(df, 24, 3)),
        ("btc_sma200", lambda df: btc_above_sma(df, 200)),
        ("btc_sma50+sma200", lambda df: btc_above_sma(df, 50) & btc_above_sma(df, 200)),
        ("btc_sma50+rsi35", lambda df: btc_above_sma(df, 50) & btc_rsi_floor(df, 35)),
    ]

    # ── Exit profiles ──
    exits = ["tight", "balanced", "wide", "roi_only"]

    # Generate all combos
    for a_name, a_fn in anchors:
        for c_name, c_fn in confirms:
            for g_name, g_fn in gates:
                for exit_name in exits:
                    entry_desc = f"{a_name}+{c_name}" if c_name else a_name

                    def make_entry(a=a_fn, c=c_fn):
                        return lambda df: a(df) & c(df)

                    combos.append(SignalCombo(
                        name=f"{entry_desc}|{g_name}|{exit_name}",
                        entry_fn=make_entry(),
                        gate_fn=g_fn,
                        exit_profile=exit_name,
                        entry_desc=entry_desc,
                        gate_desc=g_name,
                    ))

    return combos


def screen_all(
    combos: list,
    pair_data: dict,
    btc_df: pd.DataFrame,
    wallet: float = 88,
    max_open: int = 3,
    timerange_start: float = 0,
    timerange_end: float = float("inf"),
    detail_data: dict = None,
) -> list:
    """Screen all combos and return sorted results."""
    results = []
    total = len(combos)
    mode = "1m detail" if detail_data else "1h only"

    for i, combo in enumerate(combos):
        if (i + 1) % 50 == 0 or i == 0:
            print(f"[lab] Screening {i+1}/{total} ({mode})...", flush=True)

        result = screen_combo(
            combo, pair_data, btc_df, wallet, max_open,
            timerange_start, timerange_end, detail_data,
        )
        results.append(result)

    results.sort(key=lambda r: r.score, reverse=True)
    return results
