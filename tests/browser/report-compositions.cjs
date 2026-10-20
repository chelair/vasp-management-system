// Real editor + isolated local Python API/parsers/auth/export. No production service/model/HPC.
// PLAYWRIGHT_MODULE=/tmp/vasp-report-debug/node_modules/playwright-core node tests/browser/report-compositions.cjs
const {build} = require('esbuild');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const {spawn} = require('node:child_process');
const http = require('node:http');
const path = require('node:path');
const fs = require('node:fs/promises');
const os = require('node:os');
const assert = require('node:assert/strict');

(async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'vasp-r2-browser-assets-'));
  let python, browser, server;
  try {
    const runtime = path.join(dir, 'runtime.js');
    await build({entryPoints: ['src/interactive/reportRuntime.ts'], bundle: true, minify: true, format: 'iife', outfile: runtime});
    const bundle = await build({stdin: {contents: `
      import React from 'react';import {createRoot} from 'react-dom/client';import {App} from 'antd';
      import ReportCompositionEditor from './src/components/reports/ReportCompositionEditor';
      import {mapLegacyHiddenBlocks} from './src/utils/reportHidden';
      window.mapLegacyHiddenBlocks = mapLegacyHiddenBlocks;
      createRoot(document.getElementById('root')).render(<App><ReportCompositionEditor projectRef="p_r2" projectName="R2P" onClose={()=>{}}/></App>);
    `, loader: 'tsx', resolveDir: path.resolve('.')}, bundle: true, write: false, outfile: path.join(dir, 'app.js'),
      jsx: 'automatic', define: {'process.env.NODE_ENV': '"development"'}});
    python = spawn('.venv/bin/python', ['tests/r2_browser_server.py', runtime], {stdio: ['ignore', 'pipe', 'pipe']});
    let stderr = ''; python.stderr.on('data', data => {stderr += data;});
    const fixture = await new Promise((resolve, reject) => {
      let output = ''; const timer = setTimeout(() => reject(new Error('fixture startup timeout '+stderr)), 15000);
      python.on('exit', code => {clearTimeout(timer); reject(new Error('fixture exited '+code+' '+stderr));});
      python.stdout.on('data', data => {output += data; if (output.includes('\n')) {clearTimeout(timer); resolve(JSON.parse(output.split('\n')[0]));}});
    });
    const apiBase = `http://127.0.0.1:${fixture.port}`;
    const api = async (suffix, method = 'GET', body) => {
      const res = await fetch(apiBase+'/api/reports/blocks/p_r2/'+suffix, {method, headers: {'Authorization': 'Bearer '+fixture.token, 'Content-Type': 'application/json'}, body: body && JSON.stringify(body)});
      const value = await res.json(); assert.equal(res.status, 200, JSON.stringify(value)); return value.data;
    };
    server = http.createServer(async (req, res) => {
      if (req.url.startsWith('/api/')) {
        const proxy = http.request(apiBase+req.url, {method: req.method, headers: req.headers}, upstream => {
          res.writeHead(upstream.statusCode, upstream.headers); upstream.pipe(res);
        }); proxy.on('error', err => {res.writeHead(502); res.end(err.message);}); req.pipe(proxy); return;
      }
      const name = req.url === '/app.js' ? 'app.js' : req.url === '/app.css' ? 'app.css' : null;
      if (name) {
        res.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : 'text/css');
        return res.end(bundle.outputFiles.find(f => f.path.endsWith(name)).text);
      }
      res.setHeader('Content-Type', 'text/html');
      res.end(`<link rel="stylesheet" href="/app.css"><div id="root"></div><script>localStorage.setItem('vasp.auth.token',${JSON.stringify(fixture.token)})</script><script src="/app.js"></script>`);
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    browser = await chromium.launch({executablePath: '/opt/microsoft/msedge/msedge', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage']});
    const page = await browser.newPage({viewport: {width: 1600, height: 1050}, acceptDownloads: true});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.getByRole('combobox', {name: '选择模型'}).waitFor();
    async function select(label, search, match) {
      const input = page.getByRole('combobox', {name: label}).first();
      if (await input.getAttribute('readonly') !== null) await input.click(); else await input.fill(search);
      await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option-content').filter({hasText: match}).first().click();
    }
    await select('选择模型', 'Model01', 'Model01');
    await select('选择模型', 'Model02', 'Model02');
    await page.getByRole('combobox', {name: '选择模型'}).press('Escape');
    for (const model of ['Model01', 'Model02']) {
      await select('选择报告元素', model+' · 最终', model+' · 最终能量');
      await page.getByRole('button', {name: '添加元素', exact: true}).click();
    }
    await page.getByRole('button', {name: '添加参数对照', exact: true}).click();
    await select('选择报告元素', 'Model01 · 收敛', 'Model01 · 收敛曲线');
    await page.getByRole('button', {name: '添加元素', exact: true}).click();
    await page.getByRole('button', {name: '添加文字', exact: true}).click();
    const manual = '事实：比较两个模型。<script>window.R2_XSS=1</script> ![leak](https://example.invalid/leak)';
    await page.getByRole('textbox', {name: '分析文本', exact: true}).fill(manual);
    await page.getByRole('textbox', {name: '新分组标题'}).fill('模型对照');
    await page.getByRole('button', {name: '添加分组', exact: true}).click();
    await select('元素分组', '模型对照', '模型对照');
    await page.getByRole('button', {name: '更新预览', exact: true}).click();
    const preview = page.frameLocator('iframe[title="专题报告预览"]');
    await preview.getByRole('cell', {name: 'KPOINTS', exact: true}).waitFor();
    await preview.getByRole('cell', {name: 'ENCUT', exact: true}).waitFor();
    assert.equal(await preview.locator('script').count(), 0); // no executable text injection
    await page.getByRole('button', {name: '保存专题报告', exact: true}).click();
    await page.getByText('报告已保存', {exact: true}).waitFor();
    let list = await api('compositions'); const id = list.items[0].composition_id;
    const first = await api('compositions/'+id);
    assert.equal(first.blocks.length, 5); assert.equal(Object.keys(first.evidence).length, 4);
    const catalog = await api('candidates');
    const legacy = await page.evaluate(({ids,candidates}) => window.mapLegacyHiddenBlocks(ids,candidates,['task:science:Model01','figure:science:1','task:science:Model04']), {ids:first.blocks.map(b=>b.block_id),candidates:catalog.candidates});
    assert.deepEqual(legacy.sort(), first.blocks.filter(b=>b.task_id==='task_opt_01').map(b=>b.block_id).sort());
    assert.ok(await page.locator(`.ant-card[data-block-id="${first.blocks[0].block_id}"]`).count(),
      JSON.stringify({expected:first.blocks.map(b=>b.block_id),actual:await page.locator('.rb-editor-controls [data-block-id]').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('data-block-id')))}));
    const energy = page.locator(`.ant-card[data-block-id="${first.blocks[0].block_id}"]`);
    await energy.getByRole('button', {name: /下\s*移/}).click();
    await energy.getByRole('button', {name: /隐\s*藏/}).click();
    await energy.getByRole('button', {name: '删除元素', exact: true}).click();
    await energy.getByRole('button', {name: '恢复元素', exact: true}).click();
    await page.getByRole('textbox', {name: '专题报告标题'}).fill('两模型专题对照');
    await page.getByRole('button', {name: '保存专题报告', exact: true}).click();
    await page.getByRole('button', {name: '导出 HTML', exact: true}).waitFor({state: 'visible'});
    await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(b => b.textContent === '导出 HTML')?.disabled);
    const second = await api('compositions/'+id);
    assert.equal(second.revision, 2); assert.deepEqual(second.evidence, first.evidence);
    assert.deepEqual(second.hidden_block_ids, [first.blocks[0].block_id]);
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', {name: '导出 HTML', exact: true}).click();
    const download = await downloadPromise; const savedHtml = await fs.readFile(await download.path(), 'utf8');
    assert.ok(savedHtml.includes('KPOINTS')); assert.ok(!savedHtml.includes('https://example.invalid/leak'));
    const printable = await browser.newPage(); await printable.setContent(savedHtml);
    assert.equal(await printable.evaluate(() => window.R2_XSS), undefined);
    const pdf = await printable.pdf({format: 'A4'}); assert.equal(pdf.subarray(0,5).toString(), '%PDF-'); assert.ok(pdf.length > 1000);
    await printable.close();
    await fetch(apiBase+'/__test/mutate', {method: 'POST'});
    await page.getByRole('button', {name: '检查数据更新', exact: true}).click();
    await page.getByText('计算数据可能已更新。', {exact: false}).waitFor();
    await page.getByRole('textbox', {name: '专题报告标题'}).fill('保留原数据');
    await page.getByRole('button', {name: '保存专题报告', exact: true}).click();
    await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(b => b.textContent === '导出 HTML')?.disabled);
    const retained = await api('compositions/'+id); assert.deepEqual(retained.evidence, first.evidence);
    await page.getByRole('button', {name: '刷新计算数据', exact: true}).click();
    await page.getByRole('button', {name: '刷新并保存', exact: true}).click();
    await page.getByText('计算数据已刷新并保存', {exact: true}).waitFor();
    const refreshed = await api('compositions/'+id);
    assert.notDeepEqual(refreshed.evidence, first.evidence);
    assert.equal(refreshed.blocks.find(b => b.type === 'text.analysis').text, manual);
    // A concurrent editor cannot overwrite another revision.
    await api('compositions/'+id, 'PUT', {...refreshed, expected_revision: refreshed.revision, title: '其他编辑者'});
    await page.getByRole('textbox', {name: '专题报告标题'}).fill('本地尚未保存');
    await page.getByRole('button', {name: '保存专题报告', exact: true}).click();
    await page.getByText('组合已被修改', {exact: false}).waitFor();
    assert.equal((await api('compositions/'+id)).title, '其他编辑者');
    const science = await api('compositions', 'POST', {title: '科学面板', blocks: [...['ele.pdos','ele.work_function','ele.bader','ele.charge_diff'].map(type => ({type, task_id: 't_ele'})), {type:'task.structure', task_id:'task_opt_01'}]});
    const response = await fetch(apiBase+`/api/reports/blocks/p_r2/compositions/${science.composition_id}/export.html`, {headers: {Authorization: 'Bearer '+fixture.token}});
    const scientific = await browser.newPage(); scientific.on('pageerror', e => errors.push(e.message));
    const outgoing = []; scientific.on('request', req => {if (req.url().startsWith('http')) outgoing.push(req.url());});
    await scientific.setContent(await response.text());
    await scientific.locator('[data-report-widget="pdos-chart"][data-mounted="1"]').waitFor();
    await scientific.locator('[data-report-widget="work-function-chart"][data-mounted="1"]').waitFor();
    assert.ok(await scientific.locator('[data-report-widget="structure-3d"]').count());
    assert.ok(await scientific.locator('[data-report-widget="structure-3d"]').evaluate(node=>node.dataset.mounted==='1' || node.childElementCount===0), 'WebGL failure retains safe fallback');
    assert.deepEqual(outgoing, []); assert.deepEqual(errors, []);
    await scientific.close();
    console.log('PASS R2 real API/editor: two models, energy + selected parameter comparison + curve + text, group/reorder/hide/delete/restore, frozen display edits, explicit refresh, revision conflict, XSS, HTML download/PDF, offline PDOS/work-function widgets');
  } finally {
    if (browser) await browser.close();
    if (server) await new Promise(resolve => server.close(resolve));
    if (python) python.kill('SIGTERM');
    await fs.rm(dir, {recursive: true, force: true});
  }
})().catch(e => {console.error(e); process.exitCode = 1;});
