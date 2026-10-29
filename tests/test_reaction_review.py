"""Endpoint diagnosis and customer report. Temporary data; no model, SSH or jobs."""
import copy
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = tempfile.TemporaryDirectory(prefix='vasp-reaction-test-')
os.environ['VASP_WEB_DATA_DIR'] = ROOT.name
os.environ['VASP_AI_KEY_FILE'] = str(Path(ROOT.name)/'ai.key')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
import ai_chat_store as store
import config
import permissions
import reaction_review as review
import storage
import topic_reports as topics
import topic_simple


def structure(points):
    return 'fixture\n1\n30 0 0\n0 30 0\n0 0 30\nB C O F Li Cl\n1 1 2 2 1 1\nCartesian\n'+'\n'.join(' '.join(map(str,p)) for p in points)+'\n'


class ReactionReviewTests(unittest.TestCase):
    def setUp(self):
        config.ensure_data_dirs()
        self.user = {'user_id':'alice','username':'alice','role':'user'}
        self.project = {'project_id':'p','name':'P','owner':'alice','calc_description':'比较B-F断键路径','tasks':[
            {'task_id':'is','model_name':'PATH_IS','task_type':'opt','dir_path':'P/neb/PATH/opt/IS','group':{'group_id':'g','group_role':'initial_opt','name':'PATH'}},
            {'task_id':'fs','model_name':'PATH_FS','task_type':'opt','dir_path':'P/neb/PATH/opt/FS','group':{'group_id':'g','group_role':'final_opt','name':'PATH'}},
            {'task_id':'path','model_name':'PATH_neb','task_type':'neb','group':{'group_id':'g','group_role':'neb_images','name':'PATH'}}]}
        storage.save_db({'projects':[self.project]})
        self.a = [[0,0,5],[0,1,5],[1,0,5],[0,2,5],[0,0,6.4],[0,0,3.6],[1,0,3],[1,1,0]]
        self.b = copy.deepcopy(self.a);self.b[2][2]=7;self.b[4][2]=7.9
        self.folders = [Path(ROOT.name)/'projects/P/neb/PATH/opt'/name/'files' for name in ('IS','FS')]
        for i, (folder, points) in enumerate(zip(self.folders,(self.a,self.b))):
            folder.mkdir(parents=True,exist_ok=True)
            (folder/'CONTCAR').write_text(structure(points))
            (folder/'INCAR').write_text('ENCUT=500\nEDIFFG=-0.02\nIVDW=11\n')
            (folder/'KPOINTS').write_text('grid\n0\nGamma\n'+('1 1 1' if i==0 else '2 2 1')+'\n0 0 0\n')
        self.guard = patch('ssh.run_remote',side_effect=AssertionError('no SSH'))
        self.guard.start();self.addCleanup(self.guard.stop)
        self.conversation = store.create_conversation('alice','diagnosis',None,None,'p')

    def test_contact_difference_shape_metric_and_parameters_are_real_evidence(self):
        result = review.analyze(self.project,self.user,{'path_task_id':'path'},illustrations=True)
        pair = next(r for r in result['interface_contacts'] if r['atoms']==[3,7])
        self.assertEqual((pair['initial_angstrom'],pair['final_angstrom'],pair['state']),(2,4,'initial_only'))
        expected=math.sqrt(((math.sqrt(5)-1)**2+(math.sqrt(6)-math.sqrt(2))**2+(3-math.sqrt(5))**2)/6)
        self.assertAlmostEqual(result['framework_shape']['pair_distance_rms_change_angstrom'],expected,places=6)
        self.assertEqual(next(p['status'] for p in result['parameters'] if p['name']=='KPOINTS'),'different')
        self.assertIsNone(result['deformation_energy']['value_ev'])
        self.assertIn('不是化学键',result['contact_criteria']['note'])
        self.assertTrue(result['structures']['initial']['annotations'])
        self.assertTrue(result['sources']['initial']['selector']['expected_sha256'])

    def test_rigid_translation_and_rotation_are_not_framework_deformation(self):
        translated = [[-p[1]+10,p[0]+4,p[2]+2] for p in self.a]
        (self.folders[1]/'CONTCAR').write_text(structure(translated))
        result=review.analyze(self.project,self.user,{'path_task_id':'path'})
        self.assertEqual(result['framework_shape']['pair_distance_rms_change_angstrom'],0)
        self.assertTrue(all(r['state']=='both' for r in result['interface_contacts']))

    def test_report_keeps_questions_and_warnings_in_chat_and_answers_freeze_evidence(self):
        doc=topic_simple.create(self.user,self.conversation,'看看断键路径',{'property_id':'neb.barrier','model_queries':['PATH'],
            'objective':'尽量隔离目标B-F断键','notes':'INTERNAL_ERROR_UNKNOWN_DO_NOT_RENDER'})
        self.assertEqual(doc['stage'],'waiting')
        self.assertEqual({q['id'] for q in doc['simple']['questions']},{'scope','bond.path'})
        output=topic_simple.render_html(doc)
        for text in ('报告重点','背景','问题','影响','为什么','解决办法','距离','O–Li','<sub>a</sub>'):
            self.assertIn(text,output)
        self.assertLess(output.index('报告重点'),output.index('为什么'))
        for text in ('INTERNAL_ERROR_UNKNOWN_DO_NOT_RENDER','数据缺口','补充说明','还缺什么','使用这个结果前'):
            self.assertNotIn(text,output)
        self.assertTrue(topics.summary(doc)['conversation_notes'])
        with patch.object(topics,'list_for',return_value=[{'run_id':'retry','topic_id':doc['topic_id']}]), patch.object(review,'load_many',side_effect=AssertionError('retry must reuse saved report')):
            retried=topic_simple.create(self.user,self.conversation,'看看断键路径',doc['request'],run_id='retry')
        self.assertEqual(retried['topic_id'],doc['topic_id'])
        self.assertEqual(retried['revision'],doc['revision'])
        frozen=copy.deepcopy(doc['data'])
        with patch.object(review,'load_many',side_effect=AssertionError('answer must not reread sources')):
            changed=topic_simple.answer(self.user,doc['topic_id'],{'expected_revision':doc['revision'],'answers':{'scope':'isolate_bond','bond.path':'A'}})
        self.assertEqual(changed['stage'],'saved')
        self.assertEqual(changed['data']['reaction_reviews'],frozen['reaction_reviews'])
        self.assertEqual(changed['data']['library'],frozen['library'])
        self.assertEqual(changed['revision'],2)
        self.assertEqual(topics.load(self.user,doc['topic_id'],revision=1)['stage'],'waiting')

    def test_permissions_mapping_and_source_changes_are_not_silently_accepted(self):
        with patch.object(review,'load_many') as read:
            with self.assertRaises(permissions.PermissionDenied):
                review.analyze(self.project,{'user_id':'bob','username':'bob','role':'user'},{'path_task_id':'path'})
            read.assert_not_called()
        with self.assertRaises(ValueError):
            review.analyze(self.project,self.user,{'path_task_id':'path','initial':{'task_id':'fs'}})
        first=review.analyze(self.project,self.user,{'path_task_id':'path'})
        (self.folders[0]/'CONTCAR').write_text(structure(self.b))
        with self.assertRaisesRegex(ValueError,'已变化'):
            review.analyze(self.project,self.user,{'path_task_id':'path','initial':first['sources']['initial']['selector']})

    def test_question_answer_continues_original_chat_once_and_keeps_evidence(self):
        from starlette.requests import Request
        from routers.topic_reports import questions
        doc=topic_simple.create(self.user,self.conversation,'诊断断键路径',{'property_id':'neb.barrier','model_queries':['PATH']})
        request=Request({'type':'http','state':{'user':self.user}})
        with patch('ai_chat_service.start_run',return_value=({'id':'continued','status':'queued'},True)) as start:
            response=questions(doc['topic_id'],request,{'expected_revision':1,'answers':{'scope':'isolate_bond','bond.path':'A'},'continue_analysis':True})
        self.assertTrue(response['success'])
        updated=response['data']
        self.assertEqual(updated['continuation']['id'],'continued')
        self.assertEqual(updated['data']['library'],doc['data']['library'])
        start.assert_called_once()
        self.assertEqual(start.call_args.args[2],self.conversation['id'])
        self.assertIn('尽量只比较目标断键',start.call_args.args[3])
        self.assertEqual(start.call_args.kwargs['topic_id'],doc['topic_id'])

    def test_card_run_reuses_confirmed_topic_even_if_model_calls_create_again(self):
        import ai_chat_service as service
        import topic_tools
        from starlette.requests import Request
        from routers.topic_reports import questions
        connection=store.save_connection('alice',{'name':'mock','base_url':'https://mock.invalid/v1',
            'model':'mock','api_key':'isolated-test-key','max_tokens':4096})
        with store.database() as db:
            db.execute('UPDATE conversations SET connection_id=? WHERE id=?',(connection['id'],self.conversation['id']))
        doc=topic_simple.create(self.user,self.conversation,'诊断断键路径',{'property_id':'neb.barrier','model_queries':['PATH']})
        before=len(topics.list_for(self.user,self.conversation['id']))
        with patch.object(service.threading,'Thread'), patch.object(service,'context_for',return_value={}):
            response=questions(doc['topic_id'],Request({'type':'http','state':{'user':self.user}}),
                {'expected_revision':1,'answers':{'scope':'isolate_bond','bond.path':'A'},'continue_analysis':True})
        confirmed=response['data'];run_id=confirmed['continuation']['id']
        with store.database() as db:
            run=store.owned(db,'runs',run_id,'alice');snapshot=json.loads(run['snapshot'])
        self.assertEqual(snapshot['topic_continuation']['topic_id'],doc['topic_id'])
        self.assertEqual(snapshot['topic_continuation']['answers']['bond.path'],'A')
        self.assertEqual(snapshot['messages'][-1]['role'],'user')
        self.assertTrue(any('不要新建同名报告' in m['content'] for m in snapshot['messages']))
        with patch.object(review,'load_many',side_effect=AssertionError('continuation must not reread sources')):
            for name in ('create_topic_report','prepare_topic_report'):
                result=topic_tools.dispatch(self.user,self.conversation,run_id,name,{'property_id':'neb.barrier','model_queries':['PATH']})
                self.assertEqual(result['topic_id'],doc['topic_id'])
                self.assertEqual(result['stage'],'saved')
                self.assertEqual(result['questions'],[])
                self.assertEqual(result['revision'],confirmed['revision'])
            edited=topic_tools.dispatch(self.user,self.conversation,run_id,'update_topic_report',{'topic_id':doc['topic_id'],
                'expected_revision':confirmed['revision'],'assessment':{'conclusion':'围绕已选目标核对端点与路径。'}})
        self.assertEqual(edited['revision'],3)
        saved=topics.load(self.user,doc['topic_id'])
        self.assertEqual(saved['data']['reaction_reviews'],confirmed['data']['reaction_reviews'])
        self.assertEqual(saved['simple']['answers'],confirmed['simple']['answers'])
        self.assertEqual(len(topics.list_for(self.user,self.conversation['id'])),before)
        with self.assertRaisesRegex(ValueError,'其他性质'):
            topic_tools.dispatch(self.user,self.conversation,run_id,'create_topic_report',{'property_id':'dos.comparison','model_queries':['PATH']})
        # Regenerating a pre-fix card answer also recovers its original topic, without a new click.
        snapshot.pop('topic_continuation')
        with store.database() as db:
            db.execute("UPDATE runs SET status='completed',snapshot=? WHERE id=?",(json.dumps(snapshot),run_id))
        with patch.object(service.threading,'Thread'), patch.object(service,'context_for',return_value={}):
            retried,_=service.start_run(self.user,'alice',self.conversation['id'],'',True,'retry-card-'+run_id)
        with store.database() as db:
            retry_snapshot=json.loads(store.owned(db,'runs',retried['id'],'alice')['snapshot'])
        self.assertEqual(retry_snapshot['topic_continuation']['topic_id'],doc['topic_id'])

    def test_card_continuation_does_not_bind_a_report_from_another_chat(self):
        import ai_chat_service as service
        doc=topic_simple.create(self.user,self.conversation,'诊断断键路径',{'property_id':'neb.barrier','model_queries':['PATH']})
        connection=store.save_connection('alice',{'name':'mock','base_url':'https://mock.invalid/v1',
            'model':'mock','api_key':'isolated-test-key','max_tokens':4096})
        other=store.create_conversation('alice','other',None,connection['id'],'p')
        with patch.object(service.threading,'Thread') as thread, patch.object(service,'context_for',return_value={}):
            with self.assertRaises(permissions.PermissionDenied):
                service.start_run(self.user,'alice',other['id'],'继续',False,'wrong-chat-'+doc['topic_id'],topic_id=doc['topic_id'])
            thread.assert_not_called()

    def test_model_readback_and_export_include_energy_order_and_selected_bond(self):
        import topic_tools
        images=[{'label':'0','energy':0,'relative':0,'max_force':.01},
            {'label':'1','energy':3.0072,'relative':3.0072,'max_force':.324072},
            {'label':'2','energy':3.2072,'relative':3.2072,'max_force':.01}]
        with patch.object(review,'merged_results',return_value={'path':{'neb_barrier':{'images':images}}}):
            doc=topic_simple.create(self.user,self.conversation,'核对端点和能量',{'property_id':'neb.barrier','model_queries':['PATH']})
        doc=topic_simple.answer(self.user,doc['topic_id'],{'expected_revision':1,'answers':{'scope':'isolate_bond','bond.path':'A'}})
        output=topic_simple.render_html(doc)
        self.assertIn('当前采样最高点：末态',output)
        self.assertIn('3.207200',output)
        self.assertIn('0.324072',output)
        self.assertIn('A（已选）',output)
        result=topic_tools.dispatch(self.user,self.conversation,'','get_topic_report',{'topic_id':doc['topic_id']})
        self.assertEqual(result['path_evidence'][0]['energy_profile']['interior_peak_observed'],False)
        self.assertIn('当前采样最高点：末态',result['content']['text'])
        self.assertIn('排除所有 F',result['content']['text'])


if __name__=='__main__':unittest.main()
