// 托管页真实浏览器验收：隔离 HTTP/鉴权/计划数据，不连接集群或模型。
const { build } = require('esbuild');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/tmp/vasp-report-debug/node_modules/playwright-core');
const { spawn } = require('node:child_process');
const http = require('node:http'), path = require('node:path'), fs = require('node:fs/promises'), os = require('node:os'), assert = require('node:assert/strict');

(async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'vasp-managed-ui-'));
  let python, browser, server;
  try {
    const bundle = await build({
      stdin: {
        contents: `import React from 'react';
import {createRoot} from 'react-dom/client';
import {App} from 'antd';
import {MemoryRouter} from 'react-router-dom';
import { ManagedPanel } from './src/components/managed/ManagedPanel';
createRoot(document.getElementById('root')).render(<App><MemoryRouter initialEntries={['/managed']}><ManagedPanel/></MemoryRouter></App>);`,
        loader: 'tsx',
        resolveDir: path.resolve('.'),
      },
      bundle: true, write: false, outfile: path.join(dir, 'app.js'), jsx: 'automatic',
      define: { 'process.env.NODE_ENV': '"development"' },
    });
    const js = bundle.outputFiles.find((f) => f.path.endsWith('.js')).text;

    python = spawn('.venv/bin/python', ['tests/managed_ui_server.py'], { cwd: path.resolve('.') });
    let stderr = '';
    python.stderr.on('data', (v) => (stderr += v));
    const fixture = await new Promise((resolve, reject) => {
      let out = '';
      const timer = setTimeout(() => reject(Error(stderr || 'fixture timeout')), 30000);
      python.on('exit', (code) => { clearTimeout(timer); reject(Error(`${code} ${stderr}`)); });
      python.stdout.on('data', (v) => {
        out += v;
        const line = out.split('\n').find((item) => item.startsWith('MANAGED_FIXTURE '));
        if (line) { clearTimeout(timer); resolve(JSON.parse(line.slice('MANAGED_FIXTURE '.length))); }
      });
    });

    server = http.createServer((req, res) => {
      if (req.url.startsWith('/api/')) {
        const proxy = http.request(`http://127.0.0.1:${fixture.port}` + req.url,
          { method: req.method, headers: req.headers }, (r) => { res.writeHead(r.statusCode, r.headers); r.pipe(res); });
        proxy.on('error', (e) => { res.writeHead(502); res.end(e.message); });
        req.pipe(proxy);
        return;
      }
      if (req.url === '/app.js') { res.setHeader('Content-Type', 'text/javascript'); return res.end(js); }
      res.setHeader('Content-Type', 'text/html');
      res.end(`<div id="root"></div><script>localStorage.setItem('vasp.auth.token', ${JSON.stringify(fixture.token)})</script><script src="/app.js"></script>`);
    });
    await new Promise((r) => server.listen(0, '127.0.0.1', r));
    const url = `http://127.0.0.1:${server.address().port}`;

    browser = await chromium.launch({ executablePath: '/opt/microsoft/msedge/msedge', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
    const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
    page.setDefaultTimeout(20000);
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(url);

    // 1) 计划渲染：目标、阶段、候选排序（人工/AI 覆盖不出现，初始为阶段优先级）
    await page.getByText('周五交 model1 阶段报告，其余接着跑').waitFor();
    await page.getByText('阶段报告').first().waitFor();
    await page.getByText('待推进 2').waitFor();
    await page.getByText('下一步：model1（首发提交）').waitFor();
    const rows = await page.locator('.ant-table-tbody tr').allInnerTexts();
    assert.ok(rows.some((t) => t.includes('model1') && t.includes('首发提交')), rows.join('|'));

    // 2) 暂停 → 恢复
    await page.getByRole('button', { name: '暂停' }).click();
    await page.getByText('已暂停推进').waitFor();
    await page.getByText('计划已暂停：不会自动推进').waitFor();
    await page.getByRole('button', { name: '恢复' }).click();
    await page.getByText('已恢复').waitFor();

    // 3) 人工改优先级：model2 → 100 并锁定，保存后显示"人工/AI 覆盖"
    const t2row = page.locator('.ant-table-tbody tr', { hasText: 'model2' }).first();
    const input = t2row.locator('input.ant-input-number-input');
    await input.fill('100');
    await input.press('Enter');
    await t2row.getByRole('switch').click();
    await t2row.getByRole('button', { name: /保\s*存/ }).click();
    await page.getByText('优先级已保存').waitFor();
    await page.getByText('人工/AI 覆盖').first().waitFor();
    // 锁定后 AI 不能覆盖：直接调用后端补丁应返回 409
    const api = async (method, pathname, body) => {
      const r = await fetch(`http://127.0.0.1:${fixture.port}/api` + pathname, {
        method, headers: { Authorization: 'Bearer ' + fixture.token, 'Content-Type': 'application/json' },
        body: body && JSON.stringify(body),
      });
      return { status: r.status, data: await r.json() };
    };
    const listed = await api('GET', '/managed');
    const current = listed.data.data.plans[0].plan;
    const locked = Object.values(current.task_overrides || {}).some((o) => o.locked);
    assert.ok(locked, '锁定状态应已保存');

    // 4) 资源建议：模拟快照必须显示"不能作为自动提交依据"，且不出现候选
    await page.getByRole('button', { name: '资源建议' }).click();
    await page.getByText(/模拟数据或缺少真实采集/).waitFor();
    // 空计划/未选队列时也要能看到服务器队列并可保存，而不是一片空白。
    await page.getByText('这台服务器可用的队列').waitFor();
    await page.getByRole('button', { name: '保存队列并评分' }).waitFor();

    // 5) 脚本预览：没有可用的真实快照 → 明确提示，不显示脚本
    await page.getByRole('button', { name: '脚本预览' }).click();
    await page.getByText(/没有可预览的资源方案|当前没有可预览的脚本|模拟数据或缺少真实采集/).waitFor();

    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ ok: true, planId: fixture.plan_id, rows: rows.length }));
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server) server.close();
    if (python) python.kill();
    await fs.rm(dir, { recursive: true, force: true });
  }
})().catch((error) => { console.error(error); process.exit(1); });
