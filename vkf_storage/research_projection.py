"""One navigable research-space note per accepted space; reviews stay in an index.
No direct SQLite writes from Obsidian research notes in v0.3; edits are proposed
through an explicit JSON review to avoid accepting unsupported AI claims.
"""
from __future__ import annotations

import json
from .core import Storage
from .obsidian import _generated_write, _q, _slug

MARK='<!-- VKF:GENERATED; DO NOT EDIT -->\n'


def export_research(st:Storage,root,key:str)->dict:
    from .research import get_space, list_maps
    warnings=[]; written=0
    spaces=[r['id'] for r in st.db.execute('SELECT id FROM research_spaces ORDER BY title,id')]
    index=[MARK.rstrip(),'# VKF · Research Spaces','',
        '> 研究空间是经人工审核的结构。内部假设、AI 提议和相容性结论不因此成为已验证的事实。',
        '', '## Accepted research structures','']
    for space_id in spaces:
        data=get_space(st,space_id)
        sp=data['space'];rel=f'VKF/Research Spaces/{space_id}.md'
        index.append(f"- [[{rel[:-3]}|{sp['title'].replace('|','-')}]] · v{sp['revision']}")
        lines=[MARK.rstrip(),'---',f"vkf_research_space_id: {_q(space_id)}",
           f"vkf_research_revision: {sp['revision']}",
           f"vkf_research_question: {_q(sp['central_question'])}",
           'tags: [vkf, vkf/research-space]','---','',f"# {sp['title']}",'',
           '> [!info] 研究结构已审核，但其中的科学命题仍按各自证据状态处理。',
           '',f"**核心问题：** {sp['central_question']}",'',f"**研究目标：** {sp['goal'] or '待明确'}",'']
        vs_by={}
        for v in data['views']:vs_by.setdefault(v['context_id'],[]).append(v)
        for c in data['contexts']:
            lines.extend(['',f"## {c['title']}",'',c['focus'], ''])
            assumptions=json.loads(c['assumptions_json'])
            if assumptions:
                lines.extend(['**局部假设：**',''])
                lines.extend(f'- {x}' for x in assumptions)
                lines.append('')
            for v in vs_by.get(c['id'],[]):
                lines.append(f"- **{v['role']}** · `{v['kind']}` · **{v['attribution']} / {v['epistemic_status']}** — {v['statement']}")
                if v['parent_view_id']:
                    lines.append(f"  - Sub-idea parent: `{v['parent_view_id']}`")
                for ev in v['evidence']:
                    row=st.db.execute('''SELECT c.id,c.title,m.turn_index FROM messages m JOIN conversations c
                     ON c.id=m.conversation_id WHERE m.id=?''',(ev['message_id'],)).fetchone()
                    if row:
                        chat=f"VKF/Conversations/{_slug(row['title'])}--{row['id'][-10:]}"
                        lines.append(f"  - Source: [[{chat}|{row['title'].replace('|','-')}]] · turn {row['turn_index']+1}, chars {ev['start_char']}..{ev['end_char']}")
        lines.extend(['','## Coverage & unresolved technical questions',''])
        for d in data['coverage']:
            lines.append(f"- `{d['status']}` **{d['label']}** — {d['note']}")
        lines.extend(['','## Compatibility assessments (proposals unless reviewed)',''])
        for a in data['assessments']:
            lines.append(f"- `{a['verdict']}` · `{a['status']}` — {a['rationale']}")
        lines.extend(['','## Synthesis proposals (not verified Understanding)',''])
        for s in data['syntheses']:
            lines.append(f"- **{s['title']}** · `{s['status']}` — {s['mechanism']}")
        lines.extend(['','## Frontier / obstructions',''])
        for f in data['frontiers']:
            lines.append(f"- `{f['kind']}` · `{f['status']}` — {f['question']}。下一步：{f['next_test']}")
        lines.extend(['',f"_结构详情/研究修订：`research show {space_id}`；添加新对话时通过 `research map CONV_ID --space {space_id}` 提案。_",''])
        try:
            _generated_write(st,root,key,rel,'\n'.join(lines)+'\n',MARK)
            written+=1
        except Exception as exc:
            warnings.append({'file':rel,'reason':str(exc)})
    index.extend(['','## Pending research maps (not accepted)',''])
    for p in list_maps(st,status='pending',limit=1000):
        row=st.db.execute('SELECT title FROM conversations WHERE id=?',(p['conversation_id'],)).fetchone()
        name=row['title'] if row else p['conversation_id']
        index.append(f"- **{name}** — `research map-show {p['id']}` · revision {p['revision']} · researcher feedback: `research feedback {p['id']} too_fragmented --note ...`")
    index.extend(['','## Human evaluation','',
       'Run `research feedback-summary` to see ratings (too_fragmented / balanced / too_coarse / missing_important).',
       'For review, export `research map-show`, correct the JSON plan, then run `research revise`.','',
       '## Research Overview Base','',
       '- [[VKF/Research Overview.base|Research Overview]]',''])
    base='''# VKF:GENERATED; DO NOT EDIT
filters:
  and:
    - 'vkf_research_space_id != null'
views:
  - type: table
    name: "Research Spaces"
    order:
      - file.name
      - vkf_research_question
      - vkf_research_revision
'''
    for rel,text,marker in [('VKF/02 - Research Spaces.md','\n'.join(index)+'\n',MARK),
                            ('VKF/Research Overview.base',base,'# VKF:GENERATED; DO NOT EDIT\n')]:
        try:_generated_write(st,root,key,rel,text,marker)
        except Exception as exc:warnings.append({'file':rel,'reason':str(exc)})
    return {'accepted_spaces':len(spaces),'rendered_spaces':written,
            'pending_maps':len(list_maps(st,status='pending',limit=1000)),
            'warnings':warnings}
