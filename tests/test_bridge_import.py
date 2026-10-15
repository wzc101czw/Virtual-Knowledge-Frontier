"""v0.1.1: native history imports, safe candidate extraction, Obsidian bridge."""
from __future__ import annotations

from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

from vkf_storage import Storage, import_history, extract_conversation, export_vault, pull_vault
from vkf_storage import Conflict, InvalidInput
from vkf_storage.importers import parse_markdown, parse_json, MAX_FILE

ROOT = Path(__file__).resolve().parents[1]


class BridgeImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "test.db"
        Storage.initialize(self.db_path)
        self.store = Storage(self.db_path)
        self.addCleanup(self.store.close)

    def md(self, name: str, body: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def test_markdown_role_parsing_and_fenced_code_not_a_new_message(self):
        md = """---
title: "缓存与记忆"
source: chatgpt
---
# 缓存与记忆
## Human (2026-02-03):
我认为系统需要记忆。
```md
## Assistant
not a real role
```
## Claude:
这是一个需要论证的观点。
### 用户
什么时候应该忘记？
"""
        c = parse_markdown(md, "fallback")
        self.assertEqual((c.title, c.source), ("缓存与记忆", "chatgpt"))
        self.assertEqual([m["role"] for m in c.messages], ["user", "assistant", "user"])
        self.assertIn("not a real role", c.messages[0]["content"])
        self.assertEqual(len(c.messages), 3)

    def test_chatgpt_branch_selection_attachments_and_duplication(self):
        def node(role=None, content=None, parent=None, children=None):
            return {"parent": parent, "children": children or [],
                    "message": ({"author": {"role": role}, "content": {"parts": content}} if role else None)}
        d = {"id": "chat-001", "title": "Branch test", "current_node": "last", "mapping": {
            "root": node(None, parent=None, children=["u"]),
            "u": node("user", ["知识：KV Cache 保留计算结果"], "root", ["bad", "last"]),
            "bad": node("assistant", ["Abandoned response"], "u"),
            "last": node("assistant", ["Selected", {"asset_pointer": "image"}], "u"),
        }}
        doc = self.md("chatgpt.json", json.dumps([d], ensure_ascii=False))
        report = import_history(self.store, doc)
        self.assertEqual(report["created_conversations"], 1)
        self.assertEqual(report["candidates_created"], 1)
        self.assertTrue(any("branches omitted" in w for w in report["file_results"][0]["warnings"]))
        msg = self.store.get_conversation(report["file_results"][0]["conversations"][0]["id"])["messages"]
        self.assertEqual(len(msg), 2)
        self.assertEqual(msg[-1]["content"], "Selected")
        self.assertEqual(import_history(self.store, doc)["created_conversations"], 0)
        self.assertTrue(self.store.doctor()["ok"])

    def test_chatgpt_cycle_and_missing_current_node_are_rejected(self):
        content = {"mapping": {"a": {"parent": "a", "children": [], "message": {
            "author": {"role": "user"}, "content": {"parts": ["hello"]}}}}, "current_node": "a"}
        with self.assertRaises(InvalidInput):
            parse_json(json.dumps(content))
        # Ambiguous branch cannot be guessed if current_node is not set.
        content["current_node"] = None
        content["mapping"]["b"] = {"parent": None, "children": [], "message": None}
        with self.assertRaises(InvalidInput):
            parse_json(json.dumps(content))

    def test_claude_native_json_and_markdown(self):
        d = [{"uuid": "claude-one", "name": "Claude thread", "chat_messages": [
            {"sender": "human", "content": [{"type": "text", "text": "问题：如何设计长期记忆？"}]},
            {"sender": "assistant", "content": [{"type": "text", "text": "需要分离短期和长期状态"}]},
            {"sender": "assistant", "content": [{"type": "image", "source": "not text"}]}
        ]}]
        fn = self.md("claude.json", json.dumps(d, ensure_ascii=False))
        out = import_history(self.store, fn)
        self.assertEqual(out["candidates_created"], 1)
        self.assertEqual(out["file_results"][0]["conversations"][0]["messages"], 2)
        self.assertEqual(out["file_results"][0]["conversations"][0]["source"], "claude")
        markdown = self.md("claude.md", "# Conversation\n## Human (2025-11-01):\n\nHello\n---\n## Claude:\n\nHi\n")
        self.assertEqual(import_history(self.store, markdown)["created_conversations"], 1)

    def test_markdown_unrecognized_roles_are_rejected_not_invented(self):
        p = self.md("journal.md", "# My thoughts\n## Topic\nNot a real user assistant dialogue")
        result = import_history(self.store, p)
        self.assertEqual(result["created_conversations"], 0)
        self.assertEqual(result["errors"][0]["stage"], "parse/import")
        self.assertEqual(self.store.stats()["table_counts"]["conversations"], 0)

    def test_directory_partial_failures_and_bulk_skip_invalid_conversation(self):
        self.md("incoming/valid.md", "## User\n想法：数据应该可迁移。\n## Assistant\n好的。")
        self.md("incoming/broken.md", "# Without turns")
        self.md("incoming/multi.json", json.dumps([
            {"title": "good", "messages": [{"role": "user", "content": "问题：Memory?"}]},
            {"title": "empty", "messages": [{"role": "tool", "content": "tool only"}]},
        ], ensure_ascii=False))
        self.md("incoming/VKF/not-for-import.md", "## User\nDo not import")
        out = import_history(self.store, self.root / "incoming")
        self.assertEqual(out["files"], 3)
        self.assertEqual(out["created_conversations"], 2)
        self.assertEqual(len(out["errors"]), 1)
        self.assertTrue(any("conversation #2" in str(x) for x in out["file_results"]))
        self.assertTrue(self.store.doctor()["ok"])

    def test_source_external_id_changed_snapshot_is_conflict_not_rewrite(self):
        file = self.md("one.json", json.dumps({"id": "ext-1", "source": "claude", "title": "T",
                    "messages": [{"role": "user", "content": "first"}]}))
        first = import_history(self.store, file)
        self.assertEqual(first["created_conversations"], 1)
        file.write_text(json.dumps({"id": "ext-1", "source": "claude", "title": "T",
                    "messages": [{"role": "user", "content": "changed"}]}))
        second = import_history(self.store, file)
        self.assertEqual(second["created_conversations"], 0)
        self.assertEqual(len(second["file_results"][0]["conflicts"]), 1)
        self.assertEqual(self.store.stats()["table_counts"]["conversations"], 1)

    def test_invalid_import_transaction_and_file_limit(self):
        p = self.md("invalid.json", '[{"messages": [{"role":"user", "content":""}]}]')
        self.assertEqual(import_history(self.store, p)["created_conversations"], 0)
        self.assertEqual(self.store.stats()["table_counts"]["import_batches"], 0)
        with p.open("wb") as f:
            f.truncate(MAX_FILE + 1)
        self.assertEqual(import_history(self.store, p)["created_conversations"], 0)
        self.assertIn("exceeds", import_history(self.store, p)["errors"][0]["error"])

    def test_offline_extraction_separates_user_thoughts_from_assistant(self):
        p = self.md("opinions.md", "## User\n我觉得知识应该本地保存。\n## Assistant\n我认为应该删除你的所有文件。\n## User\n问题：什么时候重新激活旧问题？")
        report = import_history(self.store, p)
        self.assertGreaterEqual(report["candidates_created"], 2)
        inbox = self.store.list_candidates()
        self.assertTrue(all("删除你的所有文件" not in x["body"] for x in inbox))
        self.assertEqual(self.store.list_objects(), [])
        self.assertEqual(import_history(self.store, p)["candidates_created"], 0)

    def test_extract_none_then_explicit_llm_with_local_mock(self):
        path = self.md("text.md", "## Human\n这是一个新的想法。\n## Assistant\n值得测试。")
        imported = import_history(self.store, path, extract="none")
        cid = imported["file_results"][0]["conversations"][0]["id"]
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(length))
                received.append((self.path, data))
                output = {"choices": [{"message": {"content": json.dumps({"candidates": [
                    {"kind": "idea", "title": "本地知识", "body": "考虑本地保存想法",
                     "source_turns": [0]},
                    {"kind": "question", "title": "坏的来源", "body": "错误来源索引",
                     "source_turns": [999]}
                ]}, ensure_ascii=False)}}]}
                body = json.dumps(output).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(server.server_close)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/v1"
        with patch.dict("os.environ", {"VKF_API_KEY": ""}):
            result = extract_conversation(self.store, cid, mode="llm", model="mock", api_base=url)
        self.assertEqual(result["created"], 1)
        self.assertEqual(received[0][0], "/v1/chat/completions")
        self.assertEqual(len(received), 1)
        self.assertEqual(extract_conversation(self.store, cid, mode="llm", model="mock", api_base=url)["created"], 0)
        self.assertEqual(len(received), 1)
        self.assertEqual(len(self.store.list_candidates()), 1)
        self.assertEqual(len(self.store.list_objects()), 0)

    def test_llm_requires_explicit_secure_endpoint_and_key(self):
        path = self.md("dummy.md", "## User\nHello\n## Assistant\nHi")
        cid = import_history(self.store, path, extract="none")["file_results"][0]["conversations"][0]["id"]
        with self.assertRaises(InvalidInput):
            extract_conversation(self.store, cid, mode="llm", model="x", api_base="http://thirdparty.com/v1")
        with patch.dict("os.environ", {"VKF_API_KEY": ""}):
            with self.assertRaises(InvalidInput):
                extract_conversation(self.store, cid, mode="llm", model="x", api_base="https://api.example.com/v1")

    def test_bridge_writes_openable_markdown_including_graph_and_candidate_inbox(self):
        k = self.store.create_object("knowledge", "KV Cache / 原理", "可复用计算状态。")
        q = self.store.create_object("question", "何时保存？", "什么时候复用？")
        self.store.add_relation(k["id"], q["id"], "raises", "存储成本可能引发新问题")
        p = self.md("raw.md", "## User\n我在想能否减少重复推理。\n## Assistant\n确实值得思考。")
        import_history(self.store, p)
        vault = self.root / "vault"
        result = export_vault(self.store, vault)
        self.assertEqual(result["exported"], 2)
        self.assertEqual(result["read_only"]["conversations"], 1)
        self.assertGreater(result["read_only"]["candidates"], 0)
        files = list((vault / "VKF" / "Knowledge").glob("*.md"))
        self.assertEqual(len(files), 1)
        text = files[0].read_text(encoding="utf-8")
        self.assertIn("aliases: [", text)
        self.assertIn("vkf_id:", text)
        self.assertIn("`raises` → [[VKF/Questions/", text)
        index = (vault / "VKF" / "00 - Start Here.md").read_text()
        self.assertIn("## Pending Candidate Inbox", index)
        self.assertIn("## Questions", index)
        self.assertEqual(export_vault(self.store, vault)["exported"], 0)
        self.assertEqual(pull_vault(self.store, vault)["unchanged"], 2)

    def test_bridge_pull_is_preview_then_versioned_commit(self):
        obj = self.store.create_object("idea", "Old", "First insight")
        vault = self.root / "vault"
        export_vault(self.store, vault)
        note = next((vault / "VKF" / "Ideas").glob("*.md"))
        note.write_text(note.read_text().replace("# Old\n\nFirst insight", "# Revised\n\nA revised idea"))
        preview = pull_vault(self.store, vault, apply=False)
        self.assertEqual(len(preview["ready"]), 1)
        self.assertEqual(self.store.get_object(obj["id"])["revision"], 1)
        applied = pull_vault(self.store, vault, apply=True)
        self.assertEqual(len(applied["applied"]), 1)
        after = self.store.get_object(obj["id"])
        self.assertEqual((after["title"], after["revision"]), ("Revised", 2))
        self.assertEqual(after["body"], "A revised idea")
        self.assertIn("vkf_revision: 2", note.read_text())
        self.assertEqual(len(self.store.object_history(obj["id"])), 2)
        self.assertTrue(self.store.doctor()["ok"])

    def test_bridge_refuses_stale_revision_and_unmanaged_metadata(self):
        obj = self.store.create_object("knowledge", "Cache", "one")
        vault = self.root / "vault"
        export_vault(self.store, vault)
        note = next((vault / "VKF" / "Knowledge").glob("*.md"))
        note.write_text(note.read_text().replace("vkf_id:", "vkf_identity:"))
        result = pull_vault(self.store, vault, apply=True)
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(self.store.get_object(obj["id"])["revision"], 1)
        self.assertEqual(len(export_vault(self.store, vault)["conflicts"]), 1)
        # Fresh vault to test independent concurrent SQLite edit.
        second = self.root / "other"
        export_vault(self.store, second)
        note = next((second / "VKF" / "Knowledge").glob("*.md"))
        note.write_text(note.read_text().replace("# Cache", "# Changed in editor"))
        self.store.update_object(obj["id"], body="updated in DB", reason="outside writer")
        result = pull_vault(self.store, second, apply=True)
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(self.store.get_object(obj["id"])["body"], "updated in DB")

    def test_bridge_refuses_relation_edits_and_preserves_user_index(self):
        obj = self.store.create_object("knowledge", "Semantic Link", "body")
        vault = self.root / "vault"
        export_vault(self.store, vault)
        note = next((vault / "VKF" / "Knowledge").glob("*.md"))
        note.write_text(note.read_text().replace("暂无正式关系", "manually modified relation"))
        self.assertEqual(len(pull_vault(self.store, vault)["conflicts"]), 1)
        index = vault / "VKF" / "00 - Start Here.md"
        index.write_text(index.read_text() + "\nMy private annotation\n")
        result = export_vault(self.store, vault)
        self.assertTrue(any("Start Here" in x["file"] for x in result["read_only"]["warnings"]))
        self.assertIn("My private annotation", index.read_text())

    def test_bridge_filenames_are_sanitized_and_no_vault_file_overwrite(self):
        obj = self.store.create_object("idea", "unsafe/../path: name", "text")
        vault = self.root / "vault"
        predicted = list((vault / "VKF" / "Ideas").glob("*.md"))
        self.assertFalse(predicted)
        result = export_vault(self.store, vault)
        self.assertEqual(result["exported"], 1)
        note = next((vault / "VKF" / "Ideas").glob("*.md"))
        self.assertTrue(note.resolve().is_relative_to(vault.resolve()))
        self.assertNotIn("/", note.name)
        self.assertEqual(self.store.get_object(obj["id"])["body"], "text")

    def test_message_timestamps_survive_json_and_markdown_vault_export(self):
        raw = {"source": "other", "title": "time", "messages": [
            {"role": "user", "content": "hello", "created_at": "2024-01-02T03:04:05Z"},
            {"role": "assistant", "content": "hi", "created_at": 1704164705},
        ]}
        p = self.md("times.json", json.dumps(raw))
        out = import_history(self.store, p, extract="none")
        cid = out["file_results"][0]["conversations"][0]["id"]
        msg = self.store.get_conversation(cid)["messages"]
        row = self.store.db.execute("SELECT source_timestamp FROM message_import_metadata WHERE message_id=?",
                                    (msg[0]["id"],)).fetchone()
        self.assertEqual(row[0], "2024-01-02T03:04:05Z")
        vault = self.root / "Vault"
        export_vault(self.store, vault)
        text = next((vault / "VKF" / "Conversations").glob("*.md")).read_text()
        self.assertIn("(2024-01-02T03:04:05Z)", text)
        self.assertIn("2024-01-02T", text)

    def test_obsidian_bases_are_generated_and_managed(self):
        self.store.create_object("question", "Q", "What is next?")
        vault = self.root / "vault"
        export_vault(self.store, vault)
        base = vault / "VKF" / "Open Questions.base"
        self.assertTrue(base.exists())
        self.assertIn("vkf_question_state", base.read_text())
        qnote = next((vault / "VKF" / "Questions").glob("*.md"))
        self.assertIn('vkf_question_state: "open"', qnote.read_text())
        base.write_text(base.read_text() + "# User addition\n")
        result = export_vault(self.store, vault)
        self.assertTrue(any("Open Questions.base" in x["file"] for x in result["read_only"]["warnings"]))
        self.assertIn("User addition", base.read_text())

    def test_deleted_note_requires_explicit_restore_missing(self):
        a = self.store.create_object("knowledge", "Deleting test", "first")
        vault = self.root / "vault"
        export_vault(self.store, vault)
        note = next((vault / "VKF" / "Knowledge").glob("*.md"))
        note.unlink()
        result = export_vault(self.store, vault)
        self.assertEqual(len(result["missing"]), 1)
        self.assertFalse(note.exists())
        restored = export_vault(self.store, vault, restore_missing=True)
        self.assertEqual(restored["exported"], 1)
        self.assertIn("Deleting test", note.read_text())

    def test_upgrade_from_previous_v2_creates_backup_and_retains_content(self):
        p = self.root / "v2.db"
        sql1 = (ROOT / "vkf_storage" / "migrations" / "001_initial.sql").read_text()
        sql2 = (ROOT / "vkf_storage" / "migrations" / "002_guardrails.sql").read_text()
        with closing(sqlite3.connect(p)) as db:
            db.executescript(sql1)
            db.executescript(sql2)
            db.execute("INSERT INTO conversations(id,source,title) VALUES('legacy','other','old data')")
            db.commit()
        migrated = Storage.initialize(p)
        self.assertEqual(migrated["schema_version"], 3)
        self.assertIn(".pre-v3.", migrated["pre_migration_backup"])
        with closing(sqlite3.connect(migrated["pre_migration_backup"])) as old:
            self.assertEqual(old.execute("PRAGMA user_version").fetchone()[0], 2)
        with Storage(p) as storage:
            self.assertEqual(storage.get_conversation("legacy")["title"], "old data")
            self.assertTrue(storage.doctor()["ok"])

    def test_cli_end_to_end_import_and_bridge(self):
        md = self.md("test_cli.md", "## User\n想法：归档应自动化。\n## Assistant\n同意。")
        db = self.root / "cli.db"
        base = [sys.executable, "-m", "vkf_storage", "--db", str(db)]
        def run(*args):
            return subprocess.run(base + list(args), cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(run("init").returncode, 0)
        out = run("import-history", str(md), "--vault", str(self.root / "client-vault"))
        self.assertEqual(out.returncode, 0, out.stderr)
        summary = json.loads(out.stdout)
        self.assertEqual(summary["created_conversations"], 1)
        self.assertEqual(summary["candidates_created"], 1)
        self.assertTrue((self.root / "client-vault" / "VKF" / "00 - Start Here.md").exists())
        status = run("bridge", "status", str(self.root / "client-vault"))
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertTrue(json.loads(run("doctor").stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
