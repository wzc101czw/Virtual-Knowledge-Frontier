"""Deterministic offline regression checks for VKF Storage Core."""
from __future__ import annotations
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from vkf_storage import Storage, Conflict, InvalidInput, NotFound, UnsupportedSchema

ROOT = Path(__file__).resolve().parents[1]


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "test.db"
        Storage.initialize(self.path)
        self.st = Storage(self.path)
        self.addCleanup(self.st.close)

    def obj(self, title="A", kind="knowledge", body="knowledge", **kwargs):
        return self.st.create_object(kind, title, body, **kwargs)

    def test_init_reload_and_sanity(self):
        self.assertEqual(self.st.db.execute("PRAGMA user_version").fetchone()[0], 3)
        self.assertEqual(self.st.db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        a = self.obj(title="KV Cache", body="中文/English observations")
        with Storage(self.path) as second:
            self.assertEqual(second.get_object(a["id"])["body"], "中文/English observations")
            self.assertTrue(second.doctor()["ok"])
        self.assertEqual(Storage.initialize(self.path)["schema_version"], 3)

    def test_init_upgrade_previous_v1_without_losing_data(self):
        oldpath = Path(self.tmp.name) / "previous.db"
        script = (ROOT / "vkf_storage" / "migrations" / "001_initial.sql").read_text(encoding="utf8")
        with closing(sqlite3.connect(oldpath)) as db, db:
            db.executescript(script)
            db.execute("INSERT INTO conversations(id,source,title) VALUES('old','other','older conversation')")
        with self.assertRaises(UnsupportedSchema):
            Storage(oldpath)
        self.assertEqual(Storage.initialize(oldpath)["schema_version"], 3)
        with Storage(oldpath) as db:
            self.assertEqual(db.get_conversation("old")["title"], "older conversation")
            self.assertEqual(db.db.execute("PRAGMA user_version").fetchone()[0], 3)

    def test_never_overwrite_non_vkf_database(self):
        bad = Path(self.tmp.name) / "not-vkf.db"
        with closing(sqlite3.connect(bad)) as db, db:
            db.execute("CREATE TABLE precious(x TEXT)")
            db.execute("INSERT INTO precious VALUES('retain me')")
        with self.assertRaises(UnsupportedSchema):
            Storage.initialize(bad)
        with closing(sqlite3.connect(bad)) as db, db:
            self.assertEqual(db.execute("SELECT x FROM precious").fetchone()[0], "retain me")

    def test_cognitive_kinds_and_raw_body_preserved(self):
        for kind in ["knowledge", "idea", "understanding", "question"]:
            a = self.obj(title="认识：" + kind, kind=kind, body="    code indent\n  second\n")
            self.assertEqual(a["body"], "    code indent\n  second\n")
            if kind == "question":
                self.assertEqual(a["epistemic_status"], "not_applicable")
                self.assertEqual(a["question_state"]["state"], "open")
            elif kind == "understanding":
                self.assertEqual(a["understanding_level"], "provisional")
        self.assertTrue(self.st.doctor()["ok"])
        with self.assertRaises(InvalidInput):
            self.obj(kind="question", epistemic_status="asserted")
        with self.assertRaises(InvalidInput):
            self.obj(body="  \n ")

    def test_versions_restore_and_optimistic_conflict(self):
        a = self.obj(title="First", body="one")
        b = self.st.update_object(a["id"], title="Second", body="two", reason="new evidence", expected_revision=1)
        self.assertEqual(b["revision"], 2)
        with self.assertRaises(Conflict):
            self.st.update_object(a["id"], title="stale", reason="bad", expected_revision=1)
        self.assertEqual(self.st.get_object(a["id"])["title"], "Second")
        restored = self.st.restore_object_revision(a["id"], 1, reason="prefer original", expected_revision=2)
        self.assertEqual((restored["title"], restored["body"], restored["revision"]), ("First", "one", 3))
        self.assertEqual([x["revision"] for x in self.st.object_history(a["id"])], [1, 2, 3])
        self.assertEqual(self.st.db.execute("SELECT COUNT(*) FROM audit_events WHERE entity_id=?",
                                            (a["id"],)).fetchone()[0], 4)
        with self.assertRaises(sqlite3.IntegrityError):
            self.st.db.execute("DELETE FROM object_versions WHERE object_id=?", (a["id"],))

    def test_object_states_and_kind_locked(self):
        a = self.obj()
        self.st.update_object(a["id"], status="challenged", reason="potential conflict")
        self.st.update_object(a["id"], status="archived", reason="retire")
        with self.assertRaises(InvalidInput):
            self.st.update_object(a["id"], status="challenged", reason="invalid transition")
        self.st.update_object(a["id"], status="active", reason="revisit")
        with self.assertRaises(sqlite3.IntegrityError):
            self.st.db.execute("UPDATE cognitive_objects SET kind='idea' WHERE id=?", (a["id"],))
        self.assertTrue(self.st.doctor()["ok"])

    def test_symmetric_relations_and_invalid_targets(self):
        a = self.obj(title="a"); b = self.obj(title="b")
        q = self.obj(title="Q", kind="question")
        result = self.st.add_relation(b["id"], a["id"], "analogous_to", "share tradeoffs")
        self.assertLess(result["from_object_id"], result["to_object_id"])
        with self.assertRaises(Conflict):
            self.st.add_relation(a["id"], b["id"], "analogous_to", "duplicate")
        with self.assertRaises(InvalidInput):
            self.st.add_relation(a["id"], b["id"], "answers", "not question")
        with self.assertRaises(InvalidInput):
            self.st.add_relation(a["id"], a["id"], "supports", "self loop")
        self.st.add_relation(a["id"], q["id"], "raises", "open direction")
        self.assertEqual(len(self.st.list_relations(q["id"])), 1)
        self.assertTrue(self.st.doctor()["ok"])

    def test_cross_insight_requires_two_sources_atomically(self):
        a = self.obj(title="kv", body="cache values")
        b = self.obj(title="db", body="materialized results")
        count0 = self.st.stats()["table_counts"]["cognitive_objects"]
        with self.assertRaises(InvalidInput):
            self.obj(title="unfinished", kind="cross_insight", body="a similarity")
        with self.assertRaises(NotFound):
            self.obj(title="broken", kind="cross_insight", body="a link", synthesized_from=[a["id"], "ghost"],
                     synthesis_rationale="cross domain")
        self.assertEqual(self.st.stats()["table_counts"]["cognitive_objects"], count0)
        insight = self.obj(title="caching analogy", kind="cross_insight", body="similarity; differences; hypothesis",
                           synthesized_from=[a["id"], b["id"]], synthesis_rationale="tradeoff of computation/storage")
        links = self.st.list_relations(insight["id"])
        self.assertEqual(len(links), 2)
        with self.assertRaises(Conflict):
            self.st.set_relation_status(links[0]["id"], "archived", reason="would break invariant")
        self.assertTrue(self.st.doctor()["ok"])

    def test_question_resolution_and_answer_relation_guard(self):
        q = self.obj(title="When to cache?", kind="question")
        a = self.obj(title="Possible answer")
        with self.assertRaises(sqlite3.IntegrityError):
            self.st.set_question_state(q["id"], "answered", reason="premature")
        rel = self.st.add_relation(a["id"], q["id"], "answers", "one evidence-backed explanation")
        self.st.set_question_state(q["id"], "answered", reason="person reviewed")
        with self.assertRaises(sqlite3.IntegrityError):
            self.st.set_relation_status(rel["id"], "archived", reason="remove only answer")
        with self.assertRaises(sqlite3.IntegrityError):
            self.st.set_question_state(q["id"], "parked", reason="invalid jump")
        self.st.set_question_state(q["id"], "open", reason="counterexample found")
        self.st.set_relation_status(rel["id"], "archived", reason="answer is now challenged")
        self.assertEqual(self.st.get_object(q["id"])["question_state"]["state"], "open")
        self.st.set_question_state(q["id"], "exploring", reason="investigating")
        self.st.set_question_state(q["id"], "answered", reason="new manual synthesis",
                                   resolution_note="We prefer computation under constraints.")
        self.assertTrue(self.st.doctor()["ok"])

    def test_candidate_isolation_approval_and_idempotency(self):
        conv = self.st.create_conversation("Ideas")
        msg = self.st.append_message(conv["id"], "assistant", "What about caching?")
        cand = self.st.propose_candidate(conv["id"], msg["id"], "idea", "Cache ideas", "Think about invalidation")
        self.assertEqual(len(self.st.search("Cache ideas")), 0)
        self.assertEqual(self.st.stats()["table_counts"]["cognitive_objects"], 0)
        same = self.st.propose_candidate(conv["id"], msg["id"], "idea", "Cache ideas", "Think about invalidation")
        self.assertEqual(cand["id"], same["id"])
        created = self.st.approve_candidate(cand["id"])
        self.assertEqual(created["origin_actor"], "mixed")
        self.assertEqual(len(self.st.search("Cache ideas")), 1)
        self.assertEqual(self.st.get_candidate(cand["id"])["resolved_object_id"], created["id"])
        self.assertEqual(self.st.db.execute("SELECT COUNT(*) FROM object_sources WHERE object_id=?",
                                            (created["id"],)).fetchone()[0], 1)
        with self.assertRaises(Conflict):
            self.st.approve_candidate(cand["id"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.st.db.execute("UPDATE candidates SET body='tampered' WHERE id=?", (cand["id"],))
        self.assertTrue(self.st.doctor()["ok"])

    def test_candidate_approval_cross_insight_requires_legal_sources(self):
        conv = self.st.create_conversation("Memory")
        msg = self.st.append_message(conv["id"], "user", "Cache vs memory")
        a = self.obj(title="cache", body="computed state")
        b = self.obj(title="memory", body="stored facts")
        c = self.st.propose_candidate(conv["id"], msg["id"], "cross_insight", "Analogy", "similarities and differences")
        with self.assertRaises(InvalidInput):
            self.st.approve_candidate(c["id"], synthesized_from=[a["id"]], synthesis_rationale="only one")
        self.assertEqual(self.st.get_candidate(c["id"])["state"], "pending")
        approved = self.st.approve_candidate(c["id"], synthesized_from=[a["id"], b["id"]],
                                             synthesis_rationale="both reuse work but have different invalidation")
        self.assertEqual(approved["kind"], "cross_insight")
        self.assertTrue(self.st.doctor()["ok"])

    def test_candidate_merge_and_reject(self):
        target = self.obj(title="KB", body="old formulation")
        conv = self.st.create_conversation("Merge")
        msg = self.st.append_message(conv["id"], "user", "new observation")
        c = self.st.propose_candidate(conv["id"], msg["id"], "knowledge", "KB", "new formulation")
        with self.assertRaises(Conflict):
            self.st.merge_candidate(c["id"], target["id"], reason="merge", new_body="updated", expected_revision=42)
        self.assertEqual(self.st.get_candidate(c["id"])["state"], "pending")
        merged = self.st.merge_candidate(c["id"], target["id"], reason="incorporate newer idea",
                                         new_body="old and new formulation", expected_revision=1)
        self.assertEqual(merged["revision"], 2)
        self.assertEqual(self.st.get_candidate(c["id"])["state"], "merged")
        self.assertEqual(self.st.db.execute("SELECT COUNT(*) FROM object_sources WHERE object_id=?",
                                            (target["id"],)).fetchone()[0], 1)
        c2 = self.st.propose_candidate(conv["id"], msg["id"], "idea", "weak", "maybe not")
        self.st.reject_candidate(c2["id"], reason="low value")
        self.assertEqual(self.st.get_candidate(c2["id"])["state"], "rejected")
        with self.assertRaises(Conflict):
            self.st.reject_candidate(c2["id"], reason="second reject")

    def test_normalized_json_import_deduplicated_and_preserves_messages(self):
        doc = {"source": "chatgpt", "title": "A conversation", "messages": [
            {"role": "user", "content": "    def fn():\n        pass\n"},
            {"role": "assistant", "content": "Observations"}]}
        f = Path(self.tmp.name) / "conv.json"
        f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf8")
        first = self.st.import_conversation_json(f)
        self.assertTrue(first["created"])
        self.assertEqual(self.st.get_conversation(first["conversation_id"])["messages"][0]["content"],
                         "    def fn():\n        pass\n")
        f.write_text(json.dumps({**doc, "title": "Renamed"}, ensure_ascii=False), encoding="utf8")
        same = self.st.import_conversation_json(f)
        self.assertFalse(same["created"])
        self.assertEqual(first["conversation_id"], same["conversation_id"])
        self.assertEqual(self.st.stats()["table_counts"]["import_batches"], 1)

    def test_invalid_import_is_all_or_nothing(self):
        f = Path(self.tmp.name) / "invalid.json"
        f.write_text(json.dumps({"messages": [{"role": "user", "content": "hello"},
                                                    {"role": "impossible", "content": "bad"}]}), encoding="utf8")
        with self.assertRaises(InvalidInput):
            self.st.import_conversation_json(f)
        self.assertEqual(self.st.stats()["table_counts"]["messages"], 0)
        f.write_text("{invalid", encoding="utf8")
        with self.assertRaises(InvalidInput):
            self.st.import_conversation_json(f)

    def test_search_trigram_short_chinese_and_literal_metacharacters(self):
        a = self.obj(title="物化视图", body="KV Cache and 100% reusable, a_b")
        b = self.obj(title="Other", body="routine else")
        self.assertEqual([r["id"] for r in self.st.search("物化视图")], [a["id"]])
        self.assertEqual([r["id"] for r in self.st.search("物化")], [a["id"]])
        self.assertEqual([r["id"] for r in self.st.search("100%")], [a["id"]])
        self.assertEqual([r["id"] for r in self.st.search("a_b")], [a["id"]])
        self.assertEqual(self.st.search("' OR 1=1--"), [])
        self.st.update_object(a["id"], title="Revision", body="unrelated", reason="edit")
        self.assertEqual(self.st.search("物化"), [])
        self.st.update_object(b["id"], status="archived", reason="hide")
        self.assertEqual(self.st.search("routine"), [])
        self.assertEqual([r["id"] for r in self.st.search("routine", include_archived=True)], [b["id"]])

    def test_neighborhood_two_hops_and_archive_filter(self):
        a = self.obj(title="a"); b = self.obj(title="b"); c = self.obj(title="c")
        self.st.add_relation(a["id"], b["id"], "supports", "edge A-B")
        self.st.add_relation(b["id"], c["id"], "depends_on", "edge B-C")
        self.assertEqual(len(self.st.neighborhood(a["id"], depth=1)["nodes"]), 2)
        self.assertEqual(len(self.st.neighborhood(a["id"], depth=2)["nodes"]), 3)
        self.st.update_object(b["id"], status="archived", reason="hide archived")
        self.assertEqual(len(self.st.neighborhood(a["id"], depth=2)["nodes"]), 1)
        with self.assertRaises(InvalidInput):
            self.st.neighborhood(a["id"], depth=3)

    def test_frontier_proposal_dedup_and_closed_question(self):
        source = self.obj(title="New fact")
        q = self.obj(title="open direction", kind="question")
        one = self.st.suggest_frontier(source["id"], q["id"], "new_relevance", "may answer q")
        two = self.st.suggest_frontier(source["id"], q["id"], "new_relevance", "same signal with revised wording")
        self.assertEqual(one["id"], two["id"])
        self.st.decide_frontier(one["id"], "accepted", reason="explore later")
        with self.assertRaises(Conflict):
            self.st.decide_frontier(one["id"], "dismissed", reason="already decided")
        self.st.set_question_state(q["id"], "parked", reason="paused")
        with self.assertRaises(InvalidInput):
            self.st.suggest_frontier(source["id"], q["id"], "missing_premise", "not now")

    def test_model_call_logging_and_finish_once(self):
        a = self.obj()
        rec = self.st.log_model_call(purpose="chat", model_id="manual", prompt_version="1.0",
                                     input_fingerprint="a" * 64, selected_objects=[{"id": a["id"], "revision": 1}])
        self.assertEqual(json.loads(rec["selected_objects_json"])[0]["id"], a["id"])
        done = self.st.finish_model_call(rec["id"], success=True, input_tokens=0, output_tokens=100)
        self.assertEqual(done["state"], "completed")
        with self.assertRaises(Conflict):
            self.st.finish_model_call(rec["id"], success=False)
        with self.assertRaises(InvalidInput):
            self.st.finish_model_call(rec["id"], success=False, output_tokens=-5)
        with self.assertRaises(InvalidInput):
            self.st.log_model_call(purpose="chat", model_id="m", prompt_version="v",
                                   input_fingerprint="accidentally a full prompt")
        with self.assertRaises(InvalidInput):
            self.st.log_model_call(purpose="chat", model_id="m", prompt_version="v",
                                   input_fingerprint="b" * 64,
                                   selected_objects=[{"id": "ghost", "revision": 1}])

    def test_backup_restore_and_refuse_existing_file(self):
        a = self.obj(title="important")
        backup = Path(self.tmp.name) / "backup.db"
        self.st.backup(backup)
        with self.assertRaises(Conflict):
            self.st.backup(backup)
        restored = Path(self.tmp.name) / "restored.db"
        report = Storage.restore_backup(backup, restored)
        self.assertTrue(report["doctor"]["ok"])
        with Storage(restored) as another:
            self.assertEqual(another.get_object(a["id"])["title"], "important")
        with self.assertRaises(Conflict):
            Storage.restore_backup(backup, restored)

    def test_export_json_canonical_snapshot_is_not_import_file(self):
        self.obj(title="study")
        f = Path(self.tmp.name) / "snapshot.json"
        self.st.export_json(f)
        data = json.loads(f.read_text(encoding="utf8"))
        self.assertEqual(data["format"], "vkf-readable-snapshot-v1")
        self.assertEqual(len(data["tables"]["cognitive_objects"]), 1)
        with self.assertRaises(Conflict):
            self.st.export_json(f)

    def test_doctor_detects_manual_tampering(self):
        a = self.obj(title="valid")
        self.assertTrue(self.st.doctor()["ok"])
        # Raw SQL is outside the repository's guarded API, but doctor still
        # detects a revision that has not been recorded in version history.
        self.st.db.execute("UPDATE cognitive_objects SET revision=5 WHERE id=?", (a["id"],))
        result = self.st.doctor()
        self.assertFalse(result["ok"])
        self.assertTrue(any("missing current object version" in p for p in result["problems"]))

    def test_multi_connection_append_order(self):
        conv = self.st.create_conversation("interleaved")
        with Storage(self.path) as second:
            self.st.append_message(conv["id"], "user", "first")
            second.append_message(conv["id"], "assistant", "second")
            self.st.append_message(conv["id"], "user", "third")
        seq = [m["turn_index"] for m in self.st.get_conversation(conv["id"])["messages"]]
        self.assertEqual(seq, [0, 1, 2])

    def test_cli_success_json_and_meaningful_failure_code(self):
        def run(*args):
            return subprocess.run([sys.executable, "-m", "vkf_storage", "--db", str(self.path), *args],
                                  cwd=ROOT, capture_output=True, text=True)
        success = run("object", "add", "knowledge", "--title", "CLI", "--body", "Works")
        self.assertEqual(success.returncode, 0, success.stderr)
        rec = json.loads(success.stdout)
        self.assertEqual(rec["revision"], 1)
        self.assertEqual(json.loads(run("object", "show", rec["id"]).stdout)["title"], "CLI")
        failure = run("object", "show", "nonexistent")
        self.assertEqual(failure.returncode, 2)
        # Host interpreter startup hooks may log unrelated warnings to stderr;
        # the CLI's JSON diagnostic remains a standalone line.
        errors = [line for line in failure.stderr.splitlines() if line.startswith('{"error":')]
        self.assertTrue(errors, failure.stderr)
        self.assertIn("not found", json.loads(errors[-1])["message"])
        self.assertEqual(run("doctor").returncode, 0)


    def test_upgrade_generates_private_backup_only_for_existing_v1(self):
        script = (ROOT / "vkf_storage" / "migrations" / "001_initial.sql").read_text(encoding="utf8")
        legacy = Path(self.tmp.name) / "legacy.db"
        with closing(sqlite3.connect(legacy)) as db, db:
            db.executescript(script)
            db.execute("INSERT INTO conversations(id,source,title) VALUES('prior','other','old')")
        result = Storage.initialize(legacy)
        self.assertIsNotNone(result["pre_migration_backup"])
        with closing(sqlite3.connect(result["pre_migration_backup"])) as old:
            self.assertEqual(old.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(old.execute("SELECT title FROM conversations WHERE id='prior'").fetchone()[0], "old")
        fresh_path = Path(self.tmp.name) / "fresh.db"
        result2 = Storage.initialize(fresh_path)
        self.assertIsNone(result2["pre_migration_backup"])

    def test_concurrent_writers_have_unique_turn_indexes(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        conv = self.st.create_conversation("threaded")
        barrier = Barrier(2)
        def write(tag):
            with Storage(self.path) as db:
                barrier.wait(timeout=5)
                return [db.append_message(conv["id"], "user", f"{tag}-{i}") for i in range(10)]
        with ThreadPoolExecutor(max_workers=2) as ex:
            a = ex.submit(write, "a")
            b = ex.submit(write, "b")
            first, second = a.result(timeout=10), b.result(timeout=10)
        self.assertEqual(len(first + second), 20)
        self.assertEqual([m["turn_index"] for m in self.st.get_conversation(conv["id"])["messages"]], list(range(20)))
        self.assertTrue(self.st.doctor()["ok"])

    def test_doctor_detects_fts_index_out_of_sync(self):
        a = self.obj(title="search content")
        row_id = self.st.get_object(a["id"])["row_id"]
        self.st.db.execute("DELETE FROM object_fts WHERE rowid=?", (row_id,))
        report = self.st.doctor()
        self.assertFalse(report["ok"])
        self.assertTrue(any("FTS index" in x for x in report["problems"]))

    def test_demo_script_and_clean_second_run_rejected(self):
        demo = Path(self.tmp.name) / "sample-demo.db"
        args = [sys.executable, str(ROOT / "examples" / "demo_session.py"), "--db", str(demo)]
        run1 = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(run1.returncode, 0, run1.stderr)
        summary = json.loads(run1.stdout)
        self.assertTrue(summary["doctor"]["ok"])
        with Storage(demo) as db:
            self.assertEqual(db.stats()["table_counts"]["cognitive_objects"], 4)
            self.assertEqual(db.stats()["table_counts"]["candidates"], 1)
        run2 = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(run2.returncode, 2)


    def test_object_state_transition_matrix_exhaustive(self):
        states = {"active", "challenged", "archived"}
        valid = {
            "active": {"challenged", "archived"},
            "challenged": {"active", "archived"},
            "archived": {"active"},
        }
        examined = []
        for current in sorted(states):
            for target in sorted(states):
                obj = self.obj(title=f"{current}-{target}")
                if current != "active":
                    self.st.update_object(obj["id"], status=current, reason="test setup")
                before = self.st.get_object(obj["id"])["revision"]
                if target in valid[current]:
                    out = self.st.update_object(obj["id"], status=target, reason="transition matrix")
                    self.assertEqual(out["revision"], before + 1)
                else:
                    with self.assertRaises(InvalidInput):
                        self.st.update_object(obj["id"], status=target, reason="should reject")
                    self.assertEqual(self.st.get_object(obj["id"])["revision"], before)
                examined.append((current, target))
        self.assertEqual(len(examined), 9)
        self.assertTrue(self.st.doctor()["ok"])

    def test_question_state_transition_matrix_exhaustive(self):
        states = {"open", "exploring", "answered", "parked"}
        valid = {
            "open": {"exploring", "answered", "parked"},
            "exploring": {"open", "answered", "parked"},
            "answered": {"open"},
            "parked": {"open"},
        }
        examined = []
        for current in sorted(states):
            for target in sorted(states):
                q = self.obj(title=f"question: {current}-{target}", kind="question")
                if current != "open":
                    self.st.set_question_state(q["id"], current, reason="test setup",
                                               resolution_note="Manual initial conclusion" if current == "answered" else "")
                before = self.st.get_object(q["id"])["question_state"]["state"]
                if target in valid[current]:
                    after = self.st.set_question_state(q["id"], target, reason="transition matrix",
                                                       resolution_note="Answer rationale" if target == "answered" else "")
                    self.assertEqual(after["state"], target)
                else:
                    with self.assertRaises((InvalidInput, sqlite3.IntegrityError)):
                        self.st.set_question_state(q["id"], target, reason="should reject",
                                                   resolution_note="Answer rationale" if target == "answered" else "")
                    self.assertEqual(self.st.get_object(q["id"])["question_state"]["state"], before)
                examined.append((current, target))
        self.assertEqual(len(examined), 16)
        self.assertTrue(self.st.doctor()["ok"])

    def test_open_rejects_incomplete_version2(self):
        broken = Path(self.tmp.name) / "incomplete.db"
        with closing(sqlite3.connect(broken)) as db, db:
            db.execute("PRAGMA user_version=2")
            db.execute("CREATE TABLE cognitive_objects(x INTEGER)")
        with self.assertRaises(UnsupportedSchema):
            Storage(broken)


if __name__ == "__main__":
    unittest.main(verbosity=2)

# Additional tests are collected through the StorageTests class above.
