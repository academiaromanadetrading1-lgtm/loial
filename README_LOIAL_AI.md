# Loial AI Business — arhitectură și stadiu

## Obiectiv comercial
Loial este un consultant managerial conversațional prin chat exclusiv text și documente atașate.
Pachetul Business este gândit pentru 65 EUR/lună, fără TVA adăugat în prezent, cu AI inclus. Activarea facturării și costul real pe firmă necesită validare comercială.
Nu trimite SMS/WhatsApp: eventualii furnizori sunt contractați separat de firma client.
Sistemul este multi-industrie; nu presupune că orice antreprenor vinde produse în magazin.

## Profiluri incluse
- Uber / Bolt / taxi / rideshare: curse, ore online, km, comisioane, cost energie, rezultat per tură
- Atelier / service auto: ore de manoperă, piese, grad utilizare, lucrări în garanție
- Spălătorie self-wash: boxe, cicluri, energie/apă/chimicale, indisponibilitate
- Patiserie, restaurant, retail, salon, ecommerce
- General: administratorul descrie în propriile cuvinte orice altă activitate

Administrarea profilului și setul de întrebări sunt independente de baza codului QR.

## Implementat in ramura de lucru
- Loial AI Business: chat text-only, istoric, 8 teme, profiluri multi-industrie si documente
- Indicatori si rapoarte din date verificate, CRM, export CSV/XLSX, segmente de clienti
- Mesagerie nativa Loial catre clienti, din panoul Business, fara email, SMS sau WhatsApp
- Trimitere imediata prin buton, fara aprobarea unui email si fara limita lunara de mesaje
- Mesaje catre toata audienta eligibila, segmente inactive, cumparatori de produs sau client individual
- Proiect de mesaj propus optional de AI; antreprenorul poate edita si trimite direct
- Inbox privat in portofel, cu mesaje necitite, marcare citit si preferinte pentru oferte
- La inscriere si la scanarea stampilei: notificari de serviciu generate direct in Loial
- Masurare mesaje livrate si citite; fara furnizori externi si fara taxa de email/SMS
- Acces separat per firma si token privat al dispozitivului clientului, distinct de QR-ul vizibil angajatului
- Mesajele comerciale sunt permise doar clientilor care au activat ofertele in Loial;
  pot opri ofertele fara a pierde cardul si mesajele de serviciu
- Cheile istorice .env eliminate din versiunea curenta a ramurii; rotirea lor ramane obligatorie

## Limitari si verificari inainte de lansare
- Schimbarile sunt in PR draft, nu in productie; testele Python si scenariile end-to-end
  cu baza reala necesita executie si validare.
- Accesul privat la inbox este emis sigur la primul card nou. Portofelele existente anterior
  trebuie migrate prin verificarea titularului; simpla posesie a QR-ului NU este suficienta
  pentru recuperarea accesului la mesajele private.
- Mesajele devin vizibile in portofel la deschiderea/actualizarea paginii;
  nu exista inca notificari push in afara Loial (ar cere configurari separate).
- Datele se salveaza in baza de date a aplicatiei; nu se trimit emailuri/SMS/WhatsApp.
- Fara date de contact de la platformele Uber/Bolt si fara drept de a contacta pasageri automat.
- Trimiterea la volume foarte mari trebuie verificata la testele de performanta;
  nu exista cote comerciale lunare, dar sunt necesare protectii anti-abuz.
- Bonul Loial cu QR unic este implementat pentru tranzactii inregistrate de firma, cu revendicare
  o singura data, legare la produse si retururi. Conectarea automata la POS/casa de marcat
  si imprimarea QR-ului pe bonul fiscal depind de sistemul fiscal concret.
- Cererile saptamanale automate sunt implementate pe server, in chatul Business, cu un
  eveniment per firma/saptamana si fara serviciu extern. Contin datele confirmate;
  nu inventeaza vanzari in perioade fara documente.
- RAG academic complet, analiza multimodala a PDF-urilor scanate, recuperarea securizata
  a portofelelor vechi si testarile cu case reale necesita inca dezvoltare si validare.
- Consimtamantul pentru publicitate Meta/Google este diferit de acordul pentru ofertele Loial.
- Inainte de deploy: rotire chei istorice Stripe/Wise/SendGrid/JWT, secret JWT nou,
  backup al bazei /data/loial.db, verificarea planurilor si fluxului de scanare QR.
- AI text si multimodal necesita cheie si preturi API aprobate; mesageria nativa nu necesita AI.

## API mesagerie nativa
POST /api/loial-inbox/send              # trimitere directa, fara aprobare intermediara
GET  /api/loial-inbox/audience         # numar destinatari eligibili
GET  /api/loial-inbox/sent             # livrari si citiri
GET  /api/loial-inbox/me               # inbox client, token privat in header
POST /api/loial-inbox/read/{delivery_id}
GET  /api/loial-inbox/preferences      # oferte permise pe fiecare firma
POST /api/loial-inbox/preferences

## Teste
- python -m pytest tests/test_loial_ai_core.py tests/test_loial_inbox.py -q
- Manual: activare card nou, acordare stampila cu PIN, inbox privat, segment, mesaje,
  clientul opreste ofertele, alt administrator nu poate vedea/trimitere altor firme.
- Reactivare acces pentru portofele legacy: NU implementa numai cu wallet_uuid sau QR.

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
GET /api/loial-ai/exports/customers.csv
GET /api/loial-ai/exports/sales.csv
GET /api/loial-ai/exports/ads-consented.csv

## Siguranță și guvernanță
Datele de marketing și datele de fidelizare au scopuri diferite. Exportul publicitar
include numai contactele cu consimțământ specific înregistrat. Campaniile comerciale sunt trimise doar la apăsarea butonului de trimitere. Nu trimite documente sensibile la AI fără o bază legală și acord cu furnizorul.
Loial afișează rezultatul calculat și proveniența datelor, dar nu expune prompturile,
formulele de implementare sau raționamentul intern al modelului.


## Premium Black Metal (2026-11-16)
- **Doua carduri distincte**: fidelitate client (nume, afacere, stampile, statut) si
  ambasador (nume verificat, rang calculat, referral QR). Sunt carduri LOYALTY/PARTENER,
  fara plata, fara embleme bancare.
- Design dark brushed-metal cu detalii aurii in join.html si in panoul Business.
  Imagine PNG Black Metal salvabila in telefon si utilizabila in afara Apple/Google Wallet.
- Administratorul firmei poate deveni ambasador prin /api/loial-identity/ambassador/activate;
  nu se schimba rolul de administrator. Poate fi si client, prin propriul wallet cu token privat.
  Numele de ambasador poate fi personalizat, iar rangul vine numai din vanzarile confirmate.
- Conturile de ambasador deja existente necesita parola proprie pentru asociere; un email
  introdus manual sau un QR public NU sunt dovezi de identitate.
- Apple Wallet: arhitectura genereaza .pkpass cu storeCard pentru client si generic pentru
  ambasador; imagini, manifest SHA-1 si semnatura PKCS#7/CMS. Necesita certificatul
  Apple Pass Type ID, cheia privata asociata, WWDR si Team ID in secret manager.
  In lipsa acestora, butonul Apple Wallet ramane dezactivat.
- Google Wallet: genereaza link de salvare semnat RS256 cu service account;
  loyaltyObjects pentru client, genericObjects pentru ambasador. Clasele
  issuerId.classSuffix trebuie create si aprobate de emitent, iar contul sa
  primeasca acces de publicare. Nu se emite link daca lipseste configurarea.
- Apple Wallet pe Safari utilizeaza linkuri temporare de emitere (90 secunde),
  semnate pe server, fara a include secretul privat al clientului in adresa.
  Ruta GET /api/premium-wallet/apple/claim foloseste MIME application/vnd.apple.pkpass
  si Cache-Control private, no-store; necesita test practic pe iPhone.
- Google Wallet: in cod exista o coada de actualizare a stampilelor, autentificare OAuth2
  cu contul oficial, GET al obiectului de fidelitate si PATCH doar pentru soldul stampilelor.
  Acest mecanism este dezactivat implicit (LOIAL_GOOGLE_WALLET_SYNC_ENABLED=0) pana la
  configurarea si verificarea emitentului. Nu s-au trimis apeluri reale Google.
- Apple Wallet: implementat web service PassKit pentru dispozitive/verificare token,
  inregistrare cu push token criptat, listarea cardurilor modificate si redescare
  .pkpass resemnat. Se activeaza numai cu URL HTTPS, secret, certificat si cheie de
  criptare. Componenta de notificari APNs catre dispozitivele inregistrate nu este
  finalizata si necesita contul Apple real. Fara APNs, actualizarea automata
  imediata pe iPhone nu este garantata.
