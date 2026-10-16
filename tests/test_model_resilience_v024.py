"""Mock upstream 502, malformed completions, retry caps and JSON schemas.
Never use a real paid model or user's original conversations in this suite.
"""
import io
import json
import os
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from vkf_storage.importers import request_model_json
from vkf_storage.core import VKFError, InvalidInput

class FakeResponse:
    status = 200
    headers = {'content-type':'application/json','x-request-id':'safe-1'}
    def __init__(self,text):
        self.raw = json.dumps({'choices':[{'finish_reason':'stop',
             'message':{'content':text}}],'usage':{'completion_tokens':100}}).encode()
    def __enter__(self): return self
    def __exit__(self,*a): return False
    def read(self,n): return self.raw[:n]

class ResilienceTests(unittest.TestCase):
    def run_model(self,side_effect,env=None,task='comparison'):
        defaults={'VKF_API_KEY':'DO-NOT-ECHO-THIS','VKF_CHAT_JSON_MODE':'json_object',
                  'VKF_CHAT_HTTP_RETRIES':'2','VKF_CHAT_JSON_RETRIES':'1',
                  'VKF_CHAT_MAX_OUTPUT_TOKENS':'','VKF_CHAT_TOKEN_FIELD':'max_tokens'}
        defaults.update(env or {})
        with patch.dict(os.environ,defaults), patch('vkf_storage.importers.urlopen',side_effect=side_effect), \
             patch('vkf_storage.importers.time.sleep') as sleep:
            outcome=request_model_json('Return JSON','PRIVATE QUESTIONS ABOUT RESEARCH','test',
                                      'https://example.com/v1',5,max_tokens=2048,task=task)
        return outcome,sleep

    def http_error(self,code,after=None):
        payload=json.dumps({'error':{'type':'upstream_error','message':'PRIVATE PROMPT SECRET'}}).encode()
        headers={'x-request-id':'safe-502'}
        if after is not None:
            headers['Retry-After']=after
        return HTTPError('https://example.com/v1/chat/completions',code,'error',headers,io.BytesIO(payload))

    def test_transient_502_is_retried_then_succeeds(self):
        result,sleep=self.run_model([self.http_error(502),FakeResponse('{"ok":true}')])
        self.assertTrue(result['ok'])
        self.assertEqual(sleep.call_count,1)

    def test_retry_limit_protects_against_long_outage(self):
        calls=[self.http_error(502) for _ in range(3)]
        with patch.dict(os.environ,{'VKF_API_KEY':'DO-NOT-ECHO-THIS',
                 'VKF_CHAT_HTTP_RETRIES':'2','VKF_CHAT_JSON_RETRIES':'0'}),\
             patch('vkf_storage.importers.urlopen',side_effect=calls),\
             patch('vkf_storage.importers.time.sleep') as sleep:
            with self.assertRaisesRegex(VKFError,'status=502') as caught:
                request_model_json('private','private','unit','https://example.com/v1',5)
        self.assertEqual(sleep.call_count,2)
        self.assertIn('attempts=3',str(caught.exception))
        self.assertNotIn('PRIVATE',str(caught.exception))

    def test_rate_limit_long_retry_after_does_not_retry_immediately(self):
        with patch.dict(os.environ,{'VKF_API_KEY':'private', 'VKF_CHAT_HTTP_RETRIES':'3'}),\
             patch('vkf_storage.importers.urlopen',side_effect=self.http_error(429,'60')) as called,\
             patch('vkf_storage.importers.time.sleep') as sleep:
            with self.assertRaisesRegex(VKFError,'status=429'):
                request_model_json('private','private','unit','https://example.com/v1',5)
        self.assertEqual(called.call_count,1)
        sleep.assert_not_called()

    def test_http_400_not_retried(self):
        with patch.dict(os.environ,{'VKF_API_KEY':'private', 'VKF_CHAT_HTTP_RETRIES':'3'}),\
             patch('vkf_storage.importers.urlopen',side_effect=self.http_error(400)) as call,\
             patch('vkf_storage.importers.time.sleep') as sleep:
            with self.assertRaisesRegex(VKFError,'status=400'):
                request_model_json('private','private','unit','https://example.com/v1',5)
        self.assertEqual(call.call_count,1)
        sleep.assert_not_called()

    def test_invalid_json_reprompt_then_valid(self):
        captured=[]
        def fake(req,timeout):
            captured.append(json.loads(req.data))
            return FakeResponse('Reasoning, but no JSON!') if len(captured)==1 else FakeResponse('{"ok":true}')
        result,sleep=self.run_model(fake)
        self.assertTrue(result['ok'])
        self.assertEqual(len(captured),2)
        self.assertIn('IMPORTANT RETRY',captured[1]['messages'][0]['content'])
        self.assertNotIn('Reasoning, but no JSON!',json.dumps(captured[1]))

    def test_invalid_json_can_be_disabled_and_keeps_private_output_out_of_errors(self):
        with patch.dict(os.environ,{'VKF_API_KEY':'private','VKF_CHAT_JSON_RETRIES':'0'}),\
             patch('vkf_storage.importers.urlopen',return_value=FakeResponse('PRIVATE OUTPUT')) as called:
            with self.assertRaisesRegex(VKFError,'json_attempts=1') as caught:
                request_model_json('PRIVATE PROMPT','private','unit','https://example.com/v1',5)
        self.assertEqual(called.call_count,1)
        self.assertNotIn('PRIVATE OUTPUT',str(caught.exception))

    def test_strict_schema_comparison_and_extraction(self):
        captured=[]
        def fake(req,timeout):
            captured.append(json.loads(req.data))
            return FakeResponse('{"candidates":[]}' if len(captured)==1 else '{"decision":"NEW","target_id":null,"rationale":"none"}')
        self.run_model(fake,env={'VKF_CHAT_JSON_MODE':'json_schema'},task='extraction')
        # Same fake state has second call when invoked manually via mocked connection.
        with patch.dict(os.environ,{'VKF_API_KEY':'secret','VKF_CHAT_JSON_MODE':'json_schema'}),\
             patch('vkf_storage.importers.urlopen',side_effect=fake):
            result=request_model_json('JSON','test','unit','https://example.com/v1',5,task='comparison')
        self.assertEqual(result['decision'],'NEW')
        a=captured[0]['response_format']['json_schema']['schema']
        b=captured[1]['response_format']['json_schema']['schema']
        self.assertIn('candidates',a['properties'])
        self.assertIn('decision',b['properties'])
        self.assertTrue(captured[1]['response_format']['json_schema']['strict'])

    def test_invalid_retry_knobs_and_api_schema_guard(self):
        with patch.dict(os.environ,{'VKF_CHAT_HTTP_RETRIES':'99','VKF_API_KEY':'x'}):
            with self.assertRaises(InvalidInput):
                request_model_json('JSON','test','unit','https://example.com/v1',5)
        with patch.dict(os.environ,{'VKF_CHAT_JSON_MODE':'json_schema','VKF_API_KEY':'x'}):
            with self.assertRaises(InvalidInput):
                request_model_json('JSON','test','unit','https://example.com/v1',5,task='unknown')

if __name__=='__main__': unittest.main()
