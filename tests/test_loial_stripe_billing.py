"""LOIAL Stripe billing regression coverage, isolated in-memory, no network."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from sqlalchemy import Column, Integer, String, Boolean, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from loial_stripe_billing import (
    BillingBase, LoialSubscription, StripeWebhookEvent, PRICE_CENTS,
    GRACE_DAYS, entitlements, record_payment_failure, invoice_is_eligible,
    process_paid_invoice,
)
from loial_revenue_commissions import (
    RevenueBase, PaidMerchantInvoice, AmbassadorCommission,
    SponsorRelationship, tier, recompute_recurring,
)

Base=declarative_base()
class Agent(Base):
    __tablename__="stripe_test_agent"
    id=Column(Integer,primary_key=True)
    active=Column(Boolean,default=True)
class Business(Base):
    __tablename__="stripe_test_business"
    id=Column(Integer,primary_key=True)
    agent_id=Column(Integer)
    plan=Column(String,default="free")
    max_customers=Column(Integer,default=50)

def db_fixture():
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    BillingBase.metadata.create_all(engine)
    RevenueBase.metadata.create_all(engine)
    db=sessionmaker(bind=engine)()
    db.add_all([Agent(id=1,active=True),Agent(id=2,active=True),
                Agent(id=3,active=True),Business(id=11,agent_id=2)])
    db.add(SponsorRelationship(ambassador_id=2,sponsor_id=1,referred_at="now"))
    state=LoialSubscription(business_id=11,customer_id="cus_loial",
        subscription_id="sub_loial",status="pending",
        updated_at=datetime.now(timezone.utc).isoformat())
    db.add(state)
    db.commit()
    return db,state

def invoice(invoice_id,month=11):
    start=datetime(2026,month,1,tzinfo=timezone.utc)
    finish=datetime(2027,1,1,tzinfo=timezone.utc) if month==12 else datetime(2026,month+1,1,tzinfo=timezone.utc)
    return {"id":invoice_id,"customer":"cus_loial","subscription":"sub_loial",
        "status":"paid","paid":True,"currency":"eur",
        "amount_paid":PRICE_CENTS,"billing_reason":"subscription_cycle",
        "lines":{"data":[{"price":{"id":"price_loial_67"},
               "period":{"start":int(start.timestamp()),
                         "end":int(finish.timestamp())}}]}}

def book(db,state,inv):
    result=process_paid_invoice(db,inv,state,db.get(Business,11),Agent,
        "price_loial_67",PaidMerchantInvoice,AmbassadorCommission,
        SponsorRelationship,tier,recompute_recurring)
    db.commit()
    return result

def test_67_euro_invoice_and_one_direct_recruiter():
    db,state=db_fixture()
    result=book(db,state,invoice("in_loial1"))
    assert result["credited"] and result["first"]
    assert db.get(Business,11).plan=="probusiness"
    entries=db.query(AmbassadorCommission).all()
    assert sorted((x.agent_id,x.kind,x.amount_cents) for x in entries)==[
        (1,"sponsor",1000),(2,"activation",2000)]
    assert entitlements(state,datetime(2026,11,15,tzinfo=timezone.utc))["active"]

def test_monthly_renewal_pays_only_business_owner():
    db,state=db_fixture()
    book(db,state,invoice("in_loial1"))
    book(db,state,invoice("in_loial2",month=12))
    rows=db.query(AmbassadorCommission).all()
    assert len(rows)==3
    assert [(r.agent_id,r.amount_cents) for r in rows if r.kind=="recurring"]==[(2,500)]
    assert len([r for r in rows if r.kind=="sponsor"])==1
    assert book(db,state,invoice("in_loial2",month=12))["duplicate"]

def test_price_currency_and_price_id_require_match():
    example=invoice("in_loial")
    assert invoice_is_eligible(example,"price_loial_67")
    assert not invoice_is_eligible(example,"price_other")
    example["amount_paid"]=6500
    assert not invoice_is_eligible(example,"price_loial_67")
    example["amount_paid"]=6700
    example["currency"]="usd"
    assert not invoice_is_eligible(example,"price_loial_67")

def test_no_authentication_from_unpaid_or_checkout():
    db,state=db_fixture()
    assert not entitlements(state)["active"]
    state.status="active"
    assert not entitlements(state)["active"]

def test_three_day_grace_then_suspension_and_reactivation():
    db,state=db_fixture()
    paid_until=datetime(2026,12,1,tzinfo=timezone.utc)
    state.paid_until=paid_until.isoformat()
    state.status="active"
    record_payment_failure(state,paid_until)
    assert GRACE_DAYS==3
    assert entitlements(state,paid_until+timedelta(days=2))["active"]
    assert not entitlements(state,paid_until+timedelta(days=3,seconds=1))["active"]
    book(db,state,invoice("in_loial2",month=12))
    assert entitlements(state,paid_until+timedelta(days=4))["active"]
    assert state.grace_until is None

def test_canceled_subscription_never_active():
    db,state=db_fixture()
    state.paid_until=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat()
    state.status="canceled"
    assert not entitlements(state)["active"]

def test_wrong_subscription_fails_closed():
    db,state=db_fixture()
    wrong=invoice("in_other")
    wrong["subscription"]="sub_another"
    assert book(db,state,wrong)=={"review":"subscription_mismatch"}
    assert db.query(AmbassadorCommission).count()==0
