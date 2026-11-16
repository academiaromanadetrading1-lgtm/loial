"""Regresii Loial AI. Ruleaza cu: python -m pytest tests/test_loial_ai_core.py -q"""
import csv
import io
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from loial_industries import canonical, profile, weekly_request
from loial_analytics import summarize_sales, customer_segments, sector_summary
from loial_business_ai import install_loial_ai, parse_sales_csv

def test_rideshare_matches_uber_bolt_and_no_pastry_fields():
    assert canonical("Sofer Uber / Bolt") == "rideshare"
    assert "ore online" in profile("rideshare")["units"]
    assert "kilometri" in weekly_request("bolt").lower()
    assert "croissant" not in weekly_request("bolt").lower()

def test_car_repair_and_self_wash_are_distinct():
    assert canonical("atelier auto") == "atelier_auto"
    assert canonical("spalatorie auto self wash") == "self_wash"
    assert "manopera" in " ".join(profile("atelier_auto")["metrics"])
    assert "boxa" in " ".join(profile("self_wash")["metrics"])

def test_unknown_business_asks_not_guesses():
    assert canonical("firma mea") == "general"
    assert profile("general")["questions"]

def test_missing_cost_does_not_turn_into_profit():
    s = summarize_sales([{"product":"cafea", "quantity":3, "unit_price":9,
                          "unit_variable_cost":None, "sold_at":"2026-11-15"}])
    assert s["total_revenue"] == 27
    assert s["total_contribution"] is None
    assert s["products"][0]["contribution"] is None

def test_sectors_use_only_known_operational_data():
    rideshare = sector_summary("rideshare", [], {"revenue": 400, "online_hours": 10,
                                                  "kilometres": 100, "platform_fees": 80, "fuel_energy": 55})
    assert rideshare["sector_metrics"]["revenue_per_hour"] == 40
    assert rideshare["sector_metrics"]["revenue_per_km"] == 4
    assert rideshare["sector_metrics"]["after_platform_and_energy"] == 265
    wash = sector_summary("self_wash", [], {"revenue": 240, "wash_cycles": 20, "active_bays": 3})
    assert wash["sector_metrics"]["revenue_per_cycle"] == 12
    assert wash["sector_metrics"]["revenue_per_bay"] == 80

def test_last_visit_buckets_and_missing_date():
    customers = [SimpleNamespace(last_visit="2026-11-13"),
                 SimpleNamespace(last_visit="2026-10-01"),
                 SimpleNamespace(last_visit=None)]
    x = customer_segments(customers, date(2026, 11, 16))
    assert x["active_0_7"] == 1
    assert x["inactive_31_90"] == 1
    assert x["unknown"] == 1

def test_csv_preview_requires_explicit_cost_and_date():
    raw = "sold_at,product,quantity,unit_price\n2026-11-12,cafea,2,10\n"
    parsed = parse_sales_csv(raw.encode())
    assert parsed["kind"] == "sales"
    assert parsed["rows"][0]["unit_variable_cost"] is None
    with pytest.raises(ValueError):
        parse_sales_csv(b"product,quantity,unit_price\ncafea,2,10")

