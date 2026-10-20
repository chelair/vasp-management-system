// Isolated UI fixture; backend identity/race/auth guards are covered in test_agent_gateway.
const {build} = require('esbuild');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const http = require('node:http');
const path = require('node:path');
const assert = require('node:assert/strict');

(async()=>{
  const bundle=await build({stdin:{contents:`import React,{useState} from 'react';import {createRoot} from 'react-dom/client';import {App} from 'antd';
    import PriorJobReviewDialog from './src/components/jobs/PriorJobReviewDialog';
    function Harness(){const[open,setOpen]=useState(false);return <><button onClick={()=>setOpen(true)}>模拟提交报错</button>{open&&<PriorJobReviewDialog taskId="fixture" onClose={()=>setOpen(false)}/>}</>;}
    createRoot(document.getElementById('root')).render(<App><Harness/></App>);`,loader:'tsx',resolveDir:path.resolve('.')},
    bundle:true,write:false,format:'iife',jsx:'automatic',define:{'process.env.NODE_ENV':'"development"'}});
  let mode='missing', posts=[];
  const server=http.createServer(async(req,res)=>{
    if(!req.url.startsWith('/api/')){res.setHeader('Content-Type',req.url==='/app.js'?'text/javascript':'text/html');
      return res.end(req.url==='/app.js'?bundle.outputFiles[0].text:'<div id="root"></div><script src="/app.js"></script>');}
    const send=(status,data,message='')=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify({success:status===200,data,message}));};
    if(req.method==='GET'){
      if(mode==='error')return send(409,{},'LSF查询失败，禁止提交');
      return send(200,{job_id:'751321',server:'fixture',directory:'/fixture/con1',checked_at:'test',review_fingerprint:'fixed',
        lsf_status:mode==='active'?'RUN':'NOT_FOUND',already_confirmed:false,can_confirm:mode!=='active',blocker:mode==='active'?'LSF仍有活跃作业':'',
        note:'查不到不代表结束；需人工核对回执。',confirmation_summary:mode==='unverified'?'':'用户点击确认：已核对751321的LSF回执、目录及结束时间；不自动提交。',
        receipts:[{directory:'/fixture/con1',file:'751321.out',text:'Job 751321 Done\nTerminated at test\n<img src=x onerror="window.XSS=1">'}]});
    }
    const chunks=[];for await(const chunk of req)chunks.push(chunk);posts.push(JSON.parse(Buffer.concat(chunks).toString()));
    return send(200,{job_finished:true});
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({executablePath:'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox']});
  try{
    const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
    const base=`http://127.0.0.1:${server.address().port}`;
    await page.goto(base);assert.equal(await page.getByRole('button',{name:'核实旧作业',exact:true}).count(),0);
    await page.getByRole('button',{name:'模拟提交报错',exact:true}).click();
    const confirm=page.getByRole('button',{name:'确认旧作业已结束并解除报错',exact:true});
    await page.getByText('Job 751321 Done',{exact:false}).waitFor();assert.ok(await confirm.isEnabled());
    assert.equal(await page.evaluate(()=>window.XSS),undefined);assert.equal(posts.length,0);
    assert.equal(await page.getByRole('textbox').count(),0);assert.equal(await page.getByRole('checkbox').count(),0);
    await confirm.click();await page.getByText('旧作业阻塞已解除',{exact:false}).waitFor();
    assert.equal(posts.length,1);assert.equal(posts[0].expected_job_id,'751321');assert.equal(posts[0].confirmed_finished,true);
    mode='active';await page.goto(base);await page.getByRole('button',{name:'模拟提交报错',exact:true}).click();
    await page.getByText('LSF仍有活跃作业',{exact:true}).waitFor();assert.ok(await confirm.isDisabled());assert.equal(await page.getByRole('checkbox').count(),0);
    mode='unverified';await page.goto(base);await page.getByRole('button',{name:'模拟提交报错',exact:true}).click();
    await page.getByText('现有回执不足以核实',{exact:false}).waitFor();assert.ok(await confirm.isDisabled());
    mode='error';await page.goto(base);await page.getByRole('button',{name:'模拟提交报错',exact:true}).click();
    await page.getByText('LSF查询失败，禁止提交',{exact:true}).waitFor();assert.ok(await confirm.isDisabled());
    assert.equal(posts.length,1);assert.deepEqual(errors,[]);
    console.log('PASS prior-job error dialog: one-click explicit confirmation, no permanent entry/typing/auto-submit, receipt/active/query-failure guards, XSS');
  }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);process.exitCode=1;});
