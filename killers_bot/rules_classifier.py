"""Classificador de regras para mensagens de gestao — extensao do `strict_open`.

`strict_open.py` cobre apenas OPENs limpos de moeda unica. Tudo o mais — alvo
atingido, stop atingido, promo, mudanca de plano — paga o hop de ~7,6s do
`claude` CLI. Os formatos do canal sao templatados o bastante para decidir a
maior parte disso por regra.

Contrato, igual ao do `strict_open`: retorna `None` em QUALQUER duvida, e o
chamador CAI PARA O CLAUDE. Nenhuma regra aqui adivinha.

Medido contra 3.910 mensagens rotuladas pelo Claude — o historico completo do
canal (3.373, rotulos de `ft_userdata/insiders_bridge/out/`) mais a base viva
(537) — em 2026-09-22 (#62):

    historico   decidiu 2.992/3.373 = 88,7%   concordancia 2.992/2.992 = 100%
    recente     decidiu   467/537   = 87,0%   concordancia   466/467   = 99,8%

A unica divergencia (msg 3520, `signal_update` que o rotulo guarda como
`chat`) e rotulo anterior a inclusao de `signal_update` no prompt — o exemplo
que o prompt atual usa para essa classe e aquela mesma mensagem.

Historia da medicao, para quem for mexer: a primeira versao foi medida so na
base viva e reportou 99,4%. Contra o historico, deu 94%, com os erros na
direcao cara — 66 fechamentos e 53 movimentos de stop chamados de `chat`,
porque "sem cabecalho de sinal" era tratado como promo. Tres correcoes, todas
no sentido de RECUSAR em vez de decidir:

  1. Sem cabecalho so e `chat` sem vocabulario de acao (`ACTION`). Recall de
     158/158 nas acoes sem cabecalho do historico.
  2. Todos os alvos batidos nao vira `close_full`: a spec do classificador
     define alvo atingido como `close_partial` e os rotulos variam. Ambiguo.
  3. Alvo atingido com instrucao a mais ("Move SL to entry", "Closed at SL")
     nao e `close_partial` limpo.

O que sobra para o Claude (~12%) e, por construcao, o que e ambiguo.
"""
import re
from typing import Optional, Tuple

# Cabecalho padrao do canal.
SIGID = re.compile(r"SIGNAL\s*ID\s*:\s*#?(\d+)", re.I)
COIN = re.compile(r"COIN\s*:\s*\$?([A-Z0-9]{1,15})\s*/\s*USDT?", re.I)
# Formato GEM: cabecalho proprio, sem SIGNAL ID, ticker no titulo.
GEM = re.compile(r"GEM\s*SIGNAL\s*:\s*[#$]?([A-Z0-9]{1,15})", re.I)

ENTRY = re.compile(r"^\s*ENTRY\s*:", re.I | re.M)
# Dois formatos historicos. O atual escreve `TARGETS: a - b - c` numa linha.
# O antigo (ate meados de 2024) escreve `TARGETS` sozinho, com os alvos nas
# linhas `Short Term:` / `Mid Term:` abaixo.
TARGETS = re.compile(r"^\s*TARGETS?\s*:|^\s*TARGETS?\s*$", re.I | re.M)
# GEM escreve `SL:`; o formato padrao escreve `STOP LOSS:`.
STOPLOSS = re.compile(r"^\s*(STOP\s*LOSS|SL)\s*:", re.I | re.M)

TARGET_LINE = re.compile(r"Target\s*(\d+)\s*:", re.I)
LOSS = re.compile(r"🚫|(?<!\w)Loss\s*\(", re.I)
ALL_TARGETS = re.compile(r"ALL\s+TARGETS", re.I)
# Vocabulario de acao. Uma mensagem SEM cabecalho de sinal so e `chat` se nao
# contiver nada disto. O historico do canal esta cheio de acoes sem cabecalho:
# um `CLOSE` seco, `VIP UPDATE: $CVX ... move your stop`, `Close Half Position`,
# `$ETH - Target 3,4 Achieved`, `MEGA SIGNAL`. Chamar isso de `chat` e dizer
# "nada a fazer" quando o sinal manda fechar — o erro mais caro possivel aqui.
ACTION = re.compile(
    r"^\s*CLOSED?\b|\bclosed\s+(at|all|half|the)\b|\bclosing\b|"
    r"close\s+(half|all|your|the|\d+%)|"
    r"mov(e|ing)\s+(your\s+)?(stops?|sl)\b|trail(ing)?\s+(your\s+)?stop|"
    r"stops?\s+(loss(es)?\s+)?(moved|to\s+(entry|entries|break))|break[\s-]?even|"
    r"target\s*\d[^\n]*(✅|achiev|hit|reached)|all\s+targets|"
    r"(mega|vip|gem)\s+signal\b|"
    r"stop[\s-]*loss\s*(hit|triggered)|hit\s+the\s+stop|\bsl\s+hit|stopped\s+out|"
    r"hit\s+the\s+sl|\bentry\s*:|\btargets?\s*:",
    re.I | re.M,
)
# Instrucao A MAIS numa mensagem de alvo atingido: "Target 1 ✅ ... Move SL to
# entry", "Closed at trailing SL after hitting 1st target". As linhas de alvo
# sozinhas dizem "parcial"; a instrucao diz que o stop mudou ou que a posicao
# FECHOU. Medido no historico: eram as 4 unicas divergencias restantes.
EXTRA_ACTION = re.compile(
    r"\bclosed?\b|\bclosing\b|mov(e|ing)\s+(your\s+)?(stops?|sl)\b|trail\w*|"
    r"\bstop\w*|\bsl\b|break[\s-]?even|\bmissed\b|\bexit\w*|re-?enter",
    re.I,
)
TARGET_LINE_FULL = re.compile(r"^.*Target\s*\d+\s*:.*$", re.I | re.M)

