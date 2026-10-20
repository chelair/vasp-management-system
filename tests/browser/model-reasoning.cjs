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
  await page.goto(url);
  async function select(name,label){const input=page.getByRole('combobox',{name,exact:true});await input.focus();await input.press('ArrowDown');await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option').filter({hasText:label}).last().click();}
  async function depthReady(){await page.waitForFunction(()=>!document.querySelector('input[aria-label="思考深度"]')?.disabled);}
  await page.getByRole('button',{name:/模型连接/}).click();await page.getByRole('button',{name:/新增连接/}).click();
  await page.locator('.ant-modal:visible').waitFor();
  await page.getByRole('textbox',{name:'连接名称',exact:true}).fill('可调深度测试');
  await page.getByRole('textbox',{name:'API 基础地址',exact:true}).fill(`http://127.0.0.1:${fixture.port}/v1`);
  // Use the fixture's actual provider address, not the app API port.
  const existing=(await api('/ai/chat/connections')).items[0];await page.getByRole('textbox',{name:'API 基础地址',exact:true}).fill(existing.base_url);
  await page.getByRole('textbox',{name:'模型名称',exact:true}).fill('deepseek-flash');await page.getByLabel('API Key',{exact:true}).fill('synthetic-browser-private-key');
  await select('思考接口类型','DeepSeek 兼容');await depthReady();await select('思考深度','低');
  await page.getByRole('button',{name:/^(OK|确 定|确定)$/}).click();await page.getByRole('dialog',{name:'新增模型连接',exact:true}).waitFor({state:'hidden'});
  let connection=(await api('/ai/chat/connections')).items.find(c=>c.name==='可调深度测试');assert.equal(connection.reasoning_effort,'low');assert.equal(connection.reasoning_api,'deepseek');assert.ok(!JSON.stringify(connection).includes('synthetic-browser-private-key'));
  const card=page.locator('.ai-connection').filter({hasText:'可调深度测试'});await card.getByRole('button',{name:/编辑/}).click();await depthReady();assert.equal(await page.getByLabel('API Key',{exact:true}).inputValue(),'');
  await page.getByRole('textbox',{name:'模型名称',exact:true}).fill('gpt-5.2');await select('思考接口类型','OpenAI 兼容');await depthReady();await select('思考深度','更高');await page.getByRole('button',{name:/^(OK|确 定|确定)$/}).click();await page.getByRole('dialog',{name:'编辑模型连接',exact:true}).waitFor({state:'hidden'});
  connection=(await api('/ai/chat/connections')).items.find(c=>c.name==='可调深度测试');assert.equal(connection.reasoning_effort,'xhigh');assert.ok(!connection.reasoning_capabilities.options.some(o=>o.value==='max'));
  await page.locator('.ant-drawer-open .ant-drawer-close').click();await page.getByRole('dialog',{name:'模型连接',exact:true}).waitFor({state:'hidden'});await select('当前会话模型','可调深度测试');await select('当前模型思考深度','低');
  await page.waitForFunction(()=>document.querySelector('input[aria-label="当前模型思考深度"]')?.closest('.ant-select')?.textContent.includes('低'));
  const send=async()=>{const composer=page.getByRole('textbox',{name:'输入 AI 对话消息',exact:true});await composer.fill('比较 LMR 和 LIC@LMR 的氧空位形成能并生成报告。');const [response]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/messages')&&r.request().method()==='POST'),composer.press('Enter')]);assert.equal(response.status(),200);const run=(await response.json()).data;await fetch(url+'/api/ai/chat/runs/'+run.id+'/events',{headers:{Authorization:'Bearer '+fixture.token}}).then(r=>r.text());assert.equal((await api('/ai/chat/runs/'+run.id)).status,'completed');};
  await send();let requests=await fetch(url+'/api/__test/provider-requests',{headers:{Authorization:'Bearer '+fixture.token}}).then(r=>r.json());assert.ok(requests.some(r=>r.model==='gpt-5.2'&&r.effort==='low'&&r.tools));
  await page.getByRole('button',{name:/模型连接/}).click();await card.getByRole('button',{name:/编辑/}).click();await page.getByRole('textbox',{name:'模型名称',exact:true}).fill('deepseek-flash');await select('思考接口类型','DeepSeek 兼容');await depthReady();await select('思考深度','最高');await page.getByRole('button',{name:/^(OK|确 定|确定)$/}).click();await page.getByRole('dialog',{name:'编辑模型连接',exact:true}).waitFor({state:'hidden'});await page.locator('.ant-drawer-open .ant-drawer-close').click();await page.getByRole('dialog',{name:'模型连接',exact:true}).waitFor({state:'hidden'});
  await send();requests=await fetch(url+'/api/__test/provider-requests',{headers:{Authorization:'Bearer '+fixture.token}}).then(r=>r.json());assert.ok(requests.some(r=>r.model==='deepseek-flash'&&r.effort==='max'&&r.thinking?.type==='enabled'&&r.tools));
  await page.goto(url);await page.getByRole('combobox',{name:'当前模型思考深度',exact:true}).waitFor();connection=(await api('/ai/chat/connections')).items.find(c=>c.name==='可调深度测试');assert.equal(connection.reasoning_effort,'max');
  assert.deepEqual(errors,[]);console.log('PASS reasoning browser: DeepSeek/OpenAI provider-specific options, encrypted key retention, save/reopen, per-model options, chat quick control, real HTTP/SSE upstream efforts, page reload; zero page errors');
 }finally{await browser?.close();if(server)await new Promise(r=>server.close(r));python?.kill();await fs.rm(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
