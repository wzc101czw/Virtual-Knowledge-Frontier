"""Regressions for VKF v0.2.2: real cognitive comparison JSON handling."""
from __future__ import annotations
import contextlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from vkf_storage.core import Storage, VKFError
from vkf_storage.importers import request_model_json
from vkf_storage.consolidation import (
    _comparison_prompt_and_input, _model_compare, consolidate_pending,
)
from vkf_storage.cli import main
from vkf_storage.settings import save_setting


class FakeResponse:
    status = 200
    headers = {'content-type': 'application/json'}
    def __init__(self, reply):
        self.reply = reply
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self, _: int): return self.reply


class JSONComparisonFixTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root/'vkf.db'
        Storage.initialize(self.path)
        self.st = Storage(self.path)
        self.addCleanup(self.st.close)

    def candidate(self, title='Topos 与 Monad', body='范畴论的组合思想启发任务管理'):
        conv = self.st.create_conversation(title)
        msg = self.st.append_message(conv['id'], 'user', body)
        return self.st.propose_candidate(conv['id'], msg['id'], 'idea', title, body)

    def test_comparison_prompt_has_valid_json_example(self):
        candidate = self.candidate()
        prompt, text = _comparison_prompt_and_input(candidate, [
            {'target_id':'old-1', 'kind':'idea', 'title':'Topos', 'body':'局部到整体'}])
        row = prompt.split('Valid example for a new idea:\n', 1)[1].split('\n', 1)[0]
        self.assertEqual(json.loads(row)['target_id'], None)
        self.assertNotIn('null or one supplied target ID', prompt)
        self.assertEqual(json.loads(text)['existing'][0]['id'], 'old-1')
        self.assertIn('untrusted data', prompt)

    def test_comparator_uses_shared_prompt_and_larger_reasoning_budget(self):
        c = self.candidate()
        opt = [{'target_id':'prior','kind':'idea','title':'Topos','body':'任务组合'}]
        with patch('vkf_storage.importers.request_model_json', return_value={
            'decision':'SAME','target_id':'prior','rationale':'完全相同'}) as mocked:
            r = _model_compare(self.st, c, opt, model='gpt6-astra',api_base='https://example.net/v1',timeout=60)
        self.assertEqual(r['decision'],'SAME')
        self.assertEqual(mocked.call_args.kwargs['max_tokens'], 2048)
        self.assertIn('Return ONLY one JSON object',mocked.call_args.args[0])

    def test_json_mode_default_is_enabled_but_can_be_disabled_for_legacy_apis(self):
        captures = []
        def fake(req, timeout):
            captures.append(json.loads(req.data))
            output = {'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]}
            return FakeResponse(json.dumps(output).encode('utf-8'))
        with patch.dict(os.environ, {'VKF_API_KEY':'fake'}, clear=True),\
             patch('vkf_storage.importers.urlopen', side_effect=fake):
            result = request_model_json('Please return JSON','hello','fake','https://example.org/v1',10)
        self.assertTrue(result['ok'])
        self.assertEqual(captures[-1]['response_format'],{'type':'json_object'})
        with patch.dict(os.environ, {'VKF_API_KEY':'fake', 'VKF_CHAT_JSON_MODE':'none'}, clear=True),\
             patch('vkf_storage.importers.urlopen',side_effect=fake):
            result = request_model_json('Please return JSON','hello','fake','https://example.org/v1',10)
        self.assertTrue(result['ok'])
        self.assertNotIn('response_format', captures[-1])

    def test_invalid_json_has_safe_position_but_never_echoes_content(self):
        output = {'choices':[{'finish_reason':'stop','message':{'content':'This is PRIVATE CHAT not valid JSON'}}],
                  'usage':{'completion_tokens':305,'completion_tokens_details':{'reasoning_tokens':175}}}
        with patch.dict(os.environ, {'VKF_API_KEY':'SECRET'}, clear=True),\
             patch('vkf_storage.importers.urlopen',return_value=FakeResponse(json.dumps(output).encode())):
            with self.assertRaises(VKFError) as result:
                request_model_json('PRIVATE PROMPT','PRIVATE CHAT', 'fake','https://example.org/v1',10, max_tokens=500)
        msg = str(result.exception)
        self.assertIn('json_error=Expecting value',msg)
        self.assertIn('line=1, column=1',msg)
        self.assertIn('finish_reason=stop',msg)
        self.assertNotIn('PRIVATE CHAT',msg)
        self.assertNotIn('SECRET',msg)

    def test_one_malformed_response_does_not_abort_entire_batch(self):
        a = self.candidate()
        b = self.candidate()
        c = self.candidate()
        with patch('vkf_storage.consolidation._model_compare', side_effect=[
            VKFError('model output stage: message.content is not valid JSON'),
            {'decision':'NEW', 'target_id':None, 'rationale':'这个观点存在重要的新约束，需要独立保留。'},
        ]) as llm:
            report = consolidate_pending(self.st, mode='llm', model='fake', limit=3)
        self.assertEqual(llm.call_count, 2)
        self.assertEqual(len(report['errors']),1)
        self.assertEqual(report['errors'][0]['candidate_id'],b['id'])
        self.assertEqual(report['processed'],3)
        self.assertEqual(report['reviews_created'],2)
        self.assertEqual(self.st.get_candidate(b['id'])['state'],'pending')
        self.assertEqual(self.st.stats()['table_counts']['candidate_equivalences'],0)
        self.assertTrue(self.st.doctor()['ok'])

    def test_synthetic_comparison_probe_does_not_send_private_data(self):
        save_setting(self.path,'model','unit-model')
        save_setting(self.path,'api_base','http://localhost:9876/v1')
        captured=[]
        def fake(system,text,model,api_base,timeout,**kwargs):
            captured.append((system,text,model,kwargs))
            return {'decision':'RELATED', 'target_id':'synthetic-previous',
                    'rationale':'两个观点存在相似的缓存思路，但一致性条件有差别。'}
        with patch('vkf_storage.importers.request_model_json', side_effect=fake),\
             contextlib.redirect_stdout(io.StringIO()) as console:
            status=main(['--db',str(self.path),'model-probe','--task','compare'])
        self.assertEqual(status,0)
        self.assertTrue(json.loads(console.getvalue())['ok'])
        self.assertEqual(json.loads(console.getvalue())['task'],'compare')
        self.assertIn('synthetic-previous',captured[0][1])
        self.assertNotIn('PRIVATE',captured[0][1])
        self.assertEqual(captured[0][3]['max_tokens'],2048)

    def test_synthetic_probe_rejects_invented_target(self):
        save_setting(self.path,'model','unit-model')
        save_setting(self.path,'api_base','http://localhost:9876/v1')
        with patch('vkf_storage.importers.request_model_json', return_value={
            'decision':'SAME','target_id':'hallucinated','rationale':'模型编造了目标 ID'}),\
             contextlib.redirect_stdout(io.StringIO()) as stdout,\
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            ret=main(['--db',str(self.path),'model-probe','--task','compare'])
        self.assertNotEqual(ret,0)
        self.assertIn('unknown target_id',stderr.getvalue())

if __name__ == '__main__': unittest.main()
