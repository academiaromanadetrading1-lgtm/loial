"""Calcule verificabile pentru consultantul Loial; nu foloseste un model generativ."""
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

def money(value):
    try:
        result = Decimal(str(value).replace(",", ".").strip())
        if not result.is_finite():
            raise ValueError("Valoare infinita")
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Valoare numerica invalida")

def summarize_sales(rows):
    """Fiecare rand trebuie sa fie o linie de tranzactie CONFIRMATA, fara TVA in costurile si preturile comparate."""
    totals = defaultdict(lambda: {"quantity": Decimal("0"), "revenue": Decimal("0"),
                                   "variable_cost": Decimal("0"), "cost_known": True})
    transactions = set()
    days = set()
    for r in rows:
        product = str(r["product"]).strip()
        if not product:
            continue
        qty = money(r["quantity"])
        price = money(r["unit_price"])
        if qty < 0 or price < 0:
            raise ValueError("Cantitati sau preturi negative nepermise; retururile se importa separat")
        row = totals[product]
        row["quantity"] += qty
        row["revenue"] += qty * price
        if r.get("unit_variable_cost") is None:
            row["cost_known"] = False
        else:
            cost = money(r["unit_variable_cost"])
            if cost < 0:
                raise ValueError("Cost negativ")
            row["variable_cost"] += qty * cost
        if r.get("transaction_id"):
            transactions.add(str(r["transaction_id"]))
        if r.get("sold_at"):
            days.add(str(r["sold_at"])[:10])
    products = []
    for name, s in totals.items():
        known = s["cost_known"]
        contribution = s["revenue"] - s["variable_cost"] if known else None
        products.append({
            "product": name,
            "quantity": float(s["quantity"]),
            "revenue": round(float(s["revenue"]), 2),
            "variable_cost": round(float(s["variable_cost"]), 2) if known else None,
            "contribution": round(float(contribution), 2) if known else None,
            "contribution_pct": round(float(contribution / s["revenue"] * 100), 2)
                if contribution is not None and s["revenue"] > 0 else None,
        })
    products.sort(key=lambda p: p["revenue"], reverse=True)
    revenue = sum(p["revenue"] for p in products)
    known_costs = all(p["variable_cost"] is not None for p in products) and bool(products)
    return {
        "products": products,
        "sales_lines": len(rows),
        "unique_transactions": len(transactions) if transactions else None,
        "active_days": len(days),
        "total_revenue": round(revenue, 2),
        "total_contribution": round(sum(p["contribution"] for p in products), 2)
             if known_costs else None,
        "margin_data_complete": known_costs,
        "missing": [] if known_costs else ["Costuri variabile lipsa pentru unele produse; nu se poate afirma profitabilitatea totala."],
    }

def abc_products(products):
    """Clasificare ABC pe venituri: articolul care TRECE pragul ramane in clasa lui.

    Ex.: un singur produs cu 100% din venituri este A, nu C.
    Produsele cu venituri zero nu sunt tratate drept vanzari de tip A.
    """
    positive = [p for p in products if p["revenue"] > 0]
    total = sum(p["revenue"] for p in positive)
    running = 0.0
    out = []
    for product in sorted(products, key=lambda p: p["revenue"], reverse=True):
        prior_share = 100.0 * running / total if total else 100
        if product["revenue"] <= 0:
            category = "C"
        else:
            category = "A" if prior_share < 80 else ("B" if prior_share < 95 else "C")
        running += product["revenue"]
        share = 100.0 * running / total if total else 0
        out.append({"product": product["product"],
                    "share_cumulative_pct": round(share, 1),
                    "class": category})
    return out

def customer_segments(customers, today=None):
    today = today or date.today()
    groups = {"active_0_7": 0, "inactive_8_30": 0, "inactive_31_90": 0,
              "inactive_91_365": 0, "inactive_over_year": 0, "unknown": 0}
    for customer in customers:
        value = getattr(customer, "last_visit", None)
        if not value:
            groups["unknown"] += 1
            continue
        try:
            d = datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
            elapsed = (today - d).days
        except ValueError:
            groups["unknown"] += 1
            continue
        if elapsed <= 7:
            groups["active_0_7"] += 1
        elif elapsed <= 30:
            groups["inactive_8_30"] += 1
        elif elapsed <= 90:
            groups["inactive_31_90"] += 1
        elif elapsed <= 365:
            groups["inactive_91_365"] += 1
        else:
            groups["inactive_over_year"] += 1
    return groups

