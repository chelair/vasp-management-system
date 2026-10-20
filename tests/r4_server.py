"""Isolated R4 real HTTP/SSE server + deterministic mock model, never production."""
import copy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading


def setup(root):
    import auth,ai_chat_store,storage,properties,checks_store
    import r3_fixtures
    from dates import now_iso
    from r2_science_fixtures import seed_science
    user,_=auth.create_user('tester');token,_=auth.create_session(user)
    projects=[];all_rows=[]
    for pid in ('full','partial','multi','empty'):
        p,rows=r3_fixtures.seed(root/pid)
        p.update(project_id=pid,name='R4_'+pid)
        for task in p['tasks']:
            task['task_id']=pid+'_'+task['task_id'];task['job_id']=task['task_id'];task['dir_path']=task['dir_path'].replace('R3P/',p['name']+'/')
        for row in rows:
            row.update(task_id=pid+'_'+row['task_id'],job_id=pid+'_'+row['job_id'],project_name=p['name'])
        if pid=='multi':
            run=root/'multi/runs/a_d2/con1'
            row=copy.deepcopy(rows[1]);row.update(task_id='multi_a_d2',job_id='multi_a_d2',remote_dir=str(run.parent),last_energy=-91)
            row['current_output']['dir']=str(run)
            row['property_evidence']=r3_fixtures.write_run(run,r3_fixtures.poscar(defect=True,site=3),-91)
            rows.append(row)
            p['tasks'].append({**p['tasks'][1],'task_id':'multi_a_d2','job_id':'multi_a_d2','model_name':'LMR_vac_site2','remote_dir':str(run.parent)})
        if pid=='empty':p['tasks']=[];rows=[]
        projects.append(p);all_rows+=rows
    dos={'project_id':'dos','name':'R4_DOS','owner':'tester','tasks':[],'server':'fixture'}
    electronic=seed_science(root,dos)
    row=copy.deepcopy(all_rows[0]);row.update(task_id='t_ele',task_type='ele',project_name=dos['name'],remote_dir='R4_DOS/ele/Electronic',job_id=None)
    row['current_output']={'latest_dir':'','dir':'R4_DOS/ele/Electronic'};all_rows.append(row);projects.append(dos)
    from adsorption_fixtures import seed as seed_adsorption
    for pid,kwargs in [('ads',{}),('ads_multi',{'multiple':True}),('ads_missing',{'missing_reference':True}),('ads_gas',{'isolated':True}),('ads_pending',{})]:
        p,rows=seed_adsorption(root/pid,pid,**kwargs)
        if pid=='ads_pending':
            for task in p['tasks']:
                if task['task_id']==pid+'_a_c':task['model_name']='H2@LMR'
                if task['task_id']==pid+'_mol':task['current_output']={'latest_dir':'con_unknown'}
            rows[0].pop('property_evidence')
            old=copy.deepcopy(rows[-1]);old['current_output']={'latest_dir':'con0','dir':str(root/'old/con0')};rows.append(old)
        if pid=='ads':
            from task_paths import task_dir
            import shutil
            for task in p['tasks']:
                mirror=task_dir(p['name'],task)/'files';mirror.mkdir(parents=True,exist_ok=True)
                original=Path(task['remote_dir'])/'con1'
                for name in ('POSCAR','CONTCAR'):
                    source=original/name
                    if not source.is_file():source=original/'POSCAR'
                    shutil.copy2(source,mirror/name)
        projects.append(p);all_rows+=rows
    checks_store.CHECKS_DIR.mkdir(parents=True,exist_ok=True)
    (checks_store.CHECKS_DIR/'check_results_r4.json').write_text(json.dumps(all_rows))
    checks_store.invalidate_cache()
    storage.save_db({'projects':projects})
    request=r3_fixtures.request();request['project_ids']=['full']
    for t in request['targets']:
        for role in ('pristine','defect'):t[role]['task_id']='full_'+t[role]['task_id']
    properties.evaluate({'projects':projects},user,request,persist=True)
    return user,token,projects


