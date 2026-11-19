"""Approved commercial policy, independent of legacy plan flags."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Plan:
    code: str
    label: str
    price_cents: int
    customer_cap: int | None
    location_cap: int
    activation_cents: int
    sponsor_cents: int
    renewal_cents: tuple[int, int, int]

PLANS = {
    "start": Plan("start", "Start", 0, 50, 1, 0, 0, (0, 0, 0)),
    "business": Plan("business", "Business", 6700, None, 1, 2000, 1000, (500, 1000, 1500)),
    "probusiness": Plan("probusiness", "ProBusiness", 27000, None, 5, 4000, 4000, (2000, 4000, 6000)),
}
def plan_for_amount(cents):
    if type(cents) is not int:
        raise ValueError("Invalid amount")
    for p in PLANS.values():
        if p.price_cents == cents and cents > 0:
            return p
    raise ValueError("Unsupported subscription amount")

def renewal_rate(plan, active_firms):
    if type(active_firms) is not int or active_firms < 0:
        raise ValueError("Invalid firm count")
    return PLANS[plan].renewal_cents[2 if active_firms >= 51 else 1 if active_firms >= 26 else 0]

def public_catalog():
    return [{"code": p.code,"name":p.label,"price_eur":p.price_cents//100,
             "customer_cap":p.customer_cap,"location_cap":p.location_cap,
             "custom_quote_above_cap":p.code=="probusiness"} for p in PLANS.values()]


def simulate_portfolio(new_business=0, renewed_business=0, new_pro=0,
                       renewed_pro=0, recruited_business=0, recruited_pro=0):
    """Illustrative monthly scenario in integer cents, not actual earned commission."""
    counts=(new_business,renewed_business,new_pro,renewed_pro,recruited_business,recruited_pro)
    if any(type(n) is not int or not 0<=n<=100000 for n in counts) or sum(counts)>100000:
        raise ValueError("Invalid portfolio size")
    active=new_business+renewed_business+new_pro+renewed_pro
    b,p=PLANS["business"],PLANS["probusiness"]
    activation=new_business*b.activation_cents+new_pro*p.activation_cents
    recurring=renewed_business*renewal_rate("business",active)+renewed_pro*renewal_rate("probusiness",active)
    sponsor=recruited_business*b.sponsor_cents+recruited_pro*p.sponsor_cents
    revenue=(new_business+renewed_business+recruited_business)*b.price_cents+(new_pro+renewed_pro+recruited_pro)*p.price_cents
    return {"active_direct_firms":active,"activation_cents":activation,
            "recurring_cents":recurring,"sponsor_cents":sponsor,
            "total_commission_cents":activation+recurring+sponsor,
            "illustrative_subscription_revenue_cents":revenue,
            "scenario_only":True,"requires_verified_payment":True}
