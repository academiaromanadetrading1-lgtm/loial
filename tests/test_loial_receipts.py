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
from loial_scans import ScanBase
from loial_friend_referrals import ReferralBase

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
        staff_pin=Column(String(4),default="7826")
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
    ScanBase.metadata.create_all(engine)
    ReferralBase.metadata.create_all(engine)
    BaseAI.metadata.create_all(engine)
    from loial_stripe_billing import BillingBase
    from loial_manual_admin import GrantBase, ManualBusinessGrant
    BillingBase.metadata.create_all(engine)
    GrantBase.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    app=FastAPI()
    from loial_business_ai import AIDocument, AISale
    install_receipts(app,engine,factory,Business,Customer,AIDocument,AISale,
                     "secure-only-for-tests","HS256")
    install_loial_ai(app,engine,factory,Business,Customer,Consent,
                     "secure-only-for-tests","HS256")
    with factory() as db:
        db.add_all([ManualBusinessGrant(business_id=i,active=1,actor_id=1,
                    reason="isolated test grant",updated_at="2026-11-17T00:00:00Z")
                    for i in (1,2)])
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
    from loial_inbox import read_customer_ids
    from loial_business_ai import AISale
    with db_factory() as db:
        assert "wallet-1" in read_customer_ids(db,1,AISale,"Revizie auto")
    refund=client.post("/api/loial-receipts/refund",headers=owner(),
           json={"receipt_ref":"B-100","reason":"Returnare integrala"})
    assert refund.status_code==200,refund.text
    assert refund.json()["financial_data_excluded"] is True
    assert refund.json()["loyalty_review_required"] is False
    assert refund.json()["stamp_reversed"] is True
    report=client.get("/api/loial-ai/report",headers=owner()).json()
    assert report["sales"]["total_revenue"]==0
    assert client.get("/api/loial-ai/customers/1/purchases",headers=owner()).json()["purchases"]==[]
    with db_factory() as db:
        assert "wallet-1" not in read_customer_ids(db,1,AISale,"Revizie auto")
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

def test_smart_receipt_requires_employee_and_is_one_use(setup_receipts,monkeypatch):
    from loial_business_ai import AISale
    from loial_receipts import SmartReservation
    from loial_scans import StampAward
    import loial_receipts
    client,factory,Receipt,a,b,owner,wallet=setup_receipts
    urls=[]
    original=loial_receipts.create_receipt_qr_png
    def capture(url):
        urls.append(url)
        return original(url)
    monkeypatch.setattr(loial_receipts,"create_receipt_qr_png",capture)
    prefix="/api/loial-receipts/"
    payload=receipt_payload("SMART-1")
    payload["requires_payment_confirmation"]=True
    issued=client.post(prefix+"issue",headers=owner(),json=payload)
    assert issued.status_code==200,issued.text
    assert issued.json()["status"]=="awaiting_payment"
    token=issued.json()["claim_url"].split("token=")[1]
    req={"receipt_token":token}
    assert client.post(prefix+"claim",headers=wallet(a),json=req).status_code==409
    assert client.post(prefix+"reserve",json=req).status_code==401
    first=client.post(prefix+"reserve",headers=wallet(a),json=req)
    assert first.status_code==200,first.text
    old=urls[-1].split("receipt_approval=")[1]
    assert client.post(prefix+"reserve",headers=wallet(b),json=req).status_code==409
    assert client.get(prefix+"payment-status",headers=wallet(b),params={"token":token}).status_code==404
    with factory() as db:
        assert db.query(AISale).count()==0
        assert db.query(StampAward).count()==0
    assert client.post(prefix+"reserve",headers=wallet(a),json=req).status_code==200
    new=urls[-1].split("receipt_approval=")[1]
    assert old!=new
    confirm={"business_id":1,"pin":"7826","approval_token":old}
    assert client.post(prefix+"confirm-payment",json=confirm).status_code==404
    confirm["approval_token"]=new
    assert client.post(prefix+"confirm-payment",json={**confirm,"pin":"1111"}).status_code==401
    assert client.post(prefix+"confirm-payment",json={**confirm,"business_id":2}).status_code==404
    result=client.post(prefix+"confirm-payment",json=confirm)
    assert result.status_code==200,result.text
    assert result.json()["stamps"]==2
    assert client.post(prefix+"confirm-payment",json=confirm).status_code==409
    assert client.post(prefix+"reserve",headers=wallet(b),json=req).status_code==409
    with factory() as db:
        assert db.query(AISale).count()==2
        assert {x.customer_uuid for x in db.query(AISale)}=={"wallet-1"}
        assert db.query(StampAward).count()==1
        assert db.query(SmartReservation).one().confirmed_at
    assert client.get(prefix+"payment-status",headers=wallet(a),params={"token":token}).json()["status"]=="claimed"