class Provider(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append(payload)
        history=[json.loads(m['content']) for m in payload['messages'] if m['role']=='tool']
        count=len(history)
        if payload['model']=='topic-failure' and count>=2:
            self.send_response(503);self.end_headers();self.wfile.write(b'fixture model failure');return
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
        if not payload.get('tools'):
            text=json.dumps({'text':'根据冻结事实 [[F01]]，这是重新组织的段落；未验证条件仍需保留。'},ensure_ascii=False)
            event={'content':text};reason='stop'
        elif payload['model']=='flexible-report-model':
            if count==0:
                event={'tool_calls':[{'index':0,'id':'find_inputs','type':'function','function':{'name':'search_report_data','arguments':'{}'}}]};reason='tool_calls'
            elif count==1:
                args={'property_id':'adsorption.simple','model_queries':['一号板'],'adsorbate_query':'以前那个气体',
                      'targets':[{'surface':{'task_id':'ads_missing_a_s'},'complex':{'task_id':'ads_missing_a_c'},'adsorbate':{'label':'用户已算过的气体','energy_ev':-3,'source_quote':'气体能量 -3 eV'}}]}
                event={'tool_calls':[{'index':0,'id':'use_user_inputs','type':'function','function':{'name':'create_topic_report','arguments':json.dumps(args)}}]};reason='tool_calls'
            else:event={'content':'已按你的意思生成报告。'};reason='stop'
        elif payload['model']=='simple-report-model':
            if count==0:
                args={'property_id':'adsorption.simple','model_queries':['LMR'],'adsorbate_query':'H2'}
                event={'tool_calls':[{'index':0,'id':'simple_report','type':'function','function':{'name':'create_topic_report','arguments':json.dumps(args)}}]};reason='tool_calls'
            else:event={'content':'已整理好报告。需要确认时，在下方选择即可。'};reason='stop'
        elif payload['model'].startswith('topic-hostile'):
            if count==0:
                args={'property_id':'oxygen_vacancy.neutral_single','model_queries':['LMR','LIC@LMR']}
                if payload['model']=='topic-hostile-site':args['targets']=[{'label':'LMR','pristine':{'project_id':'multi','task_id':'multi_a_p'},'defect':{'project_id':'multi','task_id':'multi_a_d'}}]
                else:args['reference_report_id']='prop_unconfirmed_reference'
                event={'tool_calls':[{'index':0,'id':'hostile_call','type':'function','function':{'name':'prepare_topic_report','arguments':json.dumps(args)}}]};reason='tool_calls'
            else:event={'content':'需要用户明确选择任务位点或参考态。'};reason='stop'
        elif count<4:
            question=payload['messages'][-1]['content'] if count==0 else ''
            if count==0:
                args={'property_id':'dos.comparison' if 'DOS' in question else 'oxygen_vacancy.neutral_single',
                      'model_queries':['Electronic'] if 'DOS' in question else ['NoExistingModel'] if '无数据' in question else ['LMR','LIC@LMR']}
                if 'DOS' not in question:args['common_oxygen_reference']=True
                if '吸附' in question:
                    args={'property_id':'adsorption.simple','model_queries':['LMR','LIC@LMR'],'adsorbate_query':'H2'}
                    if '气相' in question:args['adsorbate_reference_type']='isolated_molecule'
                name='prepare_topic_report'
            elif count==1:
                prior=history[-1]
                name='plan_topic_report'
                args={'topic_id':prior['topic_id'],'expected_revision':prior['revision'],'title':'吸附能比较专题' if prior['request']['property_id']=='adsorption.simple' else '氧空位比较科研报告' if prior['property_definition'].get('definition')!='已有DOS/PDOS曲线比较' else 'DOS比较专题',
                      'selections':[{'block_id':c['block_id'],'reason':'提供当前问题所需的计算事实与条件','section':'results' if c['type'] in ('task.energy_force','ele.pdos') else 'sources','order':i,'essential':c.get('science_status') in ('AVAILABLE','VISUAL_ONLY')} for i,c in enumerate(prior['candidates']) if c['type'] in ('task.params','task.energy_force','ele.pdos')]}
            elif count==2:
                prior=history[-1];prepared=history[0]
                name='write_topic_draft'
                text='所选数据依据为 [[F01]]。该解释限定于已列出的条件，不能替代尚未完成的验证。' if prepared['facts'] else '尚无可计算的相关数据。需要补齐模型、科学对应关系与参考态；不填充虚构结果。'
                args={'topic_id':prior['topic_id'],'expected_revision':prior['revision'],'paragraphs':[{'section':'analysis','title':'对比分析与局限','text':text,'kind':'analysis'}]}
            else:
                prior=history[-1];name='save_topic_report';args={'topic_id':prior['topic_id'],'expected_revision':prior['revision']}
            event={'tool_calls':[{'index':0,'id':f'topic_call_{count}','type':'function','function':{'name':name,'arguments':json.dumps(args,ensure_ascii=False)}}]};reason='tool_calls'
        else:
            event={'content':'已根据科学数据检查生成独立专题报告。可在本对话的“专题报告”中打开、编辑、保存和导出；缺口及未验证条件已保留。'};reason='stop'
        frame={'choices':[{'delta':event,'finish_reason':reason}],'usage':{'total_tokens':12}}
        self.wfile.write(('data: '+json.dumps(frame,ensure_ascii=False)+'\n\ndata: [DONE]\n\n').encode());self.wfile.flush()


def main():
    with tempfile.TemporaryDirectory(prefix='vasp-r4-http-') as directory:
        root=Path(directory)
        os.environ['VASP_WEB_DATA_DIR']=str(root)
        os.environ['VASP_AI_KEY_FILE']=str(root/'private/ai.key')
        sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'backend'),str(Path(__file__).resolve().parent)]
        import auth,config,ai_chat_store,ai_chat_service,ssh,permissions,uvicorn
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from middleware.auth import install
        from routers import ai_chat,topic_reports
        if len(sys.argv)>1:
            import report_interactive
            report_interactive.RUNTIME_PATH=Path(sys.argv[1])
        config.ensure_data_dirs()
        user,token,projects=setup(root)
        provider=ThreadingHTTPServer(('127.0.0.1',0),Provider);provider.daemon_threads=True;provider.requests=[]
        thread=threading.Thread(target=provider.serve_forever,daemon=True);thread.start()
        secret='r4-synthetic-private-key-never-return'
        connection=ai_chat_store.save_connection(str(user['user_id']),{'name':'隔离模拟模型','base_url':f'http://127.0.0.1:{provider.server_port}/v1','model':'topic-fixture','api_key':secret,'max_tokens':4096})
        fail_connection=ai_chat_store.save_connection(str(user['user_id']),{'name':'失败模拟模型','base_url':f'http://127.0.0.1:{provider.server_port}/v1','model':'topic-failure','api_key':secret,'max_tokens':4096})
        hostile={}
        for kind in ('site','reference'):
            hostile[kind]=ai_chat_store.save_connection(str(user['user_id']),{'name':'越权选择模拟','base_url':f'http://127.0.0.1:{provider.server_port}/v1','model':'topic-hostile-'+kind,'api_key':secret,'max_tokens':4096})['id']
        conversations={}
        for p in projects:
            c=ai_chat_store.create_conversation(str(user['user_id']),p['name']+'专题会话',None,connection['id'],p['project_id'])
            conversations[p['project_id']]=c['id']
        def forbid(*args,**kwargs):raise AssertionError('R4 HTTP fixture does not access HPC')
        ssh._get_client=forbid
        app=FastAPI();install(app);app.include_router(ai_chat.router,prefix='/api');app.include_router(topic_reports.router,prefix='/api')
        @app.exception_handler(permissions.PermissionDenied)
        async def denied(request,exc):return JSONResponse(status_code=403,content={'success':False,'message':str(exc)})
        @app.get('/api/__test/provider-requests')
        def provider_requests():
            return [{'model':p['model'],'effort':p.get('reasoning_effort'),'thinking':p.get('thinking'),'tools':bool(p.get('tools'))} for p in provider.requests]
        @app.post('/__test/mutate')
        def mutate():
            path=root/'checks/check_results_r4.json';rows=json.loads(path.read_text());rows[1]['last_energy']=-1;path.write_text(json.dumps(rows));return {'ok':True}
        sock=socket.socket();sock.bind(('127.0.0.1',0))
        print(json.dumps({'port':sock.getsockname()[1],'token':token,'conversations':conversations,'connection':connection['id'],'failure_connection':fail_connection['id'],'hostile_connections':hostile}),flush=True)
        try:uvicorn.Server(uvicorn.Config(app,log_level='error')).run(sockets=[sock])
        finally:provider.shutdown();provider.server_close()


if __name__=='__main__':main()
