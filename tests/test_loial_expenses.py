"""Verified invoice expenses: VAT separation, no estimates, tenant privacy."""
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import Column,Integer,String,create_engine
from sqlalchemy.orm import declarative_base,sessionmaker
from sqlalchemy.pool import StaticPool
from loial_expenses import install_expenses, ExpenseBase, money_minor
from loial_business_ai import BaseAI, AIDocument, install_loial_ai

@pytest.fixture
def env():
    DB=declarative_base()
    class Biz(DB):
        __tablename__="business_accounts"
        id=Column(Integer,primary_key=True)
        email=Column(String)
        name=Column(String)
        business_type=Column(String)
        plan=Column(String)
    class Customer(DB):
        __tablename__="customers"
        id=Column(Integer,primary_key=True)
        business_id=Column(Integer)
        name=Column(String)
        stamps=Column(Integer)
        last_visit=Column(String)
    class Consent(DB):
        __tablename__="consents"
        id=Column(Integer,primary_key=True)
        customer_id=Column(Integer)
        purpose=Column(String)
        granted=Column(Integer)
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},
                         poolclass=StaticPool)
    DB.metadata.create_all(engine)
    BaseAI.metadata.create_all(engine)
    ExpenseBase.metadata.create_all(engine)
    from loial_stripe_billing import BillingBase
    from loial_manual_admin import GrantBase, ManualBusinessGrant
    BillingBase.metadata.create_all(engine)
    GrantBase.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    app=FastAPI()
    install_expenses(app,engine,factory,Biz,AIDocument,"expense-test-key","HS256")
    install_loial_ai(app,engine,factory,Biz,Customer,Consent,"expense-test-key","HS256")
    with factory() as db:
        db.add_all([ManualBusinessGrant(business_id=i,active=1,actor_id=1,
                    reason="isolated test grant",updated_at="2026-11-17T00:00:00Z")
                    for i in (1,2)])
        db.add_all([Biz(id=1,email="owner1@example.invalid",name="Atelier",
                        plan="probusiness",business_type="atelier auto"),
                    Biz(id=2,email="owner2@example.invalid",name="Selfwash",
                        plan="probusiness",business_type="self wash")])
        db.add(AIDocument(business_id=1,filename="Factura test.pdf",
            sha256="A"*64,kind="pdf_text",data_json="{}",confirmed=0,
            created_at="2026-11-17T10:00:00"))
        db.commit()
        doc_id=db.query(AIDocument).first().id
    def auth(id=1):
        sub=f"owner{id}@example.invalid"
        return {"Authorization":"Bearer "+jwt.encode({"sub":sub,"role":"business"},
                                              "expense-test-key",algorithm="HS256")}
    return TestClient(app),factory,auth,doc_id

def payload(doc=None,ref="INV-100",basis="gross",amount=119):
    return {"document_id":doc,"invoice_ref":ref,"supplier":"Furnizor verificat",
            "incurred_on":"2026-11-12","category":"supplies",
            "amount":amount,"vat_basis":basis,"currency":"RON",
            "owner_confirmed":True}

def test_confirmation_requires_owner_review_and_same_business_document(env):
    client,db,auth,doc=env
    assert client.post("/api/loial-expenses/confirm",json=payload(doc)).status_code==401
    no_review=payload(doc);no_review["owner_confirmed"]=False
    assert client.post("/api/loial-expenses/confirm",headers=auth(),
                       json=no_review).status_code==422
    assert client.post("/api/loial-expenses/confirm",headers=auth(2),
                       json=payload(doc)).status_code==404
    saved=client.post("/api/loial-expenses/confirm",headers=auth(),
                      json=payload(doc))
    assert saved.status_code==200,saved.text
    assert saved.json()["ai_calls"]==0
    assert client.post("/api/loial-expenses/confirm",headers=auth(),
                       json=payload(doc)).status_code==409
    same_ref_other_supplier=payload(None)
    same_ref_other_supplier["supplier"]="Alt furnizor"
    assert client.post("/api/loial-expenses/confirm",headers=auth(),
                       json=same_ref_other_supplier).status_code==200

def test_mixed_vat_bases_and_currencies_not_summed_together(env):
    client,db,auth,doc=env
    assert client.post("/api/loial-expenses/confirm",headers=auth(),
                       json=payload(doc,"INV-100","gross",119)).status_code==200
    other=payload(None,"INV-101","net",100)
    assert client.post("/api/loial-expenses/confirm",headers=auth(),
                       json=other).status_code==200
    euro=payload(None,"INV-102","gross",50)
    euro["currency"]="EUR"
    assert client.post("/api/loial-expenses/confirm",headers=auth(),json=euro).status_code==200
    summary=client.get("/api/loial-expenses/summary?period=2026-11",headers=auth())
    assert summary.status_code==200,summary.text
    assert len(summary.json()["totals"])==3
    assert {x["total"] for x in summary.json()["totals"]}=={119,100,50}
    report=client.get("/api/loial-ai/report",headers=auth())
    assert report.status_code==200,report.text
    assert report.json()["verified_expenses"]["confirmed_rows"]==3
    assert client.get("/api/loial-expenses/summary",headers=auth(2)).json()["items"]==0

def test_void_is_audited_and_excluded_from_report(env):
    client,db,auth,doc=env
    item=client.post("/api/loial-expenses/confirm",headers=auth(),
                     json=payload(doc)).json()
    expense_id=item["id"]
    assert client.post(f"/api/loial-expenses/{expense_id}/void",
                       headers=auth(2)).status_code==404
    assert client.post(f"/api/loial-expenses/{expense_id}/void",
                       headers=auth()).json()["status"]=="voided"
    assert client.get("/api/loial-expenses/summary",
                      headers=auth()).json()["items"]==0
    assert client.get("/api/loial-expenses/recent",
                      headers=auth()).json()[0]["voided"] is True

def test_rounding_category_and_future_date_validation(env):
    client,db,auth,doc=env
    for changes in (
        {"amount":1.999},{"amount":-10},{"category":"imaginary"},
        {"vat_basis":"unknown"},{"incurred_on":"2099-01-01"}
    ):
        req=payload(None,ref="INV-ERROR")
        req.update(changes)
        assert client.post("/api/loial-expenses/confirm",headers=auth(),
                           json=req).status_code==422
    assert money_minor(Decimal("1.20"))==120
