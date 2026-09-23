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
