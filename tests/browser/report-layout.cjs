// Real Report page -> isolated report API -> local mock model -> same report/export.
const {build}=require('esbuild');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || '/tmp/vasp-todo-browser/node_modules/playwright-core');
const {spawn,execFileSync}=require('node:child_process');
const http=require('node:http'),path=require('node:path'),fs=require('node:fs/promises'),os=require('node:os'),assert=require('node:assert/strict');

(async()=>{
 let python,server,browser;
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'vasp-review-browser-'));
 try{
  python=spawn('.venv/bin/python',['tests/review_browser_server.py'],{cwd:process.cwd(),env:{...process.env,LAYOUT_BROWSER_FIXTURE:'1'},stdio:['ignore','pipe','pipe']});
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
  await page.locator('.report-3d canvas').first().waitFor();
  await page.evaluate(()=>window.__original3D=document.querySelector('.report-3d'));


  const editor=page.locator('.report-layout-editor'),content=page.locator('.report-content');
  const objects=content.locator('[data-layout-object]');
  const baseline=await page.evaluate(()=>{
    const root=document.querySelector('.report-content'),r=root.getBoundingClientRect();
    return {height:r.height,blocks:[...root.querySelectorAll('[data-layout-anchor]')].map(el=>{const b=el.getBoundingClientRect();return [el.dataset.layoutAnchor,b.top-r.top,b.width,b.height,el.tagName,el.textContent.slice(0,60)];}).filter(row=>row[2]>0&&row[3]>0)};
  });
  const original3D=await page.locator('.report-3d').first().evaluate(el=>{window.__layoutOriginal3D=el;return !!el;});assert.ok(original3D);
  await page.getByRole('button',{name:'编辑排版',exact:true}).click();
  const section=(key)=>content.locator(`section[data-report-section="${key}"]`);
  const topTitle=section('basic_info').locator('h2').first();
  const intro=section('basic_info').locator('.report-markdown > p').first();
  const science=section('science');
  const end=section('actions').locator('.report-markdown > p').last();
  async function choose(id){await editor.getByLabel('选择排版对象',{exact:true}).selectOption(id);}
  async function selectedId(){return editor.getByLabel('选择排版对象',{exact:true}).inputValue();}
  async function place(kind,target,x=.5,y=8){
    if(kind==='text')await editor.getByRole('button',{name:'添加文本框',exact:true}).click();
    else await editor.getByLabel('添加基本形状',{exact:true}).selectOption(kind);
    await editor.getByText('在报告任意位置单击放置，按 Escape 取消。',{exact:true}).waitFor();
    await target.evaluate(el=>el.scrollIntoView({block:'center'}));
    const b=await target.boundingBox();assert.ok(b,kind+' target invisible: '+await target.evaluate(el=>el.outerHTML.slice(0,300)));assert.ok(b.width>0);
    await page.mouse.click(b.x+b.width*x,b.y+y);
    const id=await selectedId();assert.ok(id);
    return id;
  }
  async function drag(locator,dx,dy){
    await locator.scrollIntoViewIfNeeded();const b=await locator.boundingBox();assert.ok(b);
    await page.mouse.move(b.x+b.width/2,b.y+b.height/2);await page.mouse.down();
    await page.mouse.move(b.x+b.width/2+dx,b.y+b.height/2+dy,{steps:8});await page.mouse.up();
  }
  async function save(){
    const button=editor.getByRole('button',{name:'保存排版',exact:true});if(await button.count())await button.click();
    await editor.getByRole('status').filter({hasText:'已保存'}).waitFor();
    return (await (await page.request.get(url+'/api/reports/project/rpt_p/layout')).json()).data;
  }
  const textId=await place('text',topTitle,.55,3),box=content.locator(`[data-layout-object="${textId}"]`);
  assert.equal(await content.locator('.report-manual-region').count(),0,'No fixed canvas or blank report area');
  await box.locator('foreignObject').dblclick();await page.getByLabel('对象文字',{exact:true}).fill('Floating note on original report');await page.keyboard.press('Escape');
  await choose(textId);await editor.getByLabel('字号',{exact:true}).fill('18');
  await editor.getByLabel('填充颜色',{exact:true}).fill('#f8e6b0');await editor.getByLabel('填充不透明度',{exact:true}).fill('0.35');
  const oldTransform=await box.getAttribute('transform');await drag(box.locator('foreignObject'),-40,-25);
  await editor.getByRole('button',{name:'撤销',exact:true}).click();assert.equal(await box.getAttribute('transform'),oldTransform);
  await editor.getByRole('button',{name:'重做',exact:true}).click();await choose(textId);
  await drag(box.locator('[data-handle="se"]'),35,15);
  await editor.getByRole('button',{name:'复制对象',exact:true}).click();const copy=await selectedId();
  await page.keyboard.press('Delete');assert.equal(await content.locator(`[data-layout-object="${copy}"]`).count(),0);
  await editor.getByRole('button',{name:'撤销',exact:true}).click();assert.equal(await content.locator(`[data-layout-object="${copy}"]`).count(),1);
  await editor.getByRole('button',{name:'重做',exact:true}).click();
  // A placement click on an existing link must not navigate or open its target.
  const pagesBefore=browser.contexts()[0].pages().length;
  const linkId=await place('rectangle',intro.locator('xpath=following-sibling::p').first(),.2,8);
  assert.equal(browser.contexts()[0].pages().length,pagesBefore);
  await choose(linkId);await editor.getByRole('button',{name:'删除对象',exact:true}).click();
  const ids={text:textId};
  const paragraphs=science.locator('.report-markdown > p');
  const targets=[intro,science.locator('.report-markdown > h5').first(),paragraphs.first(),science.locator('.report-markdown > table').first(),science.locator('.report-markdown > figure:visible').last(),end];
  let i=0;
  for(const kind of ['rectangle','rounded','square','circle','ellipse','triangle','diamond','line','arrow','double-arrow']){
    const id=await place(kind,targets[i%targets.length],.12+(i%3)*.25,10);ids[kind]=id;i++;
    const shape=content.locator(`[data-layout-object="${id}"]`);
    if(['line','arrow','double-arrow'].includes(kind)){
      await drag(shape.locator('[data-handle="end"]'),80,50);await choose(id);await drag(shape.locator('[data-handle="start"]'),-25,-20);
    }else{
      await drag(shape.locator('[data-handle="se"]'),-30,-25);
      if(kind==='circle'){
        const before=Number(await shape.locator('ellipse').getAttribute('rx'));await drag(shape.locator('[data-handle="e"]'),-15,0);
        assert.ok(Number(await shape.locator('ellipse').getAttribute('rx'))<before);
      }
      if(kind==='rectangle'){
        await editor.getByRole('button',{name:'编辑文字',exact:true}).click();await page.getByLabel('对象文字',{exact:true}).fill('Shape annotation');await page.keyboard.press('Escape');await choose(id);
      }
      await editor.getByLabel('填充颜色',{exact:true}).fill('#dbeafe');await editor.getByLabel('填充不透明度',{exact:true}).fill('0.3');
    }
    await editor.getByLabel('线型',{exact:true}).selectOption('dashed');
  }
  const note3D=await place('text',science.locator('[data-report-widget="structure-3d"]').first(),.55,60);
  await editor.getByRole('button',{name:'编辑文字',exact:true}).click();await page.getByLabel('对象文字',{exact:true}).fill('Annotation on 3D');await page.keyboard.press('Escape');
  await choose(ids.diamond);await editor.getByLabel('旋转角度',{exact:true}).fill('35');
  for(const name of ['置于顶层','下移一层','置于底层','上移一层'])await editor.getByRole('button',{name,exact:true}).click();
  let data=await save();assert.equal(data.objects.length,12);assert.ok(data.objects.every(o=>o.anchor));
  // Moving between distant chapters uses scrolling without creating a canvas or changing the report.
  await choose(textId);await box.locator('foreignObject').evaluate(el=>el.scrollIntoView({block:'center'}));
  const b=await box.locator('foreignObject').boundingBox();await page.mouse.move(b.x+b.width/2,b.y+b.height/2);await page.mouse.down();
  await page.mouse.wheel(0,20000);await end.evaluate(el=>el.scrollIntoView({block:'center'}));
  const e=await end.boundingBox();await page.mouse.move(e.x+e.width*.5,e.y+160,{steps:12});await page.mouse.up();
  data=await save();assert.equal(data.objects.find(o=>o.id===textId).region,'actions','Can drag across chapters');
  const after=await page.evaluate(()=>{
    const root=document.querySelector('.report-content'),r=root.getBoundingClientRect();
    return {height:r.height,blocks:[...root.querySelectorAll('[data-layout-anchor]')].map(el=>{const b=el.getBoundingClientRect();return [el.dataset.layoutAnchor,b.top-r.top,b.width,b.height,el.tagName,el.textContent.slice(0,60)];}).filter(row=>row[2]>0&&row[3]>0)};
  });
  await fs.writeFile(path.join(dir,'geometry.json'),JSON.stringify({baseline,after},null,2));
  assert.equal(after.blocks.length,baseline.blocks.length);
  assert.ok(Math.abs(after.height-baseline.height)<1,'Annotations do not change the report height');
  baseline.blocks.forEach((row,index)=>{for(let j=1;j<4;j++)assert.ok(Math.abs(row[j]-after.blocks[index][j])<1,'Original block geometry unchanged '+JSON.stringify({before:row,after:after.blocks[index],field:j}));});
  assert.ok(await page.evaluate(()=>window.__layoutOriginal3D===document.querySelector('.report-3d')&&window.__layoutOriginal3D.isConnected));
  await page.getByRole('button',{name:'退出编辑',exact:true}).click();assert.equal(await content.locator('[data-handle]').count(),0);
  assert.ok(await content.locator('.report-layout-floating').first().evaluate(el=>getComputedStyle(el).pointerEvents==='none'));
  await page.reload();await objects.first().waitFor();assert.equal(await objects.count(),12);assert.equal(await content.locator('.report-manual-region').count(),0);
  const html=await (await page.request.get(url+'/api/reports/project/rpt_p/export.html?interactive=0')).text();await fs.writeFile(path.join(dir,'layout.html'),html);
  const offline=await browser.newPage({viewport:{width:1000,height:1000}});await offline.setContent(html);
  assert.equal(await offline.locator('[data-layout-object]').count(),12);
  assert.equal(await offline.locator('[data-handle],.report-layout-editor').count(),0);
  for(const o of data.objects){
    const live=content.locator(`[data-layout-object="${o.id}"]`),out=offline.locator(`[data-layout-object="${o.id}"]`);
    assert.ok(await out.isVisible());
    const matrix=locator=>locator.evaluate(el=>{const m=el.transform.baseVal.consolidate().matrix;return [m.a,m.b,m.c,m.d,m.e,m.f];});
    const a=await matrix(live),b=await matrix(out);a.forEach((v,j)=>assert.ok(Math.abs(v-b[j])<.001));
    const relative=locator=>locator.evaluate(el=>{
      const svg=el.closest('svg'),anchor=[...document.querySelectorAll('[data-layout-anchor]')].find(a=>a.dataset.layoutAnchor===svg.dataset.layoutAnchorRef&&a.dataset.layoutSection===svg.dataset.layoutRegion);
      const a=anchor.getBoundingClientRect(),m=svg.getScreenCTM(),vb=svg.viewBox.baseVal;
      const origin=new DOMPoint(0,0).matrixTransform(m);
      const container=anchor.closest('.report-content')||document.body,scale=container.getBoundingClientRect().width/960;
      return [(origin.x-a.left)/scale,(origin.y-a.top)/scale,m.a/scale];
    });
    const r1=await relative(live),r2=await relative(out);r1.forEach((v,j)=>assert.ok(Math.abs(v-r2[j])<3,`${o.kind} anchor offset preserved: ${r1} ${r2}`));
  }
  await offline.emulateMedia({media:'print'});const pdf=path.join(dir,'layout.pdf');await offline.pdf({path:pdf,format:'A4',printBackground:true});
  const pdfText=execFileSync('pdftotext',[pdf,'-'],{encoding:'utf8'}).replace(/\s+/g,' ');
  assert.ok(pdfText.includes('Floating note on original report'));assert.ok(pdfText.includes('Shape annotation'));assert.ok(pdfText.includes('Annotation on 3D'));
  await offline.screenshot({path:path.join(dir,'layout-export.png'),fullPage:true});await offline.close();
  // Save failures preserve the floating note and prevent exporting an older revision.
  await page.getByRole('button',{name:'编辑排版',exact:true}).click();await choose(textId);
  await page.route('**/api/reports/project/rpt_p/layout',route=>route.request().method()==='PUT'?route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({success:false,message:'隔离测试：保存失败'})}):route.continue());
  await editor.getByLabel('字号',{exact:true}).fill('20');await editor.getByRole('status').filter({hasText:'隔离测试：保存失败'}).waitFor();
  let downloads=0;page.on('download',()=>downloads++);await page.getByRole('button',{name:/导\s*出$/}).click();
  await Promise.all([page.waitForResponse(r=>r.url().endsWith('/layout')&&r.status()===500),page.getByRole('button',{name:/下载 HTML/}).click()]);assert.equal(downloads,0);
  await page.getByRole('button',{name:/导\s*出$/}).click();await page.unroute('**/api/reports/project/rpt_p/layout');await save();
  const beforeGeneration=(await (await page.request.get(url+'/api/reports/project/rpt_p/layout')).json()).data;
  assert.ok((await page.request.post(url+'/api/reports/project/generate',{data:{project_id:'p'}})).ok());
  assert.deepEqual((await (await page.request.get(url+'/api/reports/project/rpt_p/layout')).json()).data,beforeGeneration);
  await page.reload();await objects.first().waitFor();await page.setViewportSize({width:390,height:844});
  assert.ok(await content.locator('[data-layout-object]').count());
  await page.screenshot({path:path.join(dir,'layout-mobile.png')});
  await page.setViewportSize({width:1440,height:1050});await page.getByRole('button',{name:'编辑排版',exact:true}).click();await choose(ids.arrow);
  await editor.getByRole('button',{name:'删除对象',exact:true}).click();await save();await page.reload();assert.equal(await content.locator(`[data-layout-object="${ids.arrow}"]`).count(),0);
  const stored=(await (await page.request.get(url+'/api/reports/project/rpt_p/layout')).json()).data;
  const legacy={...stored.objects[0],id:'legacy_note',region:'basic_info',anchor:'',text:'Legacy floating note'};
  assert.ok((await page.request.put(url+'/api/reports/project/rpt_p/layout',{data:{version:1,revision:stored.revision,objects:[...stored.objects,legacy]}})).ok());
  await page.reload();await content.locator('[data-layout-object="legacy_note"]').waitFor();
  assert.equal(await content.locator('.report-manual-region').count(),0,'Old objects do not add a canvas');
  await page.getByRole('button',{name:'编辑排版',exact:true}).click();await choose('legacy_note');
  await editor.getByRole('button',{name:'重新放置',exact:true}).click();await end.evaluate(el=>el.scrollIntoView({block:'center'}));
  const target=await end.boundingBox();await page.mouse.click(target.x+target.width*.55,target.y+8);
  const migrated=await save();assert.equal(migrated.objects.find(o=>o.id==='legacy_note').region,'actions');assert.ok(migrated.objects.find(o=>o.id==='legacy_note').anchor);
  assert.deepEqual(errors,[]);
  console.log('PASS floating report annotations: place on headings/paragraphs/tables/charts, all shapes, cross-chapter drag, original geometry unchanged, styles/undo/save/reload/regeneration/failure, HTML/PDF and mobile. '+dir);
 }finally{await browser?.close();if(server)await new Promise(r=>server.close(r));python?.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
