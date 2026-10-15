"""Obsidian Markdown bridge with SQLite authority and opt-in review of edits.

Scope v0.1.1: preserve existing Obsidian files, never silently reconcile
conflicting edits, and never change formal knowledge from a model suggestion.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from uuid import uuid4
from typing import Any

from .core import Storage, Conflict, InvalidInput

START = '<!-- VKF:EDITABLE:START -->'
END = '<!-- VKF:EDITABLE:END -->'
FOLDERS = {
    "knowledge": "Knowledge", "idea": "Ideas", "understanding": "Understanding",
    "question": "Questions", "cross_insight": "CrossInsights",
}
MAX_NOTE = 5 * 1024 * 1024


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _vault(vault: str | Path) -> tuple[Path, str]:
    root = Path(vault).expanduser().resolve()
    if root.is_file():
        raise InvalidInput("vault must be a directory")
    root.mkdir(parents=True, exist_ok=True)
    # Only a local path fingerprint is stored. No Obsidian account/access token.
    return root, hashlib.sha256(str(root).encode()).hexdigest()


def _path(root: Path, relative: str) -> Path:
    if relative.startswith("/") or ".." in Path(relative).parts or not relative.startswith("VKF/"):
        raise InvalidInput(f"unsafe path inside vault: {relative}")
    candidate = root / relative
    if not candidate.resolve().is_relative_to(root):
        raise InvalidInput(f"vault path escapes its root: {relative}")
    if candidate.is_symlink():
        raise InvalidInput("refusing to read/write a symlink in Vault")
    return candidate


def _slug(title: str) -> str:
    clean = re.sub(r'[\\/:*?"<>|\[\]#^\r\n]+', '-', title)
    clean = re.sub(r"\s+", "-", clean).strip(". -")
    return clean[:55] or "Untitled"


def _q(s: str) -> str:
    return json.dumps(str(s), ensure_ascii=False)


def _target_path(obj: dict[str, Any]) -> str:
    return f"VKF/{FOLDERS[obj['kind']]}/{_slug(obj['title'])}--{obj['id'][-10:]}.md"


def _link(obj: dict[str, Any], path: str) -> str:
    target = path.removesuffix(".md")
    label = obj["title"].replace("|", "-").replace("]", "")
    return f"[[{target}|{label}]]"


def _atomic_write(target: Path, contents: str, *, exists_ok: bool = True) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise Conflict("refusing to write symlink")
    if target.exists() and not exists_ok:
        raise Conflict(f"refusing to overwrite existing file: {target}")
    tmp = target.with_name(target.name + ".vkf-tmp-" + uuid4().hex[:8])
    try:
        with open(tmp, "x", encoding="utf-8", newline="\n") as f:
            os.chmod(tmp, 0o600)
            f.write(contents)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def _render_object(st: Storage, obj: dict[str, Any], paths: dict[str, str]) -> tuple[str, str, str]:
    if START in obj["body"] or END in obj["body"] or "\n" in obj["title"]:
        raise Conflict("object content contains the reserved Obsidian editable delimiters")
    front = [
        "---",
        f"vkf_id: {_q(obj['id'])}",
        f"vkf_kind: {_q(obj['kind'])}",
        f"vkf_revision: {obj['revision']}",
        f"vkf_status: {_q(obj['status'])}",
        f"vkf_epistemic: {_q(obj['epistemic_status'])}",
        *([f"vkf_question_state: {_q(st.get_object(obj['id'])['question_state']['state'])}"]
          if obj["kind"] == "question" else []),
        f"aliases: [{_q(obj['title'])}]",
        f"tags: [vkf, vkf/{obj['kind']}]",
        "---", "",
        "> [!note] VKF 认知对象 · SQLite 是正式记录。请仅修改以下可编辑区域，再运行 `bridge pull --apply`。", "",
        START, "",
    ]
    prefix = "\n".join(front)
    editable = f"# {obj['title']}\n\n{obj['body'].rstrip()}\n\n"
    suffix_lines = [END, "", "## VKF Relations (generated)", ""]
    relations = st.list_relations(obj["id"], status="active", limit=1000)
    for rel in relations:
        source_id = rel["from_object_id"]
        other_id = rel["to_object_id"] if source_id == obj["id"] else source_id
        if other_id not in paths:
            continue
        other = st.get_object(other_id)
        direction = "→" if source_id == obj["id"] else "←"
        reason = rel["rationale"].replace("\n", " ").replace("|", "-")
        suffix_lines.append(f"- `{rel['kind']}` {direction} {_link(other, paths[other_id])} — {reason}")
    if not relations:
        suffix_lines.append("- 暂无正式关系")
    origins = st.db.execute("""SELECT DISTINCT c.id,c.title,m.turn_index
          FROM object_sources os JOIN messages m ON m.id=os.message_id
          JOIN conversations c ON c.id=m.conversation_id WHERE os.object_id=?
          ORDER BY c.title,m.turn_index LIMIT 100""", (obj["id"],)).fetchall()
    if origins:
        suffix_lines += ["", "## Origin Conversations (generated)", ""]
        for conv_id, conv_title, turn in origins:
            convpath = f"VKF/Conversations/{_slug(conv_title)}--{conv_id[-10:]}"
            suffix_lines.append(f"- [[{convpath}|{conv_title.replace('|','-')}]] · turn {turn + 1}")
    if obj["kind"] == "question":
        qs = st.get_object(obj["id"])["question_state"]
        suffix_lines += ["", "## Question State (generated)", "", f"- **State**: `{qs['state']}`"]
        if qs["resolution_note"]:
            suffix_lines.append(f"- **Resolution**: {qs['resolution_note']}")
    suffix_lines += ["", "---", "*VKF-managed metadata, graph and status are not editable here.*", ""]
    suffix = "\n".join(suffix_lines)
    return prefix, editable, suffix


def _state(st: Storage, key: str, oid: str) -> dict[str, Any] | None:
    row = st.db.execute("SELECT * FROM obsidian_bridge_state WHERE vault_key=? AND object_id=?", (key, oid)).fetchone()
    return dict(row) if row else None


def _mark_export(st: Storage, key: str, oid: str, rel: str, revision: int,
                 sha: str, prefix: str, suffix: str) -> None:
    with st.transaction():
        st.db.execute("""INSERT INTO obsidian_bridge_state(vault_key,object_id,relative_path,exported_revision,
                         exported_sha256,managed_prefix,managed_suffix) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(vault_key,object_id) DO UPDATE SET relative_path=excluded.relative_path,
            exported_revision=excluded.exported_revision,exported_sha256=excluded.exported_sha256,
            managed_prefix=excluded.managed_prefix,managed_suffix=excluded.managed_suffix,
            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
            (key, oid, rel, revision, sha, prefix, suffix))


