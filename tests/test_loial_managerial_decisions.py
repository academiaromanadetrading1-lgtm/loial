"""Deterministic management-accounting checks for Loial AI reports."""
from loial_analytics import abc_products, summarize_sales, manager_findings


def test_abc_single_dominant_product_is_a_not_c():
    result=abc_products([{"product":"Service A","revenue":1000.0}])
    assert result==[{"product":"Service A","share_cumulative_pct":100.0,"class":"A"}]


def test_abc_keeps_threshold_crossing_product_in_starting_category():
    products=[
        {"product":"A","revenue":900.0},
        {"product":"B","revenue":70.0},
        {"product":"C","revenue":30.0},
        {"product":"No sales","revenue":0.0},
    ]
    ranked=abc_products(products)
    assert [p["class"] for p in ranked]==["A","B","C","C"]
    assert ranked[0]["share_cumulative_pct"]==90.0


def test_manager_recommends_unit_contribution_and_total_contribution_separately():
    rows=[
        {"product":"Popular","quantity":10,"unit_price":90,
         "unit_variable_cost":80},
        {"product":"Premium","quantity":1,"unit_price":100,
         "unit_variable_cost":1},
    ]
    summary=summarize_sales(rows)
    notes=manager_findings(summary,"atelier_auto")
    texts=[p["text"] for p in notes]
    assert any("cea mai mare contributie totala" in t.lower() and "Popular" in t
               for t in texts)
    assert any("cea mai mare contributie estimata pe unitate" in t.lower()
               and "Premium" in t for t in texts)
    assert not any("profit net" in t.lower() and "100" in t for t in texts)


def test_known_negative_unit_contribution_triggers_check_not_guaranteed_causality():
    rows=[
        {"product":"Retete","quantity":2,"unit_price":30,
         "unit_variable_cost":45},
        {"product":"Cafea","quantity":10,"unit_price":15,
         "unit_variable_cost":5},
    ]
    findings=manager_findings(summarize_sales(rows),"patiserie")
    assert any(p["type"]=="risk" and "Retete" in p["text"] for p in findings)


def test_absent_costs_cannot_be_presented_as_total_margin():
    rows=[
        {"product":"Tuns","quantity":10,"unit_price":50,
         "unit_variable_cost":None},
        {"product":"Spalat","quantity":2,"unit_price":30,
         "unit_variable_cost":10},
    ]
    summary=summarize_sales(rows)
    assert summary["total_contribution"] is None
    findings=manager_findings(summary,"salon")
    assert any(p["type"]=="missing" for p in findings)
