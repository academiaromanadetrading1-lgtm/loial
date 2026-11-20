"""Public acquisition routes. No customer data, external services or paid calls."""
import os
import re
from html import escape
from xml.etree.ElementTree import Element, SubElement, tostring
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response
from loial_plans import public_catalog
from loial_seo_locales import COPY, landing, path_for
from loial_local_seo import install_local_seo, local_paths

ORIGIN = "https://loial.space"
LANGUAGES = ("ro","en","de","fr","it","es","nl","pl","hu")
CITIES = ("București","Cluj-Napoca","Timișoara","Iași","Constanța","Brașov","Craiova","Oradea","Sibiu","Arad","Pitești","Bacău","Galați","Ploiești","Târgu Mureș","Baia Mare","Buzău","Satu Mare","Botoșani","Suceava","Râmnicu Vâlcea","Drobeta-Turnu Severin","Focșani","Târgoviște","Tulcea","Reșița","Slatina","Alba Iulia","Bistrița","Deva","Hunedoara","Zalău","Sfântu Gheorghe","Giurgiu","Călărași","Slobozia","Piatra Neamț","Roman","Mediaș","Lugoj")

def sitemap_xml(paths):
    root=Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for path in sorted(set(paths)):
        node=SubElement(root,"url")
        SubElement(node,"loc").text=ORIGIN+path
    return tostring(root,encoding="utf-8",xml_declaration=True)

def page(title, body, path):
    title=escape(title)
    canonical=escape(ORIGIN+path,quote=True)
    menu = [["/","Acasă"],["/#cum-functioneaza","Cum funcționează"],["/pentru-clienti","Clienți"],["/ambasadori","Ambasadori"],["/pentru-firme","Firme"],["/#preturi","Prețuri"],["/despre-loial","Resurse"]]
    links = "".join('<a href="' + href + '"' + (' aria-current="page"' if href == path else '') + '>' + label + '</a>' for href,label in menu)
    role = {"/pentru-clienti": "client", "/pentru-firme": "business", "/ambasadori": "ambassador"}.get(path)
    css_class = "loial-public" + (" loial-public-role" if role else "")
    login_href = {"client": "/wallet", "ambassador": "/ambasador.html#contAmbasador"}.get(role, "/login.html")
    login_label = "Portofelul meu" if role == "client" else "Intră în cont"
    if role:
        body = role_landing(role, title, body)
        heading = ""
    else:
        heading = "<h1>" + title + "</h1>"
    return HTMLResponse(f"""<!doctype html><html lang="ro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} | LOIAL</title><link rel="stylesheet" href="/loial-premium.css"><link rel="canonical" href="{canonical}"></head><body class="{css_class}"><header class="loial-public-header"><div class="loial-public-nav"><a class="loial-wordmark" href="/">loial.space<span class="loial-tagline">Spațiul tău loial</span></a><nav aria-label="Navigare principală">{links}</nav><a class="loial-public-button outline" href="{login_href}">{login_label}</a></div></header><main class="loial-public-main">{heading}{body}</main><footer class="loial-public-footer"><a href="/gdpr/privacy">Confidențialitate</a> · <a href="/despre-loial">Despre LOIAL</a></footer><script src="/loial-i18n.js"></script></body></html>""")

