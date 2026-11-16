"""Google Wallet: issuer opt-in, official GET/PATCH, isolated queue, no real API calls."""
import json
from datetime import datetime

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from loial_wallet_sync import (
    BaseSync,WalletSyncItem,queue_google_refresh,sync_active,
    request_google_refresh,run_google_sync_cycle,google_patch_body,
    make_customer_card
)

def fake_google_issuer(monkeypatch):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    pem=key.private_bytes(serialization.Encoding.PEM,
                          serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption()).decode()
    account={"client_email":"unit-test@example-project.iam.gserviceaccount.com",
             "private_key":pem,"token_uri":"https://oauth2.googleapis.com/token"}
    monkeypatch.setenv("LOIAL_GOOGLE_WALLET_SERVICE_ACCOUNT_JSON",json.dumps(account))
    monkeypatch.setenv("LOIAL_GOOGLE_LOYALTY_CLASS_ID","123456789012.loial_loyalty")
    monkeypatch.setenv("LOIAL_GOOGLE_WALLET_SYNC_ENABLED","1")
    return account

def test_google_sync_disabled_without_issuer(monkeypatch):
    monkeypatch.delenv("LOIAL_GOOGLE_WALLET_SYNC_ENABLED",raising=False)
    assert not sync_active()
    assert request_google_refresh({"id":"some","role":"customer"})=="disabled"

def test_google_refresh_uses_get_before_patch_and_minimal_patch(monkeypatch):
    fake_google_issuer(monkeypatch)
    card={"id":"client:5:wallet-a","role":"customer","holder":"Alex",
          "qr_value":"https://loial.space/scan.html?wallet_uuid=wallet-a",
          "stamps":4,"target":6,"status":"MEMBRU LOIAL","entity":"Atelier"}
    captured=[]
    def mock(request):
        captured.append((request.method,request.url.path))
        if request.url.path=="/token":
            assert request.method=="POST"
            return httpx.Response(200,json={"access_token":"TEST-BEARER"})
        assert request.headers["authorization"]=="Bearer TEST-BEARER"
        if request.method=="GET":
            return httpx.Response(200,json={"loyaltyPoints":{"balance":{"int":3}}})
        assert request.method=="PATCH"
        data=json.loads(request.content)
        assert data==google_patch_body(card)
        assert data["secondaryLoyaltyPoints"]["balance"]["int"]==2
        assert data["textModulesData"][1]["body"]=="Atelier"
        return httpx.Response(200,json=data)
    transport=httpx.MockTransport(mock)
    assert request_google_refresh(card,transport=transport)=="updated"
    assert [x[0] for x in captured]==["POST","GET","PATCH"]
    assert captured[1][1].startswith("/walletobjects/v1/loyaltyObject/")

def test_google_unsaved_object_is_not_created_unintentionally(monkeypatch):
    fake_google_issuer(monkeypatch)
    calls=[]
    def mock(request):
        calls.append(request.method)
        if request.url.path=="/token":
            return httpx.Response(200,json={"access_token":"T"})
        return httpx.Response(404,json={"error":{"message":"Not found"}})
    card={"id":"client:1:w","role":"customer","holder":"A",
          "qr_value":"QR","stamps":1,"target":6}
    assert request_google_refresh(card,transport=httpx.MockTransport(mock))=="not_saved"
    assert calls==["POST","GET"]

def test_queue_is_atomic_with_loyalty_transaction_and_idempotent_per_card(monkeypatch):
    fake_google_issuer(monkeypatch)
    Base=declarative_base()
    class Business(Base):
        __tablename__="business_accounts"
        id=Column(Integer,primary_key=True)
        name=Column(String(80))
        stamps_required=Column(Integer)
    class Customer(Base):
        __tablename__="customers"
        id=Column(Integer,primary_key=True)
        business_id=Column(Integer)
        uuid=Column(String(90))
        wallet_uuid=Column(String(90))
        name=Column(String(80))
        stamps=Column(Integer)
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},
                         poolclass=StaticPool)
    Base.metadata.create_all(engine)
    BaseSync.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    with factory() as db:
        db.add(Business(id=1,name="Atelier",stamps_required=6))
        db.add(Customer(id=1,business_id=1,uuid="w1",wallet_uuid="w1",
                        name="Client",stamps=2))
        queue_google_refresh(db,1,"w1")
        db.commit()
        queue_google_refresh(db,1,"w1")
        db.commit()
        queued=db.query(WalletSyncItem).first()
        assert queued.requested_version==2
        assert queued.status=="pending"
        received=[]
        result=run_google_sync_cycle(db,Business,Customer,
            updater=lambda card:(received.append(card["stamps"]) or "updated"))
        assert result["processed"]==1
        assert received==[2]
        db.refresh(queued)
        assert queued.status=="updated"
        assert queued.synced_version==2
        assert run_google_sync_cycle(db,Business,Customer,
            updater=lambda card:"updated")["processed"]==0
