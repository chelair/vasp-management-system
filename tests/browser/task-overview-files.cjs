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
  const remote={INCAR:'present',KPOINTS:'present',POSCAR:'present',POTCAR:'present',CONTCAR:'missing',OUTCAR:'present',OSZICAR:'empty'};
  let fail=false,delay=false,release;
  const requests=[];
  const server=http.createServer((req,res)=>{
    if(req.url.startsWith('/api/')){
      requests.push({url:req.url,method:req.method});
      res.setHeader('Content-Type','application/json');
      const nameOfTask=req.url.split('/')[4];
      const items=['INCAR','KPOINTS','POSCAR','POTCAR','CONTCAR','OUTCAR','OSZICAR'].map(name=>{
        const state=nameOfTask==='b'?(name==='POTCAR'?'present':'missing'):nameOfTask==='c'?'missing':remote[name];
        return {name,status:'different',remote_status:state,
          local_size:100,local_count:1,remote_size:state==='missing'||state==='empty'?0:200,remote_count:state==='missing'?0:1};
      });
      const send=()=>{res.statusCode=fail?500:200;res.end(JSON.stringify({success:!fail,data:{files:items,remote_checked:true,remote_dir:'/remote/con2',checked_at:Date.now()/1000,error:null}}));};
      if(delay&&nameOfTask==='a')release=send;else send();
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
    await wait('OUTCAR','远端已有');
    assert.match(await row('INCAR').innerText(),/远端已有/,'draft must not mask remote file presence');
    assert.match(await page.locator('.preview-note').last().innerText(),/待生效修改：INCAR/);
    assert.match(await row('KPOINTS').innerText(),/远端已有/);
    assert.match(await row('OSZICAR').innerText(),/远端空文件/);
    assert.match(await row('CONTCAR').innerText(),/远端缺失/,'local cache must not imply remote existence');
    assert.match(await row('POTCAR').innerText(),/远端已有/);
    assert.doesNotMatch(await page.locator('.job-files').innerText(),/本地|待上传|待下载|核对一致/);
    assert.deepEqual(await page.locator('.job-file__name').allTextContents(),['INCAR','KPOINTS','POSCAR','POTCAR','CONTCAR','OUTCAR','OSZICAR']);
    assert(requests.every(r=>r.url.includes('remote=1&presence_only=1')),'opening the overview must query metadata without content comparison');
    const beforeDraft=requests.length;
    await page.evaluate(()=>window.setInput({draft:{KPOINTS:{mesh:[2,2,1]}},changes:[],files:{}}));
    await page.waitForTimeout(100);
    assert.equal(requests.length,beforeDraft,'editing local drafts must not query remote again');
    assert.match(await page.locator('.preview-note').last().innerText(),/待生效修改：KPOINTS/);
    remote.OSZICAR='changing';await page.getByRole('button',{name:'刷新状态'}).click();await wait('OSZICAR','远端更新中');
    remote.POTCAR='unknown';await page.getByRole('button',{name:'刷新状态'}).click();await wait('POTCAR','状态未知');
    fail=true;await page.getByRole('button',{name:'刷新状态'}).click();await wait('POSCAR','状态未知');
    assert.equal(await page.locator('.ant-empty').count(),0,'read failure must not pretend the directory is empty');
    fail=false;remote.CONTCAR='present';
    await page.evaluate(()=>window.dispatchEvent(new Event('vasp:inspection-completed')));await wait('CONTCAR','远端已有');
    const count=requests.length;
    await page.clock.fastForward(120000);await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    assert.equal(requests.length,count,'no polling or focus-triggered reads');
    delay=true;await page.getByRole('button',{name:'刷新状态'}).click();
    await page.waitForFunction(()=>document.querySelector('.job-files').textContent.includes('读取中'));
    while(!release)await new Promise(r=>setTimeout(r,10));
    await page.evaluate(()=>{window.setInput(null);window.select('b');});await wait('POTCAR','远端已有');
    release();await page.waitForTimeout(100);await wait('OUTCAR','远端缺失');
    assert.match(await row('POTCAR').innerText(),/远端已有/);
    await page.evaluate(()=>window.select('c'));await wait('POTCAR','远端缺失');
    await page.getByText('当前远端计算目录中尚无这些文件',{exact:true}).waitFor();
    assert(requests.every(r=>r.method==='GET'&&/^\/api\/jobs\/tasks\/[abc]\/file-status\?remote=1&presence_only=1$/.test(r.url)), 'only read-only remote metadata requests may be called');
    assert.deepEqual(errors,[]);
    console.log('PASS seven remote file states on open/refresh, independent local drafts, empty/changing/unknown, remote-only empty directory, no polling and stale response protection');
  }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
