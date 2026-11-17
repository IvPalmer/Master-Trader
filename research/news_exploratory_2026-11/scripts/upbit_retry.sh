#!/bin/bash
# re-fetch Upbit pages that came back as Cloudflare 1015, slowly with backoff
cd "$(dirname "$0")/.."
sleep 60
for p in $(seq 1 41); do
  f=data/upbit_p$p.json
  for att in 1 2 3 4 5; do
    if [ -s "$f" ] && [ "$(wc -c <"$f")" -gt 500 ]; then break; fi
    curl -s -A "Mozilla/5.0" "https://api-manager.upbit.com/api/v1/announcements?os=web&page=$p&per_page=20&category=trade" -o "$f"
    if [ "$(wc -c <"$f")" -gt 500 ]; then sleep 8; break; fi
    echo "page $p attempt $att rate-limited"; sleep $((30*att))
  done
done
echo DONE
