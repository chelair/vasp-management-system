// Run: PLAYWRIGHT_MODULE=/path/to/playwright-core node tests/browser/job-structure-refresh.cjs
const { build } = require('esbuild');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const http = require('node:http');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
  const result = await build({stdin: {contents: `
    import React, {useState} from 'react';
    import {createRoot} from 'react-dom/client';
    import {useJobStructureRefresh} from './src/hooks/useJobStructureRefresh';
    import {runSingleInspection} from './src/api/inspections';
    const state = id => ({task_id:id, files:{POSCAR:{text:'input'},CONTCAR:{text:'old'}},
      draft:{INCAR:{NSW:'unsaved'}}, pending:true, source:{con:'con1'}, changes:[],
      synced:true, poscar_cif:'input', contcar_cif:'old'});
    function App(){
      const [ids,setIds]=useState(['a']); const [states,setStates]=useState({a:state('a'),b:state('b')});
      window.run=()=>runSingleInspection('a'); window.select=setIds; window.patch=()=>setStates(p=>({...p,a:{...p.a,contcar_cif:'manual'}}));
      useJobStructureRefresh(ids,states,setStates);
      return <pre>{JSON.stringify(states)}</pre>;
    }
    createRoot(document.getElementById('root')).render(<React.StrictMode><App/></React.StrictMode>);
  `, resolveDir:path.resolve('.'), loader:'tsx'}, bundle:true, write:false, format:'iife', define:{'process.env.NODE_ENV':'"development"'}});


  let calls=0, value='new', delayed=false, release;
  const payload=id=>({task_id:id,files:{POSCAR:{text:'input'},CONTCAR:{text:value}},poscar_cif:'input',contcar_cif:value});
  const server=http.createServer((req,res)=>{
    if(req.url.startsWith('/api/')){
      res.setHeader('Content-Type','application/json');
      if(req.url.includes('/run-single/')){res.end(JSON.stringify({success:true,data:{inspected:1}}));return;}
      calls++;const data=payload(req.url.includes('/a/')?'a':'b');
      const send=()=>res.end(JSON.stringify({success:true,data}));
      if(delayed) release=send;else send();return;
    }
    res.setHeader('Content-Type',req.url==='/app.js'?'text/javascript':'text/html');
    res.end(req.url==='/app.js'?result.outputFiles[0].text:'<div id="root"></div><script src="/app.js"></script>');
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const browser=await chromium.launch({executablePath:process.env.BROWSER_PATH || '/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox']});
  try {
    const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.clock.install();await page.goto('http://127.0.0.1:'+server.address().port);
    const waitValue=value=>page.waitForFunction(v=>JSON.parse(document.querySelector('pre').textContent).a.contcar_cif===v,value);
    await waitValue('new');const initial=calls;
    await page.clock.fastForward(120000);await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    assert.equal(calls,initial,'idle/focus must not make requests');
    value='inspection-result';await page.evaluate(()=>window.run());await waitValue(value);
    assert.equal(calls,initial+1,'one local read after inspection returns');
    assert.equal(await page.evaluate(()=>JSON.parse(document.querySelector('pre').textContent).a.draft.INCAR.NSW),'unsaved');
    assert.equal(await page.evaluate(()=>JSON.parse(document.querySelector('pre').textContent).a.source.con),'con1');
    await page.evaluate(()=>window.run());await waitValue(value); // 没回传结构仍沿用同一份结果。
    delayed=true;value='stale';await page.evaluate(()=>window.run());
    while(!release) await new Promise(r=>setTimeout(r,10));
    await page.evaluate(()=>window.patch());release();release=null;await page.waitForTimeout(100);await waitValue('manual');
    await page.evaluate(()=>window.run());while(!release)await new Promise(r=>setTimeout(r,10));
    await page.evaluate(()=>window.select([]));release();await page.waitForTimeout(100);await waitValue('manual');
    delayed=false;value='latest-local';await page.evaluate(()=>window.select(['a']));await waitValue(value);
    assert.deepEqual(errors,[]);
    console.log('PASS no polling/focus requests, inspection-return refresh, unchanged structure, draft protection, stale response guard, task-switch refresh (StrictMode)');
  }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
