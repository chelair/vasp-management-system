// PLAYWRIGHT_MODULE=/path/to/playwright-core node tests/browser/kpoints-sync.cjs
const {build}=require('esbuild');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright-core');
const http=require('node:http');
const path=require('node:path');
const assert=require('node:assert/strict');
(async()=>{
  const bundle=await build({stdin:{contents:`
    import React,{useState} from 'react';
    import {createRoot} from 'react-dom/client';
    import {App} from 'antd';
    import KpointsPanel from './src/components/jobs/KpointsPanel';
    function View(){
      const [text,setText]=useState(null);
      const [input,setInput]=useState({task_id:'neb',files:{},draft:{},changes:[],pending:false,synced:false});
      return <KpointsPanel taskId="neb" taskName="LMR_neb"
        poscarContent={'H\\n1\\n10 0 0\\n0 10 0\\n0 0 20\\nH\\n1\\nDirect\\n0 0 0\\n'}
        kpointsContent={text} input={input} onConfirmMesh={()=>{}}
        onGenerate={content=>{setText(content);setInput(old=>({...old,files:{KPOINTS:{text:content}}}));}}
        onStatePushed={setInput}/>;
    }
    createRoot(document.getElementById('root')).render(<App><View/></App>);
  `,resolveDir:path.resolve('.'),loader:'tsx'},bundle:true,write:false,format:'iife',jsx:'automatic',define:{'process.env.NODE_ENV':'"development"'}});
  let calls=0,mesh;
  const server=http.createServer((req,res)=>{
    if(req.url==='/api/jobs/tasks/neb/upload-kpoints'){
      assert.equal(req.method,'POST');let body='';req.on('data',data=>body+=data);
      req.on('end',()=>{
        calls++;const text=JSON.parse(body).content;mesh=text.split('\n')[3].split(/\s+/).map(Number);
        res.setHeader('Content-Type','application/json');
        res.end(JSON.stringify({success:true,data:{dir:'/remote/neb',applied:[],backup_file:null,unchanged:true,
          state:{task_id:'neb',files:{KPOINTS:{text,mesh,mesh_note:'Gamma'}},draft:{},changes:[],pending:false,synced:true}}}));
      });return;
    }
    res.setHeader('Content-Type',req.url==='/app.js'?'text/javascript':'text/html');
    res.end(req.url==='/app.js'?bundle.outputFiles[0].text:'<div id="root"></div><script src="/app.js"></script>');
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'/opt/microsoft/msedge/msedge',headless:true,args:['--no-sandbox']});
  try{
    const page=await browser.newPage();page.setDefaultTimeout(10000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:'+server.address().port);
    await page.getByRole('button',{name:'生成 KPOINTS 文件'}).click();
    assert.equal(await page.getByText('尚未同步本次计算的 KPOINTS',{exact:false}).count(),1);
    await page.getByRole('button',{name:/同步到远端/}).click();
    await page.waitForFunction(()=>document.querySelector('.job-kpoints-form')!==null);
    assert.equal(calls,1,'local text equality must not prevent actual remote verification');
    const values=await page.locator('.job-card').first().locator('input').evaluateAll(nodes=>nodes.map(n=>Number(n.value)));
    assert.deepEqual(values,mesh,'current mesh must immediately reflect the server response');
    assert.equal(await page.getByText('尚未同步本次计算的 KPOINTS',{exact:false}).count(),0);
    assert.deepEqual(errors,[]);
    console.log('PASS generated local text cannot bypass remote verification; identical remote response fills the current grid');
  }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
