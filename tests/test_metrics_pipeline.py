"""Acceptance metrics and important near-duplicate edge cases."""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest
from vkf_storage import Storage,InvalidInput
from vkf_storage.consolidation import suggest_review,decide_review,consolidate_pending
from vkf_storage.evaluation import evaluate
from vkf_storage.importers import _full_chunks,extract_conversation
from vkf_storage.coverage import report_coverage


class PipelineMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        p=self.root/'data.db';Storage.initialize(p)
        self.st=Storage(p);self.addCleanup(self.st.close)
    def make(self,title,body):
        c=self.st.create_conversation(title)
        m=self.st.append_message(c['id'],'user',body)
        return c,self.st.propose_candidate(c['id'],m['id'],'idea',title,body)

    def test_same_title_negated_body_must_not_auto_same(self):
        _,a=self.make('Memory deletion','An agent should preserve memories indefinitely.')
        _,b=self.make('Memory deletion','An agent should NOT preserve memories indefinitely.')
        result=suggest_review(self.st,b['id'])
        self.assertNotEqual(result['decision'],'SAME')
        self.assertEqual(self.st.stats()['table_counts']['candidate_equivalences'],0)

    def test_similar_topos_conversations_preserve_new_refinement(self):
        first,canonical=self.make('范畴论与 AI 启示','以 Grothendieck Topos 的局部粘合及 Monad 解释任务世界。')
        second=self.st.create_conversation('AI 与 Grothendieck Topos 理解')
        msg=self.st.append_message(second['id'],'user','以 Grothendieck Topos 的局部粘合及 Monad 解释任务世界，并考虑 Research Kernel。')
        duplicate=self.st.propose_candidate(second['id'],msg['id'],'idea',
            'Topos / Monad 模型化任务世界','使用 Grothendieck Topos 的局部粘合及 Monad 解释任务世界。')
        delta=self.st.propose_candidate(second['id'],msg['id'],'idea',
            'Research Kernel 的一致性语义','具体检验局部 Agent 过程何时能够在 Research Kernel 中全局组合。')
        pool=self.st.db.execute('SELECT id FROM candidates').fetchall()
        self.assertEqual(len(pool),3)
        sim=suggest_review(self.st,duplicate['id'])
        self.assertEqual(sim['target_candidate_id'],canonical['id'])
        self.assertIn(sim['decision'],('RELATED','NEW')) # heuristic must not force near duplicates to SAME
        manual=suggest_review(self.st,duplicate['id'],force_decision='SAME',force_target=canonical['id'],
                              force_reason='人工确认核心命题相同，第二场提出了进一步应用')
        decide_review(self.st,manual['id'],'accept',reason='merged common claim')
        self.assertEqual(len(self.st.list_candidates()),2)
        self.assertEqual(self.st.get_candidate(delta['id'])['state'],'pending')
        self.assertEqual(len(self.st.get_candidate(canonical['id'])['sources']),2)
        self.assertEqual(self.st.stats()['table_counts']['conversations'],2)

    def test_metric_on_manual_labeled_pairs(self):
        _,a=self.make('Same proposition','缓存以存储换取重复计算性能')
        _,b=self.make('Same proposition','缓存以存储换取重复计算性能')
        _,c=self.make('Same topic, new premise','缓存失效条件与一致性模型决定复用是否正确')
        suggest_review(self.st,b['id'])
        suggest_review(self.st,c['id'])
        labels={'pairs':[{'new':b['id'],'target':a['id'],'same':True},
                         {'new':c['id'],'target':a['id'],'same':False}],
                'noise':[],'conversations':[]}
        file=self.root/'gold.json';file.write_text(json.dumps(labels),encoding='utf-8')
        result=evaluate(self.st,file)
        self.assertEqual(result['pair_count'],2)
        self.assertEqual(result['same_precision'],1.0)
        self.assertEqual(result['same_recall'],1.0)
        self.assertEqual(result['false_same_proposal_rate'],0.0)
        self.assertEqual(result['retrieval_recall_at_8'],1.0)

    def test_approval_of_real_relation_requires_approved_both(self):
        _,a=self.make('Theory A','A requires all experiments to run')
        _,b=self.make('Theory B','B says experiments are unnecessary')
        review=suggest_review(self.st,b['id'],force_decision='CONTRADICTS',
                              force_target=a['id'],force_reason='A and B make opposing universal claims')
        with self.assertRaises(InvalidInput):
            decide_review(self.st,review['id'],'accept',reason='confirm')
        self.assertEqual(self.st.stats()['table_counts']['relations'],0)
        first=self.st.approve_candidate(a['id'])
        second=self.st.approve_candidate(b['id'])
        decide_review(self.st,review['id'],'accept',reason='reviewed opposing statements')
        self.assertEqual(self.st.stats()['table_counts']['relations'],1)
        rel=self.st.list_relations(first['id'])[0]
        self.assertEqual(rel['kind'],'contradicts')

    def test_empty_model_output_still_counts_full_input(self):
        c=self.st.create_conversation('All empty candidates')
        text='中文AI🌟'*5000
        self.st.append_message(c['id'],'assistant',text)
        with patch('vkf_storage.importers._llm_suggestions',return_value=[]) as model:
            result=extract_conversation(self.st,c['id'],mode='llm',model='test')
        self.assertGreater(model.call_count,1)
        self.assertEqual(result['created'],0)
        r=report_coverage(self.st,c['id'])
        self.assertTrue(r['complete']);self.assertEqual(r['covered_chars'],len(text))


