"""Minimum-data reports and strict verification share arithmetic, not gates."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=tempfile.TemporaryDirectory(prefix='vasp-preliminary-')
os.environ['VASP_WEB_DATA_DIR']=ROOT.name
os.environ['VASP_AI_KEY_FILE']=str(Path(ROOT.name)/'ai.key')
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'backend'),str(Path(__file__).resolve().parent)]


class PreliminaryReportTests(unittest.TestCase):
    def setUp(self):
        import config, storage, ai_chat_store, r3_fixtures, properties, topic_simple
        config.ensure_data_dirs()
        self.root=Path(ROOT.name);self.fixture=r3_fixtures;self.properties=properties;self.simple=topic_simple
        for path in (self.root/'checks').glob('check_results_*.json'):path.unlink()
        self.project,self.rows=r3_fixtures.seed(self.root)
        self.db={'projects':[self.project]};self.user={'username':'tester','user_id':'preliminary-user','role':'user'}
        self.conversation=ai_chat_store.create_conversation(self.user['user_id'],'report',None,None,'r3p')
        self.store=storage
        guard=patch('ssh._get_client',side_effect=AssertionError('No HPC in report tests'))
        guard.start();self.addCleanup(guard.stop)

    def save(self):
        (self.root/'checks/check_results_r3.json').write_text(json.dumps(self.rows))
        self.store.save_db(self.db)

    def relative(self):
        return {'property_id':'relative_energy','model_queries':['a_p','a_d'],
                'targets':[{'reference':{'task_id':'a_p'},'model':{'task_id':'a_d'}}]}

    def create(self, request):
        self.save()
        return self.simple.create(self.user,self.conversation,'用已有结果生成初步报告',request)

    def test_old_task_energies_without_snapshots_are_useful_and_frozen(self):
        self.rows=[]
        for task,energy in zip(self.project['tasks'],[-100,-98,-150,-141]):
            task['last_energy']=energy;task['status']='unconverged'
        doc=self.create(self.relative());science=doc['data']['science']
        self.assertEqual([r['value'] for r in science['results']],[2])
        self.assertEqual(science['results'][0]['validation_status'],'PRELIMINARY')
        self.assertEqual(science['inputs'][0]['source']['energy_source']['kind'],'task_record')
        self.assertIn('初步计算结果',self.simple.render_html(doc))
        self.assertNotIn('缺少原始巡检',self.simple.render_html(doc))
        self.assertTrue(doc['simple']['warnings'])
        self.assertEqual(doc['data']['facts'][0]['validation_status'],'PRELIMINARY')
        self.project['tasks'][1]['last_energy']=-1;self.save()
        import topic_reports
        self.assertEqual(topic_reports.load(self.user,doc['topic_id'])['data'],doc['data'])

    def test_nonconvergence_and_different_settings_allow_partial_vacancy_results(self):
        row=self.rows[1]
        row['status']='unconverged';row['force_converged']=False
        row['property_evidence']=self.fixture.write_run(Path(row['current_output']['dir']),self.fixture.poscar(defect=True),-92,scf=False,ionic=False,encut=600)
        # Missing auxiliary sampling cannot erase the captured composition.
        del row['property_evidence']['files']['KPOINTS']
        doc=self.create({'property_id':'oxygen_vacancy.neutral_single','model_queries':['LMR','LIC@LMR'],'common_oxygen_reference':True})
        self.assertEqual([r['value'] for r in doc['data']['science']['results']],[1])
        self.assertTrue(doc['simple']['warnings'])
        self.assertEqual(self.properties.evaluate(self.db,self.user,self.fixture.request())['results'][0]['value'],4)

    def test_known_wrong_composition_and_severe_overlap_still_block(self):
        with self.assertRaisesRegex(ValueError,'相同组成'):
            self.create(self.relative())
        self.rows[1]['property_evidence']=self.fixture.write_run(Path(self.rows[1]['current_output']['dir']),self.fixture.poscar().replace('0.25 0.25 0.25','0.0 0.0 0.0'),-92)
        with self.assertRaisesRegex(ValueError,'严重原子重叠'):
            self.create(self.relative())

    def test_missing_energy_does_not_save_an_empty_ready_report(self):
        self.rows=[]
        self.project['tasks'][0]['last_energy']=-100
        import topic_reports
        before=topic_reports.list_for(self.user,self.conversation['id'])
        with self.assertRaisesRegex(ValueError,'a_d|LMR_vac'):
            self.create(self.relative())
        self.assertEqual(topic_reports.list_for(self.user,self.conversation['id']),before)

    def test_missing_chemical_potential_is_not_invented_and_valid_groups_survive(self):
        payload=self.fixture.request();del payload['mu_O'];self.save()
        result=self.properties.evaluate(self.db,self.user,payload,preliminary=True)
        self.assertEqual(result['results'],[])
        payload['common_oxygen_reference']=True
        result=self.properties.evaluate(self.db,self.user,payload,preliminary=True)
        self.assertEqual([r['value'] for r in result['results']],[1])
        payload['mu_O']=self.fixture.request()['mu_O'];payload['targets'][1]['defect']={'query':'absent'}
        result=self.properties.evaluate(self.db,self.user,payload,preliminary=True)
        self.assertEqual([r['value'] for r in result['results']],[3])
        self.assertEqual(result['status'],'PARTIAL')

    def test_reordered_relaxed_vacancy_can_be_bound_without_precise_site_mapping(self):
        for index in (1,3):
            row=self.rows[index];text=row['property_evidence']['files']['POSCAR']['text'].replace('0.5 0.5 0.5','0.51 0.5 0.5')
            row['property_evidence']=self.fixture.write_run(Path(row['current_output']['dir']),text,row['last_energy'])
        doc=self.create({'property_id':'oxygen_vacancy.neutral_single','model_queries':['LMR','LIC@LMR'],'common_oxygen_reference':True})
        self.assertEqual([r['value'] for r in doc['data']['science']['results']],[1])
        self.assertTrue(any(g['check']=='vacancy_site' for g in doc['data']['gaps']))

    def test_existing_work_function_values_do_not_require_scf_or_plateau_pass(self):
        import work_function
        from dates import now_iso
        for task,value in zip(self.project['tasks'][:2],[5,5.5]):
            path=work_function.meta_path(self.project['name'],task);path.parent.mkdir(parents=True,exist_ok=True)
            row=next(r for r in self.rows if r['task_id']==task['task_id'])
            path.write_text(json.dumps({'status':'done','finished_at':now_iso(),'remote':{'remote_dir':row['current_output']['dir']},'result':{'work_function':value,'vacuum_level':value+1,'efermi':1,'axis':'c'}}))
            row['status']='unconverged';row['force_converged']=False
        request=self.relative();request['property_id']='work_function.difference'
        doc=self.create(request)
        self.assertEqual([r['value'] for r in doc['data']['science']['results']],[.5])
        task=self.project['tasks'][1];path=work_function.meta_path(self.project['name'],task)
        meta=json.loads(path.read_text());meta['remote']['remote_dir']='/other/run';path.write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError,'目录对应'):
            self.create(request)

    def test_adsorption_known_wrong_roles_block_but_missing_structures_do_not(self):
        self.save()
        payload={'property_id':'adsorption.estimate','project_ids':['r3p'],'targets':[{'surface':{'task_id':'a_p'},'complex':{'task_id':'a_d'},'adsorbate':{'task_id':'b_p'}}]}
        result=self.properties.evaluate(self.db,self.user,payload)
        self.assertEqual(result['results'],[])
        self.assertTrue(any(g.get('check')=='stoichiometry' for g in result['gaps']))
        for row in self.rows:row['property_evidence']={}
        self.save();result=self.properties.evaluate(self.db,self.user,payload)
        self.assertEqual([r['value'] for r in result['results']],[158])

    def test_neb_requires_complete_finite_images_but_not_full_snapshots(self):
        task=self.project['tasks'][0];task.update(task_type='neb',group={'group_id':'test-neb','group_role':'neb_images','name':'LMR'})
        row=self.rows[0];row.update(task_type='neb',status='unconverged',force_converged=False,
                                  incar={'IMAGES':1},neb_barrier={'images':[{'label':str(i),'energy':v} for i,v in enumerate([-10,-8,-10.2])]})
        row['property_evidence']={};self.save()
        payload={'property_id':'neb.barrier','project_ids':['r3p'],'targets':[{'path':{'task_id':'a_p'}}]}
        result=self.properties.evaluate(self.db,self.user,payload,preliminary=True)
        self.assertEqual([r['value'] for r in result['results']],[2])
        doc=self.create({'property_id':'neb.barrier','model_queries':['LMR']})
        self.assertEqual([r['value'] for r in doc['data']['science']['results']],[2])
        self.assertTrue(any('缺少可用端点结构' in w for w in doc['simple']['warnings']))
        row['neb_barrier']['images'].pop();self.save()
        self.assertEqual(self.properties.evaluate(self.db,self.user,payload,preliminary=True)['results'],[])

    def test_known_charge_is_not_silently_evaluated_as_neutral_vacancy(self):
        row=self.rows[1]
        row['property_evidence']=self.fixture.write_run(Path(row['current_output']['dir']),self.fixture.poscar(defect=True),-92,charge=1)
        self.save();result=self.properties.evaluate(self.db,self.user,self.fixture.request(),preliminary=True)
        self.assertEqual([r['value'] for r in result['results']],[4])
        self.assertTrue(any(g['check']=='charge_state' and g['status']=='INVALID' for g in result['gaps']))

    def test_known_capture_directory_mismatch_is_not_a_quality_warning(self):
        self.rows[1]['property_evidence']['directory']='/wrong/run';self.save()
        result=self.properties.evaluate(self.db,self.user,self.fixture.request(),preliminary=True)
        self.assertEqual([r['value'] for r in result['results']],[4])
        self.assertTrue(any(g['check']=='source_identity' and g['status']=='INVALID' for g in result['gaps']))


if __name__=='__main__':unittest.main()
