"""Constrained simulated LLM mapping, source coverage, metadata-only audit."""
import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vkf_storage.core import Storage, InvalidInput, Conflict
from vkf_storage.research_mapping import map_conversation
from vkf_storage.research import (get_map,add_feedback,feedback_summary,
    recommend_spaces,save_map,review_plan,apply_map,
    add_research_reference,attach_research_reference,list_research_references)
from vkf_storage.importers import _MODEL_SCHEMAS
from vkf_storage.research_gateway import call


class ResearchLLMTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'research.db'
        Storage.initialize(self.path)
        self.st=Storage(self.path);self.addCleanup(self.st.close)
        self.conv=self.st.create_conversation('具身智能与逆向推理')
        self.user=self.st.append_message(self.conv['id'],'user','我关心动作 Token 与 inverse reasoning。')
        self.ai=self.st.append_message(self.conv['id'],'assistant','提出潜在动作表征，但仍需要验证。')

    def sample(self,who='user'):
        message=self.user if who=='user' else self.ai
        return {'title':'具身智能与逆向推理','central_question':'怎样将推理迁移到具身行动？',
           'goal':'进一步设计实验','contexts':[{'key':'a','title':'行动表示','focus':'控制变量','assumptions':[]}],
           'views':[{'key':'v','context_key':'a','kind':'idea','role':'core_idea',
              'statement':'需要结构化 Action Token','attribution':who,'epistemic_status':'hypothesis',
              'parent_key':None,'evidence':[{'message_id':message['id'],
                'start_char':0,'end_char':len(message['content'])}]}],
           'coverage_dimensions':[{'label':'Action Token','status':'open','note':'验证可执行性'}]}

    def test_supported_structured_schemas(self):
        for task in ('research_fragment','research_global','research_assessment','research_synthesis'):
            schema=_MODEL_SCHEMAS[task]
            self.assertEqual(set(schema['required']),set(schema['properties']))
            self.assertFalse(schema['additionalProperties'])

    def test_model_call_is_audited_and_does_not_store_prompt(self):
        with patch('vkf_storage.research_gateway.request_model_json',return_value={'ok':True}):
            result=call(self.st,system='Confidential system',query='Private discussion',
                        model='test-model',api_base='https://example.org/v1',timeout=10,
                        task='research_fragment',max_tokens=100)
        self.assertTrue(result['ok'])
        row=self.st.db.execute('SELECT * FROM model_calls ORDER BY created_at DESC LIMIT 1').fetchone()
        self.assertEqual(row['state'],'completed')
        self.assertNotIn('Private discussion',str(dict(row)))
        self.assertEqual(len(row['input_fingerprint']),64)

    def test_model_failure_marks_failed_and_preserves_history(self):
        with patch('vkf_storage.research_gateway.request_model_json',side_effect=InvalidInput('bad structured output')):
            with self.assertRaises(InvalidInput):
                call(self.st,system='s',query='t',model='test-model',
                     api_base='https://example.org/v1',timeout=5,
                     task='research_fragment',max_tokens=100)
        self.assertEqual(self.st.db.execute("SELECT state FROM model_calls").fetchone()['state'],'failed')
        self.assertEqual(self.st.db.execute('SELECT COUNT(*) FROM research_maps').fetchone()[0],0)

    def test_model_fragment_source_map_and_granularity_feedback(self):
        local={'title':'具身智能预训练','central_question':'动作表征如何形成？','goal':'设计实验',
          'contexts':[{'key':'local','title':'Action Representation','focus':'物理动作','assumptions':[]}],
          'views':[{'key':'local-view','context_key':'local','kind':'idea','role':'core_idea',
             'statement':'物理世界要形成可执行动作表示','attribution':'user',
             'epistemic_status':'hypothesis','parent_key':None,'evidence_segment_ids':['s0']}],
          'coverage_dimensions':[{'label':'动作表征','status':'open','note':'未验证'}]}
        with patch('vkf_storage.research_mapping.model_call',return_value=local) as fake:
            mapping=map_conversation(self.st,self.conv['id'],mode='llm',model='synthetic',api_base='https://example.org/v1')
        self.assertEqual(fake.call_count,1)
        self.assertEqual(mapping['input_coverage'],1)
        self.assertEqual(len(mapping['plan']['views']),1)
        source=mapping['plan']['views'][0]['evidence'][0]
        self.assertEqual(source['message_id'],self.user['id'])
        add_feedback(self.st,mapping['id'],'too_coarse',note='还缺技术问题',
                     missing=['实验设计'],structure_score=2,question_coverage_score=1,provenance_score=5)
        scored=feedback_summary(self.st)
        self.assertEqual(scored['rubric_scores']['structure_score']['mean'],2)
        self.assertEqual(scored['missing_mentioned']['实验设计'],1)
        self.assertEqual(scored['ratings']['too_coarse'],1)

    def test_multi_chunk_global_synthesis_preserves_every_view(self):
        # Simulate a realistic long user message requiring 2 or more model chunks.
        long_conv=self.st.create_conversation('长篇物理预训练研究')
        message=self.st.append_message(long_conv['id'],'user','反事实训练和动作 Token。\n'*1000)
        calls=[]
        def fake(*a,**kwargs):
            task=kwargs['task'];calls.append(task)
            if task=='research_fragment':
                i=sum(x=='research_fragment' for x in calls)-1
                return {'title':'研究整体','central_question':'怎样进行物理预训练？','goal':'',
                 'contexts':[{'key':'ctx','title':'局部研究情境','focus':'','assumptions':[]}],
                 'views':[{'key':'v','context_key':'ctx','kind':'question','role':'technical_question',
                   'statement':f'技术问题分块 {i}','attribution':'user','epistemic_status':'unknown',
                   'parent_key':None,'evidence_segment_ids':['s0']}],
                 'coverage_dimensions':[{'label':f'研究维度 {i}','status':'open','note':'尚无实验'}]}
            return {'title':'综合研究空间','central_question':'如何对齐训练与动作？','goal':'',
                    'groups':[{'title':'研究核心','focus':'统一整体问题',
                               'member_keys':[f'c{i}-0' for i,x in enumerate(calls) if x=='research_fragment']}]}
        # large 13k+ chunks; global must preserve every cited local view.
        with patch('vkf_storage.research_mapping.model_call',side_effect=fake):
            mapping=map_conversation(self.st,long_conv['id'],mode='llm',model='synthetic')
        self.assertGreaterEqual(calls.count('research_fragment'),2)
        self.assertEqual(calls.count('research_global'),1)
        self.assertEqual(len(mapping['plan']['views']),calls.count('research_fragment'))
        self.assertEqual(len(mapping['plan']['contexts']),1)
        self.assertEqual(mapping['plan']['title'],'综合研究空间')

    def test_exact_repeat_across_chunks_merges_evidence_without_dropping_meaning(self):
        from vkf_storage.research_mapping import _collapse_exact_duplicates
        one={'key':'a','context_key':'group-0','kind':'idea','role':'core_idea',
             'statement':'Action Token representation','attribution':'user',
             'parent_key':None,'evidence':[{'message_id':'mid1','start_char':0,'end_char':10}]}
        two={**one,'key':'b','statement':'action token representation',
             'evidence':[{'message_id':'mid2','start_char':0,'end_char':10}]}
        combined=_collapse_exact_duplicates({'views':[one,two]})
        self.assertEqual(len(combined['views']),1)
        self.assertEqual(len(combined['views'][0]['evidence']),2)

    def test_fragment_unknown_parent_is_rejected(self):
        from vkf_storage.research_mapping import _local_result
        result={'contexts':[{'key':'x','title':'Research','focus':'','assumptions':[]}],
            'views':[{'key':'a','context_key':'x','kind':'idea','role':'sub_idea',
              'statement':'A','attribution':'user','epistemic_status':'hypothesis',
              'parent_key':'nonexistent','evidence_segment_ids':['s0']}]}
        with self.assertRaisesRegex(InvalidInput,'parent'):
            _local_result(result,[(self.user['id'],0,2)],0)

    def test_research_reference_is_not_verified_automatically(self):
        space_map=save_map(self.st,self.conv['id'],{
            **self.sample(),
            'views':[{**self.sample()['views'][0],
                      'role':'reference','kind':'reference','statement':'某外部模型研究需核实'}]
        },mode='manual')
        token=review_plan(self.st,space_map['id'])
        sid=apply_map(self.st,space_map['id'],token=token['token'],
                      expected_revision=1,reason='只确认研究结构')['space_id']
        vid=self.st.db.execute('SELECT id FROM contextual_views WHERE space_id=?',(sid,)).fetchone()['id']
        ref=add_research_reference(self.st,'SAGE-nano',identifier='unverified-work',source_type='paper')
        self.assertEqual(ref['verification_status'],'unverified')
        attached=attach_research_reference(self.st,vid,ref['id'])
        self.assertEqual(attached['reference_id'],ref['id'])
        self.assertTrue(self.st.doctor()['ok'])
        self.assertEqual(len(list_research_references(self.st)),1)

    def test_suggest_existing_space_not_automatically_merge(self):
        source=save_map(self.st,self.conv['id'],self.sample(),mode='manual')
        token=review_plan(self.st,source['id'])
        result=apply_map(self.st,source['id'],token=token['token'],expected_revision=1,reason='reviewed')
        suggested=recommend_spaces(self.st,self.conv['id'])
        self.assertEqual(suggested['suggestions'][0]['space_id'],result['space_id'])
        self.assertEqual(self.st.db.execute('SELECT COUNT(*) FROM research_spaces').fetchone()[0],1)
        self.assertIn('no hit is NOT proof',suggested['warning'])


if __name__=='__main__':unittest.main()
