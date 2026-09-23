"""Entradas abaixo do minimo da venue sobem ATE o minimo (opt-in, 2026-09-23).

Casos reais que o receiver pulou antes da mudanca, com o risco de $2 atual:
SKR #3855 (stop a 20,7% -> ordem de $9,66) e CATI #3886 (stop a 43,8% -> margem
abaixo de $5). Os testes usam o stop_limit_ratio de PRODUCAO (0,98): o sizing
mede o stop na borda adversa do stop-limit, e com ele o CATI fica a 44,9% —
risco ajustado de $5,08. Um fixture com ratio 1,0 escondia que um teto de $5
continuaria perdendo o CATI. O contrato: so a entrada pequena demais muda; o risco dela fica
dentro de KILLERS_MAX_BUMP_RISK_USD; as normais nao mudam; e sem o opt-in o
comportamento antigo (pular) continua.
"""
from types import SimpleNamespace

import pytest

from app.main import compute_stake


def cfg(**over):
    base = dict(
        stake_usd=10.0, leverage=2.0, risk_usd=2.0,
        min_margin_usd=5.0, max_margin_usd=10.0, max_leverage=3.0,
        min_notional_usd=11.3, stop_limit_ratio=0.98,   # igual a producao
        bump_to_min_notional=True, max_bump_risk_usd=6.0,
    )
    base.update(over)
    return SimpleNamespace(**base)


def long_signal(dist):
    return {"entry": 100.0, "sl": 100.0 * (1 - dist), "direction": "long"}


def admitted(stake, leverage, c):
    """O mesmo gate que o handler de open aplica logo depois do sizing."""
    return stake >= c.min_margin_usd and stake * leverage >= c.min_notional_usd


@pytest.mark.parametrize("dist, nome", [(0.207, "SKR #3855"), (0.438, "CATI #3886")])
def test_sinal_perdido_agora_entra_no_minimo(dist, nome):
    c = cfg()
    stake, leverage, d = compute_stake(long_signal(dist), c)
    assert admitted(stake, leverage, c), nome
    assert leverage == int(leverage)                 # Hyperliquid so aceita inteiro
    assert c.min_margin_usd <= stake <= c.max_margin_usd
    risco = stake * leverage * d
    assert risco <= c.max_bump_risk_usd + 0.02, (nome, risco)


def test_acima_do_teto_de_risco_continua_pulando():
    c = cfg()
    stake, leverage, d = compute_stake(long_signal(0.55), c)   # efetivo 55,9% -> $6,32 > $6
    assert not admitted(stake, leverage, c)


@pytest.mark.parametrize("dist", [0.02, 0.05, 0.094, 0.15])
def test_trade_normal_nao_muda(dist):
    ligado = compute_stake(long_signal(dist), cfg())
    desligado = compute_stake(long_signal(dist), cfg(bump_to_min_notional=False))
    assert ligado == desligado


@pytest.mark.parametrize("dist", [0.207, 0.438])
def test_sem_opt_in_o_comportamento_antigo_continua(dist):
    c = cfg(bump_to_min_notional=False)
    stake, leverage, _ = compute_stake(long_signal(dist), c)
    assert not admitted(stake, leverage, c)


def test_short_tambem_sobe():
    c = cfg()
    stake, leverage, d = compute_stake({"entry": 100.0, "sl": 125.0, "direction": "short"}, c)
    assert admitted(stake, leverage, c)
    assert stake * leverage * d <= c.max_bump_risk_usd + 0.02


def test_venue_hyperliquid(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "execution_venue", lambda: "hyperliquid")
    c = cfg()
    stake, leverage, _ = compute_stake(long_signal(0.438), c)
    assert admitted(stake, leverage, c) and leverage == int(leverage)


def test_arredondamento_nao_cai_um_centavo_abaixo_do_minimo():
    # minimo que nao divide exato pela alavancagem
    c = cfg(min_notional_usd=11.29)
    stake, leverage, _ = compute_stake(long_signal(0.30), c)
    assert stake * leverage >= c.min_notional_usd


def test_cati_com_ratio_de_producao_entra():
    """Regressao do fixture errado: com ratio 0,98 o CATI custa $5,08 no
    minimo — o teto de producao tem de cobrir."""
    c = cfg()
    stake, leverage, d = compute_stake(long_signal(0.438), c)
    assert abs(d - 0.44924) < 1e-4
    assert admitted(stake, leverage, c)
    assert 5.0 < stake * leverage * d <= 6.0


def test_pior_stop_historico_entra():
    """Pior stop dos 75 opens historicos: 42,2% no sinal, 43,4% na borda do
    stop-limit -> $4,90."""
    c = cfg()
    stake, leverage, d = compute_stake(long_signal(0.422), c)
    assert admitted(stake, leverage, c)
