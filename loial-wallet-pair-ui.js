/* Pair the private, already enrolled wallet between browser storage partitions.
 * Never use the public QR as proof of ownership and never put the private token in a URL.
 */
(function(){
'use strict';
const el=id=>document.getElementById(id);
function translate(ro,en){return (window.LoialLang?.get?.()||'en')==='ro'?ro:en;}
function info(message,isError=false){
  const node=el('pairFeedback');if(!node)return;
  node.textContent=message;node.style.color=isError?'#ac392b':'#246344';
}
function ready(){
  const section=el('devicePairPanel');if(!section)return;
  const input=el('pairCode');
  const issue=el('pairIssue');
  const code=el('pairIssuedCode');
  const redeem=el('pairRedeem');
  const wallet=localStorage.getItem('loial_universal_uuid')||'';
  const token=localStorage.getItem('loial_wallet_inbox_token')||'';
  issue.hidden=!(wallet&&token);
  el('pairExistingWallet').hidden=!(wallet&&token);
  issue.onclick=async()=>{
    issue.disabled=true;
    code.value='';
    info(translate('Se generează codul temporar…','Generating a temporary code…'));
    try{
      const response=await fetch('/api/loial-wallet-pair/issue',{
        method:'POST',
        headers:{'X-Loial-Wallet-Id':wallet,'X-Loial-Wallet-Token':token},
        cache:'no-store'
      });
      const data=await response.json();
      if(!response.ok)throw Error(data.detail||'Could not generate pairing code');
      code.value=data.pairing_code;
      el('pairCodeBox').hidden=false;
      info(translate('Copiază codul și introdu-l în LOIAL instalat. Valabil 10 minute, o singură utilizare.',
        'Copy this code into the installed LOIAL app. Valid for 10 minutes, one use.'));
    }catch(error){info(error.message,true)}
    finally{issue.disabled=false}
  };
  el('pairCopy').onclick=async()=>{
    try{
      await navigator.clipboard.writeText(code.value);
      info(translate('Cod copiat. Deschide aplicația LOIAL și lipește-l în câmpul de asociere.',
                     'Code copied. Open the LOIAL app and paste it into the pairing field.'));
    }catch(e){
      code.focus();code.select();
      info(translate('Selectează și copiază manual codul.','Select and copy the code manually.'));
    }
  };
  redeem.onclick=async()=>{
    const value=input.value.trim();
    if(!/^[A-Za-z0-9_-]{40,160}$/.test(value)){
      info(translate('Introdu codul complet primit din browserul cardului original.',
                     'Enter the complete code from the original wallet browser.'),true);
      return;
    }
    const current=localStorage.getItem('loial_universal_uuid');
    if(current&&localStorage.getItem('loial_wallet_inbox_token')){
      const ok=confirm(translate('Pe acest dispozitiv există deja un alt portofel. Asocierea va înlocui portofelul activ pe acest dispozitiv. Continui?',
          'Another wallet is already stored here. Pairing will replace the active wallet on this device. Continue?'));
      if(!ok)return;
    }
    redeem.disabled=true;
    info(translate('Se verifică asocierea…','Verifying wallet pairing…'));
    try{
      const response=await fetch('/api/loial-wallet-pair/claim',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({code:value}),cache:'no-store'
      });
      const data=await response.json();
      if(!response.ok)throw Error(data.detail||'Pairing failed');
      if(!/^W-[A-Za-z0-9_-]{17,117}$/.test(data.wallet_uuid)||typeof data.private_token!=='string'||data.private_token.length<40)
        throw Error('Invalid wallet response');
      localStorage.setItem('loial_universal_uuid',data.wallet_uuid);
      localStorage.setItem('loial_wallet_inbox_token',data.private_token);
      // An earlier card belonging to the other browser must never be presented
      // as the newly paired customer's identity on this device.
      localStorage.removeItem('loial_universal_profile');
      input.value='';
      info(translate('Card asociat. Se reîncarcă portofelul…','Wallet paired. Reloading…'));
      location.replace('/wallet?source=paired');
    }catch(error){info(error.message,true);redeem.disabled=false}
  };
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready);else ready();
})();
