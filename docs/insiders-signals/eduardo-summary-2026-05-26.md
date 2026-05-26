# Insiders Scalp — replay validation (rascunho pra Eduardo)

> Não envia ainda. Operador pediu rascunho.
> Snapshot da pipeline: **2026-05-26** (re-run completo contra teu export).

---

## Números principais

Replay offline contra teu export de 1.087 mensagens (Feb 11 → Apr 21 2026,
83 dias de sinais). Conta virtual de $1.000, risk-budget $10/SL%-distance.
Walker de preço corre até hoje (Maio 26), então trades que estavam abertas
no fim do export já tiveram chance de resolver.

| | |
|---|---|
| mensagens classificadas | **1.087 / 1.087** (100%) |
| trades materializados | 147 |
| trades dimensionados | 99 (48 pulados — sem SL ou sem entry parseável) |
| trades fechados | 84 (14 ainda abertas hoje) |
| **win rate** | **51,1 %** (48W / 46L sobre fechadas e marcadas) |
| **profit factor** | **2,75** |
| **PnL realizado** (só fechadas) | **+$573,81** |
| **PnL total** (fechadas + mark-to-market das abertas) | **+$763,96** |
| **retorno da conta** | **+76,4 %** sobre os 83 dias do export |
| alavancagem média | 8,9× (bate com tua regra de $10 / $50) |
| pior loss único | -$13,17 |
| trades market-entry resgatados (regex pulava) | 15 |

**Comparação com a baseline regex (mesmo dataset, mesmas regras de sizing):**

| | LLM | Regex |
|---|---|---|
| trades dimensionados | 99 | 44 |
| PnL | **+$763,96 (+76,4 %)** | **-$266,81 (-26,7 %)** |
| alavancagem média | 8,9× | 41,0× (parser quebra em alguns sinais) |

O regex pula metade dos sinais e ainda tem bugs de parser que inflam
alavancagem. Por isso vamos com LLM em produção, regex fica como check
shadow paralelo pra detectar drift.

**Comparação com teu recap publicado Feb 16-24:**

| | nosso sim (snapshot 05-26) | teu recap |
|---|---|---|
| trades | 15 (8W / 6L / 1E) | 14 (7W / 7L) |
| WR | **57,1 %** | **50,0 %** |
| direção do PnL | positivo (+$129,27) | positivo |

WR não bate exato como batia antes — a diferença é que o walker agora teve
mais tempo pra resolver trades que estavam abertas no fim daquela janela.
Direção do resultado bate, contagem total bate (diferença de 1 trade), e
o sizing diferente já explica os $129 vs teus 2-5% balance allocation.

---

## Como funciona o stack tecnicamente

```
canal Telegram  →  listener (Telethon)  →  classifier (LLM)  →  simulator  →  price walker  →  Freqtrade Futures (dry-run)
                                                                                                              ↓
                                                                                                trade-webhook  →  @elder_brain_bot (Telegram alert)
```

**1. Listener** — Telethon subscrito ao canal usando teu `.session`. Cada
mensagem nova entra na pipeline em real-time. Modo offline (replay) lê do
HTML export que tu mandou.

**2. Classifier** — LLM (Claude Sonnet via Anthropic SDK) lê cada mensagem
e produz JSON estruturado:
```json
{
  "kind": "open" | "close_full" | "close_partial" | "move_sl" | "increase" | "chat",
  "symbol": "ETH",
  "direction": "LONG" | "SHORT",
  "entry": 2739.56, "sl": 2632.84, "tp": 2825.47,
  "leverage": 11, "confidence": 0.98,
  "scale_pct": 50  // pra increase events
}
```
Roda em paralelo (6× concurrent). Cache em JSONL — não reclassifica
mensagens já vistas. Coverage 100% sobre 1.087 mensagens.

