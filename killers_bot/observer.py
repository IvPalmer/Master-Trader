"""Main orchestrator: Telethon listener → classifier → paper simulator → log.

No exchange connection. No real orders. Observe-only.

Run via the Docker entrypoint, or locally:
  python3 -m killers_bot.observer
"""
import asyncio
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import classifier, confidence_gate, rules_classifier, simulator, strict_open

logger = logging.getLogger(__name__)


# ── Config ─────────────────────────────────────────────────────────────────


def _load_dotenv():
    """Load killers_bot/.env into os.environ if present.

    Hand-rolled (no python-dotenv dep) to keep the image minimal. Strips
    surrounding double-quotes so multi-word values like
    `KILLERS_CLAUDE_BINARY="docker exec elder-brain-bot claude"` round-trip.
    """
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1]
        os.environ.setdefault(k.strip(), v)


class Config:
    def __init__(self):
        _load_dotenv()
        self.api_id = int(_required("KILLERS_TG_API_ID"))
        self.api_hash = _required("KILLERS_TG_API_HASH")
        self.session_path = _required("KILLERS_TG_SESSION")
        self.channel_username = os.getenv(
            "KILLERS_TG_CHANNEL_USERNAME", "BinanceKillers_FreeSignal"
        )
        self.channel_id_override = os.getenv("KILLERS_TG_CHANNEL_ID")
        # Shadow do classificador de regras (#62). Como o `use_fast_path`, e
        # especifico do formato Killers — o fan-out Insiders desliga abaixo.
        self.shadow_rules = True
        # Regras DECIDEM chat / close_partial / close_full por stop (#74), com o
        # Claude em shadow. Rollback sem deploy: KILLERS_RULES_PRIMARY=0 no
        # killers_bot/.env + restart do servico.
        self.rules_primary = os.getenv("KILLERS_RULES_PRIMARY", "1").strip().lower() not in ("0", "false", "no")
        self.db_path = os.getenv("KILLERS_DB", "/var/lib/killers/state.sqlite")
        self.claude_binary = os.getenv("KILLERS_CLAUDE_BINARY", "claude")
        self.claude_model = os.getenv("KILLERS_CLAUDE_MODEL") or None
        self.claude_timeout = float(os.getenv("KILLERS_CLAUDE_TIMEOUT_SEC", "12"))
        self.heartbeat_sec = int(os.getenv("KILLERS_HEARTBEAT_SEC", "60"))
        # Receiver endpoint — when set, observer POSTs each classification.
        # Receiver translates to Freqtrade Futures REST. Leave unset to run
        # in pure observe-mode (Phase 1).
        self.receiver_url = os.getenv("KILLERS_RECEIVER_URL", "")
        # Bearer token the receiver requires on every route. Per-receiver:
        # the insiders fan-out overrides it below so a leak of one token
        # cannot drive the other funded account. Deliberately NO fallback to
        # the killers token — a missing insiders token must fail loudly (401,
        # logged, not retried) rather than silently cross-authenticate.
        self.receiver_token = os.getenv("KILLERS_RECEIVER_TOKEN", "")
        # Channel-specific classifier prompt + fast-path. Defaults are the
        # Killers VIP settings; the insiders fan-out overrides both (Dennis's
        # "Market Mastery" format is different and the strict-open rule parser
        # is Killers-only, so it's disabled for insiders).
        self.classifier_template = classifier.PROMPT_TEMPLATE
        self.use_fast_path = True
        # Gate de confianca em SHADOW (#65): so grava o veredito, nunca
        # bloqueia. Arquivo malformado derruba a subida aqui (de proposito);
        # arquivo ausente vira shadow sem limiares + WARNING.
        self.confidence_gate = confidence_gate.load_config()


