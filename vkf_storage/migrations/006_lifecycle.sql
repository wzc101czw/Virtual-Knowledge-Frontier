-- VKF 0.2.4: irreversible database actions have an explicit plan, backup and
-- a recovery manifest for still-existing Obsidian projections.
CREATE TABLE IF NOT EXISTS lifecycle_events (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL CHECK(scope IN ('derived','extraction','conversation','all')),
    conversation_id TEXT,
    backup_path TEXT NOT NULL,
    plan_token TEXT NOT NULL,
    counts_json TEXT NOT NULL CHECK(json_valid(counts_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE TABLE IF NOT EXISTS lifecycle_retired_files (
    id TEXT PRIMARY KEY,
    vault_key TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    exported_sha256 TEXT NOT NULL,
    event_id TEXT NOT NULL REFERENCES lifecycle_events(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','archived','missing')),
    archive_path TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE UNIQUE INDEX IF NOT EXISTS unique_pending_retirement ON lifecycle_retired_files(vault_key,relative_path) WHERE status='pending';
CREATE INDEX IF NOT EXISTS idx_retired_vault ON lifecycle_retired_files(vault_key,status);
PRAGMA user_version=6;
