"""Legacy recovery: owner attestation, 15-minute single-use links, tenant privacy."""
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from loial_business_ai import BaseAI, AISale, AIDocument
from loial_inbox import InboxBase, WalletInboxAccess, access_hash
from loial_wallet_recovery import RecoveryBase, RecoveryTicket, install_wallet_recovery


@pytest.fixture
def fixture():
    DB=declarative_base()
    class Business(DB):
        __tablename__="business_accounts"
        id=Column(Integer,primary_key=True)
        email=Column(String)
        name=Column(String)
    class Customer(DB):
        __tablename__="customers"
        id=Column(Integer,primary_key=True)
        business_id=Column(Integer)
        uuid=Column(String,unique=True)
        wallet_uuid=Column(String)
        name=Column(String)
        stamps=Column(Integer)
        last_visit=Column(String)
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},
                         poolclass=StaticPool)
    for meta in (DB.metadata,InboxBase.metadata,BaseAI.metadata,RecoveryBase.metadata):
        meta.create_all(engine)
    factory=sessionmaker(bind=engine)
    app=FastAPI()
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address
    limiter=Limiter(key_func=get_remote_address)
    app.state.limiter=limiter
    app.add_exception_handler(RateLimitExceeded,_rate_limit_exceeded_handler)
    install_wallet_recovery(app,engine,factory,Business,Customer,
                            AIDocument,AISale,"strong-test-secret-only","HS256",
                            limiter=limiter)
    with factory() as db:
        db.add_all([
            Business(id=1,email="owner1@loial.invalid",name="Service Auto"),
            Business(id=2,email="owner2@loial.invalid",name="Self Wash"),
            Customer(id=1,business_id=1,uuid="old-card-1",
                     wallet_uuid="W-LEGACY",name="Alex",stamps=4),
            Customer(id=2,business_id=2,uuid="old-card-2",
                     wallet_uuid="W-LEGACY",name="Alex",stamps=2),
            Customer(id=3,business_id=1,uuid="old-card-3",
                     wallet_uuid="W-PRIVATE",name="Dana",stamps=3),
        ])
        db.add(WalletInboxAccess(wallet_uuid="W-PRIVATE",
             token_hash=access_hash("P"*48),created_at="2026-11-17"))
        db.add(AISale(business_id=1,document_id=1,row_number=1,
                      sold_at="2026-11-12",transaction_id="old-1",
                      product="Revizie",quantity=1,unit_price=150,
                      customer_uuid="W-LEGACY"))
        db.add(AISale(business_id=2,document_id=2,row_number=1,
                      sold_at="2026-11-12",transaction_id="old-2",
                      product="Spalare",quantity=1,unit_price=30,
                      customer_uuid="W-LEGACY"))
        db.commit()
    def header(n=1):
        encoded=jwt.encode({"sub":f"owner{n}@loial.invalid","role":"business"},
                            "strong-test-secret-only",algorithm="HS256")
        return {"Authorization":"Bearer "+encoded}
    return TestClient(app),factory,Customer,header


def request(client,auth,customer_id):
    return client.post("/api/loial-wallet-recovery/request",headers=auth,
       json={"customer_id":customer_id,
             "verification_note":"Titular prezent si verificat la receptie"})


def code_for(response):
    return parse_qs(urlparse(response.json()["recovery_url"]).query)["code"][0]


def test_only_owner_can_issue_single_firm_recovery(fixture):
    client,db,Customer,header=fixture
    assert request(client,{},1).status_code==401
    assert request(client,header(2),1).status_code==404
    assert request(client,header(1),3).status_code==409
    eligible=client.get("/api/loial-wallet-recovery/eligible",headers=header(1))
    assert eligible.status_code==200
    assert [x["id"] for x in eligible.json()["items"]]==[1]
    assert "wallet_uuid" not in eligible.text
    assert client.get("/api/loial-wallet-recovery/eligible",headers=header(2)).json()["items"][0]["id"]==2


