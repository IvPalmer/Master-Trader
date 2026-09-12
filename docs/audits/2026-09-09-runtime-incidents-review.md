# Review operacional — 2026-09-09

Inspeção entre 20:11 e 20:18 UTC (17:11–17:18 de Brasília). Escopo: estado
de produção, logs, banco do receiver em modo somente leitura e código do
dashboard/receiver. Nenhum bot foi reiniciado, nenhuma ordem foi enviada e
nenhuma configuração de trading foi alterada.

## Estado observado

Os seis containers estão saudáveis e os seis `/show_config` respondem com
`state=running`. O dashboard responde com `errors={}`, nenhum bot stale e
`status.level=green`.

| Bot | Modo | Posições abertas |
| --- | --- | --- |
| FundingFade | live | 0 |
| KeltnerBounce | live | 0 |
| Killers | live | DOT e GRAM |
| OITrendPullback | dry-run | 0 |
| ShortKeltner | dry-run | 0 |
| Insiders | dry-run | 0 |

O offline relatado não foi reproduzido. A sessão do navegador disponível
exige login no Cloudflare Access; a investigação continuou pela conexão SSH
autorizada ao VPS. Não há evidência suficiente para atribuir o offline a um
bot específico ou à sessão do navegador.

## Achados por prioridade

### P1 — Take-profits incompatíveis com o tamanho das posições

`services/killers-receiver/app/main.py:2630` divide a quantidade igualmente
pelo número de alvos sem validar o tamanho mínimo e a precisão de cada saída.
No GRAM, 11 unidades / 8 alvos geraram uma parcela de 1,375. O Freqtrade
arredondou para 1 unidade a 1,425 e a Hyperliquid rejeitou a ordem:
`Order must have minimum value of $10` (19:01:28 UTC).

O banco do receiver confirma:

- DOT, posição 3 / trade 1: primeiro alvo rejeitado desde 29/08, oito pendentes,
  nenhum ativo ou preenchido.
- GRAM, posição 8 / trade 2: primeiro alvo rejeitado em 09/09, sete pendentes,
  nenhum ativo ou preenchido.

O motivo detalhado do erro antigo do DOT não foi recuperado; o HTTP 500 e a
escada parada estão comprovados. Os snapshots de ambos no Freqtrade contêm
apenas a entrada preenchida e uma ordem de stop aberta, com zero saídas.

Correção necessária: planejar parcelas executáveis usando quantidade realmente
preenchida, precisão e mínimo da corretora. A definição de como consolidar
alvos precisa preservar a política de saída aprovada, sem aumentar a exposição
para acomodar ordens pequenas.

### P1 — Rejeição inicial deixa a sequência de alvos sem recuperação

`services/killers-receiver/app/main.py:1124` torna qualquer falha de colocação
terminal (`rejected`). O reconciliador em `:1268` só consulta alvos `active` e
retorna imediatamente quando não encontra nenhum. Portanto, a primeira falha
deixa os alvos seguintes pendentes indefinidamente no processamento periódico.

Correção necessária: distinguir falhas transitórias de ordens inválidas,
reconciliar primeiro a existência de uma ordem real antes de repetir uma
tentativa e expor escadas sem saída ativa como falha operacional. Não repetir
automaticamente uma ordem abaixo do mínimo nem rearmar cancelamentos manuais.

### P1 — Saúde verde não representa a capacidade de gerenciar ordens

Os logs do Killers registram `RateLimitExceeded`/HTTP 429 em várias janelas nas
seis horas examinadas. Às 20:01:57 e 20:01:59 UTC há avisos `Unable to exit
trade` para DOT e GRAM por falha em `fetch_order`. Isso comprova degradação do
caminho de gerenciamento de ordens, sem comprovar que uma venda específica
foi solicitada e deixou de executar.

O receiver também falhou ao buscar os preços dessas posições. Insiders e o
container antigo `ft-short-keltner-hl` registram 429 no período. Concorrência
entre clientes é uma hipótese a medir; a origem exata da saturação não foi
estabelecida nesta revisão.

Apesar disso, `ft_userdata/ft_dashboard/app.py:1480` considera principalmente
recência da API local e integridade do banco. O `/healthz` do receiver em
`services/killers-receiver/app/main.py:1736` sempre retorna `ok=true`.
Consequentemente, o dashboard não expõe nem a escada travada nem essa
degradação da exchange no estado geral.

Correção necessária: agregar falhas recentes de execução, atualização de
preços e estado dos alvos à saúde operacional; medir chamadas e aplicar
limitação compartilhada/backoff aos clientes que competem pelo acesso.
Manter liveness separado de readiness operacional.

Os dois stops aparecem ativos no registro de ordens do Freqtrade. Esta revisão
não consultou a corretora diretamente para reconfirmar sua existência.

### P2 — Painel informa realização inexistente no GRAM

`ft_userdata/ft_dashboard/app.py:1301` passa `amount_requested` como base para
`compute_booked_pct`. Esse número é a quantidade solicitada, não necessariamente
a quantidade preenchida após arredondamento. O GRAM pediu 11,40656786 unidades
e recebeu 11; a fórmula em `:291` transforma a diferença em `booked_pct=3.6`.
O Freqtrade confirma `nr_of_successful_exits=0`, `realized_profit=0` e entrada
preenchida de 11 unidades.

Correção necessária: calcular realização a partir de entradas e saídas
efetivamente preenchidas. O limiar fixo de 0,5% para dust não cobre esse caso.

### P2 — Avisos informativos contam como incidentes ativos

Executando o controlador JavaScript com o snapshot atual de produção,
`_rawIncidents` retorna exatamente três itens azuis: Insiders, OI e ShortKeltner
em observação sem baseline. A condição em
`ft_userdata/ft_dashboard/static/dashboard.js:364` independe de qualquer falha.
O template em `ft_userdata/ft_dashboard/templates/index.html:91` conta todos
esses itens como `active incidents`.

Correção necessária: separar informações de pesquisa/simulação dos incidentes
acionáveis e aplicar severidade coerente ao resumo.

### P2 — Falha de atualização preserva um offline antigo sem explicar a causa

`ft_userdata/ft_dashboard/static/dashboard.js:132` ignora respostas HTTP não-OK
e apenas registra exceções no console. O último snapshot permanece na tela.
Uma reprodução isolada com um snapshot offline seguido de HTTP 401 mantém o
mesmo bot offline, sem estado próprio de falha de autenticação/atualização.

Isso é um defeito reproduzido, mas não prova a causa do offline relatado pelo
operador. Correção necessária: exibir idade e erro da última atualização,
separar desconexão do dashboard de indisponibilidade do bot e encaminhar
expiração de sessão para reautenticação.

## Validação e limites

- SHA-256 do dashboard Python, JavaScript e receiver: iguais entre o clone
  local e os arquivos executados nos containers.
- Suite existente do dashboard: **41 testes passaram**, executada a partir
  de `ft_userdata/ft_dashboard`. A primeira tentativa na raiz falhou na coleta
  porque `StaticFiles` resolve `static` relativamente ao diretório corrente.
- Controlador JavaScript executado em Node com snapshot real: confirmou os
  três falsos incidentes e os seis estados `running`.
- Simulação de HTTP 401 confirmou preservação do snapshot offline antigo.
- Leitura do receiver via SQLite `mode=ro` e inspeção de `/status` confirmaram
  os alvos rejeitados, ausência de take-profits ativos e zero saídas.
- Os 41 testes existentes não cobrem os casos de produção descritos acima.
- Não houve deploy, correção de código executável, mudança de modo, alteração
  de estratégia, reinício ou intervenção em posições nesta review.