- Portofelul web Loial afiseaza datele de fidelitate direct din baza aplicatiei.
- API: GET /api/premium-wallet/availability,
  GET /api/premium-wallet/customer/cards,
  GET /api/premium-wallet/customer/{business_id}/apple,
  GET /api/premium-wallet/customer/{business_id}/google,
  GET /api/premium-wallet/ambassador/card,
  GET /api/premium-wallet/ambassador/apple,
  GET /api/premium-wallet/ambassador/google.
- API identitati: GET /api/loial-identity/me,
  POST /api/loial-identity/ambassador/activate,
  POST /api/loial-identity/ambassador/link,
  PUT /api/loial-identity/ambassador/name,
  POST /api/loial-identity/customer/link.
- Validarea reala pe iOS/Android si emiterea oficiala nu pot fi facute fara
  cheile/certificatele issuerului. Nu sunt deja active pe loial.space.

## Teste premium
python -m pytest -q tests/test_loial_premium_wallet.py
Testele folosesc certificate de laborator pentru formatul PassKit, fara a pretinde
ca sunt certificate Apple si fara a crea un cont Google Wallet real.

## Documentatia oficiala pentru configurare
Apple: https://developer.apple.com/help/account/capabilities/create-wallet-identifiers-and-certificates
Google: https://developers.google.com/wallet/retail/loyalty-cards/getting-started/issuer-onboarding
Google API auth: https://developers.google.com/wallet/retail/loyalty-cards/getting-started/auth/rest

### Robustete enrolare
Dispozitivul creeaza un secret privat inainte de inscriere si il pastreaza separat
de QR; daca cererea se intrerupe, poate relua inrolarea cu acelasi secret.
Un portofel mai vechi fara acel secret nu poate fi preluat doar cunoscand QR-ul.

## Actualizare calup: rapoarte saptamanale, bon QR, securitate
- LOIAL_WEEKLY_JOBS_ENABLED=1 (implicit): thread de server cu verificare ora de ora,
  tabele SQL cu unicitate (firma, saptamana ISO), solicitare in chatul administratorului.
  Pentru CI poate fi oprit cu 0. Nu sunt trimise emailuri/SMS.
- Bon Loial QR: POST /api/loial-receipts/issue (JWT Business, numar bon si linii),
  GET /api/loial-receipts/preview (QR cu token unic), POST /api/loial-receipts/claim
  (token bon + token privat wallet), POST /api/loial-receipts/refund (JWT Business),
  GET /api/loial-receipts/recent.
- Pagina pentru client: /loial-receipt.html; generare QR si retur din /loial-ai.html.
- Emiterea bonului nu inlocuieste casa de marcat sau bonul fiscal.
  Sistemul trebuie sa primeasca linii detaliate de vanzare din software-ul comerciantului
  ori prin introducere manuala. QR-ul fiscal obligatoriu nu este folosit ca sursa SKU.
- Daca bonul e returnat, liniile sale sunt excluse din analize si exporturile active;
  stampila deja acordata necesita revizuire, nu e retrasa automat daca poate fi cheltuita.
- Firmele noi au PIN principal de 4 cifre generat criptografic, nu 1234. Butonul
  de schimbare este in panoul firmei; PIN-ul vechi 1234 este blocat in scanarile
  principale pana la rotirea lui de catre administrator. Rutele de scan au rate limits.
- Am inlocuit inserarea directa a unor nume de clienti si firme in HTML in panoul
  administratorului pentru a reduce riscul injectiilor.
- Google Wallet: GET inainte de PATCH pentru un card deja salvat; fara emiterea
  intempestiva de carduri si fara apeluri cand opt-in nu este configurat.
- Apple PassKit: /api/passkit/v1/devices/.../registrations/... si
  /api/passkit/v1/passes/... pentru serviciul de actualizare; autentificare
  per serial cu HMAC si tokenuri de push criptate, teste cu dispozitive simulate.
- Testare izolata: Python + sintaxa JavaScript + pornire FastAPI real pe SQLite temporar.
  Nu sunt accesate date reale, producția sau API-uri financiare.

