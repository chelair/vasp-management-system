"""Real existing chat HTTP/SSE pipeline -> R3 -> R2 -> topic save/export.

Subprocess fixture has its own DATA_DIR, private key, auth and mock provider.
"""
import json
from pathlib import Path
import selectors
import subprocess
import time
import unittest
import uuid
from urllib.request import Request,urlopen
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1]

class TopicHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proc=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'tests/r4_server.py')],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        selector=selectors.DefaultSelector();selector.register(cls.proc.stdout,selectors.EVENT_READ)
        if not selector.select(timeout=10):
            cls.proc.terminate();raise RuntimeError('R4 fixture startup timeout')
        line=cls.proc.stdout.readline();selector.close()
        if not line:
            error=cls.proc.stderr.read();cls.proc.terminate();raise RuntimeError(error)
        cls.fixture=json.loads(line);cls.base=f"http://127.0.0.1:{cls.fixture['port']}"
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            try:
                cls.api('/api/ai/chat/connections');break
            except OSError:time.sleep(.02)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:cls.proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:cls.proc.kill();cls.proc.communicate()

    @classmethod
    def api(cls,path,method='GET',body=None,token=True,raw=False):
        headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+cls.fixture['token']
        req=Request(cls.base+path,data=json.dumps(body).encode() if body is not None else (b'' if method=='POST' else None),method=method,headers=headers)
        try:response=urlopen(req,timeout=15)
        except HTTPError as exc:response=exc
        with response:
            text=response.read().decode();status=response.status
        if 'r4-synthetic-private-key-never-return' in text:raise AssertionError('private key leak')
        if raw:return status,text
        data=json.loads(text)
        return status,data.get('data',data)

    def conversation(self,project='full',connection=None):
        status,doc=self.api('/api/ai/chat/conversations','POST',{'title':'自然语言专题','project_id':project,'connection_id':connection or self.fixture['connection']})
        self.assertEqual(status,200,doc);return doc['id']

    def report(self,project='full',question=None,conversation=None,connection=None,expect='completed'):
        cid=conversation or self.conversation(project,connection)
        question=question or '比较 LMR 和 LIC@LMR 的氧空位形成能，生成一份科研报告。'
        status,run=self.api(f'/api/ai/chat/conversations/{cid}/messages','POST',{'content':question,'request_id':uuid.uuid4().hex})
        self.assertEqual(status,200,run)
        _,stream=self.api('/api/ai/chat/runs/'+run['id']+'/events',raw=True)
        self.assertIn('data:',stream)
        _,run=self.api('/api/ai/chat/runs/'+run['id'])
        self.assertEqual(run['status'],expect,run)
        _,items=self.api('/api/reports/topic?conversation_id='+cid)
        self.assertTrue(items['items'],run)
        if expect=='completed':
            self.assertEqual([t['name'] for t in run['tool_events']],['prepare_topic_report','plan_topic_report','write_topic_draft','save_topic_report'])
            self.assertTrue(all(e['status']=='completed' for e in run['tool_events']),run)
            topic_id=run['tool_events'][-1]['result']['topic_id']
        else:topic_id=items['items'][0]['topic_id']
        _,doc=self.api('/api/reports/topic/'+topic_id)
        self.assertEqual(doc['original_question'],question)
        return cid,doc

    def test_real_chat_full_data_correct_values_and_export(self):
        _,doc=self.report()
        self.assertEqual(doc['stage'],'saved')
        self.assertEqual([r['value'] for r in doc['data']['science']['results']],[3,4,1])
        status,html=self.api('/api/reports/topic/'+doc['topic_id']+'/export.html',raw=True)
        self.assertEqual(status,200);self.assertIn('3.0 eV',html)
        self.assertNotIn('project_full',html)

    def test_real_chat_missing_reference_is_conditional(self):
        _,doc=self.report('partial')
        self.assertEqual([r['value'] for r in doc['data']['science']['results']],[1])
        self.assertTrue(doc['data']['assumptions'])
        self.assertTrue(any(g['check']=='mu_O' for g in doc['data']['gaps']))

    def test_real_chat_multi_site_returns_choices(self):
        _,doc=self.report('multi')
        self.assertEqual(doc['data']['preparation_status'],'NEEDS_SELECTION')
        self.assertEqual(len(doc['data']['choices'][0]['relations']),2)
        self.assertEqual(doc['data']['science']['results'],[])

    def test_real_chat_dos_selects_only_relevant_evidence(self):
        _,doc=self.report('dos','比较 Electronic 的 DOS，生成一份科研报告。')
        self.assertIn('ele.pdos',{c['type'] for c in doc['data']['candidates']})
        self.assertTrue(all(c['type'] in ('ele.pdos','task.summary','task.params') for c in doc['data']['candidates']))
        self.assertEqual(doc['data']['science']['status'],'VISUAL_ONLY')

    def test_real_chat_no_data_and_three_independent_reports(self):
        cid,doc=self.report('empty','无数据时，请比较目标模型并生成科研报告。')
        self.assertEqual(doc['data']['facts'],[])
        self.assertEqual(doc['data']['science']['results'],[])
        cid=self.conversation('full')
        docs=[self.report(conversation=cid)[1] for _ in range(3)]
        self.assertEqual(len({d['topic_id'] for d in docs}),3)
        _,items=self.api('/api/reports/topic?conversation_id='+cid)
        self.assertEqual(len(items['items']),3)

    def test_failure_preserves_prepared_draft_and_no_replay(self):
        _,doc=self.report(connection=self.fixture['failure_connection'],expect='failed')
        self.assertEqual(doc['stage'],'planned')
        self.assertTrue(doc['data']['facts'])
        self.assertFalse(doc['narratives'])
        status,again=self.api('/api/reports/topic/'+doc['topic_id'])
        self.assertEqual(status,200);self.assertEqual(again['revision'],doc['revision'])

    def test_model_cannot_choose_ambiguous_site_or_reference_on_its_own(self):
        for connection in self.fixture['hostile_connections'].values():
            cid=self.conversation('multi',connection)
            _,run=self.api(f'/api/ai/chat/conversations/{cid}/messages','POST',{'content':'比较 LMR 和 LIC@LMR 氧空位形成能并生成报告','request_id':uuid.uuid4().hex})
            self.api('/api/ai/chat/runs/'+run['id']+'/events',raw=True)
            _,run=self.api('/api/ai/chat/runs/'+run['id'])
            self.assertEqual(run['status'],'completed',run)
            self.assertEqual(run['tool_events'][0]['status'],'failed')
            self.assertIn('用户',run['tool_events'][0]['result']['error'])
            _,items=self.api('/api/reports/topic?conversation_id='+cid)
            self.assertEqual(items['items'],[])

    def test_adsorption_natural_language_pipeline(self):
        _,doc=self.report('ads','比较 LMR 与 LIC@LMR 对 H2 的吸附能，生成科研报告。')
        self.assertEqual([r['value'] for r in doc['data']['science']['results']],[-2,-3,-1])
        self.assertEqual(doc['request']['adsorbate_query'],'H2')
        self.assertEqual(doc['stage'],'saved')
        status,output=self.api('/api/reports/topic/'+doc['topic_id']+'/export.html',raw=True)
        self.assertEqual(status,200);self.assertIn('-2.0 eV',output)
        self.assertIn('不等同于吸附自由能',output)

    def test_adsorption_missing_reference_and_multi_site(self):
        _,missing=self.report('ads_missing','比较 LMR 与 LIC@LMR 对 H2 的吸附能并生成报告。')
        self.assertEqual(missing['data']['science']['results'],[])
        self.assertTrue(any(g['check']=='adsorbate_reference' for g in missing['data']['gaps']))
        _,multiple=self.report('ads_multi','比较 LMR 与 LIC@LMR 对 H2 的吸附能并生成报告。')
        self.assertEqual(multiple['data']['preparation_status'],'NEEDS_SELECTION')
        self.assertEqual(len(multiple['data']['choices'][0]['adsorption_relations']),2)
        _,gas=self.report('ads_gas','比较 LMR 与 LIC@LMR 对气相 H2 分子的吸附能并生成报告。')
        self.assertEqual([r['value'] for r in gas['data']['science']['results']],[-2,-3,-1])
        self.assertEqual(gas['request']['adsorbate_reference_type'],'isolated_molecule')

    def test_auth_revision_and_science_override_protection(self):
        self.assertEqual(self.api('/api/reports/topic',token=False)[0],401)
        _,doc=self.report()
        prefix='/api/reports/topic/'+doc['topic_id']
        self.assertEqual(self.api(prefix,'PUT',{'expected_revision':doc['revision'],'data':{'value':999}})[0],400)
        status,new=self.api(prefix,'PUT',{'expected_revision':doc['revision'],'title':'人工编辑标题'})
        self.assertEqual(status,200,new)
        self.assertEqual(self.api(prefix,'PUT',{'expected_revision':doc['revision'],'title':'过期请求'})[0],409)
        status,out=self.api(prefix+'/export.html',raw=True)
        self.assertEqual(status,200);self.assertIn('人工编辑标题',out)
        self.assertEqual(new['data']['science'],doc['data']['science'])

if __name__=='__main__':unittest.main()
