// Portable PWA contract and browser installation behavior with no real customer data.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const manifest=JSON.parse(fs.readFileSync('manifest.json','utf8'));
assert.equal(manifest.lang,'en','Installed app must default to English');
assert.equal(manifest.display,'standalone');
assert.equal(manifest.scope,'/');
assert.ok(manifest.start_url.startsWith('/wallet'));
for(const size of ['192x192','512x512']){
  assert.ok(manifest.icons.some(icon=>icon.sizes===size));
}

function installHarness(userAgent, isStandalone=false) {
  const listeners={};
  const button={hidden:false,textContent:'',handler:null,
    addEventListener(event,callback){this.handler=callback;}};
  const help={textContent:''};
  const registered=[];
  const doc={
    addEventListener(name,callback){listeners['doc:'+name]=callback;},
    getElementById(id){return id==='pwaInstallBtn'?button:id==='pwaInstallHelp'?help:null;}
  };
  const context={
    document:doc,
    window:{
      matchMedia(){return {matches:isStandalone};},
      navigator:{standalone:false},
      addEventListener(name,callback){listeners['win:'+name]=callback;},
      LoialLang:{t(key){return key;}}
    },
    navigator:{userAgent,serviceWorker:{register(path,config){
      registered.push([path,config]);return Promise.resolve();
    }}},
    location:{protocol:'https:',hostname:'example.org'}
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('loial-pwa-install.js','utf8'),context,{timeout:3000});
  listeners['doc:DOMContentLoaded']();
  return {listeners,button,help,registered};
}

const apple=installHarness('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)');
assert.match(apple.help.textContent,/Safari/);
assert.equal(apple.registered.length,1);
apple.button.handler();
assert.match(apple.help.textContent,/Safari/);

const chrome=installHarness('Mozilla/5.0 (Linux; Android 14; Pixel) Chrome/130');
assert.match(chrome.help.textContent,/Android/);
let prompted=0;
chrome.listeners['win:beforeinstallprompt']({
  preventDefault(){},prompt:async()=>{prompted++},userChoice:Promise.resolve({outcome:'accepted'})
});
assert.match(chrome.help.textContent,/instala/i);
chrome.button.handler();
assert.equal(prompted,1,'Android must use native install prompt');
const installed=installHarness('Mozilla/5.0 (iPhone)',true);
assert.equal(installed.button.hidden,true,'Do not offer install when already in standalone mode');

// Exercise SW fetch handler: private routes must never be cached/intercepted.
const swListeners={};
const sw={
  URL,
  self:{
    location:{origin:'https://example.org'},
    addEventListener(name,callback){swListeners[name]=callback},
    skipWaiting(){return Promise.resolve()},
    clients:{claim(){return Promise.resolve()}}
  },
  caches:{open(){throw Error('Cache should not be consulted for private requests')}}
};
vm.createContext(sw);
vm.runInContext(fs.readFileSync('sw.js','utf8'),sw,{timeout:3000});
for(const path of ['/api/loial-inbox/me','/api/loial-winback/insights',
   '/auth/login','/wallet-recovery.html','/loial-receipt.html']){
  let intercepted=false;
  swListeners.fetch({request:{
    method:'GET',url:'https://example.org'+path,mode:'navigate',
    headers:{has(name){return false}}
  },respondWith(){intercepted=true;}});
  assert.equal(intercepted,false,'Do not intercept private path '+path);
}
console.log('PASS: PWA language, manifest, iOS/Android install instructions, native prompt and private cache bypass');
