"""Only the minimum report's critical paths; no production/SSH/model access."""
import json,os,sys,tempfile,unittest,copy
from pathlib import Path
from unittest.mock import patch
ROOT=tempfile.TemporaryDirectory(prefix='vasp-minimum-')
os.environ['VASP_WEB_DATA_DIR']=ROOT.name
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'backend')]

class MinimumReportTests(unittest.TestCase):
    def setUp(self):
        import config,storage,ai_chat_store,checks_store,topic_simple
        config.ensure_data_dirs();self.simple=topic_simple;self.store=ai_chat_store;self.storage=storage;self.checks=checks_store
        self.user={'user_id':'minimum-user','username':'tester','role':'user'}
        self.project={'project_id':'p','name':'P','owner':'tester','server':'mock','tasks':[
            {'task_id':'surface','model_name':'model1','task_type':'ele','status':'completed','last_energy':-100},
            {'task_id':'ads','model_name':'PMS','task_type':'opt','status':'unconverged','last_energy':-3},
            {'task_id':'complex','model_name':'PMS@model1','task_type':'ele','status':'completed','last_energy':-105}]}
        storage.save_db({'projects':[self.project]});self.conversation=ai_chat_store.create_conversation(self.user['user_id'],'report',None,None,'p')
        self.request={'property_id':'adsorption.simple','model_queries':['model1'],'adsorbate_query':'PMS'}
        self.guard=patch('ssh._get_client',side_effect=AssertionError('no HPC'));self.guard.start();self.addCleanup(self.guard.stop)

    def create(self):return self.simple.create(self.user,self.conversation,'查看PMS在model1上的吸附能',self.request)

    def test_three_energies_calculate_despite_quality_and_missing_structures(self):
        d=self.create();self.assertEqual(d['stage'],'saved');self.assertEqual(d['data']['science']['results'][0]['value'],-2)
        self.assertFalse(d['data']['science']['results'][0]['formal_conclusion_allowed'])
        self.assertEqual(d['simple']['questions'],[]);h=self.simple.render_html(d)
        for text in ('-2.000000','吸附能 = 完整构型能量','未收敛','基底','吸附质','完整构型'):self.assertIn(text,h)
        for text in ('NOT_TESTED','AVAILABLE','evidence_id'):self.assertNotIn(text,h)
        frozen=json.dumps(d['data'],sort_keys=True)
        d=self.simple.update_content(self.user,d['topic_id'],{'expected_revision':1,'title':'我的报告1','notes':'<script>alert(1)</script>','blocks':list(reversed([b['block_id'] for b in d['blocks']]))})
        self.assertEqual(json.dumps(d['data'],sort_keys=True),frozen);self.assertNotIn('<script>alert(1)',self.simple.render_html(d));self.assertEqual(d['revision'],2)

    def test_missing_energy_reports_exact_action(self):
        self.project['tasks'][1].pop('last_energy');self.storage.save_db({'projects':[self.project]});d=self.create()
        self.assertEqual(d['data']['science']['results'],[]);h=self.simple.render_html(d)
        self.assertIn('没有找到吸附质',h);self.assertIn('OUTCAR或OSZICAR',h);self.assertNotIn('NaN',h)

    def test_ambiguity_and_free_answer_keep_old_revision(self):
        task=copy.deepcopy(self.project['tasks'][2]);task.update(task_id='complex2',model_name='PMS@model1_site2',last_energy=-106);self.project['tasks'].append(task);self.storage.save_db({'projects':[self.project]})
        d=self.create();self.assertEqual(d['stage'],'waiting');self.assertEqual(len(d['simple']['questions']),1);self.assertEqual(d['data']['science']['results'],[])
        answer={'expected_revision':1,'answers':{'0.complex':'我想用 PMS@model1_site2'}}
        d=self.simple.answer(self.user,d['topic_id'],answer);self.assertEqual(d['data']['science']['results'][0]['value'],-3);self.assertEqual(d['revision'],2)
        import topic_reports
        self.assertEqual(topic_reports.load(self.user,d['topic_id'],revision=1)['stage'],'waiting')
        with self.assertRaises(Exception):self.simple.answer({'user_id':'someone','username':'other','role':'user'},d['topic_id'],answer)

if __name__=='__main__':unittest.main()
