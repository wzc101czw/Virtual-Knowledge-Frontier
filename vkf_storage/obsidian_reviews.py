"""Read-only Obsidian projections of consolidation reviews and topic clusters."""
from __future__ import annotations
from .core import Storage
from .obsidian import _generated_write, _slug, _q, _link


def export_consolidation_views(st: Storage, root, key: str, paths: dict[str,str]) -> dict:
    mark='<!-- VKF:GENERATED; DO NOT EDIT -->\n'
    warnings=[]; reviews=[]; topics=[]
    for r in st.db.execute("SELECT * FROM consolidation_reviews ORDER BY created_at DESC,id"):
        candidate=st.get_candidate(r['candidate_id'])
        rel=f"VKF/Consolidation/{_slug(candidate['title'])}--{r['id'][-10:]}.md"
        original=f"VKF/Candidates/{_slug(candidate['title'])}--{candidate['id'][-10:]}"
        lines=[mark.rstrip(),'---',f"vkf_review_id: {_q(r['id'])}",
               f"vkf_decision: {_q(r['decision'])}",f"vkf_review_status: {_q(r['status'])}",
               'tags: [vkf, vkf/consolidation]','---','',f"# Review: {candidate['title']}",'',
               '> [!warning] 此页记录比较建议与审核状态；并非全部建议已落实为正式关系。','',
               f"- Review status: **{r['status']}**",
               f"- New candidate: [[{original}|{candidate['title'].replace('|','-')}]]",
               f"- Suggested decision: **{r['decision']}**",
               f"- Retrieval score (not probability): {r['score']:.3f}"]
        if r['target_candidate_id']:
            other=st.get_candidate(r['target_candidate_id'])
            tgt=f"VKF/Candidates/{_slug(other['title'])}--{other['id'][-10:]}"
            lines.append(f"- Compare with: [[{tgt}|{other['title'].replace('|','-')}]]")
        if r['target_object_id']:
            other=st.get_object(r['target_object_id'])
            if other['id'] in paths:
                lines.append(f"- Compare with: {_link(other,paths[other['id']])}")
        lines += ['','## Rationale','',r['rationale'],'','## Human approval','',
                  f"`consolidate decide {r['id']} accept --reason reviewed`",'',
                  f"`consolidate decide {r['id']} dismiss --reason not-equivalent`",'']
        try:
            _generated_write(st,root,key,rel,'\n'.join(lines)+'\n',mark)
            if r['status']=='pending':
                reviews.append((candidate['title'],rel))
        except Exception as exc:
            warnings.append({'path':rel,'error':str(exc)})
    for t in st.db.execute('SELECT * FROM topics ORDER BY created_at,id'):
        rel=f"VKF/Topics/{_slug(t['label'])}--{t['id'][-10:]}.md"
        lines=[mark.rstrip(),'---',f"vkf_topic_id: {_q(t['id'])}",
               'tags: [vkf, vkf/topic]','---','',f"# Topic: {t['label']}",'',
               '> 主题聚合用于导航，并不意味着观点等价。','', '## Candidate Concepts','']
        for c in st.db.execute('''SELECT c.* FROM candidates c JOIN candidate_topics ct ON ct.candidate_id=c.id
            WHERE ct.topic_id=? ORDER BY c.created_at,c.id''',(t['id'],)):
            dst=f"VKF/Candidates/{_slug(c['title'])}--{c['id'][-10:]}"
            lines.append(f"- [[{dst}|{c['title'].replace('|','-')}]] · `{c['state']}`")
        lines.extend(['','## Formal Objects',''])
        for o in st.db.execute('''SELECT o.* FROM cognitive_objects o JOIN object_topics ot ON ot.object_id=o.id
            WHERE ot.topic_id=? ORDER BY o.created_at,o.id''',(t['id'],)):
            if o['id'] in paths:
                lines.append('- '+_link(dict(o),paths[o['id']]))
        try:
            _generated_write(st,root,key,rel,'\n'.join(lines)+'\n',mark)
            topics.append((t['label'],rel))
        except Exception as exc:
            warnings.append({'path':rel,'error':str(exc)})
    index=[mark.rstrip(),'# VKF · Cognitive Consolidation','',
           '> AI/规则仅提出合并建议，必须人工确认。','',
           '## Pending Reviews','',
           *[f"- [[{path[:-3]}|{title.replace('|','-')}]]" for title,path in reviews],
           '','## Topic Clusters','',
           *[f"- [[{path[:-3]}|{title.replace('|','-')}]]" for title,path in topics],
           '','## Bases','',
           '- [[VKF/Consolidation Inbox.base|Consolidation Inbox]]','']
    try:
        _generated_write(st,root,key,'VKF/01 - Consolidation.md','\n'.join(index)+'\n',mark)
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
'''
        _generated_write(st,root,key,'VKF/Consolidation Inbox.base',base,'# VKF:GENERATED; DO NOT EDIT\n')
    except Exception as exc:
        warnings.append({'path':'VKF/01 - Consolidation.md','error':str(exc)})
    return {'pending_reviews':len(reviews),'topics':len(topics),'warnings':warnings}
