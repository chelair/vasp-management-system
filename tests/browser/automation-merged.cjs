// 合并页验收：自动化页两个标签（项目托管 / 自动化规则），假 fetch，不连后端。
const { build } = require('esbuild');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/tmp/vasp-report-debug/node_modules/playwright-core');
const path = require('node:path'), http = require('node:http'), assert = require('node:assert/strict');

const PLAN = {
  id: 'plan_demo1234567890',
  project: 'PMS', server: 'server1', owner: 'tester', status: 'active',
  goal: { text: '周五先交 model1 的阶段报告，其余接着跑', summary: '周五交 model1 阶段报告' },
  stages: [{ stage_id: 'st_a', title: '阶段报告', task_ids: ['t1'], due: '2026-10-23', priority: 90, timezone: 'Asia/Shanghai' }],
  task_overrides: {}, resource_rules: {}, revision: 1, created_at: '2026-10-20T23:00:00', updated_at: '2026-10-20T23:00:00',
};
const CANDIDATE = {
  task_id: 't1', task_name: 'model1', task_type: 'opt', status: 'pending', intent: 'first_submit',
  action: 'task.submit', priority: 90, priority_source: 'stage', locked: false,
  stage_id: 'st_a', stage_title: '阶段报告', due: '2026-10-23', due_epoch: 1792684800, order: 0,
  reason: '输入已就绪，可首发提交',
};

(async () => {
  const bundle = await build({
    stdin: {
      contents: `import React from 'react';
import {createRoot} from 'react-dom/client';
import {App} from 'antd';
import {MemoryRouter} from 'react-router-dom';
import Automation from './src/pages/Automation';
createRoot(document.getElementById('root')).render(<App><MemoryRouter initialEntries={['/automation']}><Automation/></MemoryRouter></App>);`,
      loader: 'tsx',
      resolveDir: path.resolve('.'),
    },
    bundle: true, write: false, outfile: 'app.js', jsx: 'automatic',
    define: { 'process.env.NODE_ENV': '"development"' },
  });
  const js = bundle.outputFiles.find((f) => f.path.endsWith('.js')).text;

  const data = {
    managed: { plans: [{ plan: PLAN, summary: { counts: { ready: 1, continuation: 1, in_flight: 0 }, next: CANDIDATE, waiting: [], needs_user: [], candidates: [CANDIDATE] } }], execution_enabled: false },
    '/api/automation/status': { settings: { enabled: true, dry_run: false, schedules_enabled: false }, rules: [], schedules: [], counts: { rules: 0, enabled_rules: 0, queue: 0 }, last_results: {} },
    '/api/automation/decisions': { decisions: [] },
    '/api/automation/runs': { runs: [] },
    '/api/actions': { actions: [] },
    '/api/projects': { projects: [] },
  };
  const stub = `window.__paths = [];
window.fetch = async (url, init) => {
  const p = String(url).replace(/^https?:\\/\\/[^/]+/, '');
  window.__paths.push(p);
  let body = {};
  if (p === '/api/managed' || p.startsWith('/api/managed?')) body = ${JSON.stringify(data.managed)};
  else if (p.startsWith('/api/automation/status')) body = ${JSON.stringify(data['/api/automation/status'])};
  else if (p.startsWith('/api/automation/decisions')) body = { decisions: [] };
  else if (p.startsWith('/api/automation/runs')) body = { runs: [] };
  else if (p.startsWith('/api/actions')) body = { actions: [] };
  else if (p.startsWith('/api/projects')) body = { projects: [] };
  return { ok: true, status: 200, json: async () => ({ success: true, message: 'ok', data: body }) };
};`;

  try {
    new Function(stub);
  } catch (error) {
    console.error('STUB SYNTAX ERROR:', error.message);
    throw error;
  }

  const server = http.createServer((req, res) => {
    if (req.url === '/stub.js') { res.setHeader('Content-Type', 'text/javascript; charset=utf-8'); return res.end(stub); }
    if (req.url === '/app.js') { res.setHeader('Content-Type', 'text/javascript; charset=utf-8'); return res.end(js); }
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.end('<meta charset="utf-8"><div id="root"></div><script src="/stub.js"></script><script src="/app.js"></script>');
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const browser = await chromium.launch({ executablePath: '/opt/microsoft/msedge/msedge', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  try {
    const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
    page.setDefaultTimeout(20000);
    const errors = [];
    page.on('pageerror', (e) => errors.push(`${e.message}\n${(e.stack || '').split('\n').slice(0, 5).join('\n')}`));
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.getByRole('heading', { name: '自动化' }).waitFor();
    const tabs = page.locator('.ant-tabs-tab');
    assert.equal(await tabs.count(), 2, '应有两个标签');
    assert.equal((await tabs.nth(0).innerText()).trim(), '项目托管');
    assert.equal((await tabs.nth(1).innerText()).trim(), '自动化规则');

    // 默认进入项目托管：显示计划与候选，且带执行开关关闭提示
    await page.getByText('周五交 model1 阶段报告').waitFor();
    await page.getByText('待推进 2').waitFor();
    await page.getByText('自主执行当前关闭').waitFor();

    // 切到自动化规则：显示全局开关与新建规则按钮
    await tabs.nth(1).click();
    await page.getByText('全局开关').waitFor();
    await page.getByRole('button', { name: '新建规则' }).waitFor();
    await page.getByText('还没有条件触发规则，点右上角「新建规则」').waitFor();

    // 切回托管：计划还在
    await tabs.nth(0).click();
    await page.getByText('周五交 model1 阶段报告').waitFor();

    // 两个页面各自的数据请求都打到预期接口
    const paths = await page.evaluate(() => window.__paths);
    assert.ok(paths.some((p) => p === '/api/managed'), paths.join(','));
    assert.ok(paths.some((p) => p.startsWith('/api/automation/status')), paths.join(','));
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ ok: true, tabs: 2, paths: [...new Set(paths)] }));
  } finally {
    await browser.close().catch(() => {});
    server.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });
