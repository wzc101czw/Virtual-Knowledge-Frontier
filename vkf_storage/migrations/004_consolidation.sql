-- v0.2.0: consolidation proposals, provenance for extraction segments, and topic clusters.
-- No automatic change to already approved cognitive objects.
CREATE TABLE IF NOT EXISTS extraction_segments (
    extraction_run_id TEXT NOT NULL REFERENCES extraction_runs(id),
    message_id TEXT NOT NULL REFERENCES messages(id),
    start_char INTEGER NOT NULL CHECK (start_char >= 0),
    end_char INTEGER NOT NULL CHECK (end_char > start_char),
    PRIMARY KEY(extraction_run_id,message_id,start_char,end_char)
) STRICT;
CREATE INDEX IF NOT EXISTS idx_segments_message ON extraction_segments(message_id,start_char);

CREATE TABLE IF NOT EXISTS candidate_attributions (
    candidate_id TEXT PRIMARY KEY REFERENCES candidates(id),
    source_actor TEXT NOT NULL CHECK(source_actor IN ('user','assistant','mixed','unknown')),
    evidence_note TEXT NOT NULL DEFAULT ''
) STRICT;

CREATE TABLE IF NOT EXISTS consolidation_reviews (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES candidates(id),
    target_candidate_id TEXT REFERENCES candidates(id),
    target_object_id TEXT REFERENCES cognitive_objects(id),
    decision TEXT NOT NULL CHECK (decision IN ('SAME','REFINES','CONTRADICTS','RELATED','NEW','CROSS_DOMAIN','DISCARD')),
    score REAL NOT NULL CHECK (score >= 0 AND score <= 1),
    rationale TEXT NOT NULL CHECK (length(trim(rationale)) > 0),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','applied','dismissed')),
    policy_version TEXT NOT NULL,
    input_signature TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    decided_at TEXT,
    CHECK (NOT (target_candidate_id IS NOT NULL AND target_object_id IS NOT NULL)),
    CHECK ((decision IN ('NEW','DISCARD') AND target_candidate_id IS NULL AND target_object_id IS NULL)
      OR (decision NOT IN ('NEW','DISCARD') AND (target_candidate_id IS NOT NULL OR target_object_id IS NOT NULL))),
    CHECK (candidate_id IS NOT target_candidate_id)
) STRICT;
CREATE INDEX IF NOT EXISTS idx_reviews_status ON consolidation_reviews(status,created_at);
CREATE INDEX IF NOT EXISTS idx_reviews_candidate ON consolidation_reviews(candidate_id);

CREATE TABLE IF NOT EXISTS candidate_equivalences (
    duplicate_candidate_id TEXT PRIMARY KEY REFERENCES candidates(id),
    canonical_candidate_id TEXT NOT NULL REFERENCES candidates(id),
    review_id TEXT NOT NULL UNIQUE REFERENCES consolidation_reviews(id),
    CHECK (duplicate_candidate_id <> canonical_candidate_id)
) STRICT;

CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL CHECK (length(trim(label)) > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE TABLE IF NOT EXISTS candidate_topics (
    candidate_id TEXT NOT NULL REFERENCES candidates(id),
    topic_id TEXT NOT NULL REFERENCES topics(id),
    PRIMARY KEY(candidate_id,topic_id)
) STRICT;
CREATE TABLE IF NOT EXISTS object_topics (
    object_id TEXT NOT NULL REFERENCES cognitive_objects(id),
    topic_id TEXT NOT NULL REFERENCES topics(id),
    PRIMARY KEY(object_id,topic_id)
) STRICT;
CREATE INDEX IF NOT EXISTS idx_candidate_topics_topic ON candidate_topics(topic_id);
CREATE INDEX IF NOT EXISTS idx_object_topics_topic ON object_topics(topic_id);

PRAGMA user_version=4;
