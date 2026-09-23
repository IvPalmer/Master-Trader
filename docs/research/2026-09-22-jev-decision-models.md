# Modelos de decisão rápida (Jev e afins) no master-trader

**Data:** 2026-09-22 · **Produzido por:** sessão Claude Code (elder-brain), com revisões independentes do Codex (Sol/high) em cada etapa · **Issues:** #62 (investigação), #74 (promoção), #64, #65

Ponto de partida: o **Jev** (TypeSafe, lançado 2026-09-15) é um modelo "System 1" que recebe estado não estruturado e perguntas tipadas e devolve decisões com probabilidade calibrada em 70–500ms, sem gerar texto. O Bernardo mandou o [jarrodwatts/jev-trader](https://github.com/jarrodwatts/jev-trader) como exemplo de uso em trading. A pergunta: onde a velocidade desse tipo de modelo cria valor aqui?

**Resposta curta:** não criou em nenhum lugar medido. O problema que ele parecia resolver — o `killers_bot` gastando 7,6s de Claude CLI por mensagem — foi resolvido **por regras**, que estão em produção. O jev-trader não funciona: nem com modelos abertos, nem por construção econômica.

---

## Parte 1 — Classificador do `killers_bot`

O `classifier.py` chama o `claude` CLI (~7,6s) para transformar cada mensagem do canal de sinais em JSON tipado. O `strict_open.py` já pulava o Claude em aberturas limpas; todo o resto pagava o hop.

### O que foi tentado

| abordagem | resultado | decisão |
|---|---|---|
| **Jev** | sem chave (early access) | não testado |
| **GLiNER2** zero-shot (encoder 205M, CPU) | extração boa (`direction` 99,7%), mas `kind` **23,6%**, colapsando tudo em `open`; confiança saturada em 1,00 no acerto e no erro | descartado — ferramenta em `killers_bot/tools/encoder_probe.py` |
| **Regras** (`killers_bot/rules_classifier.py`) | ver abaixo | **em produção** |

Todo campo numérico do schema aparece literalmente na mensagem (`sl` 87/87, `entry` 150/150, `tp` 36/36): nada precisa ser gerado, só escolhido. E o campo `notes` era gerado à toa — o simulador só extrai dele um percentual que já está no texto cru (236/236 idênticos).

### Medição — e a correção que ela exigiu

A primeira versão foi medida só na base viva (537 mensagens) e reportada a **99,4%**. Contra os rótulos do Claude para o **histórico completo do canal** (3.373 mensagens em `ft_userdata/insiders_bridge/out/classifications_killers_chunk*.jsonl`, entradas em `classify_input_killers.jsonl`) ela dava **94%** — e errava na direção cara: 66 fechamentos e 53 movimentos de stop devolvidos como `chat` ("nada a fazer"), porque mensagem sem cabeçalho era tratada como promo.

Correção: **recusar em vez de decidir** em toda ambiguidade (sem cabeçalho com vocabulário de ação, todos os alvos batidos, alvo atingido com instrução a mais, linha de alvo sem ✅, mensagem sem moeda). A revisão independente achou mais quatro buracos com contraexemplo concreto, todos fechados com teste.

| corpus | cobertura | concordância com o Claude |
|---|---|---|
| histórico (3.373) | 87,7% | **2.959/2.959 = 100%** |
| base viva (537) | 85,1% | 456/457 = 99,8% (a divergência é rótulo anterior a `signal_update`) |

Duas lições registradas:
- **A janela viva não mede formato antigo nem cauda.** O canal escrevia `TARGETS` sem dois-pontos até meados de 2024; só o histórico mostrou.
- **Concordância com o Claude é fidelidade de destilação, não correção.** Nas msgs 3627/3993, que cheguei a chamar de erro do Claude, ele seguia a spec do próprio prompt.

### Em produção (desde 2026-09-22, `vps-deploy` `812fd72`)

Ordem: `strict_open` (aberturas) → **regras** (`chat`, `close_partial`, `close_full` por stop) → Claude (resto). O Claude roda em shadow sobre o que a regra decide e grava divergência em `rule_shadow` (`primary_source = 'claude-shadow'`, `agree = 0`). Antes de ligar, verificado campo a campo contra o que o Claude produz hoje: `symbol` e `signal_id` idênticos em 1.055 fechamentos; `pct` nulo nos dois (o receiver fecha 50% no padrão). Rollback: `KILLERS_RULES_PRIMARY=0` no `killers_bot/.env` + restart do `killers-observer`.

---

## Parte 2 — jev-trader

**A proposta:** market-maker na Kuru (MON-USDC, Monad). A cada bloco (~300ms) pergunta ao Jev se o mid estará mais alto em 100 blocos (~30s) e posta uma ordem limite post-only do lado escolhido.

### Experimento

- Clone `b587759`, com uma classe `OssModel` com a **mesma interface, pergunta e critérios** do `JevModel` (`oss-model.patch`). Técnica do OpenJev: um LLM aberto (qwen3 4B via ollama, Mac Studio M1 Max) lê o estado; P(buy) sai dos logprobs dos candidatos `buy`/`sell`.
- **Dry-run ao vivo de 90 min** contra o livro real (RPC pública da Monad), gravando cada decisão com o estado exato: 2.505 decisões, 470 fills simulados, zero erros.
- **Laya** (`typed-decisions`, clone aberto com `choice` nativo) pontuado offline nos mesmos estados.
- Avaliação em **janelas independentes** — as de 30s se sobrepõem e inflariam a amostra.

### Resultado (172 janelas independentes de 30s)

| preditor | acerto | IC 95% | edge bps/trade | Brier |
|---|---|---|---|---|
| qwen3 4B (ao vivo) | 46,5% | 39–54% | −0,95 | 0,520 |
| Laya | 48,8% | 42–56% | −0,45 | 0,267 |
| mock do próprio repo | 51,2% | 44–59% | +1,06 | 0,350 |
| fluxo de taker / momentum | ~50,9% / 50,6% | — | ~0 | ~0,49 |

Nada se separa do acaso. P&L simulado com o qwen: −$0,36 em 90 min. O qwen é superconfiante (95% das probabilidades abaixo de 0,1 ou acima de 0,9), leva ~1,8s por decisão e segue o fluxo de taker, como o prompt manda — mas o fluxo não prevê nada nesta amostra. O Laya responde `sell` 97% das vezes.

**Defeito de desenho:** o estado inclui `allowed.buy/sell` (limite de posição) e o prompt diz que o lado proibido é forçado. Com a compra travada (43% das decisões) o qwen respondeu `sell` em 100% — lê a trava em vez de prever. Contaminaria o Jev real igualmente.

### Por que não funciona por construção: gás

Pelas configurações do próprio repo (limite 350k, base 100 + prioridade 2 gwei), cada cancela-e-recoloca custa **0,0357 MON ≈ 1,78 bps** de uma ordem de 200 MON, e o loop faz isso a cada decisão.

| | transações/h | custo/h |
|---|---|---|
| decidindo ~todo bloco (a proposta, com Jev) | ~11.900 | **~$11,25 de gás** |
| decidindo a cada ~6 blocos (qwen) | ~1.670 | ~$1,58 de gás |
| receita máxima de spread (314 fills/h × meio-spread 1,9 bps × $5,29) | — | **~$0,31** |

Gás ≈ 36× a receita máxima, antes de seleção adversa. **Um modelo mais rápido piora o resultado.** O dry-run não cobra gás — por isso a simulação parece quase empatar.

### O único sinal encontrado não se sustenta

Com desequilíbrio forte (|imb| > 0,3) o livro parecia prever 2–4s (~57% nas duas metades da rodada). Medido nas faixas gravadas, o sinal troca de direção conforme a distância do preço:

| faixa | ~2s, 1ª metade | ~2s, 2ª metade |
|---|---|---|
| 10 bps | 37,4% (z −3,4) — invertido | 40,8% (z −2,5) — invertido |
| 25 bps | 61,2% (z +5,3) | 53,3% (z +1,7) |
| 1% | 57,0% (z +2,2) | 56,6% (z +2,9) |

Não é monotônico: parece comportamento de algum provedor de liquidez específico numa janela de 90 min. E mesmo um sinal real de 0,2–0,8 bps não pagaria 1,78 bps de gás por mutação.

Redesenho sugerido na revisão, **não testado**: maker de duas pontas persistente que só mexe na ordem quando o estado muda, com veto por desequilíbrio decidido por modelo numérico em microssegundos. LLM ou Jev só acrescentam latência.

### Limites

O Jev real não foi testado (sem chave). Uma janela, um mercado, um regime; 172 janelas só excluem vantagens grandes (≳56–60%). O Laya rodou offline, não dentro do loop.

---

## Parte 3 — Onde decisão rápida tipo Jev poderia valer

| candidato | avaliação |
|---|---|
| Killers | resolvido por regras a 0ms |
| Monitor de listagem (`research/listing_short_forward`) | títulos templatados, polling de 60s, posição de horas — não é limitado por latência |
| Canal Insiders | único encaixe semântico real (texto livre, contexto de reply). Base viva, 2026-06-06 → 09-22: 4.990 mensagens classificadas, ~95% `chat`, **77 aberturas** (~0,7/dia). O canal é observacional; se os 7,6s do Claude pioram o preço de entrada de cada abertura **não foi medido** — é o primeiro experimento, antes de qualquer modelo |
| Veto de manchete para um market-maker (hack, depeg, delisting) | o caso em que semântica em menos de 1s faria diferença; rejeitado por ora — não há maker lucrativo nem corpus de manchetes alinhado a cotações |

**Regra que saiu disto:** entrada templatada → regra; estado de mercado → modelo numérico; linguagem ambígua e rara → o Claude CLI que já existe. Velocidade de modelo tipo Jev só vira alavanca se existir um maker lucrativo que precise de veto semântico por manchete.

---

## Reprodução

**Classificador:** `killers_bot/tools/eval_rules.py <corpus.json>` (dump de `classifications ⋈ raw_messages`), `killers_bot/tools/parse_telegram_export.py` (export HTML do Telegram Desktop), `killers_bot/tools/encoder_probe.py` (GLiNER2). Rótulos históricos em `ft_userdata/insiders_bridge/out/` no VPS. **Não versionar** dumps — é conteúdo de canal privado.

**jev-trader** (`2026-09-22-jev-trader/`):

```bash
git clone https://github.com/jarrodwatts/jev-trader && cd jev-trader
git checkout b587759 && git apply ../oss-model.patch && bun install
ollama pull qwen3:4b-instruct
MODEL=oss DRY_RUN=true RECORD_PATH=run.jsonl bun run src/index.ts   # sem chave; RPC pública
python eval_trader.py run.jsonl [laya_scores.jsonl]
python scan_imbalance.py run.jsonl
python laya_score.py run.jsonl laya_scores.jsonl questions.json    # pip install laya
```

Os estados gravados (~3,7 MB) não estão versionados; regeneram com o comando acima, em outra janela de mercado.
