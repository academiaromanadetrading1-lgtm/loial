from xml.etree import ElementTree as ET
import pytest
from loial_plans import PLANS, plan_for_amount, renewal_rate, public_catalog
from loial_growth import CITIES, LANGUAGES, sitemap_xml
from loial_stripe_billing import invoice_is_eligible

def test_catalog():
    assert [(p["code"],p["price_eur"],p["location_cap"]) for p in public_catalog()] == [
        ("start",0,1),("business",67,1),("probusiness",270,5)]
    assert PLANS["start"].customer_cap == 50
    assert PLANS["probusiness"].customer_cap is None

@pytest.mark.parametrize("count,business,pro",[(1,500,2000),(25,500,2000),(26,1000,4000),(50,1000,4000),(51,1500,6000)])
def test_commission_tiers(count,business,pro):
    assert renewal_rate("business",count)==business
    assert renewal_rate("probusiness",count)==pro

@pytest.mark.parametrize("cents",[True,0,26999,27001,6700.0])
def test_unknown_amount(cents):
    with pytest.raises(ValueError):plan_for_amount(cents)

def test_pro_activation():
    p=plan_for_amount(27000)
    assert (p.activation_cents,p.sponsor_cents)==(8000,4000)

def test_invoice_plan_is_exact():
    invoice={"status":"paid","paid":True,"currency":"eur","amount_paid":27000,
             "lines":{"data":[{"quantity":1,"price":{"id":"price_pro"}}]}}
    assert invoice_is_eligible(invoice,"price_pro",27000)
    assert not invoice_is_eligible(invoice,"price_business",27000)
    assert not invoice_is_eligible(invoice,"price_pro",6700)
    invoice["lines"]["data"][0]["quantity"]=2
    assert not invoice_is_eligible(invoice,"price_pro",27000)

def test_sitemap():
    root=ET.fromstring(sitemap_xml(["/","/demo","/demo"]))
    assert len(root)==2
    assert len(CITIES)==len(set(CITIES))==40
    assert len(LANGUAGES)==9
    assert all(node[0].text.startswith("https://loial.space/") for node in root)
