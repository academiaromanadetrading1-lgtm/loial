"""Native Loial inbox: auth, consent, no-email dispatch, tenant boundaries.

Run: python -m pytest tests/test_loial_inbox.py -q
"""
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from loial_inbox import (
    install_loial_inbox, issue_wallet_access, record_offer_choice,
    queue_service_event, latest_offer_choice, audience_matches,
)

@pytest.fixture
def env():
    Model = declarative_base()

    class Business(Model):
        __tablename__ = "business_accounts"
        id = Column(Integer, primary_key=True)
        email = Column(String(150))
        name = Column(String(150))
        business_type = Column(String(100))
        plan = Column(String(40))
        reward_text = Column(String(250))
        stamps_required = Column(Integer)

    class Customer(Model):
        __tablename__ = "customers"
        id = Column(Integer, primary_key=True)
        business_id = Column(Integer)
        uuid = Column(String(150))
        wallet_uuid = Column(String(150))
        name = Column(String(100))
        email = Column(String(150))
        stamps = Column(Integer)
        last_visit = Column(String(40))

    class Consent(Model):
        __tablename__ = "consents"
        id = Column(Integer, primary_key=True)
        customer_id = Column(Integer)
        purpose = Column(String(100))
        granted = Column(Integer)
        date = Column(String(50))
        ip = Column(String(50))

    class Sale(Model):
        __tablename__ = "loial_ai_sales"
        id = Column(Integer, primary_key=True)
        business_id = Column(Integer)
        customer_uuid = Column(String(120))
        product = Column(String(150))

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Model.metadata.create_all(engine)
    session = sessionmaker(bind=engine)
    app = FastAPI()
    install_loial_inbox(app, engine, session, Business, Customer, Consent,
                        Sale, "test-inbox-jwt-signing-key", "HS256")

    with session() as db:
        db.add_all([
            Business(id=1, email="boss1@example.test", name="Auto Service",
                     business_type="atelier_auto", plan="probusiness",
                     reward_text="Schimb de ulei", stamps_required=5),
            Business(id=2, email="boss2@example.test", name="Bolt driver",
                     business_type="rideshare", plan="probusiness",
                     reward_text="Calatorie", stamps_required=8),
            Business(id=3, email="boss3@example.test", name="Free",
                     business_type="patiserie", plan="free",
                     reward_text="Cafea", stamps_required=6),
            Customer(id=1, business_id=1, uuid="wallet-a", wallet_uuid="wallet-a",
                     name="Client A", email=None, stamps=2, last_visit="2026-11-14"),
            Customer(id=2, business_id=1, uuid="wallet-b", wallet_uuid="wallet-b",
                     name="Client B", email=None, stamps=0, last_visit="2026-09-11"),
            Customer(id=3, business_id=2, uuid="card-a-2", wallet_uuid="wallet-a",
                     name="Client A", email=None, stamps=1, last_visit="2026-11-14"),
            Customer(id=4, business_id=3, uuid="wallet-c", wallet_uuid="wallet-c",
                     name="Client C", email=None, stamps=0, last_visit="2026-11-14")
        ])
        db.commit()
        token_a = issue_wallet_access(db, "wallet-a", is_new_wallet=True)
        token_b = issue_wallet_access(db, "wallet-b", is_new_wallet=True)
        token_c = issue_wallet_access(db, "wallet-c", is_new_wallet=True)
        record_offer_choice(db, Consent, 1, True, "test")
        record_offer_choice(db, Consent, 2, False, "test")
        record_offer_choice(db, Consent, 3, True, "test")
        db.add(Sale(id=1, business_id=1, customer_uuid="wallet-a", product="Revizie"))
        db.commit()

    def owner_headers(email, role="business"):
        return {"Authorization": "Bearer " + jwt.encode({"sub": email, "role": role},
                          "test-inbox-jwt-signing-key", algorithm="HS256")}

    def wallet_headers(token):
        return {"X-Loial-Wallet-Token": token}

    return TestClient(app), session, Business, Customer, Consent, (token_a, token_b, token_c), owner_headers, wallet_headers

def test_no_wallet_token_is_leaked_on_reenroll(env):
    _, session, _, _, _, (a, _, _), _, _ = env
    with session() as db:
        assert isinstance(a, str) and len(a) > 40
        assert issue_wallet_access(db, "wallet-a", is_new_wallet=False) is None
        assert issue_wallet_access(db, "wallet-a", is_new_wallet=True) is None

