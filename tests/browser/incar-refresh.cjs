// Real Jobs UI, isolated HTTP fixtures. Never contacts a scheduler or production API.
const {build}=require('esbuild');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright-core');
const http=require('node:http'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{
 const built=await build({stdin:{contents:`import React from'react';import{createRoot}from'react-dom/client';import{MemoryRouter}from'react-router-dom';import{App}from'antd';import Jobs from'./src/pages/Jobs';createRoot(document.getElementById('root')).render(<MemoryRouter initialEntries={[location.pathname+location.search]}><App><Jobs/></App></MemoryRouter>);`,loader:'tsx',resolveDir:process.cwd()},bundle:true,write:false,outfile:'/tmp/incar-refresh.js',format:'iife',jsx:'automatic',define:{'process.env.NODE_ENV':'"development"'}});
 const tasks=['calc','other','local'].map(id=>({task_id:id,task_type:'opt',model_name:id,status:'pending',job_id:null,notes:'',remote_dir:'/P/'+id,dir_path:'P/'+id,local_dir:'/P/'+id}));
 const project={id:'p',name:'P',server:'mock',progress:0,tasks};
 const saved={calc:{ENCUT:'623',NELM:'187'},other:{ENCUT:'689',NELM:'171'},local:{}};
 let continued=false,holdInitial=false,releaseInitial;const requests=[];
 const state=id=>{
  const params={ENCUT:continued&&id==='calc'?'647':'411',NELM:continued&&id==='calc'?'187':'100'};
  const draft=saved[id];
  return {task_id:id,synced:id!=='local',source:id==='local'?null:{con:continued&&id==='calc'?'con1':'',kind:'manual'},files:{INCAR:{text:id==='local'?'ENCUT=433\nNELM=91\nMY_FLAG=2\n':Object.entries(params).map(([k,v])=>k+'='+v).join('\n'),...(id==='local'?{}:{params})}},draft:{INCAR:draft},changes:Object.entries(draft).map(([key,to])=>({file:'INCAR',key,from:params[key]||'',to,applied_at:null})),pending:Object.keys(draft).length>0,applied_history:[],poscar_cif:null,contcar_cif:null};
 };
 const server=http.createServer(async(req,res)=>{
  if(!req.url.startsWith('/api/')){res.setHeader('Content-Type',req.url==='/app.js'?'text/javascript':'text/html');return res.end(req.url==='/app.js'?built.outputFiles.find(f=>f.path.endsWith('.js')).text:'<div id="root"></div><script src="/app.js"></script>');}
  requests.push([req.method,req.url]);let data={};
  const parts=req.url.split('/'),id=parts[4],task=tasks.find(t=>t.task_id===id);
  if(req.url==='/api/projects')data={projects:[project]};
  else if(req.url==='/api/task-types')data={task_types:[{type:'opt',description:'OPT',workload_weight:1,subtypes:[]}]};
  else if(req.url.endsWith('/input')){
   data=state(id);
   if(holdInitial&&id==='calc'){
    holdInitial=false;
    releaseInitial=()=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify({success:true,data}));};return;
   }
  }
  else if(req.url.endsWith('/files'))data={files:[{name:'INCAR',size:40}]};
  else if(req.url.endsWith('/files/INCAR'))data={content:state(id).files.INCAR.text};
  else if(req.url.endsWith('/input/draft')){
   let body='';for await(const c of req)body+=c;
   saved[id]=Object.fromEntries(Object.entries(JSON.parse(body).params).filter(([key,value])=>value&&value!==state(id).files.INCAR.params[key]));data=state(id);
  }else if(req.url.endsWith('/input/sync')){saved[id]={ENCUT:'728'};data=state(id);}
  else if(req.url.endsWith('/submit')){task.status='queued';task.job_id='123';data={job_id:'123',new_status:'queued'};}
  else if(req.url.endsWith('/stop')){task.status='pending';task.job_id=null;data={job_id:'123',new_status:'pending',stop_pending:false};}
  else if(req.url.endsWith('/continuation')){continued=true;saved.calc={};data={action:'created',task_id:'child',con:'con1',remote_dir:'/P/calc/con1',warnings:[]};}
  else if(req.url.startsWith('/api/jobs/nodes'))data={nodes:[],queues:[]};
  res.setHeader('Content-Type','application/json');res.end(JSON.stringify({success:true,data}));
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox']});
 const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(10000);
 const encut=page.locator('.job-incar-field').filter({has:page.locator('.job-incar-field__label').getByText('ENCUT',{exact:true})}).locator('input').first();
 const preview=async(value)=>{
  await page.getByRole('button',{name:/预览 INCAR/}).click();
  const drawer=page.locator('.ant-drawer-open');
  await drawer.locator('.file-preview').waitFor();
  assert.match(await drawer.locator('.file-preview').innerText(),new RegExp('ENCUT\\s*=\\s*'+value+'\\b'));
  await drawer.getByRole('button',{name:'Close',exact:true}).click();
  await drawer.waitFor({state:'hidden'});
 };
 const incar=()=>page.getByRole('tab',{name:'INCAR',exact:true}).click();
 const overview=()=>page.getByRole('tab',{name:'概览',exact:true}).click();
 const select=async(id)=>{await page.locator('.job-tree__task-name').getByText(id,{exact:true}).click();};
 try{
  await page.goto('http://127.0.0.1:'+server.address().port+'/?task=calc');await incar();
  await page.waitForFunction(()=>[...document.querySelectorAll('.job-incar-field')].some(e=>e.querySelector('.job-incar-field__label')?.textContent.startsWith('ENCUT')&&e.querySelector('input')?.value==='623'));
  await preview('623');await select('other');assert.equal(await encut.inputValue(),'689');await select('calc');
  await overview();await page.getByRole('button',{name:/提交作业/}).click();
  await page.getByRole('button',{name:/停止作业/}).waitFor();await incar();
  assert.equal(await encut.inputValue(),'623','submit refresh must retain the saved draft, not restore defaults');
  await preview('623');assert.match(await page.locator('.input-source__pending').innerText(),/623/);
  await overview();await page.getByRole('button',{name:/停止作业/}).click();await page.getByRole('button',{name:'停 止',exact:true}).click();
  await page.getByRole('button',{name:/停止作业/}).waitFor({state:'hidden'});await incar();
  assert.equal(await encut.inputValue(),'623','stop refresh must retain the saved draft');await preview('623');
  await page.getByRole('button',{name:/修改参数/}).click();await encut.fill('647');
  await overview();await page.getByRole('button',{name:/提交作业/}).click();await page.getByRole('button',{name:/停止作业/}).waitFor();await incar();
  assert.equal(await encut.inputValue(),'647','status refresh must also retain unconfirmed edits');
  await page.getByRole('button',{name:/确认修改/}).click();
  await page.waitForFunction(()=>document.querySelector('.input-source__pending')?.textContent.includes('647'));
  await preview('647');await overview();await page.getByRole('button',{name:/创建续算/}).click();
  await page.getByRole('dialog').getByRole('button',{name:/创建续算/}).click();await page.getByRole('dialog').waitFor({state:'hidden'});await incar();
  await page.waitForFunction(()=>!document.querySelector('.input-source__pending'));
  assert.equal(await encut.inputValue(),'647','continuation restores newly applied input without reverting parameters');await preview('647');
  await select('other');assert.equal(await encut.inputValue(),'689','continuation must not reset other task drafts');await preview('689');
  await select('local');await page.waitForTimeout(150);assert.equal(await encut.inputValue(),'433');await preview('433');
  holdInitial=true;await page.goto('http://127.0.0.1:'+server.address().port+'/?task=calc');await incar();
  await page.getByRole('button',{name:/同步最新参数/}).click();
  await page.waitForFunction(()=>[...document.querySelectorAll('.job-incar-field')].some(e=>e.querySelector('.job-incar-field__label')?.textContent.startsWith('ENCUT')&&e.querySelector('input')?.value==='728'));
  const oldResponse=page.waitForResponse(r=>r.url().endsWith('/calc/input'));releaseInitial();await oldResponse;await page.waitForTimeout(100);
  assert.equal(await encut.inputValue(),'728','late initial response must not overwrite a newer explicit sync');await preview('728');
  assert.deepEqual(requests.filter(([m])=>m!=='GET').map(([,url])=>url),['/api/jobs/tasks/calc/submit','/api/jobs/tasks/calc/stop','/api/jobs/tasks/calc/submit','/api/jobs/tasks/calc/input/draft','/api/jobs/tasks/calc/continuation','/api/jobs/tasks/calc/input/sync']);
  assert.deepEqual(errors,[]);console.log('PASS INCAR draft/preview consistency through submit, stop, unsaved edits, confirmation, continuation, task switching, local-only inputs and late initial response; only explicit mocked writes.');
 }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
