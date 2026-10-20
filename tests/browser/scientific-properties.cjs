// Real React + ephemeral authenticated Python server; no production/model/HPC.
const {build} = require('esbuild');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || '/tmp/vasp-report-debug/node_modules/playwright-core');
const {spawn} = require('node:child_process');
const http = require('node:http');
const path = require('node:path');
const fs = require('node:fs/promises');
const os = require('node:os');
const assert = require('node:assert/strict');
(async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(),'vasp-r3-ui-'));
  let python,browser,server;
  try {
    const bundle = await build({stdin:{contents:`
      import React from 'react';import {createRoot} from 'react-dom/client';import {App} from 'antd';
      import ScientificPropertiesPanel from './src/components/reports/ScientificPropertiesPanel';
      createRoot(document.getElementById('root')).render(<App><ScientificPropertiesPanel projectRef="r3p" projects={[{id:'r3p',name:'R3P'}]} onClose={()=>{}}/></App>);
    `,loader:'tsx',resolveDir:path.resolve('.')},bundle:true,write:false,outfile:path.join(dir,'app.js'),jsx:'automatic',define:{'process.env.NODE_ENV':'"development"'}});
    python = spawn('.venv/bin/python',['tests/r3_browser_server.py'],{stdio:['ignore','pipe','pipe']});
    let stderr='';python.stderr.on('data',v=>stderr+=v);
    const fixture = await new Promise((resolve,reject) => {
      let output='';const timer=setTimeout(()=>reject(new Error('startup '+stderr)),15000);
      python.on('exit',code=>{clearTimeout(timer);reject(new Error('fixture '+code+' '+stderr));});
      python.stdout.on('data',data=>{output+=data;if(output.includes('\n')){clearTimeout(timer);resolve(JSON.parse(output.split('\n')[0]));}});
    });
    const base = `http://127.0.0.1:${fixture.port}`;
    server = http.createServer((req,res) => {
      if(req.url.startsWith('/api/')){
        const proxy=http.request(base+req.url,{method:req.method,headers:req.headers},upstream=>{res.writeHead(upstream.statusCode,upstream.headers);upstream.pipe(res);});
        proxy.on('error',e=>{res.writeHead(502);res.end(e.message);});req.pipe(proxy);return;
      }
      if(req.url === '/app.js'){res.setHeader('Content-Type','text/javascript');return res.end(bundle.outputFiles.find(f=>f.path.endsWith('app.js')).text);}
      res.setHeader('Content-Type','text/html');res.end(`<div id="root"></div><script>localStorage.setItem('vasp.auth.token',${JSON.stringify(fixture.token)})</script><script src="/app.js"></script>`);
    });
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    browser=await chromium.launch({executablePath:'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
    const page=await browser.newPage({viewport:{width:1600,height:1200},acceptDownloads:true});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(15000);
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.getByRole('combobox',{name:'LMR-pristine',exact:true}).waitFor();
    async function choose(label,tid){
      const input=page.getByRole('combobox',{name:label,exact:true});
      await input.fill(tid);
      await page.locator('.ant-select-item-option').filter({hasText:tid}).last().click();
    }
    await choose('LMR-pristine','a_p');await choose('LMR-defect','a_d');
    await choose('LIC@LMR-pristine','b_p');await choose('LIC@LMR-defect','b_d');
    const evaluate = async () => {
      const button=page.getByRole('button',{name:'验证数据并计算',exact:true});
      assert.equal(await button.isEnabled(),true,JSON.stringify({inputs:await page.locator('input').evaluateAll(nodes=>nodes.map(n=>({name:n.getAttribute('aria-label'),value:n.value}))),errors}));
      const [response] = await Promise.all([page.waitForResponse(r=>r.url().endsWith('/properties/evaluate')),button.click()]);assert.equal(response.status(),200);return (await response.json()).data;
    };
    const missing=await evaluate();assert.equal(missing.results.length,0);assert.equal(missing.status,'BLOCKED');
    await page.getByRole('checkbox',{name:/确认各体系采用相同氧化学势/}).check();
    const delta=await evaluate();assert.equal(delta.status,'PARTIAL');assert.deepEqual(delta.results.map(r=>r.value),[1]);
    await page.getByRole('cell',{name:'1 eV',exact:true}).waitFor();
    await page.getByRole('checkbox',{name:/明确设置氧化学势/}).check();
    await page.getByRole('spinbutton',{name:'氧化学势',exact:true}).fill('-5');
    await page.getByRole('textbox',{name:'氧参考来源',exact:true}).fill('synthetic explicit reference');
    await page.getByRole('textbox',{name:'氧参考条件',exact:true}).fill('synthetic reference conditions');
    const complete=await evaluate();assert.equal(complete.status,'AVAILABLE');assert.deepEqual(complete.results.map(r=>r.value),[3,4,1]);
    const downloaded=page.waitForEvent('download');await page.getByRole('button',{name:'下载数据需求与结果',exact:true}).click();
    const file=await downloaded;const saved=JSON.parse(await fs.readFile(await file.path(),'utf8'));
    assert.equal(saved.evidence_sha256,complete.evidence_sha256);assert.equal(saved.report_id,complete.report_id);
    assert.ok(saved.inputs[0].frozen_observation.property_evidence.files.POSCAR.text);
    await page.getByRole('spinbutton',{name:'氧化学势',exact:true}).fill('-4');
    await page.getByText('输入已修改，请重新验证；下方保留上次快照结果。',{exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'下载数据需求与结果',exact:true}).isDisabled(),true);
    assert.deepEqual(errors,[]);
    console.log('PASS R3 browser: exact task bindings, missing reference, shared-reference delta, absolute energies, frozen JSON export, dirty-input guard; zero page errors');
  } finally {
    await browser?.close();if(server) await new Promise(resolve=>server.close(resolve));python?.kill();await fs.rm(dir,{recursive:true,force:true});
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
