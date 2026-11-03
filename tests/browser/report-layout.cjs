// Real Report page -> isolated report API -> local mock model -> same report/export.
const {build}=require('esbuild');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || '/tmp/vasp-todo-browser/node_modules/playwright-core');
const {spawn,execFileSync}=require('node:child_process');
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
  await page.locator('.report-3d canvas').first().waitFor();
  await page.evaluate(()=>window.__original3D=document.querySelector('.report-3d'));

  await page.evaluate(()=>Object.defineProperty(crypto,'randomUUID',{value:undefined,configurable:true}));
  await page.getByRole('button',{name:'编辑排版',exact:true}).click();
  const editor=page.locator('.report-layout-editor'), region=page.locator('[data-layout-region="science"]');
  async function choose(id){await editor.getByLabel('选择排版对象',{exact:true}).selectOption(id);}
  async function selectedId(){return editor.getByLabel('选择排版对象',{exact:true}).inputValue();}
  async function drag(locator,dx,dy){
    await locator.scrollIntoViewIfNeeded();const b=await locator.boundingBox();
    assert.ok(b);await page.mouse.move(b.x+b.width/2,b.y+b.height/2);await page.mouse.down();
    await page.mouse.move(b.x+b.width/2+dx,b.y+b.height/2+dy,{steps:8});await page.mouse.up();
  }
  async function save(){
    await editor.getByRole('button',{name:'保存排版',exact:true}).click().catch(()=>{});
    await editor.getByRole('status').filter({hasText:'已保存'}).waitFor();
    return (await (await page.request.get(url+'/api/reports/project/rpt_p/layout')).json()).data;
  }
  await editor.getByRole('button',{name:'添加文本框',exact:true}).click();const textId=await selectedId();
  const box=region.locator(`[data-layout-object="${textId}"]`);
  await box.locator('foreignObject').dblclick();
  await page.getByRole('textbox',{name:'对象文字',exact:true}).fill('Manual scientific layout\nSafe <script>alert(1)</script>');
  await page.keyboard.press('Escape');await choose(textId);
  await editor.getByLabel('字号',{exact:true}).fill('28');await editor.getByRole('button',{name:'粗体',exact:true}).click();
  await editor.getByRole('button',{name:'斜体',exact:true}).click();
  await editor.getByLabel('文字对齐',{exact:true}).selectOption('center');
  await editor.getByLabel('填充颜色',{exact:true}).fill('#f8e6b0');
  await editor.getByLabel('填充不透明度',{exact:true}).fill('0.5');
  const initialTransform=await box.getAttribute('transform');
  await drag(box.locator('foreignObject'),100,60);assert.notEqual(await box.getAttribute('transform'),initialTransform);
  const movedTransform=await box.getAttribute('transform');
  await editor.getByRole('button',{name:'撤销',exact:true}).click();assert.equal(await box.getAttribute('transform'),initialTransform);
  await editor.getByRole('button',{name:'重做',exact:true}).click();assert.equal(await box.getAttribute('transform'),movedTransform);
  await choose(textId);await drag(box.locator('[data-handle="se"]'),60,35);
  await editor.getByRole('button',{name:'复制对象',exact:true}).click();const copyId=await selectedId();assert.notEqual(textId,copyId);
  await page.locator('body').click({position:{x:5,y:5}});await choose(copyId);await page.keyboard.press('Delete');
  assert.equal(await region.locator(`[data-layout-object="${copyId}"]`).count(),0);
  await editor.getByRole('button',{name:'撤销',exact:true}).click();assert.equal(await region.locator(`[data-layout-object="${copyId}"]`).count(),1);
  await editor.getByRole('button',{name:'重做',exact:true}).click();assert.equal(await region.locator(`[data-layout-object="${copyId}"]`).count(),0);
  const ids={text:textId};
  for(const kind of ['rectangle','rounded','square','circle','ellipse','triangle','diamond','line','arrow','double-arrow']){
    await editor.getByLabel('添加基本形状',{exact:true}).selectOption(kind);const id=await selectedId();ids[kind]=id;
    const shape=region.locator(`[data-layout-object="${id}"]`);
    if(['line','arrow','double-arrow'].includes(kind)){
      await drag(shape.locator('[data-handle="end"]'),90,70);
      await choose(id);await drag(shape.locator('[data-handle="start"]'),35,-30);
    }else{
      await drag(shape.locator('[data-handle="se"]'),-40,-35);
      if(kind==='circle'){
        const oldRx=Number(await shape.locator('ellipse').getAttribute('rx'));
        await drag(shape.locator('[data-handle="e"]'),-20,0);
        assert.ok(Number(await shape.locator('ellipse').getAttribute('rx'))<oldRx,'Circle can shrink from an edge');
      }
      if(kind==='ellipse'){
        const ratio=Number(await shape.locator('ellipse').getAttribute('rx'))/Number(await shape.locator('ellipse').getAttribute('ry'));
        // Use the actual outer dimensions, including the stroke, to check Shift ratio.
        const outer=await shape.locator('ellipse').evaluate(el=>({w:Number(el.getAttribute('rx'))*2+2,h:Number(el.getAttribute('ry'))*2+2}));
        await page.keyboard.down('Shift');await drag(shape.locator('[data-handle="se"]'),30,10);await page.keyboard.up('Shift');
        const after=await shape.locator('ellipse').evaluate(el=>({w:Number(el.getAttribute('rx'))*2+2,h:Number(el.getAttribute('ry'))*2+2}));
        assert.ok(Math.abs(outer.w/outer.h-after.w/after.h)<.001,'Shift keeps the ellipse ratio');assert.ok(ratio>1);
      }
      await editor.getByLabel('填充颜色',{exact:true}).fill('#dbeafe');
      if(kind==='rectangle'){
        await editor.getByRole('button',{name:'编辑文字',exact:true}).click();await page.getByLabel('对象文字',{exact:true}).fill('Shape label');await page.keyboard.press('Escape');
      }
    }
    await choose(id);await editor.getByLabel('线型',{exact:true}).selectOption('dashed');
  }
  await choose(ids.rectangle);await editor.getByRole('button',{name:'置于顶层',exact:true}).click();
  await editor.getByRole('button',{name:'下移一层',exact:true}).click();
  await editor.getByRole('button',{name:'置于底层',exact:true}).click();
  await editor.getByRole('button',{name:'上移一层',exact:true}).click();
  await choose(ids.diamond);await editor.getByLabel('旋转角度',{exact:true}).fill('35');
  let data=await save();assert.equal(data.objects.length,11);
  assert.equal(data.objects.find(o=>o.id===textId).style.font_weight,700);
  assert.ok(data.objects.find(o=>o.id===ids.arrow).dy>0);
  assert.equal(data.objects.find(o=>o.id===ids.circle).width,data.objects.find(o=>o.id===ids.circle).height);
  // Arrange a gallery through the same validated API, then compare both renderers.
  let index=0;
  const gallery=data.objects.map(o=>{
    if(o.kind==='text')return {...o,x:480,y:330,width:420,height:130};
    const i=index++,x=25+(i%5)*185,y=35+Math.floor(i/5)*175;
    return {...o,x,y,width:['circle','square'].includes(o.kind)?100:140,height:100,dx:140,dy:60};
  });
  const arranged=await page.request.put(url+'/api/reports/project/rpt_p/layout',{data:{version:1,revision:data.revision,objects:gallery}});assert.ok(arranged.ok(),await arranged.text());
  data=(await arranged.json()).data;
  const before=data.objects;await page.reload();await page.getByRole('button',{name:'编辑排版',exact:true}).waitFor();
  assert.equal(await region.locator('[data-layout-object]').count(),11);
  assert.equal(await region.locator('[data-handle]').count(),0);
  assert.equal(await region.locator('foreignObject').filter({hasText:'Manual scientific layout'}).count(),1);
  assert.ok(await page.evaluate(()=>document.querySelector('.report-3d canvas')!==null));
  const html=await (await page.request.get(url+'/api/reports/project/rpt_p/export.html?interactive=0')).text();
  await fs.writeFile(path.join(dir,'layout.html'),html);
  const offline=await browser.newPage({viewport:{width:1000,height:900}});await offline.setContent(html);
  assert.equal(await offline.locator('[data-layout-object]').count(),11);
  assert.equal(await offline.locator('[data-handle],.report-layout-editor').count(),0);
  assert.equal(await offline.evaluate(()=>window.LAYOUT_XSS),undefined);
  // Both SVG implementations must preserve geometry and style exactly.
  for(const o of before){
    const screen=region.locator(`[data-layout-object="${o.id}"]`),exported=offline.locator(`[data-layout-object="${o.id}"]`);
    const matrix=async locator=>locator.evaluate(el=>{const m=el.transform.baseVal.consolidate().matrix;return [m.a,m.b,m.c,m.d,m.e,m.f];});
    const a=await matrix(screen),b=await matrix(exported);a.forEach((v,i)=>assert.ok(Math.abs(v-b[i])<.001));
  }
  await offline.emulateMedia({media:'print'});
  const pdf=path.join(dir,'layout.pdf');await offline.pdf({path:pdf,format:'A4',printBackground:true});
  const pdfText=execFileSync('pdftotext',[pdf,'-'],{encoding:'utf8'});
  assert.ok(pdfText.replace(/\s+/g,' ').includes('Manual scientific layout'));assert.ok(pdfText.replace(/\s+/g,' ').includes('Shape label'));
  await offline.locator('[data-layout-region="science"]').screenshot({path:path.join(dir,'layout-export.png')});
  await offline.close();
  // An HTTP failure must leave a clear unsaved state and retain the local object.
  await page.getByRole('button',{name:'编辑排版',exact:true}).click();await choose(textId);
  await page.route('**/api/reports/project/rpt_p/layout',route=>route.request().method()==='PUT'?route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({success:false,message:'隔离测试：保存失败'})}):route.continue());
  await editor.getByLabel('字号',{exact:true}).fill('30');
  await editor.getByRole('status').filter({hasText:'隔离测试：保存失败'}).waitFor();
  assert.equal(await region.locator('[data-layout-object]').count(),11);
  let downloads=0;page.on('download',()=>downloads++);
  await page.getByRole('button',{name:/导\s*出$/}).click();
  await Promise.all([page.waitForResponse(r=>r.url().endsWith('/layout')&&r.request().method()==='PUT'&&r.status()===500),page.getByRole('button',{name:/下载 HTML/}).click()]);
  assert.equal(downloads,0,'A failed save must stop export');
  await page.getByRole('button',{name:/导\s*出$/}).click();
  await page.unroute('**/api/reports/project/rpt_p/layout');await save();
  // Regenerate via the existing background UI; manual objects and the original 3D survive.
  const old=await (await page.request.get(url+'/api/reports/project/rpt_p/layout')).json();
  const generated=await page.request.post(url+'/api/reports/project/generate',{data:{project_id:'p'}});assert.ok(generated.ok());
  assert.deepEqual((await (await page.request.get(url+'/api/reports/project/rpt_p/layout')).json()).data,old.data);
  await page.reload();await region.locator('[data-layout-object]').first().waitFor();
  await page.setViewportSize({width:390,height:844});
  const bounds=await region.boundingBox();assert.ok(bounds.width<=390);
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>document.documentElement.clientWidth+2);assert.equal(overflow,false);
  await region.screenshot({path:path.join(dir,'layout-mobile.png')});
  await page.setViewportSize({width:1440,height:1050});await page.getByRole('button',{name:'编辑排版',exact:true}).click();await choose(ids.arrow);
  await editor.getByRole('button',{name:'删除对象',exact:true}).click();await save();await page.reload();
  assert.equal(await region.locator(`[data-layout-object="${ids.arrow}"]`).count(),0);
  assert.deepEqual(errors,[]);
  console.log('PASS manual report layout: all shapes, text, geometry, endpoints, styles/layers, undo/redo, save/failure/reload/regeneration, HTML/PDF, mobile. '+dir);
 }finally{await browser?.close();if(server)await new Promise(r=>server.close(r));python?.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