def test_single_card_recovery_does_not_take_other_business_history(fixture):
    client,db,Customer,header=fixture
    response=request(client,header(),1)
    assert response.status_code==200,response.text
    code=code_for(response)
    preview=client.get("/api/loial-wallet-recovery/preview",params={"code":code})
    assert preview.json()["business"]=="Service Auto"
    assert "name" not in preview.json()
    destination={"code":code,"new_wallet_uuid":"W-RECOVERED-DEVICE-01",
                 "new_private_token":"S"*48}
    recovered=client.post("/api/loial-wallet-recovery/claim",json=destination)
    assert recovered.status_code==200,recovered.text
    assert recovered.json()["stamps"]==4
    assert recovered.json()["other_businesses_moved"] is False
    replay=client.post("/api/loial-wallet-recovery/claim",json=destination)
    assert replay.status_code==200 and replay.json()["replayed"]
    with db() as sess:
        first=sess.query(Customer).filter(Customer.id==1).one()
        second=sess.query(Customer).filter(Customer.id==2).one()
        assert first.wallet_uuid=="W-RECOVERED-DEVICE-01"
        assert first.uuid!="old-card-1"
        assert second.wallet_uuid=="W-LEGACY"
        assert sess.query(AISale).filter(AISale.business_id==1).first().customer_uuid=="W-RECOVERED-DEVICE-01"
        assert sess.query(AISale).filter(AISale.business_id==2).first().customer_uuid=="W-LEGACY"
        ticket=sess.query(RecoveryTicket).first()
        assert ticket.verification_note.startswith("Titular prezent")
        assert ticket.ticket_hash!=code
    second_device=dict(destination,new_wallet_uuid="W-ATTACKER-DEVICE-02",
                       new_private_token="X"*48)
    assert client.post("/api/loial-wallet-recovery/claim",json=second_device).status_code==409
    assert client.get("/api/loial-wallet-recovery/preview",params={"code":code}).status_code==404


def test_new_request_invalidates_previous_secret(fixture):
    client,db,Customer,header=fixture
    old=code_for(request(client,header(),1))
    new=code_for(request(client,header(),1))
    assert old!=new
    assert client.post("/api/loial-wallet-recovery/claim",json={
        "code":old,"new_wallet_uuid":"W-NEW-DEVICE-123456789","new_private_token":"S"*48
    }).status_code==404


def test_existing_verified_destination_requires_private_secret(fixture):
    client,db,Customer,header=fixture
    with db() as sess:
        sess.add(WalletInboxAccess(wallet_uuid="W-DESTINATION-DEVICE-01",
                 token_hash=access_hash("T"*48),created_at="2026-11-17"))
        sess.commit()
    code=code_for(request(client,header(),1))
    payload={"code":code,"new_wallet_uuid":"W-DESTINATION-DEVICE-01","new_private_token":"F"*48}
    assert client.post("/api/loial-wallet-recovery/claim",json=payload).status_code==409
    payload["new_private_token"]="T"*48
    authorized=client.post("/api/loial-wallet-recovery/claim",json=payload)
    assert authorized.status_code==200,authorized.text
    with db() as sess:
        assert sess.query(WalletInboxAccess).filter(
            WalletInboxAccess.wallet_uuid=="W-DESTINATION-DEVICE-01").count()==1


def test_recovery_requires_unpredictable_code(fixture):
    client,db,Customer,header=fixture
    fake="A"*43
    assert client.get("/api/loial-wallet-recovery/preview",
                      params={"code":fake}).status_code==404
    assert client.post("/api/loial-wallet-recovery/claim",json={
      "code":fake,"new_wallet_uuid":"W-OTHER-LONG-RANDOM-DEVICE","new_private_token":"S"*48
    }).status_code==404


def test_recovery_url_stays_with_its_deployment_origin(fixture,monkeypatch):
    client,db,Customer,header=fixture
    monkeypatch.setenv("LOIAL_PUBLIC_ORIGIN",
                       "https://loial-staging-staging.up.railway.app")
    response=request(client,header(),1)
    assert response.status_code==200,response.text
    parsed=urlparse(response.json()["recovery_url"])
    assert parsed.scheme=="https"
    assert parsed.netloc=="loial-staging-staging.up.railway.app"
    assert parsed.path=="/wallet-recovery.html"
    assert code_for(response)


