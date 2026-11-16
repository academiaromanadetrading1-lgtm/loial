"""Loial premium wallet & simultaneous identities (isolated, no live issuer keys)."""
import json
import io
import os
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import Column, Boolean, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from loial_identity import install_loial_identity
from loial_inbox import WalletInboxAccess, InboxBase, issue_wallet_access, access_hash
from loial_premium_wallet import (
    install_premium_wallet, premium_card, member_status, google_pass_payload,
    apple_pass_json, signed_apple_pkpass, _image_assets
)

def test_premium_customer_and_ambassador_are_not_payment_cards():
    customer=premium_card("Alex", "customer","Patiseria A","https://loial.space/scan.html?wallet_uuid=X",
                          "client:1:X",stamps=4,target=6)
    agent=premium_card("Alex", "ambassador","Loial","https://loial.space/register.html?ref=LOIAL-X",
                       "agent:42",status="AMBASADOR MANAGER")
    assert customer["theme"]==agent["theme"]=="black-metal"
    assert not customer["is_payment_card"]
    assert customer["status"]=="MEMBRU LOIAL"
    assert agent["status"]=="AMBASADOR MANAGER"
    assert customer["qr_value"]!=agent["qr_value"]
    assert member_status(6,6)=="RECOMPENSA DISPONIBILA"

def test_google_payload_roles_have_separate_schemas():
    customer=premium_card("Mira","customer","Atelier","ABC","c:1:ABC",stamps=3,target=6)
    agent=premium_card("Mira","ambassador","Loial","https://loial.space/register.html?ref=MIRA",
                       "a:7",status="AMBASADOR")
    gc=google_pass_payload(customer,"issuer@project.iam.gserviceaccount.com","123456789012.loial_loyalty")
    ga=google_pass_payload(agent,"issuer@project.iam.gserviceaccount.com","123456789012.loial_agent")
    assert gc["payload"]["loyaltyObjects"][0]["loyaltyPoints"]["balance"]["int"]==3
    assert gc["payload"]["loyaltyObjects"][0]["barcode"]["value"]=="ABC"
    assert ga["payload"]["genericObjects"][0]["hexBackgroundColor"]=="#0D0E11"
    assert ga["payload"]["genericObjects"][0]["header"]["defaultValue"]["value"]=="Mira"

@pytest.fixture
def app_env(monkeypatch):
    for name in ("LOIAL_APPLE_PASS_TYPE_ID","LOIAL_APPLE_TEAM_ID","LOIAL_APPLE_PASS_CERT_PEM",
                 "LOIAL_APPLE_PASS_KEY_PEM","LOIAL_APPLE_WWDR_CERT_PEM",
                 "LOIAL_GOOGLE_WALLET_SERVICE_ACCOUNT_JSON",
                 "LOIAL_GOOGLE_LOYALTY_CLASS_ID","LOIAL_GOOGLE_AMBASSADOR_CLASS_ID"):
        monkeypatch.delenv(name, raising=False)
    DB=declarative_base()
    class Business(DB):
        __tablename__="business_accounts"
        id=Column(Integer,primary_key=True)
        email=Column(String(180),unique=True)
        name=Column(String(100))
        plan=Column(String(40))
        stamps_required=Column(Integer)
        reward_text=Column(String(160))
    class Agent(DB):
        __tablename__="sales_agents"
        id=Column(Integer,primary_key=True)
        email=Column(String(180),unique=True)
        name=Column(String(100))
        password=Column(String(300))
        role=Column(String(40))
        rank=Column(String(80))
        qr_code=Column(String(100))
        status=Column(String(40))
        active=Column(Boolean)
        created_at=Column(String(50))
        phone=Column(String(30))
        payout_method=Column(String(30))
        payout_details=Column(String(100))
    class Sale(DB):
        __tablename__="sales"
        id=Column(Integer,primary_key=True)
        agent_id=Column(Integer)
        status=Column(String(50))
    class Customer(DB):
        __tablename__="customers"
        id=Column(Integer,primary_key=True)
        uuid=Column(String(120))
        wallet_uuid=Column(String(120))
        business_id=Column(Integer)
        name=Column(String(100))
        stamps=Column(Integer)
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},
                         poolclass=StaticPool)
    DB.metadata.create_all(engine)
    InboxBase.metadata.create_all(engine)
    Session=sessionmaker(bind=engine)
    ctx=CryptContext(schemes=["bcrypt"],deprecated="auto")
    secret="test-only-identity-secret-strong-enough"
    def tier(n):
        return {"rank":"Ambasador Manager" if n>=26 else "Ambasador",
                "monthly_rate":10 if n>=26 else 5}
    app=FastAPI()
    install_loial_identity(app,engine,Session,Business,Agent,Sale,ctx,secret,"HS256",
                           WalletInboxAccess,access_hash,tier)
    install_premium_wallet(app,engine,Session,Business,Customer,Agent,Sale,
                           secret,"HS256",tier,
                           __import__("loial_identity").BusinessAmbassadorLink)
    with Session() as db:
        db.add_all([Business(id=1,email="owner@demo.invalid",name="Atelierul Alex",
                             plan="probusiness",stamps_required=6,reward_text="Revizie"),
                    Business(id=2,email="other@demo.invalid",name="Selfwash",
                             plan="probusiness",stamps_required=8,reward_text="Spalare"),
                    Customer(id=4,uuid="w100",wallet_uuid="w100",business_id=1,
                             name="Alex Proprietar",stamps=2)])
        db.commit()
        token=issue_wallet_access(db,"w100",True)
        db.commit()
    def headers(email="owner@demo.invalid",role="business"):
        return {"Authorization":"Bearer "+jwt.encode({"sub":email,"role":role},secret,algorithm="HS256")}
    return TestClient(app),Session,Agent,ctx,headers,token

