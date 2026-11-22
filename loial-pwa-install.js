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
      t.textContent=(window.LoialLang?.t("Loial este deja pe ecranul telefonului.") ?? "Loial is already on your home screen.");
      return;
    }
    b.hidden=false;
    b.textContent=(window.LoialLang?.t("Adaugă Loial pe ecranul telefonului") ?? "Add Loial to your home screen");
    if(isiOS){
      t.textContent=(window.LoialLang?.t("iPhone: deschide din Safari, apasă Partajare, apoi „Adaugă pe ecranul principal”. Alege „Deschide ca aplicație” dacă opțiunea apare.") ?? "iPhone: open in Safari, tap Share, then Add to Home Screen. Choose Open as Web App if available.");
    }else if(installPrompt){
      t.textContent=(window.LoialLang?.t("Apasă butonul pentru a instala Loial ca aplicație, fără Google Wallet sau magazin de aplicații.") ?? "Tap to install Loial as an app, without Google Wallet or an app store.");
    }else{
      t.textContent=(window.LoialLang?.t("Android: folosește meniul browserului → „Instalează aplicația” sau „Adaugă la ecranul principal”.") ?? "Android: use your browser menu to Install app or Add to Home screen.");
    }
  }
  document.addEventListener('loial:language',show);
  document.addEventListener('loial:ready',show);
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
      }
      // On browsers without a native prompt, show() already renders the
      // translated platform-specific instructions; do not replace them with
      // a hard-coded Romanian message on click.
      show();
    });
    if('serviceWorker' in navigator && (location.protocol==='https:' ||
        location.hostname==='localhost' || location.hostname==='127.0.0.1')){
      navigator.serviceWorker.register('/sw.js',{scope:'/'})
        .catch(()=>{/* Browser does not support installation in this mode. */});
    }
  });
})();