// PLAYWRIGHT_MODULE=/path/to/playwright-core node tests/browser/task-overview-files.cjs
const { build } = require('esbuild');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const http = require('node:http');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
  const bundle = await build({stdin:{contents:`
    import React, {useState} from 'react';
    import {createRoot} from 'react-dom/client';
    import {App} from 'antd';
    import TaskOverview from './src/components/jobs/TaskOverview';
    function Fixture() {
      const [id,setId]=useState('a');
      const [input,setInput]=useState({task_id:'a',synced:true,source:{con:'con2'},
        files:{POSCAR:{text:'cached'},CONTCAR:{text:'old'}},draft:{},
        changes:[{file:'INCAR',key:'NSW',to:'100'}]});
      window.setInput=setInput;window.select=setId;
      const workspace=React.useMemo(()=>({files:{CONTCAR:true,'vasp.lsf':false}}),[]);
      return <App><TaskOverview task={{task_id:id,task_type:'opt',status:'pending',check:{}}}
        workspace={workspace} input={input}/></App>;
    }
    createRoot(document.getElementById('root')).render(<React.StrictMode><Fixture/></React.StrictMode>);
  `,resolveDir:path.resolve('.'),loader:'tsx'},bundle:true,write:false,format:'iife',jsx:'automatic',define:{'process.env.NODE_ENV':'"development"'}});
  let entries=[{name:'INCAR',size:20},{name:'KPOINTS',size:0},{name:'POSCAR',size:100},{name:'OUTCAR',size:50}];
  let fail=false,delay=false,release;
  const requests=[];
  const server=http.createServer((req,res)=>{
    if(req.url.startsWith('/api/')){
      requests.push({url:req.url,method:req.method});
      res.setHeader('Content-Type','application/json');
      const files=req.url.includes('/b/')?[{name:'POTCAR',size:5}]:entries;
      const verified=req.url.includes('remote=1');
      const states={INCAR:'synced',POSCAR:'different',OUTCAR:'sampled',POTCAR:'download'};
      const items=['INCAR','KPOINTS','POSCAR','POTCAR','CONTCAR','OUTCAR','OSZICAR'].map(name=>{
        const file=files.find(f=>f.name===name);
        return {name,status:file?.size===0?'empty':verified?(states[name]||'missing'):file?'local':'local_missing',
          local_size:file?.size||0,local_count:file?1:0,remote_size:verified?100:null,remote_count:verified?1:null};
      });
      const send=()=>{res.statusCode=fail?500:200;res.end(JSON.stringify({success:!fail,data:{files:items,remote_checked:verified,remote_dir:'/remote/con2',checked_at:Date.now()/1000,error:null}}));};
      if(delay&&req.url.includes('/a/'))release=send;else send();
      return;
    }
    res.setHeader('Content-Type',req.url==='/app.js'?'text/javascript':'text/html');
    res.end(req.url==='/app.js'?bundle.outputFiles[0].text:'<div id="root"></div><script src="/app.js"></script>');
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox']});
  try {
    const page=await browser.newPage();const errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.clock.install();await page.goto('http://127.0.0.1:'+server.address().port);
    const row=name=>page.locator('.job-file').filter({has:page.locator('.job-file__name',{hasText:new RegExp('^'+name.replace('.','\\.')+'$')})});
    const wait=async(name,label)=>{await page.waitForFunction(({name,label})=>[...document.querySelectorAll('.job-file')].some(e=>e.querySelector('.job-file__name').textContent===name&&e.querySelector('.job-file__state').textContent.includes(label)),{name,label});};
    await wait('OUTCAR','本地已有');
    assert.match(await row('INCAR').innerText(),/有修改待同步/);
    assert.match(await row('POSCAR').innerText(),/本地已有/);
    assert.match(await row('KPOINTS').innerText(),/空文件/);
    assert.match(await row('CONTCAR').innerText(),/本地缺失/);
    assert.match(await row('POTCAR').innerText(),/本地缺失/);
    assert.doesNotMatch(await page.locator('.job-files').innerText(),/最新|过时|未生成/);
    await page.evaluate(()=>window.setInput(null));await wait('INCAR','本地已有');
    assert.deepEqual(await page.locator('.job-file__name').allTextContents(),['INCAR','KPOINTS','POSCAR','POTCAR','CONTCAR','OUTCAR','OSZICAR']);
    assert(requests.every(r=>!r.url.includes('remote=1')),'opening the overview must not contact remote');
    await page.getByRole('button',{name:'刷新状态'}).click();
    await wait('INCAR','已核对一致');await wait('POSCAR','内容不同');await wait('OUTCAR','抽样一致');
    assert(requests.some(r=>r.url.endsWith('remote=1')),'manual refresh must request a remote comparison');
    // Drafts remain visible even if the legacy change list is missing.
    await page.evaluate(()=>window.setInput({draft:{KPOINTS:{mesh:[2,2,1]}},changes:[],files:{}}));
    await wait('KPOINTS','有修改待同步');await wait('POSCAR','本地已有');
    fail=true;await page.getByRole('button',{name:'刷新状态'}).click();await wait('POSCAR','状态未知');
    assert.match(await row('KPOINTS').innerText(),/有修改待同步/);
    assert.equal(await page.locator('.ant-empty').count(),0,'read failure must not pretend the directory is empty');
    fail=false;entries=[...entries,{name:'CONTCAR',size:80}];
    await page.evaluate(()=>window.dispatchEvent(new Event('vasp:inspection-completed')));
    await wait('CONTCAR','本地已有');
    const count=requests.length;
    await page.clock.fastForward(120000);await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    assert.equal(requests.length,count,'no polling or focus-triggered reads');
    // A delayed response for the previous task must never replace the selected task.
    delay=true;await page.getByRole('button',{name:'刷新状态'}).click();
    await page.waitForFunction(()=>document.querySelector('.job-files').textContent.includes('读取中'));
    while(!release)await new Promise(r=>setTimeout(r,10));
    await page.evaluate(()=>{window.setInput(null);window.select('b');});await wait('POTCAR','本地已有');
    release();await page.waitForTimeout(100);await wait('OUTCAR','本地缺失');
    assert.match(await row('POTCAR').innerText(),/本地已有/);
    assert(requests.every(r=>r.method==='GET'&&/^\/api\/jobs\/tasks\/[ab]\/file-status(?:\?remote=1)?$/.test(r.url)), 'only read-only file-status requests may be called');
    assert.deepEqual(errors,[]);
    console.log('PASS seven-file order, local and verified remote states, sampled outputs, pending drafts, failures, explicit refresh only, no polling, stale response protection');
  }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
