// Frozen fixture and actual report runtime, including offline HTML and real WebGL.
const {build}=require('esbuild');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright-core');
const fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
(async()=>{
 const temp=await fs.mkdtemp(path.join(os.tmpdir(),'vasp-neb-browser-'));
 let browser;
 try{
  let prefix=process.env.NEB_PREVIEW_PREFIX;
  if(!prefix){
   const runtime=path.join(temp,'runtime.js');prefix=path.join(temp,'preview');
   await build({entryPoints:['src/interactive/reportRuntime.ts'],bundle:true,minify:true,jsx:'automatic',format:'iife',outfile:runtime,define:{'process.env.NODE_ENV':'"production"'}});
   execFileSync('.venv/bin/python',['-c',`import sys
sys.path[:0]=['tests','backend']
from test_report_neb import ReportNebTests
t=ReportNebTests();t.setUp()
try:t.test_reaction_report_answers_reuse_frozen_neb()
finally:t.doCleanups()`],{env:{...process.env,NEB_PREVIEW_PREFIX:prefix,NEB_RUNTIME:runtime}});
  }
  browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(12000);
  const errors=[],requests=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(!r.url().startsWith('file:')&&!r.url().startsWith('data:'))requests.push(r.url());});
  for(const kind of ['composition','reaction']){
   await page.goto('file://'+prefix+'-'+kind+'.html');
   const neb=page.locator('.report-neb');await neb.locator('.nebmd__thumb').first().waitFor();
   assert.equal(await neb.locator('.nebmd__thumb').count(),3);
   await neb.locator('.s3d-editor__canvas canvas').waitFor();
   assert.equal(await neb.getByText('查看原子受力',{exact:false}).count(),0);
   assert.ok(await neb.locator('.nebmd__table tr').nth(1).innerText().then(t=>t.includes('00')&&t.includes('-10.0000')));
   await neb.locator('.nebmd__thumb').nth(1).click();
   await neb.locator('.nebmd__no-structure').waitFor();assert.ok((await neb.locator('.nebmd__no-structure').innerText()).includes('01'));
   assert.equal(await neb.locator('.nebmd__table tr.is-selected').count(),1);
   await neb.getByRole('button',{name:'下一个映像',exact:true}).click();await neb.locator('.s3d-editor__canvas canvas').waitFor();
   assert.ok((await neb.locator('.nebmd__thumb.is-selected').innerText()).includes('02'));
   await neb.locator('.nebmd__table tbody tr').first().click();
   assert.ok((await neb.locator('.nebmd__thumb.is-selected').innerText()).includes('00'));
   const curve=neb.locator('.nebmd-curve__canvas');const box=await curve.boundingBox();
   await curve.click({position:{x:box.width/2,y:box.height/2}});
   await neb.locator('.nebmd__no-structure').waitFor();
   await neb.locator('.nebmd__thumb').last().click();await neb.locator('.s3d-editor__canvas canvas').waitFor();
   await neb.getByRole('button',{name:'a 视角',exact:true}).count().then(async count=>{if(count)await neb.getByRole('button',{name:'a 视角',exact:true}).click();});
   await page.evaluate(()=>window.dispatchEvent(new Event('beforeprint')));
   await page.emulateMedia({media:'print'});
   assert.ok(await neb.locator('.report-neb__print').isVisible(),'selected structure is visible for PDF');
   assert.ok((await neb.locator('.report-neb__print').getAttribute('src')).startsWith('data:image/png;base64,'));
   assert.ok(await neb.locator('.report-neb__print').evaluate(async img=>{
    await img.decode();const c=document.createElement('canvas');c.width=img.naturalWidth;c.height=img.naturalHeight;
    const ctx=c.getContext('2d');ctx.drawImage(img,0,0);const pixels=ctx.getImageData(0,0,c.width,c.height).data;
    const colors=new Set();for(let i=0;i<pixels.length;i+=100)colors.add(pixels.slice(i,i+4).join(','));return colors.size>5;
   }),'PDF contains the rendered atoms rather than a blank canvas');
   assert.equal(await neb.locator('.nebmd__stage').isVisible(),false);
   await page.pdf({path:path.join(temp,kind+'.pdf'),format:'A4'});
   await page.emulateMedia({media:'screen'});await page.setViewportSize({width:390,height:844});
   assert.ok(await neb.evaluate(el=>el.scrollWidth<=el.clientWidth+1),'mobile report stays within its width');
   await page.setViewportSize({width:1440,height:1000});
  }
  assert.deepEqual(errors,[]);assert.deepEqual(requests,[],'offline report must not request live APIs or network resources');
  console.log('PASS: NEB report curve/table/thumbnails/navigation, missing structure, offline HTML, mobile layout and PDF snapshot.');
 }finally{if(browser)await browser.close();await fs.rm(temp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1);});
