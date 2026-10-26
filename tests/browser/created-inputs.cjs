// Isolated real Jobs page + mocked HTTP. No production data, SSH or model calls.
const {build}=require('esbuild');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright-core');
const http=require('node:http'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{
  const bundle=await build({stdin:{contents:`
    import React from 'react';import {createRoot} from 'react-dom/client';
    import {MemoryRouter} from 'react-router-dom';import {App} from 'antd';
    import Jobs from './src/pages/Jobs';
    createRoot(document.getElementById('root')).render(<MemoryRouter initialEntries={[location.pathname+location.search]}><App><Jobs/></App></MemoryRouter>);
  `,resolveDir:path.resolve('.'),loader:'tsx'},bundle:true,write:false,format:'iife',jsx:'automatic',define:{'process.env.NODE_ENV':'"development"'}});
  const group={group_id:'g',group_type:'neb',name:'Path',structure_label:''};
  const task=(id,type,status,extra={})=>({task_id:id,task_type:type,model_name:id,status,
    last_energy:null,last_check_time:null,job_id:null,notes:'',continuation_ready:false,
    continuation_dir:null,remote_dir:'/P/'+id,local_dir:'/P/'+id,dir_path:'P/'+id,...extra});
  const tasks=[task('initial','opt','archived',{archived_from:'completed',group:{...group,group_role:'initial_opt'}}),
    task('final','opt','completed',{group:{...group,group_role:'final_opt'}}),
    task('neb','neb','pending',{group:{...group,group_role:'neb_images'}}),
    task('bad','opt','archived',{archived_from:'unconverged'})];
  const project={id:'p',name:'P',server:'mock',status:'active',progress:0,remainingHours:0,tasks};
  let created=false;const requests=[];
  const state=id=>({task_id:id,synced:true,source:{con:'',remote_dir:'/P/'+id,kind:created?'create':'manual'},
    files:{INCAR:{text:'ENCUT = '+(created?577:411)+'\nIBRION = 3\n',params:{ENCUT:String(created?577:411),IBRION:'3'}},
      KPOINTS:{text:'mesh\n0\nGamma\n'+(created?'3 4 1':'1 1 1')+'\n0 0 0\n',mesh:created?[3,4,1]:[1,1,1]}},
    draft:{},changes:[],applied_history:[],pending:false,poscar_cif:null,contcar_cif:null});
  const server=http.createServer(async(req,res)=>{
    if(!req.url.startsWith('/api/')){res.setHeader('Content-Type',req.url==='/app.js'?'text/javascript':'text/html');res.end(req.url==='/app.js'?bundle.outputFiles[0].text:'<div id="root"></div><script src="/app.js"></script>');return;}
    requests.push({url:req.url,method:req.method});let data={};
    if(req.url==='/api/projects')data={projects:[project]};
    else if(req.url==='/api/task-types')data={task_types:[{type:'opt',description:'OPT',workload_weight:1,subtypes:[]},{type:'neb',description:'NEB',workload_weight:1,subtypes:[]}]};
    else if(req.url==='/api/jobs/tasks/neb/create-neb-files'){
      let body='';for await(const chunk of req)body+=chunk;
      assert.equal(JSON.parse(body).initial_opt_task_id,'initial');
      created=true;data={neb_dir:'/P/neb',images:['00','01','02'],warnings:[]};
    }else if(/\/input$/.test(req.url))data=state(req.url.split('/')[4]);
    else if(/\/files$/.test(req.url))data={files:[{name:'INCAR',size:30},{name:'KPOINTS',size:30}]};
    else if(/\/files\/INCAR$/.test(req.url))data={content:state('neb').files.INCAR.text};
    else if(/\/files\/KPOINTS$/.test(req.url))data={content:state('neb').files.KPOINTS.text};
    else if(req.url.startsWith('/api/jobs/nodes'))data={nodes:[],queues:[]};
    res.setHeader('Content-Type','application/json');res.end(JSON.stringify({success:true,data}));
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox']});
  const page=await browser.newPage();page.setDefaultTimeout(10000);
  try{
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:'+server.address().port+'/?task=neb');
    await page.getByRole('tab',{name:'INCAR',exact:true}).click();
    const encut=page.locator('.job-incar-field').filter({has:page.locator('.job-incar-field__label').getByText('ENCUT',{exact:true})}).locator('input').first();
    await encut.waitFor();assert.equal(await encut.inputValue(),'411');
    await page.getByRole('tab',{name:'KPOINTS',exact:true}).click();
    const grid=page.locator('.job-kpoints-field').filter({has:page.getByText('k 网格',{exact:true})}).locator('input');
    assert.deepEqual(await grid.evaluateAll(rows=>rows.map(row=>row.value)),['1','1','1']);
    await page.getByRole('tab',{name:'INCAR',exact:true}).click();
    await page.getByRole('button',{name:/创建计算文件/}).click();
    const dialog=page.getByRole('dialog',{name:'创建计算文件 · neb'});
    await dialog.getByText('initial（已归档，优化已完成）',{exact:true}).waitFor();
    const selects=dialog.locator('.ant-select');
    await selects.first().click();
    await page.locator('.ant-select-item-option-disabled').getByText('bad（archived）',{exact:true}).waitFor();
    await page.keyboard.press('Escape');
    await dialog.getByRole('button',{name:'创建计算文件',exact:true}).click();
    await dialog.waitFor({state:'hidden'});
    await page.waitForFunction(()=>[...document.querySelectorAll('.job-incar-field')].some(row=>row.querySelector('.job-incar-field__label')?.textContent.startsWith('ENCUT')&&row.querySelector('input')?.value==='577'));
    assert.equal(await encut.inputValue(),'577','creation must replace the cached INCAR editor without reloading the page');
    await page.getByRole('tab',{name:'KPOINTS',exact:true}).click();
    assert.deepEqual(await grid.evaluateAll(rows=>rows.map(row=>row.value)),['3','4','1'],'already mounted KPOINTS editor must also refresh');
    assert(requests.some(r=>r.url==='/api/jobs/tasks/neb/input'&&r.method==='GET'));
    assert.deepEqual(requests.filter(r=>r.method!=='GET').map(r=>r.url),['/api/jobs/tasks/neb/create-neb-files'],'no submit, sync POST or background remote actions');
    assert.deepEqual(errors,[]);
    console.log('PASS archived completed OPT selectable, unconverged archived OPT disabled, creation refreshes cached INCAR/KPOINTS, only explicit creation POST');
  }catch(error){console.error((await page.locator('body').innerText()).slice(0,14000));throw error;}finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
