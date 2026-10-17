-- v0.3.0: research-centered structure, separate unreviewed proposals from
-- accepted research space models, with evidence-anchored views and evaluations.
CREATE TABLE research_spaces (
 id TEXT PRIMARY KEY,
 title TEXT NOT NULL CHECK(length(trim(title))>0),
 central_question TEXT NOT NULL CHECK(length(trim(central_question))>0),
 goal TEXT NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>=1),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE TABLE research_space_versions (
 space_id TEXT NOT NULL REFERENCES research_spaces(id) ON DELETE CASCADE,
 revision INTEGER NOT NULL CHECK(revision>=1),
 snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
 reason TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 PRIMARY KEY(space_id,revision)
) STRICT;
CREATE TABLE research_maps (
 id TEXT PRIMARY KEY,
 conversation_id TEXT NOT NULL REFERENCES conversations(id),
 target_space_id TEXT REFERENCES research_spaces(id),
 expected_space_revision INTEGER,
 mode TEXT NOT NULL CHECK(mode IN ('heuristic','llm','manual')),
 model_id TEXT NOT NULL DEFAULT '',
 prompt_version TEXT NOT NULL,
 content_fingerprint TEXT NOT NULL,
 input_coverage REAL NOT NULL CHECK(input_coverage>=0 AND input_coverage<=1),
 plan_json TEXT NOT NULL CHECK(json_valid(plan_json)),
 revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>=1),
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','applied','rejected')),
 reviewed_space_id TEXT REFERENCES research_spaces(id),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 reviewed_at TEXT,
 UNIQUE(conversation_id,target_space_id,mode,model_id,content_fingerprint)
) STRICT;
CREATE INDEX research_maps_status_idx ON research_maps(status,created_at);
CREATE TABLE research_contexts (
 id TEXT PRIMARY KEY,
 title TEXT NOT NULL CHECK(length(trim(title))>0),
 focus TEXT NOT NULL DEFAULT '',
 assumptions_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(assumptions_json)),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE TABLE research_space_contexts (
 space_id TEXT NOT NULL REFERENCES research_spaces(id) ON DELETE CASCADE,
 context_id TEXT NOT NULL REFERENCES research_contexts(id) ON DELETE CASCADE,
 PRIMARY KEY(space_id,context_id)
) STRICT;
CREATE TABLE research_references (
 id TEXT PRIMARY KEY,
 title TEXT NOT NULL CHECK(length(trim(title))>0),
 identifier TEXT NOT NULL DEFAULT '',
 source_type TEXT NOT NULL DEFAULT 'other',
 verification_status TEXT NOT NULL DEFAULT 'unverified' CHECK(verification_status IN ('unverified','verified','disputed')),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE TABLE contextual_views (
 id TEXT PRIMARY KEY,
 space_id TEXT NOT NULL REFERENCES research_spaces(id) ON DELETE CASCADE,
 context_id TEXT NOT NULL REFERENCES research_contexts(id) ON DELETE CASCADE,
 role TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('knowledge','idea','understanding','question','cross_insight','reference')),
 statement TEXT NOT NULL CHECK(length(trim(statement))>0),
 attribution TEXT NOT NULL CHECK(attribution IN ('user','assistant','mixed','external','unknown')),
 epistemic_status TEXT NOT NULL CHECK(epistemic_status IN ('hypothesis','reported','supported','disputed','unknown')),
 parent_view_id TEXT REFERENCES contextual_views(id),
 candidate_id TEXT REFERENCES candidates(id),
 object_id TEXT REFERENCES cognitive_objects(id),
 reference_id TEXT REFERENCES research_references(id),
 fingerprint TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 UNIQUE(space_id,context_id,fingerprint),
 CHECK(candidate_id IS NULL OR object_id IS NULL)
) STRICT;
CREATE INDEX contextual_views_space_idx ON contextual_views(space_id,context_id);
CREATE TABLE view_evidence_spans (
 view_id TEXT NOT NULL REFERENCES contextual_views(id) ON DELETE CASCADE,
 message_id TEXT NOT NULL REFERENCES messages(id),
 start_char INTEGER NOT NULL CHECK(start_char>=0),
 end_char INTEGER NOT NULL CHECK(end_char>start_char),
 PRIMARY KEY(view_id,message_id,start_char,end_char)
) STRICT;
CREATE TABLE coverage_dimensions (
 id TEXT PRIMARY KEY,
 space_id TEXT NOT NULL REFERENCES research_spaces(id) ON DELETE CASCADE,
 label TEXT NOT NULL CHECK(length(trim(label))>0),
 status TEXT NOT NULL CHECK(status IN ('addressed','open','unknown')),
 note TEXT NOT NULL DEFAULT '',
 UNIQUE(space_id,label)
) STRICT;
CREATE TABLE compatibility_assessments (
 id TEXT PRIMARY KEY,
 space_id TEXT NOT NULL REFERENCES research_spaces(id) ON DELETE CASCADE,
 context_a TEXT NOT NULL REFERENCES research_contexts(id),
 context_b TEXT NOT NULL REFERENCES research_contexts(id),
 verdict TEXT NOT NULL CHECK(verdict IN ('compatible','incompatible','needs_mapping','underdetermined','unknown')),
 mappings_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(mappings_json)),
 checks_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(checks_json)),
 rationale TEXT NOT NULL CHECK(length(trim(rationale))>0),
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','rejected')),
 fingerprint TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 CHECK(context_a<>context_b)
) STRICT;
CREATE TABLE synthesis_proposals (
 id TEXT PRIMARY KEY,
 space_id TEXT NOT NULL REFERENCES research_spaces(id) ON DELETE CASCADE,
 title TEXT NOT NULL CHECK(length(trim(title))>0),
 mechanism TEXT NOT NULL CHECK(length(trim(mechanism))>0),
 assumptions_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(assumptions_json)),
 limitations_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(limitations_json)),
 validation TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','rejected')),
 fingerprint TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE TABLE synthesis_members (
 synthesis_id TEXT NOT NULL REFERENCES synthesis_proposals(id) ON DELETE CASCADE,
 view_id TEXT NOT NULL REFERENCES contextual_views(id),
 PRIMARY KEY(synthesis_id,view_id)
) STRICT;
CREATE TABLE frontier_obstructions (
 id TEXT PRIMARY KEY,
 space_id TEXT NOT NULL REFERENCES research_spaces(id) ON DELETE CASCADE,
 kind TEXT NOT NULL CHECK(kind IN ('coverage_gap','compatibility_gap','evidence_gap','translation_gap','synthesis_gap')),
 question TEXT NOT NULL CHECK(length(trim(question))>0),
 blocking_what TEXT NOT NULL,
 next_test TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','rejected')),
 fingerprint TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE TABLE researcher_feedback (
 id TEXT PRIMARY KEY,
 map_id TEXT NOT NULL REFERENCES research_maps(id),
 map_revision INTEGER NOT NULL,
 granularity TEXT NOT NULL CHECK(granularity IN ('too_fragmented','balanced','too_coarse','missing_important')),
 note TEXT NOT NULL DEFAULT '',
 structure_score INTEGER CHECK(structure_score BETWEEN 1 AND 5),
 question_coverage_score INTEGER CHECK(question_coverage_score BETWEEN 1 AND 5),
 provenance_score INTEGER CHECK(provenance_score BETWEEN 1 AND 5),
 missing_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(missing_json)),
 edits_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(edits_json)),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE INDEX feedback_map_idx ON researcher_feedback(map_id,created_at);
PRAGMA user_version=7;
