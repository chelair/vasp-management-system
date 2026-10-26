// Real workbench + app shell, isolated HTTP/SSE. No production data, model or SSH calls.
const { build } = require('esbuild');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const path = require('node:path'), http = require('node:http'), assert = require('node:assert/strict');
const REASONING = '先检查整体结构合理性与优化前后的变化，再检查局部配位。';
const stamp = '2026-10-26T10:00:00';
const TOOL = { id: 'tool1', name: 'check_structure', arguments: { structure: { task_id: 'model2', file: 'CONTCAR' } }, result: { source: 'project/model2/CONTCAR', atom_count: 188 }, status: 'completed', at: stamp };
const RUN = { id: 'r1', conversation_id: 'c1', message_id: 'a1', status: 'completed', model: 'deepseek-flash', connection_name: 'DeepSeek', prompt_version: 1, error: '', created_at: stamp, finished_at: '2026-10-26T10:00:18', usage: { total_tokens: 1024 }, reasoning: REASONING, tool_events: [TOOL, { ...TOOL, id: 'tool2', name: 'read_workspace', arguments: { path: 'project/model2/OUTCAR' }, result: { error: '文件尚未同步' }, status: 'failed' }] };
const msg = (id, role, content, status = 'completed') => ({ id, seq: 1, conversation_id: 'c1', role, content, status, created_at: stamp });
const detail = { id: 'c1', title: 'model2 结构优化分析', task_id: null, connection_id: 'model', project_id: 'p', workspace_enabled: true, prompt: '', prompt_version: 1, created_at: stamp, updated_at: stamp, messages: [msg('u1', 'user', '帮我看看 model2 的结构优化，应该重点关注什么？'), msg('a1', 'assistant', '优先关注**整体结构是否合理、优化后是否发生明显重构**，再检查局部配位和界面。\n\n目前读取到 188 个原子，OUTCAR 尚未同步，需要补充后再判断收敛。')], runs: [RUN], has_more: false };
const other = { ...detail, id: 'c2', title: '下一步计算计划', messages: [], runs: [] };
const connection = { id: 'model', name: 'DeepSeek', model: 'deepseek-flash', base_url: 'https://example.invalid', max_tokens: 2048, is_default: true, effective_reasoning_effort: 'high', reasoning_effort: 'high', reasoning_capabilities: { provider: 'deepseek', options: [{ value: 'none', label: '关闭' }, { value: 'high', label: '深入' }], tool_policy: 'supported', note: '' } };
(async () => {
  const bundle = await build({ stdin: { contents: `
    import React from 'react'; import {createRoot} from 'react-dom/client';
    import {App} from 'antd'; import {MemoryRouter,Routes,Route} from 'react-router-dom';
    import {AuthProvider} from './src/context/AuthContext'; import {SSHProvider} from './src/context/SSHContext';
    import AppLayout from './src/components/layout/AppLayout'; import AI from './src/pages/AI';
    import './src/styles/global.css';
    createRoot(document.getElementById('root')).render(<App><MemoryRouter initialEntries={['/ai?conversation=c1']}><AuthProvider><SSHProvider><Routes><Route element={<AppLayout/>}><Route path='/ai' element={<AI/>}/><Route path='/jobs' element={<div>作业管理入口</div>}/></Route></Routes></SSHProvider></AuthProvider></MemoryRouter></App>);
  `, loader: 'tsx', resolveDir: path.resolve('.') }, bundle: true, write: false, outfile: 'app.js', jsx: 'automatic', define: { 'process.env.NODE_ENV': '"development"' } });
  const js = bundle.outputFiles.find(f => f.path.endsWith('.js')).text;
  const css = bundle.outputFiles.find(f => f.path.endsWith('.css')).text;
  const requests = []; const streams = new Set(); let live;
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (!url.pathname.startsWith('/api/')) {
      res.setHeader('Content-Type', req.url === '/app.js' ? 'text/javascript' : req.url === '/app.css' ? 'text/css' : 'text/html; charset=utf-8');
      return res.end(req.url === '/app.js' ? js : req.url === '/app.css' ? css : '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/app.css"><div id="root"></div><script src="/app.js"></script>');
    }
    requests.push({ url: req.url, method: req.method });
    let data = {};
    const p = url.pathname;
    if (p === '/api/ai/chat/runs/live/events') {
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
      streams.add(res); res.on('close', () => streams.delete(res));
      res.write('data: ' + JSON.stringify({ run: live, message: detail.messages.at(-1) }) + '\n\n'); return;
    }
    if (p === '/api/ai/chat/connections') data = { items: [connection] };
    else if (p === '/api/ai/chat/targets') data = { items: [{ id: 'p', name: 'Kaolin', closed: false, tasks: [] }] };
    else if (p === '/api/ai/chat/conversations') data = { items: [detail, other] };
    else if (p === '/api/ai/chat/conversations/c1') data = detail;
    else if (p === '/api/ai/chat/conversations/c2') data = other;
    else if (p.endsWith('/context')) data = { generated_at: stamp, project: { name: 'Kaolin' }, tasks: [], summary: { task_count: 2 } };
    else if (p === '/api/ai/chat/conversations/c1/messages') {
      let body = ''; for await (const chunk of req) body += chunk;
      const input = JSON.parse(body); assert.equal(input.content, '继续检查局部配位'); assert.equal(input.retry, false);
      live = { ...RUN, id: 'live', message_id: 'a2', status: 'running', reasoning: '继续读取 model2 的局部环境。', tool_events: [{ ...TOOL, id: 'liveTool', name: 'get_structure_environment', status: 'running', result: {} }], finished_at: null };
      detail.messages.push(msg('u2', 'user', input.content), msg('a2', 'assistant', '', 'running')); detail.runs.unshift(live); data = live;
    } else if (p === '/api/ai/chat/runs/live/cancel') {
      live.status = 'cancelled'; live.finished_at = stamp; detail.messages.at(-1).status = 'cancelled';
      for (const stream of streams) { stream.end('data: ' + JSON.stringify({ run: live, message: detail.messages.at(-1) }) + '\n\n'); } data = {};
    } else if (p === '/api/ai/chat/runs/r1') data = RUN;
    else if (p.endsWith('/workspace')) data = { roots: [{ path: 'project/', access: 'read', purpose: '项目计算文件' }], rules: [], task_locations: [] };
    else if (p.endsWith('/workspace/files')) data = { path: 'project', items: [{ name: 'CONTCAR', path: 'project/CONTCAR', type: 'file', bytes: 50 }], total: 1 };
    else if (p.endsWith('/workspace/file')) data = { path: 'project/CONTCAR', content: '结构文件内容', bytes: 50, offset: 0, next_offset: null, sha256: 'mock', hash_scope: 'slice' };
    else if (p.startsWith('/api/reports/topic')) data = { items: [] };
    else if (p === '/api/deps') data = { dependencies: [] };
    else if (p === '/api/ssh/config') data = { servers: [] };
    else if (p === '/api/ssh/status') data = { connected: false };
    else if (p === '/api/auth/me') data = { user: { user_id: 'test', username: 'test', role: 'user' }, session: {} };
    res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ success: true, data }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ executablePath: process.env.BROWSER_PATH || '/opt/microsoft/msedge/msedge', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } }); page.setDefaultTimeout(10000);
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto('http://127.0.0.1:' + server.address().port);
    await page.getByText('目前读取到 188 个原子', { exact: false }).waitFor();
    assert.equal(await page.locator('.sidebar').isVisible(), false, 'workbench has one sidebar');
    assert.equal(await page.locator('.topbar').isVisible(), false);
    const activity = page.locator('.ai-activity-summary').first(); assert.equal(await activity.getAttribute('aria-expanded'), 'false');
    await activity.click(); await page.locator('.ai-thought summary').click(); await page.getByText(REASONING, { exact: true }).waitFor();
    const tools = page.locator('.ai-tool-call'); await tools.first().locator('summary').click(); await tools.first().getByText('check_structure', { exact: true }).waitFor();
    await tools.nth(1).locator('summary').click(); await tools.nth(1).getByText('文件尚未同步', { exact: false }).waitFor();
    await tools.nth(1).locator('summary').click(); await tools.first().locator('summary').click();
    await page.locator('.ai-thought summary').click();
    await page.screenshot({ path: '/tmp/vasp-ai-codex-desktop.png' });
    const composer = page.locator('.ai-composer'); assert((await composer.boundingBox()).y > 650, 'composer docks at bottom');
    await page.getByRole('button', { name: '项目资料', exact: true }).click();
    await page.getByRole('tab', { name: '工作区', exact: true }).click();
    await page.locator('.ai-run-row').filter({ hasText: 'project/' }).click();
    await page.locator('.ai-file-row').filter({ hasText: 'CONTCAR' }).click();
    await page.getByText('结构文件内容', { exact: true }).waitFor();
    await page.getByRole('dialog').last().getByRole('button', { name: 'Close', exact: true }).click();
    await page.getByRole('dialog', { name: '项目资料' }).getByRole('button', { name: 'Close', exact: true }).click();
    await page.getByRole('textbox', { name: '输入 AI 对话消息' }).fill('继续检查局部配位');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await page.getByRole('button', { name: '停止生成', exact: true }).waitFor();
    await page.getByRole('status').filter({ hasText: '分析原子环境' }).waitFor();
    assert.equal(requests.filter(r => r.url.endsWith('/messages')).length, 1, 'one send creates exactly one run');
    await page.getByRole('textbox', { name: '输入 AI 对话消息' }).fill('保留下一条草稿');
    await page.getByRole('button', { name: '停止生成', exact: true }).click();
    await page.getByRole('button', { name: '发送', exact: true }).waitFor();
    assert.equal(await page.getByRole('textbox', { name: '输入 AI 对话消息' }).inputValue(), '保留下一条草稿');
    await page.locator('.ai-activity-summary').last().click();
    assert.equal(await page.locator('.ai-tool-call').last().locator('summary').innerText().then(t => t.includes('已中断')), true, 'unfinished tools stop spinning after cancellation');
    await page.getByRole('textbox', { name: '搜索对话' }).fill('下一步');
    assert.equal(await page.locator('.ai-session').count(), 1);
    await page.locator('.ai-session').click(); await page.locator('.ai-chat-heading strong').getByText('下一步计算计划', { exact: true }).waitFor(); await page.getByRole('textbox', { name: '输入 AI 对话消息' }).waitFor();
    assert.equal(await page.getByRole('textbox', { name: '输入 AI 对话消息' }).inputValue(), '');
    await page.getByRole('textbox', { name: '搜索对话' }).fill('model2'); await page.locator('.ai-session').click();
    await page.waitForFunction(() => document.querySelector('.ai-composer textarea')?.value === '保留下一条草稿');
    await page.getByRole('button', { name: '收起会话栏', exact: true }).click();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: '/tmp/vasp-ai-codex-mobile.png' });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'mobile has no horizontal overflow');
    const mobileComposer = await composer.boundingBox(); assert(mobileComposer.y + mobileComposer.height <= 844, 'mobile composer stays visible');
    await page.getByRole('button', { name: '展开会话栏', exact: true }).click();
    await page.getByRole('button', { name: '关闭会话栏', exact: true }).waitFor();
    await page.getByRole('link', { name: '返回项目管理' }).click(); await page.getByText('作业管理入口', { exact: true }).waitFor();
    assert.equal(await page.locator('.app-shell--ai').count(), 0, 'workbench layout only affects the AI route');
    assert.equal(await page.locator('.topbar').isVisible(), true, 'system header returns outside workbench');
    assert.deepEqual(requests.filter(r => r.method !== 'GET').map(r => r.url), ['/api/ai/chat/conversations/c1/messages', '/api/ai/chat/runs/live/cancel']);
    assert.deepEqual(errors, []);
    console.log('PASS Codex layout, activity details, live SSE, stop, drafts, file drawer, session search, mobile and return navigation; only explicit send/cancel writes');
  } catch (error) { console.error((await page.locator('body').innerText()).slice(0, 8000)); throw error; }
  finally { for (const stream of streams) stream.end(); await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; });
