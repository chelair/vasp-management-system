// Real SSH page and providers; isolated HTTP fixtures, no real server changes.
const { build } = require('esbuild');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const http = require('node:http'), path = require('node:path'), assert = require('node:assert/strict');

(async () => {
  const bundle = await build({ stdin: { contents: "import './src/main';", loader: 'tsx', resolveDir: path.resolve('.') }, bundle: true, write: false, outfile: 'app.js', jsx: 'automatic', define: { 'process.env.NODE_ENV': '"production"' } });
  const files = Object.fromEntries(bundle.outputFiles.map(f => [f.path.endsWith('.css') ? '/app.css' : '/app.js', f.text]));
  let servers = [
    { name: 'server1', host: 'login.research.example', port: 22, user: 'researcher', key_path: '~/.ssh/id_rsa', queue_system: 'lsf', home: '/data/researcher', remote_base: '/data/researcher/projects' },
    { name: 'server2', host: 'compute.example', port: 2222, user: 'scientist', password_configured: true, queue_system: 'slurm', home: '/home/scientist', remote_base: '/scratch/scientist/projects' },
  ];
  let roots = { local_root: '/data/projects', remote_roots: { server1: '/data/researcher/projects', server2: '/scratch/scientist/projects' } };
  const requests = []; let failTest = false;
  const server = http.createServer(async (req, res) => {
    const p = new URL(req.url, 'http://localhost').pathname;
    if (!p.startsWith('/api/')) {
      res.setHeader('Content-Type', p === '/app.js' ? 'text/javascript' : p === '/app.css' ? 'text/css' : 'text/html; charset=utf-8');
      res.end(files[p] || '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/app.css"><div id="root"></div><script>localStorage.setItem("vasp.auth.token","synthetic-ssh-ui");localStorage.setItem("vasp.nav.collapsed","true")</script><script src="/app.js"></script>'); return;
    }
    let raw = ''; for await (const chunk of req) raw += chunk;
    const body = raw ? JSON.parse(raw) : null;
    requests.push({ p, method: req.method, body });
    let data = {};
    if (p === '/api/auth/me') data = { user: { user_id: 'fixture', username: 'researcher', role: 'admin', enabled: true }, session: {} };
    else if (p === '/api/deps') data = { dependencies: [] };
    else if (p === '/api/ssh/config') {
      if (req.method === 'PUT') servers = body.servers.map(s => ({ ...servers.find(old => old.name === s.name), ...s }));
      data = { servers };
    } else if (p === '/api/ssh/status') data = { connected: true, server: 'server1', latencyMs: 28 };
    else if (p === '/api/servers') data = { servers };
    else if (p === '/api/settings/root-paths') {
      if (req.method === 'PUT') roots = body;
      data = roots;
    } else if (p === '/api/ssh/test') {
      await new Promise(r => setTimeout(r, 250));
      if (failTest) {
        res.writeHead(502, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: false, message: '连接超时，请检查服务器地址' })); return;
      }
      const target = servers.find(s => s.name === body.server);
      data = { server: target.name, host: target.host, user: target.user, latency_ms: 42 };
    }
    res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ success: true, data }));
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const browser = await chromium.launch({ executablePath: process.env.BROWSER_PATH || '/opt/microsoft/msedge/msedge', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1040 } }); page.setDefaultTimeout(10000);
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  const base = 'http://127.0.0.1:' + server.address().port;
  const select = name => page.getByRole('navigation', { name: '服务器列表' }).getByRole('button', { name: new RegExp(name) }).click();
  const writes = () => requests.filter(r => r.method !== 'GET');
  const dialog = () => page.getByRole('dialog');
  try {
    await page.goto(base + '/ssh'); await page.locator('.ssh-connection-heading h2').getByText('server1', { exact: true }).waitFor();
    assert.equal(await page.getByText('演示模式说明', { exact: true }).count(), 0);
    await page.getByRole('button', { name: /设为当前服务器/ }).click();
    assert.equal(writes().length, 0, 'selection preserves existing local-only behavior');
    await page.reload(); await page.getByRole('button', { name: /取消选用/ }).waitFor();

    await page.getByRole('button', { name: /测试连接/ }).click();
    await select('server2');
    await page.waitForFunction(() => !document.querySelector('.ssh-connection-toolbar .ant-btn-loading'));
    await page.waitForFunction(() => !document.querySelector('.ssh-connection-toolbar button').disabled);
    assert.equal(await page.locator('.ssh-connection-heading h2').innerText(), 'server2', 'test completion keeps user selection');
    assert.equal(writes().filter(r => r.p === '/api/ssh/test').length, 1);
    assert.equal(writes().filter(r => r.p === '/api/ssh/config').length, 0, 'testing does not rewrite configuration');
    failTest = true; await page.getByRole('button', { name: /测试连接/ }).click();
    await page.locator('.ssh-connection-result').getByText('连接测试未通过', { exact: true }).waitFor();
    failTest = false; await page.getByRole('button', { name: /测试连接/ }).click();
    await page.locator('.ssh-connection-result').getByText('连接测试通过 · 42 ms', { exact: true }).waitFor();

    await page.getByRole('button', { name: /编辑配置/ }).click();
    await dialog().getByLabel('主机地址', { exact: true }).fill('updated.compute.example');
    await dialog().getByRole('button', { name: /保存配置/ }).click(); await dialog().waitFor({ state: 'hidden' });
    assert.equal(servers.find(s => s.name === 'server2').host, 'updated.compute.example');
    assert.equal(await page.locator('.ssh-connection-result').count(), 0, 'edited settings do not retain an old test success');
    assert.equal(servers.find(s => s.name === 'server2').password, null, 'editing an existing password server leaves its secret unchanged');
    await page.getByRole('button', { name: /新建服务器/ }).click();
    await dialog().getByLabel('服务器名称', { exact: true }).fill('server1');
    await dialog().getByLabel('主机地址', { exact: true }).fill('third.example');
    await dialog().getByLabel('登录用户', { exact: true }).fill('tester');
    await dialog().getByLabel('私钥路径', { exact: true }).fill('~/.ssh/id_test');
    await dialog().getByRole('button', { name: /保存配置/ }).click();
    await dialog().getByText('服务器名称已存在', { exact: true }).waitFor();
    await dialog().getByLabel('服务器名称', { exact: true }).fill('server3');
    await dialog().locator('.ant-radio-button-wrapper').filter({ hasText: '密码' }).click();
    await dialog().locator('input[type="password"]').fill('synthetic-fixture-secret');
    await dialog().getByRole('button', { name: /保存配置/ }).click(); await dialog().waitFor({ state: 'hidden' });
    assert.equal(servers.length, 3);
    assert.equal(await page.locator('.ssh-connection-heading h2').innerText(), 'server3');
    assert(!await page.evaluate(() => localStorage.getItem('vasp.ssh.servers.v1').includes('synthetic-fixture-secret')));

    await page.getByRole('button', { name: /删除配置/ }).click();
    await page.getByRole('button', { name: /取\s*消/ }).click(); assert.equal(servers.length, 3);
    await page.getByRole('button', { name: /删除配置/ }).click();
    await page.getByRole('button', { name: /删\s*除$/ }).click();
    await page.waitForFunction(() => document.querySelectorAll('.ssh-directory__entry').length === 2);
    assert.equal(servers.length, 2); assert.equal(await page.locator('.ssh-connection-heading h2').innerText(), 'server1');

    await page.getByRole('button', { name: /项目文件位置/ }).click();
    await page.getByLabel('本地项目根目录', { exact: true }).fill('/data/new-projects');
    await page.getByRole('button', { name: '保存根目录', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('.ssh-path-settings .ant-btn-loading'));
    assert.equal(roots.local_root, '/data/new-projects');
    await page.getByRole('button', { name: /项目文件位置/ }).click();
    await select('server1'); await page.getByRole('button', { name: /测试连接/ }).click();
    await page.locator('.ssh-connection-result').getByText('连接测试通过 · 42 ms', { exact: true }).waitFor();
    await page.waitForFunction(() => document.querySelectorAll('.ant-message-notice').length === 0);
    await page.locator('.app-content').evaluate(el => el.scrollTo({ top: 0, behavior: 'instant' }));
    await page.screenshot({ path: '/tmp/vasp-ssh-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.querySelector('.sidebar').getBoundingClientRect().right <= 1);
    await page.locator('.app-content').evaluate(el => el.scrollTo({ top: 0, behavior: 'instant' }));
    await page.screenshot({ path: '/tmp/vasp-ssh-mobile.png', fullPage: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'mobile has no horizontal overflow');
    await page.getByRole('button', { name: /编辑配置/ }).click();
    assert.equal(await dialog().evaluate(e => e.getBoundingClientRect().width <= innerWidth), true);
    await dialog().getByRole('button', { name: /取\s*消/ }).click();
    const navButton = page.getByRole('navigation', { name: '服务器列表' }).getByRole('button').nth(1);
    await navButton.focus(); await page.keyboard.press('Enter');
    assert.equal(await page.locator('.ssh-connection-heading h2').innerText(), 'server2');
    servers = []; await page.reload(); await page.getByText('还没有服务器', { exact: true }).waitFor();
    await page.getByRole('button', { name: /添加第一台服务器/ }).click(); await dialog().waitFor();
    assert.equal(await dialog().getByLabel('主机地址', { exact: true }).inputValue(), '', 'new form resets old values');
    assert.deepEqual(errors, []);
    assert(writes().every(r => ['/api/ssh/test', '/api/ssh/config', '/api/settings/root-paths'].includes(r.p)), 'only existing SSH and path APIs are used');
    console.log('PASS SSH real page: server selection/persistence, test success/failure/retry, cross-server loading, add/edit/delete/cancel, duplicate validation, stored password, path save, keyboard, mobile and empty state; isolated HTTP only.');
  } catch (error) {
    console.error((await page.locator('body').innerText()).slice(0, 7000)); throw error;
  } finally { await browser.close(); await new Promise(r => server.close(r)); }
})().catch(error => { console.error(error); process.exitCode = 1; });
