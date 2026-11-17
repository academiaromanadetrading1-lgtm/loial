# LOIAL — stadiul verificabil de pre-lansare (17.11.2026)

**Specificații active:** 67 EUR/lună fără TVA adăugat în prezent; Stripe Checkout pentru încasări și administrarea automată a accesului; 3 zile de remediere după eșecul plății; Wise Business exclusiv pentru transferul comisioanelor ambasadorilor. Card Black Metal PWA independent de Apple/Google Wallet.

**Comisioane:** 20 EUR direct + 10 EUR recrutorul direct, numai la prima plată verificată pentru firmă; reînnoiri de 5/10/15 EUR lunar pentru 1–25 / 26–50 / 51+ firme direct aduse și cu plata confirmată. Niciun alt nivel superior nu este remunerat.

**Fluxuri implementate în ramura de dezvoltare:** înscriere firmă și ambasador, atribuirea codurilor cu validare, dashboarduri separate, activitate periodic actualizată, export Excel, confirmare plăți Stripe prin webhook semnat, reînnoire și suspendare/relansare drepturi după plata confirmată, control al limitei gratuite de 50 de carduri, program de fidelizare, PWA, aplicație CRM și AI.

**Condiții încă necesare înainte de producție:** 
1. Testele automate pe ultimul commit să fie verzi.
2. Verificare autentificare și autorizare pe conturi independente, plus backup/restore DB și rotația oricăror credențiale istorice.
3. Validare instalare și folosire card PWA pe iPhone și Android reale.
4. Stripe LOIAL: cont distinct, Price ID EUR 67 lunar, chei și webhook în secret manager, tranzacție de probă cu evenimente/out-of-order/retry/cancel.
5. Confirmare fiscală și operațională pentru facturare fără TVA adăugat și reconciliere.
6. Deploy controlat al ramurii testate pe loial.space cu rollback; fără publicare automată și fără plăți reale inițiate de acest document.

**Status:** toate activitățile de cod pot fi pregătite fără contul Stripe. Stripe și testarea pe dispozitive reale sunt deliberat ultimele etape. Nu confunda trecerea testelor cu lansarea reală.

Document de referință pentru Stripe: [STRIPE_LOIAL_LAUNCH_67_EUR.md](STRIPE_LOIAL_LAUNCH_67_EUR.md).
