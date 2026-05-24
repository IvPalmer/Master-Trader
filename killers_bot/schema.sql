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
