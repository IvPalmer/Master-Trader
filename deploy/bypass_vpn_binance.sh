#!/bin/bash
# Bypass VPN for Binance API traffic
# Adds /24 CIDR routes for all Binance endpoints through real gateway
# Run with: sudo ./bypass_vpn_binance.sh

set -euo pipefail

GATEWAY=$(netstat -rn | grep "^default" | grep -v "utun" | head -1 | awk '{print $2}')
IFACE=$(netstat -rn | grep "^default" | grep -v "utun" | head -1 | awk '{print $NF}')

if [ -z "$GATEWAY" ] || [ -z "$IFACE" ]; then
    echo "ERROR: Could not detect non-VPN gateway. Is WiFi connected?"
    exit 1
fi

echo "Real gateway: $GATEWAY via $IFACE"

if ! netstat -rn | grep -q "^0/1.*utun"; then
    echo "VPN not detected. No bypass needed."
    exit 0
fi

echo "VPN detected. Adding Binance bypass routes..."

HOSTS="api.binance.com api1.binance.com api2.binance.com api3.binance.com fapi.binance.com dapi.binance.com data.binance.com stream.binance.com ws-api.binance.com"
ADDED=0
CIDRS_FILE=$(mktemp)

# Collect unique /24 CIDRs from host DNS
for host in $HOSTS; do
    dig +short "$host" | grep -E '^[0-9]+\.' | sed 's/\.[0-9]*$/.0/' >> "$CIDRS_FILE" 2>/dev/null || true
done

# Also collect from Docker DNS (resolves differently)
for host in api.binance.com fapi.binance.com data.binance.com; do
    docker exec ft-bollinger-rsi python3 -c "import socket; print(socket.getaddrinfo('$host', 443)[0][4][0])" 2>/dev/null | sed 's/\.[0-9]*$/.0/' >> "$CIDRS_FILE" || true
    docker exec ft-cluchanix python3 -c "import socket; print(socket.getaddrinfo('$host', 443)[0][4][0])" 2>/dev/null | sed 's/\.[0-9]*$/.0/' >> "$CIDRS_FILE" || true
done

# Deduplicate and add /24 routes
for cidr in $(sort -u "$CIDRS_FILE"); do
    NETWORK="${cidr}/24"
    if netstat -rn | grep -q "${cidr}.*${IFACE}"; then
        echo "  Route exists: $NETWORK"
    else
        route -n add -net "$NETWORK" "$GATEWAY" 2>/dev/null && \
            echo "  Added: $NETWORK -> $GATEWAY" && \
            ADDED=$((ADDED + 1)) || \
            echo "  Failed: $NETWORK"
    fi
done

rm -f "$CIDRS_FILE"
echo ""
echo "Added $ADDED new /24 routes."

# Verify
echo ""
echo "Testing connectivity..."
for endpoint in "api.binance.com/api/v3/ping" "fapi.binance.com/fapi/v1/ping"; do
    code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "https://$endpoint" 2>/dev/null || echo "000")
    echo "  $endpoint: HTTP $code"
done

docker_code=$(docker run --rm --entrypoint curl freqtradeorg/freqtrade:stable -s -o /dev/null -w "%{http_code}" --connect-timeout 5 https://api.binance.com/api/v3/ping 2>/dev/null || echo "000")
echo "  Docker -> api.binance.com: HTTP $docker_code"

if [ "$docker_code" = "200" ]; then
    echo ""
    echo "SUCCESS - restart blocked bots: docker compose restart cluchanix bollingerrsimeanreversion"
else
    echo ""
    echo "STILL BLOCKED - CloudFront may use IPs outside added CIDRs."
    echo "Check: dig +short api.binance.com and add those /24s manually."
fi
