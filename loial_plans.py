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
    "probusiness": Plan("probusiness", "ProBusiness", 27000, None, 5, 8000, 4000, (2000, 4000, 6000)),
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
