> **ARHIVAT — înlocuit la 17.11.2026.** Nu folosi instrucțiunile de încasare de mai jos. Regula curentă: **Stripe LOIAL încasează 67 EUR/lună**, confirmă automat abonamentul prin webhook; **Wise Business este exclusiv pentru plata comisioanelor ambasadorilor**. Document autoritativ: [STRIPE_LOIAL_LAUNCH_67_EUR.md](STRIPE_LOIAL_LAUNCH_67_EUR.md).

# LOIAL — Wise Business, sursa unică pentru încasări și comisioane
Data: 2026-11-17. Decizie de produs aprobată. Acest document nu activează transferuri.

## Model comercial
- Abonamentul firmei: EUR 65/lună, fără TVA.
- Prima încasare validată pentru firma nouă: EUR 20 ambasadorului direct și EUR 10 recrutorului direct al acelui ambasador.
- Nu există comision pentru simpla înscriere a unui ambasador și nici pentru strămoși mai îndepărtați.
- Din luna a doua, doar ambasadorul firmei încasează lunar EUR 5 (1–25 firme), EUR 10 (26–50) sau EUR 15 (51+), exclusiv pe baza firmelor cu abonamente efectiv achitate.
- O firmă nu poate produce multiple bonusuri de activare; rambursările și disputele suspendă/reversează comisioanele.

## Wise Business: încasări
- Sursa fondurilor: încasările din Wise Business LOIAL, prin link creat în interfața Wise sau transfer la detaliile bancare Wise.
- Referință unică LOIAL pentru fiecare factură (business_id, lună, sumă, monedă), cu reconciliere Wise independentă.
- Plata neconfirmată nu activează abonament și nu generează comisioane.
- API-ul Wise Business cu token personal nu oferă, în mod obișnuit, crearea linkurilor de plată sau interogarea extraselor pentru România. Nu presupunem că webhook-ul incoming-transfer#credited este disponibil în contul existent; accesul depinde de tipul integrării.
- Pentru pilot: verificare pe extras Wise de către administrator, păstrarea referinței tranzacției și a documentului justificativ înainte de marcarea încasării ca verificată. Automatizarea se poate activa doar dacă există acces documentat Wise pentru cont.

## Wise Business: comisioane
- LOIAL calculează drepturi de comision doar după validarea încasărilor; păstrează pending/approved/paid/reversed.
- Transferurile se pregătesc/efectuează exclusiv din Wise Business, în contul beneficiarului validat și pe baza documentelor necesare.
- Pentru conturile Wise Business din România, API-ul standard permite pregătirea transferurilor, dar nu finanțarea lor automată. Finalizarea transferului se face în Wise, iar LOIAL înregistrează transferul doar pe baza referinței Wise confirmate.
- Fără transferuri automate sau apeluri Wise live în pilot; fără acces la tokenuri sau IBAN-uri hardcodate în repository.

## Siguranță la implementare
1. Închidere fluxuri de simulare și Stripe legacy înainte de lansare.
2. Model dedicat receipt Wise cu reference ID unic, reconciliere, document justificativ, audit și idempotency.
3. Generarea comisioanelor doar din receipt verificat Wise (nu din marcaj de plată în frontend).
4. Payout Wise verificat + unicitate referință; nu se marchează paid la inițierea transferului.
5. Teste: plată nouă, a doua lună, duplicate, sume insuficiente, refund, nivel direct, calcul tier, administratori fără drepturi, concurență.

Surse: https://docs.wise.com/guides/product/partner/business-account-support ; https://docs.wise.com/guides/product/send-money/use-cases/payouts-smbs ; https://wise.com/help/articles/4qr3kkvIQlHNiD8BegEB4u/getting-paid-to-your-wise-business-by-payment-link
