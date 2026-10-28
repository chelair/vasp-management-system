"""Project intake -> bindings -> inspection comparison -> frozen report, isolated I/O."""
import copy
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

TEMP = tempfile.TemporaryDirectory(prefix='vasp-requirements-test-')
os.environ['VASP_WEB_DATA_DIR'] = TEMP.name
os.environ['VASP_AI_KEY_FILE'] = str(Path(TEMP.name) / 'ai.key')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

import ai_chat_service as service
import ai_chat_store as store
import auth
import config
import permissions
import project_requirements as req
import project_setup_tools as setup
import storage
from models import ProjectPatchIn
from routers.projects import update_project

ALICE = {'user_id':'alice-id', 'username':'alice', 'role':'user', 'enabled':True}
BOB = {'user_id':'bob-id', 'username':'bob', 'role':'user', 'enabled':True}
RAW = '''模型：合金、界面、分离三个模型。
计算内容：三个结构优化，三个电子结构（DOS/PDOS和差分电荷共用主任务）。
自由能：合金六个构型。
H迁移：界面五个中间映像。
预期吸附能 A > B。
交付：2026-12-15'''


def stream(delta):
    return io.BytesIO(('data: ' + json.dumps({'choices':[{'delta':delta, 'finish_reason':'tool_calls' if 'tool_calls' in delta else 'stop'}]}) + '\n\ndata: [DONE]\n\n').encode())


