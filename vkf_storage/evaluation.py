"""Human-label based consolidation evaluation. Only evaluates explicitly annotated pairs."""
from __future__ import annotations
import json
from pathlib import Path
from .core import Storage,InvalidInput
from .consolidation import retrieve
from .coverage import report_coverage


def evaluate(st:Storage,annotation_file:str|Path) -> dict:
    p=Path(annotation_file)
    data=json.loads(p.read_text(encoding='utf-8'))
    if not isinstance(data,dict):
        raise InvalidInput('evaluation JSON must be an object')
    pairs=data.get('pairs',[])
    noise=data.get('noise',[])
    conversations=data.get('conversations',[])
    if not all(isinstance(x,list) for x in (pairs,noise,conversations)):
        raise InvalidInput('pairs, noise, and conversations must be arrays')
    pair_report=[];tp=fp=fn=tn=found=pos=0
    for item in pairs:
        if not isinstance(item,dict) or type(item.get('same')) is not bool:
            raise InvalidInput('pair must have new, target and boolean same')
        new=item['new'];target=item['target'];gold=item['same']
        st.get_candidate(new)
        row=st.db.execute('SELECT 1 FROM candidates WHERE id=?',(target,)).fetchone()
        if not row:
            st.get_object(target)
        in_pool=any(x['target_id']==target for x in retrieve(st,new,limit=8))
        review=st.db.execute('''SELECT decision,target_candidate_id,target_object_id FROM consolidation_reviews
            WHERE candidate_id=? AND status IN ('pending','applied') ORDER BY created_at DESC,rowid DESC LIMIT 1''',(new,)).fetchone()
        predicted=bool(review and review['decision']=='SAME' and (review['target_candidate_id']==target or review['target_object_id']==target))
        if gold:
            pos+=1;found+=int(in_pool)
        if gold and predicted: tp+=1
        if not gold and predicted: fp+=1
        if gold and not predicted: fn+=1
        if not gold and not predicted: tn+=1
        pair_report.append({'new':new,'target':target,'gold_same':gold,'retrieved_at_8':in_pool,
                            'proposed_same':predicted})
    noise_report=[];np=ntp=nfp=nfn=0
    for item in noise:
        if not isinstance(item,dict) or type(item.get('low_value')) is not bool:
            raise InvalidInput('noise entries require candidate_id and boolean low_value')
        cid=item['candidate_id']; st.get_candidate(cid)
        row=st.db.execute('''SELECT decision FROM consolidation_reviews WHERE candidate_id=?
          AND status IN ('pending','applied') ORDER BY created_at DESC,rowid DESC LIMIT 1''',(cid,)).fetchone()
        proposal=bool(row and row[0]=='DISCARD')
        actual=item['low_value']
        if actual: np+=1
        ntp+=int(actual and proposal)
        nfp+=int(not actual and proposal)
        nfn+=int(actual and not proposal)
        noise_report.append({'candidate_id':cid,'low_value':actual,'suggested_discard':proposal})
    coverage=[report_coverage(st,cid) for cid in conversations]
    metric=lambda n,d: round(n/d,4) if d else None
    return {'scope':'ONLY these human-labelled examples; not global model accuracy',
            'pairs':pair_report,'pair_count':len(pairs),
            'same_precision':metric(tp,tp+fp),'same_recall':metric(tp,tp+fn),
            'retrieval_recall_at_8':metric(found,pos),
            'false_same_proposal_rate':metric(fp,fp+tn),
            'same_confusion':{'TP':tp,'FP':fp,'FN':fn,'TN':tn},
            'noise':noise_report,'noise_precision':metric(ntp,ntp+nfp),
            'noise_recall':metric(ntp,ntp+nfn),
            'coverage':coverage,
            'note':'No automatic semantic consolidation into formal knowledge is performed.'}
