// AI 工作台「可选显示思考链路/工具调用」验收：真实 React + 假 fetch，不连模型。
const { build } = require('esbuild');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/tmp/vasp-report-debug/node_modules/playwright-core');
const path = require('node:path'), http = require('node:http'), assert = require('node:assert/strict');

const REASONING = '先看现有计划，再定位任务，最后建计划';
const RUN = {
  id: 'r1', conversation_id: 'c1', message_id: 'm2', status: 'completed', model: 'deepseek-flash',
  connection_name: '测试连接', prompt_version: 1, error: '', created_at: '2026-10-20T23:00:00',
  finished_at: '2026-10-20T23:00:05', usage: { total_tokens: 10 }, reasoning: REASONING,
  tool_events: [{ id: 'call_0', name: 'get_managed_plans', arguments: {}, result: { plans: [] }, status: 'completed', at: '2026-10-20T23:00:01' }],
};
const DETAIL = {
  id: 'c1', title: '测试会话', task_id: null, connection_id: null, project_id: 'P1',
  workspace_enabled: true, prompt: '', prompt_version: 1,
  created_at: '2026-10-20T23:00:00', updated_at: '2026-10-20T23:00:05',
  messages: [
    { id: 'm1', seq: 1, conversation_id: 'c1', role: 'user', content: '帮我托管这个项目', status: 'completed', created_at: '2026-10-20T23:00:00' },
    { id: 'm2', seq: 2, conversation_id: 'c1', role: 'assistant', content: '好的，先看看现有计划。', status: 'completed', created_at: '2026-10-20T23:00:01' },
  ],
  runs: [RUN], has_more: false,
};

(async () => {
  const bundle = await build({
    stdin: {
      contents: `import React from 'react';
import {createRoot} from 'react-dom/client';
import {App} from 'antd';
import {MemoryRouter} from 'react-router-dom';
import AI from './src/pages/AI';
createRoot(document.getElementById('root')).render(<App><MemoryRouter initialEntries={['/?conversation=c1']}><AI/></MemoryRouter></App>);`,
      loader: 'tsx',
      resolveDir: path.resolve('.'),
    },
    bundle: true, write: false, outfile: 'app.js', jsx: 'automatic',
    define: { 'process.env.NODE_ENV': '"development"' },
  });
  const js = bundle.outputFiles.find((f) => f.path.endsWith('.js')).text;

  const stub = `window.fetch = async (url) => {
  const p = String(url).replace(/^https?:\\/\\/[^/]+/, '');
  let data = {};
  if (p === '/api/ai/chat/conversations/c1') data = ${JSON.stringify(DETAIL)};
  else if (p === '/api/ai/chat/conversations/c1/context') data = { generated_at: '2026-10-20T23:00:00', scope: 'project', project: { project_id: 'P1', name: 'PMS' }, tasks: [] };
  else if (p === '/api/ai/chat/conversations') data = { items: [${JSON.stringify({ id: 'c1', title: '测试会话', project_id: 'P1', workspace_enabled: true, prompt: '', prompt_version: 1, task_id: null, connection_id: null, created_at: '2026-10-20T23:00:00', updated_at: '2026-10-20T23:00:05' })}] };
  else if (p === '/api/ai/chat/targets') data = { items: [] };
  else if (p.startsWith('/api/reports/topic')) data = { items: [] };
  else if (p === '/api/ai/chat/connections') data = { items: [] };
  return { ok: true, status: 200, json: async () => ({ success: true, message: 'ok', data }) };
};`;

  const server = http.createServer((req, res) => {
    if (req.url === '/stub.js') { res.setHeader('Content-Type', 'text/javascript; charset=utf-8'); return res.end(stub); }
    if (req.url === '/app.js') { res.setHeader('Content-Type', 'text/javascript; charset=utf-8'); return res.end(js); }
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.end('<meta charset="utf-8"><div id="root"></div><script>localStorage.setItem("vasp.auth.token","t")</script><script src="/stub.js"></script><script src="/app.js"></script>');
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const browser = await chromium.launch({ executablePath: '/opt/microsoft/msedge/msedge', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  try {
    const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
    page.setDefaultTimeout(20000);
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/`);

    await page.getByText('好的，先看看现有计划。').waitFor();
    // 没有“工具开关”：思考与工具调用始终作为思考链路的一部分存在（历史回答默认折叠）。
    const block = page.getByText(/思考与工具调用/);
    await block.waitFor();
    assert.equal(await page.locator('label.ai-toggle').count(), 0, '不应再有工具/思考开关');
    assert.ok(await page.getByText('模型可读取项目文件并调用工具').isVisible());
    await block.click();
    await page.getByText(REASONING).waitFor();
    await page.getByText('get_managed_plans').waitFor();

    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ ok: true }));
  } finally {
    await browser.close().catch(() => {});
    server.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });
