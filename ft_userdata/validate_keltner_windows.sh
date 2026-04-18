#!/bin/bash
# Run Freqtrade 1m-detail backtest on 6 non-overlapping windows
# Cross-validates the lab walk-forward result

cd "$(dirname "$0")"

windows=(
    "20230101-20230701 2023-H1"
    "20230701-20240101 2023-H2"
    "20240101-20240701 2024-H1"
    "20240701-20250101 2024-H2"
    "20250101-20250701 2025-H1"
    "20250701-20260415 2025-H2+2026"
)

echo "KeltnerBounceV1 — 6-window Freqtrade validation (1m detail)"
echo "============================================================"

for w in "${windows[@]}"; do
    range="${w%% *}"
    label="${w#* }"
    echo ""
    echo "── $label ($range) ──"

    output=$(docker run --rm \
        -v "$(pwd)/user_data:/freqtrade/user_data" \
        freqtradeorg/freqtrade:stable \
        backtesting \
        --strategy KeltnerBounceV1 \
        --timerange "$range" \
        --timeframe 1h \
        --timeframe-detail 1m \
        --config /freqtrade/user_data/configs/backtest-KeltnerBounceV1.json \
        --enable-protections \
        --export none \
        --no-color 2>&1)

    # Extract key metrics
    pnl=$(echo "$output" | grep "Total profit %" | head -1 | grep -oE '[-+]?[0-9]+\.[0-9]+')
    pf=$(echo "$output" | grep "Profit factor" | head -1 | awk -F '│' '{print $3}' | xargs)
    trades=$(echo "$output" | grep "Total/Daily Avg Trades" | head -1 | awk -F '│' '{print $3}' | awk '{print $1}' | cut -d'/' -f1)
    wr=$(echo "$output" | grep "KeltnerBounceV1" | grep -oE '[0-9]+\.[0-9]+ │' | tail -1 | tr -d '│' | xargs)
    dd=$(echo "$output" | grep "Absolute drawdown" | head -1 | awk -F '│' '{print $3}' | xargs)

    echo "  Trades: $trades | P&L: $pnl% | PF: $pf | DD: $dd"
done

echo ""
echo "============================================================"
echo "DONE"
