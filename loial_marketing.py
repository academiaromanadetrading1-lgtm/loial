"""Sabloane de comunicare Loial, pregatite pentru aprobare, fara trimitere implicita."""
from datetime import date, datetime

TEMPLATES = {
    "welcome": {
        "label": "Bun venit",
        "subject": "Bine ai venit la {business}",
        "body": "Bine ai venit, {name}! Cardul tau de fidelitate la {business} este activ. Te asteptam cu drag!",
        "commercial": False,
    },
    "thank_you": {
        "label": "Multumim pentru cumparatura",
        "subject": "Multumim ca ai ales {business}",
        "body": "Multumim, {name}, pentru vizita! Ai acum {stamps} din {target} stampile.",
        "commercial": False,
    },
    "welcome_back": {
        "label": "Bine ai revenit",
        "subject": "Bine ai revenit la {business}",
        "body": "Bine ai revenit, {name}! Ne bucuram ca ne-ai vizitat din nou.",
        "commercial": False,
    },
    "remaining": {
        "label": "Mai ai cateva stampile",
        "subject": "Progresul cardului tau la {business}",
        "body": "Salut, {name}! Mai ai {remaining} stampile pana la recompensa oferita de {business}.",
        "commercial": False,
    },
    "reward": {
        "label": "Recompensa disponibila",
        "subject": "Ai deblocat o recompensa la {business}",
        "body": "Felicitari, {name}! Ai deblocat recompensa: {reward}. Prezinta cardul Loial la locatie.",
        "commercial": False,
    },
    "reactivation": {
        "label": "Reactivare client",
        "subject": "Te asteptam din nou la {business}",
        "body": "Salut, {name}! Ne-ar face placere sa te revedem la {business}. {offer}",
        "commercial": True,
    },
    "product_offer": {
        "label": "Oferta pentru un produs preferat",
        "subject": "O oferta de la {business}",
        "body": "Salut, {name}! Avem o oferta noua pentru {product}. {offer}",
        "commercial": True,
    },
}

class SafeFormat(dict):
    def __missing__(self, key):
        return "{" + key + "}"

def render(template_key, values):
    template = TEMPLATES.get(template_key)
    if not template:
        raise KeyError("Sablon necunoscut")
    allowed = {"business", "name", "stamps", "target", "remaining",
               "reward", "product", "offer"}
    fields = SafeFormat({k: str(v)[:300] for k, v in values.items() if k in allowed})
    return {
        "label": template["label"],
        "subject": template["subject"].format_map(fields),
        "text": template["body"].format_map(fields),
        "requires_marketing_permission": template["commercial"],
        "sent": False,
    }

def eligible_segment(customers, segment, consented_ids, reference_date=None):
    """Returneaza doar clienti cu consimtamant de marketing explicit."""
    ref = reference_date or date.today()
    found = []
    for c in customers:
        if c.id not in consented_ids or not c.email:
            continue
        try:
            last = datetime.fromisoformat(str(c.last_visit).replace("Z", "+00:00")).date()
            days = (ref - last).days
        except (TypeError, ValueError):
            continue
        ok = {
            "all": True,
            "active_0_7": days <= 7,
            "inactive_8_30": 8 <= days <= 30,
            "inactive_31_90": 31 <= days <= 90,
            "inactive_91_365": 91 <= days <= 365,
        }.get(segment, False)
        if ok:
            found.append(c)
    return found
