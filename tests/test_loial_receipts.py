"""One-use receipt QR: merchant ownership, client ownership, refunds, actual products."""
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from loial_business_ai import BaseAI, install_loial_ai
from loial_inbox import InboxBase, issue_wallet_access
from loial_receipts import install_receipts, ReceiptBase, Receipt
from loial_wallet_sync import BaseSync, WalletSyncItem
from loial_apple_updates import AppleBase

@pytest.fixture
def setup_receipts():
    Base=declarative_base()
    class Business(Base):
        __tablename__="business_accounts"
        id=Column(Integer,primary_key=True)
        name=Column(String(120))
        email=Column(String(120),unique=True)
        business_type=Column(String(90))
        plan=Column(String(50))
        reward_text=Column(String(200))
        stamps_required=Column(Integer)
    class Customer(Base):
        __tablename__="customers"
        id=Column(Integer,primary_key=True)
        business_id=Column(Integer)
        uuid=Column(String(120))
        wallet_uuid=Column(String(120))
        name=Column(String(120))
        email=Column(String(150))
        phone=Column(String(80))
        stamps=Column(Integer)
        last_visit=Column(String(40))
    class Consent(Base):
        __tablename__="consents"
        id=Column(Integer,primary_key=True)
        customer_id=Column(Integer)
        purpose=Column(String(100))
        granted=Column(Integer)
        date=Column(String(40))
        ip=Column(String(40))
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},
                         poolclass=StaticPool)
    Base.metadata.create_all(engine)
    InboxBase.metadata.create_all(engine)
    ReceiptBase.metadata.create_all(engine)
    BaseSync.metadata.create_all(engine)
    AppleBase.metadata.create_all(engine)
    BaseAI.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    app=FastAPI()
    from loial_business_ai import AIDocument, AISale
    install_receipts(app,engine,factory,Business,Customer,AIDocument,AISale,
                     "secure-only-for-tests","HS256")
    install_loial_ai(app,engine,factory,Business,Customer,Consent,
                     "secure-only-for-tests","HS256")
    with factory() as db:
        db.add_all([
            Business(id=1,name="Atelier",
                     email="owner1@test.invalid",business_type="atelier auto",
                     plan="probusiness",reward_text="Revizie gratuita",stamps_required=6),
            Business(id=2,name="Spalatorie",
                     email="owner2@test.invalid",business_type="self wash",
                     plan="probusiness",reward_text="Spalare gratuita",stamps_required=6),
            Customer(id=1,business_id=1,uuid="wallet-1",
                     wallet_uuid="wallet-1",name="Client A",
                     email=None,phone=None,stamps=1,last_visit="2026-11-10"),
            Customer(id=2,business_id=1,uuid="wallet-2",
                     wallet_uuid="wallet-2",name="Client B",
                     email=None,phone=None,stamps=0,last_visit="2026-11-10")])
        db.commit()
        token_a=issue_wallet_access(db,"wallet-1",True)
        token_b=issue_wallet_access(db,"wallet-2",True)
        db.commit()
    def biz_headers(email="owner1@test.invalid"):
        return {"Authorization":"Bearer "+jwt.encode(
            {"sub":email,"role":"business"},"secure-only-for-tests",algorithm="HS256")}
    def wallet_headers(token):
        return {"X-Loial-Wallet-Token":token}
    return TestClient(app),factory,Receipt,token_a,token_b,biz_headers,wallet_headers

def receipt_payload(ref="B-100"):
    return {"receipt_ref":ref,"lines":[
        {"product":"Revizie auto","quantity":1,"unit_price":200.0,"unit_variable_cost":85.0},
        {"product":"Filtru","quantity":2,"unit_price":25.0,"unit_variable_cost":9.0}]}

def test_receipt_is_once_per_firm_and_requires_owner(setup_receipts):
    client,_,_,a,b,owner,wallet=setup_receipts
    assert client.post("/api/loial-receipts/issue",json=receipt_payload()).status_code==401
    response=client.post("/api/loial-receipts/issue",headers=owner(),json=receipt_payload())
    assert response.status_code==200,response.text
    assert response.json()["total"]==250.0
    assert response.json()["claim_url"].startswith("https://loial.space/loial-receipt.html?token=")
    assert response.json()["qr_png_base64"].startswith("data:image/png;base64,")
    duplicate=client.post("/api/loial-receipts/issue",headers=owner(),json=receipt_payload())
    assert duplicate.status_code==409
    # Different merchant has independent receipt numbers.
    separate=client.post("/api/loial-receipts/issue",
                         headers=owner("owner2@test.invalid"),json=receipt_payload())
    assert separate.status_code==200

