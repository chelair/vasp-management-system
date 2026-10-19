// Security/compatibility regression for the existing SSH configuration client.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {buildSync} = require('esbuild');
const output = buildSync({entryPoints:['src/api/ssh.ts'],bundle:true,write:false,platform:'node',format:'cjs'}).outputFiles[0].text;
const cache = new Map();
const requests = [];
const exportsObject = {};
const context = vm.createContext({module:{exports:exportsObject},exports:exportsObject,Headers,console,
  localStorage:{getItem:key=>cache.get(key)||null,setItem:(key,value)=>cache.set(key,value)},
  fetch:async(url,init)=>{
    requests.push({url,init});
    return {ok:true,status:200,json:async()=>({success:true,data:url.endsWith('/config')?
      {servers:[{name:'fixture',host:'mock',user:'mock',auth_type:'password',password_configured:true}]}:
      {latency_ms:1,user:'mock',host:'mock'}})};
  },
});
vm.runInContext(output,context);
const api=context.module.exports;
(async()=>{
  const {servers}=await api.fetchServerConfigs();
  assert.equal(servers[0].password,undefined);
  assert.equal(servers[0].passwordConfigured,true);
  assert.equal((await api.testRemoteConnection(servers[0])).ok,true,'saved password must still permit connection test');
  api.persistUICache([{...servers[0],password:'private-fixture'}]);
  assert(!cache.get('vasp.ssh.servers.v1').includes('private-fixture'));
  cache.set('vasp.ssh.servers.v1',JSON.stringify([{...servers[0],password:'old-private-fixture'}]));
  assert.equal(api.readUICache()[0].password,undefined,'legacy cache password must not re-enter app state');
  await api.syncServerConfigs(servers);
  const body=JSON.parse(requests.at(-1).init.body);
  assert.equal(body.servers[0].password,null,'missing password must preserve backend stored credential');
  console.log('PASS no credential cache/echo, saved-password connection compatibility');
})().catch(error=>{console.error(error);process.exitCode=1;});