def test_admin_can_be_ambassador_without_losing_business_role(app_env):
    client,Session,Agent,ctx,headers,token=app_env
    first=client.get("/api/loial-identity/me",headers=headers())
    assert first.json()["roles"]==["business"]
    activated=client.post("/api/loial-identity/ambassador/activate",headers=headers(),
                          json={"display_name":"Alex Pop"})
    assert activated.status_code==200,activated.text
    assert activated.json()["ambassador"]["name"]=="Alex Pop"
    second=client.get("/api/loial-identity/me",headers=headers()).json()
    assert "business" in second["roles"] and "ambassador" in second["roles"]
    assert "customer" not in second["roles"]
    assert client.get("/api/premium-wallet/ambassador/card",headers=headers()).status_code==200

def test_wallet_link_requires_private_token_not_public_qr(app_env):
    client,Session,Agent,ctx,headers,token=app_env
    assert client.post("/api/loial-identity/customer/link",headers=headers(),
                       json={"wallet_private_token":"w100"}).status_code==422
    assert client.post("/api/loial-identity/customer/link",headers=headers(),
                       json={"wallet_private_token":"A"*43}).status_code==401
    assert client.post("/api/loial-identity/customer/link",headers=headers(),
                       json={"wallet_private_token":token}).status_code==200
    assert "customer" in client.get("/api/loial-identity/me",headers=headers()).json()["roles"]
    assert client.get("/api/premium-wallet/customer/cards",
                      headers={"X-Loial-Wallet-Token":token}).json()["cards"][0]["holder"]=="Alex Proprietar"

def test_existing_ambassador_password_needed_to_link(app_env):
    client,Session,Agent,ctx,headers,token=app_env
    with Session() as db:
        db.add(Agent(email="owner@demo.invalid",name="Alex",password=ctx.hash("strong-existing-pass"),
                     role="ambassador",rank="Ambasador",qr_code="LOIAL-EXISTING",
                     status="active",active=True))
        db.commit()
    assert client.post("/api/loial-identity/ambassador/activate",headers=headers(),
                       json={}).status_code==409
    assert client.post("/api/loial-identity/ambassador/link",headers=headers(),
                       json={"password":"wrong"}).status_code==401
    valid=client.post("/api/loial-identity/ambassador/link",headers=headers(),
                      json={"password":"strong-existing-pass"})
    assert valid.status_code==200,valid.text
    assert client.get("/api/loial-identity/me",headers=headers()).json()["ambassador"]["ref_code"]=="LOIAL-EXISTING"

def test_premium_pass_download_is_blocked_without_issuer_credentials(app_env):
    client,Session,Agent,ctx,headers,token=app_env
    card_headers={"X-Loial-Wallet-Token":token}
    assert client.get("/api/premium-wallet/customer/1/apple",headers=card_headers).status_code==503
    assert client.get("/api/premium-wallet/customer/1/google",headers=card_headers).status_code==503
    assert client.get("/api/premium-wallet/customer/2/apple",headers=card_headers).status_code==404
    assert client.get("/api/premium-wallet/customer/cards").status_code==401