def test_smart_receipt_expired_and_cancelled(setup_receipts,monkeypatch):
    from loial_receipts import SmartReservation
    from loial_business_ai import AISale
    import loial_receipts
    client,factory,Receipt,a,b,owner,wallet=setup_receipts
    urls=[]
    monkeypatch.setattr(loial_receipts,"create_receipt_qr_png",lambda url: urls.append(url) or "test")
    prefix="/api/loial-receipts/"
    payload=receipt_payload("SMART-2")
    payload["requires_payment_confirmation"]=True
    token=client.post(prefix+"issue",headers=owner(),json=payload).json()["claim_url"].split("token=")[1]
    assert client.post(prefix+"reserve",headers=wallet(a),json={"receipt_token":token}).status_code==200
    approval=urls[-1].split("receipt_approval=")[1]
    with factory() as db:
        db.query(SmartReservation).one().approval_expires="2000-01-01T00:00:00+00:00"
        db.commit()
    req={"business_id":1,"pin":"7826","approval_token":approval}
    assert client.post(prefix+"confirm-payment",json=req).status_code==410
    assert client.post(prefix+"refund",headers=owner(),json={"receipt_ref":"SMART-2","reason":"Comanda anulata"}).status_code==200
    assert client.post(prefix+"confirm-payment",json=req).status_code==409
    with factory() as db:
        assert db.query(AISale).count()==0

def test_print_integration_scoped_reprint_and_revocation(setup_receipts):
    client,factory,Receipt,a,b,owner,wallet=setup_receipts
    p="/api/loial-receipts/"
    key=client.post(p+"integration/rotate",headers=owner()).json()["api_key"]
    headers={"X-Loial-Receipt-Key":key}
    payload=receipt_payload("PRINT-1")
    assert client.post(p+"integration/issue",json=payload).status_code==401
    first=client.post(p+"integration/issue",headers=headers,json=payload)
    assert first.status_code==200,first.text
    data=first.json()
    assert data["status"]=="awaiting_payment"
    again=client.post(p+"integration/issue",headers=headers,json=payload)
    assert again.status_code==200,again.text
    assert again.json()["claim_url"]==data["claim_url"]
    changed=receipt_payload("PRINT-1")
    changed["lines"][0]["unit_price"]=201
    assert client.post(p+"integration/issue",headers=headers,json=changed).status_code==409
    assert client.get(p+"recent",headers=owner("owner2@test.invalid")).json()==[]
    other_key=client.post(p+"integration/rotate",headers=owner("owner2@test.invalid")).json()["api_key"]
    other=client.post(p+"integration/issue",headers={"X-Loial-Receipt-Key":other_key},json=payload)
    assert other.status_code==200
    assert other.json()["claim_url"]!=data["claim_url"]
    assert client.post(p+"integration/revoke",headers=owner()).status_code==200
    assert client.post(p+"integration/issue",headers=headers,json=payload).status_code==401
    assert client.post(p+"integration/issue",headers={"X-Loial-Receipt-Key":other_key},json=payload).status_code==200

def test_crm_receipt_source_excludes_refunded_transaction(setup_receipts):
    from loial_business_ai import AISale
    client,factory,Receipt,a,b,owner,wallet=setup_receipts
    # Inspect mapped models through the fixture's SQLAlchemy registry is not needed:
    # reuse the existing receipt API and verify CRM purchase history.
    p="/api/loial-receipts/"
    issued=client.post(p+"issue",headers=owner(),json=receipt_payload("CRM-TEST"))
    assert issued.status_code==200,issued.text
    key=issued.json()["claim_url"].split("token=")[1]
    assert client.post(p+"claim",headers=wallet(a),json={"receipt_token":key}).status_code==200
    with factory() as db:
        assert db.query(AISale).filter_by(customer_uuid="wallet-1").count()==2
        assert db.query(AISale).filter_by(customer_uuid="wallet-2").count()==0
    assert client.post(p+"refund",headers=owner(),json={"receipt_ref":"CRM-TEST","reason":"Returnare totala"}).status_code==200
    with factory() as db:
        assert db.query(Receipt).filter_by(status="claimed").count()==0