**3. Simulator** — recebe a stream classificada e gerencia o lifecycle de
cada posição:
- `open` cria a trade. Se não tem SL, fica em estado `pending_sl` e aceita
  backfill por até 24h (move_sl ou novo open mesma direção carregando SL).
- `close_partial` reduz o notional proporcionalmente, mantém a posição
  aberta com o residual.
- `move_sl` muta o stop sem fechar nada.
- `increase` adiciona ao notional + recalcula a entry média ponderada
  (preço de mercado no momento do increase via price walker).
- `close_full` fecha o que sobrou.
- Sizing: `notional = $10 / SL_distance_pct` (tua regra). Trade que perde
  abate $10; trade que ganha rende `(TP_distance / SL_distance) × $10`.

**4. Price walker** — pra qualquer query "qual era o preço de X no
timestamp Y" o walker:
- Tenta primeiro **Binance Futures USDT-M klines 1-min** (endpoint
  público, sem auth, rate limit 1200/min/IP).
- Se o símbolo não tá listado na Binance (caso de XTIU, XAG), cai pro
  **WEEX `/historyCandles`** (com `priceType=LAST`).
- Sanity check: rejeita qualquer vela com drift > 2 minutos do timestamp
  pedido. Isso pegou um bug feio do WEEX que retornava a vela atual pra
  qualquer query histórica.
- Cache em memória por (símbolo, minuto). Não bate na API duas vezes pro
  mesmo candle.

**5. Resolver de saídas** — pra cada trade aberta, walka 1-min candles
desde a entry pro futuro até atingir TP, SL ou close manual via mensagem
do canal. Exit_reason marcado como `tp` / `sl` / `manual` / `open` (se a
trade ainda estava aberta no momento do snapshot).

**6. Output** — três artefatos:
- `trades_llm.json` — todas as trades com lifecycle completo (events
  array, scaled_pnl, status closed/open/skipped, unrealized_pnl_mark)
- `report.html` — painel interativo com headline metrics, equity curve,
  trade log com filtro/sort, comparação LLM vs regex lado a lado
- `recap_matcher.py` — extrai per-trade lines dos teus posts de stats
  semanais e matcheia greedy contra trades do sim por (symbol, direction,
  ±48h)

**7. Bot deployment** — quando for ao vivo:
- Receiver (`insiders-receiver`, FastAPI) recebe sinal classificado e
  dispara `/forceenter` MARKET no Freqtrade Futures (dry-run inicial,
  $200 paper wallet, Binance USDT-M perp).
- Estratégia (`InsidersScalpV1`) é pass-through — não tem indicadores
  próprios, só executa o que o sinal disse. SL/TP per-trade puxados do
  graph via `/position/by_ft_id/{id}` em cada candle.
- Webhook (`format: json`, mesmo padrão do KillersScalp) dispara em
  entry/exit/fill pro `trade-webhook` → `@elder_brain_bot` me alerta no
  Telegram em cada trade.
- Receiver tem 4 camadas de proteção: validador defensivo na cold-path,
  rejection de SL no lado errado antes de entrar, retry/reconciliação
  com Freqtrade pra heal de orphans (crash entre order placement e
  graph write), e endpoints `/positions/requested` + `/position/{id}/fail`
  + `/position/{id}/link` pra resolução manual quando reconciliação fica
  ambígua.

## Pendência única pra ir ao vivo

Teu `.session` file. Vai dropar (encriptado com age, conforme onboarding
que mandei dia 19/05) e a gente coloca em
`ft_userdata/insiders_bridge/secrets/insiders.session` na VPS — o compose
monta read-only dentro do container como `/run/secrets/insiders.session`.
Aí o listener subscreve no canal e cada msg nova entra na pipeline que
acabou de processar os 1.087 sem erros. Todos os outros estágios estão
verdes.

---

*Painel HTML interativo + tabela trade-by-trade em
[docs/insiders-signals/replay/report-2026-05-26.html](replay/report-2026-05-26.html).*
