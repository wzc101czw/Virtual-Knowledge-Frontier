"""Offline failure injection for research-map timeout recovery (v0.3.1)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from vkf_storage import Storage, VKFError
from vkf_storage.research_mapping import map_conversation, checkpoint_progress
from vkf_storage.settings import load_settings, save_setting
from vkf_storage.importers import request_model_json
from vkf_storage.lifecycle import plan as lifecycle_plan, apply as lifecycle_apply


class ResearchTimeoutRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / '认知 实测.db'
        Storage.initialize(self.path)
        self.st = Storage(self.path)
        self.addCleanup(self.st.close)
        c = self.st.create_conversation('Synthetic research, no user data')
        self.id = c['id']
        # Two complete fragments, derived from the same user message.
        self.msg = self.st.append_message(self.id, 'user', 'Action tokens, physical reasoning.\n' * 590)
        self.model = 'fake-local'
        self.base = 'https://example.invalid/v1'

    @staticmethod
    def fake_response(*a, **kwargs):
        task = kwargs['task']
        if task == 'research_fragment':
            start = re.search(r'chars=(\d+)\.\.', kwargs['query'])
            assert start, 'no chunk source offset in evidence header'
            return {'title': 'Research', 'central_question': 'How to represent action?', 'goal': '',
                    'contexts': [{'key': 'c', 'title': 'Methods', 'focus': 'tokens', 'assumptions': []}],
                    'views': [{'key': 'v', 'context_key': 'c', 'kind': 'idea',
                               'role': 'core_idea', 'statement': 'Action tokens require a representation near char ' + start.group(1),
                               'attribution': 'user', 'epistemic_status': 'hypothesis',
                               'parent_key': None, 'evidence_segment_ids': ['s0']}],
                    'coverage_dimensions': [{'label': 'Tokenization', 'status': 'open', 'note': ''}]}
        if task == 'research_global':
            keys = [entry['key'] for entry in json.loads(kwargs['query'])]
            return {'title': 'Unified Research', 'central_question': 'Action representation?',
                    'goal': '', 'groups': [{'title': 'Methods', 'focus': 'test',
                                             'member_keys': keys}]}
        raise AssertionError('unexpected model task')

    def run_map(self, **kwargs):
        return map_conversation(self.st, self.id, mode='llm', model=self.model,
                                api_base=self.base, timeout=300, **kwargs)

    def test_timeout_second_fragment_then_resume_without_rebilling_first(self):
        progress = checkpoint_progress(self.st, self.id, model=self.model, api_base=self.base)
        self.assertEqual(progress['total_fragments'], 2)
        self.assertEqual(progress['completed_fragment_numbers'], [])
        calls = []
        def first(*a, **kwargs):
            calls.append(kwargs['task'])
            if len(calls) == 2:
                raise VKFError('transport stage: TimeoutError; timeout_seconds=300')
            return self.fake_response(*a, **kwargs)
        with patch('vkf_storage.research_mapping.model_call', side_effect=first):
            with self.assertRaisesRegex(VKFError, 'fragment 2/2') as caught:
                self.run_map()
        self.assertIn('completed_checkpoints=1', str(caught.exception))
        self.assertEqual(calls, ['research_fragment','research_fragment'])
        self.assertEqual(self.st.db.execute('SELECT COUNT(*) FROM research_maps').fetchone()[0], 0)
        before = checkpoint_progress(self.st, self.id, model=self.model, api_base=self.base)
        self.assertEqual(before['completed_fragment_numbers'], [1])
        calls.clear()
        def second(*a, **kwargs):
            calls.append(kwargs['task'])
            return self.fake_response(*a, **kwargs)
        with patch('vkf_storage.research_mapping.model_call', side_effect=second):
            result = self.run_map()
        self.assertEqual(calls, ['research_fragment', 'research_global'])
        self.assertEqual(len(result['plan']['views']), 2)
        self.assertEqual(result['input_coverage'], 1.0)
        self.assertEqual(self.st.db.execute('SELECT COUNT(*) FROM research_map_checkpoints').fetchone()[0], 0)
        self.assertTrue(self.st.doctor()['ok'])

    def test_global_integration_timeout_preserves_every_local_fragment(self):
        def first(*a, **kwargs):
            if kwargs['task'] == 'research_global':
                raise VKFError('transport stage: TimeoutError')
            return self.fake_response(*a, **kwargs)
        with patch('vkf_storage.research_mapping.model_call',side_effect=first):
            with self.assertRaisesRegex(VKFError, 'global integration'):
                self.run_map()
        progress=checkpoint_progress(self.st, self.id, model=self.model, api_base=self.base)
        self.assertEqual(progress['completed_fragment_numbers'], [1,2])
        calls=[]
        def second(*a, **kwargs):
            calls.append(kwargs['task'])
            return self.fake_response(*a, **kwargs)
        with patch('vkf_storage.research_mapping.model_call',side_effect=second):
            result=self.run_map()
        self.assertEqual(calls,['research_global'])
        self.assertEqual(len(result['plan']['views']),2)

    def test_checkpoint_does_not_survive_research_provider_change(self):
        calls=[]
        def fake(*a, **kwargs):
            calls.append(kwargs['task'])
            if len(calls)==2:raise VKFError('synthetic timeout')
            return self.fake_response(*a,**kwargs)
        with patch('vkf_storage.research_mapping.model_call',side_effect=fake):
            with self.assertRaises(VKFError):self.run_map()
        alt=checkpoint_progress(self.st,self.id,model=self.model,api_base='https://different.invalid/v1')
        self.assertEqual(alt['completed_fragment_numbers'],[])
        with patch.dict(os.environ,{'VKF_CHAT_JSON_MODE':'json_schema'}):
            alt=checkpoint_progress(self.st,self.id,model=self.model,api_base=self.base)
        self.assertEqual(alt['completed_fragment_numbers'],[])

    def test_restart_invalidates_checkpoint_without_deleting_source(self):
        count=0
        def stop(*a,**kwargs):
            nonlocal count
            count+=1
            if count==2: raise VKFError('timeout')
            return self.fake_response(*a,**kwargs)
        with patch('vkf_storage.research_mapping.model_call',side_effect=stop):
            with self.assertRaises(VKFError):self.run_map()
        self.assertEqual(checkpoint_progress(self.st,self.id,model=self.model,api_base=self.base)['completed_fragment_numbers'],[1])
        tasks=[]
        def redo(*a,**kwargs):
            tasks.append(kwargs['task'])
            return self.fake_response(*a,**kwargs)
        with patch('vkf_storage.research_mapping.model_call',side_effect=redo):
            self.run_map(restart=True)
        self.assertEqual(tasks,['research_fragment','research_fragment','research_global'])
        self.assertEqual(self.st.get_conversation(self.id)['messages'][0]['content'], 'Action tokens, physical reasoning.\n'*590)

    def test_lifecycle_reset_removes_derived_partial_checkpoints_but_keeps_source(self):
        n=0
        def fake(*a,**kwargs):
            nonlocal n
            n+=1
            if n==2:raise VKFError('timeout')
            return self.fake_response(*a,**kwargs)
        with patch('vkf_storage.research_mapping.model_call',side_effect=fake):
            with self.assertRaises(VKFError):self.run_map()
        review=lifecycle_plan(self.st,'derived')
        self.assertEqual(review['counts']['research_map_checkpoints'],1)
        removed=lifecycle_apply(self.st,'derived',confirm=review['token'])
        self.assertTrue(Path(removed['backup']).is_file())
        self.assertEqual(self.st.db.execute('SELECT COUNT(*) FROM research_map_checkpoints').fetchone()[0],0)
        self.assertEqual(len(self.st.get_conversation(self.id)['messages']),1)

    def test_smaller_chunk_budget_increases_calls_without_losing_characters(self):
        from vkf_storage.importers import _full_chunks
        full=self.st.get_conversation(self.id)['messages']
        normal=_full_chunks(full)
        smaller=_full_chunks(full,budget=6000)
        self.assertGreater(len(smaller),len(normal))
        self.assertEqual(sum(b-a for _,_,_,segments in smaller for _,a,b in segments),
                         len(full[0]['content']))
        self.assertEqual(checkpoint_progress(self.st,self.id,model=self.model,
                         api_base=self.base,chunk_chars=6000)['total_fragments'],len(smaller))

    def test_research_chunk_size_can_be_configured_separately(self):
        from vkf_storage.core import InvalidInput
        self.assertEqual(load_settings(self.path)['research_chunk_chars'],13000)
        save_setting(self.path,'research_chunk_chars',6500)
        self.assertEqual(load_settings(self.path)['research_chunk_chars'],6500)
        with self.assertRaises(InvalidInput):
            save_setting(self.path,'research_chunk_chars',500)

    def test_default_research_timeout_is_300_and_can_be_persisted(self):
        self.assertEqual(load_settings(self.path)['research_timeout'],300)
        save_setting(self.path,'research_timeout',420)
        self.assertEqual(load_settings(self.path)['research_timeout'],420)
        self.assertEqual(load_settings(self.path)['timeout'],60)

    def test_schema_v7_migrates_to_v8_with_pre_migration_backup(self):
        root=Path(__file__).resolve().parents[1]
        previous=Path(self.temp.name)/'legacy.db'
        with sqlite3.connect(previous) as conn:
            for v in range(1,8):
                migration=list((root/'vkf_storage/migrations').glob(f'{v:03d}_*.sql'))
                self.assertEqual(len(migration),1)
                conn.executescript(migration[0].read_text(encoding='utf-8'))
            conn.execute("INSERT INTO conversations(id,source,title) VALUES('keep','other','Preserved conversation')")
        result=Storage.initialize(previous)
        self.assertEqual(result['schema_version'],8)
        self.assertIn('.pre-v8.',result['pre_migration_backup'])
        with sqlite3.connect(result['pre_migration_backup']) as backup:
            self.assertEqual(backup.execute('PRAGMA user_version').fetchone()[0],7)
        with Storage(previous) as upgraded:
            self.assertEqual(upgraded.get_conversation('keep')['title'],'Preserved conversation')
            self.assertTrue(upgraded.doctor()['ok'])

    def test_read_body_timeout_is_identified_without_leaking_response(self):
        class Response:
            status = 200
            headers = {'content-type': 'application/json'}
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size): raise TimeoutError('PRIVATE CONTENT')
        with patch.dict(os.environ, {'VKF_API_KEY':'key','VKF_CHAT_HTTP_RETRIES':'2'}), \
             patch('vkf_storage.importers.urlopen',return_value=Response()) as opened:
            with self.assertRaises(VKFError) as caught:
                request_model_json('system','private','model','https://example.org/v1',7,
                                   task='research_global')
        self.assertEqual(opened.call_count, 1)
        self.assertIn('phase=response_body',str(caught.exception))
        self.assertIn('task=research_global',str(caught.exception))
        self.assertNotIn('PRIVATE CONTENT',str(caught.exception))

    def test_checkpoint_integrity_corruption_is_detected_before_reuse(self):
        from vkf_storage.core import Conflict
        call_count=0
        def fake(*a,**kwargs):
            nonlocal call_count
            call_count+=1
            if call_count==2:raise VKFError('fake network timeout')
            return self.fake_response(*a,**kwargs)
        with patch('vkf_storage.research_mapping.model_call',side_effect=fake):
            with self.assertRaises(VKFError):self.run_map()
        key=self.st.db.execute('SELECT key FROM research_map_checkpoints').fetchone()[0]
        self.st.db.execute("UPDATE research_map_checkpoints SET result_json='{}' WHERE key=?",(key,))
        with self.assertRaisesRegex(Conflict, 'integrity'):
            checkpoint_progress(self.st,self.id,model=self.model,api_base=self.base)

    def test_completed_checkpoint_deleted_by_single_conversation_lifecycle(self):
        fake_count=0
        def fake(*a,**kwargs):
            nonlocal fake_count
            fake_count+=1
            if fake_count==2:raise VKFError('timeout')
            return self.fake_response(*a,**kwargs)
        with patch('vkf_storage.research_mapping.model_call',side_effect=fake):
            with self.assertRaises(VKFError):self.run_map()
        preview=lifecycle_plan(self.st,'conversation',self.id)
        self.assertEqual(preview['counts']['research_map_checkpoints'],1)
        result=lifecycle_apply(self.st,'conversation',conversation_id=self.id,confirm=preview['token'])
        self.assertTrue(result['doctor']['ok'])
        self.assertEqual(self.st.db.execute('SELECT COUNT(*) FROM research_map_checkpoints').fetchone()[0],0)
        self.assertEqual(self.st.db.execute('SELECT COUNT(*) FROM conversations').fetchone()[0],0)

    def test_transport_timeout_not_automatically_repeated_and_stage_reported(self):
        with patch.dict(os.environ,{'VKF_API_KEY':'secret','VKF_CHAT_HTTP_RETRIES':'3'}), \
             patch('vkf_storage.importers.urlopen',side_effect=TimeoutError('PRIVATE DATA')) as urlopen:
            with self.assertRaisesRegex(VKFError,'timeout_seconds=5') as error:
                request_model_json('private','private','synthetic','https://example.org/v1',5,
                                   task='research_fragment')
        urlopen.assert_called_once()
        self.assertIn('phase=connect_or_headers',str(error.exception))
        self.assertNotIn('PRIVATE DATA',str(error.exception))

if __name__ == '__main__':unittest.main()
