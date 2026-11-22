/* Wallet UI translations: do not translate customer-supplied names, offers or messages. */
(function(){
'use strict';
const languages={
 en:['Current card','Wallet','Messages','Ambassador','Progress at this business','stamps','Show this QR at checkout','Loyal member','Reward available','My LOIAL Wallet','Your messages','Offers, stamps and rewards, directly in Loial','Refresh messages','Offer preferences','Show the QR to staff to earn a stamp','How to add LOIAL to iPhone home screen'],
 ro:['Cardul curent','Portofel','Mesaje','Ambasador','Progres la această afacere','ștampile','Arată acest QR la casă','Membru Loial','Recompensă disponibilă','Portofelul meu LOIAL','Mesajele tale','Oferte, ștampile și recompense, direct în Loial','Actualizează mesajele','Preferințe pentru oferte','Arată QR-ul angajatului pentru o ștampilă','Cum adaugi LOIAL pe ecranul iPhone'],
 de:['Aktuelle Karte','Wallet','Nachrichten','Botschafter','Fortschritt bei diesem Unternehmen','Stempel','Zeige diesen QR-Code an der Kasse','Treues Mitglied','Prämie verfügbar','Meine LOIAL Wallet','Deine Nachrichten','Angebote, Stempel und Prämien direkt in Loial','Nachrichten aktualisieren','Angebotseinstellungen','QR-Code an der Kasse vorzeigen','LOIAL zum iPhone-Startbildschirm hinzufügen'],
 fr:['Carte actuelle','Portefeuille','Messages','Ambassadeur','Progression dans cet établissement','tampons','Présentez ce QR code en caisse','Membre fidèle','Récompense disponible','Mon portefeuille LOIAL','Vos messages','Offres, tampons et récompenses dans Loial','Actualiser les messages','Préférences des offres','Présentez le QR code en caisse','Ajouter LOIAL à l’écran d’accueil de l’iPhone'],
 it:['Carta attuale','Portafoglio','Messaggi','Ambasciatore','Progressi presso questa attività','timbri','Mostra questo QR alla cassa','Membro fedele','Premio disponibile','Il mio portafoglio LOIAL','I tuoi messaggi','Offerte, timbri e premi direttamente su Loial','Aggiorna messaggi','Preferenze offerte','Mostra il QR alla cassa','Aggiungi LOIAL alla schermata Home di iPhone'],
 es:['Tarjeta actual','Cartera','Mensajes','Embajador','Progreso en este negocio','sellos','Muestra este QR en caja','Miembro fiel','Recompensa disponible','Mi cartera LOIAL','Tus mensajes','Ofertas, sellos y recompensas directamente en Loial','Actualizar mensajes','Preferencias de ofertas','Muestra el QR en caja','Añadir LOIAL a la pantalla de inicio del iPhone'],
 nl:['Huidige kaart','Portemonnee','Berichten','Ambassadeur','Voortgang bij dit bedrijf','stempels','Toon deze QR-code bij de kassa','Trouw lid','Beloning beschikbaar','Mijn LOIAL-portemonnee','Je berichten','Aanbiedingen, stempels en beloningen in Loial','Berichten vernieuwen','Aanbiedingsvoorkeuren','Toon de QR-code bij de kassa','LOIAL toevoegen aan iPhone-beginscherm'],
 pl:['Bieżąca karta','Portfel','Wiadomości','Ambasador','Postęp w tej firmie','pieczątki','Pokaż kod QR przy kasie','Lojalny klient','Nagroda dostępna','Mój portfel LOIAL','Twoje wiadomości','Oferty, pieczątki i nagrody w Loial','Odśwież wiadomości','Preferencje ofert','Pokaż kod QR przy kasie','Dodaj LOIAL do ekranu głównego iPhone’a'],
 hu:['Aktuális kártya','Tárca','Üzenetek','Nagykövet','Haladás ennél a vállalkozásnál','pecsét','Mutasd meg a QR-kódot a pénztárnál','Hűséges tag','Jutalom elérhető','LOIAL tárcám','Üzeneteid','Ajánlatok, pecsétek és jutalmak a Loialban','Üzenetek frissítése','Ajánlatbeállítások','Mutasd meg a QR-kódot a pénztárnál','LOIAL hozzáadása az iPhone kezdőképernyőjéhez']
};
const original={
 '#tabBtnCard':0,
 '#tabBtnAmb':3,
 '#panelInbox .pass-brand':9,
 '#panelInbox .pass-biz':10,
 '#panelInbox .pass-reward':11,
 '#panelInbox .btn-save':12,
 '#panelInbox strong':13,
 '.progress-header span:first-child':4
};
function label(id,txt){const el=document.querySelector(id);if(el)el.textContent=txt;}
function prefix(id,text){const el=document.querySelector(id);if(!el)return;
 const node=Array.from(el.childNodes).find(n=>n.nodeType===3);
 if(node)node.textContent=text+' '; // Preserve unread and card count spans.
}
function apply(){
 const locale=window.LoialLang?.get?.()||'en';
 const t=languages[locale]||languages.en;
 for(const [selector,index] of Object.entries(original))label(selector,t[index]);
 prefix('#tabBtnWallet',t[1]+' (');
 // Closing bracket lives in a separate text node; leave counter untouched.
 prefix('#tabBtnInbox','💬 '+t[2]);
 const progress=document.querySelector('#progressText');
 if(progress){
   const match=progress.textContent.match(/(\d+)\s*\/\s*(\d+)/);
   if(match)progress.textContent=match[1]+' / '+match[2]+' '+t[5];
 }
 const hint=document.querySelector('#holderLabel');
 if(hint&&hint.textContent.trim().match(/^(Arată acest QR|Show this QR|Zeige diesen QR|Présentez ce QR|Mostra questo QR|Muestra este QR|Toon deze QR|Pokaż kod QR|Mutasd meg a QR)/))hint.textContent=t[6];
 const status=document.querySelector('#premiumCustomerStatus');
 if(status&&/^(MEMBRU LOIAL|RECOMPENSĂ DISPONIBILĂ|Loyal member|Reward available)$/i.test(status.textContent.trim())){
   status.textContent=/RECOMPENSĂ|Reward available/i.test(status.textContent)?t[8]:t[7];
 }
 const b=document.getElementById('pwaInstallBtn');
 if(b && /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.matchMedia('(display-mode: standalone)').matches){
   b.textContent=t[15];
 }
}
window.LoialWalletLanguage={apply,languages};
document.addEventListener('loial:language',apply);
document.addEventListener('loial:ready',apply);
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',apply);else apply();
})();
