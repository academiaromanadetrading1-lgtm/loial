import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool
from passlib.context import CryptContext
from sales import create_sales_models
from loial_inbox import InboxBase, issue_wallet_access
from loial_manual_admin import GrantBase
from loial_revenue_commissions import RevenueBase, AmbassadorCommission, PaidMerchantInvoice
from loial_merchant_referrals import install_merchant_referrals, resolve_code, attribute_merchant, linked_agent

Base=declarative_base()
Agent, _, _, _=create_sales_models(Base)
class Business(Base):
    __tablename__="growth_test_business"
    id=Column(Integer,primary_key=True)
    email=Column(String,nullable=False)
    agent_id=Column(Integer,nullable=True)

@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("LOIAL_PUBLIC_ORIGIN","https://staging.example.invalid")
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    for metadata in (Base.metadata,InboxBase.metadata,GrantBase.metadata,RevenueBase.metadata):
        metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    app=FastAPI()
    install_merchant_referrals(app,engine,factory,Agent,Business,CryptContext(schemes=["pbkdf2_sha256"]))
    with factory() as db:
        for name in ("wallet-a","wallet-b"):
            issue_wallet_access(db,name,True,proposed_token=("A" if name=="wallet-a" else "B")*48)
        db.commit()
    return TestClient(app),factory

def auth(letter="A"):
    return {"X-Loial-Wallet-Token":letter*48}

URL="/api/loial-merchant-referrals"
DETAILS={"name":"Test Ambassador","email":"amb@example.invalid","password":"unique-test-password","accept_terms":True}

def recruit(factory,code,bid,email="firm@example.invalid"):
    with factory() as db:
        source=resolve_code(db,code)
        assert source
        agent=linked_agent(db,source.wallet_uuid,Agent)
        db.add(Business(id=bid,email=email,agent_id=agent.id if agent else None))
        row=attribute_merchant(db,bid,source.wallet_uuid)
        row.agent_id=agent.id if agent else None
        db.commit()

def test_first_recruitment_activation_and_future_attribution(env):
    client,factory=env
    assert client.get(URL+"/me").status_code==401
    assert client.get(URL+"/me",headers=auth("Z")).status_code==401
    first=client.get(URL+"/me",headers=auth()).json()
    assert first["status"]=="customer"
    assert first["share_url"]=="https://staging.example.invalid/register.html?ref="+first["code"]
    assert first["code"].startswith("LM-")
    assert client.get(URL+"/me",headers=auth()).json()["code"]==first["code"]
    assert client.get(URL+"/me",headers=auth("B")).json()["code"]!=first["code"]
    assert client.post(URL+"/activate",headers=auth(),json=DETAILS).status_code==409
    recruit(factory,first["code"],1)
    assert client.get(URL+"/me",headers=auth()).json()["status"]=="eligible_for_activation"
    assert client.get(URL+"/me",headers=auth("B")).json()["registered_merchants"]==0
    assert client.post(URL+"/activate",headers=auth(),json={**DETAILS,"accept_terms":False}).status_code==422
    result=client.post(URL+"/activate",headers=auth(),json=DETAILS)
    assert result.status_code==200,result.text
    assert result.json()["assigned_merchants"]==1
    assert result.json()["commission_on_signup"] is False
    assert client.get(URL+"/me",headers=auth()).json()["status"]=="ambassador"
    assert client.post(URL+"/activate",headers=auth(),json=DETAILS).status_code==409
    recruit(factory,first["code"],2,"second@example.invalid")
    with factory() as db:
        agent=db.query(Agent).one()
        assert db.get(Business,1).agent_id==agent.id
        assert db.get(Business,2).agent_id==agent.id
        assert db.query(AmbassadorCommission).count()==0
        assert db.query(PaidMerchantInvoice).count()==0

def test_link_requires_password_and_cannot_take_another_wallet(env):
    client,factory=env
    for letter,bid in (("A",1),("B",2)):
        code=client.get(URL+"/me",headers=auth(letter)).json()["code"]
        recruit(factory,code,bid)
    assert client.post(URL+"/activate",headers=auth(),json=DETAILS).status_code==200
    assert client.post(URL+"/link",headers=auth("B"),json={**DETAILS,"password":"invalid"}).status_code==401
    assert client.post(URL+"/link",headers=auth("B"),json=DETAILS).status_code==409
    with factory() as db:
        assert db.get(Business,2).agent_id is None
        assert db.query(Agent).count()==1
