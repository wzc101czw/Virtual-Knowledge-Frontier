"""Transactional SQLite repository for VKF. No network calls or model dependence.

All writes use BEGIN IMMEDIATE / COMMIT / ROLLBACK. The API is deliberately
small and opinionated; no direct SQL string can be supplied by a caller.
"""
from __future__ import annotations

from contextlib import contextmanager, closing
from datetime import datetime, timezone
import hashlib
from importlib import resources
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator
from uuid import uuid4


SCHEMA_VERSION = 8
KINDS = {"knowledge", "idea", "understanding", "question", "cross_insight"}
OBJECT_STATUSES = {"active", "challenged", "archived"}
QUESTION_STATES = {"open", "exploring", "answered", "parked"}
RELATION_KINDS = {"depends_on", "supports", "contradicts", "analogous_to", "synthesizes", "raises", "answers"}
SYMMETRIC_KINDS = {"contradicts", "analogous_to"}
FRONTIER_SIGNALS = {"new_relevance", "contradiction", "cross_domain", "missing_premise"}
EPISTEMIC = {"asserted", "tentative", "disputed", "not_applicable"}
ACTORS = {"user", "model", "mixed"}
SOURCES = {"live", "chatgpt", "claude", "other"}
ROLES = {"system", "user", "assistant", "tool"}
TABLES_TO_EXPORT = (
    "import_batches", "conversations", "messages", "extraction_runs",
    "cognitive_objects", "model_calls", "candidates", "candidate_sources",
    "object_sources", "relations", "question_states", "object_versions",
    "audit_events", "frontier_suggestions", "conversation_origins", "message_import_metadata", "obsidian_bridge_state", "obsidian_readonly_state",
    "extraction_segments", "candidate_attributions", "consolidation_reviews", "candidate_equivalences", "topics", "candidate_topics", "object_topics", "candidate_links",
    "lifecycle_events", "lifecycle_retired_files",
    "research_spaces", "research_space_versions", "research_maps", "research_contexts",
    "research_space_contexts", "research_references", "contextual_views",
    "view_evidence_spans", "coverage_dimensions", "compatibility_assessments",
    "synthesis_proposals", "synthesis_members", "frontier_obstructions", "researcher_feedback", "research_map_checkpoints")


class VKFError(Exception):
    """A user-addressable VKF failure."""


class NotFound(VKFError):
    pass


class Conflict(VKFError):
    pass


class InvalidInput(VKFError):
    pass


