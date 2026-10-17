-- Version 8: validated and source-keyed partial research-map checkpoints.
-- Cached model output is private cognitive data inside the user's SQLite DB.
CREATE TABLE research_map_checkpoints (
  key TEXT PRIMARY KEY CHECK(length(key) = 64),
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  stage TEXT NOT NULL CHECK(stage IN ('fragment','global')),
  model_id TEXT NOT NULL,
  chunk_index INTEGER NOT NULL CHECK(chunk_index >= 0),
  chunks_total INTEGER NOT NULL CHECK(chunks_total >= 1),
  result_json TEXT NOT NULL CHECK(json_valid(result_json)),
  result_sha256 TEXT NOT NULL CHECK(length(result_sha256) = 64),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE INDEX research_checkpoint_conversation_idx
  ON research_map_checkpoints(conversation_id,stage,chunk_index);
PRAGMA user_version=8;
