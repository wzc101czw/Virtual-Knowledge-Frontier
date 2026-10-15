"""Tests for model response diagnosis, without accessing a real API."""
from __future__ import annotations
import contextlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from vkf_storage.core import InvalidInput, VKFError, Storage
from vkf_storage.importers import request_model_json
from vkf_storage.settings import save_setting
from vkf_storage.cli import main

class MockResponse:
    status = 200
    headers = {'content-type': 'application/json', 'x-request-id': 'req-safe-123'}
    def __init__(self, data):
        self.data = data
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, n): return self.data[:n]

class GatewayTests(unittest.TestCase):
    def call(self, data, env=None, model='unit-model', max_tokens=500):
        if isinstance(data, dict): data = json.dumps(data, ensure_ascii=False).encode()
        settings={'VKF_API_KEY': 'DONT-LOG-THIS-KEY',
                  'VKF_CHAT_TOKEN_FIELD': 'max_tokens',
                  'VKF_CHAT_MAX_OUTPUT_TOKENS': '',
                  'VKF_CHAT_OMIT_TEMPERATURE': '0',
                  'VKF_CHAT_JSON_MODE': 'none'}
        settings.update(env or {})
        with patch.dict(os.environ, settings), patch('vkf_storage.importers.urlopen',return_value=MockResponse(data)):
            return request_model_json('PRIVATE PROMPT','PRIVATE USER CONTENT',model,
                                      'https://example.org/v1',15,max_tokens=max_tokens)
    def choice(self, content, reason='stop', tokens=10, reasoning=0):
        return {'choices':[{'finish_reason':reason,'message':{'content':content}}],
                'usage':{'completion_tokens':tokens,
                         'completion_tokens_details':{'reasoning_tokens':reasoning}}}

    def test_normal_object(self):
        self.assertEqual(self.call(self.choice('{"ok":true}')), {'ok':True})
    def test_markdown_fence(self):
        self.assertEqual(self.call(self.choice('```json\n{"ok":true}\n```')), {'ok':True})
    def test_http_empty_not_confused_with_model_empty(self):
        with self.assertRaisesRegex(VKFError,'HTTP response stage: empty body') as cm:
            self.call(b'')
        self.assertIn('req-safe-123',str(cm.exception))
    def test_http_html_not_reported_as_model_json(self):
        with self.assertRaisesRegex(VKFError,'HTTP response stage: body is not valid JSON'):
            self.call(b'<!doctype html><html>PRIVATE USER CONTENT</html>')
    def test_model_length_empty_reasoning_tokens(self):
        with self.assertRaisesRegex(VKFError, 'model output stage: empty message.content') as cm:
            self.call(self.choice('', reason='length',tokens=500,reasoning=500))
        msg=str(cm.exception)
        self.assertIn('finish_reason=length',msg)
        self.assertIn('reasoning_tokens=500',msg)
        self.assertNotIn('PRIVATE',msg)
        self.assertNotIn('DONT-LOG-THIS-KEY',msg)
    def test_complete_json_but_length_reason_is_rejected(self):
        with self.assertRaisesRegex(VKFError,'incomplete completion'):
            self.call(self.choice('{"ok":true}',reason='length',tokens=500,reasoning=350))
    def test_no_cognitive_value_prompt_requires_object(self):
        from vkf_storage.importers import _SYSTEM
        self.assertIn('{"candidates":[]}', _SYSTEM)
        self.assertNotIn('Return [] when', _SYSTEM)
    def test_model_non_json_text(self):
        with self.assertRaisesRegex(VKFError,'message.content is not valid JSON') as cm:
            self.call(self.choice('Here is PRIVATE USER CONTENT'))
        self.assertNotIn('PRIVATE USER CONTENT',str(cm.exception))
    def test_null_content(self):
        with self.assertRaisesRegex(VKFError,'empty message.content'):
            self.call(self.choice(None))
    def test_refusal(self):
        doc=self.choice(None)
        doc['choices'][0]['message']['refusal']='Cannot comply'
        with self.assertRaisesRegex(VKFError,'refusal present'):
            self.call(doc)
    def test_wrong_schema(self):
        with self.assertRaisesRegex(VKFError,'missing choices\\[0\\]'):
            self.call({'output':[{'content':'hi'}]})
    def test_model_array_not_object(self):
        with self.assertRaisesRegex(VKFError,'expected JSON object'):
            self.call(self.choice('[]'))
    def test_provider_error_inside_success(self):
        with self.assertRaisesRegex(VKFError,'provider returned error type=invalid_request_error'):
            self.call({'error':{'type':'invalid_request_error','message':'PRIVATE USER CONTENT'}})
    def test_body_size_limit(self):
        with self.assertRaisesRegex(VKFError,'exceeds 2000000 bytes'):
            self.call(b'{' + b' ' * 2_000_000 + b'}')
    def test_http_400_reports_code_param_not_echoed_message(self):
        issue={'error': {'type':'invalid_request_error','code':'unsupported_parameter',
                          'param':'max_tokens','message':'PRIVATE USER CONTENT'}}
        error=HTTPError('https://example.org/v1/chat/completions',400,'Bad Request',
                        {'x-request-id':'req-400'}, io.BytesIO(json.dumps(issue).encode()))
        with patch.dict(os.environ, {'VKF_API_KEY':'SECRET'}), patch('vkf_storage.importers.urlopen',side_effect=error):
            with self.assertRaises(VKFError) as cm:
                request_model_json('PRIVATE', 'PRIVATE','unit','https://example.org/v1',15)
        msg=str(cm.exception)
        for expected in ('HTTP stage: status=400','code=unsupported_parameter','param=max_tokens','req-400'):
            self.assertIn(expected,msg)
        self.assertNotIn('PRIVATE',msg)
        self.assertNotIn('SECRET',msg)
    def test_optional_compatibility_settings(self):
        seen=[]
        def fake(req,timeout):
            seen.append(json.loads(req.data))
            return MockResponse(json.dumps(self.choice('{"ok":true}')).encode())
        values={'VKF_API_KEY':'test', 'VKF_CHAT_TOKEN_FIELD':'max_completion_tokens',
                'VKF_CHAT_MAX_OUTPUT_TOKENS':'4096', 'VKF_CHAT_OMIT_TEMPERATURE':'1',
                'VKF_CHAT_JSON_MODE':'json_object'}
        with patch.dict(os.environ,values),patch('vkf_storage.importers.urlopen',side_effect=fake):
            result=request_model_json('Return JSON','hello','reasoning','http://localhost:8123/v1',5)
        self.assertTrue(result['ok'])
        self.assertEqual(seen[0]['max_completion_tokens'],4096)
        self.assertNotIn('max_tokens',seen[0])
        self.assertNotIn('temperature',seen[0])
        self.assertEqual(seen[0]['response_format']['type'],'json_object')
    def test_invalid_knob(self):
        with self.assertRaises(InvalidInput):
            self.call(self.choice('{"ok":true}'), env={'VKF_CHAT_MAX_OUTPUT_TOKENS':'abc'})
        with self.assertRaises(InvalidInput):
            self.call(self.choice('{"ok":true}'), env={'VKF_CHAT_JSON_MODE':'json_schema'})
        with self.assertRaises(InvalidInput):
            self.call(self.choice('{"ok":true}'), max_tokens=63)
        self.assertEqual(self.call(self.choice('{"ok":true}'), max_tokens=64),{'ok':True})
    def test_probe_cli_uses_saved_settings_but_no_chat_data(self):
        with TemporaryDirectory() as temp:
            db=Path(temp)/'vkf.db'
            Storage.initialize(db)
            save_setting(db,'model','unit-model')
            save_setting(db,'api_base','http://localhost:8123/v1')
            seen=[]
            def fake(request,timeout):
                seen.append(json.loads(request.data))
                return MockResponse(json.dumps(self.choice('{"ok":true,"probe":"vkf"}')).encode())
            with patch.dict(os.environ, {'VKF_CHAT_TOKEN_FIELD':'max_tokens','VKF_CHAT_MAX_OUTPUT_TOKENS':'',
                                          'VKF_CHAT_OMIT_TEMPERATURE':'0','VKF_CHAT_JSON_MODE':'none'}), \
                 patch('vkf_storage.importers.urlopen',side_effect=fake), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                return_code=main(['--db',str(db),'model-probe'])
            self.assertEqual(return_code,0)
            data=json.loads(output.getvalue())
            self.assertTrue(data['ok'])
            self.assertEqual(seen[0]['model'],'unit-model')
            self.assertEqual(data['response_keys'],['ok','probe'])
            self.assertNotIn('PRIVATE', json.dumps(seen))

if __name__=='__main__':unittest.main()
