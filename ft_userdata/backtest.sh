#!/bin/bash
# Backtest wrapper with VPN bypass (passes extra_hosts from docker-compose)
# Usage: ./backtest.sh --strategy ClucHAnix --config user_data/configs/backtest-ClucHAnix.json --timerange 20260201-20260312

IMAGE="freqtradeorg/freqtrade:stable"

# Check if strategy needs FreqAI image
for arg in "$@"; do
    if [[ "$arg" == "MasterTraderAI" ]]; then
        IMAGE="freqtradeorg/freqtrade:stable_freqai"
        break
    fi
done

docker run --rm \
    --add-host "api.binance.com:13.226.219.154" \
    --add-host "api1.binance.com:13.226.219.154" \
    --add-host "api2.binance.com:13.226.219.154" \
    --add-host "api3.binance.com:13.226.219.154" \
    --add-host "fapi.binance.com:108.138.85.11" \
    --add-host "dapi.binance.com:13.226.219.154" \
    --add-host "data.binance.com:13.226.219.154" \
    --add-host "stream.binance.com:13.112.187.8" \
    -v /Users/palmer/ft_userdata/user_data:/freqtrade/user_data \
    "$IMAGE" \
    backtesting "$@"
