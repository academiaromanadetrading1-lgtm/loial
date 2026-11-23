// Offline PWA must follow the persisted language, default to English,
// and never attempt to fetch or cache personal information.
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('loial-offline.html','utf8');
assert.match(html,/<html lang="en">/);
const script=html.match(/<script>([\s\S]*?)<\/script>/);
assert.ok(script,'Expected self-contained offline localization script');
const supported=['en','ro','es','de','fr','it','nl','pl','hu'];
function simulate(saved){
  const elements={};
  for(const id of ['offlineMessage','offlineRetry','offlinePrivacy'])elements[id]={textContent:''};
  const document={
    title:'',documentElement:{lang:'en'},
    getElementById(id){return elements[id]||null;}
  };
  const context={document,localStorage:{
    getItem(key){assert.equal(key,'loial_language');return saved;}
  }};
  vm.runInNewContext(script[1],context,{timeout:3000});
  return {document,elements};
}
for(const language of supported){
  const {document,elements}=simulate(language);
  assert.equal(document.documentElement.lang,language);
  for(const entry of [document.title,...Object.values(elements).map(x=>x.textContent)])
    assert.ok(entry.length>5,'All text must be translated: '+language);
}
const fallback=simulate('unknown');
assert.equal(fallback.document.documentElement.lang,'en');
assert.equal(fallback.elements.offlineRetry.textContent,'Try again');
assert.equal(simulate(null).elements.offlineRetry.textContent,'Try again');
assert.equal(simulate('ro').elements.offlineRetry.textContent,'Încearcă din nou');
assert.equal(simulate('es').elements.offlineRetry.textContent,'Reintentar');
assert.doesNotMatch(script[1],/\bfetch\s*\(|\bcaches\.|\bXMLHttpRequest\b/);
console.log('PASS: PWA offline page localizes all nine languages, defaults to English, makes no private requests');
