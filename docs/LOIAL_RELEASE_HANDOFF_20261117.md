# LOIAL — raport de predare tehnică înainte de publicare
**Data:** 17 noiembrie 2026  
**Ramură:** `chatgpt/loial-ai-business-foundation-20261116`  
**Stare:** *Release candidate în GitHub, fără integrare sau deploy de producție.*

## Specificații active
- **LOIAL ProBusiness:** 67 EUR/lună, fără TVA adăugat în prezent; configurația fiscală finală trebuie verificată înainte de încasări.
- **Stripe**: încasare lunară și drepturi ProBusiness; numai webhook semnat și factură eligibilă pot activa accesul. Trei zile de remediere după neplată, apoi blocarea funcțiilor premium și limită de 50 de carduri pentru gratuit.
- **Wise Business**: numai virarea manuală a comisioanelor ambasadorilor după aprobare și dovada transferului.
- **Comisioane**: prima firmă plătitoare aduce 20 EUR ambasadorului direct și 10 EUR persoanei care l-a recrutat direct. Din a doua lună, exclusiv ambasadorul direct primește 5/10/15 EUR per firmă cu încasare verificată, la 1–25/26–50/51+ firme. Nu există comision pentru înscrierea unui ambasador sau două niveluri de uplines.
- **Card PWA Black Metal**: lansare independentă de Google Wallet/Apple Wallet.

## 1. Audit de securitate — verificări și modificări efectuate
- Ruta nesecurizată `/setup-admin` a fost dezactivată anterior și hotfix-ul a fost integrat în `main`.
- În ramura de dezvoltare: au fost retrase endpointurile istorice cu expunere globală a clienților, statisticilor, locațiilor, ștampilărilor fără PIN și notificărilor arbitrare.
- JWT-ul de conectare al firmei include ID-ul firmei; rolul trebuie să coincidă cu rolul utilizatorului real.
- Înscrierea firmei sau a ambasadorului refuză coduri de recomandare invalide, în loc să piardă atribuirea.
- Contul Wise al ambasadorului se poate modifica numai în contul propriu, cu parolă reconfirmată. Nu se returnează în API-ul privat datele financiare.
- Limitare de cereri la înscrieri/autentificări; comisioanele și datele firmelor sunt limitate la contul autentificat.
- Exportul Excel al administratorului evită formulele introduse de utilizatori. Fișierul conține date Wise personale și trebuie păstrat securizat.
- Nu s-a efectuat un audit extern independent, test de penetrare sau verificare de încărcare pe producție.

## 2. Comisioane — acoperire automată
- Primă plată verificată: 20 EUR direct + 10 EUR recrutor direct, fără uplines recursive.
- Reînnoiri lunare și praguri 5/10/15 EUR, inclusiv la 26 și 51 firme cu plăți eligibile.
- Identificatori unici de factură/transfer și evenimente Stripe; duplicatele nu adaugă comisioane.
- Disputele sau creditele țin în așteptare comisioanele neplătite. Recuperarea unor comisioane deja virate necesită revizuire manuală.
- Excel lunar disponibil doar administratorului: comisioane de plată, stare și destinații Wise.
- Nicio virare Wise și nicio plată Stripe reală nu a fost executată.

## 3. Interfețe — acoperire automată
- Dashboard administrator: firme, atribuiri, recrutări, încasări confirmate, comisioane, export Excel; actualizare automată cât timp pagina este vizibilă.
- Dashboard ambasador: autentificare, firme directe și firmele recruților direcți, referințe de plăți confirmate, comisioane pending/approved/paid și actualizarea detaliilor Wise.
- Pagini cu meta viewport și breakpoints responsive; verificări JavaScript în CI și verificări statice separate pentru UI.
- Verificarea vizuală efectivă în browsere mobile reale și de accesibilitate completă nu este încă certificată.

## 4. Fidelizare și PWA — acoperire automată
- Manifest standalone, iconuri Black Metal 192/512, service worker cu shell offline. API-urile și datele private ale portofelului nu sunt stocate în cache-ul public.
- Teste integrate pentru crearea cardului, recuperare cu token privat, scanare cu PIN, anti-duplicare, schimbare PIN, bon unic și puncte de recomandare.
- Limită 50 carduri fără abonament verificat prin înrolare QR, portofel universal și scanarea unui portofel dintr-o altă firmă.
- **Nevalidat fizic:** instalare PWA din Safari iOS / Chrome Android, permisiuni, scanarea camerei, comportament la actualizări și offline.

## 5. Pregătire pentru lansare
- Utilitar `loial_backup.py` cu copie SQLite online, integritate PRAGMA, destinație nouă fără suprascriere, permisiuni restrictive și test de restaurare pe fișier temporar.
- `loial_preflight.py` are verificări statice pentru medii, chei și configurarea Stripe și păstrează blocaje manuale pentru rotație secrete și backup real.
- Workflow-ul GitHub verifică sintaxa Python, JavaScript, manifestul, PWA și suita de teste pe o bază izolată.
- PR #1 rămâne **Draft**; conține modificări multiple și necesită revizuire finală față de `main` înainte de merge. Nu se face merge automat.

## Ultimele praguri înainte de GO LIVE
1. Ultimul commit trece CI; nicio regresie de securitate sau comisioane.
2. Backup **real** al bazei actuale de producție și probă de restore într-un mediu separat; păstrarea unei copii externe sigure.
3. Test pe două telefoane reale și în minimum două browsere mobile; capturi pentru card, QR, recompense, instalare și recuperare.
4. Cont Stripe **dedicat LOIAL** cu produs 67 EUR/lună, Price ID, secret key, semnătură webhook; teste integrale în modul TEST (achitare, eșec, grație, reluare, anulare, dispute).
5. Confirmare configurație fiscală/facturi, date legale, GDPR, documente pentru plățile Wise și persoanele responsabile.
6. Review PR și merge controlat după aprobarea lansării, verificare DNS/TLS, health-check, rotație chei și rollback pregătit.

**Interpretare:** verificările automate din CI sunt probe ale codului. Nu constituie dovezi privind funcționarea mediului de producție, testarea telefoanelor sau plata reală. Nu activa checkout-ul până când toate porțile obligatorii nu sunt verificate.

Vezi și `docs/STRIPE_LOIAL_LAUNCH_67_EUR.md`.
