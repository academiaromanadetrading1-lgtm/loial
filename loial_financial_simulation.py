"""Bounded, deterministic managerial simulations; never posts accounting entries."""
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

RULES = """
Raspunde ca un consultant financiar si comercial orientat spre decizii. Foloseste valorile
declarate in mesajul curent, profil si conversatie pentru estimari conditionale. Nu cere
documente daca poti calcula o simulare utila. Arata ce este declarat, ce este confirmat
si ce presupui (perioada, TVA, monede, costuri fixe/variabile, numar de bonuri).
Daca baza TVA este neclara, calculeaza conditional numai sub ipoteza explicita ca
sumele sunt comparabile; daca se declara preturi cu TVA, nu le trata ca venit net.
Nu transforma lipsa datelor in zero si nu dubla cheltuielile. Nu confunda achizitiile
cu consumul. O simulare nu modifica registrul firmei. Nu promite cresterea profitului.
Cand exista suficiente valori sau ipoteze explicite pentru o simulare lunara de
profitabilitate, include EXACT un bloc fenced JSON la final. Exemplul de sintaxa de mai jos contine numere fictive; NU le folosi ca date sau ipoteze implicite pentru firma analizata. Inlocuieste toate valorile cu cele relevante cazului:
```loial-simulation
{"currency":"RON","basis":"explain period, VAT, provenance and assumptions in reply language","revenue":100000,"variable_cost":40000,"fixed_cost":30000,"target_pct":20,"scenarios":[{"name":"short label","assumption":"specific action and numeric assumptions","revenue_delta":0,"variable_cost_delta":-1000,"fixed_cost_delta":0}]}
```
In loc de revenue poti furniza transactions (numar lunar) si average_ticket; nu ambele.
Valorile numerice sunt fara separatori de mii. target_pct este optional si nu se
interpreteaza ca garantie. Include pana la 3-5 scenarii ALTERNATIVE independente,
nu cumulate, adaptate cererii. Pentru fiecare, cuantifica separat modificarea
veniturilor, costurilor variabile si fixe; zero inseamna neschimbat, nu necunoscut.
La volum suplimentar include cost variabil incremental; la schimbari de pret explica
ipoteza privind cererea; la campanii include costul/recompensa. Pentru o tinta de
profit, arata actiuni plauzibile si ce trebuie masurat; nu pretinde ca tinta e atinsa.
Daca datele chiar nu permit un model de baza, explica ce poate fi calculat, ofera o
sensibilitate/interval justificat si cere doar datele cu adevarat decisive.
Blocul este calculat de server; nu repeta rezultatele numerice derivate in text.
Scrie clar cu titluri Markdown, bold si liste scurte. Tabele Markdown sunt permise.
Nu emite HTML sau cod executabil. Nu emite blocuri loial-chart direct.
"""

