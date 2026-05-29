# Hyperliquid $100 live go-live runbook — ShortKeltnerV2HL

**Status:** prepped, NOT live. This is a **plumbing / execution test**, not an alpha
test — at ~22 trades/yr it will NOT prove profitability; it proves the bot can trade
HL for real (fills, stops, funding, withdrawal). Treat the ~$100 as **tuition, written
off on day one.** Max loss = whatever USDC you fund (isolated margin).

Codex stance: no-capital-until-forward-test; this overrides that as a *deliberate,
capped execution test*. Whitelist = **11 liquid pairs** (BTC/ETH/SOL/XRP/SUI/NEAR/DOGE/
BNB/LINK/AVAX/ADA). Entries fill fine on any HL alt at ~$90 notional, but a forced
EXIT/stop during a squeeze needs depth — so restricted to liquid names (codex). Excludes
ZEC (HL squeeze anomaly, risky to short) + the thin alts.

## ⭐ RECOMMENDED FIRST: testnet (free) — makes the $100 mostly redundant (codex)

HL has a full **testnet** + faucet (1,000 mock USDC / 4h). Freqtrade/ccxt supports it
(`exchange.sandbox: true`). This tests the execution mechanics for **free**, so the $100
mainnet run is mostly redundant as a plumbing test.

**Testnet PROVES:** auth + agent-key signing, order accept/reject, min-size/precision/
leverage/isolated-margin rules, stop placement→trigger→fill *mechanics*, cancel/replace,
force-exit, rate-limits.
**Testnet does NOT prove:** mainnet book depth, real slippage, **real stop-fill in a
squeeze**, real funding magnitude, liquidation path.
**⚠️ Single caveat (codex):** "stop filled on testnet" ≠ a stop-limit will save a short
alt on mainnet. Testnet = mechanics; mainnet liquidity-under-stress is unproven by it.

### Minimal no-/low-capital sequence (codex)
1. Create a **dedicated wallet** (only for this).
2. **Tiny mainnet deposit (~$10), then withdraw most back** → this IS the custody test
   (≈$1 fee / ~5 min) AND unlocks the faucet. Use the SAME address for the faucet. No bot.
3. Claim **1,000 mock USDC** at https://app.hyperliquid-testnet.xyz/drip
4. Create a **TESTNET agent wallet** (app.hyperliquid-testnet.xyz → API).
5. Put the testnet walletAddress + testnet agent key into the pre-placed testnet config
   `~/hl_validation/user_data/configs/ShortKeltnerV2HL-testnet.json` (sandbox=true,
   dry_run=false, force_entry_enable=true, BTC/ETH/SOL). chmod 600.
6. Launch the testnet bot:
```
U=$(sudo docker exec ft-dashboard printenv FREQTRADE__API_SERVER__USERNAME)
P=$(sudo docker exec ft-dashboard printenv FREQTRADE__API_SERVER__PASSWORD)
sudo docker run -d --name ft-short-keltner-hl-testnet --memory 1g \
  -e FREQTRADE__API_SERVER__USERNAME="$U" -e FREQTRADE__API_SERVER__PASSWORD="$P" \
  -p 127.0.0.1:8102:8080 \
  -v /home/ubuntu/hl_validation/user_data:/freqtrade/user_data \
  freqtradeorg/freqtrade:stable \
  trade --strategy ShortKeltnerV2HL --config /freqtrade/user_data/configs/ShortKeltnerV2HL-testnet.json
```
7. **Force tiny trades** + verify the full mechanic chain (force_entry_enable is on):
```
curl -s -u "$U:$P" -H "Content-Type: application/json" -X POST \
  http://127.0.0.1:8102/api/v1/forceenter -d '{"pair":"BTC/USDC:USDC","side":"short"}'
# then watch logs/HL-testnet: entry fill, stop placement, stop trigger+fill, cancel/replace,
# forceexit (market), precision/min-size logs.
```
8. **Only then** consider a one-trade mainnet micro test (BTC/ETH/SOL only) — the live
   config below. Don't deploy the autonomous 11-alt run on mainnet just to test plumbing.

### Testnet gotchas (don't be misled)
Testnet liquidity can be fake/thin/stale; fills can be false +/-; funding & liquidations
aren't economically meaningful; testnet asset IDs/keys are SEPARATE from mainnet.

---

## What's DONE (by Claude — no money/keys involved)
- Live config template committed: `ft_userdata/user_data/configs/ShortKeltnerV2HL-live.json`
  (dry_run=false, **empty keys**, 11-pair liquid whitelist, stake $45 × max 2 @ 2x isolated,
  **bot-managed market-simulated stops** — stoploss_on_exchange=false, stop/force/emergency
  exits = market). Inert until you add keys on the VPS.
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
- **Hardening (codex):** use a dedicated HL sub-account/account for this bot only; fund ONLY
  the test amount; **verify the agent key cannot withdraw** before funding more; rotate/delete
  the agent key when the test ends. Never the master seed/key on the VPS.

### 4. Put the keys on the VPS (NOT in git)
The live config is **already placed** (empty keys, chmod 600) at
`~/hl_validation/user_data/configs/ShortKeltnerV2HL-live.json` — it's NOT in git.
Just edit the two fields:
```
ssh ubuntu@100.96.225.124
nano ~/hl_validation/user_data/configs/ShortKeltnerV2HL-live.json
#   set  "walletAddress": "0xYOUR_MAIN_HL_ADDRESS"   (public — your HL account address)
#   set  "privateKey":    "0xYOUR_AGENT_WALLET_KEY"    (secret — the agent key from step 3)
# (already chmod 600; keep it that way)
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
- Wait for the first real fill (sparse — gated to BTC<200d-MA, 11 pairs; could be days).
- **STOP-FILL VERIFICATION — codex's go/no-go gate.** On the first live trade, confirm the
  stop actually *executes*: when the −5% stop triggers, the bot must submit a market-simulated
  exit that **fills** (not a dead limit sitting unfilled). Check the HL fills + bot logs. If a
  real adverse move does NOT produce a clean stop fill → STOP, do not add capital, rethink.
- Confirm entry fills at a sane price + funding debits look right.
- After a trade or two, **test a withdrawal** of ~$10 USDC HL→Arbitrum→your wallet, to
  prove the exit path before trusting HL with anything.

### Kill switch
```
sudo docker rm -f ft-short-keltner-hl    # stops trading immediately (open positions
                                          # stay on HL — close them in the HL app)
```

## Caveats (eyes open)
- **Not an alpha test.** Won't prove profit. Plumbing only.
- **HL has no native market orders** → stops/forced-exits use ccxt's market-simulation
  (aggressive limit, 5% cap). Stop is **bot-managed** (stoploss_on_exchange=false): if the
  bot/VPS is DOWN there's no protective order resting on HL — acceptable ONLY because isolated
  margin + the ~$100 wallet caps the worst case. The first-trade stop-fill check (step 6) is
  what proves the exit actually works.
- **Universe mismatch:** live runs 11 liquid HL pairs; HL prices/funding/liquidity differ
  from Binance → results are NOT comparable to the +27.86%.
- **BR tax/legal:** HL perps are derivatives (CVM scope) + Receita reporting applies. Self-
  custody ≠ invisible. Get advice before scaling beyond the test.
- **Hot key:** agent key on the VPS can mis-trade the sub-account to zero (not withdraw).
  Keep only the test amount on HL; never the master key on the box.
