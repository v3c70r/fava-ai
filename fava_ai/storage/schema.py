SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS conversations (
    id            TEXT PRIMARY KEY,
    title         TEXT,
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK(role IN ('system','user','assistant','tool')),
    content         TEXT,
    tool_calls      TEXT,
    tool_call_id    TEXT,
    name            TEXT,
    token_count     INTEGER,
    metadata        TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS traces (
    id              TEXT PRIMARY KEY,
    message_id      TEXT NOT NULL REFERENCES messages(id),
    step_index      INTEGER NOT NULL,
    step_type       TEXT NOT NULL CHECK(step_type IN ('plan','tool_call','synthesis')),
    tool_name       TEXT,
    tool_input      TEXT,
    tool_output     TEXT,
    bql_query       TEXT,
    wiki_sources    TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    error           TEXT
);

CREATE INDEX IF NOT EXISTS idx_traces_message ON traces(message_id);

CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_registry (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    version     TEXT,
    description TEXT,
    category    TEXT,
    file_path   TEXT,
    metadata    TEXT,
    enabled     INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
"""

MIGRATIONS = {
    1: DDL,
}