LABELS = {
"ro": ["Simulare lunară condițională","Ipoteze","Indicator","Valoare","Venituri","Costuri variabile","Costuri fixe","Profit operațional estimat","Marjă operațională","Prag de rentabilitate","Profit țintă","Creștere necesară","Scenariu alternativ","Profit estimat","Diferență față de bază","Bază","Nedeterminabil","Scenariile sunt independente, nu cumulative.","Simulare invalidă; rezultatele numerice nu au fost validate.","Venituri scenariu","Costuri variabile scenariu","Costuri fixe scenariu"],
"en": ["Conditional monthly simulation","Assumptions","Metric","Value","Revenue","Variable costs","Fixed costs","Estimated operating profit","Operating margin","Break-even revenue","Target profit","Required increase","Alternative scenario","Estimated profit","Change vs baseline","Baseline","Not determinable","Scenarios are independent, not cumulative.","Invalid simulation; numerical results were not validated.","Scenario revenue","Scenario variable costs","Scenario fixed costs"],
"es": ["Simulación mensual condicional","Supuestos","Indicador","Valor","Ingresos","Costes variables","Costes fijos","Beneficio operativo estimado","Margen operativo","Umbral de rentabilidad","Beneficio objetivo","Aumento necesario","Escenario alternativo","Beneficio estimado","Cambio frente a base","Base","No determinable","Los escenarios son independientes, no acumulativos.","Simulación no válida; los resultados numéricos no se han validado.","Ingresos del escenario","Costes variables del escenario","Costes fijos del escenario"],
"de": ["Bedingte Monatssimulation","Annahmen","Kennzahl","Wert","Umsatz","Variable Kosten","Fixkosten","Geschätzter Betriebsgewinn","Betriebsmarge","Break-even-Umsatz","Zielgewinn","Erforderlicher Anstieg","Alternativszenario","Geschätzter Gewinn","Änderung zur Basis","Basis","Nicht bestimmbar","Szenarien sind unabhängig, nicht kumulativ.","Ungültige Simulation; Zahlen nicht validiert.","Szenarioumsatz","Variable Szenariokosten","Fixe Szenariokosten"],
"fr": ["Simulation mensuelle conditionnelle","Hypothèses","Indicateur","Valeur","Chiffre d’affaires","Coûts variables","Coûts fixes","Résultat opérationnel estimé","Marge opérationnelle","Seuil de rentabilité","Résultat cible","Hausse nécessaire","Scénario alternatif","Résultat estimé","Écart à la base","Base","Non déterminable","Les scénarios sont indépendants, non cumulatifs.","Simulation invalide ; chiffres non validés.","CA du scénario","Coûts variables du scénario","Coûts fixes du scénario"],
"it": ["Simulazione mensile condizionale","Ipotesi","Indicatore","Valore","Ricavi","Costi variabili","Costi fissi","Utile operativo stimato","Margine operativo","Punto di pareggio","Utile obiettivo","Aumento necessario","Scenario alternativo","Utile stimato","Variazione dalla base","Base","Non determinabile","Gli scenari sono indipendenti, non cumulativi.","Simulazione non valida; risultati numerici non verificati.","Ricavi scenario","Costi variabili scenario","Costi fissi scenario"],
"nl": ["Voorwaardelijke maandsimulatie","Aannames","Kengetal","Waarde","Omzet","Variabele kosten","Vaste kosten","Geschatte bedrijfswinst","Bedrijfsmarge","Break-evenomzet","Winstdoel","Vereiste stijging","Alternatief scenario","Geschatte winst","Verschil met basis","Basis","Niet bepaalbaar","Scenario’s zijn onafhankelijk, niet cumulatief.","Ongeldige simulatie; cijfers niet gevalideerd.","Scenario-omzet","Variabele scenariokosten","Vaste scenariokosten"],
"pl": ["Warunkowa symulacja miesięczna","Założenia","Wskaźnik","Wartość","Przychody","Koszty zmienne","Koszty stałe","Szacowany zysk operacyjny","Marża operacyjna","Próg rentowności","Docelowy zysk","Wymagany wzrost","Scenariusz alternatywny","Szacowany zysk","Zmiana względem bazy","Baza","Nieokreślony","Scenariusze są niezależne, nie sumują się.","Nieprawidłowa symulacja; liczby niezweryfikowane.","Przychody scenariusza","Koszty zmienne scenariusza","Koszty stałe scenariusza"],
"hu": ["Feltételes havi szimuláció","Feltételezések","Mutató","Érték","Bevétel","Változó költségek","Fix költségek","Becsült üzemi eredmény","Üzemi eredményhányad","Fedezeti pont","Célzott eredmény","Szükséges növekedés","Alternatív forgatókönyv","Becsült eredmény","Eltérés az alaptól","Alap","Nem meghatározható","A forgatókönyvek függetlenek, nem összeadandók.","Érvénytelen szimuláció; a számok nem ellenőrzöttek.","Forgatókönyv bevétele","Forgatókönyv változó költségei","Forgatókönyv fix költségei"],
}

def number(value, nonnegative=False):
    if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)):
        raise ValueError("numeric value required")
    d=Decimal(str(value))
    if not d.is_finite() or abs(d)>Decimal("1000000000000") or (nonnegative and d<0):
        raise ValueError("out of range")
    return d

def label(value, limit):
    if not isinstance(value,str) or not value.strip():
        raise ValueError("missing text")
    return re.sub(r"[\r\n|\x00-\x1f]", " ", value).strip()[:limit]

def rounded(d):
    return d.quantize(Decimal(".01"),rounding=ROUND_HALF_UP)

