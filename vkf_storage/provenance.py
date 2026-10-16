"""Lightweight conversation provenance for proposed cognitive relationships.

A shared conversation is NOT evidence that two propositions are equivalent.
Provenance is for retrieval context and review presentation, not authority.
"""
from __future__ import annotations
from collections import defaultdict
from .core import Storage


def source_conversations(st: Storage) -> tuple[dict[str,set[str]], dict[str,set[str]]]:
    candidates: dict[str,set[str]] = defaultdict(set)
    objects: dict[str,set[str]] = defaultdict(set)
    for row in st.db.execute('''SELECT cs.candidate_id, m.conversation_id
        FROM candidate_sources cs JOIN messages m ON m.id=cs.message_id'''):
        candidates[row[0]].add(row[1])
    for row in st.db.execute('''SELECT os.object_id, m.conversation_id
        FROM object_sources os JOIN messages m ON m.id=os.message_id'''):
        objects[row[0]].add(row[1])
    return candidates, objects


def compare_scope(a: set[str], b: set[str]) -> str:
    if not a or not b:
        return 'unknown'
    if not (a & b):
        return 'cross_conversation'
    if a == b:
        return 'same_conversation'
    return 'mixed'


def scope_allowed(scope: str, requested: str) -> bool:
    if requested == 'all':
        return True
    if requested == 'cross':
        return scope in ('cross_conversation','mixed')
    if requested == 'within':
        return scope in ('same_conversation','mixed')
    raise ValueError('invalid retrieval scope')
