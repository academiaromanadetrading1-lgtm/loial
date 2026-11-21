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
    assert db.get(Business,11).plan=="business"
    from loial_multilocation import direct_plan
    # Paid Business grants single-location features, never ProBusiness.
    state.paid_until=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    assert direct_plan(db,11,state)=="business"
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


def test_recurring_portfolio_rates_at_26_and_51_verified_merchants():
    db,state=db_fixture()
    from loial_stripe_billing import utc_iso, now_utc
    stamp=utc_iso(now_utc())
    for firm_id in range(100,151):
        db.add(PaidMerchantInvoice(
            external_invoice_id=f"in_test_tier_{firm_id}",
            business_id=firm_id,agent_id=2,payment_intent_id=None,
            subscription_id="sub_tier",provider_customer_id="cus_tier",
            currency="eur",gross_paid_cents=6700,net_revenue_cents=6700,
            eligible=1,review_reason="",refunded=0,paid_at=stamp,
            period="2026-11",created_at=stamp))
        db.flush()
        invoice=db.query(PaidMerchantInvoice).filter(
            PaidMerchantInvoice.external_invoice_id==f"in_test_tier_{firm_id}").one()
        db.add(AmbassadorCommission(
            invoice_id=invoice.id,agent_id=2,kind="recurring",
            amount_cents=500,period="2026-11",
            status="pending",created_at=stamp))
        if firm_id==125:
            db.flush()
            result=recompute_recurring(db,Agent,"2026-11",2)
            assert result["active_firms"]==26
            assert result["recurring_rate_cents"]==1000
            assert all(x.amount_cents==1000 for x in db.query(
                AmbassadorCommission).all())
    db.flush()
    result=recompute_recurring(db,Agent,"2026-11",2)
    assert result["active_firms"]==51
    assert result["recurring_rate_cents"]==1500
    assert all(x.amount_cents==1500 for x in db.query(
        AmbassadorCommission).all())


def test_verified_probusiness_activation_and_renewal():
    from loial_multilocation import direct_plan
    db,state=db_fixture()
    def book_pro(invoice_id,month):
        inv=invoice(invoice_id,month)
        inv["amount_paid"]=27000
        inv["lines"]["data"][0]["price"]["id"]="price_loial_270"
        result=process_paid_invoice(db,inv,state,db.get(Business,11),Agent,
            "price_loial_270",PaidMerchantInvoice,AmbassadorCommission,
            SponsorRelationship,tier,recompute_recurring,expected_cents=27000)
        db.commit()
        return result
    try:
        assert book_pro("in_pro_first",11)["first"] is True
        assert book_pro("in_pro_renew",12)["first"] is False
        assert book_pro("in_pro_renew",12)["duplicate"] is True
        assert sorted((x.agent_id,x.kind,x.amount_cents) for x in
                      db.query(AmbassadorCommission).all())==[
            (1,"sponsor",4000),(2,"activation",4000),(2,"recurring",2000)]
        row=db.query(PaidMerchantInvoice).filter_by(
            external_invoice_id="in_pro_renew").one()
        assert row.review_reason=="stripe_verified_probusiness"
        assert db.get(Business,11).plan=="probusiness"
        assert state.last_paid_invoice=="in_pro_renew"
        # Move the paid period relative to the test clock, not real billing.
        state.paid_until=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        assert direct_plan(db,11,state)=="probusiness"
        row.refunded=1
        db.flush()
        assert direct_plan(db,11,state)!="probusiness"
    finally:
        db.close()


def test_wrong_customer_and_second_invoice_same_month_do_not_pay():
    db,state=db_fixture()
    try:
        wrong=invoice("in_wrong_customer")
        wrong["customer"]="cus_other"
        assert book(db,state,wrong)=={"review":"customer_mismatch"}
        assert book(db,state,invoice("in_valid"))["credited"]
        assert book(db,state,invoice("in_same_month"))=={
            "review":"duplicate_business_billing_month"}
        assert db.query(PaidMerchantInvoice).count()==1
        assert db.query(AmbassadorCommission).count()==2
    finally:
        db.close()


def test_delayed_payment_failure_must_match_current_subscription():
    from loial_stripe_billing import subscription_event_matches
    db,state=db_fixture()
    try:
        assert subscription_event_matches(state,"cus_loial","sub_loial")
        assert subscription_event_matches(state,{"id":"cus_loial"},{"id":"sub_loial"})
        assert not subscription_event_matches(state,"cus_loial","sub_old")
        assert not subscription_event_matches(state,"cus_other","sub_loial")
        assert not subscription_event_matches(state,"cus_loial",None)
        assert not subscription_event_matches(None,"cus_loial","sub_loial")
    finally:
        db.close()


def test_refund_of_old_period_preserves_new_period_and_paid_commission():
    from loial_stripe_billing import apply_full_subscription_refund
    db,state=db_fixture()
    try:
        first=invoice("in_first")
        first["payment_intent"]="pi_first"
        assert book(db,state,first)["credited"]
        assert book(db,state,invoice("in_current",12))["credited"]
        old=db.query(PaidMerchantInvoice).filter_by(external_invoice_id="in_first").one()
        assert old.payment_intent_id=="pi_first"
        old_activation=db.query(AmbassadorCommission).filter_by(
            invoice_id=old.id,kind="activation").one()
        old_activation.status="paid"
        until=state.paid_until
        result=apply_full_subscription_refund(db,old,Agent,recompute_recurring)
        assert result["manual_recovery_required"] is True
        assert old_activation.status=="paid"
        assert state.paid_until==until
        assert state.last_paid_invoice=="in_current"
        assert apply_full_subscription_refund(db,old,Agent,recompute_recurring)["duplicate"]
        current=db.query(PaidMerchantInvoice).filter_by(external_invoice_id="in_current").one()
        result=apply_full_subscription_refund(db,current,Agent,recompute_recurring)
        assert result["reversed"] is True
        assert not entitlements(state)["active"]
        assert state.grace_until is None
        assert db.query(AmbassadorCommission).filter_by(
            invoice_id=current.id,kind="recurring").one().status=="reversed"
    finally:
        db.close()
