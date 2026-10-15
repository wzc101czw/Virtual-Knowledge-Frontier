"""Regression tests for UTF-8 Markdown handling on Windows GBK locales."""
from __future__ import annotations

import ast
from pathlib import Path
import tempfile
import unittest

from vkf_storage import Storage, export_vault, pull_vault

ROOT = Path(__file__).resolve().parents[1]


class EncodingPortabilityTests(unittest.TestCase):
    def test_chinese_emoji_markdown_roundtrip(self):
        # A text sample that fails when incorrectly decoded as GBK.
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            database = folder / "vkf.db"
            vault = folder / "Vault"
            Storage.initialize(database)
            with Storage(database) as storage:
                item = storage.create_object(
                    "idea", "UTF8 Test", "理解缓存策略：🌟、Ω 和长期记忆。"
                )
                report = export_vault(storage, vault)
                self.assertEqual(report["exported"], 1)
                note = next((vault / "VKF" / "Ideas").glob("*.md"))
                text = note.read_text(encoding="utf-8")
                self.assertIn("缓存策略：🌟、Ω", text)
                self.assertIn("缓存策略：🌟、Ω".encode("utf-8"), note.read_bytes())
                revised = text.replace("长期记忆", "长期理解")
                self.assertNotEqual(revised, text)
                note.write_text(revised, encoding="utf-8")
                result = pull_vault(storage, vault, apply=True)
                self.assertEqual(len(result["applied"]), 1)
                self.assertEqual(storage.get_object(item["id"])["body"],
                                 "理解缓存策略：🌟、Ω 和长期理解。")
                self.assertEqual(storage.get_object(item["id"])["revision"], 2)
                self.assertTrue(storage.doctor()["ok"])

    def test_explicit_encoding_for_path_text_calls(self):
        # Prevent another Windows GBK regression in source or test code.
        missing = []
        for file in sorted(ROOT.rglob("*.py")):
            if "__pycache__" in file.parts:
                continue
            contents = file.read_text(encoding="utf-8")
            parsed = ast.parse(contents, filename=str(file))
            for node in ast.walk(parsed):
                if not (isinstance(node, ast.Call) and
                        isinstance(node.func, ast.Attribute) and
                        node.func.attr in ("read_text", "write_text")):
                    continue
                required_positional = 1 if node.func.attr == "read_text" else 2
                if (not any(k.arg == "encoding" for k in node.keywords)
                        and len(node.args) < required_positional):
                    missing.append(f"{file.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(missing, [], f"Text IO must use an explicit encoding: {missing}")


if __name__ == "__main__":
    unittest.main()
