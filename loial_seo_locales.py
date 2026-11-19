"""Localized public landing pages; no mass-generated thin city pages."""
from html import escape

ORIGIN="https://loial.space"
COPY={
"ro":("Carduri digitale de fidelitate pentru afaceri locale","Înlocuiește cardurile de hârtie cu un card digital accesibil prin cod QR.","Clienții pot adăuga cardul pe ecranul telefonului, fără instalare din magazinele de aplicații.","Alege recompensa, distribuie codul QR și urmărește utilizarea cardurilor.","Începe gratuit","Prețuri","Programul de ambasadori","Română"),
"en":("Digital loyalty cards for local businesses","Replace paper loyalty cards with a digital card customers can open using a QR code.","Customers can add their card to their phone home screen without downloading an app from an app store.","Choose your reward, share your QR code and monitor card usage.","Get started for free","Pricing","Ambassador programme","English"),
"de":("Digitale Treuekarten für lokale Unternehmen","Ersetzen Sie Papier-Stempelkarten durch digitale Karten, die Ihre Kunden per QR-Code öffnen.","Kunden können die Karte zum Startbildschirm hinzufügen, ohne eine App aus einem App-Store herunterzuladen.","Legen Sie Ihre Prämie fest, teilen Sie den QR-Code und verfolgen Sie die Kartennutzung.","Kostenlos starten","Preise","Botschafterprogramm","Deutsch"),
"fr":("Cartes de fidélité numériques pour commerces de proximité","Remplacez les cartes papier par une carte numérique accessible via un code QR.","Vos clients peuvent ajouter leur carte à l’écran d’accueil de leur téléphone sans passer par une boutique d’applications.","Choisissez la récompense, partagez le code QR et suivez l’utilisation des cartes.","Commencer gratuitement","Tarifs","Programme ambassadeurs","Français"),
"it":("Carte fedeltà digitali per attività locali","Sostituisci le tessere cartacee con una carta digitale accessibile tramite codice QR.","I clienti possono aggiungere la carta alla schermata iniziale del telefono senza scaricare un’app dallo store.","Scegli il premio, condividi il codice QR e monitora l’utilizzo delle carte.","Inizia gratis","Prezzi","Programma ambasciatori","Italiano"),
"es":("Tarjetas de fidelización digitales para negocios locales","Sustituye las tarjetas de papel por una tarjeta digital accesible mediante un código QR.","Tus clientes pueden añadir la tarjeta a la pantalla de inicio del móvil sin descargar una aplicación de una tienda.","Elige la recompensa, comparte el código QR y consulta el uso de las tarjetas.","Empieza gratis","Precios","Programa de embajadores","Español"),
"nl":("Digitale spaarkaarten voor lokale bedrijven","Vervang papieren spaarkaarten door een digitale kaart die klanten via een QR-code openen.","Klanten kunnen de kaart aan hun startscherm toevoegen zonder een app uit een appstore te downloaden.","Kies de beloning, deel de QR-code en volg het kaartgebruik.","Gratis beginnen","Prijzen","Ambassadeursprogramma","Nederlands"),
"pl":("Cyfrowe karty lojalnościowe dla lokalnych firm","Zastąp papierowe karty cyfrową kartą dostępną po zeskanowaniu kodu QR.","Klienci mogą dodać kartę do ekranu głównego telefonu bez pobierania aplikacji ze sklepu.","Wybierz nagrodę, udostępnij kod QR i monitoruj korzystanie z kart.","Zacznij bezpłatnie","Cennik","Program ambasadorski","Polski"),
"hu":("Digitális hűségkártyák helyi vállalkozásoknak","Cseréld le a papírkártyákat QR-kóddal megnyitható digitális kártyákra.","A vásárlók alkalmazásbolti letöltés nélkül hozzáadhatják a kártyát telefonjuk kezdőképernyőjéhez.","Válaszd ki a jutalmat, oszd meg a QR-kódot, és kövesd a kártyahasználatot.","Kezdd ingyen","Árak","Nagyköveti program","Magyar"),
}
DETAIL={
"ro":("50 de clienți","1 locație","Până la 5 locații","Ofertă personalizată peste 5 locații. ProBusiness este în pregătire.","Înscrierea și detaliile comerciale sunt momentan disponibile în română."),
"en":("50 customers","1 location","Up to 5 locations","Custom quote above 5 locations. ProBusiness is in development.","Registration and detailed commercial terms are currently available in Romanian."),
"de":("50 Kunden","1 Standort","Bis zu 5 Standorte","Individuelles Angebot ab 6 Standorten. ProBusiness ist in Entwicklung.","Registrierung und Vertragsdetails sind derzeit auf Rumänisch verfügbar."),
"fr":("50 clients","1 établissement","Jusqu’à 5 établissements","Devis personnalisé au-delà de 5 établissements. ProBusiness est en préparation.","L’inscription et les conditions commerciales détaillées sont actuellement en roumain."),
"it":("50 clienti","1 sede","Fino a 5 sedi","Preventivo personalizzato oltre 5 sedi. ProBusiness è in preparazione.","Registrazione e condizioni commerciali dettagliate attualmente in rumeno."),
"es":("50 clientes","1 establecimiento","Hasta 5 establecimientos","Presupuesto personalizado para más de 5 establecimientos. ProBusiness está en desarrollo.","El registro y las condiciones comerciales detalladas están disponibles actualmente en rumano."),
"nl":("50 klanten","1 vestiging","Tot 5 vestigingen","Offerte op maat boven 5 vestigingen. ProBusiness is in ontwikkeling.","Registratie en uitgebreide commerciële voorwaarden zijn momenteel in het Roemeens beschikbaar."),
"pl":("50 klientów","1 lokalizacja","Do 5 lokalizacji","Indywidualna oferta powyżej 5 lokalizacji. ProBusiness jest w przygotowaniu.","Rejestracja i szczegółowe warunki handlowe są obecnie dostępne po rumuńsku."),
"hu":("50 ügyfél","1 helyszín","Legfeljebb 5 helyszín","5 helyszín felett egyedi ajánlat. A ProBusiness fejlesztés alatt áll.","A regisztráció és a részletes üzleti feltételek jelenleg román nyelven érhetők el."),
}
def path_for(lang):
    return "/" if lang=="ro" else "/"+lang+"/"

