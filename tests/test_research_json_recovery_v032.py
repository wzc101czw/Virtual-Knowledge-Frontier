"""Research JSON recovery: bounded adaptive splitting and privacy-preserving diagnostics."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import tempfile
import unittest
from unittest.mock import patch

from vkf_storage import Storage, VKFError
from vkf_storage.importers import ModelInvalidJSON, request_model_json, _invalid_json_shape
from vkf_storage.research_mapping import (
    map_conversation, checkpoint_progress, _split_parent_segments,
)


class ResearchJSONRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.db = self.tmp / '私人测试 知识库.db'
        Storage.initialize(self.db)
        self.st = Storage(self.db)
        self.addCleanup(self.st.close)
        self.conv = self.st.create_conversation('Research examples only')
        self.conv_id = self.conv['id']
        # 2 parent fragments; the second fragment can be split into smaller parts.
        self.msg = self.st.append_message(self.conv_id, 'user',
            ('Token representation and embodiment research.\n' * 520))
        self.model = 'fake-model'
        self.base = 'https://unit-tests.invalid/v1'

    @staticmethod
    def fake_valid(*args, **kwargs):
        if kwargs['task'] == 'research_global':
            keys=[c['key'] for c in json.loads(kwargs['query'])]
            return {'title':'Research', 'central_question':'Representation transfer?',
                    'goal':'', 'groups':[{'title':'Model integration',
                    'focus':'', 'member_keys':keys}]}
        match=re.search(r'chars=(\d+)\.\.',kwargs['query'])
        assert match
        return {'title':'Research', 'central_question':'Representation transfer?',
                'goal':'', 'contexts':[{'key':'c','title':'Embodiment',
                'focus':'', 'assumptions':[]}],
                'views':[{'key':'v','context_key':'c','kind':'idea',
                          'role':'sub_idea','statement':'Research position '+match.group(1),
                          'attribution':'user','epistemic_status':'hypothesis',
                          'parent_key':None,'evidence_segment_ids':['s0']}],
                'coverage_dimensions':[]}

    def map(self, **kwargs):
        return map_conversation(self.st,self.conv_id,mode='llm',model=self.model,
                                api_base=self.base,timeout=300,**kwargs)

    def test_failure_without_explicit_opt_in_does_not_spawn_extra_calls(self):
        calls=[]
        def fake(*a,**kw):
            calls.append(kw['task'])
            if len(calls)==2:
                raise ModelInvalidJSON('model output stage: message.content is not valid JSON')
            return self.fake_valid(*a,**kw)
        with patch('vkf_storage.research_mapping.model_call',side_effect=fake):
            with self.assertRaisesRegex(VKFError,'fragment 2/2'):
                self.map()
        self.assertEqual(calls,['research_fragment','research_fragment'])
        progress=checkpoint_progress(self.st,self.conv_id,model=self.model,api_base=self.base)
        self.assertEqual(progress['completed_fragment_numbers'],[1])
        self.assertEqual(progress['partial_recovery_fragments'],[])

    def test_split_recovers_bad_original_fragment_without_recomputing_parent_one(self):
        calls=[]
        def fake(*a,**kw):
            calls.append(kw['task'])
            if len(calls)==2:
                raise ModelInvalidJSON('model output stage: message.content is not valid JSON')
            return self.fake_valid(*a,**kw)
        with patch('vkf_storage.research_mapping.model_call',side_effect=fake):
            res=self.map(split_on_invalid_json=True)
        self.assertEqual(res['input_coverage'],1.0)
        self.assertGreaterEqual(calls.count('research_fragment'),4)
        self.assertEqual(calls.count('research_global'),1)
        self.assertEqual(self.st.db.execute('SELECT COUNT(*) FROM research_map_checkpoints').fetchone()[0],0)
        self.assertTrue(self.st.doctor()['ok'])
        self.assertEqual(self.st.get_conversation(self.conv_id)['messages'][0]['content'],
                         'Token representation and embodiment research.\n'*520)

    def test_force_split_known_bad_fragment_skips_original_full_size(self):
        attempted=[]
        def first(*a,**kw):
            attempted.append(kw['query'])
            if len(attempted)==2:
                raise ModelInvalidJSON('original malformed')
            return self.fake_valid(*a,**kw)
        with patch('vkf_storage.research_mapping.model_call',side_effect=first):
            with self.assertRaises(VKFError):
                self.map()
        attempted.clear()
        def recovered(*a,**kw):
            attempted.append(kw['query'])
            return self.fake_valid(*a,**kw)
        with patch('vkf_storage.research_mapping.model_call',side_effect=recovered):
            result=self.map(force_split_fragments=(2,))
        self.assertEqual(result['input_coverage'],1.0)
        fragment_queries=[q for q in attempted if 'Evidence segment IDs' in q]
        self.assertGreaterEqual(len(fragment_queries),2)
        self.assertTrue(all(len(q)<9000 for q in fragment_queries))
        self.assertTrue(self.st.doctor()['ok'])

    def test_split_fragment_requires_valid_fragment(self):
        from vkf_storage.core import InvalidInput
        with self.assertRaises(InvalidInput):
            self.map(force_split_fragments=(3,))
        with self.assertRaises(InvalidInput):
            self.map(force_split_fragments=(0,))

    def test_subfragment_failure_and_resume_without_resending_successful_child(self):
        orig=[]
        def fail_child(*a, **kw):
            if kw['task']=='research_global':
                return self.fake_valid(*a,**kw)
            orig.append(kw['query'])
            if len(orig) == 2:
                raise ModelInvalidJSON('original failed')
            if len(orig) == 4:
                raise ModelInvalidJSON('subfragment failed')
            return self.fake_valid(*a,**kw)
        with patch('vkf_storage.research_mapping.model_call',side_effect=fail_child):
            with self.assertRaisesRegex(VKFError,'recovery subfragment 2/'):
                self.map(split_on_invalid_json=True)
        state=checkpoint_progress(self.st,self.conv_id,model=self.model,api_base=self.base)
        self.assertEqual(state['completed_fragment_numbers'],[1])
        self.assertEqual(state['partial_recovery_fragments'][0]['fragment_number'],2)
        self.assertEqual(state['partial_recovery_fragments'][0]['completed_subfragments'],[1])
        second=[]
        def retry(*a, **kw):
            second.append(kw['query'])
            return self.fake_valid(*a,**kw)
        with patch('vkf_storage.research_mapping.model_call',side_effect=retry):
            completed=self.map(split_on_invalid_json=True)
        # On retry parent and first completed child should not be re-requested.
        self.assertEqual(completed['input_coverage'],1.0)
        self.assertNotIn(orig[0],second)
        self.assertNotIn(orig[1],second)
        self.assertNotIn(orig[2],second)
        self.assertTrue(self.st.doctor()['ok'])
        self.assertEqual(self.st.db.execute('SELECT COUNT(*) FROM research_map_checkpoints').fetchone()[0],0)

    def test_child_split_exact_offsets_and_no_repeated_or_missing_chars(self):
        from vkf_storage.importers import _full_chunks
        messages=self.st.get_conversation(self.conv_id)['messages']
        parent=_full_chunks(messages,budget=13000)[1]
        pieces=_split_parent_segments(messages,parent[3],budget=4000)
        self.assertGreater(len(pieces),1)
        self.assertEqual(sum(b-a for _,spans in pieces for _,a,b in spans),
                         sum(b-a for _,a,b in parent[3]))
        for text, spans in pieces:
            self.assertLessEqual(len(text),4000)
            self.assertTrue(spans)
            self.assertIn('offset ',text)

    def test_metadata_identifies_shape_without_disclosing_text(self):
        self.assertEqual(_invalid_json_shape('<think>private reasoning</think>'), 'reasoning_tag')
        self.assertEqual(_invalid_json_shape('```json\n{invalid}\n```'), 'markdown_fence')
        self.assertEqual(_invalid_json_shape('  {broken'), 'object_prefix')
        self.assertEqual(_invalid_json_shape('Explanation only'), 'prose_or_other')

    def test_debug_opt_in_saves_only_assistant_content_with_restrictive_permissions(self):
        from vkf_storage.importers import _capture_invalid_json
        path = self.tmp / 'debug outside vault'
        path.mkdir()
        secret='PRIVATE RESEARCH CONTENT\n<analysis>debug</analysis>'
        with patch.dict(os.environ, {'VKF_CHAT_DEBUG_DIR':str(path)}):
            name=_capture_invalid_json(secret,'research_fragment')
        self.assertNotIn(str(path),name)
        saved=path / name
        self.assertTrue(saved.is_file())
        data=json.loads(saved.read_text(encoding='utf-8'))
        self.assertEqual(data, {'task':'research_fragment','assistant_content':secret})
        if os.name!='nt':
            self.assertEqual(stat.S_IMODE(saved.stat().st_mode),0o600)

    def test_real_gateway_invalid_json_is_classified_and_retry_status_is_preserved(self):
        class MockResponse:
            status=200
            headers={'content-type':'application/json'}
            def __enter__(self):return self
            def __exit__(self,*a):return False
            def read(self,n):
                result={'choices':[{'message':{'content':'<think>PRIVATE</think>\nnot json'},
                                    'finish_reason':'stop'}],
                        'usage':{'completion_tokens':7871,
                                 'completion_tokens_details':{'reasoning_tokens':2070}}}
                return json.dumps(result).encode('utf-8')
        with patch.dict(os.environ,{'VKF_API_KEY':'NOT_REAL', 'VKF_CHAT_JSON_RETRIES':'0',
                                    'VKF_CHAT_JSON_MODE':'json_object'},clear=False), \
             patch('vkf_storage.importers.urlopen',return_value=MockResponse()):
            with self.assertRaises(ModelInvalidJSON) as raised:
                request_model_json('Return JSON', 'PRIVATE PROMPT', self.model,self.base,15,
                                   max_tokens=6000,task='research_fragment')
        message=str(raised.exception)
        self.assertIn('content_shape=reasoning_tag',message)
        self.assertIn('usage_check=provider_reported_completion_over_budget',message)
        self.assertIn('json_attempts=1',message)
        self.assertNotIn('PRIVATE',message)


if __name__=='__main__':unittest.main()
