"""Safe destructive operations on derived VKF state.

- Always preview and confirm a content-dependent token.
- Database changes use one transaction AFTER a verified online backup.
- Never unlink Obsidian files automatically: retire fingerprints, then move
  exact, unchanged generated files out of the Vault via a separate command.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
from typing import Any

from .core import Storage, InvalidInput, Conflict, NotFound, _id
from .obsidian import _vault, _path, _read_small, _sha, FOLDERS

SCOPES = {"derived", "extraction", "conversation", "all"}


def _rows(st: Storage, sql: str, args: tuple = ()) -> list[str]:
    return [r[0] for r in st.db.execute(sql, args)]


def _targets(st: Storage, scope: str, conversation_id: str | None) -> dict[str, Any]:
    if scope not in SCOPES:
        raise InvalidInput(f"lifecycle scope must be one of {sorted(SCOPES)}")
    if scope in ("derived", "all") and conversation_id is not None:
        raise InvalidInput("derived reset applies to all cognition; omit --conversation-id")
    if scope not in ("derived", "all") and not conversation_id:
        raise InvalidInput(f"{scope} requires --conversation-id")
    if conversation_id:
        st.get_conversation(conversation_id)
        if scope == 'conversation':
            if st.db.execute('SELECT 1 FROM research_maps WHERE conversation_id=? LIMIT 1',
                             (conversation_id,)).fetchone():
                raise Conflict('conversation has research map proposals/review history; '
                               'use derived reset before deleting its source')
            if st.db.execute('''SELECT 1 FROM view_evidence_spans es JOIN messages m
                ON m.id=es.message_id WHERE m.conversation_id=? LIMIT 1''',
                (conversation_id,)).fetchone():
                raise Conflict('conversation supplies an accepted Research Space evidence span; '
                               'do not delete its provenance without resetting derived cognition')

    if scope in ("derived", "all"):
        candidates = _rows(st, "SELECT id FROM candidates ORDER BY id")
        objects = _rows(st, "SELECT id FROM cognitive_objects ORDER BY id")
        runs = _rows(st, "SELECT id FROM extraction_runs ORDER BY id")
        conversations = _rows(st, 'SELECT id FROM conversations ORDER BY id') if scope == 'all' else []
        messages = _rows(st, 'SELECT id FROM messages ORDER BY id') if scope == 'all' else []
        calls = _rows(st, "SELECT id FROM model_calls ORDER BY id")
    else:
        candidates = _rows(st, """SELECT c.id FROM candidates c JOIN extraction_runs r
                   ON c.extraction_run_id=r.id WHERE r.conversation_id=? ORDER BY c.id""", (conversation_id,))
        objects = []
        runs = _rows(st, "SELECT id FROM extraction_runs WHERE conversation_id=? ORDER BY id", (conversation_id,))
        messages = (_rows(st, "SELECT id FROM messages WHERE conversation_id=? ORDER BY id", (conversation_id,))
                    if scope == "conversation" else [])
        conversations = [conversation_id] if scope == "conversation" else []
        calls = _rows(st, "SELECT id FROM model_calls WHERE conversation_id=? ORDER BY id", (conversation_id,))

    # References from OTHER candidates must be invalidated too when a target is removed.
    if scope in ("derived", "all"):
        reviews = _rows(st, "SELECT id FROM consolidation_reviews ORDER BY id")
        links = _rows(st, "SELECT id FROM candidate_links ORDER BY id")
        equiv = _rows(st, "SELECT duplicate_candidate_id FROM candidate_equivalences ORDER BY 1")
    elif candidates:
        placeholders = ",".join("?" for _ in candidates)
        reviews = _rows(st, f"""SELECT id FROM consolidation_reviews
           WHERE candidate_id IN ({placeholders}) OR target_candidate_id IN ({placeholders})
           ORDER BY id""", (*candidates, *candidates))
        # Links are also tied to review IDs; they all get removed by review linkage.
        links = _rows(st, f"""SELECT id FROM candidate_links
           WHERE from_candidate_id IN ({placeholders}) OR to_candidate_id IN ({placeholders})
           ORDER BY id""", (*candidates, *candidates))
        equiv = _rows(st, f"""SELECT duplicate_candidate_id FROM candidate_equivalences
           WHERE duplicate_candidate_id IN ({placeholders}) OR canonical_candidate_id IN ({placeholders})
           ORDER BY duplicate_candidate_id""", (*candidates, *candidates))
    else:
        reviews, links, equiv = [], [], []

    if scope not in ("derived", "all"):
        blocked = _rows(st, """SELECT c.id FROM candidates c JOIN extraction_runs r
            ON r.id=c.extraction_run_id WHERE r.conversation_id=?
            AND c.state IN ('approved','merged') ORDER BY c.id""", (conversation_id,))
        if blocked:
            raise Conflict("selected conversation has approved/merged cognition; "
                           "scoped deletion is blocked to protect formal knowledge. "
                           "Use 'lifecycle plan --scope derived' if you intend a full cognition reset")
        if scope == "conversation":
            foreign = _rows(st, """SELECT DISTINCT os.object_id FROM object_sources os
                JOIN messages m ON m.id=os.message_id WHERE m.conversation_id=? ORDER BY os.object_id""",
                (conversation_id,))
            if foreign:
                raise Conflict("conversation contains evidence used by formal knowledge; "
                               "cannot remove it without orphaning its provenance. "
                               "Use a full derived reset or preserve this conversation")

    # Stable affected topic set; topics with no remaining members are retired.
    if scope in ("derived", "all"):
        topics = _rows(st, "SELECT id FROM topics ORDER BY id")
    elif candidates:
        placeholders = ",".join("?" for _ in candidates)
        topics = _rows(st, f"""SELECT t.id FROM topics t WHERE
                 EXISTS (SELECT 1 FROM candidate_topics ct WHERE ct.topic_id=t.id
                         AND ct.candidate_id IN ({placeholders}))
                 AND NOT EXISTS (SELECT 1 FROM object_topics ot WHERE ot.topic_id=t.id)
                 AND NOT EXISTS (SELECT 1 FROM candidate_topics ct WHERE ct.topic_id=t.id
                         AND ct.candidate_id NOT IN ({placeholders}))
                 ORDER BY t.id""", tuple(candidates) * 2)
    else:
        topics = []

    research_spaces = (_rows(st, 'SELECT id FROM research_spaces ORDER BY id')
                       if scope in ('derived','all') else [])
    research_maps = (_rows(st, 'SELECT id FROM research_maps ORDER BY id')
                     if scope in ('derived','all') else [])
    research_feedback = (_rows(st, 'SELECT id FROM researcher_feedback ORDER BY id')
                         if scope in ('derived','all') else [])
    target = dict(candidates=candidates, objects=objects, extraction_runs=runs,
                  messages=messages, conversations=conversations, model_calls=calls,
                  consolidation_reviews=reviews, candidate_links=links,
                  candidate_equivalences=equiv, topics=topics,
                  research_spaces=research_spaces, research_maps=research_maps,
                  researcher_feedback=research_feedback)
    # Fingerprint affected content as well as IDs: a stale preview must not
    # authorize purging a note someone has edited in the meantime.
    digest = hashlib.sha256()
    for name, table in [('candidates','candidates'),('objects','cognitive_objects'),
                        ('conversations','conversations'),('messages','messages'),
                        ('consolidation_reviews','consolidation_reviews'),
                        ('extraction_runs','extraction_runs'),
                        ('research_spaces','research_spaces'),('research_maps','research_maps'),
                        ('researcher_feedback','researcher_feedback')]:
        ids = target[name]
        for pos in range(0, len(ids), 400):
            batch = ids[pos:pos+400]
            placeholders = ','.join('?' for _ in batch)
            for row in st.db.execute(f"SELECT * FROM {table} WHERE id IN ({placeholders}) ORDER BY id", batch):
                # Use a canonical encoding; nothing from the texts enters preview.
                digest.update(json.dumps(list(row), ensure_ascii=False, sort_keys=True).encode('utf-8'))
    signature = hashlib.sha256(json.dumps(
        {"scope": scope, "conversation_id": conversation_id, "targets": target,
         "content_sha256": digest.hexdigest(), "schema": 7},
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
    return {"scope": scope, "conversation_id": conversation_id,
            "token": signature, "counts": {k: len(v) for k, v in target.items()},
            "_target": target}


def plan(st: Storage, scope: str, conversation_id: str | None = None) -> dict[str, Any]:
    p = _targets(st, scope, conversation_id)
    return {key: val for key, val in p.items() if key != "_target"} | {
        "warning": "Destructive only after 'apply --confirm TOKEN'; original conversation text "
                   "is kept by derived/extraction scopes; Obsidian cleanup is separate."}


def _delete_ids(st: Storage, table: str, key: str, ids: list[str]) -> None:
    # Parameterized and batched to avoid SQLite bound-variable limits.
    for pos in range(0, len(ids), 400):
        batch = ids[pos:pos + 400]
        placeholders = ','.join('?' * len(batch))
        st.db.execute(f"DELETE FROM {table} WHERE {key} IN ({placeholders})", batch)


def _retire(st: Storage, event: str, rows: list[tuple[str, str, str]]) -> None:
    for key, rel, digest in rows:
        existing = st.db.execute('''SELECT id FROM lifecycle_retired_files
            WHERE vault_key=? AND relative_path=? AND status='pending' ''', (key, rel)).fetchone()
        if existing:
            # Earlier deletion still awaiting archive. Do not alter its known hash.
            continue
        st.db.execute('''INSERT INTO lifecycle_retired_files
            (id,vault_key,relative_path,exported_sha256,event_id)
            VALUES(?,?,?,?,?)''', (_id('retired'), key, rel, digest, event))


def _read_retire_rows(st: Storage, target: dict) -> tuple[list[tuple[str,str,str]], list[tuple[str,str,str]]]:
    oidset = set(target['objects'])
    research_idset = set(target['research_spaces'])
    cset = set(target['candidates'])
    rset = set(target['consolidation_reviews'])
    tset = set(target['topics'])
    conset = set(target['conversations'])
    formal = [(r['vault_key'], r['relative_path'], r['exported_sha256'])
              for r in st.db.execute('SELECT vault_key,relative_path,exported_sha256,object_id FROM obsidian_bridge_state')
              if r['object_id'] in oidset]
    readonly = []
    candidate_suffixes = {i[-10:] for i in cset}
    review_suffixes = {i[-10:] for i in rset}
    topic_suffixes = {i[-10:] for i in tset}
    conversation_suffixes = {i[-10:] for i in conset}
    for r in st.db.execute('SELECT vault_key,relative_path,exported_sha256 FROM obsidian_readonly_state'):
        relative = r['relative_path']
        if relative.startswith('VKF/Research Spaces/') and relative.endswith('.md'):
            if relative.rsplit('/',1)[-1].removesuffix('.md') in research_idset:
                readonly.append((r['vault_key'], relative, r['exported_sha256']))
            continue
        if not (relative.endswith('.md') and '--' in relative):
            continue
        note_id_suffix = relative.rsplit('--', 1)[-1].removesuffix('.md')
        if len(note_id_suffix) != 10:
            continue
        if ((relative.startswith('VKF/Candidates/') and note_id_suffix in candidate_suffixes)
            or (relative.startswith('VKF/Consolidation/') and note_id_suffix in review_suffixes)
            or (relative.startswith('VKF/Topics/') and note_id_suffix in topic_suffixes)
            or (relative.startswith('VKF/Conversations/') and note_id_suffix in conversation_suffixes)):
            readonly.append((r['vault_key'], relative, r['exported_sha256']))
    return formal, readonly


def _purge_audit(st: Storage, *, scope: str, target: dict) -> None:
    # These 2 append-only triggers are specifically lifted inside an IMMEDIATE
    # transaction and restored before commit, to authorize the user-requested purge.
    st.db.execute('DROP TRIGGER append_only_audit_delete')
    st.db.execute('DROP TRIGGER append_only_object_versions_delete')
    if scope in ('derived','all'):
        if scope == 'all':
            st.db.execute('DELETE FROM audit_events')
        else:
            st.db.execute("DELETE FROM audit_events WHERE entity_type <> 'conversation'")
    else:
        candidate_ids = target['candidates']
        if candidate_ids:
            _delete_ids(st, 'audit_events', 'entity_id', candidate_ids)
        if scope == 'conversation':
            _delete_ids(st, 'audit_events', 'entity_id', target['conversations'])



def apply(st: Storage, scope: str, *, conversation_id: str | None = None,
          confirm: str) -> dict[str, Any]:
    preliminary = _targets(st, scope, conversation_id)
    if not confirm or confirm != preliminary['token']:
        raise Conflict('confirmation token differs from current preview; run lifecycle plan again')
    if st.path == ':memory:':
        raise InvalidInput('lifecycle apply needs an on-disk database for a verified backup')
    suffix = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup_file = f'{st.path}.before-lifecycle-{suffix}-{uuid4().hex[:8]}.db'
    backup = st.backup(backup_file)['backup']
    with st.transaction():
        p = _targets(st, scope, conversation_id)
        if p['token'] != confirm:
            raise Conflict('database changed between preview and apply; no data was deleted; backup exists')
        target = p['_target']
        event = _id('life')
        st.db.execute("""INSERT INTO lifecycle_events
              (id,scope,conversation_id,backup_path,plan_token,counts_json)
              VALUES(?,?,?,?,?,?)""", (event, scope, conversation_id, backup, confirm,
                                               json.dumps(p['counts'], sort_keys=True)))
        formal, readonly = _read_retire_rows(st, target)
        _retire(st, event, formal + readonly)
        # Remove bridge registry entries for soon-to-be-deleted objects.
        _delete_ids(st, 'obsidian_bridge_state', 'object_id', target['objects'])
        for key, rel, _ in readonly:
            st.db.execute('DELETE FROM obsidian_readonly_state WHERE vault_key=? AND relative_path=?', (key, rel))

        # v0.3.0: research structures may refer to candidates, messages, and
        # accepted research spaces; delete the dependency chain before the
        # legacy derived records, only for an explicit FULL derived reset.
        if scope in ('derived','all'):
            for table in (
                'researcher_feedback', 'research_maps', 'synthesis_members',
                'synthesis_proposals', 'compatibility_assessments',
                'frontier_obstructions', 'coverage_dimensions', 'view_evidence_spans',
                'contextual_views', 'research_space_contexts', 'research_space_versions',
                'research_contexts', 'research_spaces', 'research_references'
            ):
                st.db.execute(f'DELETE FROM {table}')
        # Referenced candidate links/reviews/equivalences must be removed before candidates.
        _delete_ids(st, 'candidate_links', 'id', target['candidate_links'])
        _delete_ids(st, 'candidate_equivalences', 'duplicate_candidate_id', target['candidate_equivalences'])
        _delete_ids(st, 'consolidation_reviews', 'id', target['consolidation_reviews'])
        _delete_ids(st, 'candidate_topics', 'candidate_id', target['candidates'])
        _delete_ids(st, 'candidate_attributions', 'candidate_id', target['candidates'])
        _delete_ids(st, 'candidate_sources', 'candidate_id', target['candidates'])
        _delete_ids(st, 'candidates', 'id', target['candidates'])
        _delete_ids(st, 'extraction_segments', 'extraction_run_id', target['extraction_runs'])
        _delete_ids(st, 'extraction_runs', 'id', target['extraction_runs'])
        _delete_ids(st, 'model_calls', 'id', target['model_calls'])

        if scope in ('derived','all'):
            st.db.execute('DELETE FROM frontier_suggestions')
            st.db.execute('DELETE FROM question_states')
            st.db.execute('DELETE FROM relations')
            st.db.execute('DELETE FROM object_sources')
            st.db.execute('DELETE FROM object_topics')
            _purge_audit(st, scope=scope, target=target)
            st.db.execute('DELETE FROM object_versions')
            st.db.execute('DELETE FROM cognitive_objects')
        else:
            _purge_audit(st, scope=scope, target=target)
        _delete_ids(st, 'topics', 'id', target['topics'])
        # Reinstate append-only guarantees inside the same transaction. Both
        # triggers were suspended solely for deliberate lifecycle purges.
        st.db.execute("""CREATE TRIGGER append_only_audit_delete BEFORE DELETE ON audit_events
           BEGIN SELECT RAISE(ABORT,'audit history is append-only'); END""")
        st.db.execute("""CREATE TRIGGER append_only_object_versions_delete BEFORE DELETE ON object_versions
           BEGIN SELECT RAISE(ABORT,'object version history is append-only'); END""")
        if scope in ('conversation','all'):
            _delete_ids(st, 'message_import_metadata', 'message_id', target['messages'])
            _delete_ids(st, 'conversation_origins', 'conversation_id', target['conversations'])
            _delete_ids(st, 'messages', 'id', target['messages'])
            _delete_ids(st, 'conversations', 'id', target['conversations'])
            st.db.execute('''DELETE FROM import_batches WHERE NOT EXISTS
                (SELECT 1 FROM conversations c WHERE c.import_batch_id=import_batches.id)''')
        # Run integrity checks before COMMIT; any failure rolls the purge back.
        doctor = st.doctor()
        if not doctor['ok']:
            raise Conflict('purge integrity check failed and transaction was rolled back: '
                           + str(doctor['problems']))
    return {'event_id': event, 'scope': scope, 'conversation_id': conversation_id,
            'counts': p['counts'], 'backup': backup, 'database': st.path,
            'vault_cleanup': 'Run lifecycle vault-prune (preview first) before exporting; '
                             'only matching unmodified generated files can be archived.',
            'doctor': doctor}


def vault_prune(st: Storage, vault: str | Path, *, apply_changes: bool = False,
                confirm: str | None = None) -> dict[str, Any]:
    root, key = _vault(vault)
    rows = list(st.db.execute('''SELECT id,relative_path,exported_sha256 FROM lifecycle_retired_files
         WHERE vault_key=? AND status='pending' ORDER BY relative_path,id''', (key,)))
    manifest = [(r['id'], r['relative_path'], r['exported_sha256']) for r in rows]
    token = hashlib.sha256(json.dumps(manifest, ensure_ascii=False).encode()).hexdigest()[:20]
    results: list[dict[str, str]] = []
    for rid, rel, checksum in manifest:
        try:
            file = _path(root, rel)
            if not file.exists():
                status = 'missing'
            elif _sha(_read_small(file)) == checksum:
                status = 'ready'
            else:
                status = 'conflict_modified'
        except (OSError, Conflict, InvalidInput, UnicodeError):
            status = 'conflict_unsafe'
        results.append({'id': rid, 'file': rel, 'status': status})
    if not apply_changes:
        return {'vault': str(root), 'preview': True, 'token': token,
                'counts': {x: sum(z['status']==x for z in results) for x in ('ready','missing','conflict_modified','conflict_unsafe')},
                'files': results}
    if not confirm or token != confirm:
        raise Conflict('vault-prune confirmation token mismatch; preview again')
    folder = root.parent / f'{root.name}-VKF-retired-{uuid4().hex[:10]}'
    moved = []
    conflicts = []
    for record in results:
        rid, rel = record['id'], record['file']
        if record['status'] in ('conflict_modified', 'conflict_unsafe'):
            conflicts.append(record)
            continue
        src = _path(root, rel)
        if record['status'] == 'missing':
            with st.transaction():
                st.db.execute("UPDATE lifecycle_retired_files SET status='missing' WHERE id=? AND status='pending'", (rid,))
            continue
        # Recheck after plan was generated: content might have been edited meanwhile.
        checksum = next(digest for entry, path, digest in manifest if entry == rid)
        if not src.is_file() or _sha(_read_small(src)) != checksum:
            conflicts.append({'id': rid, 'file': rel, 'status': 'changed_during_prune'})
            continue
        dest = folder / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                conflicts.append({'id': rid, 'file': rel, 'status': 'archive_collision'})
                continue
            os.replace(src, dest)
            # The filesystem move and SQLite commit cannot share a transaction.
            # The archived copy is left intact even if the DB update fails;
            # a missing source is recoverable from archive_dir.
            with st.transaction():
                st.db.execute("UPDATE lifecycle_retired_files SET status='archived',archive_path=? "
                              "WHERE id=? AND status='pending'", (str(dest), rid))
            moved.append({'file': rel, 'archive': str(dest)})
        except OSError as exc:
            conflicts.append({'id': rid, 'file': rel, 'status': 'archive_io_error',
                              'error_type': type(exc).__name__})
    return {'vault': str(root), 'archive_dir': str(folder) if moved else None,
            'archived': moved, 'conflicts': conflicts,
            'warning': 'No manually modified or unmanaged file is overwritten or deleted.'}