def test_private_wallet_claim_is_single_use_and_links_product_history(setup_receipts):
    client,db_factory,_,token_a,token_b,owner,wallet=setup_receipts
    issued=client.post("/api/loial-receipts/issue",headers=owner(),
                       json=receipt_payload()).json()
    qr_token=issued["claim_url"].split("token=")[1]
    preview=client.get("/api/loial-receipts/preview",params={"token":qr_token})
    assert preview.status_code==200
    assert preview.json()["products"][0]["name"]=="Revizie auto"
    assert "customer" not in preview.json()
    assert client.post("/api/loial-receipts/claim",
                       json={"receipt_token":qr_token}).status_code==401
    claim=client.post("/api/loial-receipts/claim",
        headers=wallet(token_a),json={"receipt_token":qr_token})
    assert claim.status_code==200,claim.text
    assert claim.json()["stamps"]==2
    assert claim.json()["linked_products"]==2
    again=client.post("/api/loial-receipts/claim",
        headers=wallet(token_b),json={"receipt_token":qr_token})
    assert again.status_code==409
    report=client.get("/api/loial-ai/report",headers=owner()).json()
    assert report["sales"]["total_revenue"]==250
    bought=client.get("/api/loial-ai/customers/1/purchases",headers=owner()).json()
    assert len(bought["purchases"])==2
    other=client.get("/api/loial-ai/customers/2/purchases",headers=owner()).json()
    assert other["purchases"]==[]

def test_refund_excludes_sale_and_reverses_latest_unredeemed_stamp(setup_receipts):
    client,db_factory,Receipt,token_a,token_b,owner,wallet=setup_receipts
    token=client.post("/api/loial-receipts/issue",headers=owner(),
                      json=receipt_payload()).json()["claim_url"].split("token=")[1]
    claim=client.post("/api/loial-receipts/claim",
                      headers=wallet(token_a),json={"receipt_token":token})
    assert claim.status_code==200
    refund=client.post("/api/loial-receipts/refund",headers=owner(),
           json={"receipt_ref":"B-100","reason":"Returnare integrala"})
    assert refund.status_code==200,refund.text
    assert refund.json()["financial_data_excluded"] is True
    assert refund.json()["loyalty_review_required"] is False
    assert refund.json()["stamp_reversed"] is True
    report=client.get("/api/loial-ai/report",headers=owner()).json()
    assert report["sales"]["total_revenue"]==0
    assert client.get("/api/loial-ai/customers/1/purchases",headers=owner()).json()["purchases"]==[]
    assert client.post("/api/loial-receipts/claim",headers=wallet(token_b),
        json={"receipt_token":token}).status_code==409

def test_refund_requires_manual_review_when_newer_purchase_exists(setup_receipts):
    client,db_factory,Receipt,token_a,token_b,owner,wallet=setup_receipts
    for ref in ("B-001","B-002"):
        issued=client.post("/api/loial-receipts/issue",headers=owner(),
                           json=receipt_payload(ref)).json()
        key=issued["claim_url"].split("token=")[1]
        claimed=client.post("/api/loial-receipts/claim",headers=wallet(token_a),
                            json={"receipt_token":key})
        assert claimed.status_code==200,claimed.text
    earlier=client.post("/api/loial-receipts/refund",headers=owner(),
                json={"receipt_ref":"B-001","reason":"Retur la prima achizitie"})
    assert earlier.status_code==200,earlier.text
    assert earlier.json()["stamp_reversed"] is False
    assert earlier.json()["loyalty_review_required"] is True
    with db_factory() as db:
        from loial_scans import StampAward
        assert db.query(StampAward).filter(StampAward.source=="refund").count()==0
    report=client.get("/api/loial-ai/report",headers=owner()).json()
    assert report["sales"]["total_revenue"]==250
    repeat=client.post("/api/loial-receipts/refund",headers=owner(),
               json={"receipt_ref":"B-001","reason":"Retur repetat"})
    assert repeat.json()["status"]=="already_refunded"


def test_wrong_merchant_cannot_refund_or_see_receipt(setup_receipts):
    client,_,_,a,b,owner,wallet=setup_receipts
    client.post("/api/loial-receipts/issue",headers=owner(),json=receipt_payload())
    other=client.post("/api/loial-receipts/refund",headers=owner("owner2@test.invalid"),
                      json={"receipt_ref":"B-100","reason":"Nu apartine firmei"})
    assert other.status_code==404
    assert client.get("/api/loial-receipts/recent",
                      headers=owner("owner2@test.invalid")).json()==[]

def test_invalid_totals_and_missing_wallet_are_rejected(setup_receipts):
    client,_,_,token_a,token_b,owner,wallet=setup_receipts
    bad=receipt_payload("B-ERR")
    bad["lines"][0]["quantity"]=-1
    assert client.post("/api/loial-receipts/issue",
       headers=owner(),json=bad).status_code==422
    assert client.get("/api/loial-receipts/preview",params={"token":"Z"*43}).status_code==404
