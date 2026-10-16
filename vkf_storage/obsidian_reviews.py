"""Read-only Obsidian projection of review proposals, scopes, effects and topics."""
from __future__ import annotations
from .core import Storage
from .obsidian import _generated_write, _slug, _q, _link

MARK = '<!-- VKF:GENERATED; DO NOT EDIT -->\n'


def _candidate_ref(candidate):
    title = candidate['title'].replace('|','-').replace(']','')
    return f"[[VKF/Candidates/{_slug(candidate['title'])}--{candidate['id'][-10:]}|{title}]]"


def export_consolidation_views(st: Storage, root, key: str, paths: dict[str,str]) -> dict:
    warnings=[]
    pending_by_scope={x: [] for x in ('cross_conversation','mixed','same_conversation','none','unknown')}
    topics=[]
    for review in st.db.execute('SELECT * FROM consolidation_reviews ORDER BY created_at DESC,id'):
        candidate=st.get_candidate(review['candidate_id'])
        rel=f"VKF/Consolidation/{_slug(candidate['title'])}--{review['id'][-10:]}.md"
        lines=[MARK.rstrip(),'---',f"vkf_review_id: {_q(review['id'])}",
               f"vkf_decision: {_q(review['decision'])}",
               f"vkf_review_status: {_q(review['status'])}",
               f"vkf_scope: {_q(review['comparison_scope'])}",
               f"vkf_effect: {_q(review['effect'])}",
               'tags: [vkf, vkf/consolidation]','---','',
               f"# Review: {candidate['title']}",'',
               '> [!warning] 比较建议 ≠ 正式知识。审核后也可能只产生临时候选关系。','',
               f"- Review status: **{review['status']}**",
               f"- Decision: **{review['decision']}**",
               f"- Candidate: {_candidate_ref(candidate)}",
               f"- Comparison scope: **{review['comparison_scope']}**",
               f"- Review effect: **{review['effect']}**",
               f"- Lexical retrieval score (not probability): {review['score']:.3f}"]
        if review['target_candidate_id']:
            target=st.get_candidate(review['target_candidate_id'])
            lines.append('- Target: '+_candidate_ref(target))
        if review['target_object_id']:
            obj=st.get_object(review['target_object_id'])
            if obj['id'] in paths:
                lines.append('- Target: '+_link(obj,paths[obj['id']]))
        lines += ['', '## Comparison rationale','',review['rationale'],'',
                  '## Human review','',
                  f"`consolidate decide {review['id']} accept --reason reviewed`",'',
                  f"`consolidate decide {review['id']} dismiss --reason not-equivalent`",'']
        try:
            _generated_write(st,root,key,rel,'\n'.join(lines)+'\n',MARK)
            if review['status']=='pending':
                pending_by_scope.get(review['comparison_scope'],pending_by_scope['unknown']).append((candidate['title'],rel))
        except Exception as exc:
            warnings.append({'path':rel,'error':str(exc)})

    for topic in st.db.execute('SELECT * FROM topics ORDER BY created_at,id'):
        rel=f"VKF/Topics/{_slug(topic['label'])}--{topic['id'][-10:]}.md"
        lines=[MARK.rstrip(),'---',f"vkf_topic_id: {_q(topic['id'])}",
               'tags: [vkf, vkf/topic]','---','',f"# Topic: {topic['label']}",'',
               '> 本主题仅用于导航，来源共同或词汇相近不代表两个命题等价。',
               '','## Candidates','']
        for cand in st.db.execute('''SELECT c.* FROM candidates c
              JOIN candidate_topics ct ON ct.candidate_id=c.id
              WHERE ct.topic_id=? ORDER BY c.created_at,c.id''',(topic['id'],)):
            lines.append(f"- {_candidate_ref(cand)} · `{cand['state']}`")
        lines.extend(['','## Reviewed provisional relationships',''])
        for link in st.db.execute('''SELECT cl.* FROM candidate_links cl
                JOIN candidate_topics ct ON ct.candidate_id=cl.from_candidate_id
                WHERE ct.topic_id=? ORDER BY cl.created_at,cl.id''', (topic['id'],)):
            a=st.get_candidate(link['from_candidate_id'])
            if link['to_candidate_id']:
                b=st.get_candidate(link['to_candidate_id'])
                other=_candidate_ref(b)
            else:
                b=st.get_object(link['to_object_id'])
                other=_link(b,paths[b['id']]) if b['id'] in paths else b['id']
            lines.append(f"- {_candidate_ref(a)} **{link['kind']}** → {other}")
        lines.extend(['','## Formal objects',''])
        for obj in st.db.execute('''SELECT o.* FROM cognitive_objects o
                 JOIN object_topics ot ON ot.object_id=o.id
                 WHERE ot.topic_id=? ORDER BY o.created_at,o.id''',(topic['id'],)):
            if obj['id'] in paths:
                lines.append('- '+_link(dict(obj),paths[obj['id']]))
        try:
            _generated_write(st,root,key,rel,'\n'.join(lines)+'\n',MARK)
            topics.append((topic['label'],rel))
        except Exception as exc:
            warnings.append({'path':rel,'error':str(exc)})

    index=[MARK.rstrip(),'# VKF · Cognitive Consolidation','',
           '> 对话内部的 REFINES/RELATED 不等于跨对话去重。审查范围详见每条建议的 `vkf_scope`。','']
    for title,kind in [('Across conversations','cross_conversation'),
                       ('Overlapping conversation sources','mixed'),
                       ('Within a conversation','same_conversation'),
                       ('No retrieved target','none'),('Unknown / legacy provenance','unknown')]:
        rows=pending_by_scope[kind]
        if rows:
            index.extend(['## '+title,''])
            index.extend(f"- [[{path[:-3]}|{name.replace('|','-')}]]" for name,path in rows)
            index.append('')
    index.extend(['## Topic clusters',''])
    index.extend(f"- [[{path[:-3]}|{name.replace('|','-')}]]" for name,path in topics)
    index.extend(['','## Bases','','- [[VKF/Consolidation Inbox.base|Consolidation Inbox]]',''])
    index_path='VKF/01 - Consolidation.md'
    try:
        _generated_write(st,root,key,index_path,'\n'.join(index)+'\n',MARK)
    except Exception as exc:
        warnings.append({'path':index_path,'error':str(exc)})

    base='''# VKF:GENERATED; DO NOT EDIT
filters:
  and:
    - 'vkf_review_status == "pending"'
views:
  - type: table
    name: "Consolidation Inbox"
    order:
      - file.name
      - vkf_decision
      - vkf_scope
      - vkf_effect
'''
    base_path='VKF/Consolidation Inbox.base'
    try:
        _generated_write(st,root,key,base_path,base,'# VKF:GENERATED; DO NOT EDIT\n')
    except Exception as exc:
        warnings.append({'path':base_path,'error':str(exc)})
    return {'pending_reviews':sum(map(len,pending_by_scope.values())),
            'pending_by_scope':{k:len(v) for k,v in pending_by_scope.items()},
            'topics':len(topics),'warnings':warnings}