def _read_small(path: Path) -> str:
    if path.stat().st_size > MAX_NOTE:
        raise Conflict("note is too large for the bridge")
    return path.read_text(encoding="utf-8")


def _generated_write(st: Storage, root: Path, key: str, rel: str, contents: str, marker: str) -> bool:
    """Never overwrite edits in generated indexes/chat archives/candidate notes."""
    target = _path(root, rel)
    row = st.db.execute("SELECT exported_sha256 FROM obsidian_readonly_state WHERE vault_key=? AND relative_path=?",
                        (key, rel)).fetchone()
    if target.exists():
        old = _read_small(target)
        if old == contents:
            # A newly adopted file must not be silently trusted if it was not generated by VKF.
            if row is None:
                raise Conflict(f"unmanaged existing file: {target}")
            return False
        if not old.startswith(marker) or row is None or _sha(old) != row[0]:
            raise Conflict(f"generated file has external edits or is unmanaged: {target}")
    elif row is not None:
        # Missing generated file can be recreated safely; it has no editable data authority.
        pass
    _atomic_write(target, contents, exists_ok=row is not None)
    with st.transaction():
        st.db.execute("""INSERT INTO obsidian_readonly_state(vault_key,relative_path,exported_sha256)
            VALUES(?,?,?) ON CONFLICT(vault_key,relative_path) DO UPDATE SET
            exported_sha256=excluded.exported_sha256,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
            (key, rel, _sha(contents)))
    return True


def _other_exports(st: Storage, root: Path, key: str, path_map: dict[str, str], *, include_conversations: bool,
                   include_candidates: bool) -> dict[str, Any]:
    generated = "<!-- VKF:GENERATED; DO NOT EDIT -->\n"
    summaries: dict[str, Any] = {"conversations": 0, "candidates": 0, "warnings": []}
    conversation_links = []
    if include_conversations:
        rows = st.db.execute("SELECT id,title,source FROM conversations ORDER BY created_at DESC").fetchall()
        for conv in rows:
            record = st.get_conversation(conv["id"])
            rel = f"VKF/Conversations/{_slug(record['title'])}--{record['id'][-10:]}.md"
            lines = [generated.rstrip(), "---", f"vkf_conversation_id: {_q(record['id'])}",
                     f"source: {_q(record['source'])}", f"aliases: [{_q(record['title'])}]", "tags: [vkf, vkf/conversation]",
                     "---", "", f"# {record['title']}", "", "> 只读对话归档；请在其他笔记中提炼、编辑观点。", ""]
            for msg in record["messages"]:
                metadata = st.db.execute("SELECT source_timestamp FROM message_import_metadata WHERE message_id=?",
                                         (msg["id"],)).fetchone()
                stamp = f" ({metadata[0]})" if metadata and metadata[0] else ""
                lines += [f"## {msg['turn_index'] + 1}. {msg['role'].capitalize()}{stamp}", "",
                          msg["content"], "", "---", ""]
            try:
                _generated_write(st, root, key, rel, "\n".join(lines) + "\n", generated)
                summaries["conversations"] += 1
                conversation_links.append((record["title"], rel))
            except (OSError, Conflict) as exc:
                summaries["warnings"].append({"file": rel, "reason": str(exc)})
    candidate_links = []
    if include_candidates:
        candidates = st.db.execute("SELECT * FROM candidates ORDER BY created_at DESC").fetchall()
        for cand in candidates:
            rel = f"VKF/Candidates/{_slug(cand['title'])}--{cand['id'][-10:]}.md"
            origins = st.db.execute("""SELECT DISTINCT c.id,c.title,m.turn_index FROM candidate_sources cs
                 JOIN messages m ON cs.message_id=m.id JOIN conversations c ON m.conversation_id=c.id
                 WHERE cs.candidate_id=? ORDER BY c.title,m.turn_index LIMIT 100""", (cand["id"],)).fetchall()
            source_notes = [f"- [[VKF/Conversations/{_slug(title)}--{cid[-10:]}|{title.replace('|','-')}]] · turn {turn + 1}"
                            for cid,title,turn in origins]
            origin=st.db.execute("""SELECT er.model_id,er.prompt_version,
                COALESCE(ca.source_actor,'unknown') FROM candidates c
                JOIN extraction_runs er ON er.id=c.extraction_run_id
                LEFT JOIN candidate_attributions ca ON ca.candidate_id=c.id
                WHERE c.id=?""",(cand['id'],)).fetchone()
            text = "\n".join([generated.rstrip(), "---", f"vkf_candidate_id: {_q(cand['id'])}",
                              f"vkf_kind: {_q(cand['kind'])}", f"vkf_state: {_q(cand['state'])}",
                              f"vkf_model: {_q(origin[0])}", f"vkf_prompt_version: {_q(origin[1])}",
                              f"vkf_source_actor: {_q(origin[2])}",
                              "tags: [vkf, vkf/candidate]", "---", "", f"# {cand['title']}", "",
                              f"> **{cand['state']}** · 模型/规则建议。仅经人工批准后才成为正式知识。", "",
                              cand["body"], "", "## Source conversations", "", *source_notes,
                              "", "---", "",
                              f"CLI: `candidate show {cand['id']}` / `candidate approve {cand['id']}`", ""])
            try:
                _generated_write(st, root, key, rel, text, generated)
                summaries["candidates"] += 1
                if cand["state"] == "pending" and not st.db.execute(
                    "SELECT 1 FROM candidate_equivalences WHERE duplicate_candidate_id=?",(cand['id'],)).fetchone():
                    candidate_links.append((cand["title"], rel))
            except (OSError, Conflict) as exc:
                summaries["warnings"].append({"file": rel, "reason": str(exc)})
    bases = {
        "VKF/VKF Objects.base": """# VKF:GENERATED; DO NOT EDIT
filters:
  and:
    - 'vkf_id != null'
views:
  - type: table
    name: "All Cognitive Objects"
    order:
      - file.name
      - vkf_kind
      - vkf_status
      - vkf_revision
""",
        "VKF/Open Questions.base": """# VKF:GENERATED; DO NOT EDIT
filters:
  and:
    - 'vkf_kind == "question"'
views:
  - type: table
    name: "Open Questions"
    filters:
      and:
        - 'vkf_question_state != "answered"'
    order:
      - file.name
      - vkf_question_state
      - vkf_revision
""",
        "VKF/Candidate Inbox.base": """# VKF:GENERATED; DO NOT EDIT
filters:
  and:
    - 'vkf_state == "pending"'
views:
  - type: table
    name: "Pending Candidates"
    order:
      - file.name
      - vkf_kind
      - vkf_state
""",
    }
    for basepath, basecontent in bases.items():
        try:
            _generated_write(st, root, key, basepath, basecontent, "# VKF:GENERATED; DO NOT EDIT\n")
        except (OSError, Conflict) as exc:
            summaries["warnings"].append({"file": basepath, "reason": str(exc)})
    lines = [generated.rstrip(), "# VKF · Cognitive Workspace", "",
             "> SQLite 为认知状态的权威记录；这里的 Markdown 提供人类可编辑的视图。", "",
             "## Browse with Obsidian Bases", "",
             "- [[VKF/VKF Objects.base|All Cognitive Objects]]",
             "- [[VKF/Open Questions.base|Open Questions]]",
             "- [[VKF/Candidate Inbox.base|Candidate Inbox]]",
             "- [[VKF/01 - Consolidation|Consolidation & Topics]]",
             "", "## Pending Candidate Inbox", ""]
    for title, rel in candidate_links:
        lines.append(f"- [[{rel[:-3]}|{title.replace('|','-')}]]")
    if not candidate_links:
        lines.append("- 暂无待审核候选")
    for kind, folder in FOLDERS.items():
        lines += ["", f"## {folder}", ""]
        objs = st.list_objects(kind=kind, limit=1000)
        if not objs:
            lines.append("- 暂无记录")
        for obj in objs:
            if obj["id"] in path_map:
                line = "- " + _link(obj, path_map[obj["id"]])
                if kind == "question":
                    line += f" · `{st.get_object(obj['id'])['question_state']['state']}`"
                lines.append(line)
    lines += ["", "## Conversation Archive", ""]
    for title, rel in conversation_links:
        lines.append(f"- [[{rel[:-3]}|{title.replace('|','-')}]]")
    if not conversation_links:
        lines.append("- 暂无对话")
    lines += ["", "_这是自动生成的入口；请将个人注释放在 VKF 文件夹之外。_", ""]
    try:
        _generated_write(st, root, key, "VKF/00 - Start Here.md", "\n".join(lines), generated)
    except (OSError, Conflict) as exc:
        summaries["warnings"].append({"file": "VKF/00 - Start Here.md", "reason": str(exc)})
    return summaries


def export_vault(st: Storage, vault: str | Path, *, include_conversations: bool = True,
                 include_candidates: bool = True, restore_missing: bool = False) -> dict[str, Any]:
    root, key = _vault(vault)
    objects = [dict(row) for row in st.db.execute("SELECT * FROM cognitive_objects ORDER BY created_at,id")]
    states = {obj["id"]: _state(st, key, obj["id"]) for obj in objects}
    paths = {obj["id"]: states[obj["id"]]["relative_path"] if states[obj["id"]] else _target_path(obj)
             for obj in objects}
    report: dict[str, Any] = {"vault": str(root), "exported": 0, "unchanged": 0,
                              "conflicts": [], "missing": [], "read_only": {}}
    for obj in objects:
        oid = obj["id"]
        row = states[oid]
        rel = paths[oid]
        try:
            target = _path(root, rel)
            if row and not target.exists() and not restore_missing:
                report["missing"].append({"id": oid, "file": rel, "reason": "previous projection missing; use --restore-missing"})
                continue
            if target.exists():
                incoming = _read_small(target)
                if row is None:
                    report["conflicts"].append({"id": oid, "file": rel, "reason": "unmanaged existing file"})
                    continue
                if _sha(incoming) != row["exported_sha256"]:
                    report["conflicts"].append({"id": oid, "file": rel, "reason": "unsynced Obsidian edit; run bridge pull first"})
                    continue
            prefix, editable, suffix = _render_object(st, obj, paths)
            generated = prefix + editable + suffix
            if target.exists() and incoming == generated:
                report["unchanged"] += 1
                continue
            _atomic_write(target, generated, exists_ok=bool(row))
            _mark_export(st, key, oid, rel, obj["revision"], _sha(generated), prefix, suffix)
            report["exported"] += 1
        except (OSError, Conflict, InvalidInput, UnicodeError) as exc:
            report["conflicts"].append({"id": oid, "file": rel, "reason": str(exc)})
    report["read_only"] = _other_exports(st, root, key, paths, include_conversations=include_conversations,
                                         include_candidates=include_candidates)
    from .obsidian_reviews import export_consolidation_views
    report['consolidation'] = export_consolidation_views(st,root,key,paths)
    return report


def _extract_editable(note: str, row: dict[str, Any], *, expected_id: str) -> tuple[str, str]:
    if note.count(START) != 1 or note.count(END) != 1:
        raise Conflict("editable markers are missing or duplicated")
    before, rest = note.split(START, 1)
    editable, after = rest.split(END, 1)
    if before + START + "\n" != row["managed_prefix"]:
        raise Conflict("VKF-managed properties/prefix were edited")
    if END + after != row["managed_suffix"]:
        raise Conflict("VKF-generated relations/status/footer were edited")
    if f'vkf_id: {_q(expected_id)}\n' not in before:
        raise Conflict("vkf_id mismatch")
    if f'vkf_revision: {row["exported_revision"]}\n' not in before:
        raise Conflict("vkf_revision mismatch")
    editable = editable.strip("\n")
    m = re.match(r"^# ([^\n]+)\n\n([\s\S]+)$", editable)
    if not m:
        raise Conflict("editable region must begin '# Title', followed by a blank line and body")
    title = m.group(1).strip()
    body = m.group(2).rstrip("\n")
    if not title or not body.strip():
        raise Conflict("title/body cannot be empty")
    return title, body


def pull_vault(st: Storage, vault: str | Path, *, apply: bool = False) -> dict[str, Any]:
    root, key = _vault(vault)
    rows = st.db.execute("SELECT * FROM obsidian_bridge_state WHERE vault_key=? ORDER BY object_id", (key,)).fetchall()
    report: dict[str, Any] = {"vault": str(root), "mode": "apply" if apply else "preview",
                              "ready": [], "unchanged": 0, "applied": [], "conflicts": []}
    for raw in rows:
        row = dict(raw)
        oid = row["object_id"]
        try:
            target = _path(root, row["relative_path"])
            if not target.exists():
                raise Conflict("previous projection was deleted/moved")
            content = _read_small(target)
            digest = _sha(content)
            if digest == row["exported_sha256"]:
                report["unchanged"] += 1
                continue
            obj = st.get_object(oid)
            if obj["revision"] != row["exported_revision"]:
                raise Conflict(f"SQLite revision {obj['revision']} differs from exported revision {row['exported_revision']}")
            title, body = _extract_editable(content, row, expected_id=oid)
            if title == obj["title"] and body == obj["body"].rstrip("\n"):
                raise Conflict("only formatting outside normalized editable content changed; no safe update")
            changed = {"title": title, "body": body}
            report["ready"].append({"id": oid, "file": row["relative_path"],
                                    "before_revision": obj["revision"], "new_title": title})
            if apply:
                if _sha(_read_small(target)) != digest:
                    raise Conflict("file changed during synchronization; retry")
                out = st.update_object(oid, reason="reviewed Obsidian Markdown edit",
                                       expected_revision=obj["revision"], **changed)
                # A recoverable two-step commit: note remains untouched until the next export.
                # Update the expected file fingerprint so export can rewrite the new revision.
                with st.transaction():
                    st.db.execute("UPDATE obsidian_bridge_state SET exported_sha256=?,exported_revision=?,"
                                  "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                                  "WHERE vault_key=? AND object_id=?",
                                  (digest, out["revision"], key, oid))
                report["applied"].append({"id": oid, "new_revision": out["revision"]})
        except (OSError, InvalidInput, Conflict, UnicodeError) as exc:
            report["conflicts"].append({"id": oid, "file": row["relative_path"], "reason": str(exc)})
    if apply and report["applied"]:
        report["refresh"] = export_vault(st, root)
    return report


def bridge_status(st: Storage, vault: str | Path) -> dict[str, Any]:
    return pull_vault(st, vault, apply=False)
