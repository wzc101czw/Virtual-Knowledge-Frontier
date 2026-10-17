"""v0.3.0: context-first research structures, human granularity and source safety."""
import copy
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vkf_storage.core import Storage, InvalidInput, Conflict
from vkf_storage.research import (save_map,get_map,revise_map,review_plan,apply_map,
    list_spaces,get_space,add_feedback,feedback_summary,validate_plan)
from vkf_storage.research_mapping import map_conversation,_local_result,_combine,_apply_grouping
from vkf_storage.research_synthesis import assess,synthesize,create_synthesis,decide,frontier
from vkf_storage.lifecycle import plan as purge_plan,apply as purge_apply
from vkf_storage.obsidian import export_vault

ROOT=Path(__file__).resolve().parents[1]


class ResearchSpaceTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'认知空间.db'
        Storage.initialize(self.path)
        self.st=Storage(self.path);self.addCleanup(self.st.close)
        self.conv=self.st.create_conversation('具身智能预训练头脑风暴')
        self.user=self.st.append_message(self.conv['id'],'user',
            '我设想以意图、物理规律和行动构造预训练架构。如何设计动作 Token 与数据？')
        self.ai=self.st.append_message(self.conv['id'],'assistant',
            '可借用 inverse reasoning，提出反事实轨迹分析作为备选的子想法，但尚未验证。')

    def plan_data(self):
        return {'title':'具身智能可扩展预训练','central_question':'怎样学习可迁移的物理与行动表示？',
        'goal':'通过低成本视频和少量交互形成泛化控制能力',
        'contexts':[
          {'key':'pretrain','title':'视频预训练','focus':'学到物理表示','assumptions':[]},
          {'key':'reason','title':'逆向推断','focus':'因果和反事实轨迹','assumptions':[]},
          {'key':'action','title':'动作 Token','focus':'行动表示与具身控制','assumptions':[]}],
        'views':[
          {'key':'main','context_key':'pretrain','kind':'idea','role':'core_idea',
           'statement':'意图—物理—行动联合架构','attribution':'user','epistemic_status':'hypothesis',
           'parent_key':None,'evidence':[self.ev(self.user)]},
          {'key':'sub','context_key':'reason','kind':'idea','role':'sub_idea',
           'statement':'inverse reasoning 与反事实轨迹','attribution':'assistant','epistemic_status':'hypothesis',
           'parent_key':'main','evidence':[self.ev(self.ai)]},
          {'key':'question','context_key':'action','kind':'question','role':'technical_question',
           'statement':'动作 Token 应如何设计？','attribution':'user','epistemic_status':'unknown',
           'parent_key':None,'evidence':[self.ev(self.user)]}],
        'coverage_dimensions':[
          {'label':'预训练数据','status':'open','note':'需要数据来源和成本分析'},
          {'label':'动作 Token 表征','status':'open','note':'需要跨身体迁移实验'}]}

    @staticmethod
    def ev(message):
        return {'message_id':message['id'],'start_char':0,'end_char':len(message['content'])}

    def save(self,target=None):
        return save_map(self.st,self.conv['id'],self.plan_data(),mode='manual',target_space_id=target)

    def accept(self,proposal):
        p=review_plan(self.st,proposal['id'])
        return apply_map(self.st,proposal['id'],token=p['token'],expected_revision=p['revision'],reason='研究员确认结构')

    def test_research_schema7_and_backup_existing_v6(self):
        self.assertEqual(self.st.db.execute('PRAGMA user_version').fetchone()[0],7)
        self.assertTrue(self.st.doctor()['ok'])
        legacy=Path(self.folder.name)/'old-v6.db'
        with sqlite3.connect(legacy) as c:
            for migration in range(1,7):
                name=list(sorted((ROOT/'vkf_storage/migrations').glob(f'{migration:03d}_*.sql')))[0]
                c.executescript(name.read_text(encoding='utf8'))
            c.execute("INSERT INTO conversations(id,source,title) VALUES('keep','other','保留')")
            c.commit()
        result=Storage.initialize(legacy)
        self.assertEqual(result['schema_version'],7)
        self.assertTrue(Path(result['pre_migration_backup']).is_file())
        with sqlite3.connect(result['pre_migration_backup']) as backup:
            self.assertEqual(backup.execute('PRAGMA user_version').fetchone()[0],6)
        with Storage(legacy) as upgraded:
            self.assertEqual(upgraded.get_conversation('keep')['title'],'保留')
            self.assertTrue(upgraded.doctor()['ok'])

    def test_manual_plan_and_review_commit(self):
        proposal=self.save()
        self.assertEqual(proposal['status'],'pending')
        self.assertEqual(self.st.stats()['table_counts']['research_spaces'],0)
        self.assertTrue(self.st.doctor()['ok'])
        outcome=self.accept(proposal)
        self.assertEqual(outcome['space_revision'],1)
        self.assertEqual(len(get_space(self.st,outcome['space_id'])['contexts']),3)
        self.assertEqual(len(get_space(self.st,outcome['space_id'])['views']),3)
        self.assertEqual(self.st.stats()['table_counts']['cognitive_objects'],0)
        self.assertEqual(self.st.stats()['table_counts']['candidates'],0)
        self.assertTrue(self.st.doctor()['ok'])
        self.assertEqual(self.st.db.execute('SELECT COUNT(*) FROM view_evidence_spans').fetchone()[0],3)
        self.assertEqual(len(list_spaces(self.st)),1)

    def test_human_granularity_and_revision_specific_feedback(self):
        draft=self.save();mid=draft['id']
        add_feedback(self.st,mid,'too_fragmented',note='技术路线应成为一个主架构的子想法',
             missing=['训练数据质量'],edits=[{'action':'group','keys':['pretrain','reason'],'comment':'同一主线'}])
        self.assertEqual(feedback_summary(self.st)['balanced_rate'],0)
        p=draft['plan'];p['title']='具身智能核心研究架构'
        revised=revise_map(self.st,mid,p,expected_revision=1)
        self.assertEqual(revised['revision'],2)
        add_feedback(self.st,mid,'balanced',note='现在粒度合适')
        summary=feedback_summary(self.st)
        self.assertEqual(summary['rated_revisions'],2)
        self.assertEqual(summary['balanced_rate'],0.5)
        self.assertEqual(summary['missing_mentioned']['训练数据质量'],1)
        with self.assertRaises(Conflict):revise_map(self.st,mid,p,expected_revision=1)

    def test_stale_token_and_double_accept(self):
        proposal=self.save();preview=review_plan(self.st,proposal['id'])
        changed=copy.deepcopy(proposal['plan']);changed['goal']='不同的研究目标'
        revise_map(self.st,proposal['id'],changed,expected_revision=1)
        with self.assertRaises(Conflict):
            apply_map(self.st,proposal['id'],token=preview['token'],expected_revision=1,reason='过期')
        self.accept(get_map(self.st,proposal['id']))
        with self.assertRaises(Conflict):review_plan(self.st,proposal['id'])

    def test_origin_roles_cannot_be_forced_by_model(self):
        data=self.plan_data()
        data['views'][1]['attribution']='user'
        with self.assertRaisesRegex(InvalidInput,'user attribution'):
            validate_plan(self.st,self.conv['id'],data)
        data=self.plan_data();data['views'][0]['attribution']='mixed'
        with self.assertRaisesRegex(InvalidInput,'mixed attribution'):
            validate_plan(self.st,self.conv['id'],data)

    def test_reject_invalid_evidence_and_cyclic_hierarchy(self):
        data=self.plan_data();data['views'][0]['evidence'][0]['end_char']=999999
        with self.assertRaisesRegex(InvalidInput,'evidence'):
            validate_plan(self.st,self.conv['id'],data)
        data=self.plan_data();data['views'][0]['parent_key']='sub'
        with self.assertRaisesRegex(InvalidInput,'cyclic'):
            validate_plan(self.st,self.conv['id'],data)
        data=self.plan_data();data['contexts'].append(copy.deepcopy(data['contexts'][0]))
        with self.assertRaisesRegex(InvalidInput,'duplicate context'):
            validate_plan(self.st,self.conv['id'],data)

    def test_space_extension_no_overwrite_of_old_views(self):
        proposal=self.save();first=self.accept(proposal)
        space_id=first['space_id']
        new_conv=self.st.create_conversation('具身智能研究续篇')
        new_user=self.st.append_message(new_conv['id'],'user','我提出对动作表征作独立消融实验。')
        second={
         'title':'具身智能可扩展预训练','central_question':'怎样学习可迁移的物理与行动表示？',
         'goal':'继续研究','contexts':[{'key':'test','title':'实验设计','focus':'独立消融','assumptions':[]}],
         'views':[{'key':'exp','context_key':'test','kind':'idea','role':'experiment','parent_key':None,
            'statement':'对动作表征作独立消融', 'attribution':'user','epistemic_status':'hypothesis',
            'evidence':[self.ev(new_user)]}],
         'coverage_dimensions':[]}
        next_map=save_map(self.st,new_conv['id'],second,mode='manual',target_space_id=space_id)
        next_commit=self.accept(next_map)
        self.assertEqual(next_commit['space_revision'],2)
        self.assertEqual(len(get_space(self.st,space_id)['views']),4)
        self.assertEqual(self.st.db.execute('SELECT COUNT(*) FROM research_space_versions').fetchone()[0],2)
        self.assertTrue(self.st.doctor()['ok'])

    def test_prevent_stale_space_version(self):
        first=self.accept(self.save())
        space_id=first['space_id']
        draft=self.save(target=space_id)
        second=self.save(target=space_id)
        # These are idempotent identical drafts; deliberately change one
        self.assertEqual(draft['id'],second['id'])
        proposed=self.accept(draft)
        self.assertEqual(proposed['space_revision'],2)
        draft_new=self.save(target=space_id)
        self.assertEqual(draft_new['id'],draft['id'])  # repeat is idempotent

    def test_new_conversation_does_not_silently_rewrite_existing_research_overview(self):
        first=self.accept(self.save())
        old=get_space(self.st,first['space_id'])['space']
        newconv=self.st.create_conversation('另一个研究视角')
        newmsg=self.st.append_message(newconv['id'],'user','某个补充的对照实验。')
        plan={'title':'LLM 狭窄的局部总结', 'central_question':'新的较窄问题',
            'goal':'覆盖旧目标的窄范围目标',
            'contexts':[{'key':'c','title':'受控实验','focus':'','assumptions':[]}],
            'views':[{'key':'v','context_key':'c','kind':'idea','role':'experiment',
                      'statement':'新增受控实验方案', 'attribution':'user',
                      'epistemic_status':'hypothesis','parent_key':None,
                      'evidence':[self.ev(newmsg)]}], 'coverage_dimensions':[]}
        draft=save_map(self.st,newconv['id'],plan,mode='manual',target_space_id=first['space_id'])
        self.assertTrue(self.accept(draft)['overview_preserved'])
        now=get_space(self.st,first['space_id'])['space']
        self.assertEqual(now['central_question'],old['central_question'])
        self.assertEqual(now['title'],old['title'])
        from vkf_storage.research import update_space_overview
        updated=update_space_overview(self.st,first['space_id'],title='人工更新的研究空间',
           central_question='新的经审查的总体问题',goal='人工目标',expected_revision=2,reason='研究员明确修订')
        self.assertEqual(updated['revision'],3)
        self.assertEqual(updated['title'],'人工更新的研究空间')
        with self.assertRaises(Conflict):
            update_space_overview(self.st,first['space_id'],title='旧',
                central_question='旧',goal='',expected_revision=2,reason='stale')
        self.assertTrue(self.st.doctor()['ok'])

    def test_context_may_be_shared_across_research_spaces(self):
        from vkf_storage.research import link_context_to_space
        first=self.accept(self.save())['space_id']
        extra=self.st.create_conversation('第二研究领域')
        u=self.st.append_message(extra['id'],'user','复用先前的动作表征局部研究情境。')
        draft=save_map(self.st,extra['id'],{'title':'第二领域','central_question':'怎么迁移？','goal':'',
            'contexts':[{'key':'x','title':'独立情境','focus':'','assumptions':[]}],
            'views':[{'key':'a','context_key':'x','kind':'idea','role':'core_idea',
                      'statement':'迁移架构','attribution':'user','epistemic_status':'hypothesis',
                      'parent_key':None,'evidence':[self.ev(u)]}], 'coverage_dimensions':[]},mode='manual')
        second=self.accept(draft)['space_id']
        shared=get_space(self.st,first)['contexts'][0]['id']
        attached=link_context_to_space(self.st,second,shared,expected_revision=1,
                                     reason='明确保留跨空间局部情境身份')
        self.assertEqual(attached['space_revision'],2)
        self.assertIn(shared,{c['id'] for c in get_space(self.st,second)['contexts']})
        with self.assertRaises(Conflict):
            link_context_to_space(self.st,second,shared,expected_revision=2,reason='duplicate')
        self.assertTrue(self.st.doctor()['ok'])

    def test_assessment_synthesis_and_frontier_are_pending(self):
        space_id=self.accept(self.save())['space_id']
        comparisons=assess(self.st,space_id,mode='heuristic')
        self.assertEqual(len(comparisons['assessments']),3)
        self.assertEqual(comparisons['assessments'][0]['verdict'],'unknown')
        self.assertEqual(synthesize(self.st,space_id,mode='heuristic')['status'],'requires_reasoning')
        views=get_space(self.st,space_id)['views']
        ids=[next(v['id'] for v in views if v['context_id']==c['id'])
             for c in get_space(self.st,space_id)['contexts'][:2]]
        result=create_synthesis(self.st,space_id,{
            'title':'预训练与逆向推理的可能联系','mechanism':'待验证的多情境假设',
            'member_view_ids':ids,'assumptions':['假设有可靠物理表征'],
            'limitations':['无法从类比推出真实性'],'validation':'通过可控消融测试'})
        self.assertEqual(result['status'],'pending')
        self.assertEqual(self.st.stats()['kinds'],{})
        decide(self.st,'synthesis',result['id'],'accept','只认可此研究综合方向')
        self.assertEqual(self.st.stats()['kinds'],{})
        gaps=frontier(self.st,space_id)['obstructions']
        self.assertEqual(len(gaps),2)
        self.assertTrue(self.st.doctor()['ok'])

    def test_synthesis_requires_multiple_contexts(self):
        space_id=self.accept(self.save())['space_id']
        view=get_space(self.st,space_id)['views'][0]['id']
        with self.assertRaisesRegex(InvalidInput,'distinct'):
            create_synthesis(self.st,space_id,{'title':'伪综合','mechanism':'伪机制',
                'member_view_ids':[view,view]})

    def test_mapping_heuristic_is_explicitly_low_confidence(self):
        report=map_conversation(self.st,self.conv['id'],mode='heuristic')
        self.assertEqual(report['input_coverage'],1)
        self.assertEqual(report['mode'],'heuristic')
        self.assertEqual(len(report['plan']['views']),2)
        self.assertEqual(map_conversation(self.st,self.conv['id'],mode='heuristic')['skipped_existing'],True)

    def test_local_resolves_authoritative_evidence_segments(self):
        result={'contexts':[{'key':'a','title':'训练','focus':'','assumptions':[]}],
            'views':[{'key':'x','context_key':'a','kind':'idea','role':'core_idea',
                      'statement':'观点','attribution':'user','epistemic_status':'hypothesis',
                      'parent_key':None,'evidence_segment_ids':['s0']}],
            'title':'整体','central_question':'问题','goal':'','coverage_dimensions':[]}
        converted=_local_result(result,[(self.user['id'],0,10)],0)
        self.assertEqual(converted['views'][0]['evidence'][0]['end_char'],10)
        with self.assertRaises(InvalidInput):
            _local_result({'contexts':result['contexts'],'views':[
                dict(converted['views'][0], evidence_segment_ids=['not-supplied'])]},
                [(self.user['id'],0,10)],1)

    def test_global_grouping_cannot_erase_a_context(self):
        p=self.plan_data()
        with self.assertRaisesRegex(InvalidInput,'every context'):
            _apply_grouping(p,{'groups':[{'title':'group','focus':'','member_keys':['pretrain']}]})

    def test_lifecycle_derived_clears_space_preserves_conversation(self):
        space=self.accept(self.save())['space_id']
        p=purge_plan(self.st,'derived')
        self.assertEqual(p['counts']['research_spaces'],1)
        result=purge_apply(self.st,'derived',confirm=p['token'])
        self.assertTrue(result['doctor']['ok'])
        self.assertEqual(self.st.list_conversations()[0]['title'],'具身智能预训练头脑风暴')
        self.assertEqual(len(list_spaces(self.st)),0)
        self.assertEqual(feedback_summary(self.st)['rated_revisions'],0)

    def test_conversation_delete_blocks_accepted_provenance(self):
        self.accept(self.save())
        with self.assertRaisesRegex(Conflict,'research map'):
            purge_plan(self.st,'conversation',self.conv['id'])

    def test_obsidian_projection_single_overview_and_conflict_protection(self):
        self.accept(self.save())
        vault=Path(self.folder.name)/'Knowledge Vault'
        report=export_vault(self.st,vault)
        self.assertEqual(report['research']['accepted_spaces'],1)
        notes=list((vault/'VKF'/'Research Spaces').glob('*.md'))
        self.assertEqual(len(notes),1)
        self.assertIn('## 视频预训练',notes[0].read_text(encoding='utf-8'))
        self.assertIn('turn 1',notes[0].read_text(encoding='utf-8'))
        self.assertIn('Research Spaces', (vault/'VKF'/'00 - Start Here.md').read_text(encoding='utf-8'))
        notes[0].write_text(notes[0].read_text(encoding='utf-8')+'\n人工编辑',encoding='utf-8')
        second=export_vault(self.st,vault)
        self.assertGreater(len(second['research']['warnings']),0)
        self.assertIn('人工编辑',notes[0].read_text(encoding='utf-8'))

    def test_lifecycle_retirement_includes_research_space_projection(self):
        from vkf_storage.lifecycle import vault_prune
        self.accept(self.save())
        vault=Path(self.folder.name)/'Vault with spaces'
        report=export_vault(self.st,vault)
        note=next((vault/'VKF'/'Research Spaces').glob('*.md'))
        self.assertTrue(note.exists())
        p=purge_plan(self.st,'derived')
        purge_apply(self.st,'derived',confirm=p['token'])
        preview=vault_prune(self.st,vault)
        self.assertTrue(any('Research Spaces' in r.get('relative_path','') or
                            'Research Spaces' in str(r) for r in preview.get('items',preview.get('files',[])))
                        or self.st.db.execute("SELECT 1 FROM lifecycle_retired_files WHERE relative_path LIKE 'VKF/Research Spaces/%'").fetchone())
        # The cleanup must respect fingerprint and leave other Vault files alone.
        count=self.st.db.execute("SELECT COUNT(*) FROM lifecycle_retired_files WHERE relative_path LIKE 'VKF/Research Spaces/%'").fetchone()[0]
        self.assertEqual(count,1)

    def test_feedback_can_be_exported_without_source_conversation(self):
        from vkf_storage.research import export_feedback
        m=self.save()
        add_feedback(self.st,m['id'],'too_fragmented',note='合并多个方法',
                     missing=['Action Token'],structure_score=2)
        dst=Path(self.folder.name)/'human.json'
        report=export_feedback(self.st,dst)
        self.assertEqual(report['annotations_exported'],1)
        payload=json.loads(dst.read_text(encoding='utf8'))
        self.assertEqual(payload['reviewer_annotations'][0]['granularity'],'too_fragmented')
        self.assertNotIn(self.ai['content'],dst.read_text(encoding='utf8'))
        with self.assertRaises(FileExistsError):export_feedback(self.st,dst)

    def test_feedback_version_improvement_report(self):
        m=self.save()
        add_feedback(self.st,m['id'],'too_coarse',note='第一次提炼太笼统')
        data=m['plan'];data['goal']='修订后的研究目标'
        revise_map(self.st,m['id'],data,expected_revision=1)
        add_feedback(self.st,m['id'],'balanced',note='第二次结构更接近研究员')
        self.assertEqual(feedback_summary(self.st)['improved_maps'],1)

    def test_cli_map_feedback_review_and_list(self):
        import contextlib,io
        from vkf_storage.cli import main
        def cli(args):
            stream=io.StringIO()
            with contextlib.redirect_stdout(stream):
                code=main(['--db',str(self.path),*args])
            self.assertEqual(code,0,args)
            return json.loads(stream.getvalue())
        result=cli(['research','map',self.conv['id']])
        ident=result['id']
        self.assertEqual(cli(['research','feedback',ident,'too_coarse','--missing','动作 Token'])['granularity'],'too_coarse')
        self.assertEqual(cli(['research','feedback-summary'])['rated_revisions'],1)
        p=cli(['research','review-plan',ident])
        accepted=cli(['research','review-apply',ident,'--confirm',p['token'],
                      '--expected-revision',str(p['revision']),'--reason','reviewed'])
        self.assertEqual(cli(['research','show',accepted['space_id']])['space']['revision'],1)
        self.assertTrue(self.st.doctor()['ok'])


if __name__=='__main__':unittest.main()