@pytest.fixture
def app_client(monkeypatch):
    for key in ("LOIAL_AI_OPENAI_API_KEY", "LOIAL_AI_INPUT_USD_PER_M",
                "LOIAL_AI_OUTPUT_USD_PER_M", "LOIAL_AI_USD_TO_EUR"):
        monkeypatch.delenv(key, raising=False)
    DB = declarative_base()
    class Biz(DB):
        __tablename__ = "business_accounts"
        id = Column(Integer, primary_key=True)
        email = Column(String, unique=True)
        name = Column(String)
        business_type = Column(String)
        plan = Column(String)
    class Customer(DB):
        __tablename__ = "customers"
        id = Column(Integer, primary_key=True)
        business_id = Column(Integer)
        name = Column(String)
        email = Column(String)
        uuid = Column(String)
        wallet_uuid = Column(String)
        last_visit = Column(String)
        stamps = Column(Integer)
    class Consent(DB):
        __tablename__ = "consents"
        id = Column(Integer, primary_key=True)
        customer_id = Column(Integer)
        purpose = Column(String)
        granted = Column(Integer)
    engine = create_engine("sqlite://", connect_args={"check_same_thread":False},
                           poolclass=StaticPool)
    DB.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        db.add_all([Biz(id=1, email="owner1@test.invalid", name="Taxi",
                        business_type="uber", plan="probusiness"),
                    Biz(id=2, email="owner2@test.invalid", name="Garaj",
                        business_type="atelier auto", plan="probusiness"),
                    Biz(id=3, email="free@test.invalid", name="Free",
                        business_type="patiserie", plan="free")])
        db.add(Customer(id=1,business_id=1,name="Client Taxi",email="taxi@test.invalid",
                        uuid="w1",wallet_uuid="w1",last_visit="2026-11-10",stamps=1))
        db.add(Customer(id=2,business_id=2,name="Client Garaj",email="garage@test.invalid",
                        uuid="w2",wallet_uuid="w2",last_visit="2026-11-10",stamps=2))
        db.add(Consent(id=1,customer_id=1,purpose="personalized_ads",granted=1))
        db.commit()
    app = FastAPI()
    install_loial_ai(app, engine, factory, Biz, Customer, Consent, "test-secret", "HS256")
    def headers(email, role="business"):
        return {"Authorization": "Bearer " + jwt.encode(
            {"sub":email,"role":role}, "test-secret", algorithm="HS256")}
    return TestClient(app), headers

def test_business_scoping_and_premium_entitlement(app_client):
    client, auth = app_client
    assert client.get("/api/loial-ai/context", headers=auth("free@test.invalid")).status_code == 403
    assert client.get("/api/loial-ai/context", headers=auth("owner1@test.invalid", "admin")).status_code == 403
    assert client.get("/api/loial-ai/context").status_code == 401
    assert client.get("/api/loial-ai/context",headers=auth("owner1@test.invalid")).json()["industry"]["key"] == "rideshare"
    assert client.get("/api/loial-ai/context",headers=auth("owner2@test.invalid")).json()["industry"]["key"] == "atelier_auto"

def test_sales_confirmation_cannot_cross_tenant(app_client):
    client, auth = app_client
    csvdata=b"sold_at,transaction_id,product,quantity,unit_price\n2026-11-11,receipt1,Transport,1,100\n"
    upload=client.post("/api/loial-ai/documents",headers=auth("owner1@test.invalid"),
                       files={"file":("sales.csv",csvdata,"text/csv")})
    assert upload.status_code == 200, upload.text
    doc=upload.json()["id"]
    other=client.post("/api/loial-ai/documents/"+str(doc)+"/confirm",
                      headers=auth("owner2@test.invalid"))
    assert other.status_code == 404
    mine=client.post("/api/loial-ai/documents/"+str(doc)+"/confirm",
                     headers=auth("owner1@test.invalid"))
    assert mine.status_code == 200
    assert client.post("/api/loial-ai/documents/"+str(doc)+"/confirm",
                       headers=auth("owner1@test.invalid")).json()["status"] == "already_confirmed"
    own_report=client.get("/api/loial-ai/report",headers=auth("owner1@test.invalid")).json()
    other_report=client.get("/api/loial-ai/report",headers=auth("owner2@test.invalid")).json()
    assert own_report["sales"]["total_revenue"] == 100
    assert other_report["sales"]["total_revenue"] == 0
    assert b"Transport" not in client.get("/api/loial-ai/exports/sales.csv",
                                          headers=auth("owner2@test.invalid")).content

def test_ads_export_requires_specific_consent(app_client):
    client, auth = app_client
    a=client.get("/api/loial-ai/exports/ads-consented.csv",headers=auth("owner1@test.invalid"))
    b=client.get("/api/loial-ai/exports/ads-consented.csv",headers=auth("owner2@test.invalid"))
    assert b"taxi@test.invalid" in a.content
    assert b"garage@test.invalid" not in b.content

def test_campaign_approval_never_sends(app_client):
    client, auth = app_client
    headers=auth("owner1@test.invalid")
    result=client.post("/api/loial-ai/campaigns",headers=headers,
        json={"objective":"revenire clienti","audience":"inactive_31_90","offer":"Revino la noi."})
    assert result.status_code == 200
    item_id=result.json()["id"]
    confirmed=client.post("/api/loial-ai/campaigns/"+str(item_id)+"/approve",headers=headers)
    assert confirmed.json()["status"] == "approved_not_sent"
    assert confirmed.json()["sent"] == 0