def test_business_scoping_and_free_plan(env):
    client, _, _, _, _, _, boss, _ = env
    assert client.post("/api/loial-inbox/send",
                       json={"subject":"Test","text":"Test","audience":"all"}).status_code == 401
    assert client.get("/api/loial-inbox/sent", headers=boss("boss1@example.test", role="admin")).status_code == 403
    assert client.get("/api/loial-inbox/sent", headers=boss("boss3@example.test")).status_code == 403
    assert client.get("/api/loial-inbox/sent", headers=boss("boss1@example.test")).status_code == 200

def test_send_in_loial_directly_without_email_or_approval(env):
    client, _, _, _, _, tokens, boss, wallet = env
    payload = {"subject": "Revizie", "text": "Avem servicii noi la atelier!",
               "audience": "all"}
    res = client.post("/api/loial-inbox/send", headers=boss("boss1@example.test"),
                      json=payload)
    assert res.status_code == 200, res.text
    assert res.json()["sent"] == 1
    assert res.json()["external_messages"] == 0
    inbox = client.get("/api/loial-inbox/me", headers=wallet(tokens[0]))
    assert inbox.status_code == 200
    assert inbox.json()["messages"][0]["text"] == payload["text"]
    assert inbox.json()["messages"][0]["business_name"] == "Auto Service"
    assert client.get("/api/loial-inbox/me", headers=wallet(tokens[1])).json()["messages"] == []
    assert client.get("/api/loial-inbox/me", headers=wallet(tokens[2])).json()["messages"] == []

def test_opt_out_blocks_future_marketing_but_not_stamp_updates(env):
    client, session, biz, Customer, Consent, tokens, boss, wallet = env
    res = client.post("/api/loial-inbox/preferences", headers=wallet(tokens[0]),
                      json={"business_id":1, "enabled":False})
    assert res.status_code == 200
    send = client.post("/api/loial-inbox/send", headers=boss("boss1@example.test"),
                       json={"subject":"Oferta","text":"Un mesaj","audience":"all"})
    assert send.json()["sent"] == 0
    with session() as db:
        b=db.query(biz).filter(biz.id==1).first()
        c=db.query(Customer).filter(Customer.id==1).first()
        queue_service_event(db, b, c, kind="stamp")
        db.commit()
    messages=client.get("/api/loial-inbox/me",headers=wallet(tokens[0])).json()["messages"]
    assert any(m["kind"]=="service" for m in messages)
    assert not any(m["kind"]=="marketing" for m in messages)

def test_read_is_limited_to_wallet_owner(env):
    client, _, _, _, _, tokens, boss, wallet = env
    client.post("/api/loial-inbox/send",headers=boss("boss1@example.test"),
                json={"subject":"Atelier","text":"O noutate","audience":"all"})
    inbox=client.get("/api/loial-inbox/me",headers=wallet(tokens[0])).json()
    delivery_id=inbox["messages"][0]["delivery_id"]
    assert client.post("/api/loial-inbox/read/"+str(delivery_id),
                       headers=wallet(tokens[1])).status_code == 404
    assert client.post("/api/loial-inbox/read/"+str(delivery_id),
                       headers=wallet(tokens[0])).json()["read"] is True

def test_specific_product_audience_does_not_leak_to_other_merchants(env):
    client, _, _, _, _, tokens, boss, wallet = env
    sent=client.post("/api/loial-inbox/send", headers=boss("boss1@example.test"),
                     json={"subject":"Revizie","text":"Reducere la revizie",
                           "audience":"product_buyers","product":"Revizie"})
    assert sent.json()["sent"] == 1
    other=client.get("/api/loial-inbox/me",headers=wallet(tokens[1])).json()
    assert other["messages"] == []
    assert client.post("/api/loial-inbox/send", headers=boss("boss2@example.test"),
                       json={"subject":"Bolt","text":"Salut","audience":"product_buyers",
                             "product":"Revizie"}).json()["sent"] == 0

def test_service_messages_are_idempotent(env):
    client, session, biz, Customer, _, tokens, _, wallet = env
    with session() as db:
        business=db.query(biz).filter(biz.id==1).first()
        customer=db.query(Customer).filter(Customer.id==1).first()
        assert queue_service_event(db,business,customer,kind="welcome")
        assert not queue_service_event(db,business,customer,kind="welcome")
        assert queue_service_event(db,business,customer,kind="stamp")
        assert not queue_service_event(db,business,customer,kind="stamp")
        db.commit()
    messages=client.get("/api/loial-inbox/me",headers=wallet(tokens[0])).json()
    assert sum(m["kind"]=="service" for m in messages["messages"])==2

