"""Regression tests: only a directly recruited ambassador can generate EUR 10."""
import unittest
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from loial_revenue_commissions import (
    RevenueBase, SponsorRelationship, MerchantBilling, PaidMerchantInvoice,
    AmbassadorCommission, apply_verified_invoice, sponsor_new_ambassador,
    reverse_invoice, simulate,
)

Base = declarative_base()

class Agent(Base):
    __tablename__ = "test_agents"
    id = Column(Integer, primary_key=True)
    email = Column(String)
    qr_code = Column(String)
    active = Column(Boolean, default=True)

class Business(Base):
    __tablename__ = "test_businesses"
    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer)

class DirectRecruiterTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        RevenueBase.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        for i in range(1, 5):
            self.db.add(Agent(id=i, email=f"a{i}@example.test",
                              qr_code=f"LOIAL-{i}-ABCDEF", active=True))
        # A=1, B=2, C=3, D=4; A recruited B, B recruited C, C recruited D.
        for business_id, agent_id in ((8, 2), (9, 3), (10, 4)):
            self.db.add(Business(id=business_id, agent_id=agent_id))
            self.db.add(MerchantBilling(
                business_id=business_id,
                provider_customer_id=f"cus_business{business_id}",
                linked_at="2026-11-17"))
        for child, recruiter in ((2, 1), (3, 2), (4, 3)):
            self.db.add(SponsorRelationship(
                ambassador_id=child, sponsor_id=recruiter, referred_at="now"))
        self.db.commit()

    def invoice(self, invoice_id, business_id, month=11):
        return dict(
            id=invoice_id, customer=f"cus_business{business_id}",
            status="paid", paid=True, currency="eur",
            billing_reason="subscription_create",
            subscription=f"sub_business{business_id}",
            payment_intent=f"pi_{invoice_id}",
            amount_paid=6700, total_excluding_tax=6700,
            created=int(datetime(2026, month, 17,
                tzinfo=timezone.utc).timestamp()))

    def ledger(self):
        return sorted((x.agent_id, x.kind, x.amount_cents, x.status)
            for x in self.db.query(AmbassadorCommission).all())

    def test_b_company_pays_b_and_a(self):
        outcome=apply_verified_invoice(self.db,self.invoice("in_b",8),Agent,Business)
        self.db.commit()
        self.assertEqual(outcome["pending_commission_cents"],3000)
        self.assertEqual(self.ledger(),[
            (1,"sponsor",1000,"pending"),(2,"activation",2000,"pending")])

    def test_c_company_pays_c_and_b_not_a(self):
        outcome=apply_verified_invoice(self.db,self.invoice("in_c",9),Agent,Business)
        self.db.commit()
        self.assertEqual(outcome["pending_commission_cents"],3000)
        self.assertEqual(self.ledger(),[
            (2,"sponsor",1000,"pending"),(3,"activation",2000,"pending")])

    def test_d_company_pays_d_and_c_only(self):
        apply_verified_invoice(self.db,self.invoice("in_d",10),Agent,Business)
        self.db.commit()
        self.assertEqual(self.ledger(),[
            (3,"sponsor",1000,"pending"),(4,"activation",2000,"pending")])

    def test_invoice_idempotent_and_renewal_no_repeat_sponsor_bonus(self):
        apply_verified_invoice(self.db,self.invoice("in_c",9),Agent,Business)
        self.db.commit()
        again=apply_verified_invoice(self.db,self.invoice("in_c",9),Agent,Business)
        self.assertTrue(again["duplicate"])
        renewal=self.invoice("in_c_renew",9,month=12)
        renewal["billing_reason"]="subscription_cycle"
        apply_verified_invoice(self.db,renewal,Agent,Business)
        self.db.commit()
        self.assertEqual(len(self.ledger()),3)
        self.assertEqual(sum(x[1]=="sponsor" for x in self.ledger()),1)

    def test_refund_reverses_both_activation_and_recruiter(self):
        apply_verified_invoice(self.db,self.invoice("in_c",9),Agent,Business)
        row=self.db.query(PaidMerchantInvoice).one()
        reverse_invoice(self.db,row)
        self.db.commit()
        self.assertTrue(all(x[3]=="reversed" for x in self.ledger()))

    def test_signup_no_commission_and_no_rebinding(self):
        self.assertEqual(self.db.query(AmbassadorCommission).count(),0)
        self.assertIsNone(sponsor_new_ambassador(
            self.db,self.db.get(Agent,3),"LOIAL-1-ABCDEF",Agent))
        self.assertEqual(self.db.query(AmbassadorCommission).count(),0)

    def test_simulator_uses_direct_recruits_only(self):
        result=simulate(own_new=1,friend_ambassadors=2,
                        new_firms_per_friend=3)
        self.assertEqual(result["one_time_sponsor_commission_eur"],60)
        self.assertEqual(result["estimated_month_commission_eur"],80)
        self.assertEqual(result["max_upstream_sponsor_levels"],1)

if __name__=="__main__":
    unittest.main()