### Ce ramane pentru productie
1. Rotirea tuturor secretelor istorice publicate in repository si configurarea unui nou JWT_SECRET_KEY.
2. Backup, migrare testata a bazei persistente si validare pe STAGING.
3. Recuperare securizata a cardurilor legacy care nu au token privat de dispozitiv.
4. Sincronizare completa cu POS-ul comerciantului si compatibilitate pentru imprimarea
   QR-ului pe bon, acolo unde hardware-ul permite.
5. Cont oficial Apple/Google, certificate si test pe dispozitive; implementarea APNs
   daca se doreste schimbarea automata imediata a cardurilor Apple instalate.
6. Audit de marketing/consimtamant, protectii anti-abuz la volume mari, limite de cost AI,
   proceduri GDPR si masurarea conversiei campaniilor.
7. Verificarea rapoartelor manageriale cu date contabile reale, inclusiv tratamentul TVA
   si comparabilitatea preturilor cu costurile; nu se calculeaza profit net din date incomplete.
8. Acceptarea explicita pentru deploy dupa criteriile de lansare.


## Calup de consolidare — fidelizare, audit, confidentialitate si decizii manageriale

- Toate cele trei rute de scanare (`/api/scan`, `/api/scan-v2`, `/api/scan-universal`)
  folosesc un singur mecanism de acordare a stampilelor. Identificatorul unei
  operatiuni permite reluarea in siguranta; retrimiterea aceleiasi cereri nu
  acorda alta stampila. O noua operatie pentru acelasi card in 12 secunde este
  blocata pentru prevenirea dublelor scanari accidentale.
- Jurnalul `loial_stamp_awards` inregistreaza stampile manuale, bonuri revendicate,
  recompense folosite si corectii pentru retururi. Administratorul poate vedea
  istoricul propriului business in `GET /api/loial-scans/history` si in panoul firmei.
  Nu poate citi jurnalul altui comerciant.
- La returnarea unui bon, Loial elimina liniile sale din analiza vanzarilor,
  exporturi si audientele campaniilor bazate pe cumpararea unui anumit produs.
  Stampila este retrasa automat numai daca bonul respectiv constituie ultima
  operatie de fidelizare si recompensa nu a fost consumata. Altfel,
  administratorul este notificat ca trebuie sa verifice manual situatia.
- Informatiile personale din `/api/wallet-profile/{wallet_uuid}` necesita acum
  secretul privat `X-Loial-Wallet-Token`, nu doar QR-ul vizibil angajatului.
  Portofelele legacy fara secret nu pot consulta istoricul pana la o procedura
  verificata de recuperare. Aceasta ramane blocaj pentru migratia in productie.
- Analiza manageriala: ABC clasifica in clasa A inclusiv articolul care trece pragul
  de 80%, nu il transfera gresit in B/C. Loial diferentiaza contributia totala,
  contributia per unitate si rata contributiei atunci cand sunt cunoscute
  costurile, avertizand asupra produselor cu contributie negativa. Nu deduce
  profit net fara cheltuielile si perioada corespunzatoare.
- 56 teste izolate plus un test de pornire si traseu complet FastAPI pe SQLite
  temporar au trecut in GitHub Actions la ultima rulare de validare a calupului.
  Acestea nu inlocuiesc testul pe telefoane reale sau cu o casa de marcat.

### Verificari obligatorii ramase inainte de deploy
- Migrare si recuperare verificata a portofelelor existente, fara bazare exclusiv pe QR.
- Teste de concurenta multi-worker la scanari si importuri, plus backup/restore.
- Rotirea tuturor secretelor istorice publicate si verificarea configurarii secretelor.
- Configurarea oficiala Apple/Google Wallet, APNs pentru notificarea actualizarilor
  Apple, teste pe iOS/Android si validarea emitentului.
- Test cu casa de marcat/POS concret si politica de reconciliere a retururilor.
- Testarea UX si a proceselor GDPR, documentarea consimtamintelor si audit extern
  al izolarii multi-tenant. Publicarea ramane separata de acest PR draft.


## Pilot Google Wallet pentru primele 100 de firme (decizie 17.11.2026)

- Google Wallet are prioritate exclusiva; Apple Wallet este ascuns din UI si
  pilotul este dezactivat (`LOIAL_APPLE_PILOT_ENABLED=0`). Implementarile Apple
  existente raman in cod, dar nu impun plata contului Apple Developer.
