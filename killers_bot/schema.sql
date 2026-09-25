CREATE TABLE IF NOT EXISTS raw_messages (
    msg_id          INTEGER PRIMARY KEY,
    received_at     TEXT NOT NULL,
    posted_at       TEXT,
    edited_at       TEXT,
    reply_to_msg_id INTEGER,
    text            TEXT,
    raw_json        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS classifications (
    msg_id      INTEGER PRIMARY KEY REFERENCES raw_messages(msg_id),
    classified_at TEXT NOT NULL,
    kind        TEXT NOT NULL,
    signal_id   INTEGER,
    symbol      TEXT,
    direction   TEXT,
    entry_lo    REAL,
    entry_hi    REAL,
    sl          REAL,
    sl_str      TEXT,
    tp          REAL,
    pct         REAL,
    confidence  REAL,
    notes       TEXT,
    raw_json    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_positions (
    -- Key: (signal_id, symbol) within an open month bucket; recycled IDs get a fresh row.
    pos_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id       INTEGER,
    symbol          TEXT NOT NULL,
    direction       TEXT NOT NULL,
    state           TEXT NOT NULL,           -- pending / open / closed
    open_msg_id     INTEGER NOT NULL,
    open_date       TEXT NOT NULL,
    entry_lo        REAL,
    entry_hi        REAL,
    entry_mid       REAL,
    sl              REAL,
    sl_distance_pct REAL,
    position_notional REAL,
    leverage        REAL,
    close_msg_id    INTEGER,
    close_date      TEXT,
    close_reason    TEXT,                    -- tp_partial / tp_full / sl_hit / manual
    realized_pct    REAL,
    realized_pnl    REAL,
    last_event_at   TEXT
);

CREATE TABLE IF NOT EXISTS position_events (
    event_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    pos_id       INTEGER NOT NULL REFERENCES paper_positions(pos_id),
    msg_id       INTEGER NOT NULL,
    event_at     TEXT NOT NULL,
    kind         TEXT NOT NULL,
    pct          REAL,
    notes        TEXT
);

CREATE INDEX IF NOT EXISTS idx_pos_signal_symbol ON paper_positions(signal_id, symbol);
CREATE INDEX IF NOT EXISTS idx_pos_state ON paper_positions(state);
CREATE INDEX IF NOT EXISTS idx_events_pos ON position_events(pos_id);

-- ── Shadow do classificador de regras (#62) ────────────────────────────────
-- Observacional. Nada aqui altera o que e encaminhado ao receiver.

-- Quantos alvos o OPEN de cada sinal declarou. E o estado que separa
-- fechamento parcial de total numa mensagem de alvo atingido. Append-only:
-- SIGNAL IDs reciclam, entao a leitura casa a linha mais recente ANTERIOR
-- a mensagem sendo avaliada.
CREATE TABLE IF NOT EXISTS signal_targets (
    row_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_key TEXT NOT NULL,            -- "sid:2143" ou "gem:ZIG"
    symbol     TEXT,                     -- parte da chave de instancia
    declared   INTEGER NOT NULL,
    msg_id     INTEGER NOT NULL,
    posted_at  TEXT
);

-- Append-only de proposito: uma mensagem editada e reavaliada, e sobrescrever
-- apagaria justamente a divergencia que esta tabela existe para registrar.
CREATE TABLE IF NOT EXISTS rule_shadow (
    row_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id        INTEGER NOT NULL REFERENCES raw_messages(msg_id),
    evaluated_at  TEXT NOT NULL,
    primary_kind  TEXT NOT NULL,         -- o que de fato seguiu adiante
    primary_source TEXT NOT NULL,        -- rule (strict_open) | claude
    rule_kind     TEXT,                  -- NULL = a regra recusou
    rule_reason   TEXT NOT NULL,
    declared      INTEGER,               -- contagem usada, quando houve
    agree         INTEGER NOT NULL       -- 1 concorda | 0 diverge | -1 recusou
);

CREATE INDEX IF NOT EXISTS idx_signal_targets_key ON signal_targets(signal_key, symbol, msg_id);
CREATE INDEX IF NOT EXISTS idx_rule_shadow_agree ON rule_shadow(agree);
CREATE INDEX IF NOT EXISTS idx_rule_shadow_msg ON rule_shadow(msg_id, row_id);

-- ── Revisoes de mensagens editadas (#64) ───────────────────────────────────
-- `raw_messages` e `classifications` continuam "a mais recente vence" (INSERT
-- OR REPLACE por msg_id) porque o resto do codigo as le assim. Estas tabelas
-- guardam CADA gravacao, append-only, para que uma edicao nao apague a entrada
-- nem a classificacao originais. A versao autoritativa de uma mensagem e a
-- linha da tabela principal (= a revisao de maior rev_id).
-- Toda chamada de persist grava uma revisao: reentrega da mesma mensagem sem
-- edicao (backfill, reinicio) e busca de mensagem-pai na cadeia de resposta
-- tambem geram linha. E intencional: cada uma foi uma leitura real. Distinga
-- edicoes por `edited_at`.
CREATE TABLE IF NOT EXISTS raw_message_revisions (
    rev_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id          INTEGER NOT NULL,
    received_at     TEXT NOT NULL,
    posted_at       TEXT,
    edited_at       TEXT,                -- NULL = versao original
    reply_to_msg_id INTEGER,
    text            TEXT,
    raw_json        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS classification_revisions (
    rev_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id        INTEGER NOT NULL,
    classified_at TEXT NOT NULL,
    kind          TEXT NOT NULL,
    signal_id     INTEGER,
    symbol        TEXT,
    direction     TEXT,
    entry_lo      REAL,
    entry_hi      REAL,
    sl            REAL,
    sl_str        TEXT,
    tp            REAL,
    pct           REAL,
    confidence    REAL,
    notes         TEXT,
    raw_json      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_rev_msg ON raw_message_revisions(msg_id, rev_id);
CREATE INDEX IF NOT EXISTS idx_cls_rev_msg ON classification_revisions(msg_id, rev_id);

-- ── Gate de confianca em SHADOW (#65) ──────────────────────────────────────
-- Veredito que o gate daria a cada classificacao do CLAUDE antes do
-- encaminhamento. Observacional: nada aqui bloqueia. Decisoes das regras
-- (strict_open / rules_classifier) nao geram linha. Append-only: edicao ou
-- reentrega geram nova linha. Ligar enforcing e mudanca posterior (#62/#65).
CREATE TABLE IF NOT EXISTS confidence_gate (
    row_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id                INTEGER NOT NULL,
    evaluated_at          TEXT NOT NULL,
    kind                  TEXT,              -- NULL = kind ausente/nao string
    source                TEXT NOT NULL,     -- claude
    confidence            REAL,              -- NULL = ausente ou nao numerica
    threshold             REAL,              -- NULL = sem limiar (desligado / kind desconhecido)
    verdict               TEXT NOT NULL,     -- pass | would_block | disabled
    reason                TEXT NOT NULL,
    mode                  TEXT NOT NULL,     -- shadow
    config_schema_version INTEGER NOT NULL   -- 0 = arquivo de config ausente
);

CREATE INDEX IF NOT EXISTS idx_conf_gate_msg ON confidence_gate(msg_id, row_id);
CREATE INDEX IF NOT EXISTS idx_conf_gate_verdict ON confidence_gate(verdict);
