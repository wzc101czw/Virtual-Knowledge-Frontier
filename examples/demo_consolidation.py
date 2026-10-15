"""Offline, synthetic demo of VKF v0.2 review-before-merge semantics."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vkf_storage import Storage,export_vault
from vkf_storage.consolidation import consolidate_pending


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--vault',type=Path,required=True)
    a=p.parse_args()
    Storage.initialize(a.db)
    with Storage(a.db) as st:
        claims=[
            ('AI World as a Topos','研究用局部重叠与 Monad 组织 AI 的任务世界。'),
            ('AI World as a Topos','研究用局部重叠与 Monad 组织 AI 的任务世界。'),
            ('Research Kernel: global consistency','怎样保证多个 Agent 局部任务的结果可以全局组合？'),
            ('PDF 交付记录','PDF 文件交付记录，下载链接已生成。'),
        ]
        ids=[]
        for i,(title,body) in enumerate(claims):
            convo=st.create_conversation(f'Synthetic discussion {i+1}')
            msg=st.append_message(convo['id'],'user',body)
            ids.append(st.propose_candidate(convo['id'],msg['id'],
                'question' if i==2 else ('knowledge' if i==3 else 'idea'),title,body)['id'])
        review=consolidate_pending(st)
        vault=export_vault(st,a.vault)
        print(json.dumps({'candidate_ids':ids,'reviews':review['proposals'],
                          'formal_objects_count':len(st.list_objects()),
                          'obsidian':vault['consolidation'],'database':str(a.db),'vault':str(a.vault)},
                          ensure_ascii=False,indent=2))


if __name__=='__main__':main()