# Boilerplate recorrente que a spec do classificador manda chamar de `chat`,
# mas que fala em "move stops to entries" e "breakeven" — casaria ACTION.
BOILERPLATE = re.compile(r"^\s*IMPORTANT\b.*Remember to have entry orders", re.I | re.S)

PLAN_CHANGE = re.compile(
    r"\b(adjust\w*|close at (the )?first target|close now|exit at market|"
    r"move (the )?stop|tighten\w*|be ready to take profit)\b", re.I,
)


def signal_key(text: str) -> Optional[str]:
    """Chave estavel do sinal: o SIGNAL ID quando existe, senao o ticker GEM.

    Usada para recuperar quantos alvos o OPEN daquele sinal declarou.
    NB: os SIGNAL IDs reciclam ao longo do corpus historico — o chamador deve
    casar dentro de uma janela cronologica, como o killers_analyzer ja faz.
    """
    if not text:
        return None
    m = SIGID.search(text)
    if m:
        return f"sid:{m.group(1)}"
    g = GEM.search(text)
    return f"gem:{g.group(1).upper()}" if g else None


def signal_symbol(text: str) -> Optional[str]:
    """Ticker do sinal. Junto do SIGNAL ID forma a chave de INSTANCIA: um ID
    reciclado so empresta contagem de alvos se a moeda tambem casar."""
    if not text:
        return None
    m = COIN.search(text) or GEM.search(text)
    return m.group(1).upper() if m else None


def declared_target_count(open_text: str) -> Optional[int]:
    """Quantos alvos um OPEN declara. Alimenta `declared_targets`."""
    # O bloco de alvos vai do cabecalho TARGETS ate a linha em branco seguinte
    # ou ate o stop. Cobre o formato de uma linha e o antigo, de varias
    # (`Short Term:` / `Mid Term:`), somando os alvos de todas elas.
    m = re.search(r"TARGETS?\s*:?[ \t]*\n?(.+?)(?:\n[ \t]*\n|\n\s*STOP|\n\s*SL[:\s]|$)",
                  open_text or "", re.S | re.I)
    if not m:
        return None
    n = len(re.findall(r"\d+(?:[.,]\d+)?", m.group(1)))
    return n or None


def classify(text: Optional[str],
             declared_targets: Optional[int] = None) -> Tuple[Optional[str], str]:
    """Classifica por regra. Retorna `(kind, motivo)`; `kind=None` = vai p/ Claude.

    `declared_targets` e o nº de alvos que o OPEN deste sinal declarou. Sem ele,
    uma mensagem de alvo atingido NAO pode ser separada entre fechamento parcial
    e total, e a funcao devolve None de proposito.
    """
    if not text:
        return None, "sem texto"

    has_header = bool(SIGID.search(text) or COIN.search(text) or GEM.search(text))
    target_lines = TARGET_LINE.findall(text)

    # Sem cabecalho de sinal: promo, PNL, guia, papo de membro — mas SO se nao
    # houver vocabulario de acao. Na duvida, o Claude decide.
    if not has_header:
        if ACTION.search(text) and not BOILERPLATE.search(text):
            return None, "sem cabecalho, com vocabulario de acao"
        return "chat", "sem cabecalho de sinal"

    # Setup novo completo.
    if ENTRY.search(text) and TARGETS.search(text) and STOPLOSS.search(text):
        return "open", "entry+targets+sl"

    # Stop atingido: stop + perda, e nenhuma linha de alvo.
    if STOPLOSS.search(text) and LOSS.search(text) and not target_lines:
        return "close_full", "stop atingido"

    if target_lines:
        # Todos os alvos batidos e AMBIGUO na propria spec: o prompt do
        # classificador define alvo atingido como `close_partial` e reserva
        # `close_full` para linguagem explicita de encerramento, e os rotulos
        # historicos variam entre os dois para mensagens identicas. A regra nao
        # desempata — preserva o que o Claude faria.
        if ALL_TARGETS.search(text):
            return None, "all targets: parcial x total ambiguo"
        n = len(target_lines)
        if declared_targets is None:
            return None, "alvos sem contagem do open"
        if n >= declared_targets:
            return None, f"{n}>={declared_targets} alvos: parcial x total ambiguo"
        if EXTRA_ACTION.search(TARGET_LINE_FULL.sub("", text)):
            return None, "alvo atingido com instrucao a mais"
        return "close_partial", f"{n}<{declared_targets} alvos"

    # Cabecalho de sinal sem numeros, carregando instrucao: mudanca de plano.
    if PLAN_CHANGE.search(text):
        return "signal_update", "instrucao de mudanca de plano"

    return None, "sem regra"
