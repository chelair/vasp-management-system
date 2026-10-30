// Manual note editing with a restored background draft. Background execution is
// covered by report-background.cjs through the real temporary API and model.
const {build}=require('esbuild'),{chromium}=require(process.env.PLAYWRIGHT_MODULE||'/tmp/vasp-todo-browser/node_modules/playwright-core');
const http=require('node:http'),assert=require('node:assert/strict'),path=require('node:path');
const {execFileSync}=require('node:child_process');
(async()=>{
 const built=await build({stdin:{contents:`import React,{useState}from'react';import{createRoot}from'react-dom/client';import{ReportAIProvider,ReportAIControls}from'./src/components/reports/ReportAIContext';import{ReportWorkProvider}from'./src/components/reports/ReportWorkContext';import ReportNotePanel from'./src/components/reports/ReportNotePanel';function Harness(){const[notes,setNotes]=useState({manual:{analysis_note:'人工原文',paper_note:'',revision:'manual-rev'}}),[connection,setConnection]=useState('mine');return <ReportWorkProvider projectId="fixture" connectionId={connection} onConnectionChange={setConnection} onChanged={async()=>{}}><ReportAIProvider reportId="fixture" notes={notes} onSaved={setNotes} connectionId={connection} onConnectionChange={setConnection}><ReportAIControls/><ReportNotePanel reportId="fixture" noteKey="manual" title="manual" analysis={notes.manual.analysis_note} paper={notes.manual.paper_note} onSaved={setNotes}/></ReportAIProvider></ReportWorkProvider>};createRoot(document.getElementById('root')).render(<Harness/>);`,loader:'tsx',resolveDir:path.resolve('.')},bundle:true,write:false,outfile:'/tmp/report-note-manual.js',format:'iife',jsx:'automatic',define:{'process.env.NODE_ENV':'"development"'}});
 let off=false,noModels=false,discarded=false,saves=[];
 const draft={key:'manual',analysis_note:'AI草稿 <script>window.XSS=1</script> [x](javascript:alert)\n![leak](https://example.invalid/leak)',paper_note:'**Results**：事实。\n**Discussion**：待验证。',draft_token:'mock-receipt',base_revision:'manual-rev',model:'mock',generated_at:'2026-10-30T12:00:00'};
 const server=http.createServer(async(req,res)=>{
  const send=(data,status=200)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify({success:status===200,data}));};
  if(req.url==='/app.js'){res.setHeader('Content-Type','text/javascript');return res.end(built.outputFiles.find(f=>f.path.endsWith('.js')).text);}
  if(!req.url.startsWith('/api/')){res.setHeader('Content-Type','text/html');return res.end('<div id="root"></div><script src="/app.js"></script>');}
  if(req.url.endsWith('/connections'))return send({items:noModels?[]:[{id:'mine',name:'我的连接',model:'mock'}]});
  if(req.url.endsWith('/ai-status'))return send({enabled:!off,empty_revision:'empty',notes:{manual:{analysis_note:'人工原文',paper_note:'',revision:'manual-rev'}},targets:[{key:'manual',title:'manual'}]});
  if(req.url.startsWith('/api/reports/assistant/')){
   if(req.method==='DELETE'){discarded=true;return send({});}
   return send({conversation:null,drafts:discarded?[]:[{report_id:'fixture',run_id:'restored',title:'manual',draft}]});
  }
  if(req.method==='PUT'&&req.url.endsWith('/notes')){const chunks=[];for await(const c of req)chunks.push(c);const body=JSON.parse(Buffer.concat(chunks));saves.push(body);return send({notes:{manual:{analysis_note:body.analysis_note,paper_note:body.paper_note,revision:'saved'}}});}
  send({},404);
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));const base='http://127.0.0.1:'+server.address().port;
  await page.goto(base);await page.getByRole('button',{name:/草稿与状态（1）/}).waitFor();
  await page.getByRole('button',{name:/编\s*辑/}).click();const dialog=page.locator('dialog[open]');
  await dialog.getByText('AI 草稿预览 · 尚未保存',{exact:true}).waitFor();
  assert.equal(await dialog.locator('textarea').first().inputValue(),'人工原文');assert.equal(saves.length,0);
  assert.equal(await page.evaluate(()=>window.XSS),undefined);assert.equal(await dialog.locator('script,img,a[href^="javascript:"]').count(),0);
  await dialog.getByRole('button',{name:'采用草稿到编辑区'}).click();await dialog.getByRole('button',{name:'恢复本次生成前文本'}).click();
  assert.equal(await dialog.locator('textarea').first().inputValue(),'人工原文');
  await dialog.getByRole('button',{name:'采用草稿到编辑区'}).click();await dialog.locator('textarea').first().fill('人工修订后台草稿');
  await dialog.getByRole('button',{name:/^保\s*存$/}).click();await page.locator('.notes-text').getByText('人工修订后台草稿',{exact:true}).waitFor();
  assert.equal(saves[0].draft_token,'mock-receipt');assert.equal(saves[0].analysis_note,'人工修订后台草稿');
  discarded=false;await page.reload();await page.getByRole('button',{name:/草稿与状态（1）/}).waitFor();await page.getByRole('button',{name:/编\s*辑/}).click();
  await dialog.getByRole('button',{name:'放弃草稿',exact:true}).click();await dialog.getByText('AI 草稿预览 · 尚未保存',{exact:true}).waitFor({state:'hidden'});
  assert.equal(await dialog.locator('textarea').first().inputValue(),'人工原文');await dialog.getByRole('button',{name:/^取\s*消$/}).click();
  off=true;await page.reload();await page.getByText('AI撰写未开启',{exact:false}).waitFor();await page.getByRole('button',{name:/编\s*辑/}).click();
  assert.equal(await dialog.getByRole('button',{name:'AI 重新生成',exact:true}).isDisabled(),true);await dialog.locator('textarea').first().fill('关闭AI后人工编辑');
  await dialog.getByRole('button',{name:/^保\s*存$/}).click();assert.equal(saves.at(-1).analysis_note,'关闭AI后人工编辑');
  off=false;noModels=true;await page.reload();await page.getByRole('button',{name:/编\s*辑/}).click();assert.equal(await dialog.getByRole('button',{name:'AI 重新生成',exact:true}).isDisabled(),true);
  const html=execFileSync('.venv/bin/python',['-c',`import os,sys,tempfile
from pathlib import Path
with tempfile.TemporaryDirectory(prefix='vasp-note-print-') as data:
 os.environ['VASP_WEB_DATA_DIR']=data
 os.environ['VASP_AI_KEY_FILE']=str(Path(data)/'ai.key')
 sys.path[:0]=['backend','tests']
 from test_report_ai_notes import report
 from report_export import render_html
 doc=report();doc['note_blocks']={'Model':[{'analysis_note':'实际能量 -10.0 eV','paper_note':'Results：事实；Discussion：需证据。'}]}
 print(render_html(doc,doc['markdown_sections']))`],{encoding:'utf8'});
  const printPage=await browser.newPage();await printPage.setContent(html);const pdf=await printPage.pdf({format:'A4'});assert.equal(pdf.subarray(0,5).toString(),'%PDF-');assert.ok(pdf.length>1000);await printPage.close();
  assert.deepEqual(errors,[]);console.log('PASS restored draft preview/adopt/manual edit/restore/save/discard, AI off/no model, safe Markdown and HTML/PDF.');
 }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
