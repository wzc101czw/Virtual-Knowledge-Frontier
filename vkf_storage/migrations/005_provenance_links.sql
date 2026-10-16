-- v0.2.3: Distinguish local dialogue elaboration from historical consolidation.
-- Links between unapproved candidates are NOT formal knowledge-graph edges.
ALTER TABLE consolidation_reviews ADD COLUMN comparison_scope TEXT NOT NULL DEFAULT 'unknown'
 CHECK(comparison_scope IN ('none','same_conversation','cross_conversation','mixed','unknown'));
ALTER TABLE consolidation_reviews ADD COLUMN effect TEXT NOT NULL DEFAULT 'none'
 CHECK(effect IN ('none','provisional_relation','equivalence','merged_formal',
                  'formal_revision','formal_relation','rejected','acknowledged_only','legacy_unknown'));
-- Existing accepted reviews may have effected a merge, a formal relation, or no change.
-- Without reconstructing the audit trail, their effect cannot be asserted safely.
UPDATE consolidation_reviews SET effect='legacy_unknown' WHERE status='applied';

CREATE TABLE IF NOT EXISTS candidate_links (
    id TEXT PRIMARY KEY,
    from_candidate_id TEXT NOT NULL REFERENCES candidates(id),
    to_candidate_id TEXT REFERENCES candidates(id),
    to_object_id TEXT REFERENCES cognitive_objects(id),
    kind TEXT NOT NULL CHECK(kind IN ('refines','related')),
    rationale TEXT NOT NULL CHECK(length(trim(rationale))>0),
    review_id TEXT NOT NULL UNIQUE REFERENCES consolidation_reviews(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK((to_candidate_id IS NULL) <> (to_object_id IS NULL)),
    CHECK(from_candidate_id IS NOT to_candidate_id)
) STRICT;
CREATE INDEX IF NOT EXISTS idx_candidate_links_from ON candidate_links(from_candidate_id);
CREATE INDEX IF NOT EXISTS idx_candidate_links_to_candidate ON candidate_links(to_candidate_id);
CREATE INDEX IF NOT EXISTS idx_candidate_links_to_object ON candidate_links(to_object_id);
PRAGMA user_version=5;
