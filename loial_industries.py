"""Profiluri manageriale Loial AI - intrebari si indicatori adaptati domeniului.

Nu se deduce ca o firma are un anumit tip de activitate numai din denumire.
Administratorul poate alege si schimba profilul oricand.
"""
import unicodedata

PROFILES = {
    "general": {
        "label": "Afacere / servicii diverse",
        "units": ["produse", "servicii", "comenzi"],
        "metrics": ["incasari", "costuri", "contributie", "clienti recurenti", "lichiditate"],
        "documents": ["raport de vanzari sau incasari", "facturi de achizitie", "cheltuieli pe categorii"],
        "questions": ["Care este principala activitate?", "Ce vinzi si cum incasezi?", "Ce costuri poti masura?"],
        "insights": ["evolutia incasarilor", "costurile care cresc", "clientii inactivi"],
    },
    "patiserie": {
        "label": "Patiserie / brutarie / cofetarie",
        "units": ["produse", "bonuri", "loturi"],
        "metrics": ["marja pe produs", "valoarea bonului", "pierderi", "rotatia ingredientelor"],
        "documents": ["vanzari pe produs", "preturi ingrediente", "retete sau costuri pe lot", "produse nevandute"],
        "questions": ["Ce produse prepari si ce produse revinzi?", "Ce se arunca zilnic?"],
        "insights": ["produse cu contributie buna", "risipa", "oferte combinate"],
    },
    "rideshare": {
        "label": "Transport prin aplicatii (Uber / Bolt / taxi)",
        "units": ["curse", "ore online", "kilometri"],
        "metrics": ["incasari pe ora", "incasari pe kilometru", "comisioane platforma", "combustibil sau energie", "cheltuiala pe kilometru", "rezultat per tura"],
        "documents": ["raport saptamanal Uber/Bolt sau curse", "costuri combustibil/incarcare", "kilometri si ore lucrate", "service, asigurari si alte cheltuieli"],
        "questions": ["Lucrezi pe Uber, Bolt sau ambele?", "Folosesti masina personala, inchiriata sau flota?", "Cate ore si kilometri ai lucrat?", "Raportul include bacsis si comisioane?"],
        "insights": ["ore cu rezultat mai bun", "cost per kilometru", "curse si ture neprofitabile"],
    },
    "atelier_auto": {
        "label": "Service / atelier auto",
        "units": ["comenzi de reparatie", "ore de manopera", "piese"],
        "metrics": ["venit pe ora productiva", "marja pe piese", "ocuparea posturilor", "ore facturate", "reveniri"],
        "documents": ["comenzi de reparatie", "ore lucrate si facturate", "facturi piese", "cheltuieli fixe ale atelierului"],
        "questions": ["Cate posturi de lucru ai?", "Cat facturezi pe ora?", "Separi piesele de manopera?", "Ai reveniri sau lucrari in garantie?"],
        "insights": ["servicii profitabile", "timp nefacturat", "rotatia pieselor si reviziile recurente"],
    },
    "self_wash": {
        "label": "Spalatorie auto self-service",
        "units": ["cicluri", "boxe", "ore functionare"],
        "metrics": ["venit per boxa", "venit per ciclu", "consum apa", "consum energie", "consum chimicale", "timp nefunctionare"],
        "documents": ["incasari pe boxa/aparat", "citiri contoare apa si energie", "achizitii detergenti", "interventii si perioade nefunctionale"],
        "questions": ["Cate boxe active ai?", "Cum inregistrezi incasarile per boxa?", "Ai contoare si pentru apa si energie?", "Ce perioade de nefunctionare ai avut?"],
        "insights": ["boxe performante", "cost per spalare", "pierderi din nefunctionare"],
    },
    "restaurant": {
        "label": "Restaurant / cafenea / bar",
        "units": ["preparate", "bonuri", "mese"],
        "metrics": ["food cost", "contributie meniu", "valoare bon", "pierderi", "ocupare"],
        "documents": ["raport produse si bonuri", "cost retete si ingrediente", "pierderi", "cost personal si utilitati"],
        "questions": ["Servesti la masa, takeaway sau delivery?", "Ai costuri de reteta?", "Cat platesti comisioane pentru livrari?"],
        "insights": ["ingineria meniului", "produse cu cerere ridicata si marja buna", "risipa"],
    },
    "retail": {
        "label": "Magazin / comert cu amanuntul",
        "units": ["articole", "bonuri", "categorii"],
        "metrics": ["adaos", "marja comerciala", "rotatie stoc", "valoare bon", "retururi"],
        "documents": ["vanzari pe SKU", "achizitii si costuri", "stocuri si retururi"],
        "questions": ["Ce categorii comercializezi?", "Ai evidenta pe cod de articol?", "Cum urmaresti retururile?"],
        "insights": ["produse cu rotatie lenta", "produse cu marja buna", "nevoie de reaprovizionare"],
    },
    "salon": {
        "label": "Salon / frizerie / beauty",
        "units": ["programari", "servicii", "ore"],
        "metrics": ["venit per ora", "ocuparea calendarului", "reveniri", "cost consumabile", "anulari"],
        "documents": ["programari si incasari", "servicii pe operator", "consumabile si chirie"],
        "questions": ["Cati specialisti lucreaza?", "Care este durata unui serviciu?", "Cate programari sunt anulate?"],
        "insights": ["servicii cu contributie mare", "intervale libere", "clienti care nu au revenit"],
    },
    "ecommerce": {
        "label": "Magazin online",
        "units": ["comenzi", "produse", "vizite"],
        "metrics": ["valoare comanda", "rata retur", "cost achizitie client", "contributie per comanda", "recurenta"],
        "documents": ["export comenzi", "costuri produse si livrare", "cheltuieli promovare", "retururi si rambursari"],
        "questions": ["Ce platforma folosesti?", "Ai costuri de livrare si procesare pe comanda?", "Cat investesti in reclame?"],
        "insights": ["categorii rentabile", "clienti recurenti", "campanii cu contributie pozitiva"],
    },
}
ALIASES = {
    "uber": "rideshare", "bolt": "rideshare", "taxi": "rideshare",
    "ridesharing": "rideshare", "transport alternativ": "rideshare",
    "auto service": "atelier_auto", "service auto": "atelier_auto", "atelier": "atelier_auto",
    "mecanic": "atelier_auto", "vulcanizare": "atelier_auto",
    "self wash": "self_wash", "self-wash": "self_wash", "self service carwash": "self_wash",
    "spalatorie auto": "self_wash", "spalatorie self": "self_wash",
    "cofetarie": "patiserie", "brutarie": "patiserie", "patiserie": "patiserie",
    "cafenea": "restaurant", "bar": "restaurant", "horeca": "restaurant",
    "magazin": "retail", "supermarket": "retail", "comert": "retail",
    "frizerie": "salon", "coafor": "salon", "beauty": "salon",
    "online shop": "ecommerce", "magazin online": "ecommerce",
}

def normalize(value):
    v = unicodedata.normalize("NFKD", (value or "").lower())
    return " ".join("".join(c for c in v if not unicodedata.combining(c)).replace("_", " ").split())

def canonical(value):
    normalized = normalize(value)
    if not normalized:
        return "general"
    for key in PROFILES:
        if normalize(key) == normalized:
            return key
    for synonym, sector in sorted(ALIASES.items(), key=lambda item: -len(item[0])):
        if normalize(synonym) in normalized:
            return sector
    return "general"

def profile(sector):
    key = canonical(sector)
    return dict(PROFILES[key], key=key)

def weekly_request(sector, missing=None):
    p = profile(sector)
    required = [x for x in p["documents"] if not missing or x in missing]
    return ("Pentru analiza saptamanala a activitatii de tip " + p["label"] +
            ", poti incarca fotografii, capturi de ecran, PDF sau rapoarte CSV/Excel. " +
            "Am nevoie de: " + "; ".join(required) + ". " +
            "Daca unele date lipsesc, iti explic ce pot analiza si ce ramane neverificat.")
