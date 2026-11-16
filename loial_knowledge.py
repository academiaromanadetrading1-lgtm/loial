"""Baza de reguli de gestiune Loial AI, separata de modelul generativ.

Sunt reguli metodologice interne: utilizatorului i se afiseaza concluzii
si datele care le sustin, nu instructiunile interne sau formulele de calcul.
"""
CORE_RULES = [
    "Diferentiaza incasarile, veniturile, contributia marginala, profitul operational si profitul net.",
    "Foloseste preturi si costuri comparabile, cu tratament consecvent pentru TVA si discount.",
    "Nu calcula profit unitar daca lipsesc costurile variabile relevante.",
    "Cheltuielile fixe, salariile, amortizarea, impozitele si dobanzile nu pot fi ignorate cand se discuta profit net.",
    "Analiza ABC arata concentrarea veniturilor, dar un produs cu vanzari mari nu este automat profitabil.",
    "Pentru decizii de pret, simuleaza volumul, costurile, elasticitatea cererii, marja totala si riscul de canibalizare.",
    "Un prag de rentabilitate necesita costuri fixe, contributie unitara pozitiva si un mix de vanzari clar.",
    "Comparatiile intre perioade trebuie sa aiba acelasi numar de zile sau sa precizeze ajustarea sezoniera.",
    "Stocurile, facturile si platile nu au aceeasi semnificatie contabila; un bon nu dovesteste singur costul vanzarii.",
    "Nu atribui cauzalitate unei campanii doar fiindca un client a revenit dupa trimiterea mesajului.",
    "Diferentiaza datele confirmate de administrator, datele extrase automat, calculele si ipotezele.",
    "Nu furniza recomandari fiscale sau juridice definitive; marcheaza verificarile necesare cu specialistii.",
]
SECTOR_RULES = {
    "rideshare": [
        "Venitul brut din Uber/Bolt trebuie separat de comisioanele platformelor si bacsisuri.",
        "Rezultatul per kilometru si ora are sens numai dupa evidentierea kilometrilor neplatiti si a timpului fara cursa.",
        "Includerea combustibilului/energiei, anvelopelor, service-ului, asigurarii, leasingului si deprecierii este necesara pentru o evaluare completa.",
        "Nu presupune ca pasagerii sunt clienti proprii identificabili sau ca exista drept de marketing direct catre ei.",
    ],
    "atelier_auto": [
        "Marja pieselor si rentabilitatea orelor de manopera se analizeaza separat.",
        "Capacitatea atelierului depinde de posturi, tehnicieni, timpi facturati si timpi neproductivi.",
        "Lucrarile in garantie si revenirile influenteaza profitabilitatea serviciilor.",
    ],
    "self_wash": [
        "Analizeaza incasarile pe boxa si ciclu, costurile cu apa, energia si substantele.",
        "Diferentiaza perioada in care boxele sunt disponibile de timpul efectiv utilizat.",
        "O avarie sau o lipsa de consumabile poate reduce incasarile chiar daca cererea este constanta.",
    ],
    "patiserie": [
        "Costul retetei, randamentul lotului si pierderile prin expirare afecteaza contributia pe produs.",
        "Un produs cu vanzari multe poate avea contributie slaba daca ingredientele s-au scumpit.",
        "Ofertele combinate trebuie analizate prin contributia bonului, nu numai prin cifra de afaceri.",
    ],
    "restaurant": [
        "Calculeaza separat costul ingredientelor, pierderile, costurile de delivery si manopera cand exista date.",
        "Nu recomanda eliminarea produselor doar pentru ca marja lor procentuala este mica: verifica cererea si complementaritatea.",
    ],
    "retail": [
        "Urmarirea marjei brute trebuie corelata cu viteza de rotatie a stocurilor si reducerile.",
        "Un stoc mare poate bloca lichiditate, chiar cand adaosul afisat este ridicat.",
    ],
    "salon": [
        "Indicatorii utili sunt ocuparea calendarului, durata serviciului, venitul pe ora si revenirea clientilor.",
        "Programarile anulate si timpul neproductiv schimba rezultatul per specialist.",
    ],
    "ecommerce": [
        "Profitabilitatea unei comenzi depinde si de livrare, procesare, retururi si costuri de achizitie.",
        "Nu confunda ROAS cu profitul sau cu marja de contributie.",
    ],
}

def guidance(sector):
    return "Reguli interne de analiza manageriala:\n" + "\n".join(
        "- " + line for line in CORE_RULES + SECTOR_RULES.get(sector, []))