def sector_summary(sector, rows, operational=None):
    """Indicatori specifici numai daca sunt oferite explicit numitorii relevanti."""
    operational = operational or {}
    basic = summarize_sales(rows)
    extras = {}
    revenue = money(operational.get("revenue", basic["total_revenue"]))
    if sector == "rideshare":
        for label, key in (("revenue_per_hour", "online_hours"), ("revenue_per_km", "kilometres")):
            if key in operational and money(operational[key]) > 0:
                extras[label] = round(float(revenue / money(operational[key])), 2)
        if "platform_fees" in operational and "fuel_energy" in operational:
            extras["after_platform_and_energy"] = round(float(revenue - money(operational["platform_fees"]) -
                                                              money(operational["fuel_energy"])), 2)
            extras["caveat"] = "Nu este profit net: lipsesc alte costuri, taxe si amortizarea."
    elif sector == "atelier_auto":
        if "billed_hours" in operational and money(operational["billed_hours"]) > 0:
            extras["revenue_per_billed_hour"] = round(float(revenue / money(operational["billed_hours"])), 2)
        if "worked_hours" in operational and "billed_hours" in operational and money(operational["worked_hours"]) > 0:
            extras["billed_hours_pct"] = round(100 * float(money(operational["billed_hours"]) /
                                                         money(operational["worked_hours"])), 1)
    elif sector == "self_wash":
        if "wash_cycles" in operational and money(operational["wash_cycles"]) > 0:
            extras["revenue_per_cycle"] = round(float(revenue / money(operational["wash_cycles"])), 2)
        if "active_bays" in operational and money(operational["active_bays"]) > 0:
            extras["revenue_per_bay"] = round(float(revenue / money(operational["active_bays"])), 2)
    return dict(basic, sector_metrics=extras)


def manager_findings(summary, sector):
    """Constatari explicite din date confirmate, nu predictii sau cauzalitate presupusa."""
    products = summary.get("products") or []
    notes = []
    if not products:
        notes.append({"type": "missing", "text":
            "Incarca vanzarile pe produse sau servicii pentru a compara contributia si cererea."})
    else:
        highest_revenue = max(products, key=lambda p: p["revenue"])
        notes.append({"type": "observation", "text":
            "Produsul sau serviciul cu cele mai mari venituri din datele disponibile este " +
            highest_revenue["product"] + "."})
        known = [p for p in products if p["contribution"] is not None]
        if known:
            best = max(known, key=lambda p: p["contribution"])
            notes.append({"type": "observation", "text":
                "Cea mai mare contributie totala cunoscuta o are " + best["product"] +
                ". Compara cererea si capacitatea inainte de a promova acest produs."})
        # Contributia totala si contributia pe unitate pot indica prioritati diferite.
        # Explicatiile catre antreprenor sunt concrete, fara formule afisate.
        positive_units = [p for p in known if p["quantity"] > 0]
        if positive_units:
            best_unit = max(positive_units, key=lambda p: p["contribution"] / p["quantity"])
            unit_value = best_unit["contribution"] / best_unit["quantity"]
            notes.append({"type":"opportunity","text":
                "Din produsele cu costuri cunoscute, "+best_unit["product"]+
                " lasa cea mai mare contributie estimata pe unitate vanduta ("+
                str(round(unit_value,2))+
                " in moneda raportului). Verifica cererea, capacitatea si costurile complete inainte de a-i creste promovarea."})
            loss = [p for p in positive_units if p["contribution"] < 0]
            if loss:
                names=", ".join(p["product"] for p in loss[:4])
                notes.append({"type":"risk","text":
                    "In datele introduse, costul variabil depaseste incasarea pentru: "+
                    names+". Verifica preturile, reducerile si costurile din documente."})
        known_pct = [p for p in known if p["contribution_pct"] is not None]
        if len(known_pct)>1:
            top_rate = max(known_pct,key=lambda p:p["contribution_pct"])
            notes.append({"type":"observation","text":
                "Cea mai buna rata a contributiei din produsele verificate apare la "+
                top_rate["product"]+" ("+str(top_rate["contribution_pct"])+
                "%). O rata mare nu garanteaza si cel mai mare castig total."})
        if len(known) < len(products):
            notes.append({"type": "missing", "text":
                "Pentru o parte dintre produse lipsesc costurile variabile; comparația completa a marjelor nu este posibila."})
        if len(products) > 1:
            least_revenue = min(products, key=lambda p: p["revenue"])
            notes.append({"type": "check", "text":
                "Verifica evolutia in timp si stocul pentru " + least_revenue["product"] +
                ", care are cele mai mici venituri in importul disponibil. Vanzarile mici nu dovedesc singure ca produsul trebuie eliminat."})
    metrics = summary.get("sector_metrics") or {}
    needed = {
        "rideshare": ("online_hours", "kilometres", "platform_fees", "fuel_energy"),
        "atelier_auto": ("billed_hours", "worked_hours"),
        "self_wash": ("wash_cycles", "active_bays"),
    }
    if sector in needed and not metrics:
        notes.append({"type": "missing", "text":
            "Pentru acest domeniu sunt necesari si indicatori operationali: " +
            ", ".join(needed[sector]) + "."})
    notes.append({"type": "limitation", "text":
        "Recomandarile se bazeaza doar pe perioadele si costurile introduse; profitul net si efectul campaniilor necesita date suplimentare."})
    return notes