def alternate_tags():
    return "".join(f'<link rel="alternate" hreflang="{lang}" href="{ORIGIN+path_for(lang)}">' for lang in COPY)+f'<link rel="alternate" hreflang="x-default" href="{ORIGIN}/">'

BILLING_LABEL={"ro":"EUR / lună","en":"EUR / month","de":"EUR / Monat","fr":"EUR / mois","it":"EUR / mese","es":"EUR / mes","nl":"EUR / maand","pl":"EUR / miesiąc","hu":"EUR / hó"}

DISCOVERY={
  "ro": [
    "Fidelizare și management pentru afaceri locale",
    "LOIAL reunește carduri digitale QR, CRM și campanii de retenție. Consultanții virtuali LOIAL AI asistă analiza vânzărilor, cheltuielilor, stocurilor și lichidității, în funcție de plan și datele disponibile.",
    "Clienții gestionează recompensele; ambasadorii pot primi comisioane numai pentru abonamente eligibile achitate. Pilotul este gratuit; abonamentele plătite depind de activarea plăților."
  ],
  "en": [
    "Customer loyalty and business management for local businesses",
    "LOIAL brings together digital QR loyalty cards, CRM and retention campaigns. LOIAL AI virtual consultants assist with sales, expense, inventory and cash-flow analysis, subject to plan access and available data.",
    "Customers manage rewards; ambassadors may earn commissions only on eligible paid subscriptions. The pilot is free; paid plans depend on payment activation."
  ],
  "de": [
    "Kundenbindung und Geschäftsmanagement für lokale Unternehmen",
    "LOIAL verbindet digitale QR-Treuekarten, CRM und Kundenbindungskampagnen. Virtuelle LOIAL AI-Berater unterstützen die Analyse von Umsatz, Ausgaben, Lagerbestand und Liquidität, abhängig vom Tarif und den verfügbaren Daten.",
    "Kunden verwalten Prämien; Botschafter können Provisionen nur für berechtigte bezahlte Abonnements erhalten. Die Pilotphase ist kostenlos; kostenpflichtige Tarife setzen die Zahlungsaktivierung voraus."
  ],
  "fr": [
    "Fidélisation et gestion des commerces locaux",
    "LOIAL réunit cartes de fidélité numériques QR, CRM et campagnes de rétention. Les consultants virtuels LOIAL AI aident à analyser les ventes, dépenses, stocks et liquidités selon la formule et les données disponibles.",
    "Les clients gèrent leurs récompenses ; les ambassadeurs peuvent toucher des commissions uniquement sur les abonnements payés éligibles. Le pilote est gratuit ; les offres payantes dépendent de l’activation des paiements."
  ],
  "it": [
    "Fidelizzazione e gestione delle attività locali",
    "LOIAL integra carte fedeltà digitali QR, CRM e campagne di fidelizzazione. I consulenti virtuali LOIAL AI assistono nell’analisi di vendite, spese, scorte e liquidità secondo il piano e i dati disponibili.",
    "I clienti gestiscono i premi; gli ambasciatori possono ricevere commissioni solo sugli abbonamenti idonei pagati. Il progetto pilota è gratuito; i piani a pagamento dipendono dall’attivazione dei pagamenti."
  ],
  "es": [
    "Fidelización y gestión de negocios locales",
    "LOIAL reúne tarjetas de fidelización digitales QR, CRM y campañas de retención. Los consultores virtuales LOIAL AI ayudan a analizar ventas, gastos, inventario y liquidez según el plan y los datos disponibles.",
    "Los clientes gestionan sus recompensas y los embajadores pueden recibir comisiones únicamente por suscripciones elegibles pagadas. El piloto es gratuito; los planes de pago dependen de la activación de los cobros."
  ],
  "nl": [
    "Klantloyaliteit en bedrijfsbeheer voor lokale ondernemers",
    "LOIAL combineert digitale QR-spaarkaarten, CRM en retentiecampagnes. Virtuele LOIAL AI-adviseurs ondersteunen analyses van omzet, uitgaven, voorraad en liquiditeit, afhankelijk van het abonnement en beschikbare gegevens.",
    "Klanten beheren beloningen; ambassadeurs kunnen uitsluitend commissies ontvangen op in aanmerking komende betaalde abonnementen. De pilot is gratis; betaalde abonnementen vereisen activering van betalingen."
  ],
  "pl": [
    "Lojalność klientów i zarządzanie lokalną firmą",
    "LOIAL łączy cyfrowe karty lojalnościowe QR, CRM i kampanie utrzymania klientów. Wirtualni konsultanci LOIAL AI wspierają analizę sprzedaży, wydatków, zapasów i płynności zależnie od planu i dostępnych danych.",
    "Klienci zarządzają nagrodami; ambasadorzy mogą otrzymywać prowizje wyłącznie za kwalifikujące się opłacone abonamenty. Pilotaż jest bezpłatny; płatne plany zależą od aktywacji płatności."
  ],
  "hu": [
    "Ügyfélhűség és üzletvezetés helyi vállalkozásoknak",
    "A LOIAL egyesíti a digitális QR-hűségkártyákat, a CRM-et és az ügyfélmegtartási kampányokat. A LOIAL AI virtuális tanácsadói a csomagtól és az elérhető adatoktól függően segítik az értékesítés, a kiadások, a készletek és a likviditás elemzését.",
    "Az ügyfelek kezelik jutalmaikat; a nagykövetek csak jogosult, kifizetett előfizetések után kaphatnak jutalékot. A pilot ingyenes; a fizetős csomagok a fizetés aktiválásától függenek."
  ]
}

