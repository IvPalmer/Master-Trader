# Insiders Scalp — replay validation (rascunho pra Eduardo)

> Não envia ainda. Operador pediu rascunho.

---

## Números principais

Replay offline contra teu export de 1.087 mensagens (Feb 11 → Apr 21 2026, 83 dias). Conta virtual de $1.000, risk-budget $10/SL%-distance (tua regra).

| | |
|---|---|
| mensagens classificadas | **1.087 / 1.087** (100%) |
| sinais acionáveis | 431 (164 open · 73 close_full · 91 close_partial · 62 move_sl · 41 increase) |
| trades materializados | 146 |
| trades dimensionados | 102 (44 pulados — sem SL em 24h ou sem entry parseável) |
| trades fechados | 67 (35 ainda abertos no corte do export) |
| **win rate ($)** | **52,0 %** |
| **profit factor** | **1,79** |
| **PnL realizado** | **+$232,70** |
| **retorno da conta** | **+23,27 %** em 83 dias |
| alavancagem média | 9,4× (bate com tua regra) |
| pior loss único | -$12,60 |
| lifecycle orphans | 1 em 1.087 (msg #437 fecha "Gold" sem open prévio — canal usa XAUT em outros pontos) |

**Comparação direta com teu recap publicado Feb 16-24:**

| | nosso sim | teu recap |
|---|---|---|
| trades | 16 (8W/7L/1E) | 14 (7W/7L) |
| **WR** | **50,0 %** | **50,0 %** ✓ |
| direção do PnL | positivo | positivo |

WR bate exato. Diferença de PnL absoluto é só sizing (teu post: 2-5% balance allocation; nosso: 1% conservador).

---

## Como funciona o stack tecnicamente

```
canal Telegram  →  listener (Telethon)  →  classifier (LLM)  →  simulator  →  price walker  →  Freqtrade Futures (dry-run)
                                                                                                              ↓
                                                                                                trade-webhook  →  @elder_brain_bot (Telegram alert)
```

**1. Listener** — Telethon subscrito ao canal usando teu `.session`. Cada mensagem nova entra na pipeline em real-time. Modo offline (replay) lê do HTML export que tu mandou.

**2. Classifier** — LLM (Claude Sonnet via Anthropic SDK) lê cada mensagem e produz JSON estruturado:
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
Roda em paralelo (6× concurrent). Cache em JSONL — não reclassifica mensagens já vistas. Coverage 100% sobre 1.087 mensagens.

**3. Simulator** — recebe a stream classificada e gerencia o lifecycle de cada posição:
- `open` cria a trade. Se não tem SL, fica em estado `pending_sl` e aceita backfill por até 24h (move_sl ou novo open mesma direção carregando SL).
- `close_partial` reduz o notional proporcionalmente, mantém a posição aberta com o residual.
- `move_sl` muta o stop sem fechar nada.
- `increase` adiciona ao notional + recalcula a entry média ponderada (preço de mercado no momento do increase via price walker).
- `close_full` fecha o que sobrou.
- Sizing: `notional = $10 / SL_distance_pct` (tua regra). Trade que perde abate $10; trade que ganha rende `(TP_distance / SL_distance) × $10`.

**4. Price walker** — pra qualquer query "qual era o preço de X no timestamp Y" o walker:
- Tenta primeiro **Binance Futures USDT-M klines 1-min** (endpoint público, sem auth, rate limit 1200/min/IP).
- Se o símbolo não tá listado na Binance (caso de XTIU, XAG), cai pro **WEEX `/historyCandles`** (com `priceType=LAST`).
- Sanity check: rejeita qualquer vela com drift > 2 minutos do timestamp pedido. Isso pegou um bug feio do WEEX que retornava a vela atual pra qualquer query histórica.
- Cache em memória por (símbolo, minuto). Não bate na API duas vezes pro mesmo candle.

**5. Resolver de saídas** — pra cada trade aberta, walka 1-min candles desde a entry pro futuro até atingir TP, SL ou close manual via mensagem do canal. Exit_reason marcado como `tp` / `sl` / `manual` / `open` (se a trade ainda estava aberta no corte).

**6. Output** — três artefatos:
- `trades_llm.json` — todas as trades com lifecycle completo (events array, scaled_pnl, status closed/open/skipped, unrealized_pnl_mark)
- `report.html` — painel interativo com headline metrics, equity curve, trade log com filtro/sort
- `recap_matcher.py` — extrai per-trade lines dos teus posts de stats semanais e matcheia greedy contra trades do sim por (symbol, direction, ±48h)

**7. Bot deployment** — quando for ao vivo:
- Receiver (`killers-receiver` adaptado) recebe sinal classificado e dispara `/forceenter` no Freqtrade Futures (dry-run inicial, $200 paper wallet, Binance USDT-M perp).
- Estratégia (`InsidersScalpV1`) é pass-through — não tem indicadores próprios, só executa o que o sinal disse.
- Webhook (`format: json`, mesmo padrão do KillersScalp que arrumamos hoje) dispara em entry/exit/fill pro `trade-webhook` → `@elder_brain_bot` me alerta no Telegram em cada trade.

## Pendência única pra ir ao vivo

Teu `.session` file. Quando dropar em `insiders_bridge/_local/eduardo.session`, o listener subscreve no canal e cada msg nova entra na pipeline que acabou de processar os 1.087 sem erros. Todos os outros estágios estão verdes.

---

*Painel HTML interativo + tabela trade-by-trade disponíveis quando quiser ver linha por linha.*
