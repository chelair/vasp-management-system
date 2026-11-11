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
    window.actions=[];
    function Fixture() {
      const [id,setId]=useState('a');
      const [metadata,setMetadata]=useState({});
      const [busy,setBusy]=useState({});
      const [input,setInput]=useState({task_id:'a',synced:true,source:{con:'con2'},
        files:{POSCAR:{text:'cached'},CONTCAR:{text:'old'}},draft:{},
        changes:[{file:'INCAR',key:'NSW',to:'100'}]});
      window.setInput=setInput;window.select=setId;window.setMetadata=setMetadata;window.setBusy=setBusy;
      const workspace=React.useMemo(()=>({files:{CONTCAR:true,'vasp.lsf':false}}),[]);
      return <App><TaskOverview task={{task_id:id,task_type:'opt',status:'pending',check:{},...metadata}}
        workspace={workspace} input={input} {...busy}
        onSubmit={task=>window.actions.push('submit:'+task.task_id)}
        onStop={task=>window.actions.push('stop:'+task.task_id)}/></App>;
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
    await wait('OUTCAR','未查询');
    assert.equal(await page.locator('.job-file__state').filter({hasText:'未查询'}).count(),7);
    assert.equal(requests.length,0,'opening the overview in StrictMode must not query remote');
    const refresh=()=>page.getByRole('button',{name:'刷新状态'}).click();
    await refresh();await wait('OUTCAR','远端已有');
    assert.equal(requests.length,1,'one click must make exactly one request');
    assert.match(await row('INCAR').innerText(),/远端已有/,'draft must not mask remote file presence');
    assert.match(await page.locator('.preview-note').last().innerText(),/待生效修改：INCAR/);
    assert.match(await row('KPOINTS').innerText(),/远端已有/);
    assert.match(await row('OSZICAR').innerText(),/远端空文件/);
    assert.match(await row('CONTCAR').innerText(),/远端缺失/,'local cache must not imply remote existence');
    assert.match(await row('POTCAR').innerText(),/远端已有/);
    assert.doesNotMatch(await page.locator('.job-files').innerText(),/本地|待上传|待下载|核对一致/);
    assert.deepEqual(await page.locator('.job-file__name').allTextContents(),['INCAR','KPOINTS','POSCAR','POTCAR','CONTCAR','OUTCAR','OSZICAR']);
    const beforeDraft=requests.length;
    await page.evaluate(()=>{
      window.setInput({source:{synced_at:12345},draft:{KPOINTS:{mesh:[2,2,1]}},changes:[],files:{}});
      window.setMetadata({status:'running',job_id:'123',remote_dir:'/remote/new',current_output:{latest_dir:'/remote/new/con3'}});
      window.dispatchEvent(new Event('vasp:inspection-completed'));
    });
    await page.waitForTimeout(100);
    assert.equal(requests.length,beforeDraft,'draft/sync/status/job/directory changes and inspection must not query remote again');
    assert.match(await page.locator('.preview-note').last().innerText(),/待生效修改：KPOINTS/);
    remote.OSZICAR='changing';await page.getByRole('button',{name:'刷新状态'}).click();await wait('OSZICAR','远端更新中');
    assert.match(requests.at(-1).url,/&force=1$/,'manual refresh must bypass the server cache');
    remote.POTCAR='unknown';await page.getByRole('button',{name:'刷新状态'}).click();await wait('POTCAR','状态未知');
    fail=true;await page.getByRole('button',{name:'刷新状态'}).click();await wait('POSCAR','状态未知');
    assert.equal(await page.locator('.ant-empty').count(),0,'read failure must not pretend the directory is empty');
    fail=false;remote.CONTCAR='present';
    const beforeInspection=requests.length;
    await page.evaluate(()=>window.dispatchEvent(new Event('vasp:inspection-completed')));
    await page.waitForTimeout(100);await wait('CONTCAR','状态未知');
    assert.equal(requests.length,beforeInspection,'inspection must not retry failed file reads');
    await refresh();await wait('CONTCAR','远端已有');
    const count=requests.length;
    await page.clock.fastForward(120000);await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    assert.equal(requests.length,count,'no polling or focus-triggered reads');
    delay=true;await page.getByRole('button',{name:'刷新状态'}).click();
    await page.waitForFunction(()=>document.querySelector('.job-files').textContent.includes('读取中'));
    while(!release)await new Promise(r=>setTimeout(r,10));
    const beforeSwitch=requests.length;
    await page.evaluate(()=>{window.setInput(null);window.select('b');});await wait('POTCAR','未查询');
    release();await page.waitForTimeout(100);await wait('OUTCAR','未查询');
    assert.equal(requests.length,beforeSwitch,'switching tasks must not query or accept the old response');
    await refresh();await wait('OUTCAR','远端缺失');
    assert.match(await row('POTCAR').innerText(),/远端已有/);
    await page.evaluate(()=>window.select('c'));await wait('POTCAR','未查询');
    assert.equal(await page.locator('.ant-empty').count(),0,'unqueried state must not imply empty directory');
    await refresh();await wait('POTCAR','远端缺失');
    await page.getByText('当前远端计算目录中尚无这些文件',{exact:true}).waitFor();
    assert(requests.every(r=>r.method==='GET'&&/^\/api\/jobs\/tasks\/[abc]\/file-status\?remote=1&presence_only=1&force=1$/.test(r.url)), 'only manual read-only remote metadata requests may be called');
    assert.equal(requests.length,8,'requests must match the eight explicit refresh clicks');
    const actionButton=page.getByRole('button',{name:/提交作业|停止作业/});
    for(const status of ['pending','queued','running','zombied','completed','unconverged','archived']){
      await page.evaluate(status=>window.setMetadata({status,job_id:'123'}),status);
      const expected=['completed','unconverged','archived'].includes(status)?'提交作业':'停止作业';
      await page.getByRole('button',{name:new RegExp(expected)}).waitFor();
      assert.equal(await actionButton.count(),1,'each task state must show one submit/stop action');
    }
    await page.evaluate(()=>window.setMetadata({status:'pending',job_id:null}));
    await page.getByRole('button',{name:/提交作业/}).click();
    await page.evaluate(()=>window.setBusy({submitting:true}));
    await page.waitForFunction(()=>document.querySelector('.ant-btn-loading')?.textContent.includes('提交作业'));
    await page.evaluate(()=>{window.setBusy({});window.setMetadata({status:'running',job_id:'123'});});
    await page.getByRole('button',{name:/停止作业/}).click();
    assert.deepEqual(await page.evaluate(()=>window.actions),['submit:c'],'opening stop confirmation must not stop the job');
    await page.getByRole('button',{name:'取 消',exact:true}).click();
    await page.getByRole('button',{name:/停止作业/}).click();
    await page.getByRole('button',{name:'停 止',exact:true}).click();
    await page.evaluate(()=>window.setBusy({stopping:true}));
    await page.waitForFunction(()=>document.querySelector('.ant-btn-loading')?.textContent.includes('停止作业'));
    assert.deepEqual(await page.evaluate(()=>window.actions),['submit:c','stop:c']);
    assert.equal(requests.length,8,'button state changes must not trigger file queries');
    await page.evaluate(()=>{window.setBusy({});window.setMetadata({status:'running',job_id:'352424',stop_requested_at:'2026-11-10T20:45:32',stop_requested_job_id:'352424'});});
    await page.getByRole('button',{name:'核对停止状态',exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:/创建续算/}).isDisabled(),true);
    assert.equal(await page.getByRole('button',{name:/提交作业/}).count(),0);
    assert.equal(await page.getByRole('button',{name:/停止作业/}).count(),0);
    assert.ok((await page.getByRole('alert').innerText()).includes('正在等待调度器确认结束'));
    await page.getByRole('button',{name:'核对停止状态',exact:true}).click();
    assert.deepEqual(await page.evaluate(()=>window.actions),['submit:c','stop:c','stop:c']);
    await page.evaluate(()=>window.setMetadata({status:'pending',job_id:null}));
    await page.getByRole('button',{name:/提交作业/}).waitFor();
    assert.equal(await page.getByRole('button',{name:/创建续算/}).isEnabled(),true);
    assert.equal(requests.length,8,'stop intent and completion do not add file queries');
    assert.deepEqual(errors,[]);
    console.log('PASS manual-only file queries, no automatic reads, seven remote states, failure retry/stale response protection; single submit/stop button across task states, confirmation/cancel and loading feedback');
  }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
