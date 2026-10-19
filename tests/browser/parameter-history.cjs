// PLAYWRIGHT_MODULE=/path/to/playwright-core node tests/browser/parameter-history.cjs
const { build } = require('esbuild');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const http = require('node:http');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
  const bundle = await build({stdin:{contents:`
    import React from 'react';
    import {createRoot} from 'react-dom/client';
    import InputSourceBanner from './src/components/jobs/InputSourceBanner';
    const input={task_id:'fixture',source:{con:'con6'},synced:true,files:{},pending:true,
      poscar_cif:null,contcar_cif:null,draft:{INCAR:{NSW:'999'}},
      changes:[{file:'INCAR',key:'NSW',from:'410',to:'999',at:'2026-10-19T12:00:00'}],
      applied_history:[
        {id:'uploaded',at:'2026-10-19T11:00:00',event:'upload',directory:'/project/task/con6',job_id:null,
          changes:[{file:'INCAR',key:'NSW',before:'309',after:'410',baseline_known:true}]},
        {id:'submitted',at:'2026-10-19T10:00:00',event:'submit',directory:'/project/task/con5',job_id:'42',
          changes:[{file:'INCAR',key:'NSW',before:null,after:'309',baseline_known:false}]}
      ]};
    createRoot(document.getElementById('root')).render(<InputSourceBanner input={input}
      onSync={()=>{}} onRevertChange={()=>{}} onRevertFiles={()=>{}}/>);
  `,resolveDir:path.resolve('.'),loader:'tsx'},bundle:true,write:false,format:'iife',jsx:'automatic',define:{'process.env.NODE_ENV':'"development"'}});
  let apiCalls=0;
  const server=http.createServer((req,res)=>{
    if(req.url.startsWith('/api/'))apiCalls++;
    res.setHeader('Content-Type',req.url==='/app.js'?'text/javascript':'text/html');
    res.end(req.url==='/app.js'?bundle.outputFiles[0].text:'<div id="root"></div><script src="/app.js"></script>');
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox']});
  try {
    const page=await browser.newPage();const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto('http://127.0.0.1:'+server.address().port);
    await page.getByText('实际参数记录（最近 2 次，最多 5 次，不含草稿）').click();
    await page.getByText('旧值未采集').waitFor();
    const history=page.locator('.ant-collapse-content-box');
    assert.match(await history.innerText(),/309 → 410/);
    assert.match(await history.innerText(),/作业 42/);
    assert.match(await history.innerText(),/con5/);
    assert.match(await history.innerText(),/con6/);
    assert.doesNotMatch(await history.innerText(),/999/,'draft must not enter applied history');
    assert.equal(await page.locator('.input-source__pending').count(),1,'draft stays independently visible');
    assert.equal(apiCalls,0,'opening parameter history never polls or queries remote');
    assert.deepEqual(errors,[]);
    console.log('PASS actual parameter history, directory/job provenance, drafts separate, no background request');
  } finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
