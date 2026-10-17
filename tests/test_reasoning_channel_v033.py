"""Research JSON responses from Chat Completions compatibility gateways.

Never accept chain-of-thought as final material. The first-class final content
must be a complete JSON object, optionally after a CLOSED reasoning envelope.
All requests here are mocked; no user data or external network is involved.
"""
from __future__ import annotations

import hashlib
import json
import os
import unittest
from unittest.mock import patch

from vkf_storage.core import InvalidInput
from vkf_storage.importers import (
    ModelInvalidJSON, _final_json_text, _final_message_content, request_model_json,
)
from vkf_storage.research_checkpoints import key_for


class _Response:
    status = 200
    headers = {'content-type': 'application/json', 'x-request-id': 'req-demo'}

    def __init__(self, body: dict):
        self.body = json.dumps(body, ensure_ascii=False).encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, *ignored):
        return False

    def read(self, n):
        return self.body[:n]


class ReasoningChannelTests(unittest.TestCase):
    def _request(self, content, *, reason='stop', reasoning_content=None, env=None):
        model_message = {'content': content}
        if reasoning_content is not None:
            model_message['reasoning_content'] = reasoning_content
        payload = {'choices': [{'message': model_message, 'finish_reason': reason}],
                   'usage': {'completion_tokens': 10055,
                             'completion_tokens_details': {'reasoning_tokens': 2588}}}
        variables = {'VKF_API_KEY':'SYNTHETIC_ONLY', 'VKF_CHAT_JSON_RETRIES': '0',
                     'VKF_CHAT_JSON_MODE':'json_object', 'VKF_CHAT_TOKEN_FIELD':'max_tokens',
                     'VKF_CHAT_MAX_OUTPUT_TOKENS':'', 'VKF_CHAT_REASONING_EFFORT':''}
        variables.update(env or {})
        with patch.dict(os.environ, variables), \
             patch('vkf_storage.importers.urlopen', return_value=_Response(payload)):
            return request_model_json('Return JSON only', 'SYNTHETIC INPUT',
                                      'unit-model','https://example.org/v1',40,
                                      max_tokens=6000, task='research_fragment')

    def test_closed_think_then_valid_json_is_accepted(self):
        self.assertEqual(self._request('<think>fake private reasoning {"ok":false}</think>\n'
                                       '{"ok":true}'), {'ok':True})

    def test_closed_analysis_then_fenced_json_is_accepted(self):
        text = '<analysis>Not a final answer</analysis>\n```json\n{"ok":true}\n```'
        self.assertTrue(self._request(text)['ok'])

    def test_multiple_closed_envelopes_and_explicit_final(self):
        self.assertTrue(self._request('<think>draft</think><analysis>evaluation</analysis>'
                                      '<final>{"ok":true}</final>')['ok'])

    def test_incomplete_reasoning_envelope_is_never_salvaged(self):
        with self.assertRaises(ModelInvalidJSON) as capture:
            self._request('<think>unclosed reasoning contains {"ok":true}')
        message = str(capture.exception)
        self.assertIn('content_shape=reasoning_tag', message)
        self.assertIn('reasoning_prefix=unclosed', message)
        self.assertIn('final_shape=empty', message)
        self.assertNotIn('unclosed reasoning', message)

    def test_closed_reasoning_without_final_answer_is_not_accepted(self):
        with self.assertRaises(ModelInvalidJSON) as cm:
            self._request('<think>{"ok":true}</think>')
        self.assertIn('reasoning_prefix=closed_without_final', str(cm.exception))

    def test_closed_reasoning_plus_prose_is_still_invalid(self):
        with self.assertRaises(ModelInvalidJSON) as cm:
            self._request('<think>private</think>\nHere are some ideas')
        self.assertIn('final_shape=prose_or_other', str(cm.exception))
        self.assertNotIn('Here are some ideas', str(cm.exception))

    def test_closed_reasoning_plus_malformed_final_json_is_rejected(self):
        with self.assertRaises(ModelInvalidJSON) as cm:
            self._request('<think>notes</think>\n{"ok":}')
        self.assertIn('final_shape=object_prefix', str(cm.exception))
        self.assertIn('reasoning_prefix=closed', str(cm.exception))

    def test_final_json_from_message_with_separate_reasoning_field(self):
        response = self._request('{"ok":true}', reasoning_content='PRIVATE LONG REASONING')
        self.assertTrue(response['ok'])

    def test_part_based_reasoning_is_not_concatenated_into_final(self):
        parts = [
            {'type':'reasoning', 'text':'PRIVATE REASONING'},
            {'type':'text', 'text':'{"ok":true}'},
        ]
        self.assertTrue(self._request(parts)['ok'])
        self.assertEqual(_final_message_content(parts), '{"ok":true}')

    def test_reasoning_only_part_list_is_not_accepted(self):
        with self.assertRaisesRegex(Exception, 'empty message.content'):
            self._request([{'type':'reasoning', 'text':'{"ok":true}'}])

    def test_empty_final_but_separate_reasoning_diagnostic(self):
        with self.assertRaisesRegex(Exception, 'separate_reasoning=true'):
            self._request('', reasoning_content='SECRET')

    def test_unframed_json_in_prose_is_not_extracted(self):
        with self.assertRaises(ModelInvalidJSON):
            self._request('Possible result: {"ok":true}')

    def test_ordinary_json_still_works(self):
        self.assertTrue(self._request('{"ok":true}')['ok'])

    def test_reasoning_effort_is_strictly_opt_in_and_validated(self):
        seen = []
        def fake(req, timeout):
            seen.append(json.loads(req.data))
            return _Response({'choices':[{'message':{'content':'{"ok":true}'},
                                          'finish_reason':'stop'}]})
        base = {'VKF_API_KEY':'SYNTHETIC_ONLY', 'VKF_CHAT_JSON_RETRIES':'0',
                'VKF_CHAT_MAX_OUTPUT_TOKENS':'', 'VKF_CHAT_JSON_MODE':'json_object'}
        with patch.dict(os.environ, dict(base, VKF_CHAT_REASONING_EFFORT='low')), \
             patch('vkf_storage.importers.urlopen', side_effect=fake):
            result = request_model_json('Return JSON','synthetic','unit-model',
                                        'https://example.org/v1',12)
        self.assertTrue(result['ok'])
        self.assertEqual(seen[-1]['reasoning_effort'], 'low')
        with patch.dict(os.environ, dict(base, VKF_CHAT_REASONING_EFFORT='')), \
             patch('vkf_storage.importers.urlopen', side_effect=fake):
            request_model_json('Return JSON','synthetic','unit-model',
                               'https://example.org/v1',12)
        self.assertNotIn('reasoning_effort',seen[-1])
        with patch.dict(os.environ, dict(base, VKF_CHAT_REASONING_EFFORT='aggressive')):
            with self.assertRaises(InvalidInput):
                request_model_json('Return JSON','synthetic','unit-model',
                                   'https://example.org/v1',12)

    def test_cache_key_backward_compatible_when_effort_unset(self):
        keys = ('VKF_CHAT_JSON_MODE','VKF_CHAT_TOKEN_FIELD','VKF_CHAT_OMIT_TEMPERATURE',
                'VKF_CHAT_MAX_OUTPUT_TOKENS')
        args = {'conversation_id':'conv_1', 'stage':'fragment', 'model':'m',
                'api_base':'https://example.org/v1/', 'system':'prompt',
                'query':'queries', 'max_tokens':6000}
        with patch.dict(os.environ, {'VKF_CHAT_REASONING_EFFORT':''}, clear=True):
            expected = hashlib.sha256(json.dumps([
                args['conversation_id'], args['stage'], args['model'],
                args['api_base'].rstrip('/'), args['system'],args['query'],
                args['max_tokens'], {k:'' for k in keys}
            ], ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
            self.assertEqual(key_for(**args), expected)
            with patch.dict(os.environ, {'VKF_CHAT_REASONING_EFFORT':'low'}):
                self.assertNotEqual(key_for(**args), expected)

    def test_parser_does_not_strip_partial_or_unknown_tags(self):
        text,status,shape = _final_json_text('<think>hello<final>{"ok":true}</final>')
        self.assertEqual(text, '')
        self.assertEqual(status, 'unclosed')
        text,status,shape = _final_json_text('<something>HELLO</something>{"ok":true}')
        self.assertEqual(status, 'absent')
        self.assertEqual(shape, 'markup_prefix')


if __name__ == '__main__':
    unittest.main()
