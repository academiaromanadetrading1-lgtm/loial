"""Deterministic academic business methods and cost-volume-profit estimates."""
import pytest

from loial_analytics import break_even_analysis
from loial_academic_methods import retrieve, context_for, bibliography_for


def sales(product="Revizie",quantity=10,price=200,cost=80):
    return [{"product":product,"quantity":quantity,"unit_price":price,
             "unit_variable_cost":cost,"sold_at":"2026-11-12"}]


def test_single_product_break_even_is_computed_only_from_verified_costs():
    result=break_even_analysis(sales(),fixed_costs=1200,
                               period="2026-11",vat_basis_confirmed=True)
    assert result["status"]=="estimated"
    assert result["estimated_break_even_revenue"]==2000
    assert result["estimated_break_even_units"]==10
    assert result["observed_revenue"]==2000
    assert result["sales_gap_to_break_even"]==0


def test_mixed_product_break_even_is_revenue_only_without_fake_units():
    result=break_even_analysis(sales("Revizie",10,200,80)+
                               sales("Piese",8,50,25),fixed_costs=1200,
                               period="2026-11",vat_basis_confirmed=True)
    assert result["status"]=="estimated"
    assert result["estimated_break_even_units"] is None
    assert any("mixului" in c for c in result["caveats"])


def test_missing_costs_do_not_become_zero():
    result=break_even_analysis(sales(cost=None),1200,"2026-11",True)
    assert result["status"]=="insufficient_data"
    assert result["estimated_break_even_revenue"] is None
    assert any("costurile variabile" in c.lower() for c in result["caveats"])


def test_vat_basis_must_be_confirmed_explicitly():
    result=break_even_analysis(sales(),1200,"2026-11",False)
    assert result["status"]=="insufficient_data"
    assert result["estimated_break_even_units"] is None
    assert any("TVA" in c for c in result["caveats"])


def test_negative_contribution_cannot_pay_fixed_expenses():
    result=break_even_analysis(sales(price=80,cost=95),
                               1000,"2026-11",True)
    assert result["status"]=="negative_contribution"
    assert result["estimated_break_even_revenue"] is None


def test_period_and_cost_validation():
    with pytest.raises(ValueError):
        break_even_analysis(sales(),-1,"2026-11",True)
    with pytest.raises(ValueError):
        break_even_analysis(sales(),500,"2026-13",True)
    with pytest.raises(ValueError):
        break_even_analysis(sales(),500,"2026-X",True)


def test_retrieval_matches_industry_and_topic():
    refs=retrieve("invoices","patiserie")
    assert any(m.key=="stock_value" for m in refs)
    unrelated=retrieve("invoices","rideshare")
    assert all(m.key!="stock_value" for m in unrelated)


def test_internal_context_flags_missing_data_and_separates_claims():
    text=context_for("margin","atelier_auto",confirmed_sales=False,
                     confirmed_costs=False)
    assert "Nu există suficiente vânzări" in text
    assert "nu afirma profitabilitate" in text
    assert "formule" in text
    assert all("http" not in line for line in text.splitlines())
    bibliography=bibliography_for("margin","atelier_auto")
    assert bibliography
    assert all(r["source"].startswith("https://") for r in bibliography)
