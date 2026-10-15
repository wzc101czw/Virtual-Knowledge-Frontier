-- VKF Storage Core v0.1.1, schema version 3.
-- The bridge is a projection: committed cognitive objects remain authoritative in SQLite.
CREATE TABLE IF NOT EXISTS conversation_origins (
    source TEXT NOT NULL CHECK(source IN ('live','chatgpt','claude','other')),
    external_key TEXT NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    source_format TEXT NOT NULL,
    original_title TEXT NOT NULL DEFAULT '',
    imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(source, external_key)
) STRICT;
CREATE TABLE IF NOT EXISTS message_import_metadata (
    message_id TEXT PRIMARY KEY REFERENCES messages(id),
    source_timestamp TEXT NOT NULL DEFAULT '',
    external_message_id TEXT NOT NULL DEFAULT ''
) STRICT;
CREATE INDEX IF NOT EXISTS idx_conversation_origins_conv ON conversation_origins(conversation_id);

CREATE TABLE IF NOT EXISTS obsidian_bridge_state (
    vault_key TEXT NOT NULL,
    object_id TEXT NOT NULL REFERENCES cognitive_objects(id),
    relative_path TEXT NOT NULL,
    exported_revision INTEGER NOT NULL CHECK(exported_revision >= 1),
    exported_sha256 TEXT NOT NULL,
    managed_prefix TEXT NOT NULL,
    managed_suffix TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(vault_key, object_id),
    UNIQUE(vault_key, relative_path)
) STRICT;
CREATE TABLE IF NOT EXISTS obsidian_readonly_state (
    vault_key TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    exported_sha256 TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(vault_key, relative_path)
) STRICT;
PRAGMA user_version=3;