def test_invalid_wallet_access_rejected(env):
    client, _, _, _, _, _, _, _ = env
    assert client.get("/api/loial-inbox/me").status_code == 401
    assert client.get("/api/loial-inbox/me",headers={"X-Loial-Wallet-Token":"A"*43}).status_code == 401


def test_resending_same_request_does_not_duplicate_messages(env):
    client, _, _, _, _, tokens, boss, wallet = env
    payload={"subject":"Revizie","text":"Program nou la atelier",
             "audience":"all","idempotency_key":"test-idempotent-001"}
    a=client.post("/api/loial-inbox/send",headers=boss("boss1@example.test"),json=payload)
    b=client.post("/api/loial-inbox/send",headers=boss("boss1@example.test"),json=payload)
    assert a.status_code==200
    assert b.status_code==200
    assert b.json()["status"]=="already_delivered"
    assert a.json()["message_id"]==b.json()["message_id"]
    entries=client.get("/api/loial-inbox/me",headers=wallet(tokens[0])).json()["messages"]
    assert len(entries)==1
    payload["text"]="Alt mesaj"
    invalid=client.post("/api/loial-inbox/send",headers=boss("boss1@example.test"),json=payload)
    assert invalid.status_code==409

def test_one_targeted_customer_does_not_receive_other_customer_messages(env):
    client, _, _, _, _, tokens, boss, wallet = env
    payload={"subject":"Personal","text":"Vino la atelier",
             "audience":"all","customer_ids":[2]}
    sent=client.post("/api/loial-inbox/send",headers=boss("boss1@example.test"),json=payload)
    assert sent.status_code==200
    assert sent.json()["sent"]==0   # Clientul 2 nu a acceptat ofertele
    enabled=client.post("/api/loial-inbox/preferences",headers=wallet(tokens[1]),
                        json={"business_id":1,"enabled":True})
    assert enabled.status_code==200
    sent2=client.post("/api/loial-inbox/send",headers=boss("boss1@example.test"),json=payload)
    assert sent2.json()["sent"]==1
    assert client.get("/api/loial-inbox/me",headers=wallet(tokens[0])).json()["messages"]==[]
    assert len(client.get("/api/loial-inbox/me",headers=wallet(tokens[1])).json()["messages"])==1


def test_wallet_preferences_are_per_business(env):
    client, _, _, _, _, tokens, boss, wallet = env
    preferences = client.get("/api/loial-inbox/preferences", headers=wallet(tokens[0])).json()
    by_biz = {p["business_id"]: p["offers_enabled"] for p in preferences}
    assert by_biz[1] is True
    assert by_biz[2] is True
    changed = client.post("/api/loial-inbox/preferences", headers=wallet(tokens[0]),
                          json={"business_id":1,"enabled":False})
    assert changed.status_code == 200
    again=client.get("/api/loial-inbox/preferences", headers=wallet(tokens[0])).json()
    latest = {p["business_id"]:p["offers_enabled"] for p in again}
    assert latest[1] is False and latest[2] is True

def test_private_wallet_token_cannot_be_replaced_by_public_qr_uuid(env):
    client, _, _, _, _, tokens, _, wallet = env
    spoof = client.get("/api/loial-inbox/me",
        headers={"X-Loial-Wallet-Token":"wallet-a"})
    assert spoof.status_code == 401
    valid = client.get("/api/loial-inbox/me", headers=wallet(tokens[0]))
    assert valid.status_code == 200


def test_same_device_secret_recovers_after_network_retry(env):
    client, session, _, _, _, tokens, boss, wallet = env
    # QR alone never grants access, but the same device can prove its original claim.
    with session() as db:
        device_secret = "S" * 48
        issued = issue_wallet_access(db,"brand-new-wallet",is_new_wallet=True,
                                     proposed_token=device_secret)
        db.commit()
        assert issued==device_secret
        assert issue_wallet_access(db,"brand-new-wallet",False,device_secret)==device_secret
        assert issue_wallet_access(db,"brand-new-wallet",False,"X"*48) is None
        assert issue_wallet_access(db,"brand-new-wallet",False) is None
    owner = client.get("/api/loial-inbox/me",
                       headers={"X-Loial-Wallet-Token":device_secret})
    assert owner.status_code==200
