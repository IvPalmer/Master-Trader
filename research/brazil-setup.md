# Brazil-Specific Setup Guide

## Regulatory Landscape

### CVM (Comissão de Valores Mobiliários)
- Automated trading on B3 is legal but regulated
- No specific prohibition on retail algo trading
- HFT firms need CVM registration
- Crypto is not regulated as a security (yet)

### Banco Central
- Crypto exchanges operating in Brazil must register (Marco Legal das Criptomoedas, Lei 14.478/2022)
- Foreign exchange regulations apply to moving money to international brokers
- IOF tax on international remittances (0.38% for investments)

### Receita Federal (Tax Authority)
- **Crypto:** Monthly DARF payment on gains over R$35K/month (15-22.5%)
- **US Stocks:** 15% on gains (no monthly exemption), paid via DARF
- **B3 Stocks:** 15% on swing trades, 20% on day trades
- **Monthly exemption for B3 only:** R$20K/month in sales (not gains)
- **Carnê-Leão:** Monthly tax collection for foreign income

## Recommended Setup for Brazilian Trader

### Path 1: Crypto Trading (Recommended Start)

**Why crypto first:**
- No minimum capital
- 24/7 markets = bot runs continuously
- Best open-source ecosystem (Freqtrade)
- Binance fully accessible from Brazil
- BRL deposit/withdrawal via Pix on Binance
- Tax only above R$35K/month in sales

**Setup:**
1. Binance account (use Binance.com, not Binance Brazil for full API)
2. Freqtrade running locally or on VPS
3. Start with paper trading (dry-run mode)
4. Small live capital (R$500-2000 to start)

**Tax handling:**
- Track all trades (Freqtrade exports trade history)
- Use Koinly or CoinTracker for tax reports
- Monthly: check if sales exceeded R$35K, pay DARF if needed
- Annual: declare in DIRPF under "Bens e Direitos"

### Path 2: US Stocks via IBKR/Alpaca

**Setup:**
1. Open IBKR or Alpaca international account
2. Fund via international wire (IOF 0.38%)
3. Use QuantConnect cloud or local Lean engine
4. Consider timezone: US market hours = 10:30-17:00 BRT

**Tax handling:**
- 15% on capital gains (no minimum exemption for foreign stocks)
- Pay monthly via DARF (code 0473)
- Convert USD gains to BRL using PTAX rate on transaction date
- Declare in DIRPF under "Bens e Direitos no Exterior"

### Path 3: B3 (Brazilian Market)

**Setup:**
1. Broker with MetaTrader 5 or Profit Pro (Clear, Rico)
2. Expert Advisors (MQL5) for automation
3. Limited API access compared to US/crypto

**Not recommended as primary** due to limited automation tools and API access.

## Infrastructure from Brazil

### VPS Options
- **For crypto:** Any VPS works (latency is not critical for most strategies)
  - DigitalOcean São Paulo region
  - AWS sa-east-1 (São Paulo)
  - Contabo (cheap, decent)
  - Cost: ~$5-20/month

- **For US stocks:** Consider US-East VPS
  - AWS us-east-1
  - Vultr New Jersey
  - Cost: ~$10-30/month

### Internet Considerations
- Home internet in Brazil is generally sufficient for non-HFT
- Consider a secondary connection (4G failover) for live trading
- Most ISPs provide 100Mbps+ which is more than enough

## Money Flow

### Funding Crypto Trading
- **Pix to Binance:** Instant, free or minimal fees
- **Pix to other exchanges:** Via Mercado Bitcoin, Foxbit, etc.
- No IOF on crypto purchases

### Funding US Brokerage
- **Remessa Online / Wise / Avenue:** Lower fees than bank wire
- **Direct bank wire:** Higher fees but reliable
- **IOF:** 0.38% on all outbound remittances
- **Spread:** Watch the USD/BRL spread carefully

## Quick Start Recommendation

```
Week 1:  Set up Freqtrade locally, learn the framework
Week 2:  Backtest 3-5 strategies on BTC/USDT and ETH/USDT
Week 3:  Paper trade the best strategy on Binance testnet
Week 4:  Go live with R$500-1000
Week 5+: Iterate, monitor, adjust
```

## Essential Tools
- **Freqtrade:** Trading bot
- **FreqUI:** Web dashboard for Freqtrade
- **Koinly:** Crypto tax reporting (supports Brazilian tax rules)
- **TradingView:** Charting and analysis
- **Telegram:** Bot alerts and monitoring
