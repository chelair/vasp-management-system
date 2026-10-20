// Existing AI React page -> real isolated chat/SSE -> R3/R2 -> edit/export/history.
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
  async function generate(scenario='full',question='比较 LMR 和 LIC@LMR 的氧空位形成能，生成一份科研报告。'){
   await page.goto(url+'/?scenario='+scenario);const composer=page.getByRole('textbox',{name:'输入 AI 对话消息',exact:true});await composer.fill(question);await composer.press('Enter');
   await page.getByText('已根据科学数据检查生成独立专题报告。',{exact:false}).first().waitFor();await page.getByRole('button',{name:'打开专题报告',exact:true}).first().click();await page.getByRole('textbox',{name:'专题报告标题',exact:true}).waitFor();
   const items=await api('/reports/topic?conversation_id='+fixture.conversations[scenario]);return await api('/reports/topic/'+items.items[0].topic_id);
  }
  let doc=await generate();const id=doc.topic_id,science=JSON.stringify(doc.data);assert.deepEqual(doc.data.science.results.map(r=>r.value),[3,4,1]);
  const controls=page.locator('[data-topic-block]');const evidence=doc.blocks.find(b=>b.origin==='r2'&&b.section==='results');const card=page.locator(`[data-topic-block="${evidence.block_id}"]`);
  await card.getByRole('textbox',{name:'元素标题',exact:true}).fill('用于删除的证据');await card.getByRole('button',{name:'删除专题元素',exact:true}).click();
  const lastEvidence=doc.blocks.filter(b=>b.origin==='r2'&&b.section==='results').at(-1);await page.locator(`[data-topic-block="${lastEvidence.block_id}"]`).getByRole('button',{name:'上移专题元素',exact:true}).click();
  await page.getByRole('textbox',{name:'专题报告标题',exact:true}).fill('编辑后的氧空位专题');await page.getByRole('textbox',{name:'专题段落文字',exact:true}).fill('人工编辑的解释 [[F01]]；仍保留科学局限。');
  assert.equal(await page.getByRole('button',{name:'下载 HTML',exact:true}).isDisabled(),true);
  const save=async()=>{await page.getByRole('button',{name:'保存专题科研报告',exact:true}).click();await page.getByRole('button',{name:'下载 HTML',exact:true}).waitFor();await page.waitForFunction(()=>!Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='下载 HTML')?.disabled);};await save();
  doc=await api('/reports/topic/'+id);assert.equal(JSON.stringify(doc.data),science);assert.deepEqual(doc.deleted_block_ids,[evidence.block_id]);assert.equal(doc.title,'编辑后的氧空位专题');assert.equal(doc.narratives[Object.keys(doc.narratives)[0]].user_text,'人工编辑的解释 [[F01]]；仍保留科学局限。');
  assert.deepEqual(await controls.evaluateAll(nodes=>nodes.map(n=>n.getAttribute('data-topic-block'))),doc.blocks.map(b=>b.block_id));
  let download=page.waitForEvent('download');await page.getByRole('button',{name:'下载 HTML',exact:true}).click();const file=await download;const html=await fs.readFile(await file.path(),'utf8');assert.ok(html.includes('人工编辑的解释'));assert.ok(!html.includes('用于删除的证据'));assert.ok(html.includes('3.0 eV'));
  const frame=page.frameLocator('iframe[title="专题科研报告预览"]');await frame.getByText('人工编辑的解释',{exact:false}).waitFor();
  const printResponse=page.waitForResponse(r=>r.url().includes('/export.html?print=true'));await page.getByRole('button',{name:'PDF 打印',exact:true}).click();assert.equal((await printResponse).status(),200);
  const exportPage=await browser.newPage();await exportPage.setContent(html,{waitUntil:'domcontentloaded'});const pdf=await exportPage.pdf();assert.ok(pdf.length>1000);assert.equal(pdf.subarray(0,4).toString(),'%PDF');await exportPage.close();
  await page.getByRole('button',{name:'重新生成本段',exact:true}).click();await page.waitForFunction(()=>document.querySelector('textarea[aria-label="专题段落文字"]')?.value.includes('重新组织')); doc=await api('/reports/topic/'+id);assert.equal(JSON.stringify(doc.data),science);assert.equal(doc.narratives[Object.keys(doc.narratives)[0]].user_text,null);
  await page.goto(url);await page.getByRole('button',{name:'打开专题报告',exact:true}).first().click();await page.getByRole('textbox',{name:'专题报告标题',exact:true}).waitFor();assert.equal(await page.getByRole('textbox',{name:'专题报告标题',exact:true}).inputValue(),'编辑后的氧空位专题');assert.equal(await page.getByRole('button',{name:'恢复专题元素',exact:true}).count(),1);
  const multi=await generate('multi');assert.equal(multi.data.science.results.length,0);const select=page.getByRole('combobox',{name:'LMR-氧位点',exact:true});await select.click();await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option').first().click();await page.getByRole('button',{name:'应用明确选择',exact:true}).click();await page.getByText('已检查数据',{exact:true}).waitFor();const resolved=await api('/reports/topic/'+multi.topic_id);assert.equal(resolved.data.science.results.length,1);assert.equal(resolved.stage,'prepared');
  const dos=await generate('dos','比较 Electronic 的 DOS，生成一份科研报告。');assert.ok(dos.selections.some(s=>dos.data.candidates.find(c=>c.block_id===s.block_id)?.type==='ele.pdos'));await page.frameLocator('iframe[title="专题科研报告预览"]').locator('[data-report-widget="pdos-chart"][data-mounted="1"]').waitFor();
  const ads=await generate('ads','比较 LMR 与 LIC@LMR 对 H2 的吸附能，生成科研报告。');assert.deepEqual(ads.data.science.results.map(r=>r.value),[-2,-3,-1]);
  await page.frameLocator('iframe[title="专题科研报告预览"]').getByText('不等同于吸附自由能',{exact:false}).first().waitFor();
  const adsMulti=await generate('ads_multi','比较 LMR 与 LIC@LMR 对 H2 的吸附能，生成科研报告。');assert.equal(adsMulti.data.preparation_status,'NEEDS_SELECTION');
  await page.getByRole('combobox',{name:'LMR-吸附位点',exact:true}).click();await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option').last().click();
  await page.getByRole('button',{name:'应用明确选择',exact:true}).click();await page.getByText('已检查数据',{exact:true}).waitFor();const adsChosen=await api('/reports/topic/'+adsMulti.topic_id);assert.deepEqual(adsChosen.data.science.results.map(r=>r.value),[-1,-3,-2]);
  const gasAds=await generate('ads_gas','比较 LMR 与 LIC@LMR 对 H2 的吸附能，生成科研报告。');assert.equal(gasAds.data.science.results.length,0);
  await page.getByRole('combobox',{name:'专题吸附物参考类型',exact:true}).focus();await page.getByRole('combobox',{name:'专题吸附物参考类型',exact:true}).press('ArrowDown');await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option').filter({hasText:'确认孤立/气相分子参考'}).click();
  await page.getByRole('button',{name:'应用明确选择',exact:true}).click();await page.getByText('已检查数据',{exact:true}).waitFor();const gasChosen=await api('/reports/topic/'+gasAds.topic_id);assert.deepEqual(gasChosen.data.science.results.map(r=>r.value),[-2,-3,-1]);
  const pending=await api('/reports/topic/prepare','POST',{conversation_id:fixture.conversations.ads_pending,question:'查看 H2 在 LMR 上的吸附能',request:{property_id:'adsorption.simple',model_queries:['LMR'],adsorbate_query:'H2'}});
  assert.equal(pending.stage,'prepared');assert.equal(pending.data.science.results.length,0);
  await page.goto(url+'/?scenario=ads_pending');await page.getByRole('button',{name:'打开专题报告',exact:true}).first().click();
  await page.getByText('报告尚未生成完成',{exact:true}).waitFor();
  await page.getByRole('button',{name:'重新检查已有数据',exact:true}).click();await page.getByText('版本 2',{exact:false}).waitFor();
  const pick=async(name,label)=>{const control=page.getByRole('combobox',{name,exact:true});await control.focus();await control.press('ArrowDown');await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option').filter({hasText:label}).last().click();};
  await pick('LMR · complex-候选任务','H2@LMR');await pick('LMR · surface-候选任务','ads_pending_a_s');
  await pick('0.adsorbate-计算快照','con1');await page.getByRole('button',{name:'应用明确选择',exact:true}).click();await page.getByText('版本 3',{exact:false}).waitFor();
  const checked=await api('/reports/topic/'+pending.topic_id);assert.equal(checked.data.targets[0].complex.task_id,'ads_pending_a_c');assert.equal(checked.data.targets[0].surface.task_id,'ads_pending_a_s');assert.ok(checked.data.targets[0].adsorbate.observation_id);assert.equal(checked.data.science.results.length,0);assert.equal((await api('/reports/topic/'+pending.topic_id+'?revision=1')).revision,1);
  assert.deepEqual(errors,[]);console.log('PASS R4 browser: existing AI chat/SSE, complete values, edit/delete/reorder/save/reopen, HTML/PDF, private paragraph regeneration, explicit multi-site choice, relevant DOS, adsorption comparison and site/reference selection; zero page errors');
 }finally{await browser?.close();if(server)await new Promise(r=>server.close(r));python?.kill();await fs.rm(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