class RequirementsTests(unittest.TestCase):
    def setUp(self):
        permissions.clear_current_user()
        shutil.rmtree(config.DATA_DIR / 'project_requirements', ignore_errors=True)
        shutil.rmtree(config.PROJECTS_DIR, ignore_errors=True)
        self.scheduling = patch.object(req, 'schedule')
        self.schedule = self.scheduling.start()
        self.addCleanup(self.scheduling.stop)
        storage.save_db({'projects':[]}, backup=False)
        self.ssh = patch('ssh.mkdir_remote', side_effect=AssertionError('no SSH for AI intake')).start()
        self.addCleanup(patch.stopall)
        self.catalog = patch('paths.local_root', return_value=config.PROJECTS_DIR).start()
        self.addCleanup(permissions.clear_current_user)
        self.conn = store.save_connection(ALICE['user_id'], {'name':'test', 'base_url':'http://localhost:9999/v1',
            'model':'mock-model', 'api_key':'test-no-real-provider', 'max_tokens':4096, 'is_default':True})
        self.conv = store.create_conversation(ALICE['user_id'], '新项目', None, self.conn['id'])
        with store.database() as db:
            db.execute("INSERT INTO messages(id,conversation_id,role,content,status,created_at) VALUES (?,?, 'user',?,'completed','now')", (store.uid(),self.conv['id'],RAW))

    def create(self):
        args = {'name':'RuCu_NG', 'deadline':'2026-12-15', 'server':next(iter(config.load_servers())),
            'original_request':RAW, 'description':RAW.splitlines()[0],
            'calc_description':'\n'.join(RAW.splitlines()[1:4]), 'expected_results':'预期吸附能 A > B。',
            'tasks':[{'model_name':f'{name}_{kind}', 'task_type':kind} for name in ('Alloy','Interface','Separated') for kind in ('opt','ele')],
            'groups':[{'name':'Alloy_NO3RR', 'group_type':'free_energy','structures':6},
                      {'name':'Interface_H', 'group_type':'neb','images':5}]}
        result = setup.dispatch(None, self.conv, ALICE, 'create_project_from_request', args)
        self.assertTrue(result.get('contents_complete'), result)
        project = storage.load_db()['projects'][0]
        with store.database() as db:
            self.conv = store.owned(db,'conversations',self.conv['id'],ALICE['user_id'])
        return project, args

    def adsorption_project(self):
        project, _ = self.create()
        project['calc_description'] = '吸附计算 A；吸附计算 B。'
        project['tasks'] = [{'task_id':tid, 'model_name':tid, 'task_type':'opt', 'status':'unconverged',
            'last_energy':energy, 'dir_path':f'RuCu_NG/opt/{tid}'} for tid,energy in
            [('A',-10),('B',-20),('X',-2),('XA',-13),('XB',-24)]]
        storage.save_db({'projects':[project]}, backup=False)
        return project

    def mapping(self):
        return {'calculations':[{'key':key,'title':key,'kind':'adsorption',
            'source':{'field':'calc_description','quote':'吸附计算 '+key},
            'task_ids':[key], 'inputs':{'surface':{'task_id':key},'adsorbate':{'task_id':'X'},'complex':{'task_id':'X'+key}}}
            for key in ('A','B')], 'expectations':[{'key':'ads-order','description':'A的吸附能大于B',
            'source':{'field':'expected_results','quote':'预期吸附能 A > B。'},'property_id':'adsorption.estimate',
            'left':'A','right':'B','operator':'gt','meaning':'numeric'}]}

    def test_intake_reuses_core_unique_ids_idempotent_no_remote(self):
        project,args = self.create()
        self.assertEqual(len(project['tasks']),21)
        self.assertEqual(len({t['task_id'] for t in project['tasks']}),21)
        self.assertEqual(project['expected_results'],'预期吸附能 A > B。')
        self.assertEqual(project['original_request'],RAW)
        self.assertEqual(len([t for t in project['tasks'] if t['task_type']=='ele']),3)
        result=setup.dispatch(project,self.conv,ALICE,'create_project_from_request',args)
        self.assertTrue(result['contents_complete'])
        self.assertEqual(len(storage.load_db()['projects'][0]['tasks']),21)
        self.ssh.assert_not_called()
        with self.assertRaises(ValueError):
            setup.dispatch(project,self.conv,ALICE,'create_project_from_request',{**args,'expected_results':'AI invented result'})
        self.assertEqual(self.conv['project_id'],project['project_id'])

    def test_manual_edit_invalidates_only_changed_sources_and_conflicts(self):
        project=self.adsorption_project()
        initial=req.touch(project)
        mapped=req.save_mapping(project['project_id'],ALICE,initial['source_hash'],self.mapping(),initial['revision'])
        # A restart/unrelated pending project must not cause an admin's save to request other models.
        db=storage.load_db();db['projects'].append({'project_id':'other-project','name':'Other', 'owner':'bob',
            'description':'其他项目尚未整理的原文', 'tasks':[]})
        storage.save_db(db,backup=False)
        permissions.set_current_user({**ALICE,'role':'admin'})
        request=SimpleNamespace(state=SimpleNamespace(user=ALICE))
        self.schedule.reset_mock()
        update_project(project['project_id'],ProjectPatchIn(deadline='2026-12-16'),request)
        self.assertEqual(req.view(storage.load_db()['projects'][0])['status'],'ready')
        self.schedule.assert_not_called()
        self.schedule.reset_mock()
        update_project(project['project_id'],ProjectPatchIn(expected_results=''),request)
        self.schedule.assert_called_once()
        latest=storage.load_db()['projects'][0]
        self.assertEqual(len(latest['tasks']),5)
        self.assertEqual(req.view(latest)['mapping'],{})
        with self.assertRaisesRegex(ValueError,'资料已变化'):
            req.save_mapping(project['project_id'],ALICE,mapped['source_hash'],self.mapping(),mapped['revision'])
        with self.assertRaisesRegex(ValueError,'引用必须来自当前'):
            req.save_mapping(project['project_id'],ALICE,req.fingerprint(latest),self.mapping())
        new=self.mapping();new['expectations']=[]
        result=req.save_mapping(project['project_id'],ALICE,req.fingerprint(latest),new)
        self.assertEqual(result['comparisons'],[])

    def test_numeric_vs_strength_missing_results_and_inspection_update(self):
        project=self.adsorption_project()
        with patch('adsorption_minimum.collect_task_observations',return_value=[]):
            result=req.save_mapping(project['project_id'],ALICE,req.fingerprint(project),self.mapping())
        comp=result['comparisons'][0]
        self.assertEqual((comp['left_ev'],comp['right_ev'],comp['difference_ev']),(-1,-2,1))
        self.assertEqual(comp['status'],'matches')
        self.assertTrue(comp['science']['warnings'])
        mapping=self.mapping();mapping['expectations'][0]['meaning']='stronger_adsorption'
        result=req.save_mapping(project['project_id'],ALICE,req.fingerprint(project),mapping)
        self.assertEqual(result['comparisons'][0]['status'],'differs')
        with patch.object(service,'readonly_json_completion') as model, patch.object(auth,'find_user_by_id',return_value=ALICE):
            db=storage.load_db();db['projects'][0]['tasks'][-1]['last_energy']=-22.5
            storage.save_db(db,backup=False)
            req.inspection_updated('XB')
            self.assertEqual(req.view(db['projects'][0])['comparisons'][0]['status'],'matches')
            req.inspection_updated('XB')
            model.assert_not_called()
        db['projects'][0]['tasks'][-1]['last_energy']=None
        storage.save_db(db,backup=False)
        self.assertEqual(req.evaluate(project['project_id'],ALICE)['comparisons'][0]['status'],'missing')

    def test_cross_project_forged_sources_and_versions_rejected(self):
        project=self.adsorption_project();mapping=self.mapping()
        with self.assertRaises(permissions.PermissionDenied):
            req.save_mapping(project['project_id'],BOB,req.fingerprint(project),mapping)
        mapping['calculations'][0]['inputs']['complex']['task_id']='another-user-task'
        with self.assertRaisesRegex(ValueError,'当前项目'):
            req.save_mapping(project['project_id'],ALICE,req.fingerprint(project),mapping)
        mapping=self.mapping();mapping['expectations'][0]['source']['quote']='A < B'
        with self.assertRaisesRegex(ValueError,'引用必须'):
            req.save_mapping(project['project_id'],ALICE,req.fingerprint(project),mapping)
        result=req.save_mapping(project['project_id'],ALICE,req.fingerprint(project),self.mapping())
        with self.assertRaisesRegex(ValueError,'其他请求更新'):
            req.save_mapping(project['project_id'],ALICE,req.fingerprint(project),self.mapping(),result['revision']-1)
        mapping=self.mapping();mapping['calculations'][0]['inputs']['adsorbate']={'energy_value':-999,'source_quote':'吸附计算 A'}
        with self.assertRaisesRegex(ValueError,'数值不一致'):
            req.save_mapping(project['project_id'],ALICE,req.fingerprint(project),mapping)

    def test_background_extraction_failure_and_late_response_preserve_originals(self):
        project=self.adsorption_project()
        with patch.object(service,'readonly_json_completion',side_effect=ValueError('no model')):
            with self.assertRaises(ValueError):
                req.refresh(project['project_id'],ALICE,self.conn['id'])
        self.assertEqual(storage.load_db()['projects'][0]['expected_results'],project['expected_results'])
        def change_during_request(*args, **kwargs):
            db=storage.load_db();db['projects'][0]['expected_results']=''
            storage.save_db(db,backup=False)
            return self.mapping(),'mock'
        with patch.object(service,'readonly_json_completion',side_effect=change_during_request), patch.object(auth,'find_user_by_id',return_value=ALICE):
            with self.assertRaisesRegex(ValueError,'资料已变化'):
                req.refresh(project['project_id'],ALICE,self.conn['id'])
        self.assertEqual(req.view(storage.load_db()['projects'][0])['mapping'],{})

    def test_automatic_extraction_uses_editor_connection_and_rechecks_revocation(self):
        project=self.adsorption_project()
        store.save_connection(BOB['user_id'], {'name':'other-private', 'base_url':'http://localhost:8888/v1',
            'model':'other', 'api_key':'never-use-others-key', 'max_tokens':4096, 'is_default':True})
        with patch.object(service,'readonly_json_completion',return_value=(self.mapping(),'mock')) as model, patch.object(auth,'find_user_by_id',return_value=ALICE):
            req.refresh(project['project_id'],ALICE)
            self.assertEqual(model.call_args.args[:2],(ALICE['user_id'],self.conn['id']))
        db=storage.load_db();db['projects'][0]['description']='修改后的项目说明'
        storage.save_db(db,backup=False)
        with patch.object(service,'readonly_json_completion',return_value=(self.mapping(),'mock')), patch.object(auth,'find_user_by_id',return_value={**ALICE,'enabled':False}):
            with self.assertRaises(permissions.PermissionDenied):
                req.refresh(project['project_id'],ALICE,self.conn['id'])
        self.assertEqual(req.view(db['projects'][0])['status'],'pending')

    def test_partial_registration_resume_protects_existing_files_and_default_group_name(self):
        project,args=self.create()
        from routers.groups import core_create_group
        result=core_create_group({'project':project['name'],'group_type':'free_energy','structures':1},SimpleNamespace(state=SimpleNamespace(user=ALICE)),local_only=True)
        self.assertTrue(result.get('success'),result)
        orphan=config.PROJECTS_DIR / project['name'] / 'ele' / 'Unregistered'
        orphan.mkdir(parents=True)
        (orphan / 'INCAR').write_text('existing-computation-do-not-overwrite')
        with self.assertRaisesRegex(ValueError,'已有文件'):
            setup.dispatch(storage.load_db()['projects'][0],self.conv,ALICE,'create_calculation_contents',
                {'tasks':[{'model_name':'Unregistered','task_type':'ele'}]})
        self.assertEqual((orphan/'INCAR').read_text(),'existing-computation-do-not-overwrite')
        self.assertNotIn('$ref',json.dumps(setup.TOOLS))

    def test_frozen_report_reuses_same_evidence_and_respects_historical_selection(self):
        import topic_simple, topic_reports
        project=self.adsorption_project()
        result=req.save_mapping(project['project_id'],ALICE,req.fingerprint(project),self.mapping())
        targets=[{'label':c['title'],**c['inputs']} for c in result['mapping']['calculations']]
        doc=topic_simple.create(ALICE,self.conv,'比较A和B的吸附能',{'property_id':'adsorption.estimate',
            'model_queries':['A','B'],'adsorbate_query':'X','targets':targets})
        self.assertTrue(doc['data']['requirements'][0]['comparisons'])
        self.assertIn('数值关系符合预期',topic_simple.render_html(doc))
        before=topic_simple.render_html(doc)
        db=storage.load_db();db['projects'][0]['tasks'][-1]['last_energy']=-22.1
        storage.save_db(db,backup=False)
        self.assertEqual(topic_simple.render_html(topic_reports.load(ALICE,doc['topic_id'])),before)
        historical=req.report_snapshot(db['projects'],ALICE,['A','B','X','XA','XB'],doc['data']['science'])
        self.assertEqual(historical[0]['comparisons'],[])

    def test_general_chat_tools_create_then_bind_project_same_run(self):
        args={'name':'RuCu_NG','deadline':'2026-12-15','server':next(iter(config.load_servers())),
            'original_request':RAW,'description':RAW,'tasks':[{'task_type':'opt','model_name':'Alloy'}]}
        calls=[]
        def upstream(connection,key,path,payload):
            calls.append(copy.deepcopy(payload))
            index=len(calls)
            if index==1:
                names={t['function']['name'] for t in payload['tools']}
                self.assertEqual(names,setup.GENERAL_NAMES)
                delta={'tool_calls':[{'index':0,'id':'create1','type':'function','function':{'name':'create_project_from_request','arguments':json.dumps(args,ensure_ascii=False)}}]}
            elif index==2:
                self.assertIn('get_task_inspections',{t['function']['name'] for t in payload['tools']})
                delta={'tool_calls':[{'index':0,'id':'read1','type':'function','function':{'name':'get_project_requirements','arguments':'{}'}}]}
            else:
                delta={'content':'已建立项目和优化任务，原文保留。'}
            return stream(delta)
        with patch('threading.Thread.start'):
            run,_=service.start_run(ALICE,ALICE['user_id'],self.conv['id'],RAW,False,'requirements-chat-test')
        with store.database() as db:
            saved=store.owned(db,'runs',run['id'],ALICE['user_id'])
            connection=store.owned(db,'connections',self.conn['id'],ALICE['user_id'])
        with patch.object(service,'_open',side_effect=upstream):
            service._generate(run['id'],connection,'test-no-real-provider',json.loads(saved['snapshot'])['messages'],ALICE,True)
        detail=store.detail(ALICE['user_id'],self.conv['id'])
        self.assertEqual(detail['runs'][0]['status'],'completed',detail['runs'][0])
        self.assertEqual([e['status'] for e in detail['runs'][0]['tool_events']],['completed','completed'])
        self.assertEqual(detail['project_id'],storage.load_db()['projects'][0]['project_id'])
        self.assertEqual(len(calls),3)


if __name__=='__main__':
    unittest.main()
