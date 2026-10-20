// Model settings + existing AI page, real isolated authenticated API/SSE/mock model.
const {build}=require('esbuild');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'/tmp/vasp-report-debug/node_modules/playwright-core');
const {spawn}=require('node:child_process');
const http=require('node:http'),path=require('node:path'),fs=require('node:fs/promises'),os=require('node:os'),assert=require('node:assert/strict');
(async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'vasp-r4-ui-'));let python,browser,server;
 try{
  const runtime=path.join(dir,'runtime.js');await build({entryPoints:['src/interactive/reportRuntime.ts'],bundle:true,minify:true,format:'iife',outfile:runtime});
  const bundle=await build({stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';import {App} from 'antd';import {MemoryRouter} from 'react-router-dom';import AI from './src/pages/AI';createRoot(document.getElementById('root')).render(<App><MemoryRouter initialEntries={['/?conversation='+window.CONVERSATION]}><AI/></MemoryRouter></App>);`,loader:'tsx',resolveDir:path.resolve('.')},bundle:true,write:false,outfile:path.join(dir,'app.js'),jsx:'automatic',define:{'process.env.NODE_ENV':'"development"'}});
  python=spawn('.venv/bin/python',['tests/r4_server.py',runtime],{stdio:['ignore','pipe','pipe']});let stderr='';python.stderr.on('data',v=>stderr+=v);
  const fixture=await new Promise((resolve,reject)=>{let out='';const timer=setTimeout(()=>reject(Error(stderr)),15000);python.on('exit',code=>{clearTimeout(timer);reject(Error(code+' '+stderr));});python.stdout.on('data',v=>{out+=v;if(out.includes('\n')){clearTimeout(timer);resolve(JSON.parse(out.split('\n')[0]));}});});
  const api=async(s,method='GET',body)=>{const r=await fetch(`http://127.0.0.1:${fixture.port}/api`+s,{method,headers:{Authorization:'Bearer '+fixture.token,'Content-Type':'application/json'},body:body&&JSON.stringify(body)});const data=await r.json();assert.equal(r.status,200,JSON.stringify(data));return data.data;};
  server=http.createServer((req,res)=>{
   if(req.url.startsWith('/api/')){const p=http.request(`http://127.0.0.1:${fixture.port}`+req.url,{method:req.method,headers:req.headers},r=>{res.writeHead(r.statusCode,r.headers);r.pipe(res);});p.on('error',e=>{res.writeHead(502);res.end(e.message);});req.pipe(p);return;}
   const asset=['/app.js','/app.css'].includes(req.url)?req.url.slice(1):null;if(asset){res.setHeader('Content-Type',asset.endsWith('.js')?'text/javascript':'text/css');return res.end(bundle.outputFiles.find(f=>f.path.endsWith(asset)).text);}
   const key=new URL(req.url,'http://local').searchParams.get('scenario')||'full';res.setHeader('Content-Type','text/html');res.end(`<link rel="stylesheet" href="/app.css"><div id="root"></div><script>window.CONVERSATION=${JSON.stringify(fixture.conversations[key])};localStorage.setItem('vasp.auth.token',${JSON.stringify(fixture.token)})</script><script src="/app.js"></script>`);
  });await new Promise(r=>server.listen(0,'127.0.0.1',r));const url=`http://127.0.0.1:${server.address().port}`;
  browser=await chromium.launch({executablePath:'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});const page=await browser.newPage({viewport:{width:1700,height:1100},acceptDownloads:true});page.setDefaultTimeout(15000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const existing=(await api('/ai/chat/connections')).items[0];const connection=await api('/ai/chat/connections','POST',{name:'语义翻译报告模型',base_url:existing.base_url,model:'flexible-report-model',api_key:'synthetic-flexible-key',max_tokens:4096});
  await api('/ai/chat/conversations/'+fixture.conversations.ads_missing,'PUT',{title:'用户口语报告',connection_id:connection.id,prompt:'用户的报告口径优先',workspace_enabled:true});
  await page.goto(url+'/?scenario=ads_missing');const input=page.getByRole('textbox',{name:'输入 AI 对话消息',exact:true});await input.fill('一号板和以前那个气体做吸附能，气体能量 -3 eV，我来审核。');await input.press('Enter');await page.getByText('已按你的意思生成报告。',{exact:false}).first().waitFor();
  const reports=await api('/reports/topic?conversation_id='+fixture.conversations.ads_missing);const id=reports.items[0].topic_id;const original=await api('/reports/topic/'+id);assert.equal(original.data.science.results[0].value,-2);assert.equal(original.simple.questions.length,0);assert.equal(original.data.science.inputs.find(i=>i.role==='0.adsorbate').source.kind,'user_provided');
  await page.getByRole('button',{name:'查看报告',exact:true}).first().click();const frame=page.frameLocator('iframe[title="科研报告预览"]');await frame.locator('.warnings').waitFor();assert.ok((await frame.locator('.value').textContent()).includes('-2.000000'));
  await page.getByRole('button',{name:'编辑报告',exact:true}).click();await page.getByRole('switch',{name:'显示风险提示',exact:true}).click();await page.getByRole('button',{name:'保存修改',exact:true}).click();await frame.locator('.warnings').waitFor({state:'detached'});
  const saved=await api('/reports/topic/'+id);assert.equal(saved.simple.show_warnings,false);assert.deepEqual(saved.data,original.data);assert.ok(saved.simple.warnings.length);
  const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'下载 HTML',exact:true}).click()]);const html=await fs.readFile(await download.path(),'utf8');assert.ok(html.includes('-2.000000'));assert.ok(!html.includes('<section class="warnings">'));
  assert.deepEqual(errors,[]);console.log('PASS flexible report: natural alias -> task search -> model role binding; external user energy with no molecule task; editable risk visibility and export; scientific data preserved.');
 }finally{await browser?.close();if(server)await new Promise(r=>server.close(r));python?.kill();await fs.rm(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
