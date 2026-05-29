# Hyperliquid $100 live go-live runbook — ShortKeltnerV2HL

**Status:** prepped, NOT live. This is a **plumbing / execution test**, not an alpha
test — at ~22 trades/yr it will NOT prove profitability; it proves the bot can trade
HL for real (fills, stops, funding, withdrawal). Treat the ~$100 as **tuition, written
off on day one.** Max loss = whatever USDC you fund (isolated margin).

Codex stance: no-capital-until-forward-test; this overrides that as a *deliberate,
capped execution test*. Sizing/whitelist below reflect HL reality (most of the 20
Binance pairs are thin on HL — live set is the 6 liquid names).

## What's DONE (by Claude — no money/keys involved)
- Live config template committed: `ft_userdata/user_data/configs/ShortKeltnerV2HL-live.json`
  (dry_run=false, **empty keys**, liquid-6 whitelist, stake $45 × max 2 @ 2x isolated,
  stoploss_on_exchange=true). Inert until you add keys on the VPS.
- Strategy `ShortKeltnerV2HL` already validated to boot + run on HL (dry-run live now).
- Dashboard already shows the HL bot.

## What's YOURS (money / account / keys — Claude is guard-railed out, and a wrong
## address/key is irreversible, so these MUST be you):

### 1. Self-custody wallet
Install a wallet you control (Rabby or MetaMask). **You hold the seed phrase. Never
share it, never put the seed/master key anywhere near the VPS.**

### 2. Get USDC onto Hyperliquid (~$100)
- Hyperliquid runs on its own L1; deposits come via **Arbitrum USDC**.
- Buy/transfer ~$100 USDC to your wallet on Arbitrum, then deposit to HL at
  https://app.hyperliquid.xyz (Deposit → it bridges Arbitrum USDC → HL).
- Start with exactly what you'll risk. Don't park extra on HL.

### 3. Create an HL **API/agent wallet** (the key the bot uses)
- In the HL app: **More → API** (or "API Wallets" / "Agent Wallets").
- Generate an agent wallet. It returns a **private key**. This key can **place/cancel
  orders but CANNOT withdraw** — that's the whole point (if the VPS key leaks, funds
  can't be stolen, only mis-traded, capped by your $100 isolated margin).
- Note your **main account address** (public, starts 0x...) AND the **agent private key**.

### 4. Put the keys on the VPS (NOT in git)
SSH to the VPS, copy the template into the bot's data dir (which is NOT a git repo),
and fill the two fields:
```
ssh ubuntu@100.96.225.124
cp ~/master-trader/ft_userdata/user_data/configs/ShortKeltnerV2HL-live.json \
   ~/hl_validation/user_data/configs/ShortKeltnerV2HL-live.json
nano ~/hl_validation/user_data/configs/ShortKeltnerV2HL-live.json
#   set  "walletAddress": "0xYOUR_MAIN_HL_ADDRESS"
#   set  "privateKey":    "0xYOUR_AGENT_WALLET_KEY"
chmod 600 ~/hl_validation/user_data/configs/ShortKeltnerV2HL-live.json
```

### 5. Flip it live (replaces the dry-run container, same name/port)
```
# fetch the dashboard API creds so the dashboard keeps polling it
U=$(sudo docker exec ft-dashboard printenv FREQTRADE__API_SERVER__USERNAME)
P=$(sudo docker exec ft-dashboard printenv FREQTRADE__API_SERVER__PASSWORD)
sudo docker rm -f ft-short-keltner-hl                 # stop the dry-run
sudo docker run -d --restart unless-stopped --name ft-short-keltner-hl --memory 1g \
  -e FREQTRADE__API_SERVER__USERNAME="$U" -e FREQTRADE__API_SERVER__PASSWORD="$P" \
  -p 127.0.0.1:8101:8080 \
  -v /home/ubuntu/hl_validation/user_data:/freqtrade/user_data \
  freqtradeorg/freqtrade:stable \
  trade --strategy ShortKeltnerV2HL \
        --config /freqtrade/user_data/configs/ShortKeltnerV2HL-live.json
sudo docker network connect compose-bypass-mobile-port-fbk1m6_default ft-short-keltner-hl
# confirm it authenticated + sees your balance:
sleep 20; sudo docker logs ft-short-keltner-hl 2>&1 | grep -iE "balance|dry|error|exchange" | tail
```
If logs show a real USDC balance and no auth error → it's live.

### 6. First-trade + withdrawal test (the actual point)
- Wait for the first real fill (sparse — gated to BTC<200d-MA, only 6 pairs; could be
  days). Confirm: entry fills at a sane price, the protective stop appears on HL, funding
  debits look right.
- After a trade or two, **test a withdrawal** of ~$10 USDC HL→Arbitrum→your wallet, to
  prove the exit path before trusting HL with anything.

### Kill switch
```
sudo docker rm -f ft-short-keltner-hl    # stops trading immediately (open positions
                                          # stay on HL — close them in the HL app)
```

## Caveats (eyes open)
- **Not an alpha test.** Won't prove profit. Plumbing only.
- **HL stops are limit (no market orders)** → in a fast move a stop may not fill; isolated
  margin + $100 caps the worst case.
- **Universe mismatch:** live runs 6 liquid HL pairs vs the 20-pair Binance backtest → HL
  results are NOT comparable to the +27.86% number.
- **BR tax/legal:** HL perps are derivatives (CVM scope) + Receita reporting applies. Self-
  custody ≠ invisible. Get advice before scaling beyond the test.
- **Hot key:** agent key on the VPS can mis-trade the sub-account to zero (not withdraw).
  Keep only the test amount on HL; never the master key on the box.
