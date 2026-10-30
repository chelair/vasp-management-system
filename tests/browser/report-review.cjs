// Real Report page -> isolated report API -> local mock model -> same report/export.
const {build}=require('esbuild');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || '/tmp/vasp-todo-browser/node_modules/playwright-core');
const {spawn}=require('node:child_process');
const http=require('node:http'),path=require('node:path'),fs=require('node:fs/promises'),os=require('node:os'),assert=require('node:assert/strict');

(async()=>{
 let python,server,browser;
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'vasp-review-browser-'));
 try{
  python=spawn('.venv/bin/python',['tests/review_browser_server.py'],{cwd:process.cwd(),stdio:['ignore','pipe','pipe']});
  let logs='';python.stderr.on('data',d=>logs+=d);
  const config=await new Promise((resolve,reject)=>{let pending='';const timer=setTimeout(()=>reject(Error('Fixture startup: '+logs)),15000);python.stdout.on('data',data=>{pending+=data;const line=pending.split('\n').find(line=>line.startsWith('{"base"'));if(line){clearTimeout(timer);resolve(JSON.parse(line));}});python.on('exit',code=>reject(Error('Fixture exited '+code+' '+logs)));});
  const built=await build({stdin:{contents:`import React from 'react';import{createRoot}from'react-dom/client';import{App}from'antd';import{MemoryRouter}from'react-router-dom';import Report from './src/pages/Report';import './src/styles/global.css';createRoot(document.getElementById('root')).render(<MemoryRouter><App><Report/></App></MemoryRouter>);`,loader:'tsx',resolveDir:process.cwd()},bundle:true,write:false,outfile:path.join(dir,'app.js'),format:'iife',jsx:'automatic',define:{'process.env.NODE_ENV':'"development"'}});
  const js=built.outputFiles.find(f=>f.path.endsWith('.js')).text,css=built.outputFiles.find(f=>f.path.endsWith('.css')).text;
  server=http.createServer(async(req,res)=>{
   if(req.url==='/app.js'){res.setHeader('Content-Type','text/javascript');return res.end(js);}
   if(req.url==='/app.css'){res.setHeader('Content-Type','text/css');return res.end(css);}
   if(req.url.startsWith('/3dmol/')){res.setHeader('Content-Type','text/javascript');return res.end(await fs.readFile(path.join('public',req.url)));}
   if(req.url==='/api/projects'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({success:true,data:{projects:[{id:'p',name:'ReportFixture',owner:'alice',tasks:[],deadline:'2026-12-01',ai_report_notes_enabled:true}]}}));}
   if(req.url==='/api/ai/chat/connections'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({success:true,data:{items:[{id:config.connection,name:'隔离模型',model:'mock'}]}}));}
   if(req.url.startsWith('/api/')){
    const proxy=http.request(config.base+req.url,{method:req.method,headers:{...req.headers,host:new URL(config.base).host}},result=>{res.writeHead(result.statusCode,result.headers);result.pipe(res);});
    proxy.on('error',e=>{res.writeHead(502);res.end(e.message);});req.pipe(proxy);return;
   }
   res.setHeader('Content-Type','text/html');res.end('<meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/app.css"><div id="root"></div><script src="/app.js"></script>');
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const url='http://127.0.0.1:'+server.address().port;
  browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1440,height:1050}});const errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().startsWith('https://example.invalid'))external.push(r.url());});
  await page.goto(url);await page.locator('.report-content h6').filter({hasText:'Model'}).waitFor();
  const module=page.locator('.report-content h6').filter({hasText:'Model'});
  await module.getByRole('button',{name:'批注',exact:true}).click();
  await page.getByLabel('新的报告批注').fill('浏览器私有批注：请补充说明，保留3D和图表');
  await page.getByRole('button',{name:'保存批注',exact:true}).click();
  const comment=page.locator('.report-review-comment').last();await comment.getByText('待处理',{exact:true}).waitFor();
  await page.getByRole('combobox',{name:'批注处理模型'}).click();await page.getByText('隔离模型 · mock',{exact:true}).click();
  await comment.getByRole('button',{name:'让AI处理',exact:true}).click();await comment.getByText('已完成',{exact:true}).waitFor();
  await page.locator('.report-content').getByText('浏览器核对后的报告解释，原有结构交互继续保留。',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>window.REVIEW_XSS),undefined);assert.deepEqual(external,[]);
  assert.ok(await page.locator('.report-3d').count()>=2);
  await page.getByRole('button',{name:'Close',exact:true}).last().click();
  await page.locator('.report-3d').first().getByText('初始（POSCAR）',{exact:true}).click();
  await page.locator('[data-panel="free-energy"]').waitFor();
  await page.locator('.report-content h6').filter({hasText:'Path'}).getByRole('button',{name:'批注',exact:true}).click();
  await page.getByLabel('新的报告批注').fill('只对比四个结构，按我选定的顺序展示；保留台阶图和三维窗口。');
  await page.getByRole('button',{name:'保存批注',exact:true}).click();
  const pathComment=page.locator('.report-review-comment').last();
  await pathComment.getByText('待处理',{exact:true}).waitFor();
  await pathComment.getByRole('button',{name:'让AI处理',exact:true}).click();
  await pathComment.getByText('已完成',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Close',exact:true}).last().click();
  assert.equal(await page.locator('.report-fe3d__btn').count(),4);
  assert.equal((await page.locator('.report-fe3d__btn').first().textContent()).trim(),'结构 4');
  await page.locator('.report-fe3d__btn').filter({hasText:'结构 1'}).click();
  assert.ok((await page.locator('.report-fe3d__btn.is-on').textContent()).includes('结构 1'));
  assert.equal(await page.locator('[data-panel="free-energy"]').count(),1);
  await page.reload();await page.getByRole('button',{name:'报告批注',exact:true}).click();
  await page.getByText('浏览器私有批注：请补充说明，保留3D和图表',{exact:true}).waitFor();
  await page.getByText('已完成',{exact:true}).last().waitFor();
  assert.equal(await page.locator('.report-review-comment').first().getByRole('button',{name:'让AI处理'}).isDisabled(),true);
  await page.locator('.report-review-comment').first().getByRole('button',{name:'重新打开'}).click();
  await page.locator('.report-review-comment').first().getByText('待处理',{exact:true}).waitFor();
  await page.locator('.report-review-comment').first().locator('textarea').fill('补充一句：保持现有结构展示');
  await page.locator('.report-review-comment').first().getByRole('button',{name:'发送回复',exact:true}).click();
  await page.getByText('补充一句：保持现有结构展示',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Close',exact:true}).last().click();
  await page.getByRole('button',{name:/导\s*出$/}).click();
  const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:/下载 HTML/}).click()]);
  const html=await fs.readFile(await download.path(),'utf8');assert.ok(html.includes('浏览器核对后的报告解释'));assert.ok(html.includes('data-report-widget="structure-3d"'));assert.ok(!html.includes('浏览器私有批注'));assert.ok(!html.includes('批注回复专用内容'));
  await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:/报告批注/}).click();
  await page.waitForTimeout(500);
  const bounds=await page.locator('.ant-drawer-content').last().boundingBox();assert.ok(bounds.width<=390 && bounds.x>=-1 && bounds.x+bounds.width<=391);
  await page.screenshot({path:path.join(dir,'review-mobile.png')});
  assert.deepEqual(errors,[]);console.log('PASS report review: module comment, saved reply/status, AI scoped edit, reload/reopen, original 3D controls, export exclusion and mobile. '+dir);
 }finally{await browser?.close();if(server)await new Promise(r=>server.close(r));python?.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
