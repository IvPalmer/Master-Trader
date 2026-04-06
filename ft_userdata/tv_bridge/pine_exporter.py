"""
Strategy Lab → Pine Script Bridge.

Converts strategy_lab.py winning signal combos into Pine Script indicators
for visual validation on TradingView before deploying as Freqtrade bots.

Usage: python3 ft_userdata/tv_bridge/pine_exporter.py <lab_results_file>
"""
import json
import os
import sys
import hashlib
from datetime import datetime

LAB_PINE_DIR = os.path.join(os.path.dirname(__file__), "lab_pine")

# Signal name → Pine Script expression mapping
# Must match signal names from strategy_lab's signals.py
SIGNAL_TO_PINE = {
    # Bollinger Bands
    "bb_lower_bounce": "ta.crossover(close, ta.bb(close, 20, 2.0)[2])",
    "bb_upper_reject": "ta.crossunder(close, ta.bb(close, 20, 2.0)[0])",
    # RSI conditions
    "rsi_oversold_bounce": "(ta.rsi(close, 14) > 30 and ta.rsi(close, 14)[1] <= 30)",
    "rsi_30_70": "(ta.rsi(close, 14) >= 30 and ta.rsi(close, 14) <= 70)",
    "rsi_overbought": "(ta.rsi(close, 14) > 70)",
    "rsi_oversold": "(ta.rsi(close, 14) < 30)",
    # ADX / trend
    "adx_trending": "(ta.dmi(14, 14)[2] > 25)",
    "adx_strong_trend": "(ta.dmi(14, 14)[2] > 30)",
    "di_bullish": "(ta.dmi(14, 14)[0] > ta.dmi(14, 14)[1])",
    "di_bearish": "(ta.dmi(14, 14)[1] > ta.dmi(14, 14)[0])",
    # EMA crossovers
    "ema_cross_up_9_21": "ta.crossover(ta.ema(close, 9), ta.ema(close, 21))",
    "ema_cross_down_9_21": "ta.crossunder(ta.ema(close, 9), ta.ema(close, 21))",
    "close_above_ema50": "(close > ta.ema(close, 50))",
    "close_below_ema50": "(close < ta.ema(close, 50))",
    # SMA guards
    "close_above_sma200": "(close > ta.sma(close, 200))",
    "close_below_sma200": "(close < ta.sma(close, 200))",
    "close_above_sma50": "(close > ta.sma(close, 50))",
    # Volume
    "volume_above_avg": "(volume > ta.sma(volume, 20))",
    "volume_spike": "(volume > ta.sma(volume, 20) * 2.0)",
    # MACD
    "macd_bullish_cross": "ta.crossover(ta.macd(close, 12, 26, 9)[0], ta.macd(close, 12, 26, 9)[1])",
    "macd_bearish_cross": "ta.crossunder(ta.macd(close, 12, 26, 9)[0], ta.macd(close, 12, 26, 9)[1])",
    "macd_above_zero": "(ta.macd(close, 12, 26, 9)[0] > 0)",
    # Supertrend
    "supertrend_bullish": "(ta.supertrend(3, 10)[1] < 0)",
    "supertrend_bearish": "(ta.supertrend(3, 10)[1] > 0)",
    # Stochastic
    "stoch_oversold": "(ta.stoch(close, high, low, 14) < 20)",
    "stoch_overbought": "(ta.stoch(close, high, low, 14) > 80)",
}


def generate_pine_script(combo, score=None, pf=None, combo_name=None):
    """Generate a Pine Script indicator from a signal combo."""
    if combo_name is None:
        combo_name = "_".join(combo[:3])

    # Build entry condition
    pine_conditions = []
    unknown_signals = []

    for signal in combo:
        if signal in SIGNAL_TO_PINE:
            pine_conditions.append(SIGNAL_TO_PINE[signal])
        else:
            unknown_signals.append(signal)

    if not pine_conditions:
        return None, f"No known Pine mappings for signals: {combo}"

    entry_condition = " and\n     ".join(pine_conditions)

    # BTC gate (always include)
    btc_gate = """
// BTC SMA200 Gate
btc_close = request.security("BINANCE:BTCUSDT", timeframe.period, close)
btc_sma200 = request.security("BINANCE:BTCUSDT", timeframe.period, ta.sma(close, 200))
btc_gate = btc_close > btc_sma200"""

    # Build the script
    meta = f"// Score: {score}, PF: {pf}" if score else ""
    if unknown_signals:
        meta += f"\n// Unknown signals (not mapped): {unknown_signals}"

    script = f"""//@version=6
indicator("Lab: {combo_name}", overlay=true, max_labels_count=500)
{meta}

// === Signals ===
// Combo: {combo}
{btc_gate}

entry_signal = btc_gate and
     {entry_condition}

// === Plot ===
plotshape(entry_signal, "Entry", shape.triangleup, location.belowbar, color.lime, size=size.small)
bgcolor(btc_gate ? color.new(color.green, 95) : color.new(color.red, 95), title="BTC Guard")

var tbl = table.new(position.top_right, 1, 2, bgcolor=color.new(color.black, 80))
if barstate.islast
    table.cell(tbl, 0, 0, "Lab: {combo_name}", text_color=color.lime, text_size=size.small)
    table.cell(tbl, 0, 1, "Signals: {len(combo)}", text_color=color.white, text_size=size.small)
"""
    return script, None


def export_lab_results(results_file, top_n=5):
    """Read a lab results JSON and export top combos as Pine Scripts."""
    with open(results_file) as f:
        data = json.load(f)

    results = data if isinstance(data, list) else data.get("results", data.get("combos", []))
    if not results:
        print(f"No results found in {results_file}")
        return []

    # Sort by score descending
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    top = results[:top_n]

    exported = []
    os.makedirs(LAB_PINE_DIR, exist_ok=True)

    for i, result in enumerate(top):
        combo = result.get("combo", result.get("signals", []))
        score = result.get("score", 0)
        pf = result.get("profit_factor", result.get("pf", 0))

        combo_hash = hashlib.md5("_".join(combo).encode()).hexdigest()[:8]
        combo_name = f"combo_{i+1}_{combo_hash}"

        script, error = generate_pine_script(combo, score=score, pf=pf, combo_name=combo_name)
        if error:
            print(f"  Skip combo {i+1}: {error}")
            continue

        filepath = os.path.join(LAB_PINE_DIR, f"{combo_name}.pine")
        with open(filepath, "w") as f:
            f.write(script)

        exported.append(
            {
                "combo": combo,
                "score": score,
                "pf": pf,
                "pine_file": filepath,
                "combo_name": combo_name,
            }
        )
        print(f"  #{i+1} [{combo_name}] score={score} pf={pf} → {filepath}")

    return exported


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 pine_exporter.py <lab_results_file> [top_n]")
        print()
        print("Converts Strategy Lab winning combos to Pine Script indicators.")
        print("Signal mappings:")
        for sig, pine in sorted(SIGNAL_TO_PINE.items()):
            print(f"  {sig:30s} → {pine[:60]}")
        sys.exit(0)

    results_file = sys.argv[1]
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    print(f"=== Pine Script Exporter ===")
    print(f"Input: {results_file}")
    print(f"Top N: {top_n}\n")

    exported = export_lab_results(results_file, top_n)
    print(f"\nExported {len(exported)} Pine Scripts to {LAB_PINE_DIR}")
