"""后台报告真实本机HTTP/模型Mock；复用报告夹具，临时数据与私有密钥。"""
import copy
import io
import json
import threading
import time
import unittest
from unittest.mock import patch

import test_report_ai_notes as fixture
import test_report_review as review_fixture
import ai_chat_service as service
import ai_chat_store as chat
import report_background as work
import report_review
import report_store


class ReportBackgroundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        review_fixture.ReportReviewTests.setUpClass()
        cls.client = review_fixture.ReportReviewTests.client

    @classmethod
    def tearDownClass(cls):
        review_fixture.ReportReviewTests.tearDownClass()

    def setUp(self):
        self.case = review_fixture.ReportReviewTests('test_review_real_model_text_scope_completion_and_export_exclusion')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        with chat.database() as db:
            db.execute('DELETE FROM conversations')

    def tearDown(self):
        fixture.RELEASE.set()
        deadline = time.monotonic()+4
        while work._CONTROLS and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse(work._CONTROLS, '后台测试工作必须结束后才能清理夹具')

    def start(self, action='notes', scope='p', **payload):
        return self.client.post('/api/reports/assistant/'+scope, json={'action': action,
            'request_id': chat.uid(), 'connection_id': self.case.connection['id'], 'report_id': 'rpt_p', **payload})

    def state(self, scope='p'):
        response = self.client.get('/api/reports/assistant/'+scope)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['data']

    def wait(self, run_id):
        deadline = time.monotonic()+8
        while time.monotonic() < deadline:
            response = self.client.get('/api/ai/chat/runs/'+run_id)
            self.assertEqual(response.status_code, 200, response.text)
            run = response.json()['data']
            if run['status'] not in ('queued','running'):
                return run
            time.sleep(.015)
        self.fail('后台工作未结束')

    def test_start_returns_immediately_and_restores_progress_draft_and_save(self):
        self.case.mode('slow')
        began = time.monotonic()
        response = self.start(keys=['t'], request_id='report-idempotency-1')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertLess(time.monotonic()-began, 1)
        run = response.json()['data']
        self.assertTrue(fixture.SEEN.wait(2))
        state = self.state()
        self.assertEqual(state['conversation']['runs'][0]['report_progress']['done'], 0)
        self.assertEqual(state['drafts'], [])
        again = self.start(keys=['t'], request_id='report-idempotency-1')
        self.assertEqual(again.json()['data']['id'], run['id'])
        fixture.RELEASE.set()
        self.assertEqual(self.wait(run['id'])['status'], 'completed')
        state = self.state()  # 与刷新/新浏览器一样不依赖原请求和页面状态。
        self.assertEqual(len(state['drafts']), 1)
        self.assertEqual(len(fixture.REQUESTS), 1)
        item = state['drafts'][0]
        import report_ai_notes
        status = report_ai_notes.status(self.case.doc, self.case.user)
        with patch.object(report_ai_notes, 'status', return_value={**status, 'targets': [{'key': 't', 'title': 'Model'}]}):
            repeated = self.start()
            self.wait(repeated.json()['data']['id'])
        self.assertEqual(len(fixture.REQUESTS), 1, '批量应跳过已持久化的待审草稿')
        self.assertEqual(report_store.read_notes('rpt_p'), {})
        self.assertEqual(self.case.save(item['draft']).status_code, 200)
        gone = self.client.request('DELETE', '/api/reports/assistant/p/drafts/'+run['id']+'/rpt_p%3At')
        self.assertEqual(gone.status_code, 200, gone.text)
        self.assertEqual(self.state()['drafts'], [])
        self.assertNotIn(fixture.KEY, json.dumps(state))

    def test_partial_drafts_and_failure_messages_survive_later_failure(self):
        import report_ai_notes
        preview = report_ai_notes.preview
        def one_failure(report_id, key, *args):
            if key == 'type_opt':
                raise ValueError('缺少参考能量，请在对话补充')
            return preview(report_id, key, *args)
        with patch.object(report_ai_notes, 'preview', side_effect=one_failure):
            result = self.start(keys=['type_opt','t'])
            self.assertEqual(result.status_code,200,result.text)
            self.wait(result.json()['data']['id'])
        state = self.state()
        self.assertEqual(len(state['drafts']), 1)
        self.assertIn('缺少参考能量', state['conversation']['messages'][-1]['content'])
        self.assertEqual(report_store.read_notes('rpt_p'), {})

    def test_stop_and_restart_never_apply_late_result_or_retry_model(self):
        for restart in (False, True):
            with self.subTest(restart=restart):
                self.case.mode('slow');fixture.RELEASE.clear();fixture.SEEN.clear()
                result = self.start(keys=['t']);run_id=result.json()['data']['id']
                self.assertTrue(fixture.SEEN.wait(2))
                if restart:
                    chat.recover_runs()
                else:
                    self.assertEqual(self.client.post('/api/ai/chat/runs/'+run_id+'/cancel').status_code,200)
                fixture.RELEASE.set()
                self.assertEqual(self.wait(run_id)['status'], 'interrupted' if restart else 'cancelled')
                deadline=time.monotonic()+3
                while work._CONTROLS and time.monotonic()<deadline:time.sleep(.01)
                self.assertEqual(self.state()['drafts'], [])
        self.assertEqual(len(fixture.REQUESTS), 2)

    def test_no_model_full_generation_is_background_and_reports_actual_steps(self):
        entered, release = threading.Event(), threading.Event()
        doc = copy.deepcopy(self.case.doc)
        def build(pid, *, progress):
            progress(1,3,'整理结构：Ovcc_In2O3@LMR');entered.set();release.wait(3)
            progress(2,3,'整理正文与图表')
            return {'report':doc,'markdown':'new background report','charts':{}}
        with patch('report_builder.build_report',side_effect=build):
            result=self.start('generate',connection_id=None)
            self.assertEqual(result.status_code,200,result.text)
            self.assertTrue(entered.wait(2))
            self.assertIn('Ovcc_In2O3',self.state()['conversation']['runs'][0]['report_progress']['label'])
            release.set();self.assertEqual(self.wait(result.json()['data']['id'])['status'],'completed')
        self.assertEqual(fixture.REQUESTS,[])
        self.assertIn('完整报告已生成',self.state()['conversation']['messages'][-1]['content'])

    def test_project_connection_owner_and_revocation_enforced(self):
        denied=self.client.get('/api/reports/assistant/p',headers={'x-test-user':'bob'})
        self.assertEqual(denied.status_code,403)
        denied=self.client.get('/api/reports/assistant/p',headers={'x-test-user':'agent'})
        self.assertEqual(denied.status_code,403)
        bob=chat.save_connection('bob',{'name':'other','base_url':'http://localhost:1','model':'mock','api_key':'unused','max_tokens':1000,'is_default':True})
        self.assertEqual(self.start(connection_id=bob['id'],keys=['t']).status_code,403)
        self.case.mode('slow')
        result=self.start(keys=['t']);self.assertTrue(fixture.SEEN.wait(2))
        self.case.change_project(owner='bob');fixture.RELEASE.set()
        deadline=time.monotonic()+3
        while work._CONTROLS and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(self.client.get('/api/reports/assistant/p').status_code,403)
        with chat.database() as db:
            snapshot=json.loads(db.execute('SELECT snapshot FROM runs WHERE id=?',(result.json()['data']['id'],)).fetchone()[0])
        self.assertNotIn('report_drafts',snapshot)

    def test_generation_with_ai_enabled_never_generates_notes_and_preserves_manual_text(self):
        report_store.save_note('rpt_p','t','保留已有人工分析','保留已有论文参考')
        before=report_store.read_notes('rpt_p')
        def build(pid, *, progress):
            return {'report':copy.deepcopy(self.case.doc),'markdown':'已有数据报告','charts':{}}
        with patch('report_builder.build_report',side_effect=build), patch.object(work,'notes',side_effect=AssertionError('生成报告不能调用AI注解')):
            result=self.start('generate')
            self.assertEqual(result.status_code,200,result.text)
            run=self.wait(result.json()['data']['id'])
            self.assertEqual(run['status'],'completed',run)
        self.assertEqual(fixture.REQUESTS,[])
        self.assertEqual(self.state()['drafts'],[])
        self.assertEqual(report_store.read_notes('rpt_p'),before)

    def test_report_conversation_policy_keeps_identity_and_blocks_unscoped_ai_writing(self):
        import report_tools
        convo=work.conversation(self.case.user,'p',self.case.connection['id'],create=True)
        self.assertEqual(convo['prompt'],work.prompt('p'))
        self.assertIn('AI只处理用户已经保存的批注',work.model_prompt(convo['prompt']))
        self.assertEqual(work.model_prompt('普通科研分析'),'普通科研分析')
        run_id=chat.uid()
        with patch.object(chat,'owned',return_value={'conversation_id':convo['id']}), patch.object(work,'notes') as notes:
            with self.assertRaisesRegex(ValueError,'只处理你提交的批注'):
                report_tools.dispatch(self.case.project,convo,self.case.user,'generate_project_report_notes',{},run_id)
            notes.assert_not_called()
        restored=work.conversation(self.case.user,'p')
        self.assertEqual(restored['id'],convo['id'])
        self.assertEqual(restored['prompt'],convo['prompt'])

    def test_batch_generates_only_visible_open_projects_and_rechecks_scope(self):
        built = []
        def build(pid, *, progress):
            built.append(pid)
            doc = copy.deepcopy(self.case.doc)
            doc['metadata'].update(project_id=pid, report_id='rpt_'+pid, project_name='ReportFixture' if pid=='p' else 'Off')
            return {'report':doc,'markdown':'batch fixture','charts':{}}
        with patch('report_builder.build_report',side_effect=build):
            result=self.start('generate',scope='all',connection_id=None)
            self.assertEqual(result.status_code,200,result.text)
            self.wait(result.json()['data']['id'])
        self.assertEqual(built,['p','q'])
        self.assertEqual(fixture.REQUESTS,[])
        self.assertEqual(self.client.get('/api/reports/assistant/all',headers={'x-test-user':'bob'}).json()['data']['conversation'],None)
        self.case.change_project(owner='bob')
        self.assertEqual(self.client.get('/api/reports/assistant/all').status_code,403)

    def test_comment_model_question_and_reply_use_same_report_and_source(self):
        state,module=self.case.comment(text='请补充比较，需要什么就问我')
        cid=state['comments'][0]['id']
        self.case.plan([],status='blocked',reply='请补充氧气分子的参考能量。')
        result=self.start('comment',comment_id=cid);self.wait(result.json()['data']['id'])
        state=self.state()
        self.assertIn('氧气分子的参考能量',state['conversation']['messages'][-1]['content'])
        self.case.plan([{'kind':'text','target':module['key'],'text':'已根据用户补充的参考条件完成说明。'}],reply='已根据补充修改原报告。')
        original_do_post=fixture.Provider.do_POST
        def chat_response(handler):
            data=handler.rfile.read(int(handler.headers['Content-Length']))
            body=json.loads(data)
            handler.rfile=io.BytesIO(data)
            if 'tools' not in body:return original_do_post(handler)
            last=body['messages'][-1]
            if last['role']=='tool' and last.get('tool_call_id')=='process-original':
                delta={'content':'已根据你的参考能量处理原批注并修改报告。'};reason='stop'
            elif last['role']=='tool':
                delta={'tool_calls':[{'index':0,'id':'process-original','type':'function','function':{
                    'name':'process_project_report_comment','arguments':json.dumps({'report_id':'rpt_p','comment_id':cid})}}]};reason='tool_calls'
            else:
                delta={'tool_calls':[{'index':0,'id':'reply-original','type':'function','function':{
                    'name':'reply_project_report_comment','arguments':json.dumps({'report_id':'rpt_p','comment_id':cid})}}]};reason='tool_calls'
            handler.send_response(200);handler.send_header('Content-Type','text/event-stream');handler.end_headers()
            handler.wfile.write(('data: '+json.dumps({'choices':[{'delta':delta,'finish_reason':reason}]})+'\n\ndata: [DONE]\n\n').encode());handler.wfile.flush()
        with patch.object(fixture.Provider,'do_POST',chat_response):
            follow=self.start('chat',content='氧气分子能量采用-8.3 eV')
            self.assertEqual(follow.status_code,200,follow.text)
            finished=self.wait(follow.json()['data']['id'])
            self.assertEqual(finished['status'],'completed',finished)
        comment=report_review.view(report_store.load_report('rpt_p')[0])['comments'][0]
        self.assertEqual(comment['replies'][-2]['text'],'氧气分子能量采用-8.3 eV')
        self.assertEqual(comment['status'],'done')
        self.assertIn('参考条件',self.client.get('/api/reports/project/rpt_p').json()['data']['markdown'])
        self.assertEqual(self.state()['conversation']['id'],state['conversation']['id'])


if __name__ == '__main__':
    unittest.main()
