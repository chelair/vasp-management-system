// Actual standalone HTML: embedded initial/final, intermediate and Bader CIF downloads.
const {build}=require('esbuild');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright-core');
const fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
(async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'vasp-report-cif-'));let browser;
 try{
  const cif=name=>`data_${name}\n# 中文结构原文\n_cell_length_a 10\n_cell_length_b 10\n_cell_length_c 10\n_cell_angle_alpha 90\n_cell_angle_beta 90\n_cell_angle_gamma 90\nloop_\n_atom_site_label\n_atom_site_type_symbol\n_atom_site_fract_x\n_atom_site_fract_y\n_atom_site_fract_z\nC1 C 0.4 0.4 0.4\nO1 O 0.52 0.4 0.4\n`;
  const poscar=cif('initial'),contcar=cif('optimized'),a=cif('intermediate_A'),b=cif('intermediate_B'),bader=cif('charge_structure');
  const doc={metadata:{report_id:'cif_report',project_name:'CIF模型',generated_at:'2026-11-10'},science:{
   opt:[{task_id:'opt',task_name:'模型一',structure:{poscar_cif:poscar,contcar_cif:contcar}}],
   free_energy:[{group_id:'path',structures:[{structure_label:'A',cif:a},{structure_label:'B',cif:b}]}],
   neb:[{task_id:'migration',endpoint_path:{group_id:'neb_endpoints_migration',structures:[
    {structure_label:'IS',display_label:'初态-IS',cif:a},{structure_label:'FS',display_label:'末态-FS',cif:b}]}}],
   ele:{tasks:[{task_id:'bader',task_name:'电荷模型',bader_summary:{cif:bader,atoms:[{index:1,element:'C',net_charge:.2}]}}]}},
   markdown_sections:[{key:'science',title:'结构',markdown:'### 优化结构\n\n@[structure-3d:opt]\n\n### 中间体\n\n@[free-energy-3d:path]\n\n### NEB\n\n#### M1_H_mig_neb\n\n@[free-energy-3d:neb_endpoints_migration]\n\n| 初末态 | 状态 |\n|---|---|\n| [初态-IS](#fe-3d:neb_endpoints_migration:0:is) | 已收敛 |\n| [末态-FS](#fe-3d:neb_endpoints_migration:1:fs) | 未收敛 |\n\n### 电荷结构\n\n@[bader-table:bader]\n'}]};
  await fs.writeFile(path.join(dir,'input.json'),JSON.stringify(doc));
  await build({entryPoints:['src/interactive/reportRuntime.ts'],bundle:true,minify:true,format:'iife',outfile:path.join(dir,'runtime.js'),define:{'process.env.NODE_ENV':'"production"'}});
  execFileSync('.venv/bin/python',['-c',`import json,sys
from pathlib import Path
sys.path.insert(0,'backend')
from report_export import render_html
from report_interactive import interactive_payload
p=Path(sys.argv[1]);doc=json.loads((p/'input.json').read_text())
text=render_html(doc,doc['markdown_sections'],interactive_data=interactive_payload(doc),interactive_js=(p/'runtime.js').read_text(),mol_js=Path('public/3dmol/3Dmol-min.js').read_text())
(p/'report.html').write_text(text,encoding='utf-8')`,dir],{env:{...process.env,VASP_WEB_DATA_DIR:path.join(dir,'data')}});
  browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox','--enable-unsafe-swiftshader']});
  const page=await browser.newPage();const network=[],errors=[];
  page.on('request',r=>{if(/^https?:/.test(r.url()))network.push(r.url());});page.on('pageerror',e=>errors.push(e.message));
  await page.goto('file://'+path.join(dir,'report.html'));
  const check=async(host,expected,suffix)=>{
   const [download]=await Promise.all([page.waitForEvent('download'),host.getByRole('button',{name:'导出 CIF',exact:true}).click()]);
   assert.equal(await fs.readFile(await download.path(),'utf8'),expected,'download preserves embedded CIF bytes without BOM');
   assert.ok(download.suggestedFilename().endsWith(suffix),download.suggestedFilename());
  };
  const opt=page.locator('[data-report-widget="structure-3d"][data-task-id="opt"]');
  await check(opt,contcar,'_CONTCAR.cif');
  await opt.getByRole('button',{name:'初始（POSCAR）',exact:true}).click();await check(opt,poscar,'_POSCAR.cif');
  await opt.getByRole('button',{name:'优化后（CONTCAR）',exact:true}).click();await check(opt,contcar,'_CONTCAR.cif');
  const intermediate=page.locator('[data-report-widget="free-energy-3d"][data-task-id="path"]');
  await check(intermediate,a,'_structure_A_structure.cif');
  await intermediate.getByRole('button',{name:'结构 B',exact:true}).click();await check(intermediate,b,'_structure_B_structure.cif');
  const endpoints=page.locator('[data-report-widget="free-energy-3d"][data-task-id="neb_endpoints_migration"]');
  assert.equal(await endpoints.count(),1,'one shared endpoint structure window');
  await check(endpoints,a,'_structure_IS_structure.cif');
  await endpoints.getByRole('button',{name:'末态-FS',exact:true}).click();await check(endpoints,b,'_structure_FS_structure.cif');
  await page.locator('[data-fe-3d="neb_endpoints_migration"][data-fe-index="0"]').click();
  await check(endpoints,a,'_structure_IS_structure.cif');
  assert.equal(await endpoints.getByRole('button',{name:'初态-IS',exact:true}).count(),1);
  assert.equal(await page.locator('h4,h5').filter({hasText:'M1_H_mig_IS'}).count(),0);
  await page.setViewportSize({width:390,height:844});
  assert.ok(await endpoints.evaluate(el=>el.scrollWidth<=el.clientWidth+1));
  await page.setViewportSize({width:1280,height:900});
  await check(page.locator('[data-source="bader"]'),bader,'_structure.cif');
  await build({stdin:{contents:`import React from 'react';import{createRoot}from'react-dom/client';import ReportFreeEnergy3D from './src/components/reports/ReportFreeEnergy3D';import './src/styles/global.css';createRoot(document.getElementById('root')).render(<ReportFreeEnergy3D groupName="M1_H_mig_neb" structures={${JSON.stringify(doc.science.neb[0].endpoint_path.structures)}}/>);`,loader:'tsx',resolveDir:process.cwd()},bundle:true,format:'iife',jsx:'automatic',outfile:path.join(dir,'endpoint-component.js'),define:{'process.env.NODE_ENV':'"production"'}});
  await fs.writeFile(path.join(dir,'endpoint-component.html'),`<meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="endpoint-component.css"><script src="file://${path.resolve('public/3dmol/3Dmol-min.js')}"></script><div id="root"></div><script src="endpoint-component.js"></script>`);
  await page.goto('file://'+path.join(dir,'endpoint-component.html'));
  const reactEndpoints=page.locator('.report-3d');
  await reactEndpoints.locator('canvas').first().waitFor();
  assert.equal(await reactEndpoints.getByRole('button',{name:'初态-IS',exact:true}).count(),1);
  await check(reactEndpoints,a,'_structure_IS.cif');
  await reactEndpoints.getByRole('button',{name:'末态-FS',exact:true}).click();
  await check(reactEndpoints,b,'_structure_FS.cif');
  assert.deepEqual(network,[]);assert.deepEqual(errors,[]);
  console.log('PASS: standalone HTML and actual React endpoint selector, grouped IS/FS labels, table switching, mobile width and exact embedded CIF downloads; no network requests.');
 }finally{await browser?.close();await fs.rm(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
