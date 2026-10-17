"""v0.2.3 safety tests: conversation provenance and human-review effect."""
from __future__ import annotations
import json
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from vkf_storage import Storage, Conflict, InvalidInput
from vkf_storage.consolidation import (retrieve, suggest_review, decide_review,
    consolidate_pending, list_candidate_links)
from vkf_storage.provenance import compare_scope, scope_allowed
from vkf_storage.obsidian import export_vault

class ProvenanceLinksTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'vkf.db'
        Storage.initialize(self.path)
        self.st=Storage(self.path)
        self.addCleanup(self.st.close)

    def make(self, conversation, title, body, kind='idea'):
        conv=self.st.create_conversation(conversation)
        msg=self.st.append_message(conv['id'],'user',f'{title}\n{body}')
        cand=self.st.propose_candidate(conv['id'],msg['id'],kind,title,body)
        return cand

    def two(self):
        a=self.make('first conversation','最小充分生成','满足正确性与完整性的前提下减少冗余表达')
        b=self.make('second conversation','最小充分生成细化','为实现充分性控制，增加边际效用停止机制以减少冗余表达')
        return a,b

    def test_scope_comparison_sets(self):
        self.assertEqual(compare_scope({'x'},{'x'}),'same_conversation')
        self.assertEqual(compare_scope({'x'},{'y'}),'cross_conversation')
        self.assertEqual(compare_scope({'x','y'},{'x'}),'mixed')
        self.assertEqual(compare_scope(set(),{'y'}),'unknown')
        self.assertTrue(scope_allowed('mixed','cross'))
        self.assertTrue(scope_allowed('mixed','within'))
        self.assertFalse(scope_allowed('same_conversation','cross'))

    def test_retrieve_scope_filters_cross_and_same_conversation(self):
        a,b=self.two()
        source_conv=self.st.db.execute('''SELECT m.conversation_id FROM candidate_sources cs
                  JOIN messages m ON cs.message_id=m.id WHERE cs.candidate_id=?''',(a['id'],)).fetchone()[0]
        source_msg=self.st.db.execute('''SELECT cs.message_id FROM candidate_sources cs
                  WHERE cs.candidate_id=?''',(a['id'],)).fetchone()[0]
        c=self.st.propose_candidate(source_conv,source_msg,'idea','最小充分生成验证','符合正确性与完整性后缩减冗余表达')
        cross=retrieve(self.st,b['id'],scope='cross')
        self.assertIn(a['id'],{x['target_id'] for x in cross})
        self.assertTrue(all(x['source_scope']=='cross_conversation' for x in cross))
        within=retrieve(self.st,c['id'],scope='within')
        self.assertIn(a['id'],{x['target_id'] for x in within})
        self.assertTrue(all(x['source_scope']=='same_conversation' for x in within))
        self.assertNotIn(a['id'],{x['target_id'] for x in retrieve(self.st,c['id'],scope='cross')})

    def test_same_conversation_does_not_inflate_lexical_similarity(self):
        a=self.make('one','量子传感器设计','利用光学干涉测量磁场信号')
        conv=self.st.db.execute('''SELECT m.conversation_id FROM candidate_sources cs
                    JOIN messages m ON m.id=cs.message_id WHERE cs.candidate_id=?''',(a['id'],)).fetchone()[0]
        msg=self.st.db.execute('SELECT message_id FROM candidate_sources WHERE candidate_id=?',(a['id'],)).fetchone()[0]
        b=self.st.propose_candidate(conv,msg,'idea','审美留白偏好','绘画构图应保留适度空白')
        matches=retrieve(self.st,b['id'])
        self.assertNotIn(a['id'],{r['target_id'] for r in matches})

    def test_accepted_refines_creates_provisional_edge_only(self):
        a,b=self.two()
        review=suggest_review(self.st,b['id'],force_decision='REFINES',force_target=a['id'],
                              force_reason='new stopping mechanism',scope='cross')
        self.assertEqual(review['comparison_scope'],'cross_conversation')
        self.assertEqual(len(list_candidate_links(self.st)),0)
        accepted=decide_review(self.st,review['id'],'accept',reason='reviewed claim')
        self.assertEqual(accepted['effect'],'provisional_relation')
        link=list_candidate_links(self.st)[0]
        self.assertEqual(link['kind'],'refines')
        self.assertEqual(link['to_candidate_id'],a['id'])
        self.assertEqual(self.st.stats()['table_counts']['cognitive_objects'],0)
        self.assertEqual(self.st.stats()['table_counts']['relations'],0)
        with self.assertRaises(Conflict):
            decide_review(self.st,review['id'],'accept',reason='again')
        self.assertEqual(len(list_candidate_links(self.st)),1)
        self.assertTrue(self.st.doctor()['ok'])

    def test_related_creates_provisional_link_and_vault_navigation(self):
        a,b=self.two()
        review=suggest_review(self.st,b['id'],force_decision='RELATED',force_target=a['id'],
                              force_reason='same technical area, different claims')
        decide_review(self.st,review['id'],'accept',reason='keep separate')
        vault=Path(self.tmp.name)/'思维 Vault'
        exported=export_vault(self.st,vault)
        self.assertFalse(exported['conflicts'], exported)
        topic_docs=list((vault/'VKF'/'Topics').glob('*.md'))
        self.assertTrue(topic_docs)
        text='\n'.join(x.read_text(encoding='utf-8') for x in topic_docs)
        self.assertIn('Reviewed provisional relationships',text)
        self.assertIn('**related**',text)
        details='\n'.join(x.read_text(encoding='utf-8') for x in (vault/'VKF'/'Consolidation').glob('*.md'))
        self.assertIn('provisional_relation',details)
        self.assertIn('cross_conversation',details)
        self.assertTrue((vault/'VKF'/'01 - Consolidation.md').is_file())

    def test_new_acknowledgement_changes_no_formal_graph(self):
        a=self.make('first','Graph neural net','message passing over graph neighborhoods')
        review=suggest_review(self.st,a['id'])
        self.assertEqual(review['decision'],'NEW')
        result=decide_review(self.st,review['id'],'accept',reason='retain candidate')
        self.assertEqual(result['effect'],'acknowledged_only')
        self.assertEqual(len(list_candidate_links(self.st)),0)
        self.assertEqual(len(self.st.list_candidates()),1)
        self.assertEqual(len(self.st.list_objects()),0)
        result2=consolidate_pending(self.st)
        self.assertEqual(result2['processed'],0)
        self.assertFalse(result2['errors'])

    def test_same_merges_sources_not_a_graph_edge(self):
        a=self.make('A','缓存命题','缓存降低重复计算成本')
        b=self.make('B','缓存命题','缓存降低重复计算成本')
        result=suggest_review(self.st,b['id'])
        self.assertEqual(result['decision'],'SAME')
        committed=decide_review(self.st,result['id'],'accept',reason='same proposition')
        self.assertEqual(committed['effect'],'equivalence')
        self.assertEqual(len(list_candidate_links(self.st)),0)
        self.assertEqual(len(self.st.get_candidate(a['id'])['sources']),2)

    def test_comparison_prompt_receives_provenance_but_no_forced_target(self):
        a,b=self.two()
        response={'decision':'NEW','target_id':None,'rationale':'候选提供独立可探索的概念，词汇相似不是命题等价。'}
        with patch('vkf_storage.consolidation._model_compare',return_value=response) as model:
            review=suggest_review(self.st,b['id'],mode='llm',model='mock',scope='cross')
        self.assertEqual(review['decision'],'NEW')
        options=model.call_args.args[2]
        self.assertEqual(options[0]['source_scope'],'cross_conversation')
        self.assertEqual(review['comparison_scope'],'none')

    def test_question_about_idea_is_related_not_refines(self):
        idea=self.make('dialogue A','最小充分生成','满足正确性与完整性前提下减少生成表达')
        q=self.make('dialogue B','视觉生成如何评价留白','应该如何建立必要留白与冗余的评测框架？',kind='question')
        with patch('vkf_storage.consolidation._model_compare',return_value={
            'decision':'REFINES','target_id':idea['id'],
            'rationale':'提出视觉生成评测问题，以细化最小充分生成框架的操作化方式。'}):
            review=suggest_review(self.st,q['id'],mode='llm',model='fake',scope='cross')
        self.assertEqual(review['decision'],'RELATED')
        self.assertIn('跨认知类型',review['rationale'])
        with self.assertRaises(InvalidInput):
            suggest_review(self.st,q['id'],force_decision='REFINES',force_target=idea['id'],
                           force_reason='manual kind mismatch')

    def test_scope_is_in_signature_and_replaces_old_pending_proposal(self):
        a,b=self.two()
        cross=suggest_review(self.st,b['id'],scope='cross')
        all_scope=suggest_review(self.st,b['id'],scope='all')
        self.assertNotEqual(cross['input_signature'],all_scope['input_signature'])
        self.assertEqual(self.st.db.execute('SELECT status FROM consolidation_reviews WHERE id=?',
                 (cross['id'],)).fetchone()[0],'dismissed')

    def test_invalid_action_rollback_creates_no_provisional_link(self):
        a,b=self.two()
        r=suggest_review(self.st,b['id'],force_decision='REFINES',force_target=a['id'],force_reason='valid')
        with self.assertRaises(InvalidInput):
            decide_review(self.st,r['id'],'accept',reason='review',new_body='not applicable')
        self.assertEqual(len(list_candidate_links(self.st)),0)
        self.assertEqual(self.st.db.execute('SELECT status FROM consolidation_reviews WHERE id=?',(r['id'],)).fetchone()[0], 'pending')

    def test_cli_returns_explicit_effect_and_link(self):
        a,b=self.two()
        r=suggest_review(self.st,b['id'],force_decision='REFINES',force_target=a['id'],force_reason='new mechanism')
        decide_review(self.st,r['id'],'accept',reason='accept')
        cmd=[sys.executable,'-m','vkf_storage','--db',str(self.path),'consolidate','links']
        proc=subprocess.run(cmd,cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(json.loads(proc.stdout)[0]['kind'],'refines')
        cli=[sys.executable,'-m','vkf_storage','--db',str(self.path),'consolidate','run',
             '--scope','cross','--mode','heuristic']
        res=subprocess.run(cli,cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(res.returncode,0,res.stderr)
        self.assertEqual(json.loads(res.stdout)['retrieval_scope'],'cross')

    def test_conflicted_bases_are_not_rewritten_and_path_is_correct(self):
        a,b=self.two()
        suggest_review(self.st,b['id'],force_decision='RELATED',force_target=a['id'],force_reason='test')
        vault=Path(self.tmp.name)/'Vault'
        folder=vault/'VKF'
        folder.mkdir(parents=True)
        index=folder/'Consolidation Inbox.base'
        index.write_text('# user-owned view\n',encoding='utf-8')
        report=export_vault(self.st,vault)
        warnings=report['consolidation']['warnings']
        self.assertTrue(any(x['path']=='VKF/Consolidation Inbox.base' for x in warnings),warnings)
        self.assertEqual(index.read_text(encoding='utf-8'),'# user-owned view\n')
        self.assertTrue((folder/'01 - Consolidation.md').exists())

    def test_v4_upgrade_creates_backup_and_marks_unknown_legacy_effect(self):
        path=Path(self.tmp.name)/'legacy.db'
        # A real v0.2.2 schema is constructed by previous migration scripts in sequence.
        import importlib.resources
        import vkf_storage
        conn=sqlite3.connect(path,isolation_level=None)
        try:
            for n in ['001_initial.sql','002_guardrails.sql','003_bridge_import.sql','004_consolidation.sql']:
                script=importlib.resources.files('vkf_storage').joinpath('migrations',n).read_text(encoding='utf-8')
                conn.executescript('BEGIN IMMEDIATE;\n'+script+'\nCOMMIT;')
            conn.execute('''INSERT INTO conversations(id,title,source) VALUES('c','legacy','other')''')
            # An old applied NEW review may or may not have made a substantive
            # change, so v5 explicitly avoids inventing an 'effect' for it.
            conn.execute('''INSERT INTO extraction_runs
                (id,conversation_id,start_turn,end_turn,model_id,prompt_version,idempotency_key)
                VALUES('e','c',0,0,'model','v4','idempotency-v4')''')
            conn.execute('''INSERT INTO candidates
                (id,extraction_run_id,proposal_index,kind,title,body)
                VALUES('candidate_legacy','e',0,'idea','Old','Historical candidate')''')
            conn.execute('''INSERT INTO consolidation_reviews
                (id,candidate_id,decision,score,rationale,status,policy_version,input_signature)
                VALUES('review_legacy','candidate_legacy','NEW',0,'legacy accepted','applied','v4','sig-v4')''')
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],4)
        finally:
            conn.close()
        result=Storage.initialize(path)
        self.assertEqual(result['schema_version'],7)
        with sqlite3.connect(result['pre_migration_backup']) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],4)
        with Storage(path) as migrated:
            self.assertEqual(migrated.db.execute('SELECT title FROM conversations WHERE id=\'c\'').fetchone()[0],'legacy')
            self.assertTrue(migrated.doctor()['ok'])
            row=migrated.db.execute("SELECT status,effect,comparison_scope FROM consolidation_reviews WHERE id='review_legacy'").fetchone()
            self.assertEqual(tuple(row),('applied','legacy_unknown','unknown'))

if __name__=='__main__': unittest.main()
