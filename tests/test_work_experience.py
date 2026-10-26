"""Small offline acceptance: audit cleanup, owned retrieval, weekly/model path and correction."""
import copy
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

_DATA=tempfile.TemporaryDirectory(prefix='vasp-work-experience-')
os.environ['VASP_WEB_DATA_DIR']=_DATA.name
os.environ['VASP_AI_KEY_FILE']=str(Path(_DATA.name)/'ai.key')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import ai_chat_store as store
import ai_workspace
import operation_audit as audit
import permissions
import storage
import work_experience as memory


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(memory.FILE.parent.parent,Path(_DATA.name))
        memory.FILE.unlink(missing_ok=True)
        audit.FILE.parent.mkdir(parents=True,exist_ok=True)
        for path in audit.FILE.parent.glob('*'):path.unlink()
        (Path(_DATA.name)/'audit_submit.log').unlink(missing_ok=True)
        self.user={'user_id':'alice-id','username':'alice','role':'user'}
        self.other={'user_id':'bob-id','username':'bob','role':'user'}
        self.project={'project_id':'p','name':'P','owner':'alice','tasks':[{'task_id':'t','model_name':'Model','task_type':'opt'}]}
        self.db={'projects':[self.project,{'project_id':'q','name':'Q','owner':'bob','tasks':[{'task_id':'s','task_type':'opt'}]}]}
        storage.save_db(self.db,backup=False)

    def event(self,**values):
        return audit.append({'at':datetime.now().astimezone().isoformat(),'username':'alice','actor_id':'alice-id',
            'project':'P','task_id':'t','command':'parameters.upload','result':'OK',
            'details':{'changes':[{'key':'EDIFFG','before':'-.05','after':'-.02'}]},**values})

    def test_rotation_keeps_recent_actions_and_submission_totals_without_double_counting(self):
        first=self.event();second=self.event(command='task.archive')
        legacy=Path(_DATA.name)/'audit_submit.log'
        line='[2026-10-26T11:00:00] project=P result=OK job=42\n'
        legacy.write_text(line)
        original=Path.write_text
        def interrupted(path,*args,**kwargs):
            if path==legacy:raise OSError('interrupted before truncate')
            return original(path,*args,**kwargs)
        with patch.object(Path,'write_text',interrupted),self.assertRaises(OSError):audit.compact()
        with legacy.open('a') as stream:stream.write(line.replace('job=42','job=43'))
        self.assertEqual(audit.submission_counts()['2026-10-26'],2)
        audit.compact();audit.compact()
        self.assertEqual(audit.submission_counts()['2026-10-26'],2)
        self.assertEqual([r['id'] for r in audit.recent(2)],[second['id'],first['id']])
        self.assertTrue(list(audit.FILE.parent.glob('*.gz')))

    def test_learning_uses_private_model_then_chinese_search_edit_and_disable(self):
        self.event(result='OK password=do-not-send sk-Abcdefghijklmnopq')
        self.event(username='bob',actor_id='bob-id',task_id='s',result='private-other-owner')
        calls=[]
        class Provider(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(payload)
                records=json.loads(payload['messages'][1]['content'])
                body={'choices':[{'message':{'content':json.dumps({'items':[{'title':'收敛参数处理记录','body':'修改收敛标准EDIFFG，从-.05调整到-.02；只是输入写入记录，最终结果未知。','source_ids':[records[0]['id']]}]},ensure_ascii=False)}}], 'usage':{'total_tokens':123}}
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(body).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Provider)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        conn=store.save_connection('alice-id',{'name':'fixture','base_url':f'http://127.0.0.1:{server.server_port}',
            'model':'fixture','api_key':'fixture-key-only','max_tokens':2048,'is_default':True,'thinking_mode':'disabled'})
        memory.settings('alice-id',{'enabled':True,'connection_id':conn['id']})
        result=memory.learn(self.user)
        self.assertEqual(result['added'],1)
        self.assertEqual(len(calls),1)
        sent=json.dumps(calls[0])
        for secret in ('private-other-owner','do-not-send','sk-Abcdefghijklmnopq'):self.assertNotIn(secret,sent)
        self.assertLessEqual(calls[0]['max_tokens'],2048)
        rows=memory.entries(self.user,'收敛标准','p')
        self.assertEqual(len(rows),1)
        self.assertFalse(rows[0]['confirmed'])
        self.assertEqual(memory.entries(self.other,'收敛'),[])
        with self.assertRaises(permissions.PermissionDenied):memory.entries(self.other,'收敛','p')
        with self.assertRaises(permissions.PermissionDenied):memory.update(self.other,rows[0]['id'],{'disabled':True})
        tool=ai_workspace.dispatch(self.project,{}, {},'search_work_experience',{'query':'收敛'},user=self.user)
        self.assertEqual(len(tool['items']),1)
        memory.update(self.user,rows[0]['id'],{'body':'只适用于本案例的收敛设置','confirmed':True})
        self.assertIn('只适用于本案例',memory.document(self.user))
        memory.update(self.user,rows[0]['id'],{'disabled':True})
        self.assertEqual(memory.entries(self.user,'收敛','p'),[])
        with self.assertRaises(ValueError):memory.learn(self.user)
        self.assertEqual(memory.learn(self.user,manual=True)['events_used'],0)
        with self.assertRaises(ValueError):memory.learn(self.user,manual=True)
        self.assertEqual(len(calls),1,'known events and weekly retries must not cause another paid request')

    def test_unknown_source_never_becomes_experience_and_failure_is_visible(self):
        self.event()
        with memory.database() as db:
            db.execute('INSERT INTO settings(owner,enabled,connection_id) VALUES(?,?,?)',('alice-id',1,'mock'))
        with patch.object(memory,'distill',return_value=({'items':[{'title':'伪造','body':'无来源结论','source_ids':['invented']}]},{})):
            with self.assertRaises(ValueError):memory.learn(self.user)
        self.assertEqual(memory.entries(self.user),[])
        self.assertEqual(memory.settings('alice-id')['status'],'failed')
        self.assertTrue(memory.settings('alice-id')['error'])

    def test_weekly_tick_reuses_scheduler_and_does_not_repeat(self):
        with memory.database() as db:
            db.execute('INSERT INTO settings(owner,enabled,connection_id) VALUES(?,?,?)',('alice-id',1,'mock'))
        class InlineThread:
            def __init__(self,*,target,**kwargs):self.target=target
            def start(self):self.target()
        with patch('auth.find_user_by_id',return_value=self.user),patch.object(memory.threading,'Thread',InlineThread),patch.object(memory,'distill') as model:
            memory._CHECK_AT=0;memory.tick()
            memory._CHECK_AT=0;memory.tick()
            self.assertFalse(model.called,'no operations must mean no model request')
        self.assertEqual(memory.settings('alice-id')['attempts'],1)
        self.assertEqual(memory.settings('alice-id')['week'],memory.week())


if __name__=='__main__':unittest.main()