def role_landing(role, title, body):
    config = {
        "client": ("PROGRAM DE LOIALITATE PENTRU CLIENȚI", "Beneficii la fiecare vizită.", "Toate cardurile de fidelitate ale firmelor participante, pe telefonul tău.", "/wallet", "Deschide portofelul", "Card digital", "Ștampile", "Recompense"),
        "business": ("FIDELIZARE ȘI MANAGEMENT", "Construiește relații cu clienții afacerii tale.", "Configurează recompense și urmărește activitatea. LOIAL AI și campaniile sunt disponibile în planurile eligibile.", "/register.html", "Creează cont de firmă", "Carduri QR", "Fidelizare", "Analiză"),
        "ambassador": ("PROGRAM DE PARTENERIAT", "Construiește-ți un venit lunar recomandând LOIAL.", "Comisioane aferente abonamentelor eligibile achitate. Înscrierea singură nu generează venit.", "/ambasador.html#contAmbasador", "Devino ambasador", "Link personal", "Firme active", "Comisioane")
    }
    kicker, headline, desc, href, action, a, b, c = config[role]
    hero = f"""<section class="loial-hero"><div><span class="loial-kicker">{kicker}</span><h1>{headline}</h1><p>{desc}</p><div class="loial-hero-actions"><a class="loial-public-button gold" href="{href}">{action}</a><a class="loial-public-button light" href="/demo">Vezi demonstrația</a></div></div><div class="loial-hero-art" aria-hidden="true"><div class="loial-device"><div class="loial-device-brand">L · LOIAL</div><div class="loial-device-card">loial.space<small>Spațiul tău loial</small></div><div class="loial-device-row"><span>✓</span>{a}</div><div class="loial-device-row"><span>✓</span>{b}</div><div class="loial-device-row"><span>✓</span>{c}</div></div><div class="loial-art-orbit"></div></div></section>"""
    features = {
        "client": [("Cardul tău digital", "Accesează cardurile direct pe telefon, fără aplicație din magazin."), ("Ștampile și recompense", "Urmărește progresul fiecărui card în funcție de regulile firmei."), ("Mesaje și recomandări", "Consultă ofertele primite și recomandă LOIAL prietenilor sau firmelor.")],
        "business": [("Program de fidelizare", "Personalizează recompensa și numărul de ștampile."), ("Clienți și activitate", "Urmărește vizitele și cumpărăturile înregistrate."), ("Campanii și LOIAL AI", "Analizează activitatea și comunică cu clienții eligibili în planurile disponibile.")]
    }
    if role in features:
        cards = "".join(f'<article class="loial-tier"><span class="loial-feature-mark" aria-hidden="true">✓</span><h3>{name}</h3><p>{detail}</p></article>' for name,detail in features[role])
        hero += '<section class="loial-tiers" aria-label="Beneficii">' + cards + '</section>'
    if role == "ambassador":
        tiers = "".join(f'<article class="loial-tier"><small>{band} firme plătitoare active</small><h3>{name}</h3><strong>20 EUR + {rate} EUR/lună</strong><p>20 EUR la prima plată eligibilă; {rate} EUR la fiecare reînnoire eligibilă, per firmă Business.</p></article>' for band,name,rate in [("1–25","Ambasador LOIAL",5),("26–50","Ambasador Manager",10),("51+","Ambasador Senior",15)])
        hero += '<section class="loial-tiers" aria-label="Niveluri Business">' + tiers + '</section>'
    secondary = '' if role == 'ambassador' else '<a class="loial-public-button outline" href="/demo">Vezi demonstrația</a>'
    return hero + '<div class="loial-content-panel">' + body + '</div>' + f'<div class="loial-bottom-actions"><a class="loial-public-button" href="{href}">{action}</a>{secondary}</div>'

def install_growth(app, industries):
    @app.get("/api/loial-plans")
    def plans():
        return public_catalog()

    @app.get("/api/loial-plans/simulate")
    def simulate(new_business:int=0,renewed_business:int=0,new_pro:int=0,
                 renewed_pro:int=0,recruited_business:int=0,recruited_pro:int=0):
        from loial_plans import simulate_portfolio
        try:
            return simulate_portfolio(new_business,renewed_business,new_pro,renewed_pro,recruited_business,recruited_pro)
        except ValueError:
            raise HTTPException(422,"Portofoliu invalid")

    @app.get("/robots.txt")
    def robots():
        return Response("User-agent: *\nDisallow: /api/\nDisallow: /platform.html\nDisallow: /join/\nDisallow: /scan/\nDisallow: /review/\nSitemap: https://loial.space/sitemap.xml\n",media_type="text/plain")

    @app.get("/sitemap.xml")
    def sitemap():
        # Only actual, published canonical pages; never advertise speculative translations.
        return Response(sitemap_xml(["/pentru-clienti","/pentru-firme","/ambasadori","/demo","/despre-loial","/fondatori","/comparatie-fidelizare"]+[path_for(lang) for lang in COPY]+
            ["/solutii/"+x for x in industries]+local_paths()),media_type="application/xml")

    @app.get("/pentru-clienti")
    def for_clients():
        return page("LOIAL pentru clienți", """<p>Cardurile de fidelitate ale firmelor participante, într-un singur portofel digital gratuit.</p>
        <section class="loial-guide" aria-label="Ghid vizual"><h2>Cum funcționează</h2><article class="loial-guide-step"><svg viewBox="0 0 96 96" role="img" aria-label="Activează cardul"><rect x="0" y="0" width="96" height="96" rx="18" fill="#dfede4"/><g stroke="#155743" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><rect x="23" y="14" width="50" height="68" rx="8"/><rect x="34" y="30" width="10" height="10"/><rect x="52" y="30" width="10" height="10"/><rect x="34" y="48" width="10" height="10"/><path d="M52 48h10v10H52zM44 71h8"/></g></svg><div><h3>Activează cardul</h3><p>Scanează codul unei firme participante.</p></div></article><article class="loial-guide-step"><svg viewBox="0 0 96 96" role="img" aria-label="Prezintă cardul"><rect x="0" y="0" width="96" height="96" rx="18" fill="#dfede4"/><g stroke="#155743" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><rect x="13" y="25" width="70" height="46" rx="8"/><path d="M13 39h70M24 58h18M58 56h14"/></g></svg><div><h3>Prezintă cardul</h3><p>Arată QR-ul la casă pentru înregistrarea vizitei.</p></div></article><article class="loial-guide-step"><svg viewBox="0 0 96 96" role="img" aria-label="Verifică recompensa"><rect x="0" y="0" width="96" height="96" rx="18" fill="#dfede4"/><g stroke="#155743" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><rect x="19" y="41" width="58" height="34" rx="3"/><path d="M16 30h64v12H16zM48 30v45M48 30c-28 0-23-27-8-15l8 15c28 0 23-27 8-15z"/></g></svg><div><h3>Verifică recompensa</h3><p>Consultă oferta și progresul fiecărei firme.</p></div></article></section><h2>Ce poți face?</h2><p>Prezintă codul QR la casă, urmărește ștampilele și recompensele fiecărei firme, consultă ofertele disponibile și recomandă LOIAL prietenilor sau firmelor.</p>
        <h2>Cum începi?</h2><p>Activează cardul la o firmă participantă, apoi adaugă portofelul LOIAL pe ecranul telefonului. Nu ai nevoie de Apple Wallet sau Google Wallet.</p>
        <h2>Cât costă?</h2><p>Portofelul clientului este gratuit. Recompensele depind de condițiile fiecărei firme.</p>
        <p><a href="/wallet">Deschide portofelul</a> · <a href="/wallet-recovery.html">Recuperează cardul</a> · <a href="/demo">Vezi demonstrația</a></p>
        <h2>Întrebări frecvente</h2><p>QR-ul LOIAL nu este un card bancar. Ofertele comerciale depind de acordul tău și de regulile fiecărei firme.</p>""", "/pentru-clienti")

    @app.get("/pentru-firme")
    def for_businesses():
        return page("LOIAL pentru firme", """<p>Configurează un program de fidelizare și gestionează relațiile cu clienții din același panou.</p>
        <section class="loial-guide" aria-label="Ghid vizual"><h2>Cum funcționează</h2><article class="loial-guide-step"><svg viewBox="0 0 96 96" role="img" aria-label="Configurează recompensa"><rect x="0" y="0" width="96" height="96" rx="18" fill="#dfede4"/><g stroke="#155743" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><rect x="19" y="41" width="58" height="34" rx="3"/><path d="M16 30h64v12H16zM48 30v45M48 30c-28 0-23-27-8-15l8 15c28 0 23-27 8-15z"/></g></svg><div><h3>Configurează recompensa</h3><p>Alege condițiile programului de fidelizare.</p></div></article><article class="loial-guide-step"><svg viewBox="0 0 96 96" role="img" aria-label="Afișează codul QR"><rect x="0" y="0" width="96" height="96" rx="18" fill="#dfede4"/><g stroke="#155743" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><rect x="23" y="14" width="50" height="68" rx="8"/><rect x="34" y="30" width="10" height="10"/><rect x="52" y="30" width="10" height="10"/><rect x="34" y="48" width="10" height="10"/><path d="M52 48h10v10H52zM44 71h8"/></g></svg><div><h3>Afișează codul QR</h3><p>Clienții pot activa cardul folosind camera telefonului.</p></div></article><article class="loial-guide-step"><svg viewBox="0 0 96 96" role="img" aria-label="Analizează activitatea"><rect x="0" y="0" width="96" height="96" rx="18" fill="#dfede4"/><g stroke="#155743" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><rect x="15" y="18" width="66" height="53" rx="5"/><path d="M25 59l14-15 13 7 18-22M61 29h9v9M38 79h20M48 71v8"/></g></svg><div><h3>Analizează activitatea</h3><p>Consultă datele disponibile și folosește LOIAL AI în planurile eligibile.</p></div></article></section><h2>Fidelizare și CRM</h2><p>Creează recompense, emite carduri digitale, scanează coduri QR și analizează vizitele și cumpărăturile înregistrate. Trimite campanii către clienții eligibili care au acceptat comunicările.</p>
        <h2>LOIAL AI</h2><p>Specialiști virtuali pentru analiza vânzărilor, cheltuielilor, stocurilor și deciziilor de management, în planurile eligibile. Rezultatele depind de datele disponibile.</p>
        <h2>Tarife</h2><p>Start: 0 EUR, până la 50 de clienți. Business: 67 EUR/lună. ProBusiness: 270 EUR/lună, maximum cinci locații. Pilotul este gratuit; planurile plătite depind de activarea plăților.</p>
        <h2>Cum începi?</h2><p>Creezi contul firmei, configurezi recompensa și afișezi codul QR. Integrarea cu echipamentele POS se validează separat.</p>
        <p><a href="/register.html">Creează cont de firmă</a> · <a href="/login.html">Autentificare</a> · <a href="/demo">Testează demonstrația</a></p>""", "/pentru-firme")

    @app.get("/despre-loial")
    def about_loial():
        return page("Ce este LOIAL.space?", """<p>LOIAL este o platformă SaaS de fidelizare, management și dezvoltare pentru afacerile locale, clienții lor și ambasadori.</p>
        <h2>Ce face LOIAL pentru afaceri?</h2><p>Carduri digitale de fidelitate, recompense, istoricul cumpărăturilor confirmate, CRM și campanii de retenție. Consultanții LOIAL AI asistă antreprenorii în analiza vânzărilor, cheltuielilor, stocurilor, lichidității și deciziilor de management, în funcție de plan și de datele disponibile.</p>
        <h2>Ce oferă clienților?</h2><p>Carduri accesibile din browser și instalabile pe ecranul telefonului, fără Google Wallet sau Apple Wallet obligatoriu. Clienții pot consulta recompensele și ofertele și pot recomanda platforma firmelor.</p>
        <h2>Ce oferă ambasadorilor?</h2><p>Instrumente de recomandare și simulare a comisioanelor. Comisioanele depind de abonamentele eligibile efectiv plătite; înscrierile gratuite nu generează venit.</p>
        <h2>Cât costă?</h2><p>Start: 0 EUR, până la 50 de clienți. Business: 67 EUR/lună. ProBusiness: 270 EUR/lună, până la cinci locații. Lansarea pilot este gratuită; disponibilitatea abonamentelor plătite depinde de activarea sistemului de plăți.</p>
        <h2>Cum evaluezi dacă LOIAL este potrivit pentru afacerea ta?</h2><p>Compară limita de clienți, costul, integrarea QR, accesul fără instalare, CRM și instrumentele de analiză. Rezultatele depind de implementare și activitatea fiecărei firme.</p><p><a href="/demo">Testează simulatorul</a> · <a href="/ambasadori">Programul de ambasadori</a> · <a href="/fondatori">Parteneri fondatori</a> · <a href="/">Site oficial</a></p>""", "/despre-loial")

    @app.get("/comparatie-fidelizare")
    def compare_loyalty():
        return page("Cum alegi o platformă de fidelizare pentru afacerea ta?",
            """<p>Ghid de evaluare pentru cafenele, restaurante, saloane, magazine și alte afaceri locale. Nu este un clasament independent.</p>
            <table style="width:100%;border-collapse:collapse"><caption>Criterii de evaluare</caption><thead><tr><th scope="col">Criteriu</th><th scope="col">LOIAL</th><th scope="col">Ce verifici la alternative</th></tr></thead><tbody>
            <tr><th scope="row">Acces client</th><td>Card digital prin browser, QR și acces de pe ecranul telefonului.</td><td>Necesită aplicație, cont sau portofel extern?</td></tr>
            <tr><th scope="row">Cost inițial</th><td>Start gratuit, maximum 50 de clienți.</td><td>Abonament minim, instalare, cost per client.</td></tr>
            <tr><th scope="row">CRM și retenție</th><td>Istoric de cumpărături confirmate și campanii în funcție de plan.</td><td>Segmentare, consimțământ, export, istoricul cumpărăturilor.</td></tr>
            <tr><th scope="row">Management</th><td>Consultanți LOIAL AI și simulări în planurile eligibile.</td><td>Analiză financiară, stocuri, vânzări și limite de utilizare.</td></tr>
            <tr><th scope="row">Recomandări</th><td>Program de ambasadori cu comisioane condiționate de plăți validate.</td><td>Reguli de atribuire și transparența comisioanelor.</td></tr>
            </tbody></table><h2>Când merită testat LOIAL?</h2><p>Dacă afacerea are clienți recurenți și dorește să combine recompensele digitale cu analiza activității și comunicarea comercială. Integrarea cu echipamentele de la casă trebuie verificată înainte de utilizarea operațională. Pilotul este gratuit; tarifele plătite depind de activarea plăților.</p><p><a href="/despre-loial">Funcții și tarife</a> · <a href="/demo">Testează simulatorul</a></p>""","/comparatie-fidelizare")

    @app.get("/llms.txt")
    def llms_reference():
        return Response("""# LOIAL
> LOIAL is a customer loyalty and business management SaaS for local businesses, customers and ambassadors.

The official website is https://loial.space/. LOIAL offers browser-based QR loyalty cards, rewards, CRM, retention campaigns and plan-dependent AI-assisted business analysis. Customers can access cards without a mandatory app store download. Ambassador commissions depend on eligible verified paid subscriptions; registration alone does not earn commissions.

The free pilot is active. Start includes up to 50 customers at EUR 0; catalog prices are EUR 67/month for Business and EUR 270/month for ProBusiness. Paid availability depends on billing activation. No claim of independent ranking, guaranteed business results or guaranteed commission is made.

## Official public references
- [Product overview](https://loial.space/despre-loial): Romanian product facts, roles and pricing.
- [English overview](https://loial.space/en/): English product facts and catalog.
- [Spanish overview](https://loial.space/es/): Spanish product facts and catalog.
- [Evaluation guide](https://loial.space/comparatie-fidelizare): transparent criteria, not an independent ranking.
- [Card simulator](https://loial.space/demo): demonstration only.
- [Ambassador programme](https://loial.space/ambasadori): commission conditions and illustration.
- [Founding partners](https://loial.space/fondatori): verified public listings only.
- [Sitemap](https://loial.space/sitemap.xml): public pages.
""",media_type="text/plain")

    @app.get("/ambasadori")
    def ambassadors():
        return page("Programul de ambasadori LOIAL",
            """<p>Prezintă LOIAL firmelor locale și câștigă comisioane pentru abonamentele eligibile efectiv achitate. Înscrierea unui ambasador nu generează comision.</p><section class="loial-guide" aria-label="Ghid vizual"><h2>Cum funcționează</h2><article class="loial-guide-step"><svg viewBox="0 0 96 96" role="img" aria-label="Prezintă LOIAL"><rect x="0" y="0" width="96" height="96" rx="18" fill="#dfede4"/><g stroke="#155743" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M18 38l8-20h44l8 20M18 38v8q8 9 15 0 8 9 15 0 8 9 15 0 8 9 15 0v-8M23 51v28h50V51M39 79V57h18v22"/></g></svg><div><h3>Prezintă LOIAL</h3><p>Arată unei firme cum funcționează fidelizarea.</p></div></article><article class="loial-guide-step"><svg viewBox="0 0 96 96" role="img" aria-label="Distribuie linkul personal"><rect x="0" y="0" width="96" height="96" rx="18" fill="#dfede4"/><g stroke="#155743" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M40 55l16-16M39 61l-7 7a12 12 0 0 1-17-17l17-17a12 12 0 0 1 17 0M57 35l7-7a12 12 0 0 1 17 17L64 62a12 12 0 0 1-17 0"/></g></svg><div><h3>Distribuie linkul personal</h3><p>Folosește linkul generat în contul tău.</p></div></article><article class="loial-guide-step"><svg viewBox="0 0 96 96" role="img" aria-label="Urmărește comisioanele"><rect x="0" y="0" width="96" height="96" rx="18" fill="#dfede4"/><g stroke="#155743" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><rect x="15" y="18" width="66" height="53" rx="5"/><path d="M25 59l14-15 13 7 18-22M61 29h9v9M38 79h20M48 71v8"/></g></svg><div><h3>Urmărește comisioanele</h3><p>Comisioanele se acordă pentru plăți eligibile confirmate.</p></div></article></section><h2>Business — 67 EUR/lună</h2><p>20 EUR la prima plată pentru ambasadorul direct, 10 EUR pentru recrutorul său direct; reînnoiri 5/10/15 EUR în funcție de numărul firmelor plătitoare.</p><h2>ProBusiness — 270 EUR/lună (în pregătire)</h2><p>Comisioane aprobate: 40 EUR direct, 40 EUR recrutor direct, reînnoiri 20/40/60 EUR. Venitul nu este garantat; plățile depind de validarea abonamentelor și de condițiile programului.</p><p><a href="/ambasador.html">Devino ambasador</a> · <a href="/demo">Creează o demonstrație</a></p><section class="loial-slider-simulator"><h2>Calculator de venituri lunare</h2><p>Trage bara pentru a vedea instantaneu comisioanele estimate. Firmele sunt considerate plătitoare eligibile.</p><form id="portfolioForm"><fieldset><legend>Alege abonamentul firmelor</legend><label><input type="radio" name="simPlan" value="business" checked> Business · 67 EUR/lună</label><label><input type="radio" name="simPlan" value="probusiness"> ProBusiness · 270 EUR/lună (în pregătire)</label></fieldset><label for="portfolioRange" class="loial-range-label">Firme plătitoare aduse <output id="portfolioCount" for="portfolioRange">20 firme</output></label><input id="portfolioRange" type="range" min="0" max="100" step="1" value="20"><div class="loial-range-scale"><span>0</span><span>25</span><span>50</span><span>75</span><span>100</span></div></form><div id="portfolioResult" aria-live="polite"><p id="portfolioRank"></p><div class="loial-sim-results"><article><strong id="portfolioActivation">400 EUR</strong><span>Comision total la prima plată</span></article><article><strong id="portfolioRenewal">100 EUR/lună</strong><span>Comision lunar la reînnoire</span></article></div></div><p class="loial-sim-note">Scenariu ilustrativ pentru firme recomandate direct: prima plată și lunile ulterioare sunt prezentate separat. Reînnoirea presupune că toate firmele rămân active și achită abonamentul. Venitul nu este garantat.</p><details><summary>Comisioane pentru firme aduse de ambasadorii recrutați de către tine</summary><p>10 EUR pentru prima plată eligibilă Business sau 40 EUR pentru ProBusiness, o singură dată per firmă.</p></details></section><script>(function(){const form=document.getElementById('portfolioForm'),range=document.getElementById('portfolioRange');const el=id=>document.getElementById(id);const fmt=n=>new Intl.NumberFormat('ro-RO',{maximumFractionDigits:0}).format(n)+' EUR';function render(){const n=Number(range.value),pro=form.elements.simPlan.value==='probusiness',tier=n>=51?2:n>=26?1:0,rate=(pro?[20,40,60]:[5,10,15])[tier];el('portfolioCount').textContent=n+(n===1?' firmă':' firme');el('portfolioRank').textContent=n===0?'Nicio firmă plătitoare în simulare.':['Ambasador LOIAL','Ambasador Manager','Ambasador Senior'][tier]+' · '+rate+' EUR/lună/firmă';el('portfolioActivation').textContent=fmt(n*(pro?40:20));el('portfolioRenewal').textContent=fmt(n*rate)+'/lună';range.style.setProperty('--loial-progress',n+'%');}form.addEventListener('submit',e=>e.preventDefault());form.addEventListener('input',render);form.addEventListener('change',render);render();})();</script>""","/ambasadori")

    @app.get("/demo")
    def demo():
        return page("Personalizează un card demonstrativ",
            """<p>Demonstrație locală. Nu creează conturi, carduri sau ștampile reale.</p><label>Numele firmei <input id="n" maxlength="80" value="Afacerea ta"></label><p><label>Recompensă <input id="r" maxlength="120" value="La 6 vizite primești o recompensă"></label></p><label>Culoare <input id="c" type="color" value="#153c2b"></label><div class="card" id="card"><strong>DEMO · LOIAL</strong><h2 id="pn">Afacerea ta</h2><p id="pr">La 6 vizite primești o recompensă</p><p id="count">0 / 6</p></div><p><button id="stamp">Simulează o ștampilă</button> <button id="reset">Resetează</button></p><a href="/register.html?utm_source=demo">Încearcă gratuit</a><script>const el=id=>document.getElementById(id);let count=0;el('n').oninput=()=>el('pn').textContent=el('n').value;el('r').oninput=()=>el('pr').textContent=el('r').value;el('c').oninput=()=>el('card').style.backgroundColor=el('c').value;function show(){el('count').textContent=count+' / 6'}el('stamp').onclick=()=>{count=Math.min(6,count+1);show()};el('reset').onclick=()=>{count=0;show()};</script>""","/demo")

    for lang in COPY:
        if lang=="ro":continue
        def make_page(locale):
            def localized_page():
                return HTMLResponse(landing(locale))
            return localized_page
        app.add_api_route(path_for(lang),make_page(lang),methods=["GET"],name="loial_landing_"+lang)

    install_local_seo(app,page)

    @app.get("/{filename}.txt")
    def indexnow_key(filename: str):
        key=os.environ.get("LOIAL_INDEXNOW_KEY","")
        if not re.fullmatch(r"[A-Za-z0-9-]{8,128}",key) or filename!=key:
            raise HTTPException(404,"Not found")
        return Response(key,media_type="text/plain",headers={"X-Robots-Tag":"noindex"})