def test_apple_pass_archive_is_signed_with_test_keys(monkeypatch, app_env):
    monkeypatch.setenv("LOIAL_APPLE_PILOT_ENABLED","1")
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"Unit Test Signing Certificate")])
    moment=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name)
          .public_key(key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(moment-timedelta(days=1))
          .not_valid_after(moment+timedelta(days=5)).sign(key,hashes.SHA256()))
    monkeypatch.setenv("LOIAL_APPLE_PASS_TYPE_ID","pass.com.example.loial")
    monkeypatch.setenv("LOIAL_APPLE_TEAM_ID","TEST123456")
    monkeypatch.setenv("LOIAL_APPLE_PASS_CERT_PEM",cert.public_bytes(serialization.Encoding.PEM).decode())
    monkeypatch.setenv("LOIAL_APPLE_WWDR_CERT_PEM",cert.public_bytes(serialization.Encoding.PEM).decode())
    monkeypatch.setenv("LOIAL_APPLE_PASS_KEY_PEM",key.private_bytes(
        serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode())
    card=premium_card("Alex","customer","Atelier","https://loial.space/scan.html?wallet_uuid=abc",
                      "client:1:abc",stamps=2,target=6)
    packed=signed_apple_pkpass(card)
    assert len(packed)>1000
    with zipfile.ZipFile(io.BytesIO(packed)) as archive:
        assert {"pass.json","manifest.json","signature","logo.png","icon.png","strip.png"} <= set(archive.namelist())
        data=json.loads(archive.read("pass.json"))
        assert data["storeCard"]["primaryFields"][0]["value"]=="Alex"
        assert data["barcodes"][0]["format"]=="PKBarcodeFormatQR"
        assert archive.read("signature")
    # Browser delivery: a temporary verified link returns the correct MIME type,
    # without exposing the private wallet access token in its URL.
    client,Session,Agent,ctx,headers,private_token=app_env
    authorized={"X-Loial-Wallet-Token":private_token}
    ticket=client.post("/api/premium-wallet/customer/1/apple-ticket",headers=authorized)
    assert ticket.status_code==200,ticket.text
    assert ticket.json()["expires_in_seconds"]<=90
    assert private_token not in ticket.json()["url"]
    downloaded=client.get(ticket.json()["url"])
    assert downloaded.status_code==200,downloaded.text
    assert downloaded.headers["content-type"]=="application/vnd.apple.pkpass"
    assert downloaded.headers["cache-control"]=="private, no-store"
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as saved:
        assert json.loads(saved.read("pass.json"))["storeCard"]["primaryFields"][0]["value"]=="Alex Proprietar"


def test_apple_download_link_requires_private_identity_and_issuer(app_env):
    client,Session,Agent,ctx,headers,token=app_env
    endpoint="/api/premium-wallet/customer/1/apple-ticket"
    assert client.post(endpoint).status_code==401
    assert client.post(endpoint,headers={"X-Loial-Wallet-Token":"A"*43}).status_code==401
    assert client.post(endpoint,headers={"X-Loial-Wallet-Token":token}).status_code==503
    assert client.get("/api/premium-wallet/apple/claim?ticket=not-valid").status_code==401
    assert client.post("/api/premium-wallet/ambassador/apple-ticket",headers=headers()).status_code==403

def test_apple_routes_are_disabled_during_google_first_pilot(app_env,monkeypatch):
    monkeypatch.setenv("LOIAL_APPLE_PILOT_ENABLED","0")
    client,Session,Agent,ctx,headers,private_token=app_env
    wallet_headers={"X-Loial-Wallet-Token":private_token}
    assert client.get("/api/premium-wallet/customer/1/apple",
                      headers=wallet_headers).status_code==503
    assert client.post("/api/premium-wallet/customer/1/apple-ticket",
                       headers=wallet_headers).status_code==503
    client.post("/api/loial-identity/ambassador/activate",
                headers=headers(),json={"display_name":"Administrator"})
    assert client.get("/api/premium-wallet/ambassador/apple",
                      headers=headers()).status_code==503
