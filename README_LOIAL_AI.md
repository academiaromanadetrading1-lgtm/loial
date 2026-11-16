# Loial AI Business — arhitectură și stadiu

## Obiectiv comercial
Loial este un consultant managerial conversațional prin chat exclusiv text și documente atașate.
Pachetul Business este gândit pentru 65 EUR/lună + TVA, cu AI inclus.
Nu trimite SMS/WhatsApp: eventualii furnizori sunt contractați separat de firma client.
Sistemul este multi-industrie; nu presupune că orice antreprenor vinde produse în magazin.

## Profiluri incluse
- Uber / Bolt / taxi / rideshare: curse, ore online, km, comisioane, cost energie, rezultat per tură
- Atelier / service auto: ore de manoperă, piese, grad utilizare, lucrări în garanție
- Spălătorie self-wash: boxe, cicluri, energie/apă/chimicale, indisponibilitate
- Patiserie, restaurant, retail, salon, ecommerce
- General: administratorul descrie în propriile cuvinte orice altă activitate

Administrarea profilului și setul de întrebări sunt independente de baza codului QR.

## Implementat pe ramura de lucru
- Interfață separată /loial-ai.html, legătură din dashboardul firmelor (fără redesenare)
- 8 butoane de analiză și chat exclusiv text cu istoric persistent, izolat pe firmă
- Profil de industrie, descriere adaptabilă, solicitări documente și prompt săptămânal în UI
- Încărcare CSV, XLSX, PDF cu text, fotografii (prin model multimodal configurat)
- Previzualizare și confirmare explicită înainte de includerea vânzărilor în rapoarte
- Fără stocarea fotografiilor/documentelor brute: sunt reținute metadatele și extragerile
- Raport de contribuție (doar când costurile variabile sunt disponibile), analiza ABC
- Indicatori pentru rideshare, service auto și self-wash, baza extinsă pentru alte industrii
- Segmente de inactivitate, director de clienți, produse cumpărate pe baza ID-urilor de client din export
- Șabloane bun venit, mulțumire, revenire, ștampile, recompensă, oferte
- Proiecte de campanie, aprobări fără expediere, audiențe cu consimțământ de email
- Export CSV clienți, vânzări, identificatori publicitari cu acord explicit
- Router AI nou cu Bearer JWT și acces strict la firma autentificată
- Endpointurile vechi /api/biz-full și /api/admin sunt protejate în această ramură;
  fluxul join/scan citește doar configurația publică necesară
- Buget AI per firmă/lună și model mai puternic opțional dacă prețurile sunt configurate
- Reguli manageriale interne pentru costuri, marje, stocuri și diferențierea profitului de venituri

## Nu este încă livrat end-to-end
- Nu s-a efectuat încă un deploy real și nu a fost validat cu baza de producție.
- Nu există trimitere reală de email; campaniile sunt doar proiecte și previzualizări.
- Nu există încă sincronizare POS, QR de tranzacție fiscală sau integrare în contabilitate.
- Pentru fotografii este necesară cheia AI + tarifele API configurate.
- PDF-urile text sunt extrase și folosite ca informație neconfirmată; PDF-urile scanate
  fără text nu pot fi procesate automat dacă modelul multimodal nu este configurat.
- Nu există cron / notificare push în afara platformei: solicitarea săptămânală apare la
  accesarea paginii și la cererea administratorului.
- Nu sunt activate încă emailurile automate la evenimentele de ștampilă.
- Nu este implementată încă sincronizarea automată a audiențelor Meta/Google.
- Bibliotecă managerială de reguli inclusă; recuperarea semantică din cursuri academice (RAG)
  necesită documente verificate, drepturi de utilizare și o etapă de indexare.
- Nu au fost executate teste GitHub Actions sau teste cu conturi reale.

## Condiții obligatorii înainte de merge / deploy
1. Înlocuiește toate cheile istorice publicate în .env (Wise, Stripe, SendGrid și secretele aplicației).
   Ștergerea .env din ultima versiune NU elimină valorile din istoricul Git public.
2. Configurează un JWT_SECRET_KEY nou, unic, de minimum 32 caractere, pe server.
3. Verifică mediul în care se află baza /data/loial.db și backupul; nu rula migrări pe producție
   fără backup și test de compatibilitate.
4. Configurează providerul AI numai după acceptarea condițiilor de prelucrare a datelor.
5. Configurează LOIAL_AI_INPUT_USD_PER_M, LOIAL_AI_OUTPUT_USD_PER_M,
   LOIAL_AI_USD_TO_EUR pentru modelul economic. Pentru modelul avansat configurează și
   LOIAL_AI_ADVANCED_MODEL și prețurile sale. Prețurile trebuie revizuite după tariful real.
6. Nu folosi API-urile administrative noi fără Bearer token.
7. Rulează testele izolate cu pip install -r requirements.txt și
   python -m pytest tests/test_loial_ai_core.py -q.
8. Efectuează teste reale separate pentru scanare, ștampile, înregistrare și bonusuri.

## CSV de vânzări
Antet minimal: sold_at,product,quantity,unit_price
Antet opțional: transaction_id,unit_variable_cost,customer_uuid
- Data ISO YYYY-MM-DD
- Prețurile și costurile comparabile, preferabil fără TVA, validate de administrator
- Maximum 2000 rânduri, 4 MB per fișier
- Dacă lipsește costul variabil, contribuția produsului rămâne necunoscută
- Nu se deduc costuri inexistente, nu se amestecă automat facturile cu vânzările

## API noi
GET /api/loial-ai/context
PUT /api/loial-ai/profile
GET /api/loial-ai/history
POST /api/loial-ai/chat
GET /api/loial-ai/weekly
GET /api/loial-ai/report
POST /api/loial-ai/metrics
POST /api/loial-ai/documents
GET /api/loial-ai/documents
POST /api/loial-ai/documents/{id}/confirm
GET /api/loial-ai/customers
GET /api/loial-ai/customers/{id}/purchases
GET /api/loial-ai/message-templates
GET /api/loial-ai/message-templates/{key}/preview
POST /api/loial-ai/campaigns
GET /api/loial-ai/campaigns
POST /api/loial-ai/campaigns/{id}/approve
GET /api/loial-ai/campaigns/{id}/audience
GET /api/loial-ai/exports/customers.csv
GET /api/loial-ai/exports/sales.csv
GET /api/loial-ai/exports/ads-consented.csv

## Siguranță și guvernanță
Datele de marketing și datele de fidelizare au scopuri diferite. Exportul publicitar
include numai contactele cu consimțământ specific înregistrat. Campaniile nu pleacă
automat. Nu trimite documente sensibile la AI fără o bază legală și acord cu furnizorul.
Loial afișează rezultatul calculat și proveniența datelor, dar nu expune prompturile,
formulele de implementare sau raționamentul intern al modelului.
