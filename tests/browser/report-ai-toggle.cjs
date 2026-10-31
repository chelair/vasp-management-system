// 智能报告页「AI 批注处理」开关验收：真实 React 渲染 + 假的 fetch 记录请求，不连后端。
const { build } = require('esbuild');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/tmp/vasp-report-debug/node_modules/playwright-core');
const path = require('node:path'), fs = require('node:fs'), http = require('node:http'), assert = require('node:assert/strict');

(async () => {
  const bundle = await build({
    stdin: {
      contents: `import React from 'react';
import {createRoot} from 'react-dom/client';
import {App} from 'antd';
import {MemoryRouter} from 'react-router-dom';
import Report from './src/pages/Report';
createRoot(document.getElementById('root')).render(<App><MemoryRouter initialEntries={['/report']}><Report/></MemoryRouter></App>);`,
      loader: 'tsx',
      resolveDir: path.resolve('.'),
    },
    bundle: true, write: false, outfile: 'app.js', jsx: 'automatic',
    define: { 'process.env.NODE_ENV': '"development"' },
  });
  const js = bundle.outputFiles.find((f) => f.path.endsWith('.js')).text;

  const stub = `window.__calls = [];
const baseProject = {id:'PMS', name:'PMS', owner:'zouyuxi', closed:false, description:'', deadline:'2026-10-23',
  ai_report_notes_enabled:false, calc_description:'', expected_results:'', tasks:[], task_count:0,
  workload:'small', urgency:'urgent', quadrant:'urgent_small'};
window.fetch = async (url, init) => {
  const path = String(url).replace(/^https?:\\/\\/[^/]+/, '');
  const method = (init && init.method) || 'GET';
  const body = init && init.body ? String(init.body) : '';
  window.__calls.push({path, method, body});
  let data = {};
  if (path.startsWith('/api/projects/PMS')) {
    const patch = body ? JSON.parse(body) : {};
    data = {project: {...baseProject, ...patch}};
  } else if (path.startsWith('/api/projects')) {
    data = {projects: [baseProject]};
  } else if (path.startsWith('/api/reports/project/list')) {
    data = {reports: []};
  } else if (path.startsWith('/api/reports')) {
    data = {reports: []};
  } else {
    data = {};
  }
  return {ok: true, status: 200, json: async () => ({success: true, message: 'ok', data})};
};`;

  const server = http.createServer((req, res) => {
    if (req.url === '/app.js') { res.setHeader('Content-Type', 'text/javascript'); return res.end(js); }
    res.setHeader('Content-Type', 'text/html');
    res.end(`<div id="root"></div><script>${stub}</script><script src="/app.js"></script>`);
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const browser = await chromium.launch({ executablePath: '/opt/microsoft/msedge/msedge', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  try {
    const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
    page.setDefaultTimeout(20000);
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/`);

    const toggle = page.getByRole('switch', { name: 'AI 批注处理' });
    await toggle.waitFor();
    assert.equal(await toggle.getAttribute('aria-checked'), 'false', '初始应为关闭');
    assert.ok(await page.getByText('AI 批注处理').isVisible(), '应显示在智能报告页');

    await toggle.click();
    await page.getByText('已开启 AI 批注处理').waitFor();
    assert.equal(await toggle.getAttribute('aria-checked'), 'true');
    const puts = (await page.evaluate(() => window.__calls)).filter((c) => c.method === 'PUT');
    assert.equal(puts.length, 1, JSON.stringify(puts));
    assert.equal(JSON.parse(puts[0].body).ai_report_notes_enabled, true);

    await toggle.click();
    await page.getByText('已关闭 AI 批注处理（已有内容保留）').waitFor();
    assert.equal(await toggle.getAttribute('aria-checked'), 'false');
    const puts2 = (await page.evaluate(() => window.__calls)).filter((c) => c.method === 'PUT');
    assert.equal(puts2.length, 2);
    assert.equal(JSON.parse(puts2[1].body).ai_report_notes_enabled, false);

    assert.deepEqual(errors, []);
    // 旧位置必须已移除（项目编辑弹窗不再有该开关）
    const dialog = fs.readFileSync('src/components/projects/ProjectEditDialog.tsx', 'utf8');
    assert.ok(!dialog.includes('ai_report_notes_enabled'), '项目编辑弹窗里不应再保留该开关');
    console.log(JSON.stringify({ ok: true, puts: puts2.map((c) => JSON.parse(c.body)) }));
  } finally {
    await browser.close().catch(() => {});
    server.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });
