"""Public acquisition routes. No customer data, external services or paid calls."""
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
    return HTMLResponse(f"""<!doctype html><html lang="ro"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} | LOIAL</title><link rel="canonical" href="{canonical}"><style>body{{font-family:system-ui,sans-serif;background:#f6f9f7;color:#17392a;max-width:760px;margin:40px auto;padding:20px;line-height:1.6}}a{{color:#246449}}input{{padding:10px;max-width:100%;box-sizing:border-box}}.card{{padding:25px;border-radius:18px;background:#153c2b;color:white}}button{{padding:10px;cursor:pointer}}</style><header><a href="/">LOIAL</a></header><main><h1>{title}</h1>{body}</main><footer><a href="/gdpr/privacy">Confidențialitate</a></footer></html>""")

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
        return Response(sitemap_xml(["/ambasadori","/demo","/despre-loial","/fondatori"]+[path_for(lang) for lang in COPY]+
            ["/solutii/"+x for x in industries]+local_paths()),media_type="application/xml")

    @app.get("/despre-loial")
    def about_loial():
        return page("Ce este LOIAL.space?", """<p>LOIAL este o platformă SaaS de fidelizare, management și dezvoltare pentru afacerile locale, clienții lor și ambasadori.</p>
        <h2>Ce face LOIAL pentru afaceri?</h2><p>Carduri digitale de fidelitate, recompense, istoricul cumpărăturilor confirmate, CRM și campanii de retenție. Consultanții LOIAL AI asistă antreprenorii în analiza vânzărilor, cheltuielilor, stocurilor, lichidității și deciziilor de management, în funcție de plan și de datele disponibile.</p>
        <h2>Ce oferă clienților?</h2><p>Carduri accesibile din browser și instalabile pe ecranul telefonului, fără Google Wallet sau Apple Wallet obligatoriu. Clienții pot consulta recompensele și ofertele și pot recomanda platforma firmelor.</p>
        <h2>Ce oferă ambasadorilor?</h2><p>Instrumente de recomandare și simulare a comisioanelor. Comisioanele depind de abonamentele eligibile efectiv plătite; înscrierile gratuite nu generează venit.</p>
        <h2>Cât costă?</h2><p>Start: 0 EUR, până la 50 de clienți. Business: 67 EUR/lună. ProBusiness: 270 EUR/lună, până la cinci locații. Lansarea pilot este gratuită; disponibilitatea abonamentelor plătite depinde de activarea sistemului de plăți.</p>
        <h2>Cum evaluezi dacă LOIAL este potrivit pentru afacerea ta?</h2><p>Compară limita de clienți, costul, integrarea QR, accesul fără instalare, CRM și instrumentele de analiză. Rezultatele depind de implementare și activitatea fiecărei firme.</p><p><a href="/demo">Testează simulatorul</a> · <a href="/ambasadori">Programul de ambasadori</a> · <a href="/fondatori">Parteneri fondatori</a> · <a href="/">Site oficial</a></p>""", "/despre-loial")

    @app.get("/ambasadori")
    def ambassadors():
        return page("Programul de ambasadori LOIAL",
            """<p>Prezintă LOIAL firmelor locale și câștigă comisioane pentru abonamentele eligibile efectiv achitate. Înscrierea unui ambasador nu generează comision.</p><h2>Business — 67 EUR/lună</h2><p>20 EUR la prima plată pentru ambasadorul direct, 10 EUR pentru recrutorul său direct; reînnoiri 5/10/15 EUR în funcție de numărul firmelor plătitoare.</p><h2>ProBusiness — 270 EUR/lună (în pregătire)</h2><p>Comisioane aprobate: 80 EUR direct, 40 EUR recrutor direct, reînnoiri 20/40/60 EUR. Venitul nu este garantat; plățile depind de validarea abonamentelor și de condițiile programului.</p><p><a href="/ambasador.html">Devino ambasador</a> · <a href="/demo">Creează o demonstrație</a></p><section><h2>Simulează comisioanele lunare</h2><p>Introdu numărul de firme cu plăți eligibile în luna analizată. Scenariu ipotetic, nu venit garantat.</p><form id="portfolioForm"><p><label>Business · firme noi <input name="new_business" type="number" min="0" max="100000" step="1" value="0" required></label></p><p><label>Business · reînnoiri <input name="renewed_business" type="number" min="0" max="100000" step="1" value="0" required></label></p><p><label>ProBusiness · firme noi <input name="new_pro" type="number" min="0" max="100000" step="1" value="0" required></label></p><p><label>ProBusiness · reînnoiri <input name="renewed_pro" type="number" min="0" max="100000" step="1" value="0" required></label></p><p><label>Business · firme noi ale recruților direcți <input name="recruited_business" type="number" min="0" max="100000" step="1" value="0" required></label></p><p><label>ProBusiness · firme noi ale recruților direcți <input name="recruited_pro" type="number" min="0" max="100000" step="1" value="0" required></label></p><button type="submit">Calculează</button></form><div id="portfolioResult" aria-live="polite"></div></section><script>const pf=document.getElementById('portfolioForm'),pr=document.getElementById('portfolioResult');pf.addEventListener('submit',async e=>{e.preventDefault();const b=pf.querySelector('button');b.disabled=true;pr.textContent='Se calculează...';try{const response=await fetch('/api/loial-plans/simulate?'+new URLSearchParams(new FormData(pf)));if(!response.ok)throw Error('Verifică valorile introduse.');const d=await response.json();pr.replaceChildren();const money=n=>new Intl.NumberFormat('ro-RO',{style:'currency',currency:'EUR'}).format(n/100);for(const [label,key] of [['Activare','activation_cents'],['Reînnoiri','recurring_cents'],['Recrutare directă','sponsor_cents'],['Total estimat','total_commission_cents']]){const p=document.createElement('p');p.textContent=label+': '+money(d[key]);pr.append(p);const track=document.createElement('div');track.style.cssText='height:10px;background:#dce6e0;border-radius:8px';const bar=document.createElement('div');bar.style.cssText='height:100%;background:#2d6a4f;border-radius:8px';bar.style.width=(d.total_commission_cents?100*d[key]/d.total_commission_cents:0)+'%';track.append(bar);pr.append(track)}}catch(err){pr.textContent=err.message}finally{b.disabled=false}});</script>""","/ambasadori")

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