if __name__=='__main__':unittest.main()

class ReviewExportTests(unittest.TestCase):
    def test_accepted_review_becomes_nonpending_in_obsidian(self):
        from vkf_storage import export_vault
        with TemporaryDirectory() as dirname:
            root=Path(dirname);db=root/'db.sqlite';vault=root/'vault'
            Storage.initialize(db)
            with Storage(db) as st:
                ids=[]
                for i in range(2):
                    c=st.create_conversation(f'discussion{i}')
                    m=st.append_message(c['id'],'user','shared insight')
                    ids.append(st.propose_candidate(c['id'],m['id'],'idea','shared title','shared body'))
                r=suggest_review(st,ids[1]['id'])
                export_vault(st,vault)
                note=next((vault/'VKF'/'Consolidation').glob('*'+r['id'][-10:]+'.md'))
                self.assertIn('vkf_review_status: "pending"',note.read_text(encoding='utf-8'))
                decide_review(st,r['id'],'accept',reason='manually verified')
                report=export_vault(st,vault)
                self.assertFalse(report['consolidation']['warnings'])
                self.assertIn('vkf_review_status: "applied"',note.read_text(encoding='utf-8'))

class ModelComparisonTransportTests(unittest.TestCase):
    def test_llm_transport_and_model_call_audit(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        import io
        with TemporaryDirectory() as dirname:
            root=Path(dirname);db=root/'db.sqlite';Storage.initialize(db)
            with Storage(db) as st:
                candidates=[]
                for n in range(2):
                    c=st.create_conversation('Topos Talk')
                    m=st.append_message(c['id'],'user','Topos builds agent worlds')
                    candidates.append(st.propose_candidate(c['id'],m['id'],'idea',
                        'World Topos', 'Gluing worlds with local overlaps'))
                body={'choices':[{'message':{'content':json.dumps({
                    'decision':'SAME','target_id':candidates[0]['id'],
                    'rationale':'两个候选描述的是相同的局部拼接任务世界构建原理。'},ensure_ascii=False)}}]}
                seen=[]
                class Response:
                    def __enter__(self):return self
                    def __exit__(self,*args):pass
                    def read(self,size):return json.dumps(body).encode('utf-8')
                def fake_urlopen(request,timeout):
                    seen.append((request.full_url,json.loads(request.data)))
                    return Response()
                with patch('vkf_storage.importers.urlopen',side_effect=fake_urlopen):
                    r=suggest_review(st,candidates[1]['id'],mode='llm',model='local-judge',
                                      api_base='http://localhost:11434/v1')
                self.assertEqual(r['decision'],'SAME')
                self.assertEqual(len(seen),1)
                self.assertEqual(seen[0][0],'http://localhost:11434/v1/chat/completions')
                self.assertEqual(seen[0][1]['model'],'local-judge')
                audit=st.db.execute("SELECT state,purpose FROM model_calls ORDER BY created_at DESC LIMIT 1").fetchone()
                self.assertEqual(tuple(audit),('completed','link'))
                self.assertTrue(st.doctor()['ok'])