def landing(lang):
    title, intro, pwa, steps, cta, pricing, ambassador, name=COPY[lang]
    cap,one,five,quote,note=DETAIL[lang]
    overview,features,roles=DISCOVERY[lang]
    nav=" · ".join(f'<a lang="{key}" href="{path_for(key)}">{escape(row[-1])}</a>' for key,row in COPY.items())
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(overview)} | LOIAL</title><meta name="description" content="{escape(features,quote=True)}"><link rel="canonical" href="{ORIGIN+path_for(lang)}">{alternate_tags()}<style>body{{font-family:system-ui,sans-serif;background:#f6f9f7;color:#17392a;max-width:850px;margin:40px auto;padding:20px;line-height:1.6}}a{{color:#246449}}.price{{display:inline-block;padding:20px;background:white;border:1px solid #dce6e0;border-radius:12px;margin:6px}}.cta{{display:inline-block;color:white;background:#246449;padding:12px 20px;border-radius:9px;text-decoration:none}}</style></head><body><header><strong>LOIAL</strong><nav>{nav}</nav></header><main><h1>{escape(overview)}</h1><p>{escape(features)}</p><p>{escape(roles)}</p><h2>{escape(title)}</h2><p>{escape(intro)}</p><p>{escape(pwa)}</p><p>{escape(steps)}</p><a class="cta" href="/register.html?utm_source=industry">{escape(cta)}</a><h2>{escape(pricing)} ({BILLING_LABEL[lang]})</h2><div class="price">Start · 0 EUR<br>{escape(cap)}</div><div class="price">Business · 67 EUR<br>{escape(one)}</div><div class="price">ProBusiness* · 270 EUR<br>{escape(five)}</div><p>{escape(quote)}</p><p>{escape(note)}</p><a href="/ambasadori">{escape(ambassador)}</a></main></body></html>"""
