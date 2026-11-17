"""Curated local SEO guides: practical examples, no fictitious local statistics."""
from html import escape
from fastapi import HTTPException

GUIDES={
("timisoara","cafenele"):("Timișoara","cafenele","Oferă o recompensă la a șasea cafea. Începe cu clienții care cumpără regulat în drum spre serviciu; compară vizitele repetate în intervale egale.","Urmărește costul cafelei oferite și marja incrementală, nu doar numărul de carduri."),
("bucuresti","restaurante"):("București","restaurante","Testează o campanie pentru prânz în timpul săptămânii, distinctă de vizitele de seară. Alege o recompensă cu cost cunoscut.","Compară tranzacțiile din același interval orar înainte și după test."),
("cluj-napoca","saloane"):("Cluj-Napoca","saloane","Acordă puncte după programările efectuate, nu după rezervări. Definește o recompensă compatibilă cu marja serviciului.","Măsoară revenirea clienților în funcție de ciclul obișnuit al serviciului."),
("brasov","pizzerii"):("Brașov","pizzerii","Separă comenzile ridicate din locație de livrări. Testează recompense pentru comenzile repetate în același canal.","Compară contribuția după costurile ingredientelor, ambalajelor și recompenselor."),
("iasi","frizerii"):("Iași","frizerii","Acordă ștampile după tunsorile finalizate și testează o recompensă după un număr stabilit de vizite.","Măsoară intervalul dintre vizite și gradul de ocupare fără a promite creșteri."),
}
def local_paths():
    return ["/local/"+city+"/"+industry for city,industry in GUIDES]

def install_local_seo(app,page):
    @app.get("/local/{city}/{industry}")
    def local_guide(city:str,industry:str):
        entry=GUIDES.get((city,industry))
        if not entry:raise HTTPException(404,"Ghid indisponibil")
        name,sector,example,metric=map(escape,entry)
        body=f"<p>Ghid de configurare pentru {sector} din {name}. Exemplu ipotetic, nu studiu de caz local.</p><h2>Campanie de test</h2><p>{example}</p><h2>Cum evaluezi rezultatele</h2><p>{metric}</p><p>LOIAL permite distribuirea cardurilor digitale prin QR și monitorizarea utilizării.</p><a href='/register.html?utm_source=industry'>Creează cont gratuit</a><p><a href='/solutii/{industry}'>Descoperă soluția pentru industrie</a></p>"
        return page("Fidelizare digitală pentru "+entry[1]+" în "+entry[0],body,"/local/"+city+"/"+industry)
