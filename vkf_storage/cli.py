"""Human and script-friendly command-line interface for VKF Storage Core."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from .core import Storage, VKFError, InvalidInput


def _body_group(parser: argparse.ArgumentParser, *, prefix: str = "body", required: bool = True) -> None:
    group = parser.add_mutually_exclusive_group(required=required)
    group.add_argument(f"--{prefix}")
    group.add_argument(f"--{prefix}-file", type=Path)


def _read_body(args: argparse.Namespace, prefix: str = "body") -> str | None:
    raw = getattr(args, prefix, None)
    filename = getattr(args, f"{prefix}_file", None)
    if filename:
        try:
            return filename.read_text(encoding="utf-8")
        except OSError as exc:
            raise InvalidInput(f"cannot read {filename}: {exc}") from exc
    return raw


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vkf", description="Offline VKF Cognitive Storage Core")
    p.add_argument("--db", default="./vkf.db", help="local SQLite file, default ./vkf.db")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create or upgrade the database, without deleting data")
    sub.add_parser("doctor", help="check SQLite and VKF logical integrity")
    sub.add_parser("stats", help="count stored records")
    s = sub.add_parser("search", help="literal title/body substring search")
    s.add_argument("query"); s.add_argument("--limit", type=int, default=20)
    s.add_argument("--archived", action="store_true")
    s = sub.add_parser("graph", help="one/two-hop local graph")
    s.add_argument("object_id"); s.add_argument("--depth", type=int, default=1)
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--archived", action="store_true")

    ob = sub.add_parser("object", help="manage formal cognitive objects").add_subparsers(dest="action", required=True)
    s = ob.add_parser("add")
    s.add_argument("kind", choices=["knowledge", "idea", "understanding", "question", "cross_insight"])
    s.add_argument("--title", required=True)
    _body_group(s)
    s.add_argument("--epistemic", choices=["asserted", "tentative", "disputed"])
    s.add_argument("--understanding", choices=["provisional", "articulated"])
    s.add_argument("--uncertainty", default="")
    s.add_argument("--source-id", action="append", default=[], help="required twice for cross_insight")
    s.add_argument("--synthesis-rationale")
    s = ob.add_parser("list")
    s.add_argument("--kind", choices=["knowledge", "idea", "understanding", "question", "cross_insight"])
    s.add_argument("--status", choices=["active", "challenged", "archived"])
    s.add_argument("--limit", type=int, default=100)
    s = ob.add_parser("show"); s.add_argument("id")
    s = ob.add_parser("edit"); s.add_argument("id")
    s.add_argument("--title"); _body_group(s, required=False)
    s.add_argument("--epistemic", choices=["asserted", "tentative", "disputed"])
    s.add_argument("--understanding", choices=["provisional", "articulated"])
    s.add_argument("--uncertainty")
    s.add_argument("--reason", required=True); s.add_argument("--expected-revision", type=int)
    s = ob.add_parser("status"); s.add_argument("id")
    s.add_argument("state", choices=["active", "challenged", "archived"])
    s.add_argument("--reason", required=True); s.add_argument("--expected-revision", type=int)
    s = ob.add_parser("history"); s.add_argument("id")
    s = ob.add_parser("restore"); s.add_argument("id"); s.add_argument("revision", type=int)
    s.add_argument("--reason", required=True); s.add_argument("--expected-revision", type=int)

    q = sub.add_parser("question").add_subparsers(dest="action", required=True)
    s = q.add_parser("list"); s.add_argument("--state", choices=["open", "exploring", "answered", "parked"])
    s.add_argument("--limit", type=int, default=100)
    s = q.add_parser("set"); s.add_argument("id")
    s.add_argument("state", choices=["open", "exploring", "answered", "parked"])
    s.add_argument("--reason", required=True); s.add_argument("--resolution-note", default="")

    rel = sub.add_parser("relation").add_subparsers(dest="action", required=True)
    s = rel.add_parser("add")
    s.add_argument("from_id"); s.add_argument("to_id")
    s.add_argument("kind", choices=["depends_on", "supports", "contradicts", "analogous_to",
                                    "synthesizes", "raises", "answers"])
    s.add_argument("--reason", required=True)
    s = rel.add_parser("list"); s.add_argument("--object-id")
    s.add_argument("--status", choices=["active", "challenged", "archived"])
    s.add_argument("--limit", type=int, default=100)
    s = rel.add_parser("status"); s.add_argument("id")
    s.add_argument("state", choices=["active", "challenged", "archived"])
    s.add_argument("--reason", required=True)

    conv = sub.add_parser("conversation").add_subparsers(dest="action", required=True)
    s = conv.add_parser("add"); s.add_argument("--title", default="")
    s.add_argument("--source", default="live", choices=["live", "chatgpt", "claude", "other"])
    s = conv.add_parser("message"); s.add_argument("id"); s.add_argument("role", choices=["system", "user", "assistant", "tool"])
    _body_group(s)
    s = conv.add_parser("show"); s.add_argument("id")
    s = conv.add_parser("list"); s.add_argument("--limit", type=int, default=100)
    s = conv.add_parser("import-json"); s.add_argument("file", type=Path)

    ca = sub.add_parser("candidate").add_subparsers(dest="action", required=True)
    s = ca.add_parser("propose", help="simulate extraction from a source message, no LLM call")
    s.add_argument("conversation_id"); s.add_argument("message_id")
    s.add_argument("kind", choices=["knowledge", "idea", "understanding", "question", "cross_insight"])
    s.add_argument("--title", required=True); _body_group(s)
    s = ca.add_parser("list"); s.add_argument("--state", default="pending",
                                                choices=["pending", "approved", "merged", "rejected", "all"])
    s.add_argument("--limit", type=int, default=100)
    s = ca.add_parser("show"); s.add_argument("id")
    s = ca.add_parser("approve"); s.add_argument("id")
    s.add_argument("--source-id", action="append", default=[])
    s.add_argument("--synthesis-rationale")
    s = ca.add_parser("merge"); s.add_argument("id"); s.add_argument("target_id")
    s.add_argument("--reason", required=True); _body_group(s, prefix="new_body", required=False)
    s.add_argument("--expected-revision", type=int)
    s = ca.add_parser("reject"); s.add_argument("id"); s.add_argument("--reason", required=True)

    fr = sub.add_parser("frontier").add_subparsers(dest="action", required=True)
    s = fr.add_parser("suggest"); s.add_argument("source_id"); s.add_argument("question_id")
    s.add_argument("signal", choices=["new_relevance", "contradiction", "cross_domain", "missing_premise"])
    s.add_argument("--reason", required=True)
    s = fr.add_parser("list"); s.add_argument("--state", default="pending",
                                                choices=["pending", "accepted", "dismissed", "snoozed", "all"])
    s.add_argument("--limit", type=int, default=100)
    s = fr.add_parser("decide"); s.add_argument("id")
    s.add_argument("state", choices=["accepted", "dismissed", "snoozed"])
    s.add_argument("--reason", required=True)

    imp = sub.add_parser("import-history", help="import native ChatGPT/Claude JSON or role-labelled Markdown")
    imp.add_argument("path", type=Path, help=".json/.md file or directory")
    imp.add_argument("--source", choices=["live", "chatgpt", "claude", "other"],
                     help="override source identification for all imported conversations")
    imp.add_argument("--extract", default="heuristic", choices=["none", "heuristic", "llm"],
                     help="default offline literal candidates; model requests are explicit only")
    imp.add_argument("--model", help="required if --extract llm")
    imp.add_argument("--api-base", default="https://api.openai.com/v1")
    imp.add_argument("--timeout", type=int, default=60)
    imp.add_argument("--vault", type=Path, help="export imported archive & candidate inbox into Obsidian vault")

    ext = sub.add_parser("extract", help="generate candidate inbox entries from an already imported chat")
    ext.add_argument("conversation_id")
    ext.add_argument("--mode", default="heuristic", choices=["heuristic", "llm"])
    ext.add_argument("--model")
    ext.add_argument("--api-base", default="https://api.openai.com/v1")
    ext.add_argument("--timeout", type=int, default=60)

    bridge = sub.add_parser("bridge", help="Obsidian Markdown projection + reviewed edits")
    bridges = bridge.add_subparsers(dest="action", required=True)
    s = bridges.add_parser("export", help="write a managed VKF/ folder in an Obsidian vault")
    s.add_argument("vault", type=Path)
    s.add_argument("--restore-missing", action="store_true", help="recreate explicitly deleted managed notes")
    s.add_argument("--no-conversations", action="store_true")
    s.add_argument("--no-candidates", action="store_true")
    s = bridges.add_parser("status", help="review pending Obsidian edits without modifying SQLite")
    s.add_argument("vault", type=Path)
    s = bridges.add_parser("pull", help="preview Obsidian edits, optionally apply them")
    s.add_argument("vault", type=Path)
    s.add_argument("--apply", action="store_true", help="commit safe edits as new SQLite object revisions")

    s = sub.add_parser("backup"); s.add_argument("file", type=Path)
    s = sub.add_parser("restore-db", help="restore a backup to a NEW database path supplied by --db")
    s.add_argument("file", type=Path)
    s = sub.add_parser("export-json"); s.add_argument("file", type=Path)
    return p


def execute(args: argparse.Namespace):
    if args.command == "init":
        return Storage.initialize(args.db)
    if args.command == "restore-db":
        return Storage.restore_backup(args.file, args.db)
    with Storage(args.db) as st:
        cmd = args.command
        if cmd == "import-history":
            from .importers import import_history
            from .obsidian import export_vault
            result = import_history(st, args.path, source=args.source, extract=args.extract,
                                    model=args.model, api_base=args.api_base, timeout=args.timeout)
            if args.vault is not None:
                result["obsidian"] = export_vault(st, args.vault)
            return result
        if cmd == "extract":
            from .importers import extract_conversation
            return extract_conversation(st, args.conversation_id, mode=args.mode,
                                        model=args.model, api_base=args.api_base, timeout=args.timeout)
        if cmd == "bridge":
            from .obsidian import export_vault, pull_vault, bridge_status
            if args.action == "export":
                return export_vault(st, args.vault, include_conversations=not args.no_conversations,
                                    include_candidates=not args.no_candidates,
                                    restore_missing=args.restore_missing)
            if args.action == "pull":
                return pull_vault(st, args.vault, apply=args.apply)
            if args.action == "status":
                return bridge_status(st, args.vault)
        if cmd == "doctor": return st.doctor()
        if cmd == "stats": return st.stats()
        if cmd == "search": return st.search(args.query, limit=args.limit, include_archived=args.archived)
        if cmd == "graph": return st.neighborhood(args.object_id, depth=args.depth,
                                                   limit=args.limit, include_archived=args.archived)
        if cmd == "backup": return st.backup(args.file)
        if cmd == "export-json": return st.export_json(args.file)
        a = args.action
        if cmd == "object":
            if a == "add":
                return st.create_object(args.kind, args.title, _read_body(args),
                                        epistemic_status=args.epistemic, understanding_level=args.understanding,
                                        uncertainty_note=args.uncertainty, synthesized_from=args.source_id,
                                        synthesis_rationale=args.synthesis_rationale)
            if a == "list": return st.list_objects(kind=args.kind, status=args.status, limit=args.limit)
            if a == "show": return st.get_object(args.id)
            if a == "history": return st.object_history(args.id)
            if a == "restore": return st.restore_object_revision(args.id, args.revision, reason=args.reason,
                                                                  expected_revision=args.expected_revision)
            if a == "status": return st.update_object(args.id, status=args.state, reason=args.reason,
                                                       expected_revision=args.expected_revision)
            if a == "edit":
                fields = {"title": args.title, "body": _read_body(args), "epistemic_status": args.epistemic,
                          "understanding_level": args.understanding, "uncertainty_note": args.uncertainty}
                return st.update_object(args.id, reason=args.reason, expected_revision=args.expected_revision,
                                        **{k: v for k, v in fields.items() if v is not None})
        if cmd == "question":
            if a == "list": return st.list_questions(state=args.state, limit=args.limit)
            if a == "set": return st.set_question_state(args.id, args.state, reason=args.reason,
                                                        resolution_note=args.resolution_note)
        if cmd == "relation":
            if a == "add": return st.add_relation(args.from_id, args.to_id, args.kind, args.reason)
            if a == "list": return st.list_relations(args.object_id, status=args.status, limit=args.limit)
            if a == "status": return st.set_relation_status(args.id, args.state, reason=args.reason)
        if cmd == "conversation":
            if a == "add": return st.create_conversation(args.title, source=args.source)
            if a == "message": return st.append_message(args.id, args.role, _read_body(args))
            if a == "show": return st.get_conversation(args.id)
            if a == "list": return st.list_conversations(limit=args.limit)
            if a == "import-json": return st.import_conversation_json(args.file)
        if cmd == "candidate":
            if a == "propose": return st.propose_candidate(args.conversation_id, args.message_id,
                                                           args.kind, args.title, _read_body(args))
            if a == "show": return st.get_candidate(args.id)
            if a == "list": return st.list_candidates(state=None if args.state == "all" else args.state,
                                                        limit=args.limit)
            if a == "approve": return st.approve_candidate(args.id, synthesized_from=args.source_id,
                                                            synthesis_rationale=args.synthesis_rationale)
            if a == "merge": return st.merge_candidate(args.id, args.target_id, reason=args.reason,
                                                        new_body=_read_body(args, "new_body"),
                                                        expected_revision=args.expected_revision)
            if a == "reject": return st.reject_candidate(args.id, reason=args.reason)
        if cmd == "frontier":
            if a == "suggest": return st.suggest_frontier(args.source_id, args.question_id,
                                                           args.signal, args.reason)
            if a == "list": return st.list_frontier(state=None if args.state == "all" else args.state,
                                                     limit=args.limit)
            if a == "decide": return st.decide_frontier(args.id, args.state, reason=args.reason)
    raise InvalidInput("command was not implemented")


def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    try:
        result = execute(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "doctor" and not result["ok"]:
            return 1
        if args.command == "import-history" and (result.get("errors") or
              any(f.get("conflicts") for f in result.get("file_results", []))):
            return 1
        if args.command == "bridge" and (result.get("conflicts") or result.get("missing") or
              result.get("refresh", {}).get("conflicts")):
            return 1
        return 0
    except (VKFError, OSError, ValueError, UnicodeError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:
        # sqlite3.IntegrityError is a separate branch of DatabaseError, not a VKFError;
        # present a controlled diagnostic instead of a bare traceback.
        import sqlite3
        if isinstance(exc, sqlite3.Error):
            print(json.dumps({"error": "SQLiteError", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
