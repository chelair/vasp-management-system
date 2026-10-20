"""R4 isolated acceptance: real R2/R3, authenticated API later, no real model/HPC."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_DATA=tempfile.TemporaryDirectory(prefix='vasp-r4-')
os.environ['VASP_WEB_DATA_DIR']=_DATA.name
os.environ['VASP_AI_KEY_FILE']=str(Path(_DATA.name)/'ai.key')
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'backend'),str(Path(__file__).resolve().parent)]


class TopicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import config
        if str(config.DATA_DIR)!=_DATA.name:raise unittest.SkipTest('R4 requires independent isolated process')
        config.ensure_data_dirs()

    def setUp(self):
        import ai_chat_store
        import properties
        import topic_reports
        import r3_fixtures
        self.store,self.properties,self.topics,self.fixtures=ai_chat_store,properties,topic_reports,r3_fixtures
        self.root=Path(_DATA.name)
        self.project,self.rows=r3_fixtures.seed(self.root)
        self.user={'user_id':'tester-id','username':'tester','role':'user'}
        self.conversation={'id':self.store.uid(),'owner':'tester-id','project_id':'r3p','task_id':None,'workspace_enabled':1}
        with self.store.database() as db:
            db.execute("INSERT INTO conversations(id,owner,project_id,title,created_at,updated_at) VALUES(?,?,?,'科研专题','now','now')",(self.conversation['id'],self.user['user_id'],'r3p'))
        self.ssh=patch('ssh._get_client',side_effect=AssertionError('R4 may not access HPC'))
        self.ssh.start();self.addCleanup(self.ssh.stop)
        self.request={'property_id':'oxygen_vacancy.neutral_single','model_queries':['LMR','LIC@LMR'],'common_oxygen_reference':True}
        self.question='比较 LMR 和 LIC@LMR 的氧空位形成能，生成一份科研报告。'
        for p in self.properties.REPORT_DIR.glob('prop_*.json'):p.unlink()

    def prepare(self,request=None):
        return self.topics.prepare(self.user,self.conversation,self.question,request or self.request)

    def plan(self,doc):
        selections=[{'block_id':c['block_id'],'reason':'直接提供比较所需的能量和理论参数','section':'sources' if c['type']=='task.params' else 'results','order':i,'essential':True}
                    for i,c in enumerate(doc['data']['candidates']) if c['type'] in ('task.params','task.energy_force','ele.pdos')]
        return self.topics.plan(self.user,doc['topic_id'],{'expected_revision':doc['revision'],'title':'科研专题','selections':selections})

    def draft(self,doc):
        text='结果依据为 [[F01]]。比较仅限于所选理论设置与明确参考条件。' if doc['data']['facts'] else '尚无相关计算数据；需要补齐对应模型、参数及参考态，不能给出数值结论。'
        return self.topics.write_draft(self.user,doc['topic_id'],{'expected_revision':doc['revision'],'paragraphs':[{'section':'analysis','title':'对比分析','text':text,'kind':'analysis'}]})

    def test_case_1_four_energies_and_explicit_reference_auto_used(self):
        self.properties.evaluate({'projects':[self.project]},self.user,self.fixtures.request(),persist=True)
        doc=self.prepare()
        self.assertEqual([r['value'] for r in doc['data']['science']['results']],[3,4,1],doc['data']['gaps'])
        self.assertEqual(doc['data']['preparation_status'],'AVAILABLE',doc['data']['gaps'])
        self.assertTrue(doc['data']['science']['reference_state']['source_report_id'])
        doc=self.draft(self.plan(doc));doc=self.topics.save(self.user,doc['topic_id'],doc['revision'])
        self.assertEqual(doc['report_type'],'topic');self.assertEqual(doc['stage'],'saved')
        output=self.topics.render_html(doc)
        self.assertIn('3.0 eV',output)
        self.assertIn('原始科学数据',output)
        self.assertEqual(doc['original_question'],self.question)

    def test_case_2_missing_reference_only_conditional_delta(self):
        doc=self.prepare()
        self.assertEqual([r['value'] for r in doc['data']['science']['results']],[1])
        self.assertEqual(doc['data']['science']['not_calculable'],['absolute_formation_energy'])
        self.assertTrue(doc['data']['assumptions'])
        self.assertTrue(any(g['check']=='mu_O' for g in doc['data']['gaps']))
        self.assertEqual(doc['data']['facts'][0]['validation_status'],'CONDITIONAL')

    def test_case_3_multiple_vacancy_sites_never_randomly_select(self):
        root=self.root/'runs/a_d2/con1'
        row=copy.deepcopy(self.rows[1]);row.update(task_id='a_d2',job_id='a_d2',remote_dir=str(root.parent))
        row['current_output']['dir']=str(root)
        row['property_evidence']=self.fixtures.write_run(root,self.fixtures.poscar(defect=True,site=3),-91)
        self.rows.append(row)
        self.project['tasks'].append({**self.project['tasks'][1],'task_id':'a_d2','job_id':'a_d2','model_name':'LMR_vac_site2','remote_dir':str(root.parent)})
        self.write_rows()
        doc=self.prepare()
        choice=next(c for c in doc['data']['choices'] if c['label']=='LMR')
        self.assertEqual(len(choice['relations']),2)
        self.assertEqual(doc['data']['preparation_status'],'NEEDS_SELECTION')
        self.assertFalse(any(r['key'].endswith('formation_difference') for r in doc['data']['science']['results']))
        relation=choice['relations'][0]
        targets=copy.deepcopy(doc['data']['targets'])
        targets[0]={'label':'LMR',**{k:relation[k] for k in ('pristine','defect','removed_oxygen_index')}}
        chosen=self.topics.resolve(self.user,doc['topic_id'],{'expected_revision':doc['revision'],'targets':targets})
        self.assertEqual([r['value'] for r in chosen['data']['science']['results']],[1])
        self.assertEqual(self.topics.load(self.user,doc['topic_id'],revision=1)['data']['preparation_status'],'NEEDS_SELECTION')

    def write_rows(self):
        (self.root/'checks/check_results_r3.json').write_text(json.dumps(self.rows))
        (self.root/'projects.json').write_text(json.dumps({'projects':[self.project]}))

    def test_case_4_dos_only_related_pdos_and_parameters(self):
        from r2_science_fixtures import seed_science
        seed_science(self.root,self.project)
        row=copy.deepcopy(self.rows[0]);row.update(task_id='t_ele',task_type='ele',remote_dir='R3P/ele/Electronic');row['current_output']={'latest_dir':'','dir':'R3P/ele/Electronic'}
        self.rows.append(row);self.write_rows()
        request={'property_id':'dos.comparison','model_queries':['Electronic']}
        doc=self.prepare(request)
        types={c['type'] for c in doc['data']['candidates']}
        self.assertIn('ele.pdos',types)
        self.assertIn('task.params',types)
        self.assertNotIn('ele.bader',types);self.assertNotIn('group.neb',types)
        self.assertEqual(doc['data']['science']['status'],'VISUAL_ONLY')
        self.assertTrue(any(f['value']==0 for f in doc['data']['facts']),doc['data']['gaps'])
        doc=self.plan(doc)
        self.assertIn('pdos-chart',self.topics.render_html(doc))

    def test_case_5_no_data_generates_precise_requirements(self):
        doc=self.prepare({**self.request,'model_queries':['NoExistingModel']})
        self.assertEqual(doc['data']['science']['results'],[])
        self.assertEqual(doc['data']['facts'],[])
        self.assertEqual(doc['data']['candidates'],[])
        doc=self.draft(self.plan(doc))
        self.assertIn('不能给出数值',self.topics.render_html(doc))
        self.assertTrue(doc['data']['gaps'])

    def test_case_6_edit_delete_reorder_titles_and_export_consistent(self):
        doc=self.draft(self.plan(self.prepare()))
        frozen=copy.deepcopy(doc['data']);blocks=list(reversed(doc['blocks']))
        textblock=next(b for b in blocks if b['origin']=='ai_text')
        items=[{'block_id':b['block_id'],'title':b['title'],'section':b['section'],**({'text':'用户修改的分析 [[F01]]，仍需验证。'} if b['block_id']==textblock['block_id'] else {})} for b in blocks]
        deleted=next(b['block_id'] for b in blocks if b['origin']=='r2')
        doc=self.topics.edit(self.user,doc['topic_id'],{'expected_revision':doc['revision'],'title':'编辑后的专题','blocks':items,'deleted_block_ids':[deleted]})
        self.assertEqual(doc['data'],frozen)
        html=self.topics.render_html(doc)
        self.assertIn('用户修改的分析',html)
        self.assertNotIn(f"id='{deleted}'",html)
        self.assertEqual(doc['blocks'][0]['block_id'],blocks[0]['block_id'])
        self.assertEqual(self.topics.render_html(doc),self.topics.render_html(self.topics.load(self.user,doc['topic_id'])))
        note=doc['narratives'][textblock['block_id']]
        self.assertNotEqual(note['ai_text'],note['user_text'])

    def test_case_7_three_topics_do_not_touch_full_report(self):
        marker=self.root/'reports'/'project-full.json';marker.parent.mkdir(exist_ok=True)
        marker.write_text('{"report_type":"project_full","original":true}')
        before=marker.read_bytes();ids=[]
        for _ in range(3):
            doc=self.draft(self.plan(self.prepare()));doc=self.topics.save(self.user,doc['topic_id'],doc['revision']);ids.append(doc['topic_id'])
        self.assertEqual(len(set(ids)),3)
        self.assertEqual(marker.read_bytes(),before)
        listed=self.topics.list_for(self.user,self.conversation['id'])
        self.assertEqual({r['topic_id'] for r in listed},set(ids))

    def test_model_cannot_write_fabricated_numbers_or_change_science(self):
        doc=self.plan(self.prepare())
        before=self.topics.load(self.user,doc['topic_id'])
        for text in ('形成能为 999 eV。','形成能为 九百电子伏。','结果为 [[F99]]。','E_f = E_defect + E_pristine。'):
            with self.assertRaises(ValueError):self.topics.write_draft(self.user,doc['topic_id'],{'expected_revision':doc['revision'],'paragraphs':[{'section':'analysis','title':'分析','text':text,'kind':'analysis'}]})
        self.assertEqual(self.topics.load(self.user,doc['topic_id']),before)
        with self.assertRaises(ValueError):self.topics.plan(self.user,doc['topic_id'],{'expected_revision':doc['revision'],'title':'形成能999 eV','selections':[]})
        invalid=copy.deepcopy(before);invalid['data']['facts'][0]['validation_status']='INVALID'
        with self.assertRaises(ValueError):self.topics.validate_text('无效输入 [[F01]]',invalid)
        with self.assertRaises(ValueError):self.topics.edit(self.user,doc['topic_id'],{'expected_revision':doc['revision'],'science':{'value':999}})

    def test_unrelated_missing_and_forged_blocks_rejected(self):
        doc=self.prepare()
        bad={'block_id':'blk_wrong','reason':'无关资源','section':'results','order':0,'essential':True}
        with self.assertRaises(ValueError):self.topics.plan(self.user,doc['topic_id'],{'expected_revision':doc['revision'],'selections':[bad]})
        self.assertEqual(self.topics.load(self.user,doc['topic_id'])['stage'],'prepared')

    def test_cross_project_auth_and_report_ownership(self):
        private=copy.deepcopy(self.project);private.update(project_id='private',name='Private',owner='other')
        (self.root/'projects.json').write_text(json.dumps({'projects':[self.project,private]}))
        with patch('topic_discovery._matches',side_effect=AssertionError('must authorize first')):
            with self.assertRaises(self.topics.permissions.PermissionDenied):
                self.topics.prepare(self.user,self.conversation,self.question,self.request,project_ids=['r3p','private'])
        doc=self.prepare()
        with self.assertRaises(LookupError):self.topics.load({'user_id':'other','username':'other','role':'user'},doc['topic_id'])
        self.project['owner']='revoked';self.write_rows()
        with self.assertRaises(self.topics.permissions.PermissionDenied):self.topics.load(self.user,doc['topic_id'])

    def test_freeze_and_stale_prompt_on_upstream_change(self):
        doc=self.draft(self.plan(self.prepare()))
        self.assertFalse(self.topics.freshness(self.user,doc)['stale'])
        before=copy.deepcopy(doc['data'])
        self.rows[1]['last_energy']=-91;self.write_rows()
        self.assertTrue(self.topics.freshness(self.user,doc)['stale'])
        loaded=self.topics.load(self.user,doc['topic_id'])
        self.assertEqual(loaded['data'],before)
        self.assertEqual([r['value'] for r in loaded['data']['science']['results']],[1])

    def test_revision_conflict_and_model_failure_preserve_manual_edits(self):
        doc=self.draft(self.plan(self.prepare()))
        block=next(b for b in doc['blocks'] if b['origin']=='ai_text')
        current=self.topics.edit(self.user,doc['topic_id'],{'expected_revision':doc['revision'],'title':'新的人工标题'})
        with self.assertRaises(self.topics.RevisionConflict):self.topics.edit(self.user,doc['topic_id'],{'expected_revision':doc['revision'],'title':'旧编辑覆盖'})
        with patch('ai_chat_service.readonly_json_completion',side_effect=ValueError('model failed')):
            with self.assertRaises(ValueError):self.topics.regenerate(self.user,current['topic_id'],block['block_id'],current['revision'],'private-connection')
        self.assertEqual(self.topics.load(self.user,doc['topic_id']),current)
        with patch('ai_chat_service.readonly_json_completion',return_value=({'text':'依据 [[F01]]，这是重新生成的解释。'},'mock-private')):
            new=self.topics.regenerate(self.user,current['topic_id'],block['block_id'],current['revision'],'private-connection')
        self.assertEqual(new['data'],current['data'])
        self.assertIn('重新生成',new['narratives'][block['block_id']]['ai_text'])

    def test_xss_and_external_images_not_executable(self):
        doc=self.plan(self.prepare())
        text='解释<script>window.TOPIC_XSS=true</script> ![外链](https://example.invalid/leak) [[F01]]'
        doc=self.topics.write_draft(self.user,doc['topic_id'],{'expected_revision':doc['revision'],'paragraphs':[{'section':'analysis','title':'<img src=x onerror=alert()>','text':text,'kind':'hypothesis'}]})
        output=self.topics.render_html(doc)
        self.assertNotIn('<script>window.TOPIC_XSS',output)
        self.assertNotIn('<img src=x',output)
        self.assertNotIn('https://example.invalid/leak',output)
        self.assertIn('假设（未验证）',output)

    def test_r2_energy_uses_same_selected_observation_not_live_task(self):
        for task in self.project['tasks']:task['last_energy']=-999
        self.write_rows()
        doc=self.prepare()
        energy=next(b for b in doc['data']['library']['blocks'] if b['type']=='task.energy_force' and b['task_id']=='a_p')
        evidence=doc['data']['library']['evidence'][energy['source_refs'][0]['evidence_id']]
        self.assertEqual(evidence['payload']['final_energy_ev'],-100)
        doc=self.plan(doc)
        self.assertFalse(self.topics.freshness(self.user,doc)['stale'])
        self.project['tasks'][0]['job_id']='a_new_job';self.write_rows()
        self.assertTrue(self.topics.freshness(self.user,doc)['stale'])

    def test_explicit_historical_con_observation_never_mixed_with_current_r2(self):
        from checks_store import collect_task_observations
        from datetime import datetime,timedelta
        old=copy.deepcopy(self.rows[0]);old['last_energy']=-110
        old['checked_at']=(datetime.now()-timedelta(minutes=1)).isoformat()
        old['current_output']={'latest_dir':'con0','dir':str(self.root/'runs/a_p/con0')}
        old['property_evidence']=self.fixtures.write_run(self.root/'runs/a_p/con0',self.fixtures.poscar(),-110)
        self.rows.append(old);self.write_rows()
        observation=next(o for o in collect_task_observations('a_p',5) if o['data']['last_energy']==-110)
        targets=self.fixtures.request()['targets'];targets[0]['pristine']['observation_id']=observation['observation_id']
        doc=self.prepare({**self.request,'targets':targets})
        item=next(i for i in doc['data']['science']['inputs'] if i.get('source',{}).get('observation_id')==observation['observation_id'])
        self.assertEqual(item['status'],'STALE')
        energy=next(b for b in doc['data']['library']['blocks'] if b['type']=='task.energy_force' and b['task_id']=='a_p')
        evidence=doc['data']['library']['evidence'][energy['source_refs'][0]['evidence_id']]
        self.assertEqual(evidence['payload']['final_energy_ev'],-110)
        self.assertTrue(evidence['provenance'][0]['directory'].endswith('/con0'))
        self.assertEqual(evidence['provenance'][0]['observation_id'],observation['observation_id'])
        self.assertFalse(doc['data']['science']['results'])

    def test_dos_multiple_tasks_can_be_explicitly_resolved(self):
        from r2_science_fixtures import seed_science
        seed_science(self.root,self.project)
        original=next(t for t in self.project['tasks'] if t['task_id']=='t_ele')
        self.project['tasks'].append({**original,'task_id':'t_ele_second','model_name':'Electronic_copy'})
        self.write_rows()
        doc=self.prepare({'property_id':'dos.comparison','model_queries':['Electronic']})
        self.assertEqual(doc['data']['preparation_status'],'NEEDS_SELECTION')
        self.assertNotIn('task_id',doc['data']['targets'][0]['model'])
        selected=self.topics.resolve(self.user,doc['topic_id'],{'expected_revision':doc['revision'],'targets':[{'label':'Electronic','model':{'project_id':'r3p','task_id':'t_ele_second'}}]})
        self.assertEqual(selected['data']['targets'][0]['model']['task_id'],'t_ele_second')
        self.assertEqual({c['task_id'] for c in selected['data']['candidates']},{'t_ele_second'})
        self.assertNotEqual(selected['data']['preparation_status'],'NEEDS_SELECTION')

    def test_unknown_recipe_and_limits_no_formula_fallback(self):
        doc=self.prepare({'property_id':'invented.property','model_queries':['LMR']})
        self.assertEqual(doc['data']['preparation_status'],'UNSUPPORTED')
        self.assertEqual(doc['data']['facts'],[])
        with self.assertRaises(ValueError):self.prepare({**self.request,'formula':'wrong'})
        with self.assertRaises(ValueError):self.prepare({**self.request,'model_queries':['x']*5})


if __name__=='__main__':unittest.main()
