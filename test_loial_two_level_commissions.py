"""Isolated regression tests for verified two-level merchant activation."""
import unittest
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from loial_revenue_commissions import (
    RevenueBase, SponsorRelationship, MerchantBilling, PaidMerchantInvoice,
    AmbassadorCommission, apply_verified_invoice, sponsor_new_ambassador,
    reverse_invoice, simulate,
)

Base=declarative_base()
class Agent(Base):
    __tablename__="test_agents"
    id=Column(Integer, primary_key=True)
    email=Column(String)
    qr_code=Column(String)
    active=Column(Boolean, default=True)

class Business(Base):
    __tablename__="test_businesses"
    id=Column(Integer, primary_key=True)
    agent_id=Column(Integer)

class TwoLevelCommissionTests(unittest.TestCase):
    def setUp(self):
        engine=create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        RevenueBase.metadata.create_all(engine)
        self.db=sessionmaker(bind=engine)()
        for i in range(1,5):
            self.db.add(Agent(id=i,email=f"a{i}@example.test",
                qr_code=f"LOIAL-{i}-ABCDEF",active=True))
        self.db.add(Business(id=9,agent_id=3))
        self.db.add(MerchantBilling(business_id=9,
            provider_customer_id="cus_merchant9",linked_at="2026-11-17"))
        self.db.add(SponsorRelationship(ambassador_id=2,sponsor_id=1,referred_at="now"))
        self.db.add(SponsorRelationship(ambassador_id=3,sponsor_id=2,referred_at="now"))
        self.db.add(SponsorRelationship(ambassador_id=1,sponsor_id=4,referred_at="now"))
        self.db.commit()

    def invoice(self,id,month=11):
        return dict(id=id,customer="cus_merchant9",status="paid",paid=True,
            currency="eur",billing_reason="subscription_create",
            subscription="sub_merchant9",payment_intent=f"pi_{id}",
            amount_paid=7865,total_excluding_tax=6500,
            created=int(datetime(2026,month,17,tzinfo=timezone.utc).timestamp()))

    def ledger(self):
        return [(x.agent_id,x.kind,x.amount_cents,x.status)
                for x in self.db.query(AmbassadorCommission).order_by(
                AmbassadorCommission.agent_id).all()]

    def test_first_paid_firm_credits_c_b_a_not_great_grandparent(self):
        outcome=apply_verified_invoice(self.db,self.invoice("in_first"),Agent,Business)
        self.db.commit()
        self.assertEqual(outcome["pending_commission_cents"],4000)
        self.assertEqual(self.ledger(),[
            (1,"sponsor_level_2",1000,"pending"),
            (2,"sponsor",1000,"pending"),
            (3,"activation",2000,"pending")])

    def test_same_invoice_idempotent_and_renewal_no_sponsors(self):
        apply_verified_invoice(self.db,self.invoice("in_first"),Agent,Business)
        self.db.commit()
        duplicate=apply_verified_invoice(self.db,self.invoice("in_first"),Agent,Business)
        self.assertTrue(duplicate["duplicate"])
        renewal=self.invoice("in_renew",month=12)
        renewal["billing_reason"]="subscription_cycle"
        apply_verified_invoice(self.db,renewal,Agent,Business)
        self.db.commit()
        self.assertEqual(len(self.ledger()),4)
        self.assertEqual(sum(1 for row in self.ledger() if row[1].startswith("sponsor")),2)

    def test_refund_reverses_both_sponsors(self):
        apply_verified_invoice(self.db,self.invoice("in_first"),Agent,Business)
        record=self.db.query(PaidMerchantInvoice).one()
        reverse_invoice(self.db,record)
        self.db.commit()
        self.assertTrue(all(x[3]=="reversed" for x in self.ledger()))

    def test_signup_pays_nothing_and_no_cycle(self):
        self.assertEqual(self.db.query(AmbassadorCommission).count(),0)
        # Existing sponsorship cannot be replaced by an adversarial code.
        result=sponsor_new_ambassador(self.db,self.db.get(Agent,3),
            "LOIAL-4-ABCDEF",Agent)
        self.assertIsNone(result)
        self.assertEqual(self.db.query(AmbassadorCommission).count(),0)

    def test_simulation_two_upstream_levels(self):
        result=simulate(own_new=1,friend_ambassadors=2,new_firms_per_friend=3,
                        second_level_ambassadors=4,new_firms_per_second_level=2)
        self.assertEqual(result["one_time_sponsor_commission_eur"],60)
        self.assertEqual(result["one_time_second_level_commission_eur"],80)
        self.assertEqual(result["estimated_month_commission_eur"],160)

if __name__=="__main__":
    unittest.main()
