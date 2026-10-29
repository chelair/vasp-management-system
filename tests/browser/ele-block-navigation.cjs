// Real dashboard link -> Jobs page, with mocked read-only HTTP responses.
const {build}=require('esbuild');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright-core');
const http=require('node:http'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{
 const bundle=await build({stdin:{contents:`
 import {createRoot} from 'react-dom/client';import {MemoryRouter,Routes,Route,Link} from 'react-router-dom';import {App} from 'antd';
 import Jobs from './src/pages/Jobs';import RunningTasksPanel from './src/components/dashboard/RunningTasksPanel';
 const jobs=[{task_id:'blockA',task_name:'Main_diff1',job_id:'101',status:'RUN',project_name:'P',server:'mock'}];
 createRoot(document.getElementById('root')).render(<MemoryRouter initialEntries={[location.pathname+location.search]}><App>
 <nav><Link to='/jobs?task=blockB'>跳转分块B</Link><Link to='/jobs?task=main'>跳转主任务</Link></nav>
 <Routes><Route path='/' element={<RunningTasksPanel jobs={jobs} onRefresh={()=>{}}/>}/><Route path='/jobs' element={<Jobs/>}/></Routes>
 </App></MemoryRouter>);`,resolveDir:path.resolve('.'),loader:'tsx'},bundle:true,write:false,jsx:'automatic',format:'iife',define:{'process.env.NODE_ENV':'"production"'}});
 const task=(id,type,extra={})=>({task_id:id,task_type:type,model_name:id==='main'?'Main':id,status:'running',last_energy:null,last_check_time:null,job_id:'101',notes:'',continuation_ready:false,continuation_dir:null,remote_dir:'/P/'+id,local_dir:'/P/'+id,...extra});
 const tasks=[task('main','ele'),task('blockA','ele_diff',{subtype:'diff_charge',parent_task_id:'main',ele_block:1,ele_block_label:'分块A',ele_block_atoms:[1]}),task('blockB','ele_diff',{subtype:'diff_charge',parent_task_id:'main',ele_block:2,ele_block_label:'分块B',ele_block_atoms:[2]})];
 const project={id:'p',name:'P',server:'mock',status:'active',progress:0,remainingHours:0,tasks};
 const requests=[];
 const input=id=>({task_id:id,synced:true,source:{remote_dir:'/P/'+id,kind:'manual'},files:{INCAR:{text:'NSW=0\nIBRION=-1\nENCUT='+({main:411,blockA:422,blockB:433}[id]||411)+'\n',params:{NSW:'0',IBRION:'-1',ENCUT:String({main:411,blockA:422,blockB:433}[id]||411)}}},draft:{},pending:false,changes:[],applied_history:[],poscar_cif:null,contcar_cif:null});
 const server=http.createServer((req,res)=>{
  if(!req.url.startsWith('/api/')){res.setHeader('Content-Type',req.url==='/app.js'?'text/javascript':'text/html');res.end(req.url==='/app.js'?bundle.outputFiles[0].text:'<div id="root"></div><script src="/app.js"></script>');return;}
  requests.push({url:req.url,method:req.method});let data={};const id=req.url.split('/')[4];
  if(req.url==='/api/projects')data={projects:[project]};
  else if(req.url==='/api/task-types')data={task_types:[{type:'ele',description:'电子结构',workload_weight:.4,subtypes:[]}]};
  else if(/\/input$/.test(req.url))data=input(id);
  else if(/\/files$/.test(req.url))data={files:[{name:'INCAR',size:30}]};
  else if(/\/files\/INCAR$/.test(req.url))data={content:input(id).files.INCAR.text};
  else if(req.url.startsWith('/api/jobs/nodes'))data={nodes:[],queues:[]};
  res.setHeader('Content-Type','application/json');res.end(JSON.stringify({success:true,data}));
 });
 let browser;
 try{
  await new Promise(r=>server.listen(0,'127.0.0.1',r));const base='http://127.0.0.1:'+server.address().port;
  browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox']});
  const page=await browser.newPage();page.setDefaultTimeout(12000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const active=label=>page.locator('.ant-tabs-tab-active').filter({hasText:label});
  const encut=page.locator('.job-incar-field:visible').filter({has:page.locator('.job-incar-field__label').getByText('ENCUT',{exact:true})}).locator('input').first();
  const waitEnc=async value=>{await page.waitForFunction(value=>[...document.querySelectorAll('.job-incar-field')].some(row=>row.getClientRects().length>0&&row.querySelector('.job-incar-field__label')?.textContent.startsWith('ENCUT')&&row.querySelector('input')?.value===value),value);assert.equal(await encut.inputValue(),value);};
  await page.goto(base);await page.getByText('Main_diff1',{exact:true}).click();
  await active('分块A').waitFor();await page.getByText('电子结构任务 + 差分电荷 2 个分块',{exact:true}).waitFor();
  await page.getByRole('tab',{name:'INCAR',exact:true}).click();await waitEnc('422');
  await page.getByRole('link',{name:'跳转分块B',exact:true}).click();await active('分块B').waitFor();await waitEnc('433');
  await page.getByRole('link',{name:'跳转主任务',exact:true}).click();await active('主任务').waitFor();await waitEnc('411');
  await page.goto(base+'/jobs?task=blockB&tab=incar');await active('分块B').waitFor();await waitEnc('433');
  assert.deepEqual(requests.filter(r=>r.method!=='GET'),[]);assert.deepEqual(errors,[]);
  console.log('PASS: dashboard fragment link, in-place fragment/main navigation and refreshed deep link open the correct electronic-structure tab and inputs; GET only.');
 }finally{if(browser)await browser.close();await new Promise(r=>server.close(r));}
})().catch(error=>{console.error(error);process.exitCode=1;});
