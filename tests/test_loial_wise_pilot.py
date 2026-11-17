"""Wise manual reconciliation and direct-recruiter regression tests (no Wise API)."""
import pytest
from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker

from loial_revenue_commissions import (
    RevenueBase, MerchantBilling, SponsorRelationship, PaidMerchantInvoice,
    AmbassadorCommission, apply_verified_wise_receipt, tier,
    recompute_recurring,
)

Base=declarative_base()

class Agent(Base):
    __tablename__="wise_test_agents"
    id=Column(Integer,primary_key=True)
    email=Column(String)
    active=Column(Boolean,default=True)

class Business(Base):
    __tablename__="wise_test_businesses"
    id=Column(Integer,primary_key=True)
    agent_id=Column(Integer)

@pytest.fixture
def env():
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    RevenueBase.metadata.create_all(engine)
    db=sessionmaker(bind=engine)()
    for id in [1,2,3]:
        db.add(Agent(id=id,email=f"a{id}@example.test",active=True))
    for business_id, agent in [(11,2),(12,3),(13,None)]:
        db.add(Business(id=business_id,agent_id=agent))
    db.add(SponsorRelationship(ambassador_id=2,sponsor_id=1,referred_at="now"))
    db.add(SponsorRelationship(ambassador_id=3,sponsor_id=2,referred_at="now"))
    db.commit()
    yield db
    db.close()

def credit(db,biz,reference,month="2026-11",amount=6700):
    result=apply_verified_wise_receipt(
        db,db.get(Business,biz),Agent,reference,month,amount,
        "Verified personally in Wise account statement")
    db.commit()
    return result

def ledger(db):
    return sorted((row.agent_id,row.kind,row.amount_cents)
        for row in db.query(AmbassadorCommission).all())

def test_first_payment_only_direct_recruiter(env):
    result=credit(env,12,"WISE-INV-00000012")
    assert result["first_payment"]
    assert ledger(env)==[(2,"sponsor",1000),(3,"activation",2000)]

def test_other_ambassador_earns_only_on_direct_recruited_firms(env):
    credit(env,11,"WISE-INV-00000011")
    assert ledger(env)==[(1,"sponsor",1000),(2,"activation",2000)]

def test_renewal_only_business_owner(env):
    credit(env,12,"WISE-INV-00000012")
    credit(env,12,"WISE-INV-00010012","2026-12")
    assert ledger(env)==[(2,"sponsor",1000),(3,"activation",2000),
                         (3,"recurring",500)]

def test_duplicate_transaction_reference_and_month_rejected(env):
    credit(env,12,"WISE-INV-00000012")
    with pytest.raises(ValueError,match="referinta"):
        credit(env,11,"WISE-INV-00000012")
    env.rollback()
    with pytest.raises(ValueError,match="deja"):
        credit(env,12,"WISE-INV-00000013")
    env.rollback()
    assert len(ledger(env))==2

def test_no_ambassador_still_can_subscribe(env):
    result=credit(env,13,"WISE-INV-00000013")
    assert result["awards"]==[]
    assert ledger(env)==[]

@pytest.mark.parametrize("value",["bad"," ","invalid<>value"])
def test_invalid_reference_rejected(env,value):
    with pytest.raises(ValueError):
        credit(env,12,value)
    env.rollback()

def test_invalid_month_and_amount_rejected(env):
    with pytest.raises(ValueError):
        credit(env,12,"WISE-INV-00000012","2026-13")
    env.rollback()
    with pytest.raises(ValueError):
        credit(env,12,"WISE-INV-00000012",amount=6699)
    env.rollback()

def test_tier_boundaries():
    assert [tier(n)["rate_cents"] for n in (1,25,26,50,51)]==[
        500,500,1000,1000,1500]


def test_spreadsheet_export_formula_injection_is_neutralized():
    from loial_revenue_commissions import excel_literal
    for malicious in ("=1+1","+SUM(A1:A4)","-NOW()","@cmd","  =HYPERLINK('evil')"):
        assert excel_literal(malicious).startswith("'")
    assert excel_literal("Ambasador LOIAL")=="Ambasador LOIAL"
    assert excel_literal(67.0)==67.0