- Un singur cont emitent Google Wallet pentru Loial. Daca
  `LOIAL_GOOGLE_MERCHANT_CLASSES=1`, fiecare business are propriul sablon
  `issuerId.loial_business_{id}_v1` creat pe baza identitatii firmei. La apelul
  autorizat de emitere, Loial verifica template-ul prin API si il creeaza
  idempotent daca lipseste. Nu exista o taxa de emitere per card aplicata de
  Google Wallet, dar se aplica limitarile si conditiile oficiale ale API-ului.
- Aspectul in Google Wallet respecta propriile limitari Google: programul are
  numele firmei, fundalul negru Black Metal si sigla Loial; cardul individual
  contine nume, statut, stampile si stampile ramase pana la recompensa.
- Cardurile de ambasador folosesc tipul Generic cu sigla Loial, rang real,
  nume personalizat si QR de recomandare. Emiterea necesita cont emitent aprobat
  si cheia de serviciu acordata explicit in consola Google.
- La actualizarea stampilelor, workerul optional modifica in Google si progresul,
  statutul si denumirea firmei. Foloseste aceeasi clasa ca la emitere, verifica
  mai intai obiectul existent si nu creeaza carduri noi fara actiunea clientului.
- Logo public utilizat de Google: `/api/premium-wallet/brand.png`.
- Endpointurile Google raman indisponibile pana la conectarea si aprobarea
  emitentului. Testele confirma doar structura, semnatura JWT si apelurile simulate.
- Pragul de 100 firme este o prioritate de produs, nu o limita artificiala care
  ar refuza firma 101. Reanalizam Apple dupa primii 100 comercianti activi.

Documentatie Google:
- https://developers.google.com/wallet/retail/loyalty-cards/use-cases/create
- https://developers.google.com/wallet/retail/loyalty-cards/resources/template
- https://developers.google.com/wallet/reference/rest/v1/loyaltyclass
- https://developers.google.com/wallet/retail/loyalty-cards/use-cases/updates


## Etapa Google Wallet first 100, audit de lansare si facturi
- Apple Wallet este oprit explicit in API si in interfata cat timp
  LOIAL_APPLE_PILOT_ENABLED=0. Nu este necesar cont Apple pentru pilot.
- Clasele Google folosesc reviewStatus UNDER_REVIEW la creare si sunt respinse
  daca sunt DRAFT/REJECTED/necunoscute. Accesul de publicare aprobat trebuie
  verificat separat in Google Pay & Wallet Console.
- Linkurile semnate pentru adaugarea cardului Google expira dupa 15 minute.
- API privat GET /api/admin/google-wallet-pilot arata progresul catre 100 firme:
  inscrise, cu clienti si active (cu cel putin o stampila acordata).
  Panoul platformei arata si configurarea emitentului, fara chei sau parole.
- Endpointurile demonstrative /wallet/google/{id} si /wallet/{id} raspund 410.
  Nu se mai expun linkuri false sau carduri Apple nesemnate drept reale.
- Exportul, stergerea si consimtamantul din API-ul GDPR legacy sunt limitate
  la administratorul platformei: ID-ul de client nu demonstreaza proprietatea.
- Verificare offline: python loial_preflight.py; cu LOIAL_DEPLOY_STAGE=staging
  ruleaza verificari pregatitoare fara cont oficial. Sunt controlate JWT,
  origine HTTPS, baza persistenta, dezactivarea Apple, configurarea Google si
  absenta conturilor demo. Secretelor nu li se afiseaza valorile in rezultat.
  Rotația cheilor, aprobarea Google si testul de backup raman pasi manuali.
- Facturile/cheltuielile pot fi confirmate explicit cu furnizor, numar, data,
  categorie, suma, moneda si baza TVA (net/gross). Documentul PDF/fotografia
  incarcata poate fi asociata prin identificator dupa verificarea valorilor.
  Nu se aduna lei cu euro si nu se combina sume brute cu sume nete.
  Documentele anulate raman auditate dar sunt excluse din rapoarte.
  Nu se deduce profitul net din informatii contabile incomplete.
- API facturi: POST /api/loial-expenses/confirm,
  GET /api/loial-expenses/summary, GET /api/loial-expenses/recent,
  POST /api/loial-expenses/{id}/void. Calcule fara cost AI.
- Nu s-au activat abonamente Apple sau servicii AI platite si nu s-a
  schimbat versiunea publica a platformei Loial.
