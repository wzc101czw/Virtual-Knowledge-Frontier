"""v0.2.0 consolidation + configuration + migration regression tests."""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import unittest

from vkf_storage import Storage, Conflict, InvalidInput, NotFound, import_history, extract_conversation, export_vault
from vkf_storage.settings import save_setting,load_settings
from vkf_storage.consolidation import (suggest_review, consolidate_pending, list_reviews,
                                        decide_review,list_topics,retrieve)
from vkf_storage.coverage import report_coverage
from vkf_storage.importers import _full_chunks,MAX_LLM_CHARS


class ConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.path=self.root/'vkf.db'
        Storage.initialize(self.path)
        self.store=Storage(self.path)
        self.addCleanup(self.store.close)

    def make(self, title, body, kind='idea'):
        conv=self.store.create_conversation(title)
        msg=self.store.append_message(conv['id'],'user',body)
        cand=self.store.propose_candidate(conv['id'],msg['id'],kind,title,body)
        return conv,cand

    def test_settings_persist_without_secrets_and_are_isolated(self):
        vault=self.root/'中文 Vault'
        vault.mkdir()
        save_setting(self.path,'vault',str(vault))
        save_setting(self.path,'model','gpt6-astra')
        save_setting(self.path,'api_base','https://example.org/v1')
        save_setting(self.path,'timeout','120')
        config=load_settings(self.path)
        self.assertEqual(config['model'],'gpt6-astra')
        self.assertEqual(config['vault'],str(vault.resolve()))
        self.assertEqual(config['timeout'],120)
        self.assertNotIn('api_key',config)
        self.assertNotIn('gpt6-astra',json.dumps(load_settings(self.root/'another.db')))
        self.assertEqual((self.root/'vkf.db.settings.json').read_text(encoding='utf-8').count('gpt6-astra'),1)
        with self.assertRaises(InvalidInput): save_setting(self.path,'api_key','SECRET')
        with self.assertRaises(InvalidInput): save_setting(self.path,'api_base','http://external.example/v1')
        with self.assertRaises(InvalidInput): save_setting(self.path,'api_base','https://user:pass@example.org/v1')
        with self.assertRaises(InvalidInput): save_setting(self.path,'vault','/missing/vault')
        with self.assertRaises(InvalidInput): save_setting(self.path,'timeout','601')

    def test_migration_v3_creates_backup_preserves_knowledge(self):
        obj=self.store.create_object('knowledge','Prior','previous version record')
        self.store.close()
        import sqlite3
        db=sqlite3.connect(self.path)
        db.execute('PRAGMA foreign_keys=OFF')
        for table in ['extraction_segments','candidate_attributions','consolidation_reviews',
                      'candidate_equivalences','candidate_topics','object_topics','topics']:
            db.execute('DROP TABLE '+table)
        db.execute('PRAGMA user_version=3')
        db.commit();db.close()
        result=Storage.initialize(self.path)
        self.assertEqual(result['schema_version'],5)
        backup=Path(result['pre_migration_backup'])
        self.assertTrue(backup.is_file())
        with sqlite3.connect(backup) as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0],3)
        with Storage(self.path) as new:
            self.assertEqual(new.get_object(obj['id'])['body'],'previous version record')
            self.assertTrue(new.doctor()['ok'])

    def test_lossless_split_long_chinese_emoji_and_offsets(self):
        conv=self.store.create_conversation('long')
        data='标题：'+'A'*MAX_LLM_CHARS+'\n第二段：'+'范畴论🌟'*3600+'END'
        msg=self.store.append_message(conv['id'],'assistant',data)
        messages=self.store.get_conversation(conv['id'])['messages']
        pieces=_full_chunks(messages)
        self.assertGreater(len(pieces),2)
        self.assertTrue(all(len(text)<=MAX_LLM_CHARS for _,_,text,_ in pieces))
        spans=sorted([(a,b) for _,_,_,segments in pieces for mid,a,b in segments if mid==msg['id']])
        cursor=0
        for a,b in spans:
            self.assertEqual(cursor,a)
            cursor=b
        self.assertEqual(cursor,len(data))
        self.assertIn('🌟',data)
        self.assertEqual(report_coverage(self.store,conv['id'])['coverage'],0.0)

    def test_lossless_llm_extraction_persisted_and_idempotent(self):
        conv=self.store.create_conversation('long')
        text='资料🌟'*(MAX_LLM_CHARS//2+30)
        self.store.append_message(conv['id'],'user',text)
        received=[]
        def mock(text,model,api_base,timeout):
            received.append(text)
            return []
        with patch('vkf_storage.importers._llm_suggestions',side_effect=mock):
            first=extract_conversation(self.store,conv['id'],mode='llm',model='fake',api_base='http://localhost:8080/v1')
            second=extract_conversation(self.store,conv['id'],mode='llm',model='fake',api_base='http://localhost:8080/v1')
        self.assertGreater(len(received),1)
        self.assertEqual(second['skipped_existing_runs'],len(received))
        cover=report_coverage(self.store,conv['id'])
        self.assertEqual(cover['coverage'],1.0)
        self.assertTrue(cover['complete'])
        self.assertEqual(cover['covered_chars'],len(text))
        self.assertEqual(self.store.stats()['table_counts']['extraction_segments'],len(received))

    def test_repeated_candidates_are_only_proposed_until_accepted(self):
        a,ca=self.make('Topos 与 Monad 构造 AI 任务世界','使用 Grothendieck Topos 的局部组合描述任务世界，Monad 表示操作过程')
        b,cb=self.make('Topos 与 Monad 构造 AI 任务世界','使用 Grothendieck Topos 的局部组合描述任务世界，Monad 表示操作过程')
        review=suggest_review(self.store,cb['id'])
        self.assertEqual(review['decision'],'SAME')
        self.assertEqual(review['target_candidate_id'],ca['id'])
        self.assertEqual(self.store.stats()['table_counts']['cognitive_objects'],0)
        self.assertEqual(len(self.store.list_candidates()),2)
        decided=decide_review(self.store,review['id'],'accept',reason='same claim, source retained')
        self.assertEqual(decided['status'],'applied')
        self.assertEqual(len(self.store.list_candidates()),1)
        canonical=self.store.get_candidate(ca['id'])
        self.assertEqual(len(canonical['sources']),2)
        obj=self.store.approve_candidate(ca['id'])
        self.assertEqual(self.store.get_candidate(cb['id'])['resolved_object_id'],obj['id'])
        self.assertEqual(self.store.get_candidate(cb['id'])['state'],'merged')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM object_sources WHERE object_id=?',(obj['id'],)).fetchone()[0],2)
        self.assertEqual(self.store.stats()['table_counts']['conversations'],2)
        self.assertTrue(self.store.doctor()['ok'])

    def test_same_topic_not_same_claim(self):
        _,ca=self.make('Cache Mechanism','KV Cache saves key and value tensors for autoregressive attention')
        _,cb=self.make('Cache Mechanism','Disk caches preserve HTTP pages and apply expiration policies')
        review=suggest_review(self.store,cb['id'])
        self.assertNotEqual(review['decision'],'SAME')
        self.assertEqual(self.store.stats()['table_counts']['candidate_equivalences'],0)

    def test_noise_gate_no_automatic_rejection(self):
        _,cand=self.make('中文 PDF 交付记录','完成了报告的PDF文件交付记录和下载链接','knowledge')
        r=suggest_review(self.store,cand['id'])
        self.assertEqual(r['decision'],'DISCARD')
        self.assertEqual(self.store.get_candidate(cand['id'])['state'],'pending')
        decide_review(self.store,r['id'],'accept',reason='administrative log')
        self.assertEqual(self.store.get_candidate(cand['id'])['state'],'rejected')

    def test_understanding_is_not_auto_user_mastery(self):
        _,c=self.make('AI的解释','这是AI提供的解释，未经用户独立复述','understanding')
        with self.assertRaises(InvalidInput):
            self.store.approve_candidate(c['id'])
        obj=self.store.approve_candidate(c['id'],confirm_understanding=True)
        self.assertEqual(obj['kind'],'understanding')
        self.assertEqual(obj['understanding_level'],'provisional')

    def test_idempotent_consolidation_and_topic_vault_review_pages(self):
        _,a=self.make('Topos 与 Monad','以 Topos 构造任务世界')
        _,b=self.make('Topos 与 Monad','以 Topos 构造任务世界')
        first=consolidate_pending(self.store)
        self.assertEqual(first['reviews_created'],2)
        second=consolidate_pending(self.store)
        self.assertEqual(second['reviews_created'],0)
        self.assertEqual(len(list_topics(self.store)),1)
        vault=self.root/'VAULT'
        result=export_vault(self.store,vault)
        self.assertFalse(result['conflicts'],result)
        index=(vault/'VKF'/'01 - Consolidation.md').read_text(encoding='utf-8')
        self.assertIn('Consolidation',index)
        self.assertEqual(len(list((vault/'VKF'/'Consolidation').glob('*.md'))),2)
        self.assertTrue((vault/'VKF'/'Consolidation Inbox.base').exists())
        self.assertEqual(result['consolidation']['topics'],1)
        self.assertEqual(self.store.stats()['table_counts']['relations'],0)

    def test_manual_distinguishes_refinement_from_same_and_invalid_target(self):
        _,a=self.make('Agent Memory','应该借鉴缓存策略')
        _,b=self.make('Agent Memory','应建立缓存失效的可解释约束')
        r=suggest_review(self.store,b['id'],force_decision='REFINES',force_target=a['id'],
                         force_reason='第二条多出了失效语义约束')
        self.assertEqual(r['decision'],'REFINES')
        # No structural merge occurs simply because an agent labels one claim a refinement.
        self.assertEqual(self.store.get_candidate(a['id'])['state'],'pending')
        self.assertEqual(self.store.get_candidate(b['id'])['state'],'pending')
        with self.assertRaises(NotFound):
            suggest_review(self.store,b['id'],force_decision='SAME',force_target='not-a-target',force_reason='test')

    def test_llm_comparator_target_is_constrained_and_cached(self):
        _,a=self.make('局部全局 Topos 模型','局部 gluing 和 overlap 描述世界')
        _,b=self.make('局部全局 Topos 模型','局部 gluing 和 overlap 描述世界')
        with patch('vkf_storage.consolidation._model_compare') as model:
            model.return_value={'decision':'SAME','target_id':a['id'], 'rationale':'两个候选的核心命题完全一致，应当合并来源。'}
            x=suggest_review(self.store,b['id'],mode='llm',model='mock')
            y=suggest_review(self.store,b['id'],mode='llm',model='mock')
        self.assertEqual(model.call_count,1)
        self.assertEqual(x['id'],y['id'])
        self.assertTrue(y['existing'])
        with patch('vkf_storage.consolidation._model_compare',return_value={
            'decision':'SAME','target_id':'invented','rationale':'这是不属于检索候选列表的 ID，不应被接受。'}):
            with self.assertRaises(InvalidInput):
                suggest_review(self.store,b['id'],mode='llm',model='other-model')
        self.assertEqual(self.store.stats()['table_counts']['candidate_equivalences'],0)

    def test_conversation_api_and_saved_vault_cli(self):
        vault=self.root/'My Vault'
        vault.mkdir()
        save_setting(self.path,'vault',str(vault))
        cmd=[sys.executable,'-m','vkf_storage','--db',str(self.path),'bridge','export']
        proc=subprocess.run(cmd,cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertTrue((vault/'VKF'/'00 - Start Here.md').exists())


if __name__=='__main__':
    unittest.main()
