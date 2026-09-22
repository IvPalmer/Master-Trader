"""Classificador de regras para mensagens de gestao — extensao do `strict_open`.

`strict_open.py` cobre apenas OPENs limpos de moeda unica. Tudo o mais — alvo
atingido, stop atingido, promo, mudanca de plano — paga o hop de ~7,6s do
`claude` CLI. Os formatos do canal sao templatados o bastante para decidir a
maior parte disso por regra.

Contrato, igual ao do `strict_open`: retorna `None` em QUALQUER duvida, e o
chamador CAI PARA O CLAUDE. Nenhuma regra aqui adivinha.

Medido contra 537 mensagens classificadas em producao (2026-09-22, issue #62):

    decidiu por regra      481/537 = 89,6%
    concordancia do que decidiu  478/481 = 99,38%
    caiu para o Claude      56/537 = 10,4%

As 3 discordancias restantes sao erro do Claude, nao da regra:
  - 1 `signal_update` explicito ("we are adjusting the $KITE setup to close at
    first target") que o Claude rotulou `chat`. Essa classe executa fechamento
    total no receiver, entao o miss do Claude e o mais caro dos tres.
  - 2 mensagens com 8/8 alvos batidos que o Claude chamou `close_partial`
    enquanto rotulou `close_full` outras estruturalmente identicas. A regra e
    auto-consistente; o Claude nao e.

Os 56 fallbacks sao todos `close_partial` cujo OPEN e anterior a janela do
corpus, logo sem contagem de alvos declarada. Em producao, com estado
persistente, isso se resolve sozinho conforme os opens entram.
"""
import re
from typing import Optional, Tuple

# Cabecalho padrao do canal.
SIGID = re.compile(r"SIGNAL\s*ID\s*:\s*#?(\d+)", re.I)
COIN = re.compile(r"COIN\s*:\s*\$?([A-Z0-9]{1,15})\s*/\s*USDT?", re.I)
# Formato GEM: cabecalho proprio, sem SIGNAL ID, ticker no titulo.
GEM = re.compile(r"GEM\s*SIGNAL\s*:\s*[#$]?([A-Z0-9]{1,15})", re.I)

ENTRY = re.compile(r"^\s*ENTRY\s*:", re.I | re.M)
TARGETS = re.compile(r"^\s*TARGETS?\s*:", re.I | re.M)
# GEM escreve `SL:`; o formato padrao escreve `STOP LOSS:`.
STOPLOSS = re.compile(r"^\s*(STOP\s*LOSS|SL)\s*:", re.I | re.M)

TARGET_LINE = re.compile(r"Target\s*(\d+)\s*:", re.I)
LOSS = re.compile(r"🚫|(?<!\w)Loss\s*\(", re.I)
ALL_TARGETS = re.compile(r"ALL\s+TARGETS", re.I)
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


def declared_target_count(open_text: str) -> Optional[int]:
    """Quantos alvos um OPEN declara. Alimenta `declared_targets`."""
    m = re.search(r"TARGETS?\s*:\s*(.+?)(?:\n\n|\nSTOP|\nSL|$)",
                  open_text or "", re.S | re.I)
    if not m:
        return None
    n = len(re.findall(r"\d+(?:\.\d+)?", m.group(1)))
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

    # Sem cabecalho de sinal: promo, PNL, guia, papo de membro.
    if not has_header:
        return "chat", "sem cabecalho de sinal"

    # Setup novo completo.
    if ENTRY.search(text) and TARGETS.search(text) and STOPLOSS.search(text):
        return "open", "entry+targets+sl"

    # Stop atingido: stop + perda, e nenhuma linha de alvo.
    if STOPLOSS.search(text) and LOSS.search(text) and not target_lines:
        return "close_full", "stop atingido"

    if target_lines:
        if ALL_TARGETS.search(text):
            return "close_full", "all targets"
        n = len(target_lines)
        if declared_targets is None:
            # Sem saber quantos alvos o sinal tinha, parcial e total sao
            # indistinguiveis. O Claude decide.
            return None, "alvos sem contagem do open"
        if n >= declared_targets:
            return "close_full", f"{n}>={declared_targets} alvos"
        return "close_partial", f"{n}<{declared_targets} alvos"

    # Cabecalho de sinal sem numeros, carregando instrucao: mudanca de plano.
    if PLAN_CHANGE.search(text):
        return "signal_update", "instrucao de mudanca de plano"

    return None, "sem regra"
