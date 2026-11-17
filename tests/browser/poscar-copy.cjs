// Real Jobs page and isolated HTTP files: no production data, SSH or scheduler.
const {build}=require('esbuild');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright-core');
const http=require('node:http'),fs=require('node:fs/promises'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{
 const bundle=await build({stdin:{contents:`import {createRoot} from 'react-dom/client';import {MemoryRouter} from 'react-router-dom';import {App} from 'antd';import Jobs from './src/pages/Jobs';createRoot(document.getElementById('root')).render(<MemoryRouter initialEntries={['/?task=target']}><App><Jobs/></App></MemoryRouter>);`,loader:'tsx',resolveDir:process.cwd()},bundle:true,write:false,outfile:'/tmp/vasp-poscar-copy.js',jsx:'automatic',format:'iife',define:{'process.env.NODE_ENV':'"production"'}});
 const poscar=label=>`${label}\n1.0\n10 0 0\n0 10 0\n0 0 10\nC O\n1 1\nDirect\n0.1 0.1 0.1\n0.2 0.2 0.2\n`;
 const tasks=['target','source','missing','invalid'].map(id=>({task_id:id,task_type:'opt',model_name:id,status:'pending',job_id:null,notes:'',remote_dir:'/P/'+id,dir_path:'P/'+id,local_dir:'/P/'+id}));
 const projects=[{id:'p',name:'TargetProject',server:'mock',tasks:tasks.slice(0,1)},
  {id:'q',name:'OtherProject',server:'mock',tasks:tasks.slice(1)}];
 const files={target:poscar('original-target'),source:poscar('actual-unopened-source'),invalid:'not a structure'};
 const kpoints='custom-kpoints\n0\nGamma\n7 8 9\n0 0 0\n';
 const state=id=>({task_id:id,synced:false,source:null,files:{POSCAR:{text:files[id]},INCAR:{text:'ENCUT=533\n',params:{ENCUT:'533'}},KPOINTS:{text:kpoints,mesh:[7,8,9]}},draft:{},changes:[],pending:false,applied_history:[],poscar_cif:null,contcar_cif:null});
 const requests=[];let holdRead=false,holdWrite=false,failWrite=false,releaseRead,releaseWrite;
 const server=http.createServer(async(req,res)=>{
  if(!req.url.startsWith('/api/')){
   if(req.url==='/3dmol/3Dmol-min.js'){res.setHeader('Content-Type','text/javascript');return res.end(await fs.readFile('public/3dmol/3Dmol-min.js'));}
   res.setHeader('Content-Type',req.url==='/app.js'?'text/javascript':'text/html');return res.end(req.url==='/app.js'?bundle.outputFiles.find(f=>f.path.endsWith('.js')).text:'<div id="root"></div><script src="/app.js"></script>');
  }
  const entry={method:req.method,url:req.url};requests.push(entry);let data={},status=200,message='ok';const id=req.url.split('/')[4];
  const send=()=>{res.statusCode=status;res.setHeader('Content-Type','application/json');res.end(JSON.stringify({success:status===200,message,data}));};
  if(req.url==='/api/projects')data={projects};
  else if(req.url==='/api/task-types')data={task_types:[{type:'opt',description:'OPT',workload_weight:1,subtypes:[]}]};
  else if(req.url.endsWith('/input'))data=state(id);
  else if(req.url.endsWith('/files'))data={files:[{name:'POSCAR',size:(files[id]??'').length},{name:'INCAR',size:10},{name:'KPOINTS',size:50}]};
  else if(req.url.endsWith('/files/POSCAR')){
   if(req.method==='PUT'){
    let body='';for await(const part of req)body+=part;entry.content=JSON.parse(body).content;
    const save=()=>{if(failWrite){status=500;message='保存测试失败';}else{files[id]=entry.content;data={name:'POSCAR',path:'/P/'+id+'/files/POSCAR',size:files[id].length,state:state(id)};}send();};
    if(holdWrite){releaseWrite=save;return;}save();return;
   }
   if(id==='missing'){status=404;message='来源 POSCAR 不存在';}else data={name:'POSCAR',path:'/P/'+id+'/files/POSCAR',content:files[id]};
   if(holdRead&&id==='source'){releaseRead=send;return;}
  }else if(req.url.endsWith('/files/INCAR'))data={content:'ENCUT=533\n'};
  else if(req.url.endsWith('/files/KPOINTS'))data={content:kpoints};
  else if(req.url.startsWith('/api/jobs/nodes'))data={nodes:[],queues:[]};
  send();
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1100}});page.setDefaultTimeout(10000);const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error(e.message)});
  try {
  await page.goto('http://127.0.0.1:'+server.address().port);await page.getByRole('tab',{name:'POSCAR',exact:true}).click();
  await page.getByRole('button',{name:/查看原文/}).click();const raw=page.locator('pre.file-preview').filter({hasText:'original-target'});await raw.waitFor();
  assert.equal(requests.filter(r=>r.url.includes('/source/files/POSCAR')).length,0,'source has never been opened or prefetched');
  const dialog=page.getByRole('dialog',{name:'从其他任务复制 POSCAR'});
  const choose=async id=>{await page.getByRole('button',{name:/从其他任务复制$/}).click();await dialog.getByPlaceholder('搜索项目 / 作业名 / 任务类型').fill(id);await dialog.locator('.task-picker__item').filter({has:page.getByText(id,{exact:true})}).click();};
  await choose('source');assert.equal(await dialog.locator('.task-picker__name').filter({hasText:/^target$/}).count(),0);
  holdRead=true;holdWrite=true;await dialog.getByRole('button',{name:/^复\s*制$/}).click();
  while(!releaseRead)await new Promise(r=>setTimeout(r,10));
  assert.equal(await dialog.isVisible(),true);assert.equal(requests.filter(r=>r.method==='PUT').length,0);assert.equal(await page.getByText('已从选中任务复制 POSCAR 并保存到本地任务目录',{exact:true}).count(),0);
  holdRead=false;releaseRead();releaseRead=null;
  while(!releaseWrite)await new Promise(r=>setTimeout(r,10));
  assert.equal(await dialog.isVisible(),true);assert.equal(files.target,poscar('original-target'));assert.ok((await raw.textContent()).includes('original-target'));
  holdWrite=false;releaseWrite();releaseWrite=null;await dialog.waitFor({state:'hidden'});
  assert.equal(files.target,files.source);assert.ok((await page.locator('pre.file-preview').innerText()).includes('actual-unopened-source'));
  assert.equal(requests.filter(r=>r.method==='PUT')[0].content,files.source);
  assert.ok(!files.target.includes('演示占位数据'));
  files.source=poscar('fresh-source-after-first-copy');await choose('source');await dialog.getByRole('button',{name:/^复\s*制$/}).click();await dialog.waitFor({state:'hidden'});assert.equal(files.target,files.source);
  for(const id of ['missing','invalid','source']){
   const before=files.target,count=requests.filter(r=>r.method==='PUT').length;failWrite=id==='source';await choose(id);await dialog.getByRole('button',{name:/^复\s*制$/}).click();
   const error=id==='missing'?'读取来源 POSCAR 失败：来源 POSCAR 不存在':id==='invalid'?'无法解析来源 POSCAR，请检查所选任务的结构文件':'POSCAR 保存失败：保存测试失败';
   await page.getByText(error,{exact:true}).waitFor();assert.equal(await dialog.isVisible(),true);assert.equal(files.target,before);assert.ok((await page.locator('pre.file-preview').innerText()).includes('fresh-source-after-first-copy'));
   assert.equal(requests.filter(r=>r.method==='PUT').length-count,id==='source'?1:0);
   await dialog.getByRole('button',{name:/^取\s*消$/}).click();await dialog.waitFor({state:'hidden'});
  }
  await Promise.all([page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().endsWith('/files/POSCAR')&&r.status()===500),page.locator('input[type="file"]').setInputFiles({name:'local.vasp',mimeType:'text/plain',buffer:Buffer.from(poscar('local-import-must-not-leak'))})]);await page.getByText('POSCAR 保存失败：保存测试失败',{exact:true}).last().waitFor();assert.ok(!(await page.locator('pre.file-preview').innerText()).includes('local-import-must-not-leak'));
  failWrite=false;await page.locator('input[type="file"]').setInputFiles({name:'local-success.vasp',mimeType:'text/plain',buffer:Buffer.from(poscar('local-import-success'))});await page.getByText('POSCAR 已导入并保存到本地任务目录',{exact:true}).waitFor();assert.equal(files.target,poscar('local-import-success'));
  await page.getByRole('tab',{name:'KPOINTS',exact:true}).click();assert.ok((await page.locator('body').innerText()).includes('custom-kpoints'),'copy/import must preserve existing KPOINTS');
  assert.ok(requests.filter(r=>r.method!=='GET').every(r=>r.method==='PUT'&&r.url==='/api/jobs/tasks/target/files/POSCAR'),'only target local POSCAR may be written');assert.deepEqual(errors,[]);
  console.log('PASS unopened cross-project source, fresh reads, save completion feedback, missing/invalid/save failures preserve target, local import result, unchanged KPOINTS, no remote actions.');
  }catch(e){console.error((await page.locator('body').innerText()).slice(-4500));console.error(JSON.stringify(requests));throw e;}
 }finally{releaseRead?.();releaseWrite?.();await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
