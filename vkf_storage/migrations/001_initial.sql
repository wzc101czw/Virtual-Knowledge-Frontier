-- VKF Core v0.1: SQLite 3.38+ (FTS5 trigram). Application executes PRAGMA foreign_keys=ON on every connection.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS import_batches (
    id TEXT PRIMARY KEY,
    format TEXT NOT NULL,
    raw_sha256 TEXT NOT NULL UNIQUE,
    archive_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('live','chatgpt','claude','other')),
    title TEXT NOT NULL DEFAULT '',
    normalized_sha256 TEXT UNIQUE,
    import_batch_id TEXT REFERENCES import_batches(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    turn_index INTEGER NOT NULL CHECK (turn_index >= 0),
    role TEXT NOT NULL CHECK (role IN ('system','user','assistant','tool')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (conversation_id,turn_index)
) STRICT;

CREATE TABLE IF NOT EXISTS extraction_runs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    start_turn INTEGER NOT NULL CHECK (start_turn >= 0),
    end_turn INTEGER NOT NULL,
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','running','completed','failed')),
    error_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (end_turn >= start_turn)
) STRICT;

CREATE TABLE IF NOT EXISTS cognitive_objects (
    row_id INTEGER PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK (kind IN ('knowledge','idea','understanding','question','cross_insight')),
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    body TEXT NOT NULL CHECK (length(trim(body)) > 0),
    epistemic_status TEXT NOT NULL DEFAULT 'tentative'
        CHECK (epistemic_status IN ('asserted','tentative','disputed','not_applicable')),
    understanding_level TEXT CHECK (understanding_level IN ('provisional','articulated')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','challenged','archived')),
    origin_actor TEXT NOT NULL CHECK (origin_actor IN ('user','model','mixed')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    uncertainty_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK ((kind = 'understanding' AND understanding_level IS NOT NULL)
       OR (kind <> 'understanding' AND understanding_level IS NULL)),
    CHECK ((kind = 'question' AND epistemic_status = 'not_applicable')
       OR (kind <> 'question' AND epistemic_status <> 'not_applicable'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_objects_kind_status ON cognitive_objects(kind,status);
CREATE TRIGGER IF NOT EXISTS immutable_object_kind
BEFORE UPDATE OF kind ON cognitive_objects
WHEN OLD.kind <> NEW.kind BEGIN
    SELECT RAISE(ABORT,'object kind is immutable; create a new object');
END;

-- Operational record of model requests; logs object IDs/versions, not full private request bodies.
CREATE TABLE IF NOT EXISTS model_calls (
    id TEXT PRIMARY KEY,
    purpose TEXT NOT NULL CHECK (purpose IN ('chat','extraction','link','frontier')),
    conversation_id TEXT REFERENCES conversations(id),
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    context_policy_version TEXT NOT NULL DEFAULT 'v1',
    selected_objects_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(selected_objects_json)),
    input_fingerprint TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('running','completed','failed')),
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    error_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY,
    extraction_run_id TEXT NOT NULL REFERENCES extraction_runs(id),
    proposal_index INTEGER NOT NULL CHECK (proposal_index >= 0),
    kind TEXT NOT NULL CHECK (kind IN ('knowledge','idea','understanding','question','cross_insight')),
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    body TEXT NOT NULL CHECK (length(trim(body)) > 0),
    proposed_relations_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(proposed_relations_json)),
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','approved','merged','rejected')),
    resolved_object_id TEXT REFERENCES cognitive_objects(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (extraction_run_id,proposal_index),
    CHECK ((state IN ('approved','merged') AND resolved_object_id IS NOT NULL)
        OR (state IN ('pending','rejected') AND resolved_object_id IS NULL))
) STRICT;
CREATE INDEX IF NOT EXISTS idx_candidates_state ON candidates(state);
CREATE TRIGGER IF NOT EXISTS candidate_terminal_state
BEFORE UPDATE OF state ON candidates
WHEN OLD.state <> 'pending' AND NEW.state <> OLD.state BEGIN
    SELECT RAISE(ABORT,'candidate decision is terminal');
END;

CREATE TABLE IF NOT EXISTS candidate_sources (
    candidate_id TEXT NOT NULL REFERENCES candidates(id),
    message_id TEXT NOT NULL REFERENCES messages(id),
    PRIMARY KEY (candidate_id,message_id)
) STRICT;

CREATE TABLE IF NOT EXISTS object_sources (
    object_id TEXT NOT NULL REFERENCES cognitive_objects(id),
    message_id TEXT NOT NULL REFERENCES messages(id),
    source_role TEXT NOT NULL CHECK (source_role IN ('origin','support','challenge')),
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (object_id,message_id,source_role)
) STRICT;
CREATE INDEX IF NOT EXISTS idx_object_sources_msg ON object_sources(message_id);

CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    from_object_id TEXT NOT NULL REFERENCES cognitive_objects(id),
    to_object_id TEXT NOT NULL REFERENCES cognitive_objects(id),
    kind TEXT NOT NULL CHECK (kind IN ('depends_on','supports','contradicts','analogous_to','synthesizes','raises','answers')),
    rationale TEXT NOT NULL CHECK (length(trim(rationale)) > 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','challenged','archived')),
    origin_actor TEXT NOT NULL CHECK (origin_actor IN ('user','model','mixed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (from_object_id,to_object_id,kind),
    CHECK (from_object_id <> to_object_id),
    CHECK (kind NOT IN ('contradicts','analogous_to') OR from_object_id < to_object_id)
) STRICT;
CREATE INDEX IF NOT EXISTS idx_relations_to ON relations(to_object_id,kind);
CREATE INDEX IF NOT EXISTS idx_relations_from ON relations(from_object_id,kind);

CREATE TRIGGER IF NOT EXISTS validate_relation_insert BEFORE INSERT ON relations BEGIN
    SELECT CASE
        WHEN NEW.kind IN ('raises','answers') AND NOT EXISTS
            (SELECT 1 FROM cognitive_objects WHERE id=NEW.to_object_id AND kind='question')
        THEN RAISE(ABORT,'raises/answers must target question')
        WHEN NEW.kind='synthesizes' AND NOT EXISTS
            (SELECT 1 FROM cognitive_objects WHERE id=NEW.from_object_id AND kind IN ('cross_insight','understanding'))
        THEN RAISE(ABORT,'synthesizes source must be insight or understanding')
    END;
END;

CREATE TRIGGER IF NOT EXISTS validate_relation_update BEFORE UPDATE OF kind,from_object_id,to_object_id ON relations BEGIN
    SELECT CASE
        WHEN NEW.kind IN ('raises','answers') AND NOT EXISTS
            (SELECT 1 FROM cognitive_objects WHERE id=NEW.to_object_id AND kind='question')
        THEN RAISE(ABORT,'raises/answers must target question')
        WHEN NEW.kind='synthesizes' AND NOT EXISTS
            (SELECT 1 FROM cognitive_objects WHERE id=NEW.from_object_id AND kind IN ('cross_insight','understanding'))
        THEN RAISE(ABORT,'synthesizes source must be insight or understanding')
    END;
END;

CREATE TRIGGER IF NOT EXISTS protect_answer_relation_update
BEFORE UPDATE OF status,kind,to_object_id ON relations
WHEN OLD.kind='answers' AND OLD.status='active'
  AND (NEW.kind<>'answers' OR NEW.status<>'active' OR NEW.to_object_id<>OLD.to_object_id)
  AND EXISTS (SELECT 1 FROM question_states WHERE object_id=OLD.to_object_id AND state='answered' AND trim(resolution_note)='')
  AND NOT EXISTS (SELECT 1 FROM relations WHERE id<>OLD.id AND to_object_id=OLD.to_object_id AND kind='answers' AND status='active')
BEGIN SELECT RAISE(ABORT,'cannot remove the final answer of an answered question'); END;

CREATE TRIGGER IF NOT EXISTS protect_answer_relation_delete
BEFORE DELETE ON relations
WHEN OLD.kind='answers' AND OLD.status='active'
  AND EXISTS (SELECT 1 FROM question_states WHERE object_id=OLD.to_object_id AND state='answered' AND trim(resolution_note)='')
  AND NOT EXISTS (SELECT 1 FROM relations WHERE id<>OLD.id AND to_object_id=OLD.to_object_id AND kind='answers' AND status='active')
BEGIN SELECT RAISE(ABORT,'cannot delete the final answer of an answered question'); END;

CREATE TABLE IF NOT EXISTS question_states (
    object_id TEXT PRIMARY KEY REFERENCES cognitive_objects(id),
    state TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open','exploring','answered','parked')),
    resolution_note TEXT NOT NULL DEFAULT '',
    last_activated_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

CREATE TRIGGER IF NOT EXISTS question_state_type_insert BEFORE INSERT ON question_states BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM cognitive_objects WHERE id=NEW.object_id AND kind='question')
        THEN RAISE(ABORT,'question_states requires question object') END;
    SELECT CASE WHEN NEW.state='answered' AND length(trim(NEW.resolution_note))=0
       AND NOT EXISTS (SELECT 1 FROM relations WHERE to_object_id=NEW.object_id AND kind='answers' AND status='active')
       THEN RAISE(ABORT,'answered question requires answer or resolution note') END;
END;
CREATE TRIGGER IF NOT EXISTS question_state_type_update BEFORE UPDATE ON question_states BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM cognitive_objects WHERE id=NEW.object_id AND kind='question')
        THEN RAISE(ABORT,'question_states requires question object') END;
    SELECT CASE WHEN NEW.state='answered' AND length(trim(NEW.resolution_note))=0
       AND NOT EXISTS (SELECT 1 FROM relations WHERE to_object_id=NEW.object_id AND kind='answers' AND status='active')
       THEN RAISE(ABORT,'answered question requires answer or resolution note') END;
END;

CREATE TRIGGER IF NOT EXISTS question_state_transition
BEFORE UPDATE OF state ON question_states
WHEN NOT (
    OLD.state=NEW.state
    OR (OLD.state='open' AND NEW.state IN ('exploring','answered','parked'))
    OR (OLD.state='exploring' AND NEW.state IN ('open','answered','parked'))
    OR (OLD.state='answered' AND NEW.state='open')
    OR (OLD.state='parked' AND NEW.state='open')
)
BEGIN SELECT RAISE(ABORT,'invalid question state transition'); END;

CREATE TABLE IF NOT EXISTS object_versions (
    object_id TEXT NOT NULL REFERENCES cognitive_objects(id),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    snapshot_json TEXT NOT NULL CHECK (json_valid(snapshot_json)),
    change_reason TEXT NOT NULL CHECK (length(trim(change_reason)) > 0),
    actor TEXT NOT NULL CHECK (actor IN ('user','workflow')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (object_id,revision)
) STRICT;

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('object','question','relation','candidate','conversation','frontier')),
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL CHECK (actor IN ('user','workflow')),
    payload_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_events(entity_type,entity_id,created_at);

CREATE TABLE IF NOT EXISTS frontier_suggestions (
    id TEXT PRIMARY KEY,
    source_object_id TEXT NOT NULL REFERENCES cognitive_objects(id),
    question_object_id TEXT NOT NULL REFERENCES cognitive_objects(id),
    signal TEXT NOT NULL CHECK (signal IN ('new_relevance','contradiction','cross_domain','missing_premise')),
    rationale TEXT NOT NULL CHECK (length(trim(rationale)) > 0),
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','accepted','dismissed','snoozed')),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE TRIGGER IF NOT EXISTS frontier_question_type BEFORE INSERT ON frontier_suggestions BEGIN
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM cognitive_objects WHERE id=NEW.question_object_id AND kind='question')
    THEN RAISE(ABORT,'frontier suggestion target must be question') END;
END;

-- Simple, explicit index. 3+ Chinese characters supported; short queries use LIKE fallback.
CREATE VIRTUAL TABLE IF NOT EXISTS object_fts USING fts5(title,body,tokenize='trigram');
CREATE TRIGGER IF NOT EXISTS fts_objects_insert AFTER INSERT ON cognitive_objects BEGIN
    INSERT INTO object_fts(rowid,title,body) VALUES (NEW.row_id,NEW.title,NEW.body);
END;
CREATE TRIGGER IF NOT EXISTS fts_objects_update AFTER UPDATE OF title,body ON cognitive_objects BEGIN
    DELETE FROM object_fts WHERE rowid=OLD.row_id;
    INSERT INTO object_fts(rowid,title,body) VALUES (NEW.row_id,NEW.title,NEW.body);
END;
CREATE TRIGGER IF NOT EXISTS fts_objects_delete AFTER DELETE ON cognitive_objects BEGIN
    DELETE FROM object_fts WHERE rowid=OLD.row_id;
END;

PRAGMA user_version = 1;