def break_even_analysis(rows, fixed_costs, period, vat_basis_confirmed=False):
    """Deterministic CVP assessment; no AI estimated costs or unverified VAT assumptions.

    Mixed portfolios get ONLY a revenue break-even estimate, never a misleading
    count of interchangeable items. Single-product portfolios can get units too.
    """
    from decimal import ROUND_CEILING
    if not isinstance(period,str) or len(period)!=7 or period[4]!="-":
        raise ValueError("Perioada trebuie YYYY-MM")
    try:
        date.fromisoformat(period+"-01")
    except ValueError:
        raise ValueError("Perioada este invalida")
    costs=money(fixed_costs)
    if costs<0:
        raise ValueError("Costurile fixe nu pot fi negative")
    result={"period":period,"method":"cost_volume_profit",
            "status":"insufficient_data","estimated_break_even_revenue":None,
            "estimated_break_even_units":None,"observed_revenue":None,
            "currency_basis":"net_of_vat" if vat_basis_confirmed else "unknown",
            "caveats":["Analiza depinde de perioada, costurile si mixul de vanzari confirmate."]}
    if not vat_basis_confirmed:
        result["caveats"].append(
          "Confirma ca preturile de vanzare si costurile sunt introduse pe baze comparabile fara TVA.")
        return result
    if not rows:
        result["caveats"].append("Lipsesc vanzarile confirmate pentru perioada aleasa.")
        return result
    summary=summarize_sales(rows)
    result["observed_revenue"]=summary["total_revenue"]
    if not summary["margin_data_complete"]:
        result["caveats"].append("Lipsesc costurile variabile pentru unele produse sau servicii.")
        return result
    revenue=money(summary["total_revenue"])
    contribution=money(summary["total_contribution"])
    if revenue<=0:
        result["caveats"].append("Veniturile confirmate nu permit calculul unui prag.")
        return result
    if contribution<=0:
        result["status"]="negative_contribution"
        result["caveats"].append(
          "Contributia este zero sau negativa: mixul observat nu acopera costurile fixe pe masura ce volumul creste.")
        return result
    required_revenue=(costs*revenue/contribution).quantize(Decimal(".01"),
                                                        rounding=ROUND_CEILING)
    result["estimated_break_even_revenue"]=float(required_revenue)
    result["observed_contribution"]=float(contribution)
    result["status"]="estimated"
    result["sales_gap_to_break_even"]=round(float(required_revenue-revenue),2)
    if len(summary["products"])==1:
        product=summary["products"][0]
        qty=money(product["quantity"])
        if qty>0:
            per_unit=contribution/qty
            if per_unit>0:
                result["estimated_break_even_units"]=int((costs/per_unit).to_integral_value(
                    rounding=ROUND_CEILING))
    else:
        result["caveats"].append(
          "Estimarea pentru mai multe produse presupune pastrarea mixului observat; nu convertim produsele diferite intr-un numar fictiv de unitati.")
    result["caveats"].append(
      "Aceasta este o estimare manageriala a acoperirii costurilor fixe, nu profit net raportat contabil.")
    return result
