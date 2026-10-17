"""Validated, resumable, per-request research mapping checkpoints.

No model output is stored outside the user's SQLite database. The cache key
covers the exact prompt, model, API base and completion-format knobs; timeout
is deliberately excluded because changing it should not require reprocessing
already completed work. Checkpoints are not human-approved research knowledge.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from .core import Storage, Conflict


def key_for(*, conversation_id: str, stage: str, model: str, api_base: str,
            system: str, query: str, max_tokens: int) -> str:
    knobs = {name: os.environ.get(name, '') for name in (
        'VKF_CHAT_JSON_MODE', 'VKF_CHAT_TOKEN_FIELD', 'VKF_CHAT_OMIT_TEMPERATURE',
        'VKF_CHAT_MAX_OUTPUT_TOKENS')}
    # Keep v0.3.2 cache keys identical when this new knob is not configured.
    effort = os.environ.get('VKF_CHAT_REASONING_EFFORT', '')
    if effort:
        knobs['VKF_CHAT_REASONING_EFFORT'] = effort
    value = [conversation_id, stage, model, api_base.rstrip('/'),
             system, query, max_tokens, knobs]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def get(st: Storage, *, key: str, conversation_id: str) -> dict[str, Any] | None:
    row = st.db.execute('''SELECT result_json,result_sha256 FROM research_map_checkpoints
                            WHERE key=? AND conversation_id=?''', (key, conversation_id)).fetchone()
    if row is None:
        return None
    payload = row['result_json']
    if hashlib.sha256(payload.encode('utf-8')).hexdigest() != row['result_sha256']:
        raise Conflict('saved research mapping checkpoint failed integrity check; '
                       'use research map --restart after backing up the database')
    result = json.loads(payload)
    if not isinstance(result, dict):
        raise Conflict('saved research mapping checkpoint has invalid structure')
    return result


def put(st: Storage, *, key: str, conversation_id: str, stage: str, model: str,
        chunk_index: int, chunks_total: int, result: dict[str, Any]) -> None:
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    sha = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    with st.transaction():
        st.db.execute('''INSERT INTO research_map_checkpoints
           (key,conversation_id,stage,model_id,chunk_index,chunks_total,result_json,result_sha256)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(key) DO NOTHING''',
           (key,conversation_id,stage,model,chunk_index,chunks_total,payload,sha))


def clear_keys(st: Storage, keys: list[str]) -> None:
    if not keys:
        return
    with st.transaction():
        for offset in range(0, len(keys), 400):
            subset = keys[offset:offset+400]
            st.db.execute('DELETE FROM research_map_checkpoints WHERE key IN (' +
                          ','.join('?' for _ in subset) + ')', subset)


def restart(st: Storage, conversation_id: str, model: str) -> int:
    with st.transaction():
        cursor = st.db.execute('''DELETE FROM research_map_checkpoints
             WHERE conversation_id=? AND model_id=?''', (conversation_id, model))
    return cursor.rowcount
