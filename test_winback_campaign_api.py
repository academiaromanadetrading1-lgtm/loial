"""API integration: drafts and consent-gated wallet dispatch on isolated SQLite.

The merchant is an authenticated test principal; Stripe is mocked active.
No Railway customer data, real messages or external payment APIs are used.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.security import HTTPBearer
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from loial_winback import WinbackBase
from loial_winback_campaigns import CampaignBase, install_winback_campaigns
from loial_scans import ScanBase, StampAward
from loial_inbox import InboxBase, InboxDelivery, PURPOSE

Base = declarative_base()

class Firm(Base):
    __tablename__ = "test_firms"
    id = Column(Integer, primary_key=True)

class Customer(Base):
    __tablename__ = "test_customers"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, index=True)
    name = Column(String(80))
    uuid = Column(String(120))
    wallet_uuid = Column(String(120))

class Consent(Base):
    __tablename__ = "test_consents"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, index=True)
    purpose = Column(String(60))
    granted = Column(Integer)
    date = Column(String(50))
    ip = Column(String(40))


class WinbackCampaignApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:",
                  connect_args={"check_same_thread":False},poolclass=StaticPool)
        for metadata in (Base.metadata,WinbackBase.metadata,CampaignBase.metadata,
                         ScanBase.metadata,InboxBase.metadata):
            metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine,expire_on_commit=False)
        app=FastAPI()
        def get_db():
            with self.Session() as db:
                yield db
        security=HTTPBearer(auto_error=False)
        def merchant_auth(credentials,db):
            return db.get(Firm,1)
        install_winback_campaigns(app,self.engine,get_db,Firm,Customer,StampAward,
                                  Consent,merchant_auth,security)
        self.client=TestClient(app)
        with self.Session() as db:
            db.add_all([Firm(id=1),Firm(id=2),
                        Customer(id=11,business_id=1,name="Eligible",uuid="wallet11"),
                        Customer(id=12,business_id=1,name="No consent",uuid="wallet12"),
                        Customer(id=13,business_id=2,name="Other firm",uuid="wallet13")])
            date=(datetime.now(timezone.utc)-timedelta(days=70)).isoformat()
            for cid in (11,12,13):
                db.add(StampAward(business_id=1 if cid!=13 else 2,customer_id=cid,
                   operation_key="scan-%s"%cid,source="manual",stamps_after=1,created_at=date))
            db.add(Consent(customer_id=11,purpose=PURPOSE,granted=1,date=date,ip="test"))
            db.commit()
        self.patch=patch("loial_stripe_billing.effective_entitlements",
                         return_value={"active":True,"plan":"business"})
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.client.close()
        self.engine.dispose()

    def draft(self):
        response=self.client.post("/api/loial-winback/campaigns/draft",
                json={"title":"Come back","message":"We would love to see you again."})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_draft_never_sends_automatically(self):
        draft=self.draft()
        self.assertEqual(draft["status"],"draft")
        self.assertEqual(draft["sent"],0)
        self.assertEqual(draft["eligible_with_marketing_consent"],1)
        with self.Session() as db:
            self.assertEqual(db.query(InboxDelivery).count(),0)

    def test_explicit_approval_delivers_only_to_consented_customer(self):
        draft=self.draft()
        response=self.client.post("/api/loial-winback/campaigns/%s/approve"%draft["campaign_id"])
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["delivered_to_wallet_inbox"],1)
        with self.Session() as db:
            deliveries=db.query(InboxDelivery).all()
            self.assertEqual(len(deliveries),1)
            self.assertEqual(deliveries[0].customer_id,11)
            self.assertEqual(deliveries[0].business_id,1)
        repeat=self.client.post("/api/loial-winback/campaigns/%s/approve"%draft["campaign_id"])
        self.assertEqual(repeat.status_code,409)

    def test_consent_withdrawn_after_draft_blocks_delivery(self):
        draft=self.draft()
        with self.Session() as db:
            db.add(Consent(customer_id=11,purpose=PURPOSE,granted=0,
                           date=datetime.now(timezone.utc).isoformat(),ip="test"))
            db.commit()
        response=self.client.post("/api/loial-winback/campaigns/%s/approve"%draft["campaign_id"])
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["delivered_to_wallet_inbox"],0)
        with self.Session() as db:
            self.assertEqual(db.query(InboxDelivery).count(),0)

    def test_invalid_campaign_id_fails_closed(self):
        response=self.client.post("/api/loial-winback/campaigns/999999/approve")
        self.assertEqual(response.status_code,404)

if __name__ == "__main__":
    unittest.main()
