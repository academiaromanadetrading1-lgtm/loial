// Verify translations of dynamic wallet labels without changing customer data.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('join.html','utf8');
assert.ok(html.includes('<script src="/loial-wallet-ui-i18n.js"></script>'));
const source=fs.readFileSync('loial-wallet-ui-i18n.js','utf8');
const supported=['ro','en','de','fr','it','es','nl','pl','hu'];
function setup(lang){
 const listeners={};
 const elements=new Map();
 function element(selector,txt='',children=[]){
  const el={textContent:txt,childNodes:children};
  elements.set(selector,el);return el;
 }
 element('#tabBtnCard','Cardul curent');
 element('#tabBtnAmb','🤝 Ambasador');
 element('#panelInbox .pass-brand','PORTOFELUL MEU LOIAL');
 element('#panelInbox .pass-biz','Mesajele tale');
 element('#panelInbox .pass-reward','Oferte, ștampile și recompense, direct în Loial');
 element('#panelInbox .btn-save','↻ Actualizează mesajele');
 element('#panelInbox strong','Preferințe pentru oferte');
 element('.progress-header span:first-child','Progres la această afacere');
 const count={nodeType:1,textContent:'1'};
 const unread={nodeType:1,textContent:'(2)'};
 element('#tabBtnWallet','Portofel (1)',[{nodeType:3,textContent:'Portofel ('},count,{nodeType:3,textContent:')'}]);
 element('#tabBtnInbox','💬 Mesaje (2)',[{nodeType:3,textContent:'💬 Mesaje '},unread]);
 element('#progressText','1 / 6 ștampile');
 element('#holderLabel','Arată acest QR la casă');
 element('#premiumCustomerStatus','MEMBRU LOIAL');
 element('#pwaInstallBtn','Adaugă Loial pe telefon');
 let locale=lang;
 const context={
  window:{LoialLang:{get:()=>locale},matchMedia:()=>({matches:false})},
  navigator:{userAgent:'Mozilla iPhone'},
  document:{readyState:'loading',addEventListener(name,callback){listeners[name]=callback;},
    querySelector(selector){return elements.get(selector)||null;},
    getElementById(id){return elements.get('#'+id)||null;}}
 };
 vm.runInNewContext(source,context,{timeout:3000});
 function rerender(){listeners['loial:language']();}
 return {elements,count,unread,rerender,setLang(value){locale=value}};
}
for(const lang of supported){
 const {elements,count,unread,rerender}=setup(lang);
 rerender();
 assert.equal(count.textContent,'1','Wallet count must remain intact');
 assert.equal(unread.textContent,'(2)','Unread count must remain intact');
 assert.match(elements.get('#progressText').textContent,/^1 \/ 6 /);
 assert.ok(elements.get('#panelInbox .pass-biz').textContent.length>3);
 assert.ok(elements.get('#pwaInstallBtn').textContent.length>8);
}
const en=setup('en');en.rerender();
assert.equal(en.elements.get('#tabBtnCard').textContent,'Current card');
assert.equal(en.elements.get('#panelInbox .pass-biz').textContent,'Your messages');
assert.equal(en.elements.get('#progressText').textContent,'1 / 6 stamps');
assert.equal(en.elements.get('#pwaInstallBtn').textContent,'How to add LOIAL to iPhone home screen');
en.setLang('ro');en.rerender();
assert.equal(en.elements.get('#progressText').textContent,'1 / 6 ștampile');
assert.equal(en.elements.get('#tabBtnCard').textContent,'Cardul curent');
console.log('PASS: wallet progress, private inbox and iPhone installation labels translate in nine languages');
