"""LOIAL Stripe Billing: hosted Checkout, verified subscription events and access.

Isolated from any other Stripe projects. Never hardcode keys. Stripe events must
be signed and all billable invoice lines must match LOIAL's configured price.
No money movement to ambassadors happens here (Wise payouts remain manual).
"""
import os
import re
from datetime import datetime, timezone, timedelta
from sqlalchemy import Column, Integer, String, UniqueConstraint
from sqlalchemy.orm import declarative_base
from fastapi import APIRouter, Depends, HTTPException, Request

BillingBase=declarative_base()
GRACE_DAYS=3
PRICE_CENTS=6700
from loial_plans import PLANS, plan_for_amount, renewal_rate, public_catalog

class LoialSubscription(BillingBase):
    __tablename__="loial_stripe_subscriptions"
    business_id=Column(Integer,primary_key=True)
    customer_id=Column(String(128),unique=True)
    subscription_id=Column(String(128),unique=True)
    status=Column(String(32),nullable=False,default="pending")
    paid_until=Column(String(50))
    grace_until=Column(String(50))
    last_paid_invoice=Column(String(128))
    last_event_at=Column(Integer,default=0,nullable=False)
    updated_at=Column(String(50),nullable=False)

class StripeWebhookEvent(BillingBase):
    __tablename__="loial_stripe_webhook_events"
    id=Column(String(128),primary_key=True)
    type=Column(String(100),nullable=False)
    received_at=Column(String(50),nullable=False)

def now_utc():
    return datetime.now(timezone.utc)

def from_unix(seconds):
    if not isinstance(seconds,int) or seconds<1:return None
    return datetime.fromtimestamp(seconds,tz=timezone.utc)

def utc_iso(dt):
    return dt.astimezone(timezone.utc).isoformat() if dt else None

def parse_utc(s):
    if not s:return None
    try:return datetime.fromisoformat(s).astimezone(timezone.utc)
    except (ValueError,TypeError):return None

def entitlements(state,clock=None):
    """Subscription permissions do not depend on mutable business.plan flags."""
    now=clock or now_utc()
    if state is None:return {"active":False,"status":"no_subscription"}
    if state.status in ("canceled","unpaid","incomplete_expired"):
        return {"active":False,"status":state.status}
    paid_until=parse_utc(state.paid_until)
    grace_until=parse_utc(state.grace_until)
    if paid_until and now<paid_until:
        return {"active":True,"status":"paid"}
    if state.status=="past_due" and grace_until and now<grace_until:
        return {"active":True,"status":"grace_period","grace_until":state.grace_until}
    return {"active":False,"status":"expired_or_unpaid"}

def effective_entitlements(db,business_id,state=None):
    from loial_manual_admin import manual_grant
    if state is None:
        state=db.get(LoialSubscription,business_id)
    paid=entitlements(state)
    from loial_multilocation import direct_plan, inherited_access, GroupMember
    if paid["active"]:
        return {**paid,"plan":direct_plan(db,business_id,state)}
    if manual_grant(db,business_id):
        return {"active":True,"status":"manual_grant","plan":"business"}
    # Some isolated test deployments initialize only the old billing metadata.
    from sqlalchemy import inspect
    if inspect(db.connection()).has_table(GroupMember.__tablename__):
        inherited=inherited_access(db,business_id)
        if inherited:return inherited
    return {**paid,"plan":"start"}

def invoice_period(invoice):
    """Use billed service period, not webhook delivery date, for deduplication."""
    lines=((invoice.get("lines") or {}).get("data") or [])
    for line in lines:
        period=line.get("period") or {}
        start=from_unix(period.get("start"))
        end=from_unix(period.get("end"))
        if start and end and end>start:
            return start.strftime("%Y-%m"),end
    return None,None

def invoice_is_eligible(invoice,price_id,expected_cents=PRICE_CENTS):
    if not price_id or invoice.get("status")!="paid" or invoice.get("paid") is not True:
        return False
    if invoice.get("paid_out_of_band") or invoice.get("currency")!="eur":
        return False
    if invoice.get("amount_paid")!=expected_cents:
        return False
    items=((invoice.get("lines") or {}).get("data") or [])
    if len(items)!=1:return False
    if items[0].get("quantity",1)!=1:return False
    price=items[0].get("price") or {}
    pricing=items[0].get("pricing") or {}
    return (price.get("id")==price_id or
            (pricing.get("price_details") or {}).get("price")==price_id)

