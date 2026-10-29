// Built application with isolated HTTP fixtures. No real accounts, models or SSH.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const dist = path.resolve(process.env.VASP_PERF_DIST || 'dist');
const baseline = process.env.VASP_PERF_BASELINE === '1';
const stamp = '2026-10-29T12:00:00';
const projects = Array.from({ length: 7 }, (_, i) => ({ id: `p${i}`, name: `Project${i}`, closed: false, tasks: [] }));
const results = projects.flatMap(project => Array.from({ length: 95 }, (_, i) => ({
  id: `${project.id}-${i}`, task_id: `${project.id}-${i}`, project_name: project.name,
  task_name: `task${String(i).padStart(3, '0')}`, project_closed: false, category: 'convergence',
  task_category: '自由能', group_name: 'PATH1', structure_label: String(i + 1),
  task_status: 'running', status: 'normal', check_time: stamp, message: '状态正常', has_inspection: true,
})));
const conversation = { id: 'c1', title: '长对话加载检查', project_id: 'p0', connection_id: 'model',
  task_id: null, prompt: '', prompt_version: 1, created_at: stamp, updated_at: stamp };
const messages = Array.from({ length: 40 }, (_, i) => ({ id: `m${i}`, seq: i + 1,
  conversation_id: 'c1', role: i % 2 ? 'assistant' : 'user', status: 'completed', created_at: stamp,
  content: i % 2 ? `回答 ${i}\n\n${'已有科学证据与解释。'.repeat(100)}` : `检查结构 ${i}`,
}));
const runs = messages.filter(message => message.role === 'assistant').map(message => ({
  id: `r${message.id}`, conversation_id: 'c1', message_id: message.id, status: 'completed',
  model: 'fixture', connection_name: 'fixture', prompt_version: 1, error: '',
  created_at: stamp, finished_at: stamp, usage: {}, reasoning: '只展示已有过程。'.repeat(500),
  tool_events: Array.from({ length: 10 }, (_, i) => ({ id: `t${i}`, name: 'read_workspace',
    arguments: { path: `project/result${i}` }, result: { content: '冻结证据'.repeat(1000) }, status: 'completed', at: stamp })),
}));
const connection = { id: 'model', name: 'fixture', model: 'fixture', base_url: 'https://example.invalid',
  max_tokens: 2048, is_default: true, effective_reasoning_effort: 'none',
  reasoning_capabilities: { options: [{ value: 'none', label: '关闭' }], tool_policy: 'supported', note: '' } };

