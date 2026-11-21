// Execute actual browser language module with a controlled, DOM-free harness.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('loial-i18n.js','utf8');

function boot(initialLanguage) {
  const storage = new Map();
  if(initialLanguage !== null) storage.set('loial_language',initialLanguage);
  const dispatched=[];
  const context = {
    localStorage: {
      getItem: key => storage.has(key) ? storage.get(key) : null,
      setItem: (key,value) => storage.set(key,value)
    },
    window: { addEventListener() {} },
    document: {
      readyState: 'loading',
      addEventListener() {},
      documentElement: { lang: '' },
      querySelectorAll() { return []; },
      dispatchEvent(event) { dispatched.push(event.type); }
    },
    CustomEvent: class CustomEvent { constructor(type) { this.type=type; } }
  };
  vm.createContext(context);
  vm.runInContext(source,context,{timeout:3000});
  return {lang:context.window.LoialLang,storage,dispatched,document:context.document};
}

const first=boot(null);
assert.equal(first.lang.get(),'en','New visitors must default to English');
assert.equal(first.lang.t('Salvează profilul'),'Save profile');
first.lang.set('es');
assert.equal(first.lang.get(),'es');
assert.equal(first.lang.t('Salvează profilul'),'Guardar perfil');
assert.equal(first.storage.get('loial_language'),'es');
assert.equal(first.document.documentElement.lang,'es');
assert.ok(first.dispatched.includes('loial:language'));
const repeat=boot('es');
assert.equal(repeat.lang.get(),'es','Saved language must survive navigation');
const invalid=boot('not-a-locale');
assert.equal(invalid.lang.get(),'en','Invalid preferences must safely fall back to English');
const supported=['ro','en','de','fr','it','es','nl','pl','hu'];
for(const locale of supported){
  repeat.lang.set(locale);
  assert.equal(repeat.lang.get(),locale);
  assert.ok(repeat.lang.t('Salvează profilul').trim(),locale+' translation missing');
}
console.log('PASS: English default, 9 languages, switching, persistence, invalid fallback');
