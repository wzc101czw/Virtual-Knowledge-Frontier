"""Destructive actions are opt-in, transactional and never overwrite manual Obsidian edits."""
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from vkf_storage import Storage, Conflict
from vkf_storage.lifecycle import plan, apply, vault_prune
from vkf_storage.obsidian import export_vault
from vkf_storage.consolidation import suggest_review, decide_review


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'知识库.db'
        Storage.initialize(self.path)
        self.st = Storage(self.path)
        self.addCleanup(self.st.close)

    def seed(self, title='缓存是好事', *, conv_title='对话一'):
        conv = self.st.create_conversation(conv_title)
        msg = self.st.append_message(conv['id'], 'user', title)
        cand = self.st.propose_candidate(conv['id'], msg['id'], 'idea', title, '缓存复用计算结果但需要失效规则')
        return conv, msg, cand

    def test_derived_resets_cognition_but_keeps_dialogues_and_backup(self):
        conv, msg, cand = self.seed()
        obj = self.st.approve_candidate(cand['id'])
        q = self.st.create_object('question','如何设置缓存有效期','了解适用范围')
        self.st.add_relation(obj['id'],q['id'],'raises','引发问题')
        info = plan(self.st,'derived')
        self.assertEqual(info['counts']['objects'],2)
        self.assertEqual(info['counts']['conversations'],0)
        with self.assertRaises(Conflict):
            apply(self.st,'derived',confirm='invalid')
        report=apply(self.st,'derived',confirm=info['token'])
        self.assertTrue(Path(report['backup']).is_file())
        self.assertEqual(self.st.stats()['table_counts']['cognitive_objects'],0)
        self.assertEqual(self.st.stats()['table_counts']['candidates'],0)
        self.assertEqual(self.st.stats()['table_counts']['relations'],0)
        self.assertEqual(self.st.get_conversation(conv['id'])['messages'][0]['content'], '缓存是好事')
        self.assertTrue(self.st.doctor()['ok'])
        triggers = {r[0] for r in self.st.db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        self.assertIn('append_only_audit_delete',triggers)
        self.assertIn('append_only_object_versions_delete',triggers)
        # The backup has the prior state and is a working VKF repository.
        with Storage(report['backup']) as prior:
            self.assertEqual(prior.get_object(obj['id'])['id'],obj['id'])
            self.assertTrue(prior.doctor()['ok'])

    def test_delete_scoped_extraction_and_rerun_same_conversation(self):
        conv,msg,cand=self.seed()
        info=plan(self.st,'extraction',conv['id'])
        self.assertEqual(info['counts']['candidates'],1)
        result=apply(self.st,'extraction',conversation_id=conv['id'],confirm=info['token'])
        self.assertTrue(result['doctor']['ok'])
        self.assertEqual(self.st.get_conversation(conv['id'])['id'],conv['id'])
        self.assertEqual(self.st.stats()['table_counts']['extraction_runs'],0)
        fresh=self.st.propose_candidate(conv['id'],msg['id'],'idea','New idea','Another hypothesis')
        self.assertNotEqual(fresh['id'],cand['id'])

    def test_scoped_delete_blocks_approved_and_shared_source(self):
        conv,msg,cand=self.seed()
        self.st.approve_candidate(cand['id'])
        with self.assertRaisesRegex(Conflict,'approved/merged'):
            plan(self.st,'extraction',conv['id'])
        with self.assertRaisesRegex(Conflict,'approved/merged'):
            plan(self.st,'conversation',conv['id'])
        # Independently created object citing this conversation must protect it.
        conv2,msg2,cand2=self.seed('新的思想',conv_title='第二次对话')
        approved=self.st.approve_candidate(cand2['id'])
        conv3,msg3,cand3=self.seed('另一条',conv_title='第三次对话')
        with self.st.transaction():
            self.st.db.execute('INSERT INTO object_sources(object_id,message_id,source_role) VALUES(?,?,?)',
                               (approved['id'],msg3['id'],'support'))
        with self.assertRaisesRegex(Conflict,'evidence used'):
            plan(self.st,'conversation',conv3['id'])

    def test_delete_conversation_and_cross_review_dependents(self):
        c1,m1,a=self.seed('范畴论构建任务空间',conv_title='范畴论 A')
        c2,m2,b=self.seed('范畴论粘合',conv_title='范畴论 B')
        review=suggest_review(self.st,b['id'],force_decision='RELATED',force_target=a['id'],
                              force_reason='local-global idea')
        decide_review(self.st,review['id'],'accept',reason='meaningful')
        p=plan(self.st,'conversation',c1['id'])
        self.assertEqual(p['counts']['candidate_links'],1)
        self.assertEqual(p['counts']['consolidation_reviews'],1)
        output=apply(self.st,'conversation',conversation_id=c1['id'],confirm=p['token'])
        self.assertTrue(output['doctor']['ok'])
        self.assertEqual(self.st.list_conversations()[0]['id'],c2['id'])
        self.assertIsNone(self.st.db.execute('SELECT id FROM candidates WHERE id=?',(a['id'],)).fetchone())
        self.assertEqual(self.st.get_candidate(b['id'])['id'],b['id'])
        self.assertEqual(self.st.stats()['table_counts']['candidate_links'],0)
        self.assertEqual(self.st.stats()['table_counts']['consolidation_reviews'],0)

    def test_token_stale_if_new_candidate_added(self):
        c1,m1,a=self.seed()
        p=plan(self.st,'derived')
        self.st.propose_candidate(c1['id'],m1['id'],'idea','New','New body')
        with self.assertRaisesRegex(Conflict,'token differs'):
            apply(self.st,'derived',confirm=p['token'])
        self.assertFalse(list(Path(self.temp.name).glob('*.before-lifecycle-*.db')))

    def test_failure_mid_delete_rolls_back_all_changes(self):
        self.seed()
        preview=plan(self.st,'derived')
        from vkf_storage import lifecycle
        original=lifecycle._delete_ids
        def fail_at_candidates(store,table,key,ids):
            if table=='candidates':
                raise RuntimeError('simulated interruption')
            return original(store,table,key,ids)
        with patch('vkf_storage.lifecycle._delete_ids',side_effect=fail_at_candidates):
            with self.assertRaisesRegex(RuntimeError,'simulated'):
                apply(self.st,'derived',confirm=preview['token'])
        self.assertEqual(self.st.stats()['table_counts']['candidates'],1)
        self.assertEqual(self.st.stats()['table_counts']['lifecycle_events'],0)
        self.assertTrue(self.st.doctor()['ok'])

    def test_vault_prune_archives_only_unmodified_generated_files(self):
        conv,msg,cand=self.seed()
        obj=self.st.approve_candidate(cand['id'])
        vault=Path(self.temp.name)/'My Vault'
        report=export_vault(self.st,vault)
        self.assertFalse(report['conflicts'])
        old_note=next((vault/'VKF'/'Ideas').glob('*.md'))
        user_note=vault/'my-notes.md'
        user_note.write_text('私人笔记',encoding='utf-8')
        preview=plan(self.st,'derived')
        apply(self.st,'derived',confirm=preview['token'])
        to_prune=vault_prune(self.st,vault)
        self.assertGreater(to_prune['counts']['ready'],0)
        self.assertTrue(old_note.is_file())
        outcome=vault_prune(self.st,vault,apply_changes=True,confirm=to_prune['token'])
        self.assertTrue(outcome['archived'])
        self.assertFalse(old_note.exists())
        self.assertTrue(user_note.is_file())
        self.assertTrue(Path(outcome['archive_dir']).is_dir())
        refresh=export_vault(self.st,vault)
        self.assertTrue(self.st.doctor()['ok'])
        self.assertEqual(refresh['conflicts'],[])

    def test_vault_prune_refuses_modified_note(self):
        _,_,cand=self.seed()
        vault=Path(self.temp.name)/'知识 Vault'
        export_vault(self.st,vault)
        candidate_note=next((vault/'VKF'/'Candidates').glob('*.md'))
        self.assertTrue(candidate_note.is_file())
        p=plan(self.st,'derived')
        apply(self.st,'derived',confirm=p['token'])
        candidate_note.write_text(candidate_note.read_text(encoding='utf-8')+'\n人工编辑',encoding='utf-8')
        inspection=vault_prune(self.st,vault)
        self.assertTrue(any(x['status']=='conflict_modified' for x in inspection['files']))
        outcome=vault_prune(self.st,vault,apply_changes=True,confirm=inspection['token'])
        self.assertTrue(outcome['conflicts'])
        self.assertTrue(candidate_note.is_file())

    def test_full_reset_drops_all_dialogue_and_stores_recoverable_backup(self):
        conv,msg,cand=self.seed('一次实验的描述')
        vault=Path(self.temp.name)/'My Vault'
        export_vault(self.st,vault)
        p=plan(self.st,'all')
        self.assertEqual(p['counts']['conversations'],1)
        self.assertEqual(p['counts']['messages'],1)
        out=apply(self.st,'all',confirm=p['token'])
        self.assertTrue(out['doctor']['ok'])
        for table in ('conversations','messages','candidates','cognitive_objects'):
            self.assertEqual(self.st.stats()['table_counts'][table],0)
        preview=vault_prune(self.st,vault)
        self.assertTrue(any('Conversations' in x['file'] for x in preview['files']))
        vault_prune(self.st,vault,apply_changes=True,confirm=preview['token'])
        report=export_vault(self.st,vault)
        self.assertFalse(report['conflicts'])
        with Storage(out['backup']) as old:
            self.assertEqual(len(old.list_conversations()),1)

    def test_legacy_v5_migration_backs_up_without_loss(self):
        import sqlite3
        from importlib import resources
        db = Path(self.temp.name)/'old-v5.db'
        connection = sqlite3.connect(db)
        try:
            for number,filename in enumerate(('001_initial.sql','002_guardrails.sql',
                '003_bridge_import.sql','004_consolidation.sql','005_provenance_links.sql'),start=1):
                script = resources.files('vkf_storage').joinpath('migrations',filename).read_text(encoding='utf-8')
                connection.executescript(script)
            connection.execute("INSERT INTO conversations(id,source,title) VALUES('conv_old','live','保留历史')")
            connection.commit()
        finally:
            connection.close()
        response=Storage.initialize(db)
        self.assertEqual(response['schema_version'],7)
        self.assertTrue(Path(response['pre_migration_backup']).is_file())
        with Storage(db) as migrated:
            self.assertEqual(migrated.get_conversation('conv_old')['title'],'保留历史')
            self.assertTrue(migrated.doctor()['ok'])

    def test_forced_doctor_failure_rolls_back_before_commit(self):
        self.seed()
        p=plan(self.st,'derived')
        with patch.object(self.st,'doctor',return_value={'ok':False,'problems':['test-only'] }):
            with self.assertRaisesRegex(Conflict,'rolled back'):
                apply(self.st,'derived',confirm=p['token'])
        self.assertEqual(self.st.stats()['table_counts']['candidates'],1)
        self.assertEqual(self.st.stats()['table_counts']['lifecycle_events'],0)
        self.assertTrue(self.st.doctor()['ok'])

    def test_token_invalidated_when_message_changes_without_id_change(self):
        conv,msg,cand=self.seed()
        p=plan(self.st,'all')
        with self.st.transaction():
            self.st.db.execute('UPDATE messages SET content=? WHERE id=?',('修订内容',msg['id']))
        with self.assertRaisesRegex(Conflict,'token differs'):
            apply(self.st,'all',confirm=p['token'])

    def test_cli_plan_and_confirmation(self):
        self.seed()
        import contextlib, io, json
        from vkf_storage.cli import main
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            code=main(['--db',str(self.path),'lifecycle','plan','--scope','derived'])
        self.assertEqual(code,0)
        token=json.loads(stream.getvalue())['token']
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            code=main(['--db',str(self.path),'lifecycle','apply','--scope','derived','--confirm',token])
        self.assertEqual(code,0)
        self.assertTrue(json.loads(stream.getvalue())['doctor']['ok'])

if __name__ == '__main__': unittest.main()
