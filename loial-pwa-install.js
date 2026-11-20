/* Loial PWA installation: native Android prompt + clear iOS home screen steps. */
(function () {
  'use strict';
  let installPrompt = null;
  const button = () => document.getElementById('pwaInstallBtn');
  const help = () => document.getElementById('pwaInstallHelp');
  const standalone = () => window.matchMedia('(display-mode: standalone)').matches ||
    window.navigator.standalone === true;
  const isiOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  function show() {
    const b=button(), t=help();
    if(!b || !t)return;
    if(standalone()){
      b.hidden=true;
      t.textContent='Loial este deja pe ecranul telefonului.';
      return;
    }
    b.hidden=false;
    b.textContent=(window.LoialLang?.t("Adaugă Loial pe ecranul telefonului") ?? "Adaugă Loial pe ecranul telefonului");
    if(isiOS){
      t.textContent='iPhone: deschide din Safari, apasă Partajare, apoi „Adaugă pe ecranul principal”. Alege „Deschide ca aplicație” dacă opțiunea apare.';
    }else if(installPrompt){
      t.textContent=(window.LoialLang?.t("Apasă butonul pentru a instala Loial ca aplicație, fără Google Wallet sau magazin de aplicații.") ?? "Apasă butonul pentru a instala Loial ca aplicație, fără Google Wallet sau magazin de aplicații.");
    }else{
      t.textContent='Android: folosește meniul browserului → „Instalează aplicația” sau „Adaugă la ecranul principal”.';
    }
  }
  window.addEventListener('beforeinstallprompt',event=>{
    event.preventDefault();
    installPrompt=event;
    show();
  });
  window.addEventListener('appinstalled',()=>{
    installPrompt=null;
    show();
  });
  document.addEventListener('DOMContentLoaded',()=>{
    show();
    const b=button();
    if(b)b.addEventListener('click',async()=>{
      if(standalone())return;
      if(installPrompt){
        const event=installPrompt;
        installPrompt=null;
        try{await event.prompt();await event.userChoice;}catch(e){}
      }else if(isiOS){
        const t=help();
        if(t)t.textContent='În Safari: Partajare (pătrat cu săgeată) → Adaugă pe ecranul principal → Adaugă. Deschide apoi pictograma Loial.';
      }else{
        const t=help();
        if(t)t.textContent='În Chrome: ⋮ → Instalează aplicația / Adaugă pe ecranul principal. Dacă nu apare, verifică folosirea HTTPS și deschide Loial într-o filă normală.';
      }
      show();
    });
    if('serviceWorker' in navigator && (location.protocol==='https:' ||
        location.hostname==='localhost' || location.hostname==='127.0.0.1')){
      navigator.serviceWorker.register('/sw.js',{scope:'/'})
        .catch(()=>{/* Browser does not support installation in this mode. */});
    }
  });
})();