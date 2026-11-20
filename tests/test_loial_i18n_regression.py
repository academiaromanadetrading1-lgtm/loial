"""Offline regression for locale handling; no external services or credentials."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def test_locale_switching_preserves_data_and_form_values():
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const code = fs.readFileSync('loial-i18n.js', 'utf8');
const prefs = new Map();
function element(text, tagName='SPAN', excluded=false) {
  return {children:[], textContent:text, tagName,
    closest:()=>excluded ? {} : null,
    hasAttribute:()=>false,
    get value(){return this._value ?? this.textContent},
    set value(v){this._value=v}
  };
}
function boot(){
  const nodes=[element('Salvează profilul'), element('Carduri','OPTION'),
    element('Cont','SPAN',true), element('private customer value')];
  const placeholder={placeholder:'Scrie întrebarea ta...',dataset:{}};
  const document={readyState:'loading',documentElement:{},addEventListener(){},
    dispatchEvent(){},querySelectorAll(q){
      return q.startsWith('h1') ? nodes : q.startsWith('input') ? [placeholder] : [];
    }};
  const window={addEventListener(){}};
  vm.runInNewContext(code,{document,window,localStorage:{
    getItem:k=>prefs.get(k),setItem:(k,v)=>prefs.set(k,v)
  },CustomEvent:function(){}});
  return {document,nodes,placeholder,lang:window.LoialLang};
}
let state=boot();
assert.equal(state.lang.get(),'en');
const langs=['en','de','fr','it','es','nl','pl','hu','ro'];
for(const lang of langs){
  state.lang.set(lang);
  assert.equal(state.document.documentElement.lang,lang);
  assert.equal(state.nodes[0].textContent,state.lang.t('Salvează profilul'));
  assert.equal(state.nodes[1].value,'Carduri');
  assert.equal(state.nodes[2].textContent,'Cont');
  assert.equal(state.nodes[3].textContent,'private customer value');
  assert.equal(state.placeholder.placeholder,state.lang.t('Scrie întrebarea ta...'));
  assert.equal(prefs.get('loial_language'),lang);
}
state.lang.set('es');
state=boot();
assert.equal(state.lang.get(),'es');
state.lang.apply();
assert.equal(state.nodes[0].textContent,'Guardar perfil');
state.lang.set('unsupported');
assert.equal(state.lang.get(),'es');
const metric=element('');
state.nodes.push(metric);
const key='Firme: {count} · Ștampile: {stamps}';
const values={count:0,stamps:12};
state.lang.bindText(metric,key,values);
values.count=999;
for(const lang of langs){
  state.lang.set(lang);
  assert.equal(metric.textContent,state.lang.format(key,{count:0,stamps:12}));
  assert.ok(metric.textContent.includes('12'));
  assert.ok(!metric.textContent.includes('999'));
}
metric.textContent='new private value';
state.lang.set('en');
assert.equal(metric.textContent,'new private value');
const malicious='<img src=x onerror=alert(1)>';
state.lang.bindText(metric,'Cardul tău de la {business}',{business:malicious});
assert.equal(metric.textContent,'Your card from '+malicious);
metric.isConnected=false;
state.lang.set('ro');
assert.equal(metric.textContent,'Your card from '+malicious);

const homepage=fs.readFileSync('index.html','utf8');
const neutral=new Set(['loial.space','RO','EN','DE','FR','IT','ES','NL','PL','HU','QR','0 EUR','LOIAL BUSINESS','Business','67 EUR','ProBusiness*','270 EUR','LOIAL.SPACE','FAQ']);
const body=homepage.slice(homepage.indexOf('<body')).replace(/<script\b[\s\S]*?<\/script>/gi,'').replace(/<style\b[\s\S]*?<\/style>/gi,'').replace(/<svg\b[\s\S]*?<\/svg>/gi,'');
const labels=[...new Set([...body.matchAll(/>([^<>]+)</g)].map(m=>m[1].trim()).filter(s=>/\p{L}/u.test(s)&&!neutral.has(s)))];
for(const label of labels){
  state.lang.set('en');const en=state.lang.t(label);
  assert.ok(en!==label||langs.some(l=>{state.lang.set(l);return state.lang.t(label)!==label;}), 'Missing homepage translation: '+label);
}
for(const lang of langs){
  state.lang.set(lang);
  const line=state.lang.format('{reserved} / 500 locuri rezervate · {remaining} disponibile',{reserved:12,remaining:488});
  assert.ok(line.includes('12')&&line.includes('488')&&!line.includes('{'));
  assert.ok(state.lang.t('Ai o metodă de recuperare a cardului? Ieșirea elimină accesul local de pe acest dispozitiv.').length>20);
}
const sections=['<span>Clienții revin.</span>','<span>Până la</span>','<span>cu PIN individual de 4 cifre</span>','id="previewName" data-no-translate','id="previewReward" data-no-translate'];
for(const marker of sections)assert.ok(homepage.includes(marker),marker);


const publicFlows=['register.html','loial-wallet.html'];
for(const filename of publicFlows){
  const source=fs.readFileSync(filename,'utf8');
  const visible=source.slice(source.indexOf('<body'))
    .replace(/<script\b[\s\S]*?<\/script>/gi,'')
    .replace(/<svg\b[\s\S]*?<\/svg>/gi,'');
  const labels=[...new Set([...visible.matchAll(/>([^<>]+)</g)]
    .map(m=>m[1].trim()).filter(s=>/[ăâîșțĂÂÎȘȚ]/.test(s)))];
  for(const label of labels){
    state.lang.set('en');
    assert.notEqual(state.lang.t(label),label, filename+': '+label);
  }
}
const register=fs.readFileSync('register.html','utf8');
const wallet=fs.readFileSync('loial-wallet.html','utf8');
assert.ok(register.includes('rewardEdited'));
assert.ok(register.includes("document.addEventListener('loial:language',localizeRewardDefault)"));
assert.ok(wallet.includes('<span>Accept regulile programului prezentate'));

"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_ambassador_simulator_language_and_amounts():
    script = r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const html=fs.readFileSync('ambasador.html','utf8');
const localization=fs.readFileSync('loial-i18n.js','utf8');
const rows=Function('return '+localization.slice(localization.indexOf('(function(){'),localization.indexOf('const dictionary='))+'return rows;})();')();
const dictionary=new Map(rows.map(x=>[x[0],x]));
const langs=['ro','en','de','fr','it','es','nl','pl','hu'];
const script=html.slice(html.indexOf('  function updateCalc()'),html.indexOf('  // The dashboard only displays authenticated'));
assert.ok(script.startsWith('  function updateCalc()'));
for(const n of [1,20,26,50,51,80])for(const lang of langs){
  const rate=n>=51?15:n>=26?10:5;
  const elements={bizSlider:{value:String(n)}};
  for(const id of ['calcCountLabel','calcRankLabel','calcMonth1','calcRecurring'])elements[id]={textContent:''};
  const t=k=>dictionary.get(k)?.[langs.indexOf(lang)]||k;
  const window={LoialLang:{t,format:(k,v)=>t(k).replace(/\{(\w+)\}/g,(_,name)=>String(v[name])),bindText:(el,k,v)=>{el.textContent=t(k).replace(/\{(\w+)\}/g,(_,name)=>String(v[name]));}}};
  const events={};
  const document={getElementById:id=>elements[id],addEventListener:(type,cb)=>events[type]=cb};
  new Function('document','window',script)(document,window);
  assert.ok(elements.calcCountLabel.textContent.includes(String(n)));
  assert.ok(elements.calcRecurring.textContent.includes(String(n*rate)));
  assert.equal(elements.calcMonth1.textContent,String(n*20)+' EUR');
  assert.ok(elements.calcRankLabel.textContent.length>10);
  assert.equal(typeof events['loial:language'],'function');
  events['loial:language']();
  assert.ok(elements.calcRecurring.textContent.includes(String(n*rate)));
}
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_public_account_and_ambassador_static_locale_coverage():
    script = r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const script=fs.readFileSync('loial-i18n.js','utf8');
const rows=Function('return '+script.slice(script.indexOf('(function(){'),script.indexOf('const dictionary='))+'return rows;})();')();
const keys=new Set(rows.map(row=>row[0]));
const checked=['ambasador.html','register.html','loial-wallet.html','login.html','wallet-recovery.html','platform.html','loial-ai.html'];
for(const filename of checked){
  const source=fs.readFileSync(filename,'utf8');
  const clean=source.slice(source.indexOf('<body'))
    .replace(/<script\b[\s\S]*?<\/script>/gi,'')
    .replace(/<style\b[\s\S]*?<\/style>/gi,'')
    .replace(/<svg\b[\s\S]*?<\/svg>/gi,'');
  const missing=[...new Set([...clean.matchAll(/>([^<>]+)</g)]
    .map(m=>m[1].trim())
    .filter(s=>/[ăâîșțĂÂÎȘȚ]/.test(s)&&!keys.has(s)))];
  assert.deepEqual(missing,[],filename+' missing translations');
}
assert.equal(rows.length,new Set(rows.map(r=>r[0])).size,'Duplicate translation keys');
for(const row of rows)assert.equal(row.length,9,'Incomplete locale row: '+row[0]);
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_accessibility_attribute_translation_and_locale_switching():
    script = r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const js=fs.readFileSync('loial-i18n.js','utf8');
const attrs={'aria-label':'Cardurile mele',title:'Cardurile mele',alt:'Cardurile mele'};
const element={closest:()=>null,hasAttribute:key=>Object.hasOwn(attrs,key),
  getAttribute:key=>attrs[key],setAttribute:(key,value)=>{attrs[key]=value;}};
const document={readyState:'loading',documentElement:{},
  addEventListener(){},dispatchEvent(){},
  querySelectorAll:selector=>selector.startsWith('[aria-label]')?[element]:[]};
const window={addEventListener(){}};
const localStorage={getItem:()=>null,setItem(){}};
new Function('document','window','localStorage','CustomEvent',js)(document,window,localStorage,function(){});
for(const lang of ['en','ro','de','fr','it','es','nl','pl','hu']){
  window.LoialLang.set(lang);
  const expected=window.LoialLang.t('Cardurile mele');
  for(const attribute of ['aria-label','title','alt'])assert.equal(attrs[attribute],expected);
}
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_dynamic_security_and_payment_status_locales():
    script = r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const code=fs.readFileSync('loial-i18n.js','utf8');
const rows=Function('return '+code.slice(code.indexOf('(function(){'),code.indexOf('const dictionary='))+'return rows;})();')();
const dict=new Map(rows.map(x=>[x[0],x]));
const langs=['ro','en','de','fr','it','es','nl','pl','hu'];
const routes=['platform.html','loial-ai.html','ambasador.html'];
let matched=0;
for(const filename of routes){
  const html=fs.readFileSync(filename,'utf8');
  for(const match of html.matchAll(/window\.LoialLang\?\.t\('([^']+)'\) \?\? '([^']+)'/g)){
    assert.equal(match[1],match[2],filename+' fallback differs');
    const translations=dict.get(match[1]);
    assert.ok(translations,filename+' missing translation: '+match[1]);
    assert.equal(translations.length,9,filename+' incomplete translation: '+match[1]);
    for(const locale of langs)assert.ok(translations[langs.indexOf(locale)].trim().length>0);
    matched++;
  }
}
assert.ok(matched>=13,'Dynamic security/payment statuses missing');
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_dynamic_variable_translations_and_runtime_links():
    script = r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const script=fs.readFileSync('loial-i18n.js','utf8');
const data=Function('return '+script.slice(script.indexOf('(function(){'),script.indexOf('const dictionary='))+'return rows;})();')();
const dictionary=new Map(data.map(x=>[x[0],x]));
const languages=['ro','en','de','fr','it','es','nl','pl','hu'];
const cases=[
  ['Colectează {count} ștampile și primești premiul!',{count:6}],
  ['Locație #{id}',{id:15}],
  ['Vânzări înregistrate: {amount}',{amount:'500 EUR'}],
  ['În așteptare: {pending} EUR | Aprobat: {approved} EUR | Achitat: {paid} EUR',{pending:'12.00',approved:'8.00',paid:'5.00'}],
  ['Ambasadori recrutați direct: {count}',{count:7}],
  ['Recomandări validate: {qualified} · În așteptare: {pending} · Puncte pilot: {points}',{qualified:4,pending:2,points:16}]
];
for(const [key,values] of cases){
  const translations=dictionary.get(key);
  assert.ok(translations,'Missing dynamic template '+key);
  for(const [index,lang] of languages.entries()){
    const text=translations[index].replace(/\{([a-zA-Z]\w*)\}/g,(_,name)=>String(values[name]));
    for(const value of Object.values(values))assert.ok(text.includes(String(value)),lang+': '+key);
    assert.ok(!/\{[a-zA-Z]\w*\}/.test(text),lang+': unresolved template '+key);
  }
}
const merchant=fs.readFileSync('platform.html','utf8');
const ambassador=fs.readFileSync('ambasador.html','utf8');
const wallet=fs.readFileSync('loial-wallet.html','utf8');
for(const key of cases.slice(0,3).map(x=>x[0]))assert.ok(merchant.includes("LoialLang?.format('"+key+"'"),'Merchant missing formatting: '+key);
for(const key of cases.slice(3,5).map(x=>x[0]))assert.ok(ambassador.includes("LoialLang?.format('"+key+"'"),'Ambassador missing formatting: '+key);
assert.ok(wallet.includes("LoialLang?.format('"+cases[5][0]+"'"),'Wallet missing formatting');
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_ai_and_merchant_dynamic_ui_no_raw_critical_messages():
    script = r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const dict=fs.readFileSync('loial-i18n.js','utf8');
const rows=Function('return '+dict.slice(dict.indexOf('(function(){'),dict.indexOf('const dictionary='))+'return rows;})();')();
const lookup=new Map(rows.map(row=>[row[0],row]));
const paths=['platform.html','loial-ai.html','ambasador.html','loial-wallet.html'];
let translated=0,templated=0;
for(const filename of paths){
  const html=fs.readFileSync(filename,'utf8');
  for(const match of html.matchAll(/LoialLang\?\.t\('([^']+)'\) \?\? '([^']+)'/g)){
    assert.equal(match[1],match[2],filename+' has inconsistent fallback');
    assert.ok(lookup.has(match[1]),filename+' lacks dictionary key '+match[1]);
    translated++;
  }
  for(const match of html.matchAll(/LoialLang\?\.format\('([^']+)'/g)){
    assert.ok(lookup.has(match[1]),filename+' lacks format key '+match[1]);
    templated++;
  }
}
assert.ok(translated>=30,'Expected explicit runtime translation coverage');
assert.ok(templated>=8,'Expected dynamic templates');
const ai=fs.readFileSync('loial-ai.html','utf8');
assert.ok(ai.includes("LoialLang?.format('Ultima solicitare săptămânală: {date}. Vezi mesajul din conversație.'"));
assert.ok(ai.includes("LoialLang?.t('Format: Produs;Cantitate;Preț unitar;Cost variabil (opțional)'"));
assert.ok(ai.includes("LoialLang?.t('Indicator agregat declarat."));
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
