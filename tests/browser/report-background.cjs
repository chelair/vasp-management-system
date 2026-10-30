// Real report page -> temporary API / run store / SSE -> local mock model.
const {build}=require('esbuild'),{chromium}=require(process.env.PLAYWRIGHT_MODULE||'/tmp/vasp-todo-browser/node_modules/playwright-core');
const {spawn}=require('node:child_process'),http=require('node:http'),path=require('node:path'),fs=require('node:fs/promises'),os=require('node:os'),assert=require('node:assert/strict');
(async()=>{
 let python,server,browser;const dir=await fs.mkdtemp(path.join(os.tmpdir(),'vasp-report-background-browser-'));
 try{
  python=spawn('.venv/bin/python',['tests/background_browser_server.py'],{cwd:process.cwd(),stdio:['ignore','pipe','pipe']});
  let logs='';python.stderr.on('data',d=>logs+=d);
  const config=await new Promise((resolve,reject)=>{let pending='';const timer=setTimeout(()=>reject(Error('Fixture startup: '+logs)),15000);python.stdout.on('data',d=>{pending+=d;const line=pending.split('\n').find(l=>l.startsWith('{"base"'));if(line){clearTimeout(timer);resolve(JSON.parse(line));}});python.on('exit',code=>reject(Error('Fixture exited '+code+' '+logs)));});
  const built=await build({stdin:{contents:`import React from'react';import{createRoot}from'react-dom/client';import{App}from'antd';import{MemoryRouter}from'react-router-dom';import Report from'./src/pages/Report';import'./src/styles/global.css';createRoot(document.getElementById('root')).render(<MemoryRouter><App><Report/></App></MemoryRouter>);`,loader:'tsx',resolveDir:process.cwd()},bundle:true,write:false,outfile:path.join(dir,'app.js'),format:'iife',jsx:'automatic',define:{'process.env.NODE_ENV':'"development"'}});
  const js=built.outputFiles.find(f=>f.path.endsWith('.js')).text,css=built.outputFiles.find(f=>f.path.endsWith('.css')).text;
  const posts=[];
  server=http.createServer(async(req,res)=>{
   if(req.url==='/app.js'){res.setHeader('Content-Type','text/javascript');return res.end(js);}
   if(req.url==='/app.css'){res.setHeader('Content-Type','text/css');return res.end(css);}
   if(req.url.startsWith('/3dmol/')){res.setHeader('Content-Type','text/javascript');return res.end(await fs.readFile(path.join('public',req.url)));}
   if(req.url==='/api/projects'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({success:true,data:{projects:[{id:'p',name:'ReportFixture',owner:'alice',tasks:[],deadline:'2026-12-01',ai_report_notes_enabled:true}]}}));}
   if(req.url==='/api/ai/chat/connections'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({success:true,data:{items:[{id:config.connection,name:'隔离模型',model:'mock'}]}}));}
   if(req.url.startsWith('/api/')){
    if(req.method==='POST')posts.push(req.url);
    const proxy=http.request(config.base+req.url,{method:req.method,headers:{...req.headers,host:new URL(config.base).host}},result=>{res.writeHead(result.statusCode,result.headers);result.pipe(res);});
    proxy.on('error',e=>{if(!res.headersSent)res.writeHead(502);res.end(e.message);});req.pipe(proxy);res.on('close',()=>proxy.destroy());return;
   }
   res.setHeader('Content-Type','text/html');res.end('<meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/app.css"><div id="root"></div><script src="/app.js"></script>');
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));const url='http://127.0.0.1:'+server.address().port;
  browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);await page.locator('.report-content h6').filter({hasText:'Model'}).waitFor();
  await page.locator('.report-content h6').filter({hasText:'Model'}).getByRole('button',{name:/^批注/}).click();
  await page.getByLabel('新的报告批注').fill('后台验证：补充说明');await page.getByRole('button',{name:'保存批注',exact:true}).click();
  await page.getByRole('combobox',{name:'批注处理模型'}).click();await page.getByText('隔离模型 · mock',{exact:true}).click();
  await page.locator('.report-review-comment').last().getByRole('button',{name:'让AI处理',exact:true}).click();
  const panel=page.locator('.report-work-drawer');await panel.getByText('AI正在处理批注',{exact:true}).waitFor();
  await panel.getByRole('button',{name:'Close',exact:true}).click();
  await page.reload();await page.getByRole('button',{name:/后台处理中 · 查看进度|报告进度与对话/}).click();
  await panel.getByText('后台已完成。<script>window.REVIEW_XSS=1</script>',{exact:true}).waitFor();
  assert.equal(posts.filter(p=>p==='/api/reports/assistant/p').length,1);assert.equal(await page.evaluate(()=>window.REVIEW_XSS),undefined);
  await panel.getByRole('button',{name:'Close',exact:true}).click();await page.locator('.report-content').getByText('后台完成的报告解释。',{exact:true}).waitFor();
  await page.getByRole('button',{name:'生成缺失注解',exact:true}).click();await panel.getByText('已保存的待审阅草稿',{exact:true}).waitFor();
  const summary=panel.locator('.report-work-message--assistant').filter({hasText:/生成\d+份草稿/}).last();await summary.waitFor();
  const expected=Number((await summary.textContent()).match(/生成(\d+)份草稿/)[1]);
  await page.waitForFunction(expected=>[...document.querySelectorAll('.report-work-drafts button')].filter(b=>b.textContent==='预览与编辑').length===expected,expected);
  const drafts=panel.getByRole('button',{name:'预览与编辑',exact:true});const count=await drafts.count();assert.ok(count>0);
  await panel.getByRole('button',{name:'Close',exact:true}).click();await page.reload();await page.getByRole('button',{name:'报告进度与对话',exact:true}).click();
  await panel.getByText('已保存的待审阅草稿',{exact:true}).waitFor();assert.equal(await drafts.count(),count);
  await drafts.first().click();await page.getByLabel('后台草稿结果分析').fill('人工核对后台草稿');await page.getByRole('button',{name:'保存到报告',exact:true}).click();
  await page.getByText('已保存注解',{exact:true}).waitFor();await page.waitForTimeout(200);assert.equal(await drafts.count(),count-1);
  await page.getByLabel('报告对话输入').fill('氧气分子能量采用-8.3 eV');await panel.getByRole('button',{name:/发\s*送/}).click();
  await panel.getByText('收到你的补充，可以继续处理原报告。',{exact:true}).waitFor();
  await panel.getByRole('button',{name:'Close',exact:true}).click();
  await page.locator('.report-content h6').filter({hasText:'Model'}).getByRole('button',{name:/^批注/}).click();
  await page.getByLabel('新的报告批注').fill('补充参考：需要什么就问我');await page.getByRole('button',{name:'保存批注',exact:true}).click();
  await page.locator('.report-review-comment').getByText('补充参考：需要什么就问我',{exact:true}).waitFor();
  await page.locator('.report-review-comment').last().getByRole('button',{name:'让AI处理',exact:true}).click();
  await panel.getByText('请在对话中补充氧气参考能量。',{exact:true}).waitFor();
  await panel.getByRole('button',{name:'Close',exact:true}).click();
  await page.locator('.report-content h6').filter({hasText:'Model'}).getByRole('button',{name:/^批注/}).click();
  await page.getByLabel('新的报告批注').fill('等待取消：不要写入这项修改');await page.getByRole('button',{name:'保存批注',exact:true}).click();
  await page.locator('.report-review-comment').getByText('等待取消：不要写入这项修改',{exact:true}).waitFor();
  await page.locator('.report-review-comment').last().getByRole('button',{name:'让AI处理',exact:true}).click();
  await panel.getByRole('button',{name:/停\s*止/}).click();await panel.getByText('已停止',{exact:true}).first().waitFor();
  await panel.getByRole('button',{name:'Close',exact:true}).click();
  await page.getByRole('button',{name:/生成报告$/}).click();
  await panel.getByText('ReportFixture：整理已有项目数据',{exact:true}).waitFor();
  await panel.getByRole('button',{name:'Close',exact:true}).click();await page.reload();
  await page.getByRole('button',{name:/后台处理中 · 查看进度|报告进度与对话/}).click();
  await panel.getByText('ReportFixture：完整报告已生成。',{exact:false}).waitFor();
  await page.setViewportSize({width:390,height:844});await page.waitForTimeout(300);
  const bounds=await panel.locator('.ant-drawer-content').boundingBox();assert.ok(bounds.width<=390&&bounds.x>=-1);
  await page.screenshot({path:path.join(dir,'background-mobile.png')});
  assert.equal(posts.filter(p=>p.includes('/review/process')||p.includes('/notes/ai-preview')||p.endsWith('/project/generate')).length,0);
  assert.deepEqual(errors,[]);console.log('PASS background report: close/reload persistence, real progress/SSE, drafts preview/save, model question/reply, explicit stop, no foreground generation, mobile. '+dir);
 }finally{await browser?.close();if(server)await new Promise(r=>server.close(r));python?.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
