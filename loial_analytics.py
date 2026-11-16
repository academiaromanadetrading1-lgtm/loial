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
    total = sum(p["revenue"] for p in products)
    running = 0.0
    out = []
    for product in sorted(products, key=lambda p: p["revenue"], reverse=True):
        running += product["revenue"]
        share = 100.0 * running / total if total else 0
        out.append({"product": product["product"], "share_cumulative_pct": round(share, 1),
                    "class": "A" if share <= 80 else "B" if share <= 95 else "C"})
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
