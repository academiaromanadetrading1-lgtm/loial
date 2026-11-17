"""Small, auditable retrieval library of management accounting methods for Loial.

Theory is retrieved by task/sector, then numerical outcomes come ONLY from
deterministic calculations on confirmed merchant data. Sources are official
ACCA and IFRS explanatory resources; this library is not a substitute for
local Romanian accounting/tax rules. Bibliography stays internal.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Method:
    key: str
    title: str
    topics: tuple
    sectors: tuple
    inputs: tuple
    decision: str
    limitation: str
    source: str

ACCA_CVP="https://www.accaglobal.com/uk/en/student/exam-support-resources/fundamentals-exams-study-resources/f5/technical-articles/CVP-analysis.html"
ACCA_RELEVANT="https://www.accaglobal.com/gb/en/student/exam-support-resources/fundamentals-exams-study-resources/f5/technical-articles/relevant-costs.html"
ACCA_PERFORMANCE="https://www.accaglobal.com/gb/en/student/exam-support-resources/professional-exams-study-resources/p5/technical-articles/moving-up-from-paper-f5-to-paper-p5.html"
IFRS_INVENTORIES="https://www.ifrs.org/issued-standards/list-of-standards/ias-2-inventories/"

METHODS=(
    Method("contribution","Contribuție pe produs",
        ("products","margin","performance","weekly"),("*",),
        ("sales","unit_variable_cost"),
        "Separă produsul care aduce cea mai mare contribuție totală de produsul cu cea mai mare contribuție unitară.",
        "Nu numi contribuția profit net; lipsesc costurile fixe, impozitele și alte cheltuieli.",
        ACCA_CVP),
    Method("break_even","Prag de rentabilitate",
        ("margin","performance","weekly"),("*",),
        ("unit_variable_cost","fixed_costs","period","sales_mix"),
        "Estimează volumul necesar pentru acoperirea costurilor fixe pentru perioada și mixul verificate.",
        "Nu calcula pragul dacă nu există contribuție unitară pozitivă și costuri fixe comparabile.",
        ACCA_CVP),
    Method("relevant_cost","Costuri relevante pentru decizii",
        ("products","margin","performance","campaign"),("*",),
        ("incremental_costs","incremental_revenue"),
        "La acceptarea unei comenzi sau reduceri analizează costurile și veniturile pe care decizia le modifică.",
        "Costurile istorice irecuperabile nu trebuie prezentate ca plăți noi cauzate de decizie.",
        ACCA_RELEVANT),
    Method("stock_value","Evaluarea și riscul stocurilor",
        ("products","slow","invoices","weekly"),("retail","patiserie","restaurant","ecommerce","atelier_auto"),
        ("inventory_quantities","purchase_costs","estimated_realizable_value"),
        "Identifică articole cu rotație slabă și solicită cost, cantitate, preț posibil de vânzare și costuri necesare vânzării.",
        "IAS 2 privește raportarea IFRS, nu înlocuiește regulile locale aplicabile; nu presupune cost sau depreciere fără documente.",
        IFRS_INVENTORIES),
    Method("variances","Comparabilitate și abateri",
        ("performance","weekly","slow"),("*",),
        ("period_1","period_2","days_compared"),
        "Compară perioade comparabile, explică volumul, prețul și costul separat dacă există informații.",
        "O schimbare între două perioade nu dovedește cauza; notează sezonalitatea și datele lipsă.",
        ACCA_PERFORMANCE),
    Method("capacity","Capacitatea și resursele limitative",
        ("performance","products","margin","weekly"),("atelier_auto","self_wash","salon","restaurant","rideshare"),
        ("available_hours","productive_hours","utilization"),
        "Compară utilizarea capacității cu cererea și contribuția, înainte de a sugera personal sau echipamente suplimentare.",
        "Fără ore și costuri operaționale nu estima oportunitatea investiției.",
        ACCA_PERFORMANCE),
    Method("retention","Revenirea clienților",
        ("customers","campaign","weekly"),("*",),
        ("customer_visits","period","consent"),
        "Separă clienții recenți de cei inactivi și propune mesaje Loial pentru cei care permit oferte.",
        "Revenirea după campanie nu demonstrează efectul campaniei; folosește comparații și grupuri de control când există.",
        ACCA_PERFORMANCE),
)

def retrieve(topic, sector, max_results=5):
    sector=(sector or "general").lower()
    candidates=[m for m in METHODS if (topic in m.topics or topic=="general") and
               ("*" in m.sectors or sector in m.sectors)]
    # Focus on task-specific sources first, while keeping repeatability.
    return candidates[:max(1,min(int(max_results),8))]

def context_for(topic,sector,confirmed_sales=False,confirmed_costs=False):
    methods=retrieve(topic,sector)
    parts=[
      "Bibliotecă metodologică internă, selectată pentru întrebarea curentă.",
      "Prezintă doar concluziile, datele și limitările; nu divulga metode interne, surse ascunse sau formule.",
      "Fiecare valoare numerică provine numai din calculele determinate asupra datelor confirmate.",
      "Separă date confirmate, extrageri neconfirmate, calcule și date lipsă.",
    ]
    if not confirmed_sales:
        parts.append("Nu există suficiente vânzări confirmate; cere doar exportul necesar.")
    if not confirmed_costs:
        parts.append("Costurile variabile nu sunt confirmate complet; nu afirma profitabilitate totală.")
    for m in methods:
        parts.append("Metodă: "+m.title+
                     ". Decizie: "+m.decision+
                     " Limitare: "+m.limitation+
                     " Date necesare: "+", ".join(m.inputs)+".")
    return "\n".join(parts[:12])

def bibliography_for(topic,sector):
    # For internal audit and academic review; never claim source text has been copied.
    return [{"method":m.key,"source":m.source} for m in retrieve(topic,sector)]