(async () => {
  const requests = [];
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    requests.push({ path: url.pathname, method: req.method });
    if (url.pathname.startsWith('/api/')) {
      let data = {};
      if (url.pathname === '/api/auth/me') data = { user: { user_id: 'fixture', username: 'fixture', role: 'user' }, session: {} };
      else if (url.pathname === '/api/ssh/config') data = { servers: [] };
      else if (url.pathname === '/api/ssh/status') data = { connected: false };
      else if (url.pathname === '/api/deps') data = { dependencies: [] };
      else if (url.pathname === '/api/inspections') data = { results };
      else if (url.pathname === '/api/inspections/meta') data = { enabled: false, interval_hours: 2 };
      else if (url.pathname === '/api/ai/chat/connections') data = { items: [connection] };
      else if (url.pathname === '/api/ai/chat/targets') data = { items: projects };
      else if (url.pathname === '/api/ai/chat/conversations') data = { items: [conversation] };
      else if (url.pathname === '/api/ai/chat/conversations/c1') data = { ...conversation, messages, runs, has_more: false };
      else if (url.pathname.endsWith('/context')) data = { project: { name: 'Project0' }, summary: { task_count: 95 }, tasks: [] };
      else if (url.pathname.startsWith('/api/reports/topic')) data = { items: [] };
      const respond = () => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ success: true, data })); };
      if (url.pathname.endsWith('/inspections/meta')) setTimeout(respond, 1500);
      else respond();
      return;
    }
    const file = path.join(dist, url.pathname);
    const target = fs.existsSync(file) && fs.statSync(file).isFile() ? file : path.join(dist, 'index.html');
    const ext = path.extname(target);
    res.setHeader('Content-Type', ext === '.js' ? 'text/javascript' : ext === '.css' ? 'text/css' : 'text/html; charset=utf-8');
    res.end(fs.readFileSync(target));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ executablePath: process.env.BROWSER_PATH || '/opt/microsoft/msedge/msedge', headless: true, args: ['--no-sandbox'] });
  try {
    const context = await browser.newContext();
    await context.addInitScript(() => localStorage.setItem('vasp.auth.token', 'isolated-fixture'));
    const page = await context.newPage(); page.setDefaultTimeout(15000);
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    const origin = `http://127.0.0.1:${server.address().port}`;
    const metrics = {};
    let start = Date.now();
    await page.goto(origin + '/inspection', { waitUntil: 'domcontentloaded' });
    await page.locator('.ant-table-row').first().waitFor();
    metrics.inspection_rows_ready_ms = Date.now() - start;
    metrics.inspection_rendered_rows = await page.locator('.ant-table-row').count();
    await page.waitForLoadState('networkidle');
    const resources = await page.evaluate(() => performance.getEntriesByType('resource').filter(r => /\/(assets|3dmol)\//.test(r.name)).map(r => ({ path: new URL(r.name).pathname, bytes: r.decodedBodySize })));
    metrics.inspection_asset_bytes = resources.reduce((sum, resource) => sum + resource.bytes, 0);
    metrics.inspection_3d_requests = requests.filter(r => r.path.includes('/3dmol/')).length;
    metrics.inspection_chart_requests = requests.filter(r => /echarts/.test(r.path)).length;
    if (!baseline) {
      assert.equal(metrics.inspection_rendered_rows, 7 * 30);
      assert.equal(metrics.inspection_3d_requests, 0);
      assert.equal(metrics.inspection_chart_requests, 0);
      const block = page.locator('.inspection-project').first();
      const seen = [];
      for (let p = 1; p <= 4; p++) {
        if (p > 1) { await block.locator('.ant-pagination-next button').click(); await block.locator(`.ant-pagination-item-${p}.ant-pagination-item-active`).waitFor(); }
        seen.push(...await block.locator('.ant-table-row').evaluateAll(rows => rows.map(row => row.dataset.rowKey)));
        const expected = p < 4 ? 30 : 5;
        assert.equal(await block.locator('.ant-table-row').count(), expected);
        assert.equal(await block.locator('.ant-table-row').first().locator('td[rowspan]').getAttribute('rowspan'), String(expected));
      }
      assert.equal(new Set(seen).size, 95, 'all grouped tasks remain reachable without duplicates');
      assert.equal(seen.length, 95);
      await page.getByPlaceholder('搜索项目 / 任务 / 信息').fill('task094');
      assert.equal(await page.locator('.ant-table-row').count(), 7, 'search includes every page');
    }
    // Navigate through the real application; the shared layout should stay mounted.
    await page.locator('.sidebar').getByRole('link', { name: 'AI 工作台', exact: true }).click();
    await page.locator('.ai-session').click();
    await page.locator('.ai-message--assistant').last().waitFor();
    await page.waitForLoadState('networkidle');
    metrics.ai_context_requests_before_open = requests.filter(r => r.path.endsWith('/context')).length;
    if (!baseline) assert.equal(metrics.ai_context_requests_before_open, 0);
    await page.locator('.ai-activity-summary').last().click();
    await page.locator('.ai-tool-call').first().waitFor();
    metrics.ai_hidden_tool_details = await page.locator('.ai-tool-detail').count();
    if (!baseline) assert.equal(metrics.ai_hidden_tool_details, 0);
    const tool = page.locator('.ai-tool-call').first();
    await tool.locator('summary').click(); await tool.locator('.ai-tool-detail').waitFor();
    assert.ok((await tool.innerText()).includes('冻结证据'));
    if (!baseline) {
      await tool.locator('summary').click(); await tool.locator('.ai-tool-detail').waitFor({ state: 'detached' });
      assert.equal(requests.filter(r => r.path === '/api/deps').length, 1, 'route changes retain the shared layout');
    }
    start = Date.now();
    await page.getByRole('textbox', { name: '输入 AI 对话消息' }).fill('继续检查，不重新渲染历史回答');
    metrics.ai_fill_ms = Date.now() - start;
    await page.getByRole('button', { name: '项目资料', exact: true }).click();
    await page.getByRole('tab', { name: '基本信息', exact: true }).click();
    await page.getByText('项目说明', { exact: true }).waitFor();
    await page.locator('.ai-context-drawer .ant-drawer-close').click();
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(requests.filter(r => r.method !== 'GET'), []);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ baseline, ...metrics }, null, 2));
    console.log('PASS large inspection list, grouped pagination/search, long conversation, deferred evidence, route navigation and mobile layout; read-only fixtures');
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; });