def calculate(spec, currency):
    if not isinstance(spec,dict) or spec.get("currency")!=currency or not re.fullmatch("[A-Z]{3}",currency):
        raise ValueError("currency mismatch")
    basis=label(spec.get("basis"),900)
    if "revenue" in spec:
        if "transactions" in spec or "average_ticket" in spec:
            raise ValueError("ambiguous revenue")
        revenue=number(spec["revenue"],True)
    else:
        revenue=number(spec["transactions"],True)*number(spec["average_ticket"],True)
        if revenue>Decimal("1000000000000"):
            raise ValueError("out of range revenue")
    variable=number(spec["variable_cost"],True)
    fixed=number(spec["fixed_cost"],True)
    profit=revenue-variable-fixed
    margin=profit/revenue*100 if revenue>0 else None
    contribution=revenue-variable
    breakeven=fixed*revenue/contribution if contribution>0 else None
    target=None
    if spec.get("target_pct") is not None:
        pct=number(spec["target_pct"],True)
        if pct>10000:raise ValueError("target out of range")
        if profit>0:target=profit*(1+pct/100)
    scenarios=spec.get("scenarios",[])
    if not isinstance(scenarios,list) or len(scenarios)>5:
        raise ValueError("scenarios invalid")
    rows=[]
    for s in scenarios:
        if not isinstance(s,dict):raise ValueError("scenario invalid")
        r=revenue+number(s["revenue_delta"])
        v=variable+number(s["variable_cost_delta"])
        f=fixed+number(s["fixed_cost_delta"])
        if min(r,v,f)<0 or max(r,v,f)>Decimal("1000000000000"):
            raise ValueError("scenario totals invalid")
        p=r-v-f
        rows.append({"name":label(s["name"],75),"assumption":label(s["assumption"],300),
                     "revenue":r,"variable":v,"fixed":f,"profit":p,"delta":p-profit})
    return dict(basis=basis,revenue=revenue,variable=variable,fixed=fixed,profit=profit,
                margin=margin,breakeven=breakeven,target=target,scenarios=rows)

def render(spec,currency,language):
    r=calculate(spec,currency)
    l=LABELS.get(language,LABELS["en"])
    def fmt(d,unit=currency):
        if d is None:return l[16]
        n=f"{rounded(d):,.2f}"
        if language in ("ro","de","es","it","nl"):n=n.translate(str.maketrans(",.",".,"))
        return n+" "+unit
    lines=["### "+l[0],"**"+l[1]+":** "+r["basis"],"",
           "| "+l[2]+" | "+l[3]+" |","| --- | ---: |"]
    for title,key,unit in [(l[4],"revenue",currency),(l[5],"variable",currency),(l[6],"fixed",currency),
                           (l[7],"profit",currency),(l[8],"margin","%"),(l[9],"breakeven",currency)]:
        lines.append("| "+title+" | "+fmt(r[key],unit)+" |")
    if r["target"] is not None:
        lines.extend(["| "+l[10]+" | "+fmt(r["target"])+" |","| "+l[11]+" | "+fmt(r["target"]-r["profit"])+" |"])
    points=[{"label":l[15],"value":float(rounded(r["profit"]))}]
    if r["target"] is not None:points.append({"label":l[10],"value":float(rounded(r["target"]))})
    if r["scenarios"]:
        lines.extend(["",l[17],"","| "+ " | ".join([l[12],l[19],l[20],l[21],l[13],l[14]])+" |","| --- | ---: | ---: | ---: | ---: | ---: |"])
        for s in r["scenarios"]:
            lines.append("| "+s["name"]+" | "+" | ".join(fmt(s[k]) for k in ("revenue","variable","fixed","profit","delta"))+" |")
            points.append({"label":s["name"],"value":float(rounded(s["profit"]))})
        lines.append("")
        lines.extend("- **"+s["name"]+":** "+s["assumption"] for s in r["scenarios"])
    if len(points)>1:
        chart=json.dumps({"title":l[7],"unit":currency,"points":points},ensure_ascii=False,separators=(",",":"))
        lines.extend(["","```loial-chart",chart,"```"])
    return "\n".join(lines)

BLOCK=re.compile(r"(?ms)^```loial-simulation[ \t]*\r?\n(.*?)(?:^```[ \t]*$|\Z)")
RAW_CHART=re.compile(r"(?ms)^```loial-chart[ \t]*\r?\n.*?(?:^```[ \t]*$|\Z)")

def enrich_answer(answer,currency,language):
    # Only the server generates the chart contract.
    answer=RAW_CHART.sub("",answer)
    blocks=list(BLOCK.finditer(answer))
    if not blocks:return answer
    body=BLOCK.sub("",answer).strip()
    try:
        if len(blocks)!=1 or len(blocks[0].group(1))>10000:raise ValueError("invalid block")
        output=render(json.loads(blocks[0].group(1)),currency,language)
        return (body+"\n\n"+output).strip()
    except (ValueError,TypeError,KeyError,InvalidOperation,OverflowError):
        return (body+"\n\n"+LABELS.get(language,LABELS["en"])[18]).strip()