def process_paid_invoice(db, invoice, state, business, Agent, price_id,
                         PaidMerchantInvoice, AmbassadorCommission,
                         SponsorRelationship, tier, recompute_recurring, expected_cents=PRICE_CENTS):
    if not invoice_is_eligible(invoice,price_id,expected_cents):
        return {"review":"invoice_not_eligible"}
    plan=plan_for_amount(expected_cents)
    if not state or not business or state.business_id!=business.id:
        return {"review":"subscription_not_bound"}
    invoice_id=invoice.get("id")
    if not isinstance(invoice_id,str) or not invoice_id.startswith("in_"):
        return {"review":"invalid_invoice_id"}
    if db.query(PaidMerchantInvoice).filter(
        PaidMerchantInvoice.external_invoice_id==invoice_id).first():
        return {"duplicate":True}
    period,covered_until=invoice_period(invoice)
    if not period or not covered_until:
        return {"review":"missing_service_period"}
    invoice_sub=invoice.get("subscription")
    if isinstance(invoice_sub,dict):invoice_sub=invoice_sub.get("id")
    invoice_customer=invoice.get("customer")
    if isinstance(invoice_customer,dict):invoice_customer=invoice_customer.get("id")
    if not state.customer_id or invoice_customer!=state.customer_id:
        return {"review":"customer_mismatch"}
    if invoice_sub and state.subscription_id and invoice_sub!=state.subscription_id:
        return {"review":"subscription_mismatch"}
    if not invoice_sub and not state.subscription_id:
        return {"review":"missing_subscription"}
    prior=db.query(PaidMerchantInvoice).filter(
        PaidMerchantInvoice.business_id==business.id,
        PaidMerchantInvoice.eligible==1).count()
    month_existing=db.query(PaidMerchantInvoice).filter(
        PaidMerchantInvoice.business_id==business.id,
        PaidMerchantInvoice.period==period,
        PaidMerchantInvoice.eligible==1).count()
    if month_existing:return {"review":"duplicate_business_billing_month"}
    stamp=utc_iso(now_utc())
    agent=db.query(Agent).filter(Agent.id==business.agent_id,
        Agent.active.is_(True)).first() if business.agent_id else None
    row=PaidMerchantInvoice(
        external_invoice_id=invoice_id,business_id=business.id,
        agent_id=agent.id if agent else None,
        payment_intent_id=None,subscription_id=state.subscription_id,
        provider_customer_id=state.customer_id or "",
        currency="eur",gross_paid_cents=expected_cents,
        net_revenue_cents=expected_cents,eligible=1,
        review_reason="stripe_verified_probusiness" if plan.code=="probusiness" else "",refunded=0,
        paid_at=stamp,period=period,created_at=stamp)
    db.add(row);db.flush()
    first=prior==0
    if agent:
        kind="activation" if first else "recurring"
        cents=plan.activation_cents if first else renewal_rate(plan.code,1)
        db.add(AmbassadorCommission(invoice_id=row.id,agent_id=agent.id,
            kind=kind,amount_cents=cents,period=period,status="pending",
            created_at=stamp))
        if first:
            edge=db.query(SponsorRelationship).filter(
                SponsorRelationship.ambassador_id==agent.id).first()
            if edge and edge.sponsor_id!=agent.id:
                sponsor=db.query(Agent).filter(Agent.id==edge.sponsor_id,
                    Agent.active.is_(True)).first()
                if sponsor:
                    db.add(AmbassadorCommission(invoice_id=row.id,
                        agent_id=sponsor.id,kind="sponsor",
                        amount_cents=plan.sponsor_cents,period=period,status="pending",
                        created_at=stamp))
        recompute_recurring(db,Agent,period,agent.id)
    existing_paid=parse_utc(state.paid_until)
    if not existing_paid or covered_until>existing_paid:
        state.paid_until=utc_iso(covered_until)
        state.grace_until=None
        state.last_paid_invoice=invoice_id
        state.status="active"
    state.updated_at=stamp
    # Legacy flags are used by existing feature checks; commercial plan is derived from verified invoices.
    business.plan="probusiness"
    business.max_customers=999999
    return {"credited":True,"first":first,"period":period}

