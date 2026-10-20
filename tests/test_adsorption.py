"""Adsorption recipe -> data discovery -> topic report. Independent temp process."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_DATA=tempfile.TemporaryDirectory(prefix='vasp-adsorption-')
os.environ['VASP_WEB_DATA_DIR']=_DATA.name
os.environ['VASP_AI_KEY_FILE']=str(Path(_DATA.name)/'private/ai.key')
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'backend'),str(Path(__file__).resolve().parent)]

class AdsorptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import config
        if str(config.DATA_DIR)!=_DATA.name:raise unittest.SkipTest('requires independent process')
        config.ensure_data_dirs()

    def setUp(self):
        import adsorption_fixtures,properties,storage,topic_discovery,topic_reports,ai_chat_store
        self.fixtures,self.properties,self.storage,self.discovery,self.topics=adsorption_fixtures,properties,storage,topic_discovery,topic_reports
        self.root=Path(_DATA.name)
        self.user={'user_id':'ads-tester','username':'tester','role':'user'}
        self.project,self.rows=self.fixtures.seed(self.root)
        self.payload=self.fixtures.request()
        self.request={'property_id':'adsorption.simple','model_queries':['LMR','LIC@LMR'],'adsorbate_query':'H2'}
        self.write()
        self.conversation=ai_chat_store.create_conversation(self.user['user_id'],'吸附专题',None,None,'ads')
        guard=patch('ssh._get_client',side_effect=AssertionError('no HPC access'));guard.start();self.addCleanup(guard.stop)

    def write(self):
        import checks_store
        checks_store.CHECKS_DIR.mkdir(parents=True,exist_ok=True)
        (checks_store.CHECKS_DIR/'check_results_ads.json').write_text(json.dumps(self.rows))
        checks_store.invalidate_cache()
        self.storage.save_db({'projects':[self.project]})

    def evaluate(self):
        self.write();return self.properties.evaluate({'projects':[self.project]},self.user,self.payload)

    def test_five_energies_two_adsorption_values_and_shared_reference_difference(self):
        result=self.evaluate()
        self.assertEqual([r['value'] for r in result['results']],[-2,-3,-1],result['gaps'])
        self.assertTrue(all(r['formula_version']=='adsorption.1.1.0' for r in result['results']))
        self.assertEqual(result['results'][0]['reference_state']['source']['task_id'],'ads_mol')
        self.assertIn('消去',''.join(result['results'][-1]['conditions']))
        self.assertTrue(all(not r['formal_conclusion_allowed'] for r in result['results']))

    def test_automatic_structural_roles_and_frozen_report(self):
        doc=self.topics.prepare(self.user,self.conversation,'比较 LMR 与 LIC@LMR 对 H2 的吸附能并生成报告',self.request)
        self.assertEqual([r['value'] for r in doc['data']['science']['results']],[-2,-3,-1])
        self.assertEqual([t['surface']['task_id'] for t in doc['data']['targets']],['ads_a_s','ads_b_s'])
        self.assertTrue(all(c['type'] in ('task.summary','task.params','task.energy_force','task.structure') for c in doc['data']['candidates']))
        doc=self.topics.plan(self.user,doc['topic_id'],{'expected_revision':doc['revision'],'title':'吸附能对比','selections':[]})
        doc=self.topics.write_draft(self.user,doc['topic_id'],{'expected_revision':doc['revision'],'paragraphs':[{'title':'对比分析','section':'analysis','text':'依据 [[F01]] 和 [[F02]]，比较限定于所选电子能与共同参考态。','kind':'analysis'}]})
        self.assertIn('-2.0 eV',self.topics.render_html(doc))
        self.assertIn('不等同于吸附自由能',self.topics.render_html(doc))

    def test_multiple_sites_require_explicit_choice_and_keep_old_snapshot(self):
        self.project,self.rows=self.fixtures.seed(self.root,multiple=True);self.write()
        doc=self.topics.prepare(self.user,self.conversation,'比较 H2 吸附能',self.request)
        self.assertEqual(doc['data']['preparation_status'],'NEEDS_SELECTION')
        self.assertEqual(len(doc['data']['choices'][0]['adsorption_relations']),2)
        self.assertEqual([r['value'] for r in doc['data']['science']['results']],[-3])
        relation=doc['data']['choices'][0]['adsorption_relations'][1]
        targets=doc['data']['targets'];targets[0]={'label':'LMR',**{r:relation[r] for r in ('complex','surface','adsorbate')}}
        selected=self.topics.resolve(self.user,doc['topic_id'],{'expected_revision':doc['revision'],'targets':targets})
        self.assertEqual([r['value'] for r in selected['data']['science']['results']],[-1,-3,-2])
        self.assertEqual(self.topics.load(self.user,doc['topic_id'],revision=1)['data']['preparation_status'],'NEEDS_SELECTION')

    def test_missing_reference_or_unspecified_adsorbate_never_guessed(self):
        self.project,self.rows=self.fixtures.seed(self.root,missing_reference=True);self.write()
        data=self.discovery.prepare(self.user,['ads'],self.request)
        self.assertEqual(data['science']['results'],[])
        self.assertTrue(any(g['check']=='adsorbate_reference' for g in data['gaps']))
        request={k:v for k,v in self.request.items() if k!='adsorbate_query'}
        data=self.discovery.prepare(self.user,['ads'],request)
        self.assertEqual(data['science']['results'],[])
        self.assertTrue(any(g['check']=='adsorbate_query' for g in data['gaps']))

    def test_gas_reference_gamma_grid_separate_cell_and_explicit_type(self):
        self.project,self.rows=self.fixtures.seed(self.root,isolated=True)
        self.assertEqual(self.evaluate()['results'],[])
        self.payload['adsorbate_reference_type']='isolated_molecule'
        result=self.evaluate()
        self.assertEqual([r['value'] for r in result['results']],[-2,-3,-1],result['gaps'])
        self.assertTrue(any(c['check']=='adsorbate_gamma' and c['status']=='AVAILABLE' for c in result['targets'][0]['checks']))

    def test_wrong_stoichiometry_input_mapping_or_cell_is_rejected(self):
        from r3_fixtures import write_run
        for mode in ('composition','mapping','cell'):
            self.project,self.rows=self.fixtures.seed(self.root)
            row=next(r for r in self.rows if r['task_id']=='ads_a_c');run=Path(row['current_output']['dir'])
            text=(run/'POSCAR').read_text()
            if mode=='composition':text=self.fixtures.with_adsorbate(__import__('r3_fixtures').poscar(),count=1)
            elif mode=='mapping':text=text.replace('0 0 0\n','0.1 0 0\n')
            else:text=text.replace('5 0 0','6 0 0')
            row['property_evidence']=write_run(run,text,-105)
            result=self.evaluate()
            self.assertFalse(any(r['key']=='0.adsorption' for r in result['results']),mode)
            self.assertTrue(any(g['check'] in ('stoichiometry','adsorption_relation','adsorption_cell') for g in result['gaps']),result['gaps'])

    def test_unconverged_charged_or_incompatible_input_keeps_healthy_partial(self):
        from r3_fixtures import write_run
        for kwargs in ({'scf':False},{'charge':1},{'encut':520}):
            self.project,self.rows=self.fixtures.seed(self.root)
            row=next(r for r in self.rows if r['task_id']=='ads_a_c');run=Path(row['current_output']['dir'])
            row['property_evidence']=write_run(run,(run/'POSCAR').read_text(),-105,**kwargs)
            result=self.evaluate()
            self.assertEqual([r['value'] for r in result['results']],[-3],result['gaps'])
            self.assertEqual(result['status'],'PARTIAL')

    def test_different_reference_tasks_do_not_cancel(self):
        row=copy.deepcopy(self.rows[-1]);row.update(task_id='ads_mol_other',job_id='ads_mol_other');self.rows.append(row)
        task=copy.deepcopy(self.project['tasks'][-1]);task.update(task_id='ads_mol_other',job_id='ads_mol_other',model_name='OtherHydrogenReference');self.project['tasks'].append(task)
        self.payload['targets'][1]['adsorbate']['task_id']='ads_mol_other'
        result=self.evaluate()
        self.assertEqual([r['value'] for r in result['results']],[-2,-3])
        self.assertTrue(any(g['check']=='common_adsorbate_reference' for g in result['gaps']))

    def test_cross_project_reference_authorized_before_science_reads(self):
        reference=copy.deepcopy(self.project);reference.update(project_id='reference',name='AuthorizedReferences')
        reference['tasks']=[t for t in self.project['tasks'] if t['task_id']=='ads_mol']
        self.project['tasks']=[t for t in self.project['tasks'] if t['task_id']!='ads_mol']
        self.storage.save_db({'projects':[self.project,reference]})
        data=self.discovery.prepare(self.user,['ads','reference'],self.request)
        self.assertEqual([r['value'] for r in data['science']['results']],[-2,-3,-1])
        self.assertEqual(data['targets'][0]['adsorbate']['project_id'],'reference')
        reference['owner']='another-user';self.storage.save_db({'projects':[self.project,reference]})
        with patch('topic_discovery._matches',side_effect=AssertionError('authorization must happen first')):
            with self.assertRaises(self.properties.permissions.PermissionDenied):self.discovery.prepare(self.user,['ads','reference'],self.request)

    def test_legacy_three_queries_and_forbidden_formula_override(self):
        request={'property_id':'adsorption.simple','model_queries':['ads_a_c','ads_a_s','ads_mol']}
        data=self.discovery.prepare(self.user,['ads'],request)
        self.assertEqual([r['value'] for r in data['science']['results']],[-2])
        with self.assertRaises(ValueError):self.discovery.prepare(self.user,['ads'],{**request,'formula':'invented'})
        self.payload['adsorbate_reference_type']='unknown'
        with self.assertRaises(ValueError):self.evaluate()

if __name__=='__main__':unittest.main()