def _required(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise SystemExit(f"missing required env var: {name}")
    return val


# ── DB ─────────────────────────────────────────────────────────────────────


def init_db(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    schema = (Path(__file__).parent / "schema.sql").read_text()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(schema)
    return conn


def last_msg_id(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute("SELECT MAX(msg_id) FROM raw_messages").fetchone()
    return row[0] if row and row[0] else None


_RAW_COLS = "(msg_id, received_at, posted_at, edited_at, reply_to_msg_id, text, raw_json)"
_CLS_COLS = ("(msg_id, classified_at, kind, signal_id, symbol, direction, "
             " entry_lo, entry_hi, sl, sl_str, tp, pct, confidence, notes, raw_json)")


def _append_revision(conn: sqlite3.Connection, table: str, cols: str,
                     row: tuple) -> None:
    """Trilha de auditoria append-only (#64). A tabela principal guarda so a
    versao mais recente (INSERT OR REPLACE); aqui fica cada versao. Falha na
    auditoria e engolida — nunca pode derrubar a ingestao.

    O SAVEPOINT isola a falha: desfaz so a revisao, nao a escrita principal
    da mesma transacao. Se o SQLite ja abortou a transacao inteira (disco
    cheio, I/O), a escrita principal se perdeu e o erro sobe em vez de um
    commit vazio fingir sucesso."""
    conn.execute("SAVEPOINT audit_revision")
    try:
        conn.execute(
            f"INSERT INTO {table} {cols} VALUES ({', '.join('?' * len(row))})",
            row,
        )
        conn.execute("RELEASE audit_revision")
    except Exception:
        if not conn.in_transaction:
            raise
        conn.execute("ROLLBACK TO audit_revision")
        conn.execute("RELEASE audit_revision")
        logger.exception("[AUDIT] %s falhou msg_id=%s — ignorado", table, row[0])


def persist_raw(conn: sqlite3.Connection, msg: dict) -> None:
    row = (
        msg["id"],
        datetime.now(timezone.utc).isoformat(),
        str(msg.get("date")) if msg.get("date") else None,
        str(msg.get("edit_date")) if msg.get("edit_date") else None,
        msg.get("reply_to_msg_id"),
        msg.get("message") or msg.get("text"),
        json.dumps(msg, default=str),
    )
    conn.execute(
        f"INSERT OR REPLACE INTO raw_messages {_RAW_COLS} "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        row,
    )
    _append_revision(conn, "raw_message_revisions", _RAW_COLS, row)
    conn.commit()


def persist_classification(conn: sqlite3.Connection, classification: dict) -> None:
    entry_range = classification.get("entry_range") or [None, None]
    if not isinstance(entry_range, list) or len(entry_range) != 2:
        entry_range = [None, None]
    sl_val = classification.get("sl")
    sl_num = sl_val if isinstance(sl_val, (int, float)) else None
    sl_str = sl_val if isinstance(sl_val, str) else None

    row = (
        classification["id"],
        datetime.now(timezone.utc).isoformat(),
        classification.get("kind"),
        classification.get("signal_id"),
        classification.get("symbol"),
        classification.get("direction"),
        entry_range[0], entry_range[1],
        sl_num, sl_str,
        classification.get("tp"),
        classification.get("pct"),
        classification.get("confidence"),
        (classification.get("notes") or "")[:1000],
        json.dumps(classification, default=str),
    )
    conn.execute(
        f"INSERT OR REPLACE INTO classifications {_CLS_COLS} "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        row,
    )
    _append_revision(conn, "classification_revisions", _CLS_COLS, row)
    conn.commit()


# ── Shadow do classificador de regras (#62) ────────────────────────────────
# Observacional: mede a regra contra o que de fato seguiu adiante. NUNCA
# altera o encaminhamento. Qualquer falha aqui e engolida — uma regressao no
# shadow nao pode derrubar a ingestao.


def record_signal_targets(conn: sqlite3.Connection, msg: dict,
                          classification: dict) -> None:
    """Registra quantos alvos um OPEN declarou. Append-only: IDs reciclam.

    Protegido de ponta a ponta: esta funcao roda ANTES do simulador e do POST
    ao receiver, entao uma excecao aqui pularia os dois. Observacao nunca pode
    derrubar execucao.
    """
    try:
        if classification.get("kind") != "open":
            return
        text = msg.get("text") or msg.get("message") or ""
        key = rules_classifier.signal_key(text)
        declared = rules_classifier.declared_target_count(text)
        if not key or not declared:
            return
        conn.execute(
            "INSERT INTO signal_targets (signal_key, symbol, declared, msg_id, "
            "posted_at) VALUES (?, ?, ?, ?, ?)",
            (key, rules_classifier.signal_symbol(text), declared, msg["id"],
             str(msg.get("date")) if msg.get("date") else None),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("[RULE-SHADOW] record_signal_targets falhou id=%s "
                         "— ignorado", msg.get("id"))


def lookup_declared_targets(conn: sqlite3.Connection, text: str,
                            before_msg_id: int) -> Optional[int]:
    """Alvos declarados pelo OPEN mais recente desta INSTANCIA de sinal.

    Chave de instancia = SIGNAL ID + simbolo. Só o ID nao basta: os IDs
    reciclam, e se o OPEN da epoca atual ainda nao foi visto, casar so por ID
    emprestaria silenciosamente a contagem de um sinal antigo — exatamente o
    erro que o corte cronologico deveria evitar. Exigindo o simbolo, um ID
    reciclado em outra moeda nao casa, e a regra recusa em vez de chutar.

    `msg_id` e o relogio: no Telegram os IDs sao monotonicos por canal e uma
    edicao preserva o ID original. O desempate por `row_id` cobre o caso de um
    OPEN editado gerar duas linhas com o mesmo `msg_id`.
    """
    key = rules_classifier.signal_key(text)
    if not key:
        return None
    symbol = rules_classifier.signal_symbol(text)
    if not symbol:
        # Sem moeda na mensagem, a instancia do sinal e desconhecida: casar so
        # pelo ID reciclado emprestaria a contagem de outro sinal.
        return None
    row = conn.execute(
        "SELECT declared FROM signal_targets "
        "WHERE signal_key = ? AND symbol = ? AND msg_id <= ? "
        "ORDER BY msg_id DESC, row_id DESC LIMIT 1",
        (key, symbol, before_msg_id),
    ).fetchone()
    return row[0] if row else None


def shadow_rules(conn: sqlite3.Connection, msg: dict, classification: dict,
                 source: str) -> None:
    """Roda o classificador de regras em paralelo e grava a comparacao."""
    try:
        text = msg.get("text") or msg.get("message") or ""
        declared = lookup_declared_targets(conn, text, msg["id"])
        rule_kind, reason = rules_classifier.classify(text, declared)
        primary = classification.get("kind")

        agree = -1 if rule_kind is None else int(rule_kind == primary)
        # Append-only: uma edicao gera nova linha, nunca apaga a anterior.
        conn.execute(
            "INSERT INTO rule_shadow (msg_id, evaluated_at, "
            "primary_kind, primary_source, rule_kind, rule_reason, declared, agree) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (msg["id"], datetime.now(timezone.utc).isoformat(), primary, source,
             rule_kind, reason, declared, agree),
        )
        conn.commit()

        if agree == 0:
            logger.warning(
                "[RULE-SHADOW DIVERGE] id=%d primario=%s(%s) regra=%s (%s)",
                msg["id"], primary, source, rule_kind, reason,
            )
        else:
            logger.info("[RULE-SHADOW] id=%d %s regra=%s (%s)", msg["id"],
                        "ok" if agree == 1 else "recusou", rule_kind, reason)
    except Exception:
        # Um DML que falhou pode deixar a conexao COMPARTILHADA numa transacao
        # aberta. Desfaz antes de devolver o controle ao caminho de producao.
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("[RULE-SHADOW] falhou id=%s — ignorado", msg.get("id"))


# ── Gate de confianca em SHADOW (#65) ──────────────────────────────────────


def record_confidence_gate(conn: sqlite3.Connection, msg: dict,
                           classification: dict, source: str,
                           gate_cfg: "confidence_gate.GateConfig") -> None:
    """Calcula e GRAVA o veredito do gate. Nunca bloqueia, nunca levanta.

    Chamado so para classificacoes do Claude, ANTES de persistir/simular/
    encaminhar — o lugar onde um gate de verdade teria de agir. Em shadow o
    retorno e sempre None e o chamador segue exatamente como antes. Mesmo
    padrao de `shadow_rules`: falha e engolida com rollback da conexao
    compartilhada."""
    try:
        v = confidence_gate.evaluate(gate_cfg, classification)
        conn.execute(
            "INSERT INTO confidence_gate (msg_id, evaluated_at, kind, source, "
            "confidence, threshold, verdict, reason, mode, config_schema_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (msg["id"], datetime.now(timezone.utc).isoformat(), v.kind, source,
             v.confidence, v.threshold, v.verdict, v.reason, gate_cfg.mode,
             gate_cfg.schema_version),
        )
        conn.commit()
        if v.verdict == confidence_gate.WOULD_BLOCK:
            logger.warning(
                "[CONF-GATE WOULD_BLOCK] id=%s kind=%s conf=%s limiar=%s (%s) — "
                "shadow: encaminhado mesmo assim",
                msg.get("id"), v.kind, v.confidence, v.threshold, v.reason)
        else:
            logger.info("[CONF-GATE] id=%s kind=%s %s (%s)", msg.get("id"),
                        v.kind, v.verdict, v.reason)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("[CONF-GATE] falhou id=%s — ignorado", msg.get("id"))

# ── Reply chain (small, in-memory cache + DB fallback) ─────────────────────


async def build_reply_chain(client, channel_id, conn, msg_dict: dict, depth: int = 3) -> list[dict]:
    chain = []
    current = msg_dict
    for _ in range(depth):
        parent_id = current.get("reply_to_msg_id")
        if not parent_id:
            break
        row = conn.execute(
            "SELECT msg_id, posted_at, reply_to_msg_id, text FROM raw_messages WHERE msg_id = ?",
            (parent_id,),
        ).fetchone()
        if row:
            current = {"id": row["msg_id"], "date": row["posted_at"],
                       "reply_to_msg_id": row["reply_to_msg_id"], "text": row["text"] or ""}
        else:
            try:
                msg = await client.get_messages(channel_id, ids=parent_id)
                if msg is None:
                    break
                d = msg.to_dict() if hasattr(msg, "to_dict") else dict(msg)
                persist_raw(conn, d)
                current = {"id": d.get("id"), "date": str(d.get("date")),
                           "reply_to_msg_id": d.get("reply_to_msg_id"),
                           "text": d.get("message") or d.get("text") or ""}
            except Exception as e:
                logger.warning("reply chain fetch failed parent=%d: %s", parent_id, e)
                break
        chain.append(current)
    return chain


# ── Process one message end-to-end ─────────────────────────────────────────


async def process_message(client, channel_id, conn, config, msg_dict: dict, source: str) -> None:
    # Telethon's to_dict() puts message content in the 'message' key, not 'text'.
    # Mirror it onto 'text' for downstream callers (classifier prompt, snippet).
    if not msg_dict.get("text") and msg_dict.get("message"):
        msg_dict["text"] = msg_dict["message"]
    persist_raw(conn, msg_dict)
    snippet = (msg_dict.get("text") or "")[:80].replace("\n", " ⏎ ")
    logger.info("[MSG %s] id=%d %r", source.upper(), msg_dict["id"], snippet)

    chain = await build_reply_chain(client, channel_id, conn, msg_dict)

    # FAST-PATH: try the rule parser first. Saves ~7s of Claude latency on
    # clean OPEN signals. Strict checks inside the parser reject anything
    # that isn't a complete single-coin open. Claude still runs in shadow
    # after the receiver POST so any disagreement is visible.
    text = msg_dict.get("text") or msg_dict.get("message") or ""
    classification = (
        strict_open.is_strict_killers_open(text, msg_dict["id"])
        if config.use_fast_path else None
    )
    used_fast_path = classification is not None
    source_label = "rule" if used_fast_path else "claude"
    if classification is None and getattr(config, "rules_primary", False):
        # Classificador de regras (#74). Recusa em qualquer ambiguidade; so
        # decide os tipos em PRIMARY_KINDS. O Claude roda em shadow depois.
        declared = lookup_declared_targets(conn, text, msg_dict["id"])
        rule_kind, rule_reason = rules_classifier.classify(text, declared)
        if rule_kind in rules_classifier.PRIMARY_KINDS:
            classification = rules_classifier.build_classification(
                msg_dict["id"], text, rule_kind)
            used_fast_path = True
            source_label = "rules"
            logger.info("[RULES] id=%d kind=%s (%s) — bypassing Claude",
                        msg_dict["id"], rule_kind, rule_reason)
    if used_fast_path and source_label == "rule":
        logger.info(
            "[FAST-PATH] id=%d kind=open signal=#%s sym=%s — bypassing Claude",
            msg_dict["id"], classification["signal_id"], classification["symbol"],
        )
    elif not used_fast_path:
        classification = await classifier.classify(
            msg_dict, chain,
            binary=config.claude_binary,
            model=config.claude_model,
            timeout_sec=config.claude_timeout,
            template=config.classifier_template,
        )
    if classification is None:
        logger.warning("[CLASSIFY FAIL] id=%d skipping downstream", msg_dict["id"])
        return

    # Gate de confianca em SHADOW (#65): so para o que o Claude decidiu. As
    # regras sao deterministicas (confidence fixo em 1.0) e nao sao avaliadas.
    # Grava o veredito e segue — o encaminhamento abaixo NAO depende dele.
    gate_cfg = getattr(config, "confidence_gate", None)
    if source_label == "claude" and gate_cfg is not None:
        record_confidence_gate(conn, msg_dict, classification, source_label, gate_cfg)

    persist_classification(conn, classification)
    kind = classification.get("kind")
    sym = classification.get("symbol")
    sid = classification.get("signal_id")
    conf = classification.get("confidence", 0)
    logger.info("[CLASSIFY] id=%d kind=%s signal=#%s sym=%s conf=%.2f source=%s",
                msg_dict["id"], kind, sid, sym, conf, source_label)

    # Shadow observacional do classificador de regras (#62). Puro regex, roda
    # em microssegundos, e nao toca no que segue para o simulador/receiver.
    if getattr(config, "shadow_rules", False):
        record_signal_targets(conn, msg_dict, classification)
        # Quando a propria regra decidiu, comparar regra com regra nao diz
        # nada: o veredito util e o do Claude em shadow, gravado por
        # _shadow_classify.
        if source_label != "rules":
            shadow_rules(conn, msg_dict, classification, source_label)

    # Route into paper simulator (local audit trail)
    if kind == "open":
        simulator.open_paper_position(conn, msg_dict, classification)
    elif kind in ("close_partial", "close_full", "move_sl"):
        simulator.update_paper_position(conn, msg_dict, classification)
    elif kind == "increase":
        logger.info("[INCREASE] not modeled in paper sim yet")
    # else: chat — already logged via [CLASSIFY], nothing to do

    # Forward to receiver for real Freqtrade Futures dry-run execution.
    # Receiver is the source of truth for actual trades; paper sim stays
    # for audit + offline comparison.
    if config.receiver_url:
        await _post_to_receiver(config.receiver_url, msg_dict, classification,
                                getattr(config, "receiver_token", ""))

    # Shadow Claude after the fast-path decision is already in flight. Logs
    # disagreement but never blocks the receiver POST. Skip if Claude was
    # already the primary classifier (no shadow needed).
    if used_fast_path:
        asyncio.create_task(
            _shadow_classify(msg_dict, chain, classification, config,
                             conn=conn, source_label=source_label),
            name=f"shadow-classify-{msg_dict['id']}",
        )


def _record_claude_shadow(conn: sqlite3.Connection, msg: dict, rule_cls: dict,
                          claude_cls: dict, disagree_fields: list) -> None:
    """Com a regra DECIDINDO (#74), grava o veredito do Claude em shadow na
    mesma `rule_shadow`. `primary_source = 'claude-shadow'` distingue do caso
    inverso (Claude decidiu, regra observou). `agree` segue a mesma leitura:
    1 concorda, 0 diverge — e `agree = 0` e o sinal para investigar."""
    try:
        conn.execute(
            "INSERT INTO rule_shadow (msg_id, evaluated_at, primary_kind, "
            "primary_source, rule_kind, rule_reason, declared, agree) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (msg["id"], datetime.now(timezone.utc).isoformat(),
             claude_cls.get("kind"), "claude-shadow", rule_cls.get("kind"),
             "divergem: " + ",".join(disagree_fields) if disagree_fields else "regra decidiu",
             None, 0 if disagree_fields else 1),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("[RULE-SHADOW] falha ao gravar shadow do Claude id=%s",
                         msg.get("id"))


async def _shadow_classify(msg_dict: dict, chain: list, fast_path: dict,
                           config, conn: Optional[sqlite3.Connection] = None,
                           source_label: str = "rule") -> None:
    """Run Claude in the background after a fast-path open, log any
    disagreement. Best-effort — never raises out of the task."""
    try:
        cls = await classifier.classify(
            msg_dict, chain,
            binary=config.claude_binary,
            model=config.claude_model,
            timeout_sec=config.claude_timeout,
            template=config.classifier_template,
        )
        if cls is None:
            return
        # Compare critical fields. Disagreement = different kind, symbol,
        # direction, or sl off by >0.5%.
        disagree_fields: list[str] = []
        # Em `chat` nada acontece a jusante: so o tipo importa. O Claude as
        # vezes preenche o ticker de um comentario de mercado.
        both_chat = cls.get("kind") == "chat" and fast_path.get("kind") == "chat"
        for f in (("kind",) if both_chat else ("kind", "symbol", "direction")):
            if cls.get(f) != fast_path.get(f):
                disagree_fields.append(f)
        fp_sl = fast_path.get("sl")
        cl_sl = cls.get("sl")
        if (isinstance(fp_sl, (int, float)) and isinstance(cl_sl, (int, float))
                and fp_sl > 0 and abs(fp_sl - cl_sl) / fp_sl > 0.005):
            disagree_fields.append("sl")
        if disagree_fields:
            logger.warning(
                "[FAST-PATH DISAGREE] id=%d fields=%s rule=%s claude=%s — "
                "fast-path already committed (audit only)",
                msg_dict.get("id"), disagree_fields,
                {f: fast_path.get(f) for f in disagree_fields},
                {f: cls.get(f) for f in disagree_fields},
            )
        if conn is not None and source_label == "rules":
            _record_claude_shadow(conn, msg_dict, fast_path, cls, disagree_fields)
    except Exception as e:
        logger.warning("shadow classify failed id=%d: %s",
                       msg_dict.get("id"), e)


async def _post_to_receiver(url: str, msg: dict, classification: dict,
                            token: str = "") -> None:
    """POST classified event to killers-receiver with bounded retry.

    `token` is the receiver's required ingress bearer. An empty token still
    posts — the receiver answers 401, which the 4xx branch below logs at ERROR
    and does NOT retry. That is the intended shape: a misconfigured token is a
    loud, immediate, non-trading failure rather than a silent retry storm.

    Bug discovered 2026-05-27 19:38: receiver crashed 500 on a real signal,
    observer logged and moved on, msg lost silently. Retry policy:
      - 3 attempts total
      - Retry on: any exception (network drop, timeout), 5xx, 429 (rate-limit)
      - Do NOT retry on: 4xx (client error — payload is broken, retrying
        won't help)
      - Backoff: 0s, 2s + jitter, 5s + jitter (jitter = ±20%)
    Final failure logs at ERROR level with msg_id so it's loud enough to
    notice in log review.

    Telethon's to_dict() leaves datetime objects + bytes inline; pre-serialize
    via json.dumps(default=str) and post as raw data so aiohttp doesn't trip
    on its own json encoder.
    """
    import aiohttp
    import random
    payload = {"msg": msg, "classification": classification}
    try:
        body_json = json.dumps(payload, default=str)
    except Exception as e:
        logger.error("[RECV] payload serialize failed msg_id=%s: %s",
                     msg.get("id"), e)
        return

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    backoffs = [0.0, 2.0, 5.0]
    last_err: Optional[str] = None
    for attempt, base_delay in enumerate(backoffs, start=1):
        if base_delay > 0:
            # ±20% jitter on the base
            delay = base_delay * random.uniform(0.8, 1.2)
            await asyncio.sleep(delay)
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    url, data=body_json,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as r:
                    body = await r.text()
                    if 200 <= r.status < 300:
                        logger.info("[RECV] %d msg_id=%s kind=%s body=%s "
                                    "(attempt %d)",
                                    r.status, msg.get("id"),
                                    classification.get("kind"),
                                    body[:200], attempt)
                        return
                    if 400 <= r.status < 500 and r.status != 429:
                        # Client error — payload broken, retrying won't help
                        logger.error(
                            "[RECV] %d msg_id=%s kind=%s body=%s — "
                            "4xx, NOT retrying",
                            r.status, msg.get("id"),
                            classification.get("kind"), body[:200],
                        )
                        return
                    # 5xx or 429 — retry
                    last_err = f"HTTP {r.status}: {body[:200]}"
                    logger.warning(
                        "[RECV] %d msg_id=%s attempt %d/%d — will retry: %s",
                        r.status, msg.get("id"), attempt, len(backoffs),
                        body[:200],
                    )
        except Exception as e:
            last_err = f"exception: {e}"
            logger.warning(
                "[RECV] post raised msg_id=%s attempt %d/%d: %s",
                msg.get("id"), attempt, len(backoffs), e,
            )

    # Exhausted retries
    logger.error(
        "[RECV] EXHAUSTED %d retries for msg_id=%s kind=%s — message LOST. "
        "Last error: %s",
        len(backoffs), msg.get("id"), classification.get("kind"), last_err,
    )


# ── Main loop ──────────────────────────────────────────────────────────────


async def _setup_channel(client, events, conn: sqlite3.Connection,
                         config: "Config", label: str, backfill: bool = True) -> None:
    """Resolve one channel, (optionally) backfill missed msgs, register new/edit
    handlers — each routed to its OWN conn/config (DB + receiver). Extracted so a
    single client/session can drive multiple channels (killers + insiders
    fan-out). Each call's handlers close over their own channel/conn/config (no
    leak). Handler bodies are wrapped so a per-message error is logged and never
    propagates — the feed always continues."""
    if config.channel_id_override:
        channel = int(config.channel_id_override)
        logger.info("[%s] channel id=%d (override) receiver=%s db=%s",
                    label, channel, config.receiver_url, config.db_path)
    else:
        ent = await client.get_entity(config.channel_username)
        channel = ent.id
        logger.info("[%s] resolved @%s → id=%d title=%r receiver=%s",
                    label, config.channel_username, channel,
                    getattr(ent, "title", "?"), config.receiver_url)

    if backfill:
        last_id = last_msg_id(conn)
        if last_id:
            logger.info("[%s] backfilling msgs > %d", label, last_id)
            async for msg in client.iter_messages(channel, min_id=last_id, limit=100):
                await process_message(client, channel, conn, config, msg.to_dict(), source="backfill")

    async def _handle(event, source):
        try:
            await process_message(client, channel, conn, config, event.message.to_dict(), source=source)
        except Exception:
            logger.exception("[%s] handler error (source=%s) — feed continues", label, source)

    @client.on(events.NewMessage(chats=[channel]))
    async def _on_new(event):
        await _handle(event, "new")

    @client.on(events.MessageEdited(chats=[channel]))
    async def _on_edit(event):
        await _handle(event, "edited")


def _insiders_config() -> "Optional[Config]":
    """Config for the INSIDERS fan-out, built from INSIDERS_* env and reusing the
    shared killers api/session/claude settings. None (disabled) unless
    INSIDERS_TG_CHANNEL_ID is set."""
    cid = os.getenv("INSIDERS_TG_CHANNEL_ID")
    if not cid:
        return None
    ins = Config()                       # re-reads shared api/session/claude env
    ins.channel_id_override = cid
    ins.channel_username = None
    ins.receiver_url = os.getenv("INSIDERS_RECEIVER_URL", "http://127.0.0.1:8090/event")
    ins.receiver_token = os.getenv("INSIDERS_RECEIVER_TOKEN", "")
    ins.db_path = os.getenv("INSIDERS_OBSERVER_DB", "/home/ubuntu/insiders-bot/state.sqlite")
    # Dennis / Market Mastery format ≠ Killers VIP. Use the insiders-tuned prompt
    # and disable the Killers-only strict-open rule parser (it would never match
    # Dennis's terse "$SYM LONG" calls anyway, and bypassing the tuned prompt on
    # a false match would mis-classify).
    ins.classifier_template = classifier.INSIDERS_PROMPT_TEMPLATE
    ins.use_fast_path = False
    # Mesma razao: as regras sao do formato Killers. Um sinal do Dennis nao tem
    # cabecalho `SIGNAL ID:`/`COIN:`, entao a regra o chamaria `chat` e cada
    # mensagem viraria uma divergencia falsa, poluindo a medicao.
    ins.shadow_rules = False
    ins.rules_primary = False
    return ins


async def run(config: Config, conn: sqlite3.Connection) -> None:
    from telethon import TelegramClient, events

    client = TelegramClient(config.session_path, config.api_id, config.api_hash)
    await client.start()
    me = await client.get_me()
    logger.info("auth OK as %s (id=%d phone=%s)", me.first_name, me.id, getattr(me, "phone", "?"))

    # Primary channel (killers).
    await _setup_channel(client, events, conn, config, "killers")

    # Optional INSIDERS fan-out on the SAME session/client (one account, two
    # channels — avoids a second session). Fully fault-isolated: any failure
    # resolving/backfilling the insiders channel is logged and CANNOT affect the
    # killers feed. Enabled only when INSIDERS_TG_CHANNEL_ID is set.
    try:
        ins = _insiders_config()
        if ins is not None:
            ins_conn = init_db(ins.db_path)
            # No backfill: the forward measurement starts from NOW, and skipping
            # the free-channel history keeps insiders load off the killers path.
            await _setup_channel(client, events, ins_conn, ins, "insiders", backfill=False)
    except Exception:
        logger.exception("[insiders] fan-out setup FAILED — killers feed unaffected")

    # Heartbeat
    async def heartbeat():
        while True:
            try:
                await asyncio.wait_for(client.get_me(), timeout=5.0)
                logger.info("[HB] alive — last_msg_id=%s", last_msg_id(conn))
            except Exception as e:
                logger.error("[HB] auth check failed: %s", e)
            await asyncio.sleep(config.heartbeat_sec)

    hb = asyncio.create_task(heartbeat())
    try:
        await client.run_until_disconnected()
    finally:
        hb.cancel()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        stream=sys.stdout,
    )
    config = Config()
    conn = init_db(config.db_path)
    asyncio.run(run(config, conn))


if __name__ == "__main__":
    main()
