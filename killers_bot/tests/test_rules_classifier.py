"""Testes do classificador de regras (issue #62).

Fixtures sao formatos reais do canal, com precos e IDs trocados. O contrato
central e o de recusa: em duvida, `None`, e o chamador vai para o Claude.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rules_classifier import (  # noqa: E402
    classify, declared_target_count, signal_key,
)

OPEN = """📍SIGNAL ID: #2143📍
COIN: $POL/USDT (2-5x)
Direction: LONG
➖➖➖➖➖➖➖
ENTRY: 0.0894 - 0.0900

TARGETS: 0.0945 - 0.0990 - 0.1050 - 0.1125 - 0.1200 - 0.1300 - 0.1400 - 0.1500

STOP LOSS: 0.0810
- Binance Killers®"""

PARTIAL = """📍SIGNAL ID: #2143📍
COIN: $POL/USDT (2-5x)
Direction: LONG
➖➖➖➖➖➖➖
Target 1: 0.0945✅
Target 2: 0.0990✅

🔥22.4% Profit (5x)🔥
- Binance Killers®"""

SL_HIT = """📍SIGNAL ID: #2134📍
COIN: $SKY/USDT (2-5X)
Direction: LONG
➖➖➖➖➖➖➖

STOP LOSS: 0.0650

🚫19.4% Loss (2x)🚫

Volatility across global markets took this one out.
- Binance Killers®"""

ALL_SMASHED = """📍SIGNAL ID: #2142📍
COIN: $XLM/USDT (2-5x)
Direction: LONG
➖➖➖➖➖➖➖
Target 1: 0.1515✅
Target 2: 0.1580✅

ALL TARGETS SMASHED!!!!! 🚀🚀🚀

🔥275.9% Profit (5x)🔥"""

PLAN_CHANGE = """📍SIGNAL ID: #2154📍
COIN: $KITE/USDT (2-5x)
Direction: LONG
➖➖➖➖➖➖➖
Due to elevated volatility, we are adjusting the $KITE setup to close at first target.

Price is moving in our favor, be ready to take profit."""

PROMO = """NO.1 TELEGRAM CRYPTO CHANNEL

JOIN NOW 👉 https://t.me/+example"""

GEM_OPEN = """🔥GEM SIGNAL: #4USDT🔥
➖➖➖➖➖➖➖
Exchanges: Binance Futures

ENTRY: Below 0.0105

TARGETS: 0.0107 – 0.0109 – 0.0111 - 0.0115

SL: Below 0.0083"""

GEM_PARTIAL = """🔥GEM SIGNAL: $ZIG🔥
➖➖➖➖➖➖➖
Target 1: 0.045✅

🔥41.5% Profit (5x)🔥"""


def test_open_completo():
    assert classify(OPEN)[0] == "open"


def test_gem_open_usa_sl_curto():
    """O formato GEM escreve `SL:`, nao `STOP LOSS:`."""
    assert classify(GEM_OPEN)[0] == "open"


def test_stop_atingido_e_fechamento_total():
    assert classify(SL_HIT)[0] == "close_full"


def test_all_targets_e_total_mesmo_sem_contagem():
    assert classify(ALL_SMASHED)[0] == "close_full"


def test_parcial_quando_faltam_alvos():
    assert classify(PARTIAL, declared_targets=8)[0] == "close_partial"


def test_total_quando_todos_os_alvos_batem():
    assert classify(PARTIAL, declared_targets=2)[0] == "close_full"


def test_alvo_sem_contagem_recusa():
    """Contrato central: sem saber quantos alvos o sinal tinha, parcial e total
    sao indistinguiveis — tem de cair para o Claude, nunca chutar."""
    kind, why = classify(PARTIAL, declared_targets=None)
    assert kind is None
    assert "contagem" in why


def test_gem_parcial_tambem_recusa_sem_contagem():
    assert classify(GEM_PARTIAL, declared_targets=None)[0] is None


def test_mudanca_de_plano():
    assert classify(PLAN_CHANGE)[0] == "signal_update"


def test_promo_sem_cabecalho_e_chat():
    assert classify(PROMO)[0] == "chat"


@pytest.mark.parametrize("texto", ["", None, "   "])
def test_entrada_vazia_nao_explode(texto):
    kind, _ = classify(texto)
    assert kind in (None, "chat")


def test_declared_target_count():
    assert declared_target_count(OPEN) == 8
    assert declared_target_count(GEM_OPEN) == 4
    assert declared_target_count("sem alvos aqui") is None


def test_signal_key():
    assert signal_key(OPEN) == "sid:2143"
    assert signal_key(GEM_PARTIAL) == "gem:ZIG"
    assert signal_key(PROMO) is None


def test_open_nao_e_confundido_com_gestao():
    """Um OPEN tem ENTRY; uma mensagem de gestao nao. A ordem das regras
    precisa garantir que o OPEN ganhe antes do ramo de alvos."""
    assert classify(OPEN, declared_targets=8)[0] == "open"
