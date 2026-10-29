// Real AI component: general chat -> project creation SSE -> refreshed project scope.
const {build}=require('esbuild');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright-core');
const http=require('node:http'), path=require('node:path'), assert=require('node:assert/strict');
const stamp='2026-10-28T10:00:00';
const connection={id:'model',name:'测试模型',model:'mock',base_url:'https://example.invalid',max_tokens:4096,is_default:true,
  reasoning_effort:'default',effective_reasoning_effort:'default',reasoning_capabilities:{options:[{value:'default',label:'默认'}],tool_policy:'supported'}};
const detail={id:'c1',title:'新项目需求',task_id:null,project_id:null,connection_id:'model',prompt:'',prompt_version:1,workspace_enabled:true,
  created_at:stamp,updated_at:stamp,messages:[],runs:[],has_more:false};
const task={id:'alloy',name:'Alloy_opt',type:'opt',status:'pending',group:''};
const project={id:'p1',name:'RuCu_NG',closed:false,tasks:[task]};
let live, created=false, unresolved=false;
const requests=[];
(async()=>{
  const bundle=await build({stdin:{contents:`import React from 'react';import{createRoot}from'react-dom/client';import{App}from'antd';import{MemoryRouter}from'react-router-dom';import{AppearanceProvider}from'./src/context/AppearanceContext';import AI from'./src/pages/AI';import'./src/styles/global.css';createRoot(document.getElementById('root')).render(<AppearanceProvider><App><MemoryRouter initialEntries={['/ai?conversation=c1']}><AI/></MemoryRouter></App></AppearanceProvider>);`,loader:'tsx',resolveDir:path.resolve('.')},bundle:true,write:false,outfile:'app.js',jsx:'automatic',define:{'process.env.NODE_ENV':'"development"'}});
  const js=bundle.outputFiles.find(f=>f.path.endsWith('.js')).text,css=bundle.outputFiles.find(f=>f.path.endsWith('.css')).text;
  const server=http.createServer(async(req,res)=>{
    const url=new URL(req.url,'http://localhost');
    if(!url.pathname.startsWith('/api/')){
      res.setHeader('Content-Type',req.url==='/app.js'?'text/javascript':req.url==='/app.css'?'text/css':'text/html;charset=utf-8');
      return res.end(req.url==='/app.js'?js:req.url==='/app.css'?css:'<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/app.css"><div id="root"></div><script>localStorage.setItem("vasp.auth.token","mock")</script><script src="/app.js"></script>');
    }
    requests.push({path:url.pathname,method:req.method});let data={};
    const route=url.pathname;
    if(route.endsWith('/runs/live/events')){
      res.writeHead(200,{'Content-Type':'text/event-stream','Cache-Control':'no-cache'});
      res.write('data: '+JSON.stringify({run:live,message:detail.messages.at(-1)})+'\n\n');
      setTimeout(()=>{
        created=true;detail.project_id=project.id;
        live={...live,status:'completed',finished_at:stamp,tool_events:[{id:'create',name:'create_project_from_request',arguments:{name:'RuCu_NG'},result:{project_id:'p1',contents_complete:true},status:'completed',at:stamp}]};
        detail.runs=[live];detail.messages.at(-1).content='项目和优化任务已建立，原文已保留。';detail.messages.at(-1).status='completed';
        res.end('data: '+JSON.stringify({run:live,message:detail.messages.at(-1)})+'\n\n');
      },150);return;
    }
    if(route.endsWith('/connections')) data={items:[connection]};
    else if(route.endsWith('/targets')) data={items:created?[project]:[]};
    else if(route.endsWith('/conversations')) data={items:[detail]};
    else if(route.endsWith('/conversations/c1')) data=detail;
    else if(route.endsWith('/context')) data=created?{scope:'project',project:{name:'RuCu_NG',calc_description:'三个结构优化',expected_results:'预期吸附能 A > B'},requirements:{status:'ready',binding_summary:{unbound:unresolved?[{key:'diff',title:'差分电荷'}]:[]}},tasks:[{task_id:'alloy',task_name:'Alloy_opt',task_type:'opt',status:'pending'}],summary:{task_count:1},source:{kind:'local_project_snapshot'}}:{scope:'general'};
    else if(route.endsWith('/messages')){
      let raw='';for await(const part of req)raw+=part;assert.equal(JSON.parse(raw).content,'按原始需求建立RuCu_NG项目');
      live={id:'live',conversation_id:'c1',message_id:'a1',status:'running',model:'mock',connection_name:'测试模型',prompt_version:1,error:'',created_at:stamp,finished_at:null,usage:{},tool_events:[{id:'create',name:'create_project_from_request',arguments:{},result:{},status:'running',at:stamp}]};
      detail.messages=[{id:'u1',seq:1,role:'user',content:JSON.parse(raw).content,status:'completed',created_at:stamp},{id:'a1',seq:2,role:'assistant',content:'',status:'running',created_at:stamp}];detail.runs=[live];data=live;
    }else if(route.startsWith('/api/reports/topic')) data={items:[]};
    res.setHeader('Content-Type','application/json');res.end(JSON.stringify({success:true,data}));
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(12000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
  try{
    await page.goto('http://127.0.0.1:'+server.address().port);
    await page.getByRole('textbox',{name:'输入 AI 对话消息',exact:true}).fill('按原始需求建立RuCu_NG项目');
    await page.getByRole('button',{name:'发送',exact:true}).click();
    await page.getByText('项目和优化任务已建立，原文已保留。',{exact:true}).waitFor();
    await page.locator('.ai-composer-hint').filter({hasText:'已连接项目上下文 · 模型按需调用工具'}).waitFor();
    await page.getByRole('button',{name:'项目资料',exact:true}).click();
    await page.getByRole('tab',{name:'基本信息',exact:true}).click();
    await page.getByText('计算内容与预期已整理，AI可按需读取关联任务和结果。',{exact:true}).waitFor();
    await page.getByText('预期吸附能 A > B',{exact:true}).waitFor();
    await page.locator('.ant-drawer-close').click();
    unresolved=true;
    await page.setViewportSize({width:390,height:844});
    await page.reload();
    await page.getByRole('button',{name:'项目资料',exact:true}).click();
    await page.getByRole('tab',{name:'基本信息',exact:true}).click();
    await page.getByText('计算内容与预期已整理，仍有1项计算内容待关联。',{exact:true}).waitFor();
    assert.equal(requests.filter(r=>r.method==='POST').length,1);
    assert.ok(requests.filter(r=>r.path.endsWith('/targets')).length>=2);
    assert.deepEqual(errors,[]);
    console.log('PASS general chat creation, SSE completion, project scope/list/context refresh, desktop and narrow screen. HTTP/model/SSH are mocked.');
  }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
