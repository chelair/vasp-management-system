// Real Report component, saved chart data and isolated HTTP. No model or SSH.
const {build}=require('esbuild');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright-core');
const fs=require('node:fs/promises'),http=require('node:http'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const built=await build({stdin:{contents:`import {createRoot} from 'react-dom/client';import {App} from 'antd';import {MemoryRouter} from 'react-router-dom';import Report from './src/pages/Report';import './src/styles/global.css';createRoot(document.getElementById('root')).render(<MemoryRouter><App><Report/></App></MemoryRouter>);`,loader:'tsx',resolveDir:process.cwd()},bundle:true,write:false,outfile:'/tmp/vasp-report-convergence.js',format:'iife',jsx:'automatic',define:{'process.env.NODE_ENV':'"production"'}});
 const points=Array.from({length:191},(_,i)=>({step:i+1,energy:-100-i/100,max_force:1/(i+1)}));
 let doc={metadata:{report_id:'rpt_p',project_id:'p',project_name:'ReportFixture'},science:{opt:[{task_id:'endpoint',task_name:'M3_H_mig_IS',energy_force_series:points}],free_energy:[],neb:[],ele:{tasks:[]}},dialogs:[{id:'dlg_conv_endpoint',title:'M3_H_mig_IS · 收敛历史（能量 / 最大力）',chart:'charts/endpoint_energy_force.svg',note:'共 191 个离子步'}],markdown_sections:[{key:'science',title:'科学结果',markdown:'### NEB 过渡态\n\n#### PATH\n\n[查看（191 步）](#dlg_conv_endpoint)'}]};
 const cif='data_fixture\n_cell_length_a 10\n_cell_length_b 10\n_cell_length_c 10\n_cell_angle_alpha 90\n_cell_angle_beta 90\n_cell_angle_gamma 90\nloop_\n_atom_site_label\n_atom_site_type_symbol\n_atom_site_fract_x\n_atom_site_fract_y\n_atom_site_fract_z\nC1 C 0.4 0.4 0.4\nO1 O 0.52 0.4 0.4\n';
 doc.science.opt.push({task_id:'opt',task_name:'OPT',structure:{poscar_cif:cif}}, {task_id:'legacy',task_name:'Legacy'});
 doc.science.free_energy=[{group_id:'fe',group_name:'FreeEnergy',structures:[{opt_task_id:'opt',structure_label:'A',cif,free_energy_ev:-10,converged:true,corrected:true},{opt_task_id:'opt2',structure_label:'B',cif,free_energy_ev:-9,converged:true,corrected:true}]}];
 doc.science.neb=[{task_id:'neb',task_name:'NEB',barrier_ev:.5,images:[0,.5,.2].map((energy,i)=>({label:String(i),cif,relative_energy_ev:energy,energy_ev:-10+energy,max_force_ev_per_a:.01}))},
  {task_id:'waiting',task_name:'Waiting',endpoint_path:{group_id:'endpoints',group_name:'Endpoints',structures:[{structure_label:'IS',display_label:'初态-IS',cif},{structure_label:'FS',display_label:'末态-FS',cif}]}}];
 doc.science.ele.tasks=[{task_id:'ele',task_name:'Electronic',bader_summary:{cif,atoms:[{index:1,element:'C',net_charge:.2},{index:2,element:'O',net_charge:-.2}]},work_function_summary:{z:[0,1,2],potential:[-1,0,1],vacuum_level:1,efermi:-3,work_function:4}},{task_id:'wf_missing',task_name:'MissingWorkFunction',work_function_summary:{z:[0,1]}}];
 doc.dialogs.push({id:'dlg_conv_legacy',title:'Legacy · 收敛历史',chart:'charts/legacy_energy_force.svg',note:'旧快照只有静态曲线'});
 doc.markdown_sections[0].markdown+='\n\n[旧报告曲线](#dlg_conv_legacy)\n\n![内嵌曲线](charts/endpoint_energy_force.svg)\n\n#### OPT\n\n@[structure-3d:opt]\n\n![初始结构](images/opt.png)\n\n#### Legacy\n\n@[structure-3d:legacy]\n\n![旧版结构](images/legacy.png)\n\n#### FreeEnergy\n\n![自由能](charts/fe_step.svg)\n\n@[free-energy-3d:fe]\n\n#### Waiting\n\n@[free-energy-3d:endpoints]\n\n#### NEB\n\n![能垒](charts/neb_barrier.svg)\n\n@[neb-3d:neb]\n\n#### Electronic\n\n@[bader-table:ele]\n\n![功函数](charts/wf.svg)\n\n@[work-function-chart:ele]\n\n![缺少曲线数据](charts/wf_missing.svg)\n\n@[work-function-chart:wf_missing]\n\n![PDOS](charts/pdos.svg)\n\n@[pdos-chart:ele]';
 let meta={report_id:'rpt_p',project_id:'p',project_name:'ReportFixture',generated_at:'2026-11-17',summary:'收敛历史验证'};
 if(process.env.REPORT_FIXTURE_ID){const index=JSON.parse(await fs.readFile('data/reports/index.json'));meta=index.find(r=>r.report_id===process.env.REPORT_FIXTURE_ID);assert.ok(meta);doc=JSON.parse(await fs.readFile(path.join('data/reports',meta.json_path)));const spec=doc.dialogs.find(d=>d.title.includes('M3_H_mig_IS')&&d.chart);doc.markdown_sections=[{key:'science',title:'科学结果',markdown:`### NEB 过渡态\n\n[查看（191 步）](#${spec.id})`}];}
 const secondMeta={report_id:'rpt_other',project_id:'other',project_name:'OtherReport',generated_at:'2026-11-16',summary:'另一份报告'};const secondDoc={metadata:{report_id:'rpt_other'},science:{opt:[{task_id:'second',energy_force_series:points}],free_energy:[],neb:[],ele:{tasks:[]}},dialogs:[{id:'dlg_conv_second',title:'其他项目收敛历史',chart:'charts/second_energy_force.svg'}],markdown_sections:[{key:'science',title:'科学结果',markdown:'[查看另一份曲线](#dlg_conv_second)'}]};
 let releaseAssistant;const requests=[],errors=[];const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==','base64');
 const server=http.createServer(async(req,res)=>{
  if(req.url==='/app.js'||req.url==='/app.css'){const ext=req.url.endsWith('.js')?'.js':'.css';res.setHeader('Content-Type',ext==='.js'?'text/javascript':'text/css');return res.end(built.outputFiles.find(f=>f.path.endsWith(ext)).text);}
  if(req.url.startsWith('/3dmol/')){res.setHeader('Content-Type','text/javascript');return res.end(await fs.readFile('public/3dmol/3Dmol-min.js'));}
  if(!req.url.startsWith('/api/')){res.setHeader('Content-Type','text/html');return res.end('<meta charset="utf-8"><link rel="stylesheet" href="/app.css"><div id="root"></div><script src="/app.js"></script>');}
  requests.push([req.method,req.url]);let data={};
  if(req.url==='/api/projects')data={projects:[{id:meta.project_id,name:meta.project_name,tasks:[],ai_report_notes_enabled:false},{id:'other',name:'OtherReport',tasks:[],ai_report_notes_enabled:false}]};
  else if(req.url==='/api/reports/project/list')data={reports:process.env.REPORT_FIXTURE_ID?[meta]:[meta,secondMeta]};
  else if(req.url===`/api/reports/project/${meta.report_id}`)data={meta,structured:doc,dialogs:doc.dialogs,markdown_sections:doc.markdown_sections,sections:doc.markdown_sections.map(s=>({key:s.key,title:s.title})),notes:{},note_blocks:{},edits:{hidden_sections:[],hidden_elements:[]}};
  else if(req.url==='/api/reports/project/rpt_other')data={meta:secondMeta,structured:secondDoc,dialogs:secondDoc.dialogs,markdown_sections:secondDoc.markdown_sections,sections:[{key:'science',title:'科学结果'}],notes:{},edits:{hidden_sections:[],hidden_elements:[]}};
  else if(req.url.endsWith('/layout'))data={version:1,revision:0,objects:[]};
  else if(req.url.endsWith('/review'))data={source:'source',revision:'revision',modules:[],comments:[],elements:[],stale:false};
  else if(req.url.includes('/assistant/')){
   const send=()=>{if(res.writableEnded)return;res.setHeader('Content-Type','application/json');res.end(JSON.stringify({success:true,data:{conversation:{id:'conversation',runs:[{id:'completed-work',status:'completed'}],messages:[]},drafts:[]}}));};
   if(!releaseAssistant){releaseAssistant=send;return;}send();return;
  }
  else if(req.url.endsWith('/connections'))data={items:[]};
  else if(req.url.endsWith('/pdos')){res.statusCode=500;res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({success:false,message:'隔离PDOS读取失败'}));}
  else if(req.url.includes('/images/')){res.setHeader('Content-Type','image/png');return res.end(png);}
  else if(req.url.includes('/files/')){res.setHeader('Content-Type','image/svg+xml');return res.end('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="260"><path d="M10 10L500 200" stroke="blue"/></svg>');}
  res.setHeader('Content-Type','application/json');res.end(JSON.stringify({success:true,data}));
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({executablePath:'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox','--enable-unsafe-swiftshader']});const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(7000);page.on('pageerror',e=>errors.push(e.message));
 try{
  if(process.env.NO_DIALOG_TOGGLE)await page.addInitScript(()=>{const add=HTMLDialogElement.prototype.addEventListener;HTMLDialogElement.prototype.addEventListener=function(type,...args){if(type!=='toggle')return add.call(this,type,...args);};});
  await page.addInitScript(()=>{window.__detailRequests=0;const original=window.fetch;window.fetch=async(...args)=>{const response=await original(...args);if(/\/api\/reports\/project\/rpt_[^/]+$/.test(String(args[0])))window.__detailRequests++;return response;};});
  await page.goto('http://127.0.0.1:'+server.address().port);
  const spec=doc.dialogs.find(d=>d.title.includes('M3_H_mig_IS')&&d.chart);assert.ok(spec);
  const dialog=page.locator('#'+spec.id);
  await page.locator(`[data-dialog="${spec.id}"]`).first().click({noWaitAfter:true});
  await page.waitForFunction(id=>document.getElementById(id)?.open,spec.id);
  await dialog.locator('canvas').first().waitFor();
  assert.ok(await dialog.locator('canvas').first().evaluate(c=>c.width>0&&c.height>0));
  releaseAssistant();
  await page.waitForFunction(()=>window.__detailRequests>=2);await page.waitForTimeout(100);
  await dialog.locator('canvas').first().waitFor();
  await dialog.getByRole('button',{name:'关闭',exact:true}).click();await page.locator(`[data-dialog="${spec.id}"]`).first().click({noWaitAfter:true});await dialog.locator('canvas').first().waitFor();
  if(process.env.REPORT_SCREENSHOT)await dialog.screenshot({path:process.env.REPORT_SCREENSHOT});
  if(!process.env.REPORT_FIXTURE_ID){
   for(const kind of ['structure-3d','free-energy-3d','neb-3d','bader-table']){
    const host=page.locator(`[data-report-widget="${kind}"]`).filter({has:page.locator('canvas')});await host.first().locator('canvas').first().waitFor();
   }
   await page.locator('[data-panel="free-energy"] canvas').first().waitFor();
   await page.locator('[data-report-widget="work-function-chart"][data-task-id="ele"] canvas').first().waitFor();
   assert.equal(await page.locator('img[alt="缺少曲线数据"]').isVisible(),true,'missing structured curve must retain SVG');
   assert.equal(await page.locator('img[alt="旧版结构"]').isVisible(),true,'missing CIF must retain existing PNG');
   assert.equal(await page.locator('img[alt="PDOS"]').isVisible(),true,'failed PDOS load must retain SVG');
   assert.equal(await page.locator('img[alt="初始结构"]').isVisible(),false,'PNG hidden only after 3D viewer is ready');
   assert.equal(await page.locator('.report-ef-chart canvas').count(),2,'inline curves survive unchanged report reload');
   await dialog.getByRole('button',{name:'关闭',exact:true}).click();
   await page.locator('[data-dialog="dlg_conv_legacy"]').click();
   const legacy=page.locator('#dlg_conv_legacy');assert.equal(await legacy.locator('img').isVisible(),true);assert.equal(await legacy.locator('canvas').count(),0);
   await legacy.getByRole('button',{name:'关闭',exact:true}).click();
   await page.emulateMedia({media:'print'});assert.equal(await page.locator('img[alt="内嵌曲线"]').isVisible(),true);assert.equal(await page.locator('.report-ef-chart').isVisible(),false);
   await page.emulateMedia({media:'screen'});await page.setViewportSize({width:390,height:844});await page.locator('[data-report-widget="structure-3d"][data-task-id="opt"] canvas').first().waitFor();
   assert.ok(await page.locator('[data-report-widget="structure-3d"][data-task-id="opt"] canvas').first().evaluate(c=>c.width>0&&c.height>0));
   await page.setViewportSize({width:1440,height:1000});
   await page.locator('.report-item').filter({hasText:'另一份报告'}).click();
   await page.locator('[data-dialog="dlg_conv_second"]').click();await page.locator('#dlg_conv_second canvas').first().waitFor();await page.locator('#dlg_conv_second').getByRole('button',{name:'关闭',exact:true}).click();
   await page.locator('.report-item').filter({hasText:'收敛历史验证'}).click();await page.locator('[data-report-widget="structure-3d"][data-task-id="opt"] canvas').first().waitFor();await page.locator('.report-ef-chart canvas').first().waitFor();
  }
  assert.deepEqual(errors,[]);assert.ok(requests.every(([method])=>method==='GET'));
  console.log(process.env.REPORT_FIXTURE_ID?'PASS saved M3_H_mig_IS convergence data, old-browser dialog open/reopen and background reload; no writes.':'PASS convergence/open/reopen/reload, inline curve, OPT/free-energy/NEB/endpoint/Bader 3D, work function, old/missing/failed fallback, print/mobile and report switching; no writes.');
 }catch(e){console.error(JSON.stringify(await page.evaluate(()=>({dialogs:[...document.querySelectorAll('dialog')].filter(d=>d.id.includes('conv')).map(d=>({id:d.id,open:d.open,html:d.innerHTML.slice(-1500)})),hosts:[...document.querySelectorAll('.report-ef-chart')].map(el=>({task:el.dataset.efTask,connected:el.isConnected,html:el.innerHTML.slice(0,200)}))})),null,2));console.error(errors);throw e;}
 finally{releaseAssistant?.();await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