def record_payment_failure(state, when=None):
    when=when or now_utc()
    if not state:return {"ignored":"unknown_subscription"}
    if state.status in ("canceled","unpaid","incomplete_expired"):
        return {"ignored":"already_terminated"}
    state.status="past_due"
    if not state.grace_until:
        state.grace_until=utc_iso(when+timedelta(days=GRACE_DAYS))
    state.updated_at=utc_iso(when)
    return {"grace_until":state.grace_until}

def install_stripe_billing(app,engine,factory,Business,Agent,
                           PaidMerchantInvoice,AmbassadorCommission,
                           SponsorRelationship,tier,recompute_recurring,
                           secret,algorithm):
    import stripe
    from jose import jwt,JWTError
    from sqlalchemy.exc import IntegrityError
    from fastapi.responses import JSONResponse
    BillingBase.metadata.create_all(bind=engine)
    from loial_manual_admin import GrantBase
    GrantBase.metadata.create_all(bind=engine)
    api=APIRouter(prefix="/api/loial-stripe",tags=["LOIAL Stripe subscriptions"])

    def session():
        db=factory()
        try:yield db
        finally:db.close()

    def own_business(request:Request,db=Depends(session)):
        h=request.headers.get("Authorization","")
        if not h.startswith("Bearer "):
            raise HTTPException(status_code=401,detail="Autentificare necesara")
        try:claims=jwt.decode(h[7:],secret,algorithms=[algorithm])
        except JWTError:raise HTTPException(status_code=401,detail="Sesiune invalida")
        if claims.get("role")!="business":
            raise HTTPException(status_code=403,detail="Cont de firma necesar")
        biz=db.query(Business).filter(Business.id==claims.get("business_id"),
            Business.email==claims.get("sub")).first()
        if not biz:raise HTTPException(status_code=403,detail="Firma invalida")
        return biz

    @api.get("/me")
    def status(biz=Depends(own_business),db=Depends(session)):
        state=db.query(LoialSubscription).filter(
            LoialSubscription.business_id==biz.id).first()
        free_pilot=os.getenv("LOIAL_PUBLIC_FREE_PILOT","0")=="1"
        configured=not free_pilot and (os.getenv("LOIAL_STRIPE_SECRET_KEY","").startswith(
            ("sk_test_","sk_live_")) and
            os.getenv("LOIAL_STRIPE_PRICE_ID","").startswith("price_") and
            bool(os.getenv("LOIAL_STRIPE_WEBHOOK_SECRET","")))
        return {"plan_price_eur":67,"plans":public_catalog(),"free_pilot_only":free_pilot,
                "subscription":effective_entitlements(db,biz.id,state),
                "status":state.status if state else "not_started",
                "paid_until":state.paid_until if state else None,
                "checkout_configured":configured}

    @api.post("/checkout")
    def checkout(plan: str="business",biz=Depends(own_business),db=Depends(session)):
        if os.getenv("LOIAL_PUBLIC_FREE_PILOT","0")=="1":
            raise HTTPException(status_code=503,
                detail="Programul LOIAL este momentan in pilot gratuit; abonamentele vor fi disponibile ulterior")
        from loial_multilocation import GroupMember
        from sqlalchemy import inspect
        if inspect(db.connection()).has_table(GroupMember.__tablename__) and db.get(GroupMember,biz.id):
            raise HTTPException(409,"Locatia apartine unei organizatii")
        key=os.getenv("LOIAL_STRIPE_SECRET_KEY","")
        if plan not in ("business","probusiness"):
            raise HTTPException(422,"Plan invalid")
        # Expansion is explicitly gated until multi-location integration is validated.
        if plan=="probusiness" and os.getenv("LOIAL_MULTILOCATION_READY","0")!="1":
            raise HTTPException(503,"ProBusiness este in pregatire")
        price=os.getenv("LOIAL_STRIPE_PROBUSINESS_PRICE_ID" if plan=="probusiness" else "LOIAL_STRIPE_PRICE_ID","")
        expected_cents=PLANS[plan].price_cents
        other=os.getenv("LOIAL_STRIPE_PRICE_ID" if plan=="probusiness" else "LOIAL_STRIPE_PROBUSINESS_PRICE_ID","")
        if price and price==other:
            raise HTTPException(503,"Configuratie Stripe ambigua")
        origin=os.getenv("LOIAL_PUBLIC_ORIGIN","https://loial.space").rstrip("/")
        if not key.startswith(("sk_test_","sk_live_")) or not price.startswith("price_"):
            raise HTTPException(status_code=503,detail="Stripe LOIAL neconfigurat")
        stripe.api_key=key
        try:
            stripe_price=stripe.Price.retrieve(price)
            if stripe_price.get("unit_amount")!=expected_cents or \
               stripe_price.get("currency")!="eur" or \
               (stripe_price.get("recurring") or {}).get("interval")!="month":
                raise HTTPException(status_code=503,detail="Pret Stripe incorect pentru LOIAL")
        except stripe.error.StripeError:
            raise HTTPException(status_code=502,detail="Configurarea pretului Stripe nu poate fi verificata")
        state=db.query(LoialSubscription).filter(
            LoialSubscription.business_id==biz.id).first()
        if state and state.subscription_id and state.status in (
            "pending","active","past_due"):
            raise HTTPException(status_code=409,
                detail="Există deja un abonament Stripe. Folosește portalul de facturare pentru actualizare.")
        kwargs={
            "mode":"subscription",
            "line_items":[{"price":price,"quantity":1}],
            "client_reference_id":str(biz.id),
            "customer_email":biz.email,
            "subscription_data":{"metadata":{"loial_business_id":str(biz.id)}},
            "success_url":origin+"/platform.html?billing=success",
            "cancel_url":origin+"/platform.html?billing=cancel",
            "metadata":{"loial_business_id":str(biz.id)},
        }
        # Reuse bound customer when available; never pass both customer and email.
        if state and state.customer_id:
            kwargs.pop("customer_email")
            kwargs["customer"]=state.customer_id
        try:
            result=stripe.checkout.Session.create(**kwargs)
        except stripe.error.StripeError:
            raise HTTPException(status_code=502,detail="Checkout indisponibil")
        return {"url":result.url,"status":"pending_payment",
                "access_granted":False}

    @api.post("/portal")
    def portal(biz=Depends(own_business),db=Depends(session)):
        if os.getenv("LOIAL_PUBLIC_FREE_PILOT","0")=="1":
            raise HTTPException(status_code=503,detail="Stripe nu este activ in pilotul gratuit")
        state=db.query(LoialSubscription).filter(
            LoialSubscription.business_id==biz.id).first()
        if not state or not state.customer_id:
            raise HTTPException(status_code=404,detail="Nu exista abonament Stripe")
        key=os.getenv("LOIAL_STRIPE_SECRET_KEY","")
        if not key:raise HTTPException(status_code=503,detail="Stripe neconfigurat")
        stripe.api_key=key
        try:
            result=stripe.billing_portal.Session.create(
                customer=state.customer_id,
                return_url=os.getenv("LOIAL_PUBLIC_ORIGIN","https://loial.space").rstrip("/")+"/platform.html")
        except stripe.error.StripeError:
            raise HTTPException(status_code=502,detail="Portal indisponibil")
        return {"url":result.url}

    @api.post("/webhook")
    async def webhook(request:Request,db=Depends(session)):
        if os.getenv("LOIAL_PUBLIC_FREE_PILOT","0")=="1":
            raise HTTPException(status_code=503,detail="Stripe dezactivat in pilotul gratuit")
        webhook_key=os.getenv("LOIAL_STRIPE_WEBHOOK_SECRET","")
        if not webhook_key:raise HTTPException(status_code=503,detail="Webhook neconfigurat")
        body=await request.body()
        if len(body)>1024*1024:raise HTTPException(status_code=413,detail="Payload prea mare")
        try:
            event=stripe.Webhook.construct_event(body,
                request.headers.get("Stripe-Signature",""),webhook_key)
        except (ValueError,stripe.error.SignatureVerificationError):
            raise HTTPException(status_code=400,detail="Semnatura Stripe invalida")
        # Do not mix test receipts and live accounts. Test mode requires a test key.
        key=os.getenv("LOIAL_STRIPE_SECRET_KEY","")
        if not key or bool(event["livemode"])!=key.startswith("sk_live_"):
            return {"status":"ignored_mode_mismatch"}
        eid=event["id"]
        if db.query(StripeWebhookEvent).filter(
            StripeWebhookEvent.id==eid).first():
            return {"status":"duplicate"}
        obj=event["data"]["object"]
        typ=event["type"]
        outcome={"ignored":typ}
        def lookup_by_customer(cus):
            if not cus:return None
            return db.query(LoialSubscription).filter(
                LoialSubscription.customer_id==cus).first()
        if typ=="checkout.session.completed" and obj.get("mode")=="subscription":
            identifier=obj.get("client_reference_id") or (obj.get("metadata") or {}).get("loial_business_id")
            if not str(identifier or "").isdigit():
                raise HTTPException(status_code=422,detail="Referinta firma lipsa")
            business=db.query(Business).filter(Business.id==int(identifier)).first()
            if not business:raise HTTPException(status_code=422,detail="Firma necunoscuta")
            customer=obj.get("customer");subscription=obj.get("subscription")
            if not customer or not subscription:
                raise HTTPException(status_code=422,detail="Checkout incomplet")
            collision=db.query(LoialSubscription).filter(
                LoialSubscription.customer_id==customer).first()
            if collision and collision.business_id!=business.id:
                raise HTTPException(status_code=409,detail="Stripe customer asociat altei firme")
            state=db.query(LoialSubscription).filter(
                LoialSubscription.business_id==business.id).first()
            if not state:
                state=LoialSubscription(business_id=business.id,status="pending",
                    updated_at=utc_iso(now_utc()))
                db.add(state)
            if state.subscription_id and state.subscription_id!=subscription and entitlements(state)["active"]:
                raise HTTPException(status_code=409,detail="Alt abonament activ asociat firmei")
            if state.subscription_id!=subscription:
                # A new subscription starts with no access until its own
                # verified invoice arrives, even after a prior cancellation.
                state.status="pending"
                state.paid_until=None
                state.grace_until=None
                state.last_paid_invoice=None
            state.customer_id=customer
            state.subscription_id=subscription
            state.updated_at=utc_iso(now_utc())
            outcome={"linked_business":business.id,"access_granted":False}
        elif typ=="invoice.paid":
            customer=obj.get("customer")
            state=lookup_by_customer(customer)
            # Stripe can deliver invoice.paid before checkout.session.completed.
            # Reconcile by subscription metadata only through Stripe authenticated API.
            sub_id=obj.get("subscription")
            if isinstance(sub_id,dict):sub_id=sub_id.get("id")
            if not state and sub_id:
                stripe.api_key=key
                sub=stripe.Subscription.retrieve(sub_id)
                identifier=(sub.get("metadata") or {}).get("loial_business_id")
                if str(identifier or "").isdigit():
                    business=db.query(Business).filter(Business.id==int(identifier)).first()
                    if business:
                        state=db.query(LoialSubscription).filter(
                            LoialSubscription.business_id==business.id).first()
                        if not state:
                            state=LoialSubscription(business_id=business.id,
                                updated_at=utc_iso(now_utc()))
                            db.add(state)
                        state.customer_id=customer
                        state.subscription_id=sub_id
            if not state:
                raise HTTPException(status_code=503,
                    detail="Abonamentul necesita reconciliere; Stripe poate reincerca evenimentul")
            if state.status in ("canceled","unpaid","incomplete_expired"):
                outcome={"ignored":"terminated_subscription_no_reactivation"}
                db.add(StripeWebhookEvent(id=eid,type=typ,received_at=utc_iso(now_utc())))
                db.commit()
                return {"status":"recorded",**outcome}
            business=db.query(Business).filter(Business.id==state.business_id).first()
            business_price=os.getenv("LOIAL_STRIPE_PRICE_ID","")
            pro_price=os.getenv("LOIAL_STRIPE_PROBUSINESS_PRICE_ID","")
            if business_price and business_price==pro_price:
                raise HTTPException(503,"Configuratie Stripe ambigua")
            if invoice_is_eligible(obj,pro_price,27000) and os.getenv("LOIAL_MULTILOCATION_READY","0")=="1":
                price,amount=pro_price,27000
            else:
                price,amount=business_price,6700
            outcome=process_paid_invoice(db,obj,state,business,Agent,
                price,PaidMerchantInvoice,
                AmbassadorCommission,SponsorRelationship,tier,recompute_recurring,amount)
        elif typ in ("credit_note.created","charge.dispute.created"):
            # Never continue payout on disputed/credited invoices. Partial
            # credits require manual review; no automatic money clawbacks.
            from loial_revenue_commissions import reverse_invoice
            invoice_id=obj.get("invoice")
            if isinstance(invoice_id,dict):invoice_id=invoice_id.get("id")
            record=(db.query(PaidMerchantInvoice).filter(
                PaidMerchantInvoice.external_invoice_id==invoice_id).first()
                if invoice_id else None)
            if record:
                for entry in db.query(AmbassadorCommission).filter(
                    AmbassadorCommission.invoice_id==record.id).all():
                    if entry.status in ("pending","approved"):
                        entry.status="held"
                record.review_reason="stripe_credit_or_dispute_manual_review"
                outcome={"held":True,"manual_review":True}
            else:
                outcome={"review":"billing_dispute_unmatched"}
        elif typ=="invoice.payment_failed":
            state=lookup_by_customer(obj.get("customer"))
            outcome=record_payment_failure(state)
        elif typ in ("customer.subscription.updated","customer.subscription.deleted"):
            sub_id=obj.get("id")
            state=db.query(LoialSubscription).filter(
                LoialSubscription.subscription_id==sub_id).first()
            if state:
                incoming_status="canceled" if typ.endswith("deleted") else obj.get("status","")
                if incoming_status in ("canceled","unpaid","incomplete_expired"):
                    state.status=incoming_status
                    state.grace_until=None
                    outcome={"terminated":True}
                elif incoming_status=="past_due":
                    outcome=record_payment_failure(state)
                else:
                    # Never grant access solely from subscription.status=active.
                    outcome={"status_observed":incoming_status}
                state.updated_at=utc_iso(now_utc())
        db.add(StripeWebhookEvent(id=eid,type=typ,received_at=utc_iso(now_utc())))
        try:db.commit()
        except IntegrityError:
            db.rollback()
            return {"status":"duplicate"}
        return {"status":"recorded",**outcome}

    # Keep free loyalty accessible, but deny premium features after grace.
    # A paid plan flag in the legacy Business table is not an entitlement.
    @app.middleware("http")
    async def enforce_premium_access(request,call_next):
        path=request.url.path
        premium=(path.startswith("/api/loial-ai/") or
                 path in ("/api/loial-inbox/send", "/api/loial-inbox/audience",
                          "/api/loial-inbox/sent"))
        # Update stale subscription flags for business requests even if they
        # use a legacy route that checks only Business.plan.
        if path.startswith("/api/") and not path.startswith("/api/loial-stripe/"):
            header=request.headers.get("Authorization","")
            if header.startswith("Bearer "):
                try:
                    claims=jwt.decode(header[7:],secret,algorithms=[algorithm])
                    if claims.get("role")=="business":
                        db=factory()
                        try:
                            biz=db.query(Business).filter(
                                Business.id==claims.get("business_id"),
                                Business.email==claims.get("sub")).first()
                            if biz:
                                state=db.query(LoialSubscription).filter(
                                    LoialSubscription.business_id==biz.id).first()
                                access=effective_entitlements(db,biz.id,state)
                                desired="probusiness" if access["active"] else "free"
                                cap=999999 if access["active"] else 50
                                if biz.plan!=desired or biz.max_customers!=cap:
                                    biz.plan=desired
                                    biz.max_customers=cap
                                    db.commit()
                                if premium and not access["active"]:
                                    return JSONResponse(status_code=402,content={
                                        "detail":"Abonament ProBusiness inactiv",
                                        "billing_status":access["status"]})
                        finally:db.close()
                except JWTError:
                    return JSONResponse(status_code=401,content={
                        "detail":"Sesiune invalida"})
            elif premium and request.method!="OPTIONS":
                # Authentication will still be enforced by the endpoint,
                # but premium functions must never be granted anonymously.
                return JSONResponse(status_code=401,content={
                    "detail":"Autentificare necesara"})
        return await call_next(request)

    app.include_router(api)
