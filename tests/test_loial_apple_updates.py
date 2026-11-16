"""Apple PassKit authenticated device-registration/updates on isolated fake issuer."""
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column,Integer,String,Boolean,create_engine
from sqlalchemy.orm import declarative_base,sessionmaker
from sqlalchemy.pool import StaticPool

from loial_apple_updates import (
    AppleBase,ApplePass,AppleRegistration,apple_updates_ready,
    pass_authentication_token,register_issued_pass,mark_customer_pass_changed,
    install_apple_pass_updates
)
from loial_premium_wallet import premium_card,apple_pass_json

def fixture(monkeypatch):
    monkeypatch.setenv("LOIAL_APPLE_PASS_TYPE_ID","pass.com.test.loial")
    monkeypatch.setenv("LOIAL_APPLE_TEAM_ID","TESTTEAM01")
    monkeypatch.setenv("LOIAL_APPLE_WEB_SERVICE_URL","https://loial.space/api/passkit")
    monkeypatch.setenv("LOIAL_APPLE_PASS_AUTH_SECRET","unit-only-secret-should-never-go-live-2026-11-16")
    monkeypatch.setenv("LOIAL_APPLE_PUSH_TOKEN_FERNET_KEY",Fernet.generate_key().decode())
    assert apple_updates_ready()
    DB=declarative_base()
    class Biz(DB):
        __tablename__="business_accounts"
        id=Column(Integer,primary_key=True)
        name=Column(String)
        stamps_required=Column(Integer)
    class Customer(DB):
        __tablename__="customers"
        id=Column(Integer,primary_key=True)
        business_id=Column(Integer)
        uuid=Column(String)
        wallet_uuid=Column(String)
        name=Column(String)
        stamps=Column(Integer)
    class Agent(DB):
        __tablename__="sales_agents"
        id=Column(Integer,primary_key=True)
        name=Column(String)
        active=Column(Boolean)
        qr_code=Column(String)
    class Sale(DB):
        __tablename__="sales"
        id=Column(Integer,primary_key=True)
        agent_id=Column(Integer)
        status=Column(String)
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},
                         poolclass=StaticPool)
    DB.metadata.create_all(engine)
    AppleBase.metadata.create_all(engine)
    Session=sessionmaker(bind=engine)
    app=FastAPI()
    install_apple_pass_updates(app,engine,Session,Biz,Customer,Agent,Sale,
        apple_pass_json,lambda card:b"FAKE_PKPASS_BYTES",
        premium_card,lambda total:{"rank":"Ambasador"})
    with Session() as db:
        db.add(Biz(id=1,name="Atelier Black Metal",stamps_required=6))
        db.add(Customer(id=1,business_id=1,uuid="wallet1",wallet_uuid="wallet1",
                        name="Alex Client",stamps=2))
        db.commit()
        card=premium_card("Alex Client","customer","Atelier Black Metal",
                          "https://loial.space/scan.html?wallet_uuid=wallet1",
                          "client:1:wallet1",stamps=2,target=6)
        serial=register_issued_pass(db,card,business_id=1,wallet_uuid="wallet1")
        db.commit()
    return TestClient(app),Session,serial,card

def test_apple_issuer_update_configuration_is_optional(monkeypatch):
    monkeypatch.delenv("LOIAL_APPLE_PASS_AUTH_SECRET",raising=False)
    assert apple_updates_ready() is False

def test_registration_authorization_update_poll_and_download(monkeypatch):
    client,Session,serial,card=fixture(monkeypatch)
    url="/api/passkit/v1/devices/privateDeviceKey-1234/registrations/pass.com.test.loial/"+serial
    header={"Authorization":"ApplePass "+pass_authentication_token(serial)}
    wrong=client.post(url,json={"pushToken":"PRIVATE_PUSH_TOKEN_1"})
    assert wrong.status_code==401
    first=client.post(url,headers=header,json={"pushToken":"PRIVATE_PUSH_TOKEN_1"})
    assert first.status_code==201,first.text
    assert client.post(url,headers=header,json={"pushToken":"PRIVATE_PUSH_TOKEN_1"}).status_code==200
    with Session() as db:
        registration=db.query(AppleRegistration).first()
        assert "PRIVATE_PUSH_TOKEN_1" not in registration.encrypted_push_token
        assert "privateDeviceKey-1234" not in registration.device_hash
    poll="/api/passkit/v1/devices/privateDeviceKey-1234/registrations/pass.com.test.loial"
    before=client.get(poll,params={"passesUpdatedSince":"0"})
    assert before.status_code==200
    assert before.json()["serialNumbers"]==[serial]
    tag=before.json()["lastUpdated"]
    no_updates=client.get(poll,params={"passesUpdatedSince":tag})
    assert no_updates.status_code==204
    with Session() as db:
        assert mark_customer_pass_changed(db,1,"wallet1")
        db.commit()
    updates=client.get(poll,params={"passesUpdatedSince":tag})
    assert updates.status_code==200
    assert serial in updates.json()["serialNumbers"]
    invalid=client.get("/api/passkit/v1/passes/pass.com.test.loial/"+serial)
    assert invalid.status_code==401
    good=client.get("/api/passkit/v1/passes/pass.com.test.loial/"+serial,
                    headers=header)
    assert good.status_code==200
    assert good.content==b"FAKE_PKPASS_BYTES"
    assert good.headers["content-type"]=="application/vnd.apple.pkpass"
    assert client.delete(url,headers=header).status_code==200
    assert client.get(poll,params={"passesUpdatedSince":"0"}).status_code==204

def test_apple_pass_json_contains_webservice_only_when_ready(monkeypatch):
    client,Session,serial,card=fixture(monkeypatch)
    data=apple_pass_json(card)
    assert data["webServiceURL"]=="https://loial.space/api/passkit/"
    assert data["authenticationToken"]==pass_authentication_token(serial)
    assert data["serialNumber"]==serial
    monkeypatch.delenv("LOIAL_APPLE_PUSH_TOKEN_FERNET_KEY")
    standalone=apple_pass_json(card)
    assert "webServiceURL" not in standalone
    assert "authenticationToken" not in standalone
