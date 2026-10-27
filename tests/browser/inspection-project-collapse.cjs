// Real Inspection page, mocked HTTP only; folding must never trigger inspections.
const {build}=require('esbuild');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright-core');
const http=require('node:http'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
  const bundle=await build({stdin:{contents:`
    import {createRoot} from 'react-dom/client';import {MemoryRouter} from 'react-router-dom';import {App} from 'antd';
    import {AuthProvider} from './src/context/AuthContext';import Inspection from './src/pages/Inspection';import './src/styles/global.css';
    createRoot(document.getElementById('root')).render(<App><AuthProvider><MemoryRouter><Inspection/></MemoryRouter></AuthProvider></App>);
  `,resolveDir:path.resolve('.'),loader:'tsx'},bundle:true,write:false,outfile:'app.js',jsx:'automatic',define:{'process.env.NODE_ENV':'"production"'}});
  const files=Object.fromEntries(bundle.outputFiles.map(f=>[f.path.endsWith('.css')?'/app.css':'/app.js',f.text]));
  const results=['Alpha','Beta','Closed'].map((name,i)=>({id:name,task_id:name,task_name:name+' task',project_name:name,
    project_closed:i===2,category:'convergence',task_category:'结构优化',task_status:i===2?'archived':'running',
    status:i===2?'archived':'normal',check_time:'2026-10-27 12:00:00',message:'状态正常',detail:'',has_inspection:true}));
  const requests=[];
  const server=http.createServer((req,res)=>{
    if(req.url.startsWith('/api/')){
      requests.push({url:req.url,method:req.method});res.setHeader('Content-Type','application/json');
      res.end(JSON.stringify({success:true,data:req.url==='/api/inspections'?{results}:{enabled:false,interval_hours:2}}));return;
    }
    res.setHeader('Content-Type',req.url==='/app.js'?'text/javascript':req.url==='/app.css'?'text/css':'text/html; charset=utf-8');
    res.end(files[req.url]||'<meta charset="utf-8"><div id="root"></div><link rel="stylesheet" href="/app.css"><script src="/app.js"></script>');
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox']});
  try{
    const page=await browser.newPage();page.setDefaultTimeout(10000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:'+server.address().port);
    const block=name=>page.locator('.inspection-project').filter({has:page.locator('.inspection-project__name').filter({hasText:new RegExp('^'+name+'$')})});
    const header=name=>block(name).locator('.inspection-project__head');
    await header('Alpha').waitFor();
    assert.equal(await header('Alpha').getAttribute('aria-expanded'),'true');
    assert.equal(await header('Closed').getAttribute('aria-expanded'),'false');
    await header('Alpha').click();await block('Alpha').locator('.ant-table').waitFor({state:'detached'});
    assert.equal(await header('Alpha').getAttribute('aria-expanded'),'false');
    assert.equal(await block('Beta').locator('.ant-table').isVisible(),true,'other active projects stay expanded');
    await header('Closed').click();await block('Closed').locator('.ant-table').waitFor();
    await header('Closed').press('Enter');await block('Closed').locator('.ant-table').waitFor({state:'detached'});
    const search=page.getByPlaceholder('搜索项目 / 任务 / 信息');await search.fill('Beta');await block('Alpha').waitFor({state:'detached'});
    await search.fill('');await header('Alpha').waitFor();
    assert.equal(await header('Alpha').getAttribute('aria-expanded'),'true','filtering retains existing default reset behavior');
    await header('Alpha').click();await block('Alpha').locator('.ant-table').waitFor({state:'detached'});
    await header('Alpha').press('Space');await block('Alpha').locator('.ant-table').waitFor();
    assert.equal(await header('Alpha').getAttribute('aria-expanded'),'true');
    assert.equal(await header('Closed').getAttribute('aria-expanded'),'false');
    assert.deepEqual(requests.map(r=>r.method+' '+r.url).sort(),['GET /api/inspections','GET /api/inspections/meta']);
    assert.deepEqual(errors,[]);
    console.log('PASS active/closed defaults, independent folding, re-expansion, keyboard, unchanged filter reset; no inspection or extra requests');
  }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
