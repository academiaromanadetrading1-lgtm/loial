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
from loial_marketing import render, eligible_segment

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

def test_ai_campaign_is_only_a_draft(app_client):
    client, auth = app_client
    headers = auth("owner1@test.invalid")
    result = client.post("/api/loial-ai/campaigns", headers=headers,
      json={"objective":"reactivare clienti", "audience":"inactive_31_90", "offer":"Revino la noi."})
    assert result.status_code == 200
    assert result.json()["status"] == "draft"
    assert result.json()["sent"] == 0

def test_template_renders_without_sending():
    preview = render("remaining", {"business": "Atelier", "name":"Alex",
                                   "stamps": 3, "target": 6, "remaining":3})
    assert "3" in preview["text"]
    assert preview["sent"] is False
    assert render("reactivation", {"business":"Atelier", "name":"Alex",
                                   "offer":"Reducere"} )["requires_marketing_permission"]

def test_email_campaign_endpoints_are_not_part_of_business_ai(app_client):
    client, auth = app_client
    headers = auth("owner1@test.invalid")
    response = client.post("/api/loial-ai/campaigns/42/send",headers=headers,
                           json={"confirmation":"TRIMITE"})
    assert response.status_code == 404

def test_campaign_and_customer_history_are_isolated(app_client):
    client, auth = app_client
    headers1 = auth("owner1@test.invalid")
    headers2 = auth("owner2@test.invalid")
    first = client.get("/api/loial-ai/customers", headers=headers1).json()
    second = client.get("/api/loial-ai/customers", headers=headers2).json()
    assert first["items"][0]["name"] == "Client Taxi"
    assert second["items"][0]["name"] == "Client Garaj"
    assert client.get("/api/loial-ai/customers/2/purchases",headers=headers1).status_code == 404
    assert client.get("/api/loial-ai/customers/1/purchases",headers=headers2).status_code == 404


def test_chat_unconfigured_is_not_a_fake_ai_answer(app_client):
    client,auth=app_client
    h=auth("owner1@test.invalid")
    assert client.get("/api/loial-ai/context",headers=h).json()["ai_status"]=="not_configured"
    result=client.post("/api/loial-ai/chat",headers=h,json={"text":"Cum cresc marja?"})
    assert result.status_code==503
    assert result.json()["detail"]["code"]=="not_configured"
    assert client.get("/api/loial-ai/history",headers=h).json()==[]


def test_provider_chat_contains_actual_latest_question_and_selected_document(app_client,monkeypatch):
    import loial_business_ai as ai
    client,auth=app_client
    h=auth("owner1@test.invalid")
    monkeypatch.setattr(ai,"provider_status",lambda usage:"configured")
    calls=[]
    async def mocked_model(system,question,usage,db,**kwargs):
        calls.append((system,question,kwargs))
        return "Para mejorar el margen necesitamos los costes variables."
    monkeypatch.setattr(ai,"ask_model",mocked_model)
    raw=b"sold_at,product,quantity,unit_price\n2026-11-11,Coffee,1,10\n"
    doc=client.post("/api/loial-ai/documents",headers=h,
        files={"file":("test.csv",raw,"text/csv")}).json()["id"]
    assert client.get(f"/api/loial-ai/documents/{doc}/preview",headers=auth("owner2@test.invalid")).status_code==404
    preview=client.get(f"/api/loial-ai/documents/{doc}/preview",headers=h)
    assert preview.status_code==200 and preview.json()["rows"][0]["product"]=="Coffee"
    data={"text":"Como mejorar el margen?","topic":"margin","language":"es","document_id":doc}
    denied=client.post("/api/loial-ai/chat",headers=auth("owner2@test.invalid"),json=data)
    assert denied.status_code==404
    result=client.post("/api/loial-ai/chat",headers=h,json=data)
    assert result.status_code==200,result.text
    assert result.json()["mode"]=="ai"
    assert len(calls)==1
    assert "Spanish" in calls[0][0]
    assert data["text"] in calls[0][1][:200]
    assert "Coffee" in calls[0][1]
    assert calls[0][2]["advanced"] is True
    history=client.get("/api/loial-ai/history",headers=h).json()
    assert len(history)==2 and history[0]["text"]==data["text"]
    async def unavailable(*args,**kwargs):return None
    monkeypatch.setattr(ai,"ask_model",unavailable)
    failed=client.post("/api/loial-ai/chat",headers=h,json={"text":"Nueva pregunta"})
    assert failed.status_code==503 and failed.json()["detail"]["code"]=="provider_unavailable"
    assert len(client.get("/api/loial-ai/history",headers=h).json())==2


def test_export_counts_respect_tenant_and_consent(app_client):
    client,auth=app_client
    first=client.get("/api/loial-ai/exports/summary",headers=auth("owner1@test.invalid"))
    second=client.get("/api/loial-ai/exports/summary",headers=auth("owner2@test.invalid"))
    assert first.json()=={"customers":1,"sales":0,"ads_consented":1}
    assert second.json()=={"customers":1,"sales":0,"ads_consented":0}
    assert client.get("/api/loial-ai/exports/customers.xlsx",headers=auth("owner1@test.invalid")).content.startswith(b"PK")


