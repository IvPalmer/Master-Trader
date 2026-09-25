"""Gate de confianca das classificacoes do Claude (#65) — passo 1: SHADOW.

O observer encaminha ao receiver qualquer classificacao que tenha `kind`; o
`confidence` era gravado mas nao controlava nada. Este modulo calcula o
veredito que um gate daria (pass / would_block) para que ele seja GRAVADO e
medido. Nao bloqueia nada: o `confidence` e autodeclarado pelo modelo e nao
esta calibrado, entao nenhum limiar se justifica ainda.

- Configuracao versionada em `confidence_gate.json`, ao lado do classificador
  (nao em variaveis de ambiente). Carregada uma vez na subida (`Config`).
- Arquivo malformado -> `load_config` levanta `GateConfigError`; o observer
  registra ERROR e segue com o gate desligado (um gate de observacao nunca
  derruba o encaminhamento). A falha alta fica no CI, que valida o arquivo
  versionado. Arquivo AUSENTE -> shadow com limiares desligados + WARNING.
- So `mode = "shadow"` e aceito. Ligar o enforcing e uma mudanca posterior,
  revisada a parte, quando houver desfechos rotulados para calibrar (#62,
  #65); a acao prevista para close_full/signal_update e "alertar e segurar".
- Existe um unico `confidence` escalar por classificacao; nao ha
  probabilidade por campo. O gate usa esse escalar para o `kind` e, por
  extensao, para os campos criticos da acao.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).parent / "confidence_gate.json"
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})
SUPPORTED_MODES = frozenset({"shadow"})
# Tipos sem efeito a jusante: confianca ausente nao reprova.
NON_ACTION_KINDS = frozenset({"chat"})

PASS = "pass"
WOULD_BLOCK = "would_block"
DISABLED = "disabled"


class GateConfigError(ValueError):
    """Arquivo de configuracao do gate presente mas invalido."""


@dataclass(frozen=True)
class GateConfig:
    schema_version: int
    mode: str
    thresholds: dict = field(default_factory=dict)
    label_order: tuple = ()
    enabled: bool = True           # False = arquivo ausente, sem limiares


@dataclass(frozen=True)
class Verdict:
    kind: Optional[str]
    confidence: Optional[float]
    threshold: Optional[float]
    verdict: str                   # pass | would_block | disabled
    reason: str


def disabled_config() -> GateConfig:
    return GateConfig(schema_version=0, mode="shadow", enabled=False)


def _is_number(v) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v))


def parse_config(data) -> GateConfig:
    if not isinstance(data, dict):
        raise GateConfigError("raiz deve ser um objeto JSON")
    sv = data.get("schema_version")
    if isinstance(sv, bool) or sv not in SUPPORTED_SCHEMA_VERSIONS:
        raise GateConfigError(f"schema_version nao suportado: {sv!r}")
    mode = data.get("mode")
    if mode not in SUPPORTED_MODES:
        raise GateConfigError(
            f"mode {mode!r} nao suportado nesta versao (so 'shadow'); "
            "enforcing exige mudanca de codigo revisada (#65)")
    labels = data.get("label_order")
    if (not isinstance(labels, list) or not labels
            or not all(isinstance(x, str) and x for x in labels)
            or len(set(labels)) != len(labels)):
        raise GateConfigError("label_order deve ser lista de strings unicas")
    th = data.get("thresholds")
    if not isinstance(th, dict):
        raise GateConfigError("thresholds deve ser um objeto")
    if set(th) != set(labels):
        raise GateConfigError(
            f"thresholds e label_order divergem: faltam "
            f"{sorted(set(labels) - set(th))}, sobram {sorted(set(th) - set(labels))}")
    for k, v in th.items():
        if not _is_number(v) or not 0.0 <= v <= 1.0:
            raise GateConfigError(f"limiar invalido para {k!r}: {v!r}")
    return GateConfig(schema_version=sv, mode=mode,
                      thresholds={k: float(v) for k, v in th.items()},
                      label_order=tuple(labels))


def load_config(path: Optional[Path] = None) -> GateConfig:
    """Carrega e valida. Ausente -> desligado + WARNING; invalido -> levanta."""
    p = Path(path) if path is not None else DEFAULT_PATH
    if not p.exists():
        logger.warning("[CONF-GATE] %s ausente — gate em shadow com limiares "
                       "DESLIGADOS (so grava a confianca)", p)
        return disabled_config()
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise GateConfigError(f"{p}: nao foi possivel ler/parsear: {e}") from e
    try:
        cfg = parse_config(data)
    except GateConfigError as e:
        raise GateConfigError(f"{p}: {e}") from e
    logger.info("[CONF-GATE] %s schema_version=%d mode=%s limiares=%s",
                p, cfg.schema_version, cfg.mode, cfg.thresholds)
    return cfg


def evaluate(cfg: GateConfig, classification: dict) -> Verdict:
    """Veredito puro, sem efeito colateral."""
    kind = classification.get("kind")
    raw = classification.get("confidence")
    conf = float(raw) if _is_number(raw) else None
    kind_s = kind if isinstance(kind, str) else None

    if not cfg.enabled:
        return Verdict(kind_s, conf, None, DISABLED, "config ausente")
    if kind_s is None or kind_s not in cfg.thresholds:
        return Verdict(kind_s, conf, None, WOULD_BLOCK, f"kind desconhecido: {kind!r}")
    threshold = cfg.thresholds[kind_s]
    if kind_s in NON_ACTION_KINDS:
        return Verdict(kind_s, conf, threshold, PASS, "tipo sem acao")
    if raw is None:
        return Verdict(kind_s, None, threshold, WOULD_BLOCK, "confianca ausente")
    if conf is None:
        return Verdict(kind_s, None, threshold, WOULD_BLOCK,
                       f"confianca nao numerica: {raw!r}"[:200])
    if not 0.0 <= conf <= 1.0:
        return Verdict(kind_s, conf, threshold, WOULD_BLOCK,
                       "confianca fora de [0,1]")
    if conf < threshold:
        return Verdict(kind_s, conf, threshold, WOULD_BLOCK,
                       f"confianca {conf:.3f} < limiar {threshold:.3f}")
    return Verdict(kind_s, conf, threshold, PASS,
                   f"confianca {conf:.3f} >= limiar {threshold:.3f}")
