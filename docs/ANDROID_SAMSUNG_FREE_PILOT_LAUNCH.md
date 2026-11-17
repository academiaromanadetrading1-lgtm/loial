# LOIAL: pilot public gratuit pe trei telefoane Samsung

Data: 17 noiembrie 2026. Acest document descrie o procedură, nu o testare deja efectuată.

## Configurația pilotului
- LOIAL_PUBLIC_FREE_PILOT=1.
- Fără LOIAL_STRIPE_SECRET_KEY, LOIAL_STRIPE_WEBHOOK_SECRET sau LOIAL_STRIPE_PRICE_ID.
- Recrutarea și fidelizarea gratuite pot fi publicate; abonamentele ProBusiness de 67 EUR/lună rămân indisponibile până la Stripe. Nu se acordă comisioane pentru înscrieri fără plată.
- Wise Business rămâne pentru plata ulterioară a comisioanelor, după încasări reale.
- iPhone, Google Wallet și Apple Wallet nu condiționează pilotul Android.

## Test de acceptare pe cele trei Samsung
Samsung 1, administrator de firmă: înregistrare, autentificare, configurarea recompensei, schimbarea PIN-ului personalului, verificarea limitei de 50 de carduri, ieșire și autentificare repetată.

Samsung 2, client: Chrome Android, https://loial.space/wallet, meniu browser -> Instalează aplicația/Adaugă la ecranul principal, deschidere din pictogramă, înscriere prin QR, card Black Metal, verificare ștampile și recompensă, test offline și reconectare.

Samsung 3, ambasador și personal: înscriere A, invitație A către B, înregistrare firmă cu referința lui B, dashboard privat; comisionul rămâne 0 EUR până la plata verificată. Scanarea cu PIN în firmă și prevenirea acordării de două ori a aceleiași ștampile.

Capturi necesare: pictograma pe ecran, deschiderea PWA în mod standalone, QR, mesaj offline, recompensă, panouri mobile și refuzul accesului fără PIN. Nu includeți parole sau date de plată în capturi.

## Condiții obligatorii pentru publicare
1. Identificarea furnizorului de hosting și a conexiunii reale dintre main și deployment. Un Procfile în GitHub nu demonstrează că site-ul se actualizează automat.
2. Directorul de pornire al aplicației trebuie să fie rădăcina repository-ului: uvicorn main:app --host 0.0.0.0 --port $PORT.
3. Baza SQLite trebuie să fie pe un volum persistent; verificați LOIAL_DATABASE_URL și accesul aplicației.
4. JWT_SECRET_KEY aleator, ALLOWED_ORIGINS=https://loial.space, LOIAL_DEV_SEED_DATA=0, LOIAL_PUBLIC_FREE_PILOT=1; secrete doar în platforma de găzduire.
5. Backup al bazei reale cu loial_backup.py și probă de restaurare separată. Nu suprascrieți baza curentă.
6. Rularea verificărilor: LOIAL_DEPLOY_STAGE=production python loial_preflight.py, testele automate și testele de staging.
7. Verificarea TLS, accesului la /health, imposibilitatea de a citi /static/main.py și /static/.env și izolarea datelor dintre firme.
8. Deployment cu rollback pregătit și verificare în alt browser/rețea.

Opriți lansarea la lipsa backupului verificat, lipsa cheilor, probleme de securitate, plăți Stripe activate accidental sau teste eșuate.

Stripe se conectează separat după crearea contului dedicat LOIAL, cu preț lunar 67 EUR și webhook verificat.
