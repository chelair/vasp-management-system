// Real report editor and exported renderer; mocked HTTP, no production writes/model/SSH.
const {build}=require('esbuild');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright-core');
const fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os'),http=require('node:http'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
(async()=>{
 const temp=await fs.mkdtemp(path.join(os.tmpdir(),'vasp-reaction-browser-'));
 let server,browser;
 try{
  const runtime=path.join(temp,'runtime.js');
  await build({entryPoints:['src/interactive/reportRuntime.ts'],bundle:true,minify:true,format:'iife',outfile:runtime});
  let prefix=process.env.REACTION_PREVIEW_PREFIX;
  if(!prefix){
   prefix=path.join(temp,'preview');
   execFileSync('.venv/bin/python',['-c',`
import sys,json,copy
from pathlib import Path
sys.path[:0]=['tests','backend']
from test_reaction_review import ReactionReviewTests
from unittest.mock import patch
import topic_simple,report_interactive
t=ReactionReviewTests();t.setUp()
d=topic_simple.create(t.user,t.conversation,'诊断B-F断键路径',{'property_id':'neb.barrier','model_queries':['PATH'],'objective':'研究B-F断键，尽量保持其他结构可比'})
prefix=Path(sys.argv[1])
with patch.object(report_interactive,'RUNTIME_PATH',Path(sys.argv[2])):
 prefix.with_suffix('.json').write_text(json.dumps(d,ensure_ascii=False));prefix.with_suffix('.html').write_text(topic_simple.render_html(d))
 d2=copy.deepcopy(d);d2['simple']['questions']=[];d2['simple']['answers'].update({'scope':'isolate_bond','bond.path':'A'});d2['revision']=2;d2['stage']='saved'
 Path(str(prefix)+'-confirmed.json').write_text(json.dumps(d2,ensure_ascii=False));Path(str(prefix)+'-confirmed.html').write_text(topic_simple.render_html(d2))
t.doCleanups()
`,prefix,runtime],{cwd:process.cwd()});
  }
  let doc=JSON.parse(await fs.readFile(prefix+'.json','utf8'));
  const confirmed=JSON.parse(await fs.readFile(prefix+'-confirmed.json','utf8'));
  let html=await fs.readFile(prefix+'.html','utf8');
  const confirmedHtml=await fs.readFile(prefix+'-confirmed.html','utf8');
  const scientificData=JSON.stringify(doc.data),writes=[];
  const bundle=await build({stdin:{contents:`import {createRoot} from 'react-dom/client';import {App} from 'antd';import TopicReportEditor from './src/components/reports/TopicReportEditor';import './src/styles/global.css';createRoot(document.getElementById('root')).render(<App><TopicReportEditor topicId={window.TOPIC_ID} onClose={()=>{}}/></App>);`,loader:'tsx',resolveDir:path.resolve('.')},bundle:true,write:false,outfile:'app.js',jsx:'automatic',define:{'process.env.NODE_ENV':'"production"'}});
  const files=Object.fromEntries(bundle.outputFiles.map(f=>[f.path.endsWith('.css')?'/app.css':'/app.js',f.text]));
  server=http.createServer(async(req,res)=>{
   const pathname=new URL(req.url,'http://local').pathname;
   if(pathname==='/standalone'){res.setHeader('Content-Type','text/html; charset=utf-8');res.end(html);return;}
   if(pathname.startsWith('/api/')){
    let raw='';for await(const chunk of req)raw+=chunk;
    if(req.method!=='GET')writes.push({path:pathname,body:raw?JSON.parse(raw):{}});
    let result=doc;
    if(pathname.endsWith('/preview'))result={html};
    else if(pathname.endsWith('/questions')){doc=structuredClone(confirmed);html=confirmedHtml;result=doc;}
    else if(pathname.endsWith('/content')){
     const body=JSON.parse(raw);doc={...doc,title:body.title,revision:doc.revision+1,assessment_edits:body.assessment};
     html=html.replace(/<h1>[^<]*<\/h1>/,'<h1>'+body.title+'</h1>');result=doc;
    }else if(pathname.endsWith('/export.html')){res.setHeader('Content-Type','text/html; charset=utf-8');res.end(html);return;}
    res.setHeader('Content-Type','application/json');res.end(JSON.stringify({success:true,data:result}));return;
   }
   res.setHeader('Content-Type',files[pathname]?(pathname.endsWith('.css')?'text/css':'text/javascript'):'text/html; charset=utf-8');
   res.end(files[pathname]||`<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/app.css"><div id="root"></div><script>window.TOPIC_ID=${JSON.stringify(doc.topic_id)};window.topicEvents=[];window.addEventListener('vasp:topic-updated',e=>window.topicEvents.push(e.detail));</script><script src="/app.js"></script>`);
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1440,height:1000},acceptDownloads:true});page.setDefaultTimeout(10000);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const base='http://127.0.0.1:'+server.address().port;
  await page.goto(base);await page.locator('iframe').waitFor();
  const frame=page.frameLocator('iframe[title="科研报告预览"]');
  await frame.locator('.conclusion').waitFor();
  assert.equal(await frame.locator('.warnings,.missing').count(),0);
  assert.equal(await frame.getByText('补充说明',{exact:true}).count(),0);
  const groups=page.locator('.ant-radio-group');
  for(let i=0;i<doc.simple.questions.length;i++)await groups.nth(i).locator('.ant-radio-wrapper').first().click();
  await page.getByRole('button',{name:'按我的回答继续',exact:true}).click();
  await page.getByRole('button',{name:'按我的回答继续',exact:true}).waitFor({state:'detached'});
  const answer=writes.find(w=>w.path.endsWith('/questions'));assert.equal(answer.body.continue_analysis,true);
  await page.waitForFunction(()=>window.topicEvents.length>0);
  assert.equal(await page.evaluate(()=>window.topicEvents[0].conversationId),doc.conversation_id);
  await page.getByRole('button',{name:'编辑报告',exact:true}).click();
  await page.getByRole('textbox',{name:'报告标题',exact:true}).fill('断键路径：问题、影响和下一步');
  assert.equal(await page.getByRole('switch',{name:'显示风险提示'}).count(),0);
  await page.getByRole('button',{name:'保存修改',exact:true}).click();
  await frame.locator('h1').getByText('断键路径：问题、影响和下一步',{exact:true}).waitFor();
  assert.equal(JSON.stringify(doc.data),scientificData,'editing and answers preserve scientific evidence');
  const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'下载 HTML',exact:true}).click()]);
  const exported=await fs.readFile(await download.path(),'utf8');
  assert(exported.includes('<sub>a</sub>'));assert(!exported.includes('<section class="warnings">'));
  await page.screenshot({path:'/tmp/vasp-reaction-editor.png'});
  await page.goto(base+'/standalone');await page.locator('h1').waitFor();
  await page.screenshot({path:'/tmp/vasp-reaction-desktop.png',fullPage:true});
  await page.locator('.views').first().scrollIntoViewIfNeeded();
  await page.getByRole('button',{name:'距离标注',exact:true}).first().waitFor();
  await page.getByRole('button',{name:'距离标注',exact:true}).first().click();
  await page.getByRole('button',{name:'距离标注',exact:true}).first().click();
  await page.screenshot({path:'/tmp/vasp-reaction-structures.png'});
  await page.emulateMedia({media:'print'});
  assert.equal(await page.locator('.static-structure').first().evaluate(e=>getComputedStyle(e).display),'block');
  await page.emulateMedia({media:'screen'});
  await page.setViewportSize({width:390,height:844});await page.evaluate(()=>window.scrollTo(0,0));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'mobile has no horizontal overflow');
  await page.screenshot({path:'/tmp/vasp-reaction-mobile.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS real reaction report editor, questions outside report, chat continuation event, scientific evidence unchanged, standalone 3D distance labels, print fallback, subscripts, HTML export and mobile; HTTP mocked');
 }finally{await browser?.close();if(server)await new Promise(r=>server.close(r));await fs.rm(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1});