class UnsupportedSchema(VKFError):
    pass


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _required(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidInput(f"{label} must be a non-empty string")
    return value.strip()


def _content(value: str, label: str) -> str:
    """Validate without removing indentation or trailing newlines from knowledge."""
    if not isinstance(value, str) or not value.strip():
        raise InvalidInput(f"{label} must be nonempty text")
    return value


def _choice(value: str, options: set[str], label: str) -> str:
    if value not in options:
        raise InvalidInput(f"invalid {label}: {value!r}; allowed: {', '.join(sorted(options))}")
    return value


def _positive_limit(value: int, *, maximum: int = 1000) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise InvalidInput(f"limit must be between 1 and {maximum}")
    return value


def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class Storage:
    """One connection per Storage instance, not shared between threads.

    Before using an existing DB, call Storage.initialize(path) once to create
    it or migrate from the reference VKF v1 schema. Call close() when finished.
    """

    def __init__(self, path: str | Path):
        self.path = ":memory:" if str(path) == ":memory:" else str(Path(path).expanduser())
        in_memory = self.path == ":memory:"
        if not in_memory and not Path(self.path).is_file():
            raise NotFound(f"database does not exist: {self.path}; run 'vkf init' first")
        address = ":memory:" if in_memory else Path(self.path).resolve().as_uri() + "?mode=rw"
        try:
            self.db = sqlite3.connect(address, timeout=10, isolation_level=None, uri=not in_memory)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA busy_timeout=10000")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise UnsupportedSchema(
                    f"schema version {version} != {SCHEMA_VERSION}; run 'vkf init' to migrate (back up first)"
                )
            if self.db.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                raise UnsupportedSchema("SQLite foreign_keys could not be enabled")
            for table in (*TABLES_TO_EXPORT, "object_fts"):
                if not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    raise UnsupportedSchema(f"VKF database is incomplete; missing table: {table}")
        except Exception:
            if hasattr(self, "db"):
                self.db.close()
            raise

    @classmethod
    def initialize(cls, path: str | Path) -> dict[str, Any]:
        path_str = str(path)
        memory = path_str == ":memory:"
        if memory:
            raise InvalidInput("persistent Storage.initialize requires an on-disk path")
        pre_migration_backup: str | None = None
        if not memory:
            p = Path(path_str).expanduser()
            p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not p.exists():
                fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                os.close(fd)
            path_str = str(p)
        db = sqlite3.connect(path_str, timeout=10, isolation_level=None)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=10000")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            existing_version = version
            was_existing_v1 = version == 1
            was_existing_v2 = version == 2
            if version == 0:
                existing = db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'").fetchall()
                if existing:
                    raise UnsupportedSchema("this is a nonempty database without VKF schema version; refusing to overwrite it")
                cls._apply_script(db, "001_initial.sql")
                version = 1
            if version == 1:
                # Recheck required v1 tables before applying the migration.
                for table in ("import_batches", "conversations", "messages", "extraction_runs", "cognitive_objects", "model_calls", "candidates", "candidate_sources", "object_sources", "relations", "question_states", "object_versions", "audit_events", "frontier_suggestions", "object_fts"):
                    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                        raise UnsupportedSchema(f"version 1 database lacks required table {table}")
                # Create a private online backup BEFORE modifying a version 1 DB.
                # SQLite's backup API includes committed data that may still be in WAL.
                if was_existing_v1:
                    backup_path = Path(path_str).with_name(Path(path_str).name + ".pre-v2." + uuid4().hex[:8] + ".db")
                    fd = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                    os.close(fd)
                    with closing(sqlite3.connect(backup_path)) as backup_db:
                        db.backup(backup_db)
                    pre_migration_backup = str(backup_path)
                cls._apply_script(db, "002_guardrails.sql")
                version = 2
            if version == 2:
                for table in ("import_batches", "conversations", "messages", "extraction_runs", "cognitive_objects", "model_calls", "candidates", "candidate_sources", "object_sources", "relations", "question_states", "object_versions", "audit_events", "frontier_suggestions", "object_fts"):
                    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                        raise UnsupportedSchema(f"version 2 database lacks required table {table}")
                if not pre_migration_backup and was_existing_v2:
                    backup_path = Path(path_str).with_name(Path(path_str).name + ".pre-v3." + uuid4().hex[:8] + ".db")
                    fd = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                    os.close(fd)
                    with closing(sqlite3.connect(backup_path)) as backup_db:
                        db.backup(backup_db)
                    pre_migration_backup = str(backup_path)
                cls._apply_script(db, "003_bridge_import.sql")
                version = 3
            if version == 3:
                for table in ("obsidian_bridge_state", "obsidian_readonly_state", "candidates", "object_fts"):
                    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                        raise UnsupportedSchema(f"version 3 database lacks required table {table}")
                if not pre_migration_backup and existing_version == 3:
                    backup_path = Path(path_str).with_name(Path(path_str).name + ".pre-v4." + uuid4().hex[:8] + ".db")
                    fd = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                    os.close(fd)
                    with closing(sqlite3.connect(backup_path)) as backup_db:
                        db.backup(backup_db)
                    pre_migration_backup = str(backup_path)
                cls._apply_script(db, "004_consolidation.sql")
                version = 4
            if version == 4:
                for table in ('consolidation_reviews', 'candidate_equivalences', 'topics', 'candidate_sources'):
                    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                        raise UnsupportedSchema(f"version 4 database lacks required table {table}")
                if not pre_migration_backup and existing_version == 4:
                    backup_path = Path(path_str).with_name(Path(path_str).name + '.pre-v5.' + uuid4().hex[:8] + '.db')
                    fd = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                    os.close(fd)
                    with closing(sqlite3.connect(backup_path)) as backup_db:
                        db.backup(backup_db)
                    pre_migration_backup = str(backup_path)
                cls._apply_script(db, '005_provenance_links.sql')
                version = 5
            if version == 5:
                for table in ('candidate_links','consolidation_reviews','obsidian_bridge_state'):
                    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                        raise UnsupportedSchema(f'version 5 database lacks required table {table}')
                if not pre_migration_backup and existing_version == 5:
                    backup_path = Path(path_str).with_name(Path(path_str).name + '.pre-v6.' + uuid4().hex[:8] + '.db')
                    fd = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                    os.close(fd)
                    with closing(sqlite3.connect(backup_path)) as backup_db:
                        db.backup(backup_db)
                    pre_migration_backup = str(backup_path)
                cls._apply_script(db, '006_lifecycle.sql')
                version = 6
            if version == 6:
                for table in ("lifecycle_events", "candidates", "conversations", "messages"):
                    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                        raise UnsupportedSchema(f"version 6 database lacks required table {table}")
                if not pre_migration_backup and existing_version == 6:
                    backup_path = Path(path_str).with_name(Path(path_str).name + '.pre-v7.' + uuid4().hex[:8] + '.db')
                    fd = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                    os.close(fd)
                    with closing(sqlite3.connect(backup_path)) as backup_db:
                        db.backup(backup_db)
                    pre_migration_backup = str(backup_path)
                cls._apply_script(db, '007_research_spaces.sql')
                version = 7
            if version == 7:
                for table in ('research_maps', 'conversations', 'researcher_feedback'):
                    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                        raise UnsupportedSchema(f'version 7 database lacks required table {table}')
                if not pre_migration_backup and existing_version == 7:
                    backup_path = Path(path_str).with_name(Path(path_str).name + '.pre-v8.' + uuid4().hex[:8] + '.db')
                    fd = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                    os.close(fd)
                    with closing(sqlite3.connect(backup_path)) as backup_db:
                        db.backup(backup_db)
                    pre_migration_backup = str(backup_path)
                cls._apply_script(db, '008_research_checkpoints.sql')
                version = 8
            if version != SCHEMA_VERSION:
                raise UnsupportedSchema(f"schema version {version} is unsupported; expected {SCHEMA_VERSION}")
            db.execute("PRAGMA journal_mode=WAL") if not memory else None
            return {"database": path_str, "schema_version": version, "status": "ready",
                    "pre_migration_backup": pre_migration_backup}
        except sqlite3.Error as exc:
            raise VKFError(f"SQLite initialization failed: {exc}") from exc
        finally:
            db.close()

    @staticmethod
    def _apply_script(db: sqlite3.Connection, name: str) -> None:
        script = resources.files("vkf_storage").joinpath("migrations", name).read_text(encoding="utf-8")
        try:
            db.executescript("BEGIN IMMEDIATE;\n" + script + "\nCOMMIT;")
        except Exception:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self.db.in_transaction:
            raise Conflict("nested transactions are not supported")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def _one(self, sql: str, args: tuple[Any, ...] = (), *, name: str = "record") -> dict[str, Any]:
        row = self.db.execute(sql, args).fetchone()
        if row is None:
            raise NotFound(f"{name} not found")
        return dict(row)

    def _get_object_tx(self, object_id: str) -> dict[str, Any]:
        return self._one("SELECT * FROM cognitive_objects WHERE id=?", (object_id,), name=f"object {object_id}")

    def _audit(self, entity_type: str, entity_id: str, action: str, payload: dict[str, Any], *, actor: str = "user") -> None:
        self.db.execute(
            "INSERT INTO audit_events(id,entity_type,entity_id,action,actor,payload_json) VALUES(?,?,?,?,?,?)",
            (_id("aud"), entity_type, entity_id, action, actor, _json(payload)),
        )

    def _snapshot(self, obj: dict[str, Any], reason: str, actor: str) -> None:
        self.db.execute(
            "INSERT INTO object_versions(object_id,revision,snapshot_json,change_reason,actor) VALUES(?,?,?,?,?)",
            (obj["id"], obj["revision"], _json(obj), _required(reason, "change reason"), actor),
        )

    @staticmethod
    def _normalize_object(kind: str, title: str, body: str,
                          epistemic_status: str | None,
                          understanding_level: str | None) -> tuple[str, str, str, str, str | None]:
        kind = _choice(kind, KINDS, "kind")
        title = _required(title, "title")
        body = _content(body, "body")
        epistemic_status = epistemic_status or ("not_applicable" if kind == "question" else "tentative")
        _choice(epistemic_status, EPISTEMIC, "epistemic status")
        if (kind == "question") != (epistemic_status == "not_applicable"):
            raise InvalidInput("questions must use epistemic_status=not_applicable, and other kinds must not")
        if kind == "understanding":
            understanding_level = understanding_level or "provisional"
            _choice(understanding_level, {"provisional", "articulated"}, "understanding level")
        elif understanding_level is not None:
            raise InvalidInput("understanding level only applies to 'understanding' objects")
        return kind, title, body, epistemic_status, understanding_level

    def _create_object_tx(self, *, kind: str, title: str, body: str,
                          origin_actor: str, epistemic_status: str | None,
                          understanding_level: str | None,
                          uncertainty_note: str = "", reason: str = "initial creation",
                          actor: str = "user", object_id: str | None = None) -> dict[str, Any]:
        kind, title, body, epistemic_status, understanding_level = self._normalize_object(
            kind, title, body, epistemic_status, understanding_level)
        _choice(origin_actor, ACTORS, "origin actor")
        oid = object_id or _id("obj")
        self.db.execute(
            """INSERT INTO cognitive_objects(id,kind,title,body,epistemic_status,understanding_level,
                origin_actor,uncertainty_note) VALUES(?,?,?,?,?,?,?,?)""",
            (oid, kind, title, body, epistemic_status, understanding_level, origin_actor, uncertainty_note),
        )
        if kind == "question":
            self.db.execute("INSERT INTO question_states(object_id) VALUES(?)", (oid,))
        obj = self._get_object_tx(oid)
        self._snapshot(obj, reason, actor)
        self._audit("object", oid, "created", {"snapshot": obj}, actor=actor)
        return obj

    def create_object(self, kind: str, title: str, body: str, *,
                      epistemic_status: str | None = None,
                      understanding_level: str | None = None, uncertainty_note: str = "",
                      synthesized_from: list[str] | None = None,
                      synthesis_rationale: str | None = None) -> dict[str, Any]:
        """User creation. CrossInsights need two existing, distinct source objects."""
        sources = self._validate_synthesis(kind, synthesized_from, synthesis_rationale)
        with self.transaction():
            obj = self._create_object_tx(
                kind=kind, title=title, body=body, epistemic_status=epistemic_status,
                understanding_level=understanding_level, uncertainty_note=uncertainty_note,
                origin_actor="user")
            for source in sources:
                self._add_relation_tx(obj["id"], source, "synthesizes", synthesis_rationale or "", "user")
        return self.get_object(obj["id"])

    @staticmethod
    def _validate_synthesis(kind: str, sources: list[str] | None, rationale: str | None) -> list[str]:
        unique = list(dict.fromkeys(sources or []))
        if kind == "cross_insight":
            if len(unique) < 2:
                raise InvalidInput("cross_insight requires at least two distinct --source-id objects")
            _required(rationale or "", "synthesis rationale")
        elif sources:
            raise InvalidInput("--source-id is reserved for cross_insight creation")
        return unique

    def get_object(self, object_id: str) -> dict[str, Any]:
        obj = self._get_object_tx(object_id)
        if obj["kind"] == "question":
            obj["question_state"] = self._one(
                "SELECT * FROM question_states WHERE object_id=?", (object_id,), name="question state")
        return obj

    def list_objects(self, *, kind: str | None = None, status: str | None = None,
                     limit: int = 100) -> list[dict[str, Any]]:
        limit = _positive_limit(limit)
        clauses: list[str] = []
        params: list[Any] = []
        if kind is not None:
            clauses.append("kind=?")
            params.append(_choice(kind, KINDS, "kind"))
        if status is not None:
            clauses.append("status=?")
            params.append(_choice(status, OBJECT_STATUSES, "status"))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.db.execute("SELECT * FROM cognitive_objects" + where + " ORDER BY updated_at DESC,id LIMIT ?",
                               (*params, limit)).fetchall()
        return [dict(x) for x in rows]

    def _update_object_tx(self, object_id: str, changes: dict[str, Any], reason: str,
                          expected_revision: int | None = None) -> dict[str, Any]:
        obj = self._get_object_tx(object_id)
        if expected_revision is not None and expected_revision != obj["revision"]:
            raise Conflict(f"stale revision: expected {expected_revision}, current {obj['revision']}")
        allowed = {"title", "body", "status", "epistemic_status", "understanding_level", "uncertainty_note"}
        if not changes or not set(changes).issubset(allowed):
            raise InvalidInput("no supported object changes were provided")
        fields = {key: obj[key] for key in allowed}
        fields.update(changes)
        if fields["status"] != obj["status"]:
            transitions = {
                "active": {"challenged", "archived"},
                "challenged": {"active", "archived"},
                "archived": {"active"},
            }
            if fields["status"] not in transitions[obj["status"]]:
                raise InvalidInput(f"invalid object transition: {obj['status']} -> {fields['status']}")
        self._normalize_object(obj["kind"], fields["title"], fields["body"],
                               fields["epistemic_status"], fields["understanding_level"])
        if all(fields[key] == obj[key] for key in allowed):
            raise InvalidInput("no changes; object would have identical content and status")
        _required(reason, "reason")
        # Protect a confirmed cross_insight from losing its explanatory source links.
        if obj["kind"] == "cross_insight" and fields["status"] != "archived":
            n = self.db.execute("SELECT COUNT(*) FROM relations WHERE from_object_id=? AND kind='synthesizes' AND status='active'",
                                (object_id,)).fetchone()[0]
            if n < 2:
                raise Conflict("cross_insight has fewer than two active synthesis sources; fix links before updating")
        cols = sorted(allowed)
        assignments = ", ".join(f"{column}=?" for column in cols)
        self.db.execute(
            f"UPDATE cognitive_objects SET {assignments},revision=revision+1,updated_at=? WHERE id=?",
            (*[fields[x] for x in cols], _now(), object_id),
        )
        after = self._get_object_tx(object_id)
        self._snapshot(after, reason, "user")
        self._audit("object", object_id, "updated", {"previous_revision": obj["revision"], "changes": changes,
                                                    "reason": reason, "revision": after["revision"]})
        return after

    def update_object(self, object_id: str, *, reason: str,
                      expected_revision: int | None = None, **changes: Any) -> dict[str, Any]:
        with self.transaction():
            return self._update_object_tx(object_id, changes, reason, expected_revision)

    def object_history(self, object_id: str) -> list[dict[str, Any]]:
        self._get_object_tx(object_id)
        rows = self.db.execute("SELECT revision,snapshot_json,change_reason,actor,created_at FROM object_versions "
                               "WHERE object_id=? ORDER BY revision", (object_id,)).fetchall()
        return [{**dict(r), "snapshot": json.loads(r["snapshot_json"])} for r in rows]

    def restore_object_revision(self, object_id: str, target_revision: int, *, reason: str,
                                expected_revision: int | None = None) -> dict[str, Any]:
        """A restoration is a new revision, never deletion of the intervening history."""
        with self.transaction():
            current = self._get_object_tx(object_id)
            row = self.db.execute("SELECT snapshot_json FROM object_versions WHERE object_id=? AND revision=?",
                                  (object_id, target_revision)).fetchone()
            if row is None:
                raise NotFound("requested revision does not exist")
            old = json.loads(row["snapshot_json"])
            fields = {x: old[x] for x in ("title", "body", "status", "epistemic_status", "understanding_level", "uncertainty_note")}
            # Restoration of an archived object (or from archived -> active) follows
            # ordinary transition rules. Use explicit status changes if needed.
            after = self._update_object_tx(object_id, fields,
                                           f"restore from revision {target_revision}: {_required(reason, 'reason')}",
                                           expected_revision)
            self._audit("object", object_id, "restored", {"from_revision": target_revision,
                                                         "new_revision": after["revision"]})
            return after

    def add_relation(self, from_object_id: str, to_object_id: str, kind: str,
                     rationale: str) -> dict[str, Any]:
        """Only explicit user-initiated links enter the formal knowledge graph."""
        with self.transaction():
            return self._add_relation_tx(from_object_id, to_object_id, kind, rationale, "user")

    def _add_relation_tx(self, from_id: str, to_id: str, kind: str,
                         rationale: str, origin_actor: str) -> dict[str, Any]:
        _choice(kind, RELATION_KINDS, "relation kind")
        _choice(origin_actor, ACTORS, "origin actor")
        rationale = _required(rationale, "rationale")
        if from_id == to_id:
            raise InvalidInput("self-links are not permitted")
        a = self._get_object_tx(from_id)
        b = self._get_object_tx(to_id)
        if a["status"] == "archived" or b["status"] == "archived":
            raise InvalidInput("cannot attach a new relation to an archived object")
        if kind in SYMMETRIC_KINDS and from_id > to_id:
            from_id, to_id = to_id, from_id
        if kind in {"raises", "answers"} and b["kind"] != "question":
            raise InvalidInput("raises and answers must target a question")
        if kind == "synthesizes" and a["kind"] not in {"cross_insight", "understanding"}:
            raise InvalidInput("synthesizes must start from a CrossInsight or Understanding")
        dup = self.db.execute("SELECT id FROM relations WHERE from_object_id=? AND to_object_id=? AND kind=?",
                              (from_id, to_id, kind)).fetchone()
        if dup:
            raise Conflict(f"relation already exists: {dup[0]}")
        rid = _id("rel")
        self.db.execute(
            "INSERT INTO relations(id,from_object_id,to_object_id,kind,rationale,origin_actor) VALUES(?,?,?,?,?,?)",
            (rid, from_id, to_id, kind, rationale, origin_actor),
        )
        relation = self._one("SELECT * FROM relations WHERE id=?", (rid,))
        self._audit("relation", rid, "created", {"relation": relation})
        return relation

    def list_relations(self, object_id: str | None = None, *,
                       status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = _positive_limit(limit)
        clauses = []
        args: list[Any] = []
        if object_id is not None:
            self._get_object_tx(object_id)
            clauses.append("(from_object_id=? OR to_object_id=?)")
            args += [object_id, object_id]
        if status is not None:
            clauses.append("status=?")
            args.append(_choice(status, OBJECT_STATUSES, "relation status"))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return [dict(x) for x in self.db.execute(
            "SELECT * FROM relations" + where + " ORDER BY created_at DESC,id LIMIT ?", (*args, limit)).fetchall()]

    def set_relation_status(self, relation_id: str, status: str, *, reason: str) -> dict[str, Any]:
        status = _choice(status, OBJECT_STATUSES, "relation status")
        _required(reason, "reason")
        with self.transaction():
            rel = self._one("SELECT * FROM relations WHERE id=?", (relation_id,), name="relation")
            if status == rel["status"]:
                raise InvalidInput("relation already has that status")
            transitions = {"active": {"challenged", "archived"},
                           "challenged": {"active", "archived"}, "archived": {"active"}}
            if status not in transitions[rel["status"]]:
                raise InvalidInput("invalid relation status transition")
            if rel["kind"] == "synthesizes" and rel["status"] == "active" and status != "active":
                owner = self._get_object_tx(rel["from_object_id"])
                if owner["kind"] == "cross_insight" and owner["status"] == "active":
                    n = self.db.execute("SELECT COUNT(*) FROM relations WHERE from_object_id=? AND kind='synthesizes' AND status='active'",
                                        (rel["from_object_id"],)).fetchone()[0]
                    if n <= 2:
                        raise Conflict("cannot remove one of the final two active CrossInsight source links")
            self.db.execute("UPDATE relations SET status=? WHERE id=?", (status, relation_id))
            updated = self._one("SELECT * FROM relations WHERE id=?", (relation_id,))
            self._audit("relation", relation_id, "status_changed", {"before": rel["status"],
                                                                    "after": status, "reason": reason})
            return updated

    def set_question_state(self, object_id: str, state: str, *,
                           reason: str, resolution_note: str = "") -> dict[str, Any]:
        _choice(state, QUESTION_STATES, "question state")
        _required(reason, "reason")
        with self.transaction():
            obj = self._get_object_tx(object_id)
            if obj["kind"] != "question":
                raise InvalidInput("question state only applies to questions")
            before = self._one("SELECT * FROM question_states WHERE object_id=?", (object_id,))
            if state == before["state"]:
                raise InvalidInput("question already has that state")
            note = resolution_note.strip() if state == "answered" else ""
            self.db.execute("UPDATE question_states SET state=?,resolution_note=?,updated_at=? WHERE object_id=?",
                            (state, note, _now(), object_id))
            after = self._one("SELECT * FROM question_states WHERE object_id=?", (object_id,))
            self._audit("question", object_id, "state_changed", {"before": before["state"],
                                                                 "after": state, "reason": reason,
                                                                 "previous_resolution_note": before["resolution_note"],
                                                                 "resolution_note": note})
            return after

    def list_questions(self, *, state: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = _positive_limit(limit)
        if state:
            _choice(state, QUESTION_STATES, "question state")
        sql = ("SELECT o.id,o.title,o.body,o.status,q.state AS question_state,q.resolution_note "
               "FROM cognitive_objects o JOIN question_states q ON o.id=q.object_id")
        if state:
            sql += " WHERE q.state=?"
        sql += " ORDER BY q.updated_at DESC,o.id LIMIT ?"
        args: tuple[Any, ...] = (state, limit) if state else (limit,)
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def search(self, query: str, *, limit: int = 20, include_archived: bool = False) -> list[dict[str, Any]]:
        """Trigram literal phrase with literal substring fallback for short/unindexed inputs."""
        query = _required(query, "query")
        limit = _positive_limit(limit)
        archive_sql = "" if include_archived else " AND o.status <> 'archived'"
        results: list[sqlite3.Row] = []
        if len(query) >= 3:
            literal_phrase = '"' + query.replace('"', '""') + '"'
            try:
                results = self.db.execute(
                    "SELECT o.* FROM object_fts f JOIN cognitive_objects o ON o.row_id=f.rowid "
                    "WHERE object_fts MATCH ?" + archive_sql + " ORDER BY bm25(object_fts),o.id LIMIT ?",
                    (literal_phrase, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                # A malformed or unsupported tokenizer query may degrade retrieval,
                # but must never become raw SQL or crash a user search.
                results = []
        if not results:
            pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            results = self.db.execute(
                "SELECT o.* FROM cognitive_objects o WHERE (o.title LIKE ? ESCAPE '\\' "
                "OR o.body LIKE ? ESCAPE '\\')" + archive_sql + " ORDER BY o.updated_at DESC,o.id LIMIT ?",
                (pattern, pattern, limit),
            ).fetchall()
        return [dict(r) for r in results]

    def neighborhood(self, object_id: str, *, depth: int = 1, limit: int = 100,
                     include_archived: bool = False) -> dict[str, Any]:
        if type(depth) is not int or depth not in (1, 2):
            raise InvalidInput("neighborhood depth must be 1 or 2")
        limit = _positive_limit(limit, maximum=500)
        origin = self.get_object(object_id)
        seen = {object_id}
        distance = {object_id: 0}
        frontier = {object_id}
        edges: dict[str, dict[str, Any]] = {}
        for hop in range(1, depth + 1):
            if not frontier or len(seen) >= limit:
                break
            placeholders = ",".join("?" for _ in frontier)
            args = tuple(frontier) + tuple(frontier)
            rows = self.db.execute(
                f"SELECT r.* FROM relations r WHERE r.status='active' AND "
                f"(r.from_object_id IN ({placeholders}) OR r.to_object_id IN ({placeholders})) ORDER BY r.id",
                args,
            ).fetchall()
            upcoming: set[str] = set()
            for r in rows:
                a, b = r["from_object_id"], r["to_object_id"]
                other = b if a in frontier else a
                if other not in seen:
                    obj = self._get_object_tx(other)
                    if obj["status"] == "archived" and not include_archived:
                        continue
                    if len(seen) >= limit:
                        continue
                    seen.add(other)
                    distance[other] = hop
                    upcoming.add(other)
                if a in seen and b in seen:
                    edges[r["id"]] = dict(r)
            frontier = upcoming
        nodes = [self.get_object(node) for node in sorted(seen, key=lambda x: (distance[x], x))]
        return {"root": origin["id"], "nodes": nodes, "distances": distance,
                "edges": list(edges.values())}

    def create_conversation(self, title: str, *, source: str = "live") -> dict[str, Any]:
        _choice(source, SOURCES, "conversation source")
        cid = _id("conv")
        with self.transaction():
            self.db.execute("INSERT INTO conversations(id,source,title) VALUES(?,?,?)", (cid, source, title.strip()))
            self._audit("conversation", cid, "created", {"source": source, "title": title.strip()})
        return self._one("SELECT * FROM conversations WHERE id=?", (cid,))

    def append_message(self, conversation_id: str, role: str, content: str) -> dict[str, Any]:
        _choice(role, ROLES, "role")
        content = _content(content, "message content")
        with self.transaction():
            self._one("SELECT id FROM conversations WHERE id=?", (conversation_id,), name="conversation")
            next_turn = self.db.execute("SELECT COALESCE(MAX(turn_index)+1,0) FROM messages WHERE conversation_id=?",
                                        (conversation_id,)).fetchone()[0]
            msg_id = _id("msg")
            self.db.execute("INSERT INTO messages(id,conversation_id,turn_index,role,content) VALUES(?,?,?,?,?)",
                            (msg_id, conversation_id, next_turn, role, content))
            self._audit("conversation", conversation_id, "message_appended", {"message_id": msg_id,
                                                                              "turn_index": next_turn, "role": role})
            return self._one("SELECT * FROM messages WHERE id=?", (msg_id,))

    def list_conversations(self, limit: int = 100) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(
            "SELECT c.*,COUNT(m.id) AS message_count FROM conversations c LEFT JOIN messages m "
            "ON c.id=m.conversation_id GROUP BY c.id ORDER BY c.created_at DESC,c.id LIMIT ?",
            (_positive_limit(limit),)).fetchall()]

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        conv = self._one("SELECT * FROM conversations WHERE id=?", (conversation_id,), name="conversation")
        conv["messages"] = [dict(r) for r in self.db.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY turn_index", (conversation_id,)).fetchall()]
        return conv

    def import_conversation_json(self, source_path: str | Path) -> dict[str, Any]:
        """Import only VKF normalized JSON, not native ChatGPT/Claude exports.

        Schema: {source, title, messages:[{role,content}]}. Canonical content is
        deduplicated regardless of filename/title. Imported messages remain in DB.
        """
        p = Path(source_path)
        if not p.is_file():
            raise NotFound(f"import file not found: {p}")
        if p.stat().st_size > 20_000_000:
            raise InvalidInput("JSON import exceeds the 20MB first-version safety limit")
        raw = p.read_bytes()
        try:
            doc = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise InvalidInput(f"invalid UTF-8 JSON: {exc}") from exc
        if not isinstance(doc, dict) or not isinstance(doc.get("messages"), list) or not doc["messages"]:
            raise InvalidInput("JSON must contain a nonempty 'messages' array")
        source = _choice(doc.get("source", "other"), SOURCES, "conversation source")
        title = str(doc.get("title", "")).strip()
        records = []
        for idx, item in enumerate(doc["messages"]):
            if not isinstance(item, dict):
                raise InvalidInput(f"message {idx} must be an object")
            role = _choice(item.get("role"), ROLES, f"message {idx} role")
            content = _content(item.get("content"), f"message {idx} content")
            records.append({"role": role, "content": content})
        normalized_hash = _digest({"source": source, "messages": records})
        raw_hash = hashlib.sha256(raw).hexdigest()
        with self.transaction():
            existing = self.db.execute("SELECT id FROM conversations WHERE normalized_sha256=?",
                                       (normalized_hash,)).fetchone()
            if existing:
                return {"conversation_id": existing[0], "created": False, "message_count": len(records)}
            batch_id, conversation_id = _id("batch"), _id("conv")
            self.db.execute("INSERT INTO import_batches(id,format,raw_sha256,archive_path) VALUES(?,?,?,?)",
                            (batch_id, "vkf-json-v1", raw_hash, str(p.resolve())))
            self.db.execute("INSERT INTO conversations(id,source,title,normalized_sha256,import_batch_id) VALUES(?,?,?,?,?)",
                            (conversation_id, source, title, normalized_hash, batch_id))
            self.db.executemany(
                "INSERT INTO messages(id,conversation_id,turn_index,role,content) VALUES(?,?,?,?,?)",
                [(_id("msg"), conversation_id, index, rec["role"], rec["content"])
                 for index, rec in enumerate(records)],
            )
            self._audit("conversation", conversation_id, "imported", {"source": source,
                                                                     "message_count": len(records),
                                                                     "normalized_sha256": normalized_hash})
            return {"conversation_id": conversation_id, "created": True, "message_count": len(records)}

    def propose_candidate(self, conversation_id: str, message_id: str, kind: str,
                          title: str, body: str, *, model_id: str = "manual-simulation",
                          prompt_version: str = "manual-v1") -> dict[str, Any]:
        """Simulates a model suggestion; no API is called. Idempotent by content/source."""
        kind, title, body, _, _ = self._normalize_object(kind, title, body, None, None)
        with self.transaction():
            msg = self._one("SELECT * FROM messages WHERE id=?", (message_id,), name="source message")
            if msg["conversation_id"] != conversation_id:
                raise InvalidInput("message does not belong to conversation")
            key = _digest([conversation_id, message_id, kind, title, body, model_id, prompt_version])
            existing = self.db.execute("SELECT id FROM extraction_runs WHERE idempotency_key=?", (key,)).fetchone()
            if existing:
                result = self.db.execute("SELECT * FROM candidates WHERE extraction_run_id=?", (existing[0],)).fetchone()
                if result:
                    return dict(result)
                raise Conflict("a matching extraction run exists without its candidate; manual inspection needed")
            run_id, candidate_id = _id("run"), _id("cand")
            self.db.execute("""INSERT INTO extraction_runs(id,conversation_id,start_turn,end_turn,model_id,
                            prompt_version,idempotency_key,state) VALUES(?,?,?,?,?,?,?,'completed')""",
                            (run_id, conversation_id, msg["turn_index"], msg["turn_index"], model_id, prompt_version, key))
            self.db.execute("INSERT INTO candidates(id,extraction_run_id,proposal_index,kind,title,body) VALUES(?,?,?,?,?,?)",
                            (candidate_id, run_id, 0, kind, title, body))
            self.db.execute("INSERT INTO candidate_sources(candidate_id,message_id) VALUES(?,?)", (candidate_id, message_id))
            self._audit("candidate", candidate_id, "proposed", {"kind": kind, "source_message_id": message_id},
                        actor="workflow")
            return self._one("SELECT * FROM candidates WHERE id=?", (candidate_id,))

    def list_candidates(self, *, state: str | None = "pending", limit: int = 100) -> list[dict[str, Any]]:
        if state is not None:
            _choice(state, {"pending", "approved", "merged", "rejected"}, "candidate state")
        sql = "SELECT * FROM candidates"
        if state == "pending":
            sql += " WHERE state=? AND NOT EXISTS (SELECT 1 FROM candidate_equivalences ce WHERE ce.duplicate_candidate_id=candidates.id)"
        elif state:
            sql += " WHERE state=?"
        sql += " ORDER BY created_at DESC,id LIMIT ?"
        args: tuple[Any, ...] = (state, _positive_limit(limit)) if state else (_positive_limit(limit),)
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def get_candidate(self, candidate_id: str) -> dict[str, Any]:
        result = self._one("SELECT * FROM candidates WHERE id=?", (candidate_id,), name="candidate")
        result["sources"] = [r[0] for r in self.db.execute("SELECT message_id FROM candidate_sources WHERE candidate_id=?",
                                                           (candidate_id,)).fetchall()]
        return result

    def _pending_candidate_tx(self, candidate_id: str) -> dict[str, Any]:
        cand = self._one("SELECT * FROM candidates WHERE id=?", (candidate_id,), name="candidate")
        if cand["state"] != "pending":
            raise Conflict(f"candidate already resolved: {cand['state']}")
        if self.db.execute("SELECT 1 FROM candidate_equivalences WHERE duplicate_candidate_id=?", (candidate_id,)).fetchone():
            raise Conflict("candidate is consolidated into another pending candidate; review its canonical candidate")
        return cand

    def approve_candidate(self, candidate_id: str, *, synthesized_from: list[str] | None = None,
                          synthesis_rationale: str | None = None,
                          confirm_understanding: bool = False) -> dict[str, Any]:
        with self.transaction():
            cand = self._pending_candidate_tx(candidate_id)
            if cand['kind'] == 'understanding' and not confirm_understanding:
                raise InvalidInput('understanding requires explicit user confirmation (--confirm-understanding); AI explanations do not establish user mastery')
            sources = self._validate_synthesis(cand["kind"], synthesized_from, synthesis_rationale)
            obj = self._create_object_tx(kind=cand["kind"], title=cand["title"], body=cand["body"],
                                         origin_actor="mixed", epistemic_status=None,
                                         understanding_level=None, actor="user",
                                         reason=f"approved candidate {candidate_id}")
            self.db.execute("""INSERT INTO object_sources(object_id,message_id,source_role)
                SELECT ?,message_id,'origin' FROM candidate_sources WHERE candidate_id=?""",
                (obj["id"], candidate_id))
            for source in sources:
                self._add_relation_tx(obj["id"], source, "synthesizes", synthesis_rationale or "", "mixed")
            self.db.execute("UPDATE candidates SET state='approved',resolved_object_id=? WHERE id=?",
                            (obj["id"], candidate_id))
            # A confirmed canonical candidate resolves all reviewed equivalent aliases.
            self.db.execute("""UPDATE candidates SET state='merged',resolved_object_id=? WHERE id IN
                (SELECT duplicate_candidate_id FROM candidate_equivalences WHERE canonical_candidate_id=?)
                AND state='pending'""", (obj['id'],candidate_id))
            self.db.execute("""INSERT OR IGNORE INTO object_topics(object_id,topic_id)
                SELECT ?,topic_id FROM candidate_topics WHERE candidate_id=?""",(obj['id'],candidate_id))
            self._audit("candidate", candidate_id, "approved", {"object_id": obj["id"]})
            return self.get_object(obj["id"])

    def merge_candidate(self, candidate_id: str, target_object_id: str, *, reason: str,
                        new_body: str | None = None, expected_revision: int | None = None) -> dict[str, Any]:
        _required(reason, "reason")
        with self.transaction():
            cand = self._pending_candidate_tx(candidate_id)
            target = self._get_object_tx(target_object_id)
            if target["kind"] != cand["kind"]:
                raise InvalidInput("candidate and merge target must have the same kind")
            if target["status"] == "archived":
                raise InvalidInput("cannot merge into archived object")
            if expected_revision is not None and expected_revision != target["revision"]:
                raise Conflict("merge target has a newer revision")
            if new_body is not None:
                self._update_object_tx(target_object_id, {"body": new_body}, reason, expected_revision)
            self.db.execute("""INSERT OR IGNORE INTO object_sources(object_id,message_id,source_role)
                SELECT ?,message_id,'support' FROM candidate_sources WHERE candidate_id=?""",
                (target_object_id, candidate_id))
            self.db.execute("UPDATE candidates SET state='merged',resolved_object_id=? WHERE id=?",
                            (target_object_id, candidate_id))
            self.db.execute("""UPDATE candidates SET state='merged',resolved_object_id=? WHERE id IN
                (SELECT duplicate_candidate_id FROM candidate_equivalences WHERE canonical_candidate_id=?)
                AND state='pending'""", (target_object_id,candidate_id))
            self.db.execute("""INSERT OR IGNORE INTO object_topics(object_id,topic_id)
                SELECT ?,topic_id FROM candidate_topics WHERE candidate_id=?""",(target_object_id,candidate_id))
            self._audit("candidate", candidate_id, "merged", {"target_id": target_object_id,
                                                              "new_body": new_body is not None, "reason": reason})
            return self.get_object(target_object_id)

    def reject_candidate(self, candidate_id: str, *, reason: str) -> dict[str, Any]:
        _required(reason, "reason")
        with self.transaction():
            self._pending_candidate_tx(candidate_id)
            self.db.execute("UPDATE candidates SET state='rejected' WHERE id=?", (candidate_id,))
            self._audit("candidate", candidate_id, "rejected", {"reason": reason})
            return self.get_candidate(candidate_id)

    def suggest_frontier(self, source_object_id: str, question_object_id: str,
                         signal: str, rationale: str) -> dict[str, Any]:
        _choice(signal, FRONTIER_SIGNALS, "frontier signal")
        rationale = _required(rationale, "rationale")
        # Worded-differently but equivalent suggestions should not flood the inbox.
        key = _digest([source_object_id, question_object_id, signal])
        with self.transaction():
            src = self._get_object_tx(source_object_id)
            target = self.get_object(question_object_id)
            if src["status"] == "archived" or target["status"] == "archived":
                raise InvalidInput("frontier suggestion cannot involve archived objects")
            if target["kind"] != "question" or target["question_state"]["state"] not in {"open", "exploring"}:
                raise InvalidInput("frontier suggestion must target an open or exploring question")
            existing = self.db.execute("SELECT * FROM frontier_suggestions WHERE idempotency_key=?", (key,)).fetchone()
            if existing:
                return dict(existing)
            suggestion_id = _id("frontier")
            self.db.execute("""INSERT INTO frontier_suggestions(id,source_object_id,question_object_id,
                signal,rationale,idempotency_key) VALUES(?,?,?,?,?,?)""",
                (suggestion_id, source_object_id, question_object_id, signal, rationale, key))
            self._audit("frontier", suggestion_id, "suggested", {"source_id": source_object_id,
                                                                 "question_id": question_object_id, "signal": signal},
                        actor="workflow")
            return self._one("SELECT * FROM frontier_suggestions WHERE id=?", (suggestion_id,))

    def list_frontier(self, *, state: str | None = "pending", limit: int = 100) -> list[dict[str, Any]]:
        if state:
            _choice(state, {"pending", "accepted", "dismissed", "snoozed"}, "frontier state")
        sql = "SELECT * FROM frontier_suggestions" + (" WHERE state=?" if state else "") + " ORDER BY created_at DESC,id LIMIT ?"
        args = (state, _positive_limit(limit)) if state else (_positive_limit(limit),)
        return [dict(x) for x in self.db.execute(sql, args).fetchall()]

    def decide_frontier(self, suggestion_id: str, state: str, *, reason: str) -> dict[str, Any]:
        _choice(state, {"accepted", "dismissed", "snoozed"}, "frontier decision")
        _required(reason, "reason")
        with self.transaction():
            existing = self._one("SELECT * FROM frontier_suggestions WHERE id=?", (suggestion_id,), name="suggestion")
            if existing["state"] != "pending":
                raise Conflict("frontier suggestion already decided")
            self.db.execute("UPDATE frontier_suggestions SET state=? WHERE id=?", (state, suggestion_id))
            self._audit("frontier", suggestion_id, "decided", {"state": state, "reason": reason})
            return self._one("SELECT * FROM frontier_suggestions WHERE id=?", (suggestion_id,))

    def log_model_call(self, *, purpose: str, model_id: str, prompt_version: str,
                       input_fingerprint: str, selected_objects: list[dict[str, Any]] | None = None,
                       conversation_id: str | None = None, context_policy_version: str = "v1") -> dict[str, Any]:
        _choice(purpose, {"chat", "extraction", "link", "frontier"}, "model-call purpose")
        fingerprint = _required(input_fingerprint, "input_fingerprint").lower()
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise InvalidInput("input_fingerprint must be a SHA-256 hexadecimal digest, never raw prompts")
        if selected_objects is not None and not isinstance(selected_objects, list):
            raise InvalidInput("selected_objects must be a list of {id,revision} records")
        selected_objects = selected_objects or []
        with self.transaction():
            for item in selected_objects:
                if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                        or type(item.get("revision")) is not int or item["revision"] < 1):
                    raise InvalidInput("selected_objects entries require an object id and positive integer revision")
                if not self.db.execute("SELECT 1 FROM object_versions WHERE object_id=? AND revision=?",
                                       (item["id"], item["revision"])).fetchone():
                    raise InvalidInput("selected_objects contains an unknown object revision")
            call_id = _id("call")
            self.db.execute("""INSERT INTO model_calls(id,purpose,conversation_id,model_id,prompt_version,
                            context_policy_version,selected_objects_json,input_fingerprint,state)
                            VALUES(?,?,?,?,?,?,?,?,'running')""",
                            (call_id, purpose, conversation_id, _required(model_id, "model_id"),
                             _required(prompt_version, "prompt_version"), context_policy_version,
                             _json(selected_objects), fingerprint))
            return self._one("SELECT * FROM model_calls WHERE id=?", (call_id,))

    def finish_model_call(self, call_id: str, *, success: bool,
                          input_tokens: int | None = None, output_tokens: int | None = None,
                          error_message: str = "") -> dict[str, Any]:
        for n in (input_tokens, output_tokens):
            if n is not None and (type(n) is not int or n < 0):
                raise InvalidInput("token counters must be nonnegative integers")
        with self.transaction():
            current = self._one("SELECT * FROM model_calls WHERE id=?", (call_id,), name="model call")
            if current["state"] != "running":
                raise Conflict("model call already completed")
            self.db.execute("UPDATE model_calls SET state=?,input_tokens=?,output_tokens=?,error_message=? WHERE id=?",
                            ("completed" if success else "failed", input_tokens, output_tokens, error_message, call_id))
            return self._one("SELECT * FROM model_calls WHERE id=?", (call_id,))

    def stats(self) -> dict[str, Any]:
        counts = {table: self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in TABLES_TO_EXPORT}
        kinds = {r[0]: r[1] for r in self.db.execute(
            "SELECT kind,COUNT(*) FROM cognitive_objects GROUP BY kind").fetchall()}
        qstates = {r[0]: r[1] for r in self.db.execute(
            "SELECT state,COUNT(*) FROM question_states GROUP BY state").fetchall()}
        return {"database": self.path, "schema_version": SCHEMA_VERSION,
                "table_counts": counts, "kinds": kinds, "question_states": qstates}

    def doctor(self) -> dict[str, Any]:
        problems: list[str] = []
        integrity = self.db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            problems.append(f"integrity_check: {integrity}")
        fk = self.db.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            problems.append(f"foreign_key_check: {len(fk)} violations")
        # Repository invariants not all expressible in SQLite CHECK constraints.
        for row in self.db.execute("""SELECT o.id FROM cognitive_objects o LEFT JOIN question_states q
           ON o.id=q.object_id WHERE o.kind='question' AND q.object_id IS NULL"""):
            problems.append(f"missing question state: {row[0]}")
        for row in self.db.execute("""SELECT o.id FROM cognitive_objects o LEFT JOIN object_versions v
           ON o.id=v.object_id AND o.revision=v.revision WHERE v.object_id IS NULL"""):
            problems.append(f"missing current object version: {row[0]}")
        for obj in self.db.execute("SELECT * FROM cognitive_objects"):
            version = self.db.execute(
                "SELECT snapshot_json FROM object_versions WHERE object_id=? AND revision=?",
                (obj["id"], obj["revision"])).fetchone()
            if version:
                try:
                    if any(json.loads(version[0]).get(k) != obj[k] for k in obj.keys()):
                        problems.append(f"current object differs from version snapshot: {obj['id']}")
                except (json.JSONDecodeError, TypeError):
                    problems.append(f"invalid version snapshot: {obj['id']}")
            count = self.db.execute("SELECT COUNT(*) FROM object_versions WHERE object_id=?",
                                    (obj["id"],)).fetchone()[0]
            if count != obj["revision"]:
                problems.append(f"noncontiguous revision history: {obj['id']}")
        n_fts = self.db.execute("SELECT COUNT(*) FROM object_fts").fetchone()[0]
        n_obj = self.db.execute("SELECT COUNT(*) FROM cognitive_objects").fetchone()[0]
        if n_fts != n_obj:
            problems.append(f"FTS index row count {n_fts} differs from cognitive object count {n_obj}")
        for row in self.db.execute("""SELECT o.id FROM cognitive_objects o LEFT JOIN relations r
           ON o.id=r.from_object_id AND r.kind='synthesizes' AND r.status='active'
           WHERE o.kind='cross_insight' AND o.status='active'
           GROUP BY o.id HAVING COUNT(r.id)<2"""):
            problems.append(f"cross_insight lacks two active synthesis sources: {row[0]}")
        for row in self.db.execute("""SELECT c.id FROM candidates c LEFT JOIN candidate_sources s
           ON c.id=s.candidate_id WHERE c.state='approved'
           GROUP BY c.id HAVING COUNT(s.message_id)=0"""):
            problems.append(f"approved candidate lacks origins: {row[0]}")
        # Research-level invariants beyond FK constraints.
        for row in self.db.execute('''SELECT v.id FROM contextual_views v
            LEFT JOIN research_space_contexts sc ON sc.space_id=v.space_id AND sc.context_id=v.context_id
            WHERE sc.space_id IS NULL'''):
            problems.append(f'research view context not in space: {row[0]}')
        for row in self.db.execute('''SELECT v.id FROM contextual_views v
            LEFT JOIN contextual_views p ON p.id=v.parent_view_id
            WHERE v.parent_view_id IS NOT NULL AND (p.space_id IS NULL OR p.space_id<>v.space_id)'''):
            problems.append(f'research view parent outside space: {row[0]}')
        for row in self.db.execute('''SELECT v.id FROM contextual_views v
            LEFT JOIN view_evidence_spans es ON es.view_id=v.id
            GROUP BY v.id HAVING COUNT(es.message_id)=0'''):
            problems.append(f'research view lacks source evidence: {row[0]}')
        for row in self.db.execute('''SELECT s.id FROM research_spaces s
            LEFT JOIN research_space_versions v ON v.space_id=s.id AND v.revision=s.revision
            WHERE v.space_id IS NULL'''):
            problems.append(f'research space lacks current snapshot: {row[0]}')
        for row in self.db.execute('''SELECT m.id FROM research_maps m
            WHERE (m.status='applied' AND m.reviewed_space_id IS NULL)
               OR (m.status='pending' AND m.reviewed_space_id IS NOT NULL)'''):
            problems.append(f'research map has inconsistent review state: {row[0]}')
        return {"ok": not problems, "integrity": integrity,
                "foreign_key_violations": len(fk), "problems": problems}

    @staticmethod
    def _target_new(path: str | Path) -> Path:
        p = Path(path).expanduser().resolve()
        if p.exists():
            raise Conflict(f"refusing to overwrite existing file: {p}")
        p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        return p

    def backup(self, destination: str | Path) -> dict[str, Any]:
        target = self._target_new(destination)
        temp = target.with_name(target.name + ".tmp-" + uuid4().hex)
        try:
            fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(fd)
            with closing(sqlite3.connect(temp)) as backup_db:
                self.db.backup(backup_db)
            # Integrity check before publishing backup.
            with closing(sqlite3.connect(temp)) as verify:
                if verify.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise VKFError("backup failed SQLite integrity check")
            os.replace(temp, target)
            return {"backup": str(target), "size_bytes": target.stat().st_size}
        finally:
            if temp.exists():
                temp.unlink()

    @classmethod
    def restore_backup(cls, source: str | Path, destination: str | Path) -> dict[str, Any]:
        src = Path(source)
        if not src.is_file():
            raise NotFound("backup source does not exist")
        dest = cls._target_new(destination)
        temp = dest.with_name(dest.name + ".tmp-" + uuid4().hex)
        try:
            fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(fd)
            with closing(sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True)) as source_db:
                if source_db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                    raise UnsupportedSchema("backup is not a VKF version 2 database")
                if source_db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise VKFError("backup integrity check failed")
                with closing(sqlite3.connect(temp)) as output:
                    source_db.backup(output)
            os.replace(temp, dest)
            with cls(dest) as restored:
                report = restored.doctor()
            if not report["ok"]:
                # Do not publish a backup that fails logical invariants.
                dest.unlink(missing_ok=True)
                raise VKFError(f"restored database failed doctor: {report['problems']}")
            return {"restored_database": str(dest), "doctor": report}
        finally:
            if temp.exists():
                temp.unlink()

    def export_json(self, destination: str | Path) -> dict[str, Any]:
        target = self._target_new(destination)
        with self.transaction():
            payload = {"format": "vkf-readable-snapshot-v1", "schema_version": SCHEMA_VERSION,
                       "exported_at": _now(), "tables": {
                           name: [dict(r) for r in self.db.execute(f"SELECT * FROM {name}").fetchall()]
                           for name in TABLES_TO_EXPORT}}
        temp = target.with_name(target.name + ".tmp-" + uuid4().hex)
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(payload, out, ensure_ascii=False, indent=2)
                out.write("\n")
            os.replace(temp, target)
            return {"export": str(target), "format": payload["format"]}
        finally:
            if temp.exists():
                temp.unlink()
