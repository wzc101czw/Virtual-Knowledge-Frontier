"""Human-reviewed, context-first research models (v0.3.0).

This is an engineering analogy to locality/gluing, NOT a Grothendieck topos.
No pending synthesis can be interpreted as formal user understanding.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .core import Storage, Conflict, InvalidInput, NotFound, _digest, _id, _now, _required

KINDS = {'knowledge','idea','understanding','question','cross_insight','reference'}
ROLES = {'reference','core_idea','sub_idea','alternative_route','mechanism','analogy',
         'assumption','technical_question','experiment','limitation','observation','evidence'}
ATTRIBUTIONS = {'user','assistant','mixed','external','unknown'}
EPISTEMIC = {'hypothesis','reported','supported','disputed','unknown'}
VERDICTS = {'compatible','incompatible','needs_mapping','underdetermined','unknown'}
GRANULARITY = {'too_fragmented','balanced','too_coarse','missing_important'}
OBSTRUCTIONS = {'coverage_gap','compatibility_gap','evidence_gap','translation_gap','synthesis_gap'}


def _clean(value: Any, field: str, *, limit: int = 8000) -> str:
    if not isinstance(value,str) or not value.strip() or len(value)>limit:
        raise InvalidInput(f'{field}: expected nonempty text up to {limit} chars')
    return value.strip()


def _strings(value: Any, field: str, *, limit: int = 40) -> list[str]:
    if not isinstance(value,list) or len(value)>limit:
        raise InvalidInput(f'{field}: expected array of up to {limit} strings')
    return [_clean(item,field,limit=1000) for item in value]


def _message_index(st: Storage, conversation_id: str) -> dict[str,dict]:
    return {m['id']:m for m in st.get_conversation(conversation_id)['messages']}


def validate_plan(st: Storage, conversation_id: str, raw: Any) -> dict:
    """Fail closed on invented source pointers, invalid hierarchies or roles."""
    if not isinstance(raw,dict):
        raise InvalidInput('research plan must be a JSON object')
    plan={k:raw.get(k) for k in ('title','central_question','goal','contexts','views','coverage_dimensions')}
    plan['title']=_clean(plan['title'],'title',limit=180)
    plan['central_question']=_clean(plan['central_question'],'central_question',limit=2000)
    plan['goal']=str(plan['goal'] or '').strip()[:3000]
    contexts=plan['contexts']; views=plan['views']; dimensions=plan['coverage_dimensions'] or []
    if not isinstance(contexts,list) or not 1<=len(contexts)<=50:
        raise InvalidInput('contexts must have 1–50 entries; avoid needless fragmentation')
    if not isinstance(views,list) or not 1<=len(views)<=250:
        raise InvalidInput('views must have 1–250 entries')
    if not isinstance(dimensions,list) or len(dimensions)>80:
        raise InvalidInput('coverage_dimensions must be an array of at most 80')
    ckeys=set(); vkeys=set(); messages=_message_index(st,conversation_id)
    normalized_contexts=[]; normalized_views=[]; normalized_dimensions=[]
    for index,c in enumerate(contexts):
        if not isinstance(c,dict): raise InvalidInput('each context must be an object')
        key=_clean(c.get('key'),'context key',limit=90)
        if key in ckeys: raise InvalidInput('duplicate context key: '+key)
        ckeys.add(key)
        normalized_contexts.append({'key':key,'title':_clean(c.get('title'),'context title',limit=180),
           'focus':str(c.get('focus') or '')[:2500],
           'assumptions':_strings(c.get('assumptions',[]),'assumptions')})
    for v in views:
        if not isinstance(v,dict): raise InvalidInput('each view must be an object')
        key=_clean(v.get('key'),'view key',limit=90)
        if key in vkeys: raise InvalidInput('duplicate view key: '+key)
        vkeys.add(key)
        ck=_clean(v.get('context_key'),'context_key',limit=90)
        if ck not in ckeys: raise InvalidInput('view references unknown context '+ck)
        role=v.get('role'); kind=v.get('kind')
        if role not in ROLES or kind not in KINDS:
            raise InvalidInput('invalid research role or cognitive kind')
        attribution=v.get('attribution','unknown')
        epistemic=v.get('epistemic_status','unknown')
        if attribution not in ATTRIBUTIONS or epistemic not in EPISTEMIC:
            raise InvalidInput('invalid attribution or epistemic status')
        parent=v.get('parent_key')
        if parent is not None and (not isinstance(parent,str) or not parent):
            raise InvalidInput('parent_key must be a key or null')
        sources=v.get('evidence')
        if not isinstance(sources,list) or not sources or len(sources)>60:
            raise InvalidInput('each view needs at least one valid evidence span')
        normalized_sources=[]; seen=set()
        for s in sources:
            if not isinstance(s,dict): raise InvalidInput('evidence must include message_id/start_char/end_char')
            mid=s.get('message_id'); start=s.get('start_char'); end=s.get('end_char')
            if mid not in messages or type(start) is not int or type(end) is not int \
                    or not 0<=start<end<=len(messages[mid]['content']):
                raise InvalidInput(f'invalid evidence span for {key} (must belong to conversation)')
            tup=(mid,start,end)
            if tup not in seen:
                seen.add(tup)
                normalized_sources.append(dict(message_id=mid,start_char=start,end_char=end))
        source_roles={messages[e['message_id']]['role'] for e in normalized_sources}
        if attribution=='user' and 'user' not in source_roles:
            raise InvalidInput('user attribution lacks direct user evidence; AI text is not user endorsement')
        if attribution=='assistant' and 'assistant' not in source_roles:
            raise InvalidInput('assistant attribution lacks assistant evidence')
        if attribution=='mixed' and not {'user','assistant'}.issubset(source_roles):
            raise InvalidInput('mixed attribution requires both user and assistant evidence')
        normalized_views.append(dict(key=key,context_key=ck,kind=kind,role=role,
            statement=_clean(v.get('statement'),'statement',limit=7000),
            attribution=attribution,epistemic_status=epistemic,
            parent_key=parent,evidence=normalized_sources))
    parent_map={v['key']:v['parent_key'] for v in normalized_views}
    for v in normalized_views:
        if v['parent_key'] is not None and v['parent_key'] not in vkeys:
            raise InvalidInput('unknown parent key: '+v['parent_key'])
        visited=set(); node=v['key']
        while node is not None:
            if node in visited: raise InvalidInput('cyclic sub-idea hierarchy')
            visited.add(node); node=parent_map[node]
    for d in dimensions:
        if not isinstance(d,dict): raise InvalidInput('coverage dimension must be an object')
        status=d.get('status','unknown')
        if status not in ('addressed','open','unknown'):
            raise InvalidInput('invalid coverage status')
        normalized_dimensions.append({'label':_clean(d.get('label'),'dimension label',limit=180),
            'status':status,'note':str(d.get('note') or '')[:1500]})
    if len({x['label'].casefold() for x in normalized_dimensions})!=len(normalized_dimensions):
        raise InvalidInput('duplicate coverage dimension labels')
    plan.update(contexts=normalized_contexts,views=normalized_views,
                coverage_dimensions=normalized_dimensions)
    return plan


def _as_map(row: Any) -> dict:
    result=dict(row)
    result['plan']=json.loads(result.pop('plan_json'))
    return result


def save_map(st: Storage, conversation_id: str, plan: dict, *, mode: str, model: str = '',
             target_space_id: str|None=None, coverage: float = 1.0, fingerprint: str|None=None) -> dict:
    normalized=validate_plan(st,conversation_id,plan)
    if mode not in ('heuristic','llm','manual'): raise InvalidInput('invalid mapping mode')
    space_version=None
    if target_space_id:
        space_version=st._one('SELECT revision FROM research_spaces WHERE id=?',(target_space_id,),name='research space')['revision']
    finger=fingerprint or _digest([conversation_id,normalized])
    row=st.db.execute('''SELECT id FROM research_maps WHERE conversation_id=?
        AND target_space_id IS ? AND mode=? AND model_id=? AND content_fingerprint=?
        ORDER BY created_at DESC LIMIT 1''',(conversation_id,target_space_id,mode,model,finger)).fetchone()
    if row: return get_map(st,row['id']) | {'skipped_existing':True}
    new_id=_id('rmap')
    with st.transaction():
        st.db.execute('''INSERT INTO research_maps(id,conversation_id,target_space_id,expected_space_revision,
           mode,model_id,prompt_version,content_fingerprint,input_coverage,plan_json)
           VALUES(?,?,?,?,?,?,?,?,?,?)''',
           (new_id,conversation_id,target_space_id,space_version,mode,model,
            'context-map-v1',finger,coverage,json.dumps(normalized,ensure_ascii=False)))
    return get_map(st,new_id) | {'skipped_existing':False}


def get_map(st: Storage,map_id: str)->dict:
    return _as_map(st._one('SELECT * FROM research_maps WHERE id=?',(map_id,),name='research map'))


def list_maps(st: Storage, status: str='pending',limit: int=100)->list[dict]:
    if status not in ('pending','applied','rejected','all'):raise InvalidInput('invalid map status')
    rows=st.db.execute('''SELECT id,conversation_id,target_space_id,revision,status,mode,created_at,
        input_coverage FROM research_maps '''+("" if status=='all' else 'WHERE status=? ')+
        'ORDER BY created_at DESC,id LIMIT ?', (limit,) if status=='all' else (status,limit)).fetchall()
    return [dict(r) for r in rows]


def revise_map(st:Storage,map_id:str,plan:dict, *, expected_revision:int)->dict:
    row=get_map(st,map_id)
    if row['status']!='pending':raise Conflict('cannot revise decided research map')
    if row['revision']!=expected_revision: raise Conflict('research map version conflict')
    normalized=validate_plan(st,row['conversation_id'],plan)
    with st.transaction():
        st.db.execute('UPDATE research_maps SET plan_json=?,revision=revision+1 WHERE id=?',
                      (json.dumps(normalized,ensure_ascii=False),map_id))
    return get_map(st,map_id)


def review_plan(st:Storage,map_id:str)->dict:
    row=get_map(st,map_id)
    if row['status']!='pending':raise Conflict('research map already decided')
    signature=_digest([row['id'],row['revision'],row['plan'],row['target_space_id'],row['expected_space_revision']])[:24]
    return {'map_id':map_id,'revision':row['revision'],'token':signature,
            'target_space_id':row['target_space_id'],
            'counts':{'contexts':len(row['plan']['contexts']),
                      'views':len(row['plan']['views']),
                      'coverage_dimensions':len(row['plan']['coverage_dimensions'])},
            'title':row['plan']['title'],
            'warning':'Applying accepts the proposed research structure, not the truth of its hypotheses.'}


def _snapshot_space(st:Storage,space_id:str,reason:str)->None:
    space=st._one('SELECT * FROM research_spaces WHERE id=?',(space_id,))
    snapshot={'space':space,
       'contexts':[dict(r) for r in st.db.execute('''SELECT c.* FROM research_contexts c JOIN
          research_space_contexts sc ON sc.context_id=c.id WHERE sc.space_id=? ORDER BY c.id''',(space_id,))],
       'views':[dict(r) for r in st.db.execute('SELECT * FROM contextual_views WHERE space_id=? ORDER BY id',(space_id,))],
       'coverage':[dict(r) for r in st.db.execute('SELECT * FROM coverage_dimensions WHERE space_id=? ORDER BY id',(space_id,))]}
    st.db.execute('INSERT INTO research_space_versions(space_id,revision,snapshot_json,reason) VALUES(?,?,?,?)',
        (space_id,space['revision'],json.dumps(snapshot,ensure_ascii=False),reason))


def apply_map(st:Storage,map_id:str, *, token:str, expected_revision:int, reason:str)->dict:
    _required(reason,'review reason')
    if token!=review_plan(st,map_id)['token']:
        raise Conflict('research map changed since review preview; obtain new token')
    row=get_map(st,map_id)
    if row['revision']!=expected_revision: raise Conflict('map version conflict')
    plan=row['plan']
    with st.transaction():
        space_id=row['target_space_id'] or _id('space')
        if row['target_space_id']:
            old=st._one('SELECT * FROM research_spaces WHERE id=?',(space_id,))
            if old['revision']!=row['expected_space_revision']:
                raise Conflict('research space changed after proposal; map again against latest version')
            # One new conversation must never silently replace the central
            # question/goal of an accepted long-lived research space.
            st.db.execute('''UPDATE research_spaces SET revision=revision+1,
                updated_at=? WHERE id=?''',(_now(),space_id))
        else:
            st.db.execute('INSERT INTO research_spaces(id,title,central_question,goal) VALUES(?,?,?,?)',
                          (space_id,plan['title'],plan['central_question'],plan['goal']))
        ctx_ids={}; view_ids={}
        for ctx in plan['contexts']:
            existing=st.db.execute('''SELECT c.id FROM research_contexts c JOIN research_space_contexts sc
               ON sc.context_id=c.id WHERE sc.space_id=? AND lower(c.title)=lower(?) ORDER BY c.id LIMIT 1''',
               (space_id,ctx['title'])).fetchone()
            context_id=existing['id'] if existing else _id('ctx')
            if not existing:
                st.db.execute('INSERT INTO research_contexts(id,title,focus,assumptions_json) VALUES(?,?,?,?)',
                    (context_id,ctx['title'],ctx['focus'],json.dumps(ctx['assumptions'],ensure_ascii=False)))
            st.db.execute('INSERT OR IGNORE INTO research_space_contexts(space_id,context_id) VALUES(?,?)',
                          (space_id,context_id))
            ctx_ids[ctx['key']]=context_id
        for view in plan['views']:
            ctx_id=ctx_ids[view['context_key']]
            fingerprint=_digest([view['kind'],view['role'],view['statement'],view['attribution'],
                view['epistemic_status'],ctx_id])
            old=st.db.execute('SELECT id FROM contextual_views WHERE space_id=? AND context_id=? AND fingerprint=?',
                              (space_id,ctx_id,fingerprint)).fetchone()
            view_id=old['id'] if old else _id('view')
            if not old:
                st.db.execute('''INSERT INTO contextual_views(id,space_id,context_id,kind,role,statement,
                   attribution,epistemic_status,fingerprint) VALUES(?,?,?,?,?,?,?,?,?)''',
                   (view_id,space_id,ctx_id,view['kind'],view['role'],view['statement'],
                    view['attribution'],view['epistemic_status'],fingerprint))
            view_ids[view['key']]=view_id
            for ev in view['evidence']:
                st.db.execute('''INSERT OR IGNORE INTO view_evidence_spans(view_id,message_id,start_char,end_char)
                   VALUES(?,?,?,?)''',(view_id,ev['message_id'],ev['start_char'],ev['end_char']))
        for view in plan['views']:
            parent=view['parent_key']
            if parent:
                child_id=view_ids[view['key']]; parent_id=view_ids[parent]
                current=st.db.execute('SELECT parent_view_id FROM contextual_views WHERE id=?',(child_id,)).fetchone()
                if current['parent_view_id'] and current['parent_view_id']!=parent_id:
                    raise Conflict('existing sub-idea has another reviewed parent')
                st.db.execute('UPDATE contextual_views SET parent_view_id=? WHERE id=?',(parent_id,child_id))
        for d in plan['coverage_dimensions']:
            st.db.execute('''INSERT INTO coverage_dimensions(id,space_id,label,status,note)
               VALUES(?,?,?,?,?) ON CONFLICT(space_id,label) DO UPDATE SET
               status=excluded.status,note=excluded.note''',
               (_id('dimension'),space_id,d['label'],d['status'],d['note']))
        _snapshot_space(st,space_id,reason)
        st.db.execute('''UPDATE research_maps SET status='applied',reviewed_space_id=?,reviewed_at=? WHERE id=?''',
                      (space_id,_now(),map_id))
    return {'map_id':map_id,'space_id':space_id,'status':'applied',
            'overview_preserved':bool(row['target_space_id']),
            'space_revision':st._one('SELECT revision FROM research_spaces WHERE id=?',(space_id,))['revision'],
            'views_in_proposal':len(plan['views']),
            'warning':'Human review approves the STRUCTURE; AI claims are not formal user Knowledge/Understanding.'}


def reject_map(st:Storage,map_id:str,reason:str)->dict:
    _required(reason,'review reason')
    row=get_map(st,map_id)
    if row['status']!='pending':raise Conflict('research map already decided')
    with st.transaction():
        st.db.execute("UPDATE research_maps SET status='rejected',reviewed_at=? WHERE id=?",(_now(),map_id))
    return {'id':map_id,'status':'rejected','reason':reason}


def list_spaces(st:Storage,limit:int=100)->list[dict]:
    return [dict(r) for r in st.db.execute('SELECT * FROM research_spaces ORDER BY updated_at DESC,id LIMIT ?', (limit,))]


def get_space(st:Storage,space_id:str)->dict:
    space=st._one('SELECT * FROM research_spaces WHERE id=?',(space_id,),name='research space')
    contexts=[dict(r) for r in st.db.execute('''SELECT c.* FROM research_contexts c
       JOIN research_space_contexts sc ON sc.context_id=c.id WHERE sc.space_id=? ORDER BY c.title,c.id''',(space_id,))]
    views=[dict(r) for r in st.db.execute('SELECT * FROM contextual_views WHERE space_id=? ORDER BY id',(space_id,))]
    for v in views:
        v['evidence']=[dict(r) for r in st.db.execute(
            'SELECT message_id,start_char,end_char FROM view_evidence_spans WHERE view_id=? ORDER BY message_id,start_char',(v['id'],))]
    return {'space':space,'contexts':contexts,'views':views,
      'coverage':[dict(r) for r in st.db.execute('SELECT * FROM coverage_dimensions WHERE space_id=? ORDER BY label',(space_id,))],
      'assessments':[dict(r) for r in st.db.execute('SELECT * FROM compatibility_assessments WHERE space_id=? ORDER BY created_at,id',(space_id,))],
      'syntheses':[dict(r) for r in st.db.execute('SELECT * FROM synthesis_proposals WHERE space_id=? ORDER BY created_at,id',(space_id,))],
      'frontiers':[dict(r) for r in st.db.execute('SELECT * FROM frontier_obstructions WHERE space_id=? ORDER BY created_at,id',(space_id,))]}


def add_feedback(st:Storage,map_id:str,granularity:str, *, note:str='',
                 missing:list[str]|None=None,edits:list[dict]|None=None,
                 structure_score:int|None=None,question_coverage_score:int|None=None,
                 provenance_score:int|None=None)->dict:
    if granularity not in GRANULARITY:raise InvalidInput('invalid human granularity rating')
    row=get_map(st,map_id)
    missing=_strings(missing or [],'missing items',limit=80)
    edits=edits or []
    if not isinstance(edits,list) or len(edits)>80 or any(not isinstance(e,dict) for e in edits):
        raise InvalidInput('edits must be an array of action objects')
    for edit in edits:
        if edit.get('action') not in ('group','split','promote','demote','add_question','reassign_role','other'):
            raise InvalidInput('unknown edit action')
    for name,value in [('structure_score',structure_score),
                       ('question_coverage_score',question_coverage_score),
                       ('provenance_score',provenance_score)]:
        if value is not None and (type(value) is not int or not 1<=value<=5):
            raise InvalidInput(f'{name} must be between 1 and 5')
    feedback_id=_id('hfeedback')
    with st.transaction():
        st.db.execute('''INSERT INTO researcher_feedback
           (id,map_id,map_revision,granularity,note,missing_json,edits_json,
            structure_score,question_coverage_score,provenance_score)
           VALUES(?,?,?,?,?,?,?,?,?,?)''',(feedback_id,map_id,row['revision'],granularity,str(note)[:5000],
                json.dumps(missing,ensure_ascii=False),json.dumps(edits,ensure_ascii=False),
                structure_score,question_coverage_score,provenance_score))
    return {'id':feedback_id,'map_id':map_id,'revision':row['revision'],'granularity':granularity,
            'missing':missing,'edits':edits,'structure_score':structure_score,
            'question_coverage_score':question_coverage_score,'provenance_score':provenance_score}


def feedback_summary(st:Storage)->dict:
    rows=[dict(r) for r in st.db.execute('SELECT * FROM researcher_feedback ORDER BY created_at,id')]
    # Rate uses the LATEST human rating per (map,revision). No artificial model grades.
    latest={}
    for r in rows:latest[(r['map_id'],r['map_revision'])]=r
    labels={kind:sum(r['granularity']==kind for r in latest.values()) for kind in sorted(GRANULARITY)}
    n=len(latest)
    missing_counts={}
    for r in latest.values():
        for item in json.loads(r['missing_json']):missing_counts[item]=missing_counts.get(item,0)+1
    scores={}
    for column in ('structure_score','question_coverage_score','provenance_score'):
        values=[row[column] for row in latest.values() if row[column] is not None]
        scores[column]={'rated':len(values),'mean':round(sum(values)/len(values),2) if values else None}
    by_map={}
    for (map_id,rev),row in latest.items():by_map.setdefault(map_id,[]).append((rev,row['granularity']))
    improved=0
    for history in by_map.values():
        history.sort(key=lambda x:x[0])
        if len(history)>=2 and history[0][1]!='balanced' and history[-1][1]=='balanced':improved+=1
    return {'rated_revisions':n,'ratings':labels,
       'improved_maps':improved,'rubric_scores':scores,
       'balanced_rate':round(labels['balanced']/n,4) if n else None,
       'missing_mentioned':dict(sorted(missing_counts.items(),key=lambda a:(-a[1],a[0]))),
       'measurement_note':'Human-reported granularity; not a model accuracy or population estimate.'}


def recommend_spaces(st:Storage,conversation_id:str,limit:int=8)->dict:
    """Conservative lexical discovery; NEVER automatically reuses a space.

    It is not evidence of semantic equivalence and cannot discover all paraphrases.
    """
    import re
    conv=st.get_conversation(conversation_id)
    text=conv['title']+' '+ ' '.join(m['content'][:450] for m in conv['messages'] if m['role']=='user')
    def units(s):
        cjk=re.findall(r'[\u3400-\u9fff]+',s.lower())
        words=re.findall(r'[a-z0-9][a-z0-9_-]{2,}',s.lower())
        return set(words)|{chunk[i:i+2] for chunk in cjk for i in range(len(chunk)-1)}
    tokens=units(text)
    results=[]
    for space in list_spaces(st,limit=1000):
        reference=units(space['title']+' '+space['central_question']+' '+space['goal'])
        overlap=tokens & reference
        if not overlap:continue
        score=round(len(overlap)/max(1,len(reference)),4)
        results.append({'space_id':space['id'],'title':space['title'],
                        'lexical_overlap':score,'shared_units':sorted(overlap)[:12]})
    results.sort(key=lambda r:(-r['lexical_overlap'],r['space_id']))
    return {'conversation_id':conversation_id,'suggestions':results[:limit],
            'warning':'Lexical discovery only: no hit is NOT proof of novelty; no automatic merge.'}


def add_research_reference(st:Storage,title:str,*,identifier:str='',
                           source_type:str='other')->dict:
    """Register external work, not a statement that its claims were verified."""
    title=_clean(title,'reference title',limit=250)
    if source_type not in ('paper','model','dataset','report','other'):
        raise InvalidInput('invalid research reference type')
    identifier=str(identifier or '').strip()
    if len(identifier)>800:raise InvalidInput('reference identifier too long')
    if identifier:
        row=st.db.execute('SELECT * FROM research_references WHERE identifier=?',(identifier,)).fetchone()
        if row:return dict(row)|{'skipped_existing':True}
    ref_id=_id('reference')
    with st.transaction():
        st.db.execute('''INSERT INTO research_references(id,title,identifier,source_type)
          VALUES(?,?,?,?)''',(ref_id,title,identifier,source_type))
    return st._one('SELECT * FROM research_references WHERE id=?',(ref_id,))


def list_research_references(st:Storage,limit:int=100)->list[dict]:
    return [dict(r) for r in st.db.execute('SELECT * FROM research_references ORDER BY title,id LIMIT ?',(limit,))]


def attach_research_reference(st:Storage,view_id:str,reference_id:str)->dict:
    with st.transaction():
        view=st._one('SELECT * FROM contextual_views WHERE id=?',(view_id,),name='contextual view')
        st._one('SELECT id FROM research_references WHERE id=?',(reference_id,),name='research reference')
        if view['kind']!='reference' or view['role']!='reference':
            raise InvalidInput('only an explicitly reviewed research-reference view may attach an external work')
        if view['reference_id'] not in (None,reference_id):
            raise Conflict('view is already linked to a different external reference')
        st.db.execute('UPDATE contextual_views SET reference_id=? WHERE id=?',(reference_id,view_id))
    return {'view_id':view_id,'reference_id':reference_id,'verification':'unverified (until separate source check)'}


def export_feedback(st:Storage,file:Path)->dict:
    """Opt-in export of reviewer annotations, never entire private conversations."""
    rows=[]
    for r in st.db.execute('''SELECT rf.*,m.conversation_id,m.mode,
               json_extract(m.plan_json,'$.title') AS map_title
               FROM researcher_feedback rf JOIN research_maps m ON m.id=rf.map_id
               ORDER BY rf.created_at,rf.id'''):
        rows.append({'id':r['id'],'map_id':r['map_id'],'map_revision':r['map_revision'],
            'map_title':r['map_title'],'granularity':r['granularity'],'note':r['note'],
            'missing':json.loads(r['missing_json']),'edits':json.loads(r['edits_json']),
            'structure_score':r['structure_score'],
            'question_coverage_score':r['question_coverage_score'],
            'provenance_score':r['provenance_score']})
    file=Path(file).expanduser()
    file.parent.mkdir(parents=True,exist_ok=True)
    with file.open('x',encoding='utf-8',newline='\n') as f:
        json.dump({'schema':'vkf-human-feedback-0.3','summary':feedback_summary(st),
                   'reviewer_annotations':rows},f,ensure_ascii=False,indent=2)
    return {'file':str(file),'annotations_exported':len(rows),
            'note':'Review notes may contain private research details; inspect before sharing.'}


def update_space_overview(st:Storage,space_id:str,*,title:str,central_question:str,
                          goal:str,expected_revision:int,reason:str)->dict:
    """Explicit human-directed rewrite of the umbrella research question."""
    title=_clean(title,'research title',limit=180)
    central_question=_clean(central_question,'central question',limit=2000)
    _required(reason,'reason')
    with st.transaction():
        old=st._one('SELECT revision FROM research_spaces WHERE id=?',(space_id,),name='research space')
        if old['revision']!=expected_revision:raise Conflict('stale research space version')
        st.db.execute('''UPDATE research_spaces SET title=?,central_question=?,goal=?,
             revision=revision+1,updated_at=? WHERE id=?''',
             (title,central_question,str(goal or '')[:3000],_now(),space_id))
        _snapshot_space(st,space_id,reason)
    return st._one('SELECT * FROM research_spaces WHERE id=?',(space_id,))


def link_context_to_space(st:Storage,space_id:str,context_id:str,*,
                          expected_revision:int,reason:str)->dict:
    """Deliberate multi-space membership: not a duplicate research note."""
    _required(reason,'reason')
    with st.transaction():
        space=st._one('SELECT revision FROM research_spaces WHERE id=?',(space_id,),name='research space')
        st._one('SELECT id FROM research_contexts WHERE id=?',(context_id,),name='research context')
        if space['revision']!=expected_revision:raise Conflict('stale research space version')
        if st.db.execute('''SELECT 1 FROM research_space_contexts WHERE space_id=? AND context_id=?''',
                         (space_id,context_id)).fetchone():
            raise Conflict('context already belongs to research space')
        st.db.execute('INSERT INTO research_space_contexts(space_id,context_id) VALUES(?,?)',
                      (space_id,context_id))
        st.db.execute('UPDATE research_spaces SET revision=revision+1,updated_at=? WHERE id=?',(_now(),space_id))
        _snapshot_space(st,space_id,reason)
    return {'space_id':space_id,'context_id':context_id,
            'space_revision':expected_revision+1,'status':'linked'}
