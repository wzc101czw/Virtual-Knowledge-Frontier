"""Run a safe synthetic v0.3 research workflow, no model API or private data.

Example:
    python examples/demo_research_space.py --db ./demo-research.db --vault ./demo-vault
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vkf_storage.core import Storage
from vkf_storage.research import (save_map,add_feedback,feedback_summary,
                                  review_plan,apply_map,get_space)
from vkf_storage.research_synthesis import assess,frontier
from vkf_storage.obsidian import export_vault


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--vault',type=Path,required=True)
    args=p.parse_args()
    Storage.initialize(args.db)
    with Storage(args.db) as st:
        conv=st.create_conversation('合成示例：具身预训练研究')
        human=st.append_message(conv['id'],'user','我提出物理表示—意图—行动的预训练研究架构。')
        assistant=st.append_message(conv['id'],'assistant','一个待验证子方案是逆向推理；还需要数据与 Action Token 设计。')
        plan={'title':'合成具身预训练研究空间',
              'central_question':'怎样构建可迁移的物理与行动表示？',
              'goal':'提出可核查实验设计',
              'contexts':[{'key':'architecture','title':'总体架构','focus':'意图、物理、行动','assumptions':[]},
                          {'key':'inverse','title':'逆向推理方法','focus':'候选子方案','assumptions':[]}],
              'views':[{'key':'main','context_key':'architecture','kind':'idea','role':'core_idea',
                   'statement':'物理表示—意图—行动预训练框架','attribution':'user',
                   'epistemic_status':'hypothesis','parent_key':None,
                   'evidence':[{'message_id':human['id'],'start_char':0,'end_char':len(human['content'])}]},
                {'key':'sub','context_key':'inverse','kind':'idea','role':'sub_idea',
                   'statement':'用逆向推理扩展物理表示','attribution':'assistant',
                   'epistemic_status':'hypothesis','parent_key':'main',
                   'evidence':[{'message_id':assistant['id'],'start_char':0,'end_char':len(assistant['content'])}]}],
              'coverage_dimensions':[{'label':'Action Token 设计','status':'open',
                   'note':'需要机制与评价数据'}]}
        candidate=save_map(st,conv['id'],plan,mode='manual')
        add_feedback(st,candidate['id'],'balanced',note='合成演示：角色层级适当',
                     structure_score=5,question_coverage_score=4,provenance_score=5)
        preview=review_plan(st,candidate['id'])
        committed=apply_map(st,candidate['id'],token=preview['token'],
                            expected_revision=preview['revision'],reason='synthetic example approved')
        assessments=assess(st,committed['space_id'],mode='heuristic')
        gaps=frontier(st,committed['space_id'])
        vault=export_vault(st,args.vault)
        result={'database':str(args.db),'map_id':candidate['id'],
                'research_space':committed['space_id'],
                'contexts':len(get_space(st,committed['space_id'])['contexts']),
                'views':len(get_space(st,committed['space_id'])['views']),
                'assessments':assessments['assessments'],
                'frontier':gaps['obstructions'],
                'human_feedback':feedback_summary(st),
                'vault_research':vault['research'],
                'doctor':st.doctor()}
        print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
