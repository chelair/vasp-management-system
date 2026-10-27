// Real app, isolated HTTP. Display settings must not change backend configuration.
const {build}=require('esbuild');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright-core');
const http=require('node:http'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
  const bundle=await build({stdin:{contents:"import './src/main';",loader:'tsx',resolveDir:path.resolve('.')},bundle:true,write:false,outfile:'app.js',jsx:'automatic',define:{'process.env.NODE_ENV':'"production"'}});
  const files=Object.fromEntries(bundle.outputFiles.map(f=>[f.path.endsWith('.css')?'/app.css':'/app.js',f.text]));
  const requests=[];
  const server=http.createServer((req,res)=>{
    const url=new URL(req.url,'http://localhost'),p=url.pathname;
    if(!p.startsWith('/api/')){
      res.setHeader('Content-Type',p==='/app.js'?'text/javascript':p==='/app.css'?'text/css':'text/html; charset=utf-8');
      res.end(files[p]||'<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/app.css"><div id="root"></div><script>localStorage.setItem("vasp.auth.token","synthetic-ui");localStorage.setItem("vasp.nav.collapsed","true")</script><script src="/app.js"></script>');return;
    }
    requests.push({p,method:req.method});let data={};
    if(p==='/api/auth/me')data={user:{user_id:'test',username:'researcher',role:'user',enabled:true},session:{}};
    else if(p==='/api/deps')data={dependencies:[]};
    else if(p==='/api/ssh/config')data={servers:[]};
    else if(p==='/api/ssh/status')data={connected:false};
    else if(p==='/api/projects')data={projects:[]};
    else if(p==='/api/inspections')data={results:[]};
    else if(p==='/api/inspections/meta')data={enabled:true,interval_hours:2};
    else if(p.startsWith('/api/ai/chat/'))data={items:[]};
    res.setHeader('Content-Type','application/json');res.end(JSON.stringify({success:true,data}));
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1440,height:960}});page.setDefaultTimeout(10000);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const base='http://127.0.0.1:'+server.address().port;
  const openSettings=async()=>{await page.getByRole('button',{name:'用户菜单',exact:true}).click();await page.getByRole('menuitem',{name:/设置/}).click();await page.locator('.settings-page').waitFor();};
  const select=async(name,label)=>{const input=page.getByRole('combobox',{name,exact:true});await input.focus();await input.press('ArrowDown');await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option').filter({hasText:label}).click();};
  const accent=()=>page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--color-primary').trim());
  try{
    await page.goto(base+'/ai');await openSettings();
    const status=await page.locator('.settings-preview .status-tag').evaluate(e=>getComputedStyle(e).backgroundColor);
    await page.getByRole('button',{name:'鸢紫',exact:true}).click();
    await page.waitForFunction(()=>getComputedStyle(document.documentElement).getPropertyValue('--color-primary').trim()==='#7953B5');
    await page.waitForFunction(()=>getComputedStyle(document.querySelector('[aria-label="显示顶部时钟"]')).backgroundColor==='rgb(121, 83, 181)');
    assert.equal(await page.getByRole('switch',{name:'显示顶部时钟'}).evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(121, 83, 181)','Ant Design and CSS accents update together');
    assert.equal(await page.locator('.settings-preview .status-tag').evaluate(e=>getComputedStyle(e).backgroundColor),status,'status meaning remains unchanged');
    await select('显示密度','紧凑');await select('界面动效','减少动态效果');
    await page.getByRole('switch',{name:'显示顶部时钟'}).click();await page.locator('.clock-chip').waitFor({state:'detached'});
    assert.equal(await page.locator('.app-content').evaluate(e=>getComputedStyle(e).paddingTop),'18px');
    await page.reload();await page.locator('.settings-page').waitFor();
    assert.equal(await accent(),'#7953B5');
    assert.deepEqual(await page.evaluate(()=>({density:document.documentElement.dataset.density,motion:document.documentElement.dataset.motion})),{density:'compact',motion:'reduced'});
    assert.equal(await page.locator('.page-transition').evaluate(e=>getComputedStyle(e).animationName),'none','saved motion setting disables page entrance');
    assert.equal(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--motion-collapse').trim()),'0ms','saved setting disables custom folds and native details');
    assert.equal(await page.locator('.clock-chip').count(),0);
    await page.screenshot({path:'/tmp/vasp-settings-desktop.png'});
    await page.locator('.sidebar').getByRole('link',{name:'巡检中心',exact:true}).click();await page.locator('.page-header__title').getByText('巡检中心',{exact:true}).waitFor();
    assert.equal(await page.locator('.sidebar .nav-item.active').evaluate(e=>getComputedStyle(e).color),'rgb(94, 65, 141)');
    await openSettings();await page.getByRole('button',{name:'自选强调色',exact:true}).click();
    const hex=page.locator('.ant-color-picker-hex-input input');await hex.fill('FFF9E0');await hex.press('Enter');
    await page.waitForFunction(()=>getComputedStyle(document.documentElement).getPropertyValue('--color-primary').trim()==='#FFF9E0');
    await page.keyboard.press('Escape');await page.locator('.page-header__title').click();
    assert.equal(await page.locator('.settings-preview-primary').evaluate(e=>getComputedStyle(e).color),'rgb(0, 0, 0)','light custom accent keeps readable text');
    await page.setViewportSize({width:390,height:844});await page.waitForFunction(()=>document.querySelector('.sidebar').getBoundingClientRect().right<=1);
    assert.equal(await page.locator('.app-content').evaluate(e=>getComputedStyle(e).paddingTop),'12px');
    await page.screenshot({path:'/tmp/vasp-settings-mobile.png'});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.getByRole('button',{name:/恢复默认/}).click();
    await page.waitForFunction(()=>getComputedStyle(document.documentElement).getPropertyValue('--color-primary').trim()==='#527BC5');
    assert.equal(await page.evaluate(()=>localStorage.getItem('vasp.nav.collapsed')),'true','reset only changes appearance options');
    await page.getByRole('button',{name:'用户菜单',exact:true}).click();await page.getByRole('menuitem',{name:/退出登录/}).click();
    await page.getByRole('dialog',{name:'退出登录'}).waitFor();await page.getByRole('button',{name:/取\s*消/}).click();
    await page.evaluate(()=>localStorage.setItem('vasp.appearance','{invalid'));await page.reload();await page.locator('.settings-page').waitFor();
    assert.equal(await accent(),'#527BC5');
    assert.deepEqual(errors,[]);assert(requests.every(r=>r.method==='GET'),JSON.stringify(requests.filter(r=>r.method!=='GET')));
    console.log('PASS user-menu entry, real theme/custom accent, semantic colors, density/motion/clock, persistence, reset, malformed storage, mobile and unchanged logout; GET only');
  }catch(e){console.error((await page.locator('body').innerText()).slice(0,6000));throw e;}
  finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
