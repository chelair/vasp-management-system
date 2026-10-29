const { build } = require('esbuild');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const fs = require('node:fs'), http = require('node:http'), path = require('node:path'), assert = require('node:assert/strict');
const cif = `data_test
_cell_length_a 10
_cell_length_b 10
_cell_length_c 10
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
C1 C 0.4 0.4 0.4
O1 O 0.52 0.4 0.4
`;
(async () => {
  const output = await build({ stdin: { contents: `
    import './src/styles/global.css';import {useState,StrictMode} from 'react';import {createRoot} from 'react-dom/client';import {App,Button} from 'antd';
    import Structure3DFrame from './src/components/jobs/Structure3DFrame';
    import NebImageMasterDetail from './src/components/inspection/NebImageMasterDetail';
    const cif=${JSON.stringify(cif)};
    function Fixture(){const[open,setOpen]=useState(false);return <App><Button onClick={()=>setOpen(v=>!v)}>切换结构</Button>{open&&<>
      <Structure3DFrame cif={cif} selected={[]} onClickAtom={()=>{}}/>
      <NebImageMasterDetail taskId="fixture" images={[{label:'00',cif,role:'initial'},{label:'01',cif,role:'final'}]}/>
    </>}</App>;}createRoot(document.getElementById('root')).render(<StrictMode><Fixture/></StrictMode>);
  `, resolveDir: path.resolve('.'), loader: 'tsx' }, bundle: true, write: false, outfile: 'app.js', jsx: 'automatic', define: { 'process.env.NODE_ENV': '"production"' } });
  const js = output.outputFiles.find(file => file.path.endsWith('.js')).text;
  const css = output.outputFiles.find(file => file.path.endsWith('.css'))?.text || '';
  let scriptRequests = 0;
  const server = http.createServer((req, res) => {
    if (req.url === '/3dmol/3Dmol-min.js') {
      scriptRequests++;
      setTimeout(() => {
        if (scriptRequests === 1) { res.writeHead(503); res.end(); }
        else { res.setHeader('Content-Type', 'text/javascript'); res.end(fs.readFileSync('public/3dmol/3Dmol-min.js')); }
      }, 200);
    } else {
      assert.ok(!req.url.startsWith('/api/'), 'structure display must not request current scientific data');
      res.setHeader('Content-Type', req.url === '/app.js' ? 'text/javascript' : req.url === '/app.css' ? 'text/css' : 'text/html; charset=utf-8');
      res.end(req.url === '/app.js' ? js : req.url === '/app.css' ? css : '<meta charset="utf-8"><link rel="stylesheet" href="/app.css"><div id="root"></div><script src="/app.js"></script>');
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ executablePath: process.env.BROWSER_PATH || '/opt/microsoft/msedge/msedge', headless: true, args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  try {
    const page = await browser.newPage(); page.setDefaultTimeout(12000);
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    assert.equal(scriptRequests, 0);
    await page.getByRole('button', { name: '切换结构', exact: true }).click();
    await page.getByText('3D 视图加载失败，请重新打开', { exact: true }).first().waitFor();
    assert.equal(scriptRequests, 1, 'all mounted viewers share one failed load');
    await page.getByRole('button', { name: '切换结构', exact: true }).click();
    await page.getByRole('button', { name: '切换结构', exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll('.s3d-editor__canvas canvas').length === 2);
    assert.equal(scriptRequests, 2, 'reopening retries once and shares the loaded engine');
    await page.locator('.nebmd__thumb').last().click();
    await page.waitForFunction(() => document.querySelectorAll('.s3d-editor__canvas canvas').length === 2);
    await page.getByRole('button', { name: '切换结构', exact: true }).click();
    await page.getByRole('button', { name: '切换结构', exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll('.s3d-editor__canvas canvas').length === 2);
    assert.equal(scriptRequests, 2, 'subsequent viewers reuse the engine');
    assert.deepEqual(errors, []);
    console.log('PASS no initial 3D request, shared loading, failed-load retry, real structure and NEB WebGL, image switching and engine reuse');
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; });
