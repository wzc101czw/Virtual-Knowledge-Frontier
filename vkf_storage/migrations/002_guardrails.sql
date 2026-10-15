-- Additional append-only protections. Version 1 databases are upgraded in place.
CREATE TRIGGER IF NOT EXISTS immutable_candidate_payload
BEFORE UPDATE OF extraction_run_id,proposal_index,kind,title,body,proposed_relations_json ON candidates
WHEN OLD.state <> 'pending'
BEGIN SELECT RAISE(ABORT,'resolved candidate payload is immutable'); END;

CREATE TRIGGER IF NOT EXISTS append_only_object_versions_update
BEFORE UPDATE ON object_versions
BEGIN SELECT RAISE(ABORT,'object version history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS append_only_object_versions_delete
BEFORE DELETE ON object_versions
BEGIN SELECT RAISE(ABORT,'object version history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS append_only_audit_update
BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT,'audit history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS append_only_audit_delete
BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT,'audit history is append-only'); END;

-- A recognized answer must not become invisible merely by changing relation endpoints.
-- Existing version 1 guards already prevent deleting/archiving the final answer.
PRAGMA user_version = 2;