def test_modern_gpt_payload_and_cost_accounting(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import loial_business_ai as ai
    config={"LOIAL_AI_OPENAI_API_KEY":"test-key",
            "LOIAL_AI_ECONOMY_MODEL":"gpt-6-luna",
            "LOIAL_AI_ADVANCED_MODEL":"gpt-6.1-terra",
            "LOIAL_AI_INPUT_USD_PER_M":"0.10",
            "LOIAL_AI_OUTPUT_USD_PER_M":"0.50",
            "LOIAL_AI_ADVANCED_INPUT_USD_PER_M":"1.00",
            "LOIAL_AI_ADVANCED_OUTPUT_USD_PER_M":"5.00",
            "LOIAL_AI_USD_TO_EUR":"1",
            "LOIAL_AI_MONTHLY_BUDGET_EUR":"1"}
    for k,v in config.items():
        monkeypatch.setenv(k,v)
    calls=[]
    class MockClient:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,**kwargs):
            calls.append(kwargs["json"])
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{
                "choices":[{"message":{"content":"Test response"}}],
                "usage":{"prompt_tokens":1000,"completion_tokens":200}})
    monkeypatch.setattr(ai.httpx,"AsyncClient",MockClient)
    usage=SimpleNamespace(input_tokens=0,output_tokens=0,cost_eur=0.0)
    db=SimpleNamespace(commit=lambda:None)
    assert asyncio.run(ai.ask_model("system","question",usage,db))=="Test response"
    assert asyncio.run(ai.ask_model("system","question",usage,db,picture=("image/png",b"fake")) )=="Test response"
    assert [p["model"] for p in calls]==["gpt-6-luna","gpt-6.1-terra"]
    assert [p["max_completion_tokens"] for p in calls]==[1100,1800]
    assert all(p["store"] is False and p["reasoning_effort"]=="none" and "max_tokens" not in p for p in calls)
    assert abs(usage.cost_eur-0.0022)<1e-9
    usage.cost_eur=1
    assert asyncio.run(ai.ask_model("system","question",usage,db)) is None
    assert len(calls)==2


def financial_spec():
    return {"currency":"RON","basis":"Estimare lunara; toate valorile fara TVA; costuri fixe constante.",
            "transactions":3120,"average_ticket":18,"variable_cost":18700,"fixed_cost":25800,
            "target_pct":30,"scenarios":[
                {"name":"Reducere risipa","assumption":"Economii de 1750 lei fara pierdere de vanzari.",
                 "revenue_delta":0,"variable_cost_delta":-1750,"fixed_cost_delta":0},
                {"name":"Bon mediu","assumption":"Venituri +3900; costuri incrementale 402.",
                 "revenue_delta":3900,"variable_cost_delta":402,"fixed_cost_delta":0},
                {"name":"Optimizare","assumption":"Reducere de cost fix de 1000 si variabil de 2498.",
                 "revenue_delta":0,"variable_cost_delta":-2498,"fixed_cost_delta":-1000}]}


def test_simulation_deterministic_math_and_independent_scenarios():
    from decimal import Decimal
    from loial_financial_simulation import calculate,rounded
    r=calculate(financial_spec(),"RON")
    assert r["revenue"]==56160
    assert r["profit"]==11660
    assert rounded(r["margin"])==Decimal("20.76")
    assert rounded(r["breakeven"])==Decimal("38679.34")
    assert r["target"]==15158
    assert [s["profit"] for s in r["scenarios"]]==[13410,15158,15158]
    assert [s["delta"] for s in r["scenarios"]]==[1750,3498,3498]


def test_simulation_missing_or_invalid_values_are_not_zero():
    from loial_financial_simulation import calculate
    import pytest
    for key,bad in [("variable_cost",None),("fixed_cost",-1),("average_ticket",True),
                    ("average_ticket",float("nan")),("currency","EUR")]:
        spec=financial_spec();spec[key]=bad
        with pytest.raises(ValueError):calculate(spec,"RON")
    spec=financial_spec();del spec["fixed_cost"]
    with pytest.raises(KeyError):calculate(spec,"RON")
    spec=financial_spec();spec["scenarios"][0]["variable_cost_delta"]=-20000
    with pytest.raises(ValueError):calculate(spec,"RON")


def test_negative_profit_and_zero_contribution_do_not_claim_growth_target():
    from loial_financial_simulation import calculate
    spec={"currency":"RON","basis":"Conditional; comparable amounts.","revenue":100,
          "variable_cost":100,"fixed_cost":50,"target_pct":30}
    r=calculate(spec,"RON")
    assert r["profit"]==-50
    assert r["breakeven"] is None and r["target"] is None
    spec["revenue"]=0
    assert calculate(spec,"RON")["margin"] is None


def test_simulation_rendered_in_chat_and_history_without_extra_model_call(app_client,monkeypatch):
    import json
    import loial_business_ai as ai
    client,auth=app_client
    h=auth("owner1@test.invalid")
    monkeypatch.setattr(ai,"provider_status",lambda usage:"configured")
    calls=[]
    async def mocked_model(system,question,usage,db,**kwargs):
        calls.append(system)
        return "**Propuneri**\n\n```loial-simulation\n"+json.dumps(financial_spec())+"\n```"
    monkeypatch.setattr(ai,"ask_model",mocked_model)
    result=client.post("/api/loial-ai/chat",headers=h,json={"text":"Simuleaza profitul"})
    assert result.status_code==200,result.text
    answer=result.json()["answer"]
    assert len(calls)==1 and "estimari conditionale" in calls[0]
    assert "11.660,00 RON" in answer and "15.158,00 RON" in answer
    assert "```loial-chart" in answer and "```loial-simulation" not in answer
    assert client.get("/api/loial-ai/history",headers=h).json()[-1]["text"]==answer


def test_malformed_simulation_is_removed_not_rendered_as_valid():
    from loial_financial_simulation import enrich_answer
    r=enrich_answer("Text\n```loial-simulation\n{\"revenue\":100}\n```","RON","ro")
    assert "Simulare invalidă" in r and "loial-simulation" not in r
    assert "loial-chart" not in r
