"""Lossless extraction coverage audit for v0.2 model-based extraction."""
from __future__ import annotations
from .core import Storage


def report_coverage(st:Storage, conversation_id:str) -> dict:
    conv=st.get_conversation(conversation_id)
    rows=st.db.execute('''SELECT es.message_id,es.start_char,es.end_char
         FROM extraction_segments es JOIN extraction_runs er ON es.extraction_run_id=er.id
         WHERE er.conversation_id=? AND er.prompt_version='llm-extract-v2' AND er.state='completed'
         ORDER BY es.message_id,es.start_char,es.end_char''',(conversation_id,)).fetchall()
    spans={}
    for mid,a,b in rows:
        spans.setdefault(mid,[]).append((a,b))
    missing=[]; total=0;covered=0
    for message in conv['messages']:
        length=len(message['content']);total+=length
        cursor=0
        for a,b in spans.get(message['id'],[]):
            if a>cursor:
                missing.append({'turn':message['turn_index'],'start':cursor,'end':a})
            lo=max(cursor,a)
            if b>lo:
                covered+=b-lo
            cursor=max(cursor,b)
        if cursor<length:
            missing.append({'turn':message['turn_index'],'start':cursor,'end':length})
    return {'conversation_id':conversation_id,'total_chars':total,'covered_chars':covered,
            'coverage':round(covered/total,6) if total else 1.0,
            'complete':not missing,'missing_intervals':missing[:100],
            'scope':'v2 completed LLM extraction segments only; other extraction modes not counted'}
