# LOIAL — procedura de lansare pilot, 17.11.2026

## Versiune autorizată pentru pregătire (nu deploy automat)
- CI #519: https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44062943251
- Commit validat: eadbfb2d11f14686d803fef9e87184ef87754c74
- 176 teste izolate + 1 test integrat FastAPI/SQLite: PASS; 39 secunde.
- Bază de producție: 727a7fd7b404d471ae441a5e286594653fa02cd3.
- 50 commituri înainte, 0 în urmă; 27 fișiere schimbate.
- Acest document este doar procedural; deploy-ul rămâne fixat pe commitul testat, nu pe HEAD.
- Railway web / production; volum persistent /data; deployment de revenire 7e8d5fec-dd50-4577-9227-9411466eeefd.
- Tarife: Start 0 EUR/50 carduri/1 locație; Business 67 EUR/lună; ProBusiness 270 EUR/lună/până la 5 locații, ofertă individuală peste 5. Ultimul plan în pregătire. Fiscalitatea trebuie confirmată înainte de facturare.
- Pilot gratuit: LOIAL_PUBLIC_FREE_PILOT=1; LOIAL_MULTILOCATION_READY=0; fără credențiale Stripe; Apple/Google Wallet neobligatorii. Nu seta variabile în producție înainte de verificare.

## Gate 1 — copie de siguranță reală
Din terminalul serviciului existent, fără afișarea credențialelor sau datelor clienților:
```sh
set -eu
umask 077
test "${LOIAL_DATABASE_URL:-sqlite:////data/loial.db}" = "sqlite:////data/loial.db"
test -f /data/loial.db
df -h /data
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p /data/backups
python loial_backup.py --source /data/loial.db --output "/data/backups/prepilot-$STAMP.db"
python - "/data/backups/prepilot-$STAMP.db" <<'PY'
import sys, sqlite3, tempfile
from pathlib import Path
from loial_backup import backup_database
with tempfile.TemporaryDirectory() as d:
    restore=Path(d)/"restore.db"
    backup_database(sys.argv[1],restore)
    with sqlite3.connect(restore) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()==("ok",)
        assert db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]>0
    print("ISOLATED_RESTORE_OK")
PY
```
Nu substitui o copie locală din același volum unei copii externe. Păstrează o copie externă criptată, cu acces limitat. Dacă DB path diferă sau nu există suficient spațiu, oprește fără modificări. Nu trimite baza sau cheile în conversație.

## Gate 2 — operațiuni
- Confirmare rotație credențiale istorice, verificare preflight fără expunere secrete.
- Confirmare backup și restore, spațiu disponibil, configurație pilot și oprire facturare.
- Doar după acceptarea publicării: conectează serviciul existent la commitul eadbfb2d11f14686d803fef9e87184ef87754c74. Nu crea serviciu sau volum nou, nu fuziona main și nu porni Stripe.
- Verifică health-check, pagina principală, autentificare, card nou și scanare cu conturi de test separate, limite gratuite, izolarea între firme.
- Verifică QR și instalare PWA pe Samsung Android și iPhone când disponibil; nu considera testele CI dovadă de dispozitiv real.
- Dacă apar erori, oprește pilotul și restaurează versiunea anterioară după evaluarea compatibilității DB; nu suprascrie automat baza activă cu backupul. Evită pierderea tranzacțiilor ulterioare.
- Documente juridice: identitate operator, adresă/contact, fiscalitate, confidențialitate; fără date inventate.
- Stripe TEST și validare comercială ulterioară separată.

## Stare
CI PASS. Backup de producție, restore, rotație, verificare dispozitive și publicare încă neconfirmate. Nicio lansare sau execuție plătită inițiată prin acest document.

## Dovada operațională — 17.11.2026
Backup SQLite creat din consola Railway pe volumul activ: /data/backups/loial-20261117-103627.db, 851968 bytes, permisiuni 0600. Operatorul a furnizat captură cu mesajul Verified backup. Restaurarea într-un director temporar a returnat RESTORE TEST: PASS și integrity ok; baza activă nu a fost suprascrisă. Aceasta verifică integritatea copiei, nu recuperarea integrală a serviciului. Copia externă criptată, rotația cheilor și validarea dispozitivelor rămân neconfirmate. Railway read-only confirmă serviciul online și nicio modificare staged. Commitul de deploy rămâne eadbfb2d11f14686d803fef9e87184ef87754c74. Nu activa Stripe și nu publica fără aprobarea specifică și verificarea condițiilor de mai sus.

## Publicare pilot — 17.11.2026
Operatorul a furnizat dovada descărcării backupului de 832 KB pe calculator; criptarea locală nu a fost verificată. A aprobat explicit publicarea versiunii noi și a confirmat introducerea credențialelor noi. Railway a confirmat cele două variabile staged (valori nedivulgate), aplicarea patchului f9160bc6-45de-4997-8350-f5121d6bc414 și deployment SUCCESS 2ebda673-955f-4bb1-b514-7508a496e46d. Sursa este pin-uită la eadbfb2d11f14686d803fef9e87184ef87754c74. Volumul /data este conectat. Logurile noului deployment confirmă startup complet, GET /health, /, /sw.js, /scan.html și /join.html cu 200; GET /favicon.ico 404. Nu există patch staged. Stripe rămâne neconfigurat conform numelor variabilelor. Rotația efectivă a valorilor și revocarea vechii chei OpenAI nu pot fi verificate prin connector. Teste autentificate, AI cu apel real, instalare fizică PWA și identitatea juridică rămân nevalidate. Nu declara pilot integral validat.

## Rectificare și confirmare finală a deploymentului — 17.11.2026
Prima publicare (2ebda673-955f-4bb1-b514-7508a496e46d) a rulat efectiv main/02344cc, contrar commitului pin-uit din configurație; test operator 4/15. Această constatare înlocuiește afirmația anterioară privind versiunea efectiv publicată. A fost creată ramura release/loial-pilot-eadbfb2, identică SHA eadbfb2d11f14686d803fef9e87184ef87754c74; după aprobarea operatorului, deployment e61cbdaa-6b24-47a7-bde2-cef40481054f SUCCESS cu hash efectiv corect conform list_deployments. Startup complet, volum montat, health 200. Captura operatorului din consola noului container confirmă TOTAL 15/15: health, root, wallet, manifest, sw, ambele iconuri PNG, demo, ambasadori, robots, sitemap, catalog, simulator HTTP 200; identity/me și stripe/me HTTP 401. Verificările sunt status HTTP locale, nu validare a conținutului tarifelor sau a fluxurilor autentificate, TLS extern, dispozitive fizice ori apel AI real. Favicon fix rămâne separat, nepublicat. Stripe rămâne dezactivat/neconfigurat. 

## Preflight producție — 17.11.2026
Captura operatorului din containerul activ confirmă CHECKS PASSED: True și BLOCKERS: []. Aceasta validează regulile automate ale loial_preflight.py, nu audit complet de securitate. Backup și restore au dovezi separate; revocarea cheii OpenAI anterioare, identitatea juridică, testele autentificate în producție și dispozitivele fizice rămân de confirmat. Nicio modificare de producție necesară pentru acest test.