@pytest.mark.parametrize("unsafe_origin", [
    "http://loial.space",
    "https://loial.space/path",
    "https://user@loial.space",
    "https://*.loial.space",
    "https://loial.space?x=1",
    "https://loial.space:99999",
])
def test_recovery_refuses_unsafe_public_origin(fixture,monkeypatch,unsafe_origin):
    client,db,Customer,header=fixture
    monkeypatch.setenv("LOIAL_PUBLIC_ORIGIN",unsafe_origin)
    response=request(client,header(),1)
    assert response.status_code==503,response.text
    assert "recovery_url" not in response.text
    with db() as session:
        assert session.query(RecoveryTicket).count()==0


@pytest.mark.parametrize("wallet_id",[
    "W-"+("X"*17)+"?invalid",
    "W-"+("X"*17)+"/invalid",
    "W-"+("X"*17)+"#invalid",
    "W-"+("X"*17)+" invalid",
    "W-"+("X"*17)+"@invalid",
])
def test_recovery_rejects_malformed_destination_without_using_ticket(fixture,wallet_id):
    client,db,Customer,header=fixture
    code=code_for(request(client,header(),1))
    payload={"code":code,"new_wallet_uuid":wallet_id,"new_private_token":"S"*48}
    denied=client.post("/api/loial-wallet-recovery/claim",json=payload)
    assert denied.status_code==422,denied.text
    with db() as session:
        card=session.query(Customer).filter(Customer.id==1).one()
        assert card.wallet_uuid=="W-LEGACY"
        assert session.query(RecoveryTicket).first().status=="pending"
    payload["new_wallet_uuid"]="W-VALID-RECOVERED-DEVICE-001"
    valid=client.post("/api/loial-wallet-recovery/claim",json=payload)
    assert valid.status_code==200,valid.text


def test_recovery_page_removes_bearer_ticket_from_browser_history():
    from pathlib import Path
    page=(Path(__file__).resolve().parents[1]/"wallet-recovery.html").read_text(encoding="utf-8")
    assert "const code=new URLSearchParams(location.search).get('code')||'';" in page
    assert "history.replaceState(history.state,'',location.pathname);" in page
    assert page.index("history.replaceState(") < page.index("preview();")
    assert '<meta name="referrer" content="no-referrer">' in page


def test_recovery_claim_cannot_cross_expiration_during_atomic_update(fixture, monkeypatch):
    """Expiry must still be enforced if it passes after initial code lookup."""
    from datetime import datetime, timedelta
    import loial_wallet_recovery as recovery
    client, factory, Customer, header = fixture
    code = code_for(request(client, header(), 1))
    with factory() as session:
        ticket = session.query(RecoveryTicket).first()
        expiry = datetime.fromisoformat(ticket.expires_at)
    times = iter([expiry - timedelta(seconds=1), expiry + timedelta(seconds=1)])
    monkeypatch.setattr(recovery, "now_utc", lambda: next(times))
    denied = client.post("/api/loial-wallet-recovery/claim", json={
        "code": code,
        "new_wallet_uuid": "W-VALID-DEVICE-EXPIRED-001",
        "new_private_token": "S" * 48,
    })
    assert denied.status_code == 409, denied.text
    with factory() as session:
        assert session.query(Customer).filter(Customer.id == 1).one().wallet_uuid == "W-LEGACY"
        assert session.query(RecoveryTicket).first().status == "pending"
        assert session.query(WalletInboxAccess).filter(
            WalletInboxAccess.wallet_uuid == "W-VALID-DEVICE-EXPIRED-001"
        ).count() == 0


def test_recovery_ticket_issuance_is_rate_limited(fixture):
    client,db,Customer,header=fixture
    for _ in range(5):
        response=request(client,header(),1)
        assert response.status_code==200,response.text
    blocked=request(client,header(),1)
    assert blocked.status_code==429,blocked.text
    with db() as session:
        assert session.query(RecoveryTicket).count()==5
        assert session.query(RecoveryTicket).filter_by(status="pending").count()==1
