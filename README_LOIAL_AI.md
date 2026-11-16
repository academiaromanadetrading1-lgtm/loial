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
- Integrarea cu POS/bon fiscal QR, RAG academic complet, notificari saptamanale cron server-side,
  validarea imaginilor si analizele avansate raman proiecte distincte.
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
POST /api/loial-ai/campaigns/{id}/approve
GET /api/loial-ai/campaigns/{id}/audience
GET /api/loial-ai/exports/customers.csv
GET /api/loial-ai/exports/sales.csv
GET /api/loial-ai/exports/ads-consented.csv
POST /api/loial-ai/campaigns/{id}/send
POST /api/loial-ai/email/unsubscribe
GET /api/loial-ai/message-templates
GET /api/loial-ai/customers

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
- Cardul Apple/Google creat reflecta situatia la momentul emiterii; actualizarea
  automata a stampilelor pe cardul deja instalat necesita urmatoarea etapa
  (Apple PassKit web service/APNs, Google Wallet object updates).
  Portofelul web Loial continua sa arate datele actualizate.
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
