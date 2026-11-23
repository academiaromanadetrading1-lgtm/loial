// Simulate the actual Service Worker lifecycle and offline fetch behavior.
// No browser, network or private data is accessed.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

async function check() {
  const events = {};
  const cacheData = new Map();
  const cacheNames = new Map([['loial-stale-v1',new Map()],['other-site-cache',new Map()]]);
  const writes=[];
  const responses = {
    '/loial-offline.html': {kind:'offline-public'},
    '/pwa-icon-192.png': {kind:'icon192'},
    '/pwa-icon-512.png': {kind:'icon512'}
  };
  let online=true;
  let fetchCalls=[];
  const fakeCache = name => ({
    async addAll(paths) {
      for (const path of paths) {
        assert.ok(Object.hasOwn(responses,path), 'Only public offline assets pre-cached');
        cacheData.set(path,responses[path]);
        writes.push(path);
      }
    },
    async match(path) { return cacheData.get(path) || null; }
  });
  const sandbox={
    URL,
    self:{
      location:{origin:'https://loial.test'},
      addEventListener(name,handler){events[name]=handler;},
      skipWaiting:async()=>{},
      clients:{claim:async()=>{}}
    },
    caches:{
      async open(name){cacheNames.set(name,cacheData); return fakeCache(name);},
      async keys(){return [...cacheNames.keys()];},
      async delete(name){return cacheNames.delete(name);}
    },
    async fetch(request,opts){
      fetchCalls.push({url:request.url,opts});
      if(!online) throw Error('offline');
      return {kind:'network',url:request.url};
    }
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync('sw.js','utf8'),sandbox,{timeout:3000});
  async function lifecycle(name) {
    let task;
    events[name]({waitUntil(value){task=value;}});
    await task;
  }
  await lifecycle('install');
  assert.deepEqual([...cacheData.keys()].sort(),Object.keys(responses).sort());
  await lifecycle('activate');
  assert.equal(cacheNames.has('loial-stale-v1'),false,'Remove old Loial caches');
  assert.equal(cacheNames.has('other-site-cache'),true,'Preserve caches of unrelated apps');

  function request(path, mode='navigate', headers={},method='GET') {
    const raw={url:'https://loial.test'+path,mode,method,
      headers:{has(key){return Object.keys(headers).some(x=>x.toLowerCase()===key.toLowerCase());}}};
    let handled=false,task;
    events.fetch({request:raw,respondWith(response){handled=true;task=response;}});
    return {handled,read:()=>task};
  }
  online=false;
  for(const path of ['/wallet?tab=cards','/join/10','/scan.html']) {
    const result=request(path);
    assert.equal(result.handled,true,'Navigation uses public offline fallback');
    assert.deepEqual(await result.read(),responses['/loial-offline.html']);
  }
  // Private endpoints must never be served from caches, even while offline.
  for(const path of ['/api/loial-inbox/me','/api/loial-receipts/preview?token=secret',
    '/gdpr/export','/wallet-recovery.html','/wallet-profile/123',
    '/loial-receipt.html?token=secret','/auth/login']) {
    assert.equal(request(path).handled,false,'Private route must bypass SW: '+path);
  }
  assert.equal(request('/wallet', 'navigate',{'X-Loial-Wallet-Token':'secret'}).handled,false);
  assert.equal(request('/platform.html','navigate',{'Authorization':'Bearer secret'}).handled,false);
  assert.equal(request('/wallet','navigate',{},'POST').handled,false);
  const asset=request('/pwa-icon-192.png','no-cors');
  assert.equal(asset.handled,true);
  assert.deepEqual(await asset.read(),responses['/pwa-icon-192.png']);
  const before=fetchCalls.length;
  assert.equal(request('/wallet?tab=inbox','navigate').handled,true);
  assert.deepEqual(await request('/wallet?tab=inbox','navigate').read(),responses['/loial-offline.html']);
  assert.ok(fetchCalls.slice(before).every(x=>x.opts?.cache==='no-store'));
  assert.deepEqual(writes.sort(),Object.keys(responses).sort(),'Never write customer pages or API to cache');
  console.log('PASS: public offline shell, private request bypass, no-store navigation, safe cache cleanup');
}
check().catch(error=>{console.error(error);process.exitCode=1;});
