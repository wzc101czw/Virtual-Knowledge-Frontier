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
    probe = sub.add_parser("model-probe", help="safe small API compatibility check (sends test text, may be billed)")
    probe.add_argument("--model")
    probe.add_argument("--api-base")
    probe.add_argument("--timeout", type=int)
    probe.add_argument("--max-tokens", type=int, default=2048)
    probe.add_argument("--task", choices=["basic", "compare", "extract"], default="basic",
                       help="compare uses the real comparison prompt on synthetic examples")
    cf = sub.add_parser("config", help="persist vault and model settings per database (no API secrets)")
    cfsub = cf.add_subparsers(dest="action",required=True)
    cfsub.add_parser("show")
    cs = cfsub.add_parser("set")
    cs.add_argument("key", choices=["vault", "model", "api-base", "timeout", "extract", "compare"])
    cs.add_argument("value")
    lc = sub.add_parser('lifecycle', help='preview and safely purge incorrect VKF history')
    lsub = lc.add_subparsers(dest='action', required=True)
    lp = lsub.add_parser('plan', help='read-only affected-record counts and confirmation token')
    lp.add_argument('--scope', choices=['derived','extraction','conversation','all'], required=True)
    lp.add_argument('--conversation-id')
    la = lsub.add_parser('apply', help='verified SQLite backup then atomic purge')
    la.add_argument('--scope', choices=['derived','extraction','conversation','all'], required=True)
    la.add_argument('--conversation-id')
    la.add_argument('--confirm', required=True, help='token returned by lifecycle plan')
    lv = lsub.add_parser('vault-prune', help='archive fingerprint-matching retired notes outside Obsidian')
    lv.add_argument('--vault', type=Path)
    lv.add_argument('--apply', action='store_true')
    lv.add_argument('--confirm', help='token returned by lifecycle vault-prune preview')
    cc = sub.add_parser("consolidate", help="compare incoming candidates with existing cognition")
    csub = cc.add_subparsers(dest="action", required=True)
    c = csub.add_parser("run", help="create non-destructive comparison proposals")
    c.add_argument("--mode", choices=["heuristic", "llm"])
    c.add_argument("--model"); c.add_argument("--api-base"); c.add_argument("--timeout", type=int)
    c.add_argument("--limit",type=int,default=200)
    c.add_argument("--scope", choices=["all","cross","within"], default="all",
                   help="cross compares distinct source conversations; within inspects one conversation")
    c = csub.add_parser("links",help="human-confirmed provisional candidate links, not formal knowledge")
    c.add_argument("--candidate-id"); c.add_argument("--limit",type=int,default=100)
    c = csub.add_parser("list"); c.add_argument("--status", default="pending", choices=["pending","applied","dismissed","all"])
    c.add_argument("--limit", type=int,default=100)
    c = csub.add_parser("show"); c.add_argument("id")
    c = csub.add_parser("suggest",help="manually label a candidate against a target")
    c.add_argument("candidate_id"); c.add_argument("decision", choices=["SAME","REFINES","CONTRADICTS","RELATED","NEW","CROSS_DOMAIN","DISCARD"])
    c.add_argument("--target"); c.add_argument("--reason",required=True)
    c.add_argument("--scope",choices=["all","cross","within"],default="all")
    c = csub.add_parser("decide",help="explicit human approval of a suggested comparison")
    c.add_argument("id"); c.add_argument("action",choices=["accept","dismiss"])
    c.add_argument("--reason",required=True); c.add_argument("--new-body-file",type=Path)
    t = sub.add_parser("topic",help="browse provisional topic clusters")
    tt = t.add_subparsers(dest="action",required=True)
    s = tt.add_parser("list"); s.add_argument("--limit",type=int,default=100)
    pl = sub.add_parser("pipeline",help="reprocess old conversations with v2 extractor then consolidate")
    ps = pl.add_subparsers(dest="action",required=True)
    p_run = ps.add_parser("run")
    p_run.add_argument("--all",action="store_true",help="explicit confirmation to reprocess all imported conversations")
    p_run.add_argument("--extract",choices=["none","heuristic","llm"])
    p_run.add_argument("--compare",choices=["heuristic","llm"])
    p_run.add_argument("--model");p_run.add_argument("--api-base");p_run.add_argument("--timeout",type=int)
    p_run.add_argument("--limit",type=int,default=50)
    p_run.add_argument("--scope",choices=["all","cross","within"],default="all")

    ev = sub.add_parser('evaluate',help='score comparison reviews against your manually labelled pairs')
    ev.add_argument('annotations',type=Path)
    cv = sub.add_parser("coverage",help="audit lossless model extraction input coverage")
    cv.add_argument("conversation_id")
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
    s.add_argument("--confirm-understanding", action="store_true", help="confirm this is your own understanding")
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
    imp.add_argument("--extract", choices=["none", "heuristic", "llm"],
                     help="default offline literal candidates; model requests are explicit only")
    imp.add_argument("--model", help="required if --extract llm")
    imp.add_argument("--api-base")
    imp.add_argument("--timeout", type=int)
    imp.add_argument("--vault", type=Path, help="override saved vault")
    imp.add_argument("--consolidate", action="store_true", help="create review proposals immediately after import")

    ext = sub.add_parser("extract", help="generate candidate inbox entries from an already imported chat")
    ext.add_argument("conversation_id")
    ext.add_argument("--mode", choices=["heuristic", "llm"])
    ext.add_argument("--model")
    ext.add_argument("--api-base")
    ext.add_argument("--timeout", type=int)

    bridge = sub.add_parser("bridge", help="Obsidian Markdown projection + reviewed edits")
    bridges = bridge.add_subparsers(dest="action", required=True)
    s = bridges.add_parser("export", help="write a managed VKF/ folder in an Obsidian vault")
    s.add_argument("vault", type=Path, nargs="?")
    s.add_argument("--restore-missing", action="store_true", help="recreate explicitly deleted managed notes")
    s.add_argument("--no-conversations", action="store_true")
    s.add_argument("--no-candidates", action="store_true")
    s = bridges.add_parser("status", help="review pending Obsidian edits without modifying SQLite")
    s.add_argument("vault", type=Path, nargs="?")
    s = bridges.add_parser("pull", help="preview Obsidian edits, optionally apply them")
    s.add_argument("vault", type=Path, nargs="?")
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
    from .settings import load_settings,save_setting
    if args.command == 'config':
        if args.action == 'show':
            return {'path':str(Path(args.db).expanduser().resolve())+'.settings.json',
                    'settings':load_settings(args.db),'api_key_saved':False,
                    'api_key_present_in_environment':bool(__import__('os').environ.get('VKF_API_KEY'))}
        if args.action == 'set':
            return save_setting(args.db,args.key.replace('-','_'),args.value)
    settings=load_settings(args.db)
    model=lambda: (getattr(args,'model',None) or settings['model'])
    api_base=lambda: (getattr(args,'api_base',None) or settings['api_base'])
    timeout=lambda: (getattr(args,'timeout',None) or settings['timeout'])
    vault=lambda: (getattr(args,'vault',None) or settings['vault'])
    if args.command == 'model-probe':
        from .importers import request_model_json
        if not model():
            raise InvalidInput('configure a model first: config set model MODEL_ID')
        if args.task == "compare":
            from .consolidation import _comparison_prompt_and_input, DECISIONS
            system, query = _comparison_prompt_and_input(
                {'kind':'idea', 'title':'KV 缓存可以复用计算结果',
                 'body':'通过缓存降低重复计算，但需要失效条件。'},
                [{'target_id':'synthetic-previous', 'kind':'idea',
                  'title':'缓存降低重复计算成本',
                  'body':'缓存可降低重复计算，但增加了存储和一致性管理成本。'}])
            result = request_model_json(system, query, model(), api_base(), timeout(),
                                        max_tokens=args.max_tokens, task='comparison')
            if result.get('decision') not in DECISIONS:
                raise InvalidInput('comparison probe: invalid decision')
            target = result.get('target_id')
            if target not in (None, 'synthetic-previous'):
                raise InvalidInput('comparison probe: unknown target_id')
            if result['decision'] in ('NEW', 'DISCARD') and target is not None:
                raise InvalidInput('comparison probe: NEW/DISCARD must use null target_id')
            if result['decision'] not in ('NEW', 'DISCARD') and target is None:
                raise InvalidInput('comparison probe: relation decision requires target_id')
            if not isinstance(result.get('rationale'), str) or not result['rationale'].strip():
                raise InvalidInput('comparison probe: missing rationale')
            return {'ok': True, 'task': 'compare', 'decision': result['decision'],
                    'model': model(), 'note': 'Synthetic comparison only; no VKF knowledge sent.'}
        if args.task == 'extract':
            from .importers import _SYSTEM, _llm_suggestions
            # Synthetic text uses the real extraction prompt and returns counts,
            # never customer data or candidate texts.
            text = '0 | user: 我猜想缓存可以复用计算，但需要考虑失效条件。\n1 | assistant: 可将其作为待验证的研究假说。'
            extracted = request_model_json(_SYSTEM, text, model(), api_base(), timeout(),
                                           max_tokens=args.max_tokens, task='extraction')
            candidates = extracted.get('candidates')
            if not isinstance(candidates, list):
                raise InvalidInput('extraction probe: expected candidates array')
            return {'ok': True, 'task': 'extract', 'candidates_count': len(candidates),
                    'model': model(), 'note': 'Synthetic text only; no private VKF knowledge sent.'}
        result = request_model_json('Reply with a JSON object only; keys: ok and probe.',
            'Return exactly this JSON object: {"ok":true,"probe":"vkf"}',
            model(), api_base(), timeout(), max_tokens=args.max_tokens, task='probe')
        return {'ok': result.get('ok') is True, 'task': 'basic', 'model': model(),
                'response_keys': sorted(result.keys()),
                'note': 'Probe sends a small test prompt; no private VKF knowledge was sent.'}
    with Storage(args.db) as st:
        cmd = args.command
        if cmd == "import-history":
            from .importers import import_history
            from .obsidian import export_vault
            result = import_history(st, args.path, source=args.source,
                                    extract=args.extract or settings['extract'],
                                    model=model(), api_base=api_base(), timeout=timeout())
            if args.consolidate:
                from .consolidation import consolidate_pending
                result['consolidation'] = consolidate_pending(st,mode=settings['compare'],
                    model=model(),api_base=api_base(),timeout=timeout())
            if vault():
                result["obsidian"] = export_vault(st, vault())
            return result
        if cmd == "extract":
            from .importers import extract_conversation
            return extract_conversation(st, args.conversation_id, mode=args.mode or
                                        (settings['extract'] if settings['extract'] != 'none' else 'heuristic'),
                                        model=model(), api_base=api_base(), timeout=timeout())
        if cmd == "bridge":
            from .obsidian import export_vault, pull_vault, bridge_status
            if not vault():
                raise InvalidInput('no vault path supplied; use config set vault PATH')
            if args.action == "export":
                return export_vault(st, vault(), include_conversations=not args.no_conversations,
                                    include_candidates=not args.no_candidates,
                                    restore_missing=args.restore_missing)
            if args.action == "pull":
                return pull_vault(st, vault(), apply=args.apply)
            if args.action == "status":
                return bridge_status(st, vault())
        if cmd == 'lifecycle':
            from .lifecycle import plan, apply, vault_prune
            if args.action == 'plan':
                return plan(st, args.scope, args.conversation_id)
            if args.action == 'apply':
                return apply(st, args.scope, conversation_id=args.conversation_id,
                             confirm=args.confirm)
            if args.action == 'vault-prune':
                if not vault():
                    raise InvalidInput('no vault path configured; use config set vault PATH')
                return vault_prune(st, vault(), apply_changes=args.apply, confirm=args.confirm)
        if cmd == 'consolidate':
            from .consolidation import (consolidate_pending,list_reviews,get_review,
                                        suggest_review,decide_review,list_candidate_links)
            if args.action == 'run':
                return consolidate_pending(st,mode=args.mode or settings['compare'],model=model(),
                                           api_base=api_base(),timeout=timeout(),limit=args.limit,scope=args.scope)
            if args.action == 'links': return list_candidate_links(st,candidate_id=args.candidate_id,limit=args.limit)
            if args.action == 'list': return list_reviews(st,status=args.status,limit=args.limit)
            if args.action == 'show': return get_review(st,args.id)
            if args.action == 'suggest': return suggest_review(st,args.candidate_id,
                force_decision=args.decision,force_target=args.target,force_reason=args.reason,
                scope=args.scope)
            if args.action == 'decide':
                body=args.new_body_file.read_text(encoding='utf-8') if args.new_body_file else None
                return decide_review(st,args.id,args.action,reason=args.reason,new_body=body)
        if cmd == 'topic':
            from .consolidation import list_topics
            if args.action == 'list': return list_topics(st,limit=args.limit)
        if cmd == 'pipeline':
            from .importers import extract_conversation
            from .consolidation import consolidate_pending
            if not args.all:
                raise InvalidInput('pipeline run requires --all to reprocess historical conversations')
            conversations=st.list_conversations(limit=min(args.limit,1000))
            reports=[]; errors=[]
            for conv in reversed(conversations):
                try:
                    reports.append(extract_conversation(st,conv['id'],
                        mode=args.extract or settings['extract'],model=model(),
                        api_base=api_base(),timeout=timeout()))
                except (VKFError,OSError,ValueError) as exc:
                    errors.append({'conversation_id':conv['id'],'error':str(exc)})
            comparisons=consolidate_pending(st,mode=args.compare or settings['compare'],
                model=model(),api_base=api_base(),timeout=timeout(),limit=min(args.limit*20,1000),scope=args.scope)
            if vault():
                from .obsidian import export_vault
                comparisons['obsidian']=export_vault(st,vault())
            return {'conversations_processed':len(reports),'extractions':reports,
                    'extraction_errors':errors,'consolidation':comparisons}
        if cmd == 'evaluate':
            from .evaluation import evaluate
            return evaluate(st,args.annotations)
        if cmd == 'coverage':
            from .coverage import report_coverage
            return report_coverage(st,args.conversation_id)
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
                                                            synthesis_rationale=args.synthesis_rationale,
                                                            confirm_understanding=args.confirm_understanding)
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
        if args.command == "pipeline" and result.get('extraction_errors'):
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
