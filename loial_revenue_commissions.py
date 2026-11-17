"""LOIAL verified income ledger. Pilot: manual Wise Business reconciliation.

Only a platform administrator who has independently checked a real Wise receipt
may credit a business. No API-driven transfers and no simulated payments.
Only the direct recruiter earns a one-time EUR 10 bonus per new paying business.
Subsequent paid months reward only the ambassador who brought that business.
Legacy Stripe webhook is disabled.
"""
import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Session, declarative_base
from sqlalchemy.exc import IntegrityError

RevenueBase=declarative_base()
ACTIVATION_EUR_CENTS=2000
SPONSOR_EUR_CENTS=1000
SUBSCRIPTION_PRICE_EUR_CENTS=6700
REWARD_RELEASE_DAYS=14

def excel_literal(value):
    """Prevent user-controlled cells from executing formulas in Excel."""
    if isinstance(value,str) and value.lstrip().startswith(
            ("=","+","-","@","\\t","\\r")):
        return "'"+value
    return value


class SponsorRelationship(RevenueBase):
    __tablename__="loial_ambassador_sponsorships"
    ambassador_id=Column(Integer,primary_key=True)
    sponsor_id=Column(Integer,nullable=False,index=True)
    referred_at=Column(String(40),nullable=False)

class MerchantBilling(RevenueBase):
    __tablename__="loial_merchant_billing_links"
    business_id=Column(Integer,primary_key=True)
    provider_customer_id=Column(String(130),nullable=False,unique=True)
    linked_at=Column(String(40),nullable=False)

class BillingEvent(RevenueBase):
    __tablename__="loial_billing_events"
    event_id=Column(String(140),primary_key=True)
    event_type=Column(String(70),nullable=False)
    created_at=Column(String(40),nullable=False)

class PaidMerchantInvoice(RevenueBase):
    __tablename__="loial_paid_merchant_invoices"
    id=Column(Integer,primary_key=True)
    external_invoice_id=Column(String(140),nullable=False,unique=True)
    business_id=Column(Integer,nullable=True,index=True)
    agent_id=Column(Integer,nullable=True,index=True)
    payment_intent_id=Column(String(140),index=True)
    subscription_id=Column(String(140),nullable=True)
    provider_customer_id=Column(String(130),nullable=False)
    currency=Column(String(3),nullable=False)
    gross_paid_cents=Column(Integer,nullable=False)
    net_revenue_cents=Column(Integer,nullable=True)
    eligible=Column(Integer,nullable=False,default=0)
    review_reason=Column(String(160),nullable=False)
    refunded=Column(Integer,nullable=False,default=0)
    paid_at=Column(String(40),nullable=False)
    period=Column(String(7),nullable=False,index=True)
    created_at=Column(String(40),nullable=False)

class AmbassadorCommission(RevenueBase):
    __tablename__="loial_ambassador_income_ledger"
    id=Column(Integer,primary_key=True)
    invoice_id=Column(Integer,nullable=False,index=True)
    agent_id=Column(Integer,nullable=False,index=True)
    kind=Column(String(22),nullable=False)
    amount_cents=Column(Integer,nullable=False)
    period=Column(String(7),nullable=False,index=True)
    status=Column(String(22),nullable=False,default="pending")
    paid_at=Column(String(40))
    payout_reference=Column(String(100))
    created_at=Column(String(40),nullable=False)
    __table_args__=(UniqueConstraint("invoice_id","agent_id","kind",
                                     name="uq_loial_commission_from_invoice"),)

class AmbassadorSettlement(RevenueBase):
    __tablename__="loial_ambassador_settlements"
    id=Column(Integer,primary_key=True)
    agent_id=Column(Integer,nullable=False,index=True)
    period=Column(String(7),nullable=False)
    amount_cents=Column(Integer,nullable=False)
    paid_reference=Column(String(110),nullable=False,unique=True)
    paid_at=Column(String(40),nullable=False)
    approved_by=Column(String(120),nullable=False)

class WiseReceiptInput(BaseModel):
    business_id:int=Field(gt=0)
    wise_reference:str=Field(min_length=8,max_length=110)
    payment_month:str=Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    paid_amount_eur_cents:int=Field(ge=SUBSCRIPTION_PRICE_EUR_CENTS)
    confirmed_in_wise:bool=False
    evidence_note:str=Field(min_length=12,max_length=400)

class AmbassadorWiseDetails(BaseModel):
    password:str=Field(min_length=1,max_length=200)
    account_details:str=Field(min_length=6,max_length=150)

class MerchantLinkInput(BaseModel):
    business_id:int=Field(gt=0)
    stripe_customer_id:str=Field(min_length=7,max_length=130)

class SettlementInput(BaseModel):
    agent_id:int=Field(gt=0)
    period:str=Field(pattern=r"^\d{4}-\d{2}$")
    bank_reference:str=Field(min_length=6,max_length=110)
    document_confirmed:bool=False

def payable_commissions(db, period, status, agent_id=None):
    """Only ledger entries backed by an eligible, non-refunded invoice."""
    query=db.query(AmbassadorCommission).join(
        PaidMerchantInvoice,PaidMerchantInvoice.id==AmbassadorCommission.invoice_id
    ).filter(AmbassadorCommission.period==period,
             AmbassadorCommission.status==status,
             PaidMerchantInvoice.eligible==1,
             PaidMerchantInvoice.refunded==0,
             PaidMerchantInvoice.period==period)
    if agent_id is not None:
        query=query.filter(AmbassadorCommission.agent_id==agent_id)
    return query


def now_iso():
    return datetime.now(timezone.utc).isoformat()

def tier(active_paid_businesses):
    count=max(0,int(active_paid_businesses))
    if count>=51:return {"rank":"Ambasador Senior 50+","rate_cents":1500}
    if count>=26:return {"rank":"Ambasador Manager","rate_cents":1000}
    return {"rank":"Ambasador","rate_cents":500}

def simulate(own_new=0, own_active=0, friend_ambassadors=0,
             new_firms_per_friend=0, renewal=True):
    """Scenario, not a forecast or promise. All amounts EUR excl. VAT."""
    counts=(own_new,own_active,friend_ambassadors,new_firms_per_friend)
    if any(not isinstance(n,int) or n<0 or n>100000 for n in counts):
        raise ValueError("Input outside supported simulation bounds")
    total_new=own_new+friend_ambassadors*new_firms_per_friend
    active=own_active+own_new
    if total_new>100000:raise ValueError("Simulation too large")
    recurring=own_active*tier(active)["rate_cents"]//100 if renewal else 0
    return {
        "new_direct_commission_eur":own_new*20,
        "recurring_direct_commission_eur":recurring,
        "sponsored_ambassadors":friend_ambassadors,
        "sponsored_new_paid_firms":friend_ambassadors*new_firms_per_friend,
        "one_time_sponsor_commission_eur":friend_ambassadors*new_firms_per_friend*10,
        "estimated_month_commission_eur":own_new*20+recurring+
                                          friend_ambassadors*new_firms_per_friend*10,
        "rate_for_own_active_businesses_eur":tier(active)["rate_cents"]/100,
        "scenario_only":True,"guaranteed_income":False,
        "requires_real_paid_merchant_subscription":True,
        "max_upstream_sponsor_levels":1,
        "no_commission_for_ambassador_signup":True
    }

def sponsor_new_ambassador(db,child_agent,sponsor_code,Agent):
    """Bind once, at signup; no incentive for signup itself."""
    code=(sponsor_code or "").strip()
    if not code:return None
    if not re.fullmatch(r"LOIAL-[A-Za-z0-9-]{6,36}",code):
        return None
    sponsor=db.query(Agent).filter(Agent.qr_code==code,
        Agent.active.is_(True)).first()
    if not sponsor or sponsor.id==child_agent.id or sponsor.email==child_agent.email:
        return None
    if db.query(SponsorRelationship).filter(
        SponsorRelationship.ambassador_id==child_agent.id).first():
        return None
    visited={child_agent.id}
    cursor=sponsor.id
    while cursor:
        if cursor in visited:return None
        visited.add(cursor)
        edge=db.query(SponsorRelationship).filter(
            SponsorRelationship.ambassador_id==cursor).first()
        cursor=edge.sponsor_id if edge else None
    db.add(SponsorRelationship(ambassador_id=child_agent.id,
        sponsor_id=sponsor.id,referred_at=now_iso()))
    db.flush()
    return sponsor.id

def _signature_ok(raw:bytes, header:str, secret:str, clock=None):
    """Stripe t/v1 HMAC, 300-second replay window. No third-party SDK."""
    if not secret or len(secret)<20 or not header:return False
    fields={}
    for part in header.split(","):
        k,sep,v=part.strip().partition("=")
        if sep:fields.setdefault(k,[]).append(v)
    try:
        t=int((fields.get("t") or [""])[0])
    except (ValueError,TypeError):
        return False
    current=int(clock if clock is not None else time.time())
    if abs(current-t)>300 or t<1:return False
    expected=hmac.new(secret.encode(),str(t).encode()+b"."+raw,
                      hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected,x) for x in fields.get("v1",[]))

def _payment_id(value):
    return value.get("id") if isinstance(value,dict) else value

def _eligible_invoice(invoice):
    if invoice.get("status")!="paid" or invoice.get("paid") is not True:
        return "not_paid"
    if invoice.get("paid_out_of_band") is True:
        return "out_of_band_unverified"
    if str(invoice.get("currency","")).lower()!="eur":
        return "other_currency_requires_review"
    if invoice.get("billing_reason") not in (
        "subscription_create","subscription_cycle","subscription_update"):
        return "not_subscription_invoice"
    if not _payment_id(invoice.get("subscription")):
        return "missing_subscription_identifier"
    cents=invoice.get("amount_paid")
    net=invoice.get("total_excluding_tax")
    if (not isinstance(cents,int) or not isinstance(net,int) or
        cents<=0 or net<SUBSCRIPTION_PRICE_EUR_CENTS):
        return "not_full_price_67_eur"
    if not _payment_id(invoice.get("payment_intent")):
        # Some newer Stripe versions omit payment_intent from invoice; must
        # reconcile invoice.payments before declaring this payable.
        return "missing_payment_reference_reconcile_first"
    return ""

def recompute_recurring(db,Agent,period,agent_id):
    """Unpaid recurring month rate uses unique verified paying merchants."""
    qualified=db.query(PaidMerchantInvoice).filter(
        PaidMerchantInvoice.agent_id==agent_id,
        PaidMerchantInvoice.period==period,
        PaidMerchantInvoice.eligible==1,
        PaidMerchantInvoice.refunded==0).all()
    distinct=len({inv.business_id for inv in qualified})
    rate=tier(distinct)["rate_cents"]
    for inv in qualified:
        for entry in db.query(AmbassadorCommission).filter(
            AmbassadorCommission.invoice_id==inv.id,
            AmbassadorCommission.agent_id==agent_id,
            AmbassadorCommission.kind=="recurring",
            AmbassadorCommission.status=="pending").all():
            # Legacy invoices remain Business; only the verified Stripe billing
            # path can credit the exact ProBusiness subscription amount.
            from loial_plans import renewal_rate
            plan_code = ("probusiness" if inv.gross_paid_cents == 27000
                         and inv.review_reason == "stripe_verified_probusiness"
                         and inv.net_revenue_cents == 27000
                         else "business")
            entry.amount_cents=renewal_rate(plan_code,distinct)
    return {"active_firms":distinct,"tier":tier(distinct)["rank"],
            "recurring_rate_cents":rate}

def apply_verified_invoice(db,invoice,Agent,Business):
    invoice_id=invoice.get("id")
    customer=_payment_id(invoice.get("customer"))
    if not isinstance(invoice_id,str) or not invoice_id.startswith("in_"):
        return {"ignored":"invalid_invoice"}
    if not isinstance(customer,str) or not customer.startswith("cus_"):
        return {"ignored":"unlinked_customer"}
    existing=db.query(PaidMerchantInvoice).filter(
        PaidMerchantInvoice.external_invoice_id==invoice_id).first()
    if existing:return {"duplicate":True,"invoice_id":existing.id}
    binding=db.query(MerchantBilling).filter(
        MerchantBilling.provider_customer_id==customer).first()
    business=db.query(Business).filter(Business.id==binding.business_id).first() if binding else None
    agent=db.query(Agent).filter(Agent.id==business.agent_id,
        Agent.active.is_(True)).first() if business and business.agent_id else None
    reason=_eligible_invoice(invoice)
    if not binding:reason=reason or "merchant_not_bound_to_verified_customer"
    elif not agent:reason=reason or "no_active_direct_ambassador"
    now=now_iso()
    net=invoice.get("total_excluding_tax")
    paid=invoice.get("amount_paid")
    pi=_payment_id(invoice.get("payment_intent"))
    try:
        created=datetime.fromtimestamp(int(invoice.get("created")),tz=timezone.utc)
    except (ValueError,TypeError,OverflowError,OSError):
        created=datetime.now(timezone.utc)
    record=PaidMerchantInvoice(external_invoice_id=invoice_id,
        business_id=binding.business_id if binding else None,
        agent_id=agent.id if agent else None,provider_customer_id=customer,
        subscription_id=_payment_id(invoice.get("subscription")),
        payment_intent_id=pi if isinstance(pi,str) else None,
        currency=str(invoice.get("currency") or "").lower()[:3],
        gross_paid_cents=paid if isinstance(paid,int) else 0,
        net_revenue_cents=net if isinstance(net,int) else None,
        eligible=0 if reason else 1,
        review_reason=reason or "",refunded=0,
        paid_at=created.isoformat(),period=created.strftime("%Y-%m"),
        created_at=now)
    db.add(record);db.flush()
    if reason:return {"invoice_id":record.id,"review":reason,"credited":0}
    earlier=db.query(PaidMerchantInvoice).filter(
        PaidMerchantInvoice.business_id==business.id,
        PaidMerchantInvoice.id!=record.id,
        PaidMerchantInvoice.eligible==1).count()
    # Only one renewal commission per merchant per billing month.
    if earlier:
        already_this_month=db.query(PaidMerchantInvoice).filter(
            PaidMerchantInvoice.business_id==business.id,
            PaidMerchantInvoice.id!=record.id,
            PaidMerchantInvoice.eligible==1,
            PaidMerchantInvoice.period==record.period).count()
        if already_this_month:
            record.review_reason="second_invoice_same_merchant_month_no_extra_commission"
            return {"invoice_id":record.id,"eligible":True,
                    "credited":0,"note":"no_duplicate_monthly_commission"}
    activation=(earlier==0)
    kind="activation" if activation else "recurring"
    amount=ACTIVATION_EUR_CENTS if activation else tier(1)["rate_cents"]
    db.add(AmbassadorCommission(invoice_id=record.id,agent_id=agent.id,
        kind=kind,amount_cents=amount,period=record.period,
        status="pending",created_at=now))
    credited=amount
    if activation:
        # Only the agent's DIRECT recruiter receives EUR 10.
        # Example A recruited B, B recruited C:
        # firms brought by B -> A earns 10; firms brought by C -> B earns 10.
        sponsor=db.query(SponsorRelationship).filter(
            SponsorRelationship.ambassador_id==agent.id).first()
        if sponsor and sponsor.sponsor_id!=agent.id:
            eligible_sponsor=db.query(Agent).filter(
                Agent.id==sponsor.sponsor_id,Agent.active.is_(True)).first()
            if eligible_sponsor:
                db.add(AmbassadorCommission(invoice_id=record.id,
                    agent_id=eligible_sponsor.id,kind="sponsor",
                    amount_cents=SPONSOR_EUR_CENTS,period=record.period,
                    status="pending",created_at=now))
                credited+=SPONSOR_EUR_CENTS
    else:
        recompute_recurring(db,Agent,record.period,agent.id)
    return {"invoice_id":record.id,"eligible":True,"kind":kind,
            "activation":activation,"pending_commission_cents":credited}

def apply_verified_wise_receipt(db, business, Agent, reference, period,
                                gross_cents, evidence_note):
    """Admin-reconciled Wise receipt. Caller owns the DB transaction.

    The Wise reference must correspond to one genuine transfer verified by the
    admin. Never call from untrusted customer-facing UI. Immutable activation:
    a business only ever earns one first-payment bonus.
    """
    reference=(reference or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ /:-]{7,109}",reference):
        raise ValueError("Referinta Wise invalida")
    try:
        year, month=map(int,period.split("-"))
        datetime(year,month,1)
    except (ValueError,AttributeError):
        raise ValueError("Luna incasarii invalida")
    if type(gross_cents) is not int or gross_cents<SUBSCRIPTION_PRICE_EUR_CENTS:
        raise ValueError("Suma incasata sub pretul abonamentului")
    if not evidence_note or len(evidence_note.strip())<12:
        raise ValueError("Dovada reconcilierii este obligatorie")
    receipt_id="wise_"+hashlib.sha256(reference.casefold().encode()).hexdigest()
    if db.query(PaidMerchantInvoice).filter(
        PaidMerchantInvoice.external_invoice_id==receipt_id).first():
        raise ValueError("Aceasta referinta Wise a fost deja folosita")
    if db.query(PaidMerchantInvoice).filter(
        PaidMerchantInvoice.business_id==business.id,
        PaidMerchantInvoice.period==period,
        PaidMerchantInvoice.eligible==1).first():
        raise ValueError("Firma are deja o incasare eligibila in aceasta luna")
    agent=(db.query(Agent).filter(Agent.id==business.agent_id,
           Agent.active.is_(True)).first()) if business.agent_id else None
    # A direct merchant (no ambassador) may still be a paying LOIAL business.
    ever_paid=db.query(PaidMerchantInvoice).filter(
        PaidMerchantInvoice.business_id==business.id,
        PaidMerchantInvoice.eligible==1).count()>0
    first=not ever_paid
    now=now_iso()
    row=PaidMerchantInvoice(
        external_invoice_id=receipt_id,business_id=business.id,
        agent_id=agent.id if agent else None,payment_intent_id=None,
        subscription_id="wise_manually_reconciled",
        provider_customer_id="wise_business",
        currency="eur",gross_paid_cents=gross_cents,
        net_revenue_cents=gross_cents,eligible=1,
        review_reason="wise_verified_admin:"+evidence_note.strip()[:120],
        refunded=0,paid_at=now,period=period,created_at=now)
    db.add(row);db.flush()
    awards=[]
    if agent:
        kind="activation" if first else "recurring"
        cents=ACTIVATION_EUR_CENTS if first else tier(1)["rate_cents"]
        db.add(AmbassadorCommission(
            invoice_id=row.id,agent_id=agent.id,kind=kind,
            amount_cents=cents,period=period,status="pending",created_at=now))
        awards.append({"agent_id":agent.id,"kind":kind,"eur":cents/100})
        if first:
            edge=db.query(SponsorRelationship).filter(
                SponsorRelationship.ambassador_id==agent.id).first()
            if edge and edge.sponsor_id!=agent.id:
                recruiter=db.query(Agent).filter(
                    Agent.id==edge.sponsor_id,Agent.active.is_(True)).first()
                if recruiter:
                    db.add(AmbassadorCommission(
                        invoice_id=row.id,agent_id=recruiter.id,
                        kind="sponsor",amount_cents=SPONSOR_EUR_CENTS,
                        period=period,status="pending",created_at=now))
                    awards.append({"agent_id":recruiter.id,
                                   "kind":"sponsor","eur":10})
        # Recalculate pending renewals as the active portfolio changes.
        recompute_recurring(db,Agent,period,agent.id)
    return {"receipt_id":row.id,"first_payment":first,
            "business_id":business.id,"period":period,"awards":awards,
            "verified_by_admin":True,"wise_reference":reference}


def reverse_invoice(db,invoice):
    """Refund/revocation must not silently reverse money already paid out."""
    if not invoice:return {"ignored":"unknown_invoice"}
    if invoice.refunded:return {"duplicate":True}
    invoice.refunded=1
    invoice.review_reason="refunded_or_disputed"
    entries=db.query(AmbassadorCommission).filter(
        AmbassadorCommission.invoice_id==invoice.id).all()
    paid=any(entry.status=="paid" for entry in entries)
    for entry in entries:
        if entry.status=="pending":
            entry.status="reversed"
        elif entry.status=="approved":
            entry.status="held"
    if paid:
        invoice.review_reason="refunded_after_payout_manual_recovery"
    return {"reversed":not paid,"manual_recovery_required":paid}

def summary(db,Agent,period=None):
    query=db.query(AmbassadorCommission)
    if period:query=query.filter(AmbassadorCommission.period==period)
    entries=query.all()
    totals={}
    for e in entries:
        item=totals.setdefault(str(e.agent_id),
            {"agent_id":e.agent_id,"pending_eur":0,"available_eur":0,
             "paid_eur":0,"reversed_eur":0,"activation_eur":0,
             "recurring_eur":0,"sponsor_eur":0})
        euros=e.amount_cents/100
        if e.status=="pending":item["pending_eur"]+=euros
        elif e.status=="approved":item["available_eur"]+=euros
        elif e.status=="paid":item["paid_eur"]+=euros
        elif e.status in ("reversed","held"):item["reversed_eur"]+=euros
        if e.status in ("pending","approved","paid"):
            item[e.kind+"_eur"]+=euros
    agents={a.id:a.name for a in db.query(Agent).filter(
        Agent.id.in_([int(x) for x in totals])).all()} if totals else {}
    for row in totals.values():
        row["name"]=agents.get(row["agent_id"],"Ambasador")
    return {"month":period,"ambassadors":list(totals.values()),
            "verified_gross_eur":round(sum(
                x.gross_paid_cents for x in db.query(PaidMerchantInvoice).filter(
                    PaidMerchantInvoice.currency=="eur",
                    PaidMerchantInvoice.eligible==1,
                    PaidMerchantInvoice.refunded==0,
                    *([PaidMerchantInvoice.period==period] if period else [])).all())/100,2),
            "note":"Fara retineri, comisioane de procesare, TVA sau plati simulate; payout doar dupa verificare."}

def verified_ambassador_overview(db,Agent,period):
    """Backward-compatible admin display fields, but exclusively verified receipts."""
    agents=db.query(Agent).order_by(Agent.id).all()
    entries=db.query(AmbassadorCommission).filter(
        AmbassadorCommission.period==period).all()
    invoices=db.query(PaidMerchantInvoice).filter(
        PaidMerchantInvoice.period==period,
        PaidMerchantInvoice.eligible==1,
        PaidMerchantInvoice.refunded==0).all()
    result=[]
    for agent in agents:
        owned=[i for i in invoices if i.agent_id==agent.id]
        by_id={x.id:x for x in owned}
        acts=[e for e in entries if e.agent_id==agent.id and
              e.kind=="activation" and e.status in ("pending","approved","paid")]
        renewals=[e for e in entries if e.agent_id==agent.id and
                  e.kind=="recurring" and e.status in ("pending","approved","paid")]
        sponsored=[e for e in entries if e.agent_id==agent.id and
                   e.kind=="sponsor" and e.status in ("pending","approved","paid")]
        unique=len({inv.business_id for inv in owned})
        current=tier(unique)
        earned=sum(e.amount_cents for e in acts+renewals+sponsored)
        result.append({"agent_id":agent.id,"agent_name":agent.name,
            "email":agent.email,"rank":current["rank"],
            "total_active_businesses":unique,
            "new_this_month":len(acts),
            "activation_commission":sum(e.amount_cents for e in acts)/100,
            "recurring_businesses":len(renewals),
            "recurring_rate":current["rate_cents"]/100,
            "recurring_commission":sum(e.amount_cents for e in renewals)/100,
            "sponsor_commission":sum(e.amount_cents for e in sponsored)/100,

            "total":earned/100,
            "payout_method":agent.payout_method or "wise",
            "payout_details":"Disponibil in evidenta interna",
            "verified_receipts_only":True,
            "recruited_ambassadors":db.query(SponsorRelationship).filter(
                SponsorRelationship.sponsor_id==agent.id).count()})
    return result


def install_revenue(app,engine,factory,Agent,Business,User,secret,algorithm,password_hasher=None):
    RevenueBase.metadata.create_all(bind=engine)
    router=APIRouter(prefix="/api/loial-revenue",tags=["Verified Loial Revenue"])
    def session():
        db=factory()
        try:yield db
        finally:db.close()
    def claims(request):
        h=request.headers.get("Authorization","")
        if not h.startswith("Bearer "):
            raise HTTPException(status_code=401,detail="Autentificare necesara")
        try:payload=jwt.decode(h[7:],secret,algorithms=[algorithm])
        except JWTError:raise HTTPException(status_code=401,detail="Sesiune invalida")
        return payload
    def admin(request:Request,db:Session=Depends(session)):
        payload=claims(request)
        if payload.get("role")!="admin":
            raise HTTPException(status_code=403,detail="Admin Loial obligatoriu")
        u=db.query(User).filter(User.email==payload.get("sub"),
            User.role=="admin").first()
        if not u:raise HTTPException(status_code=403,detail="Admin negasit")
        return u
    def ambassador(request:Request,db:Session=Depends(session)):
        payload=claims(request)
        if payload.get("role")!="ambassador":
            raise HTTPException(status_code=403,detail="Cont ambasador necesar")
        a=db.query(Agent).filter(Agent.email==payload.get("sub"),
            Agent.active.is_(True)).first()
        if not a:raise HTTPException(status_code=403,detail="Ambasador invalid")
        return a

    @router.put("/ambassador/wise-details")
    def update_wise_details(req:AmbassadorWiseDetails,
                            agent=Depends(ambassador),db:Session=Depends(session)):
        """Only the authenticated ambassador may update their own payout details.

        Password re-verification protects against stale session-token theft.
        The API never returns the bank / Wise account value.
        """
        if not password_hasher or not agent.password or not password_hasher.verify(
                req.password,agent.password):
            raise HTTPException(status_code=403,detail="Parola nu a fost confirmata")
        details=req.account_details.strip()
        if len(details)<6 or any(ord(ch)<32 for ch in details):
            raise HTTPException(status_code=422,detail="Detalii Wise invalide")
        agent.payout_method="wise"
        agent.payout_details=details
        db.commit()
        return {"status":"updated","provider":"wise","details_saved":True}

    @router.get("/ambassador/me")
    def my_revenue(agent=Depends(ambassador),db:Session=Depends(session)):
        rows=db.query(AmbassadorCommission).filter(
            AmbassadorCommission.agent_id==agent.id).order_by(
            AmbassadorCommission.id.desc()).limit(150).all()
        recruits=db.query(SponsorRelationship).filter(
            SponsorRelationship.sponsor_id==agent.id).count()
        invoices=db.query(PaidMerchantInvoice).filter(
            PaidMerchantInvoice.eligible==1,
            PaidMerchantInvoice.refunded==0).order_by(
            PaidMerchantInvoice.id.desc()).limit(500).all()
        personal=[x for x in invoices if x.agent_id==agent.id]
        receipt_index={x.id:x for x in invoices}
        team_links=db.query(SponsorRelationship).filter(
            SponsorRelationship.sponsor_id==agent.id).all()
        recruited_ids={x.ambassador_id for x in team_links}
        recruits_people=db.query(Agent).filter(Agent.id.in_(recruited_ids)).all() if recruited_ids else []
        owned_firms=db.query(Business).filter(Business.agent_id==agent.id).all()
        team_firms=db.query(Business).filter(Business.agent_id.in_(
            recruited_ids)).all() if recruited_ids else []
        first_paid_by_business={}
        for receipt in invoices:
            if receipt.business_id not in first_paid_by_business:
                first_paid_by_business[receipt.business_id]=receipt
            elif receipt.created_at<first_paid_by_business[receipt.business_id].created_at:
                first_paid_by_business[receipt.business_id]=receipt
        firm_activity=[]
        for firm in owned_firms+team_firms:
            paid=first_paid_by_business.get(firm.id)
            direct=(firm.agent_id==agent.id)
            firm_activity.append({
                "business_name":firm.name,
                "business_id":firm.id,
                "source":"direct" if direct else "direct_recruit",
                "registered_at":firm.created_at or "",
                "first_payment_confirmed_at":paid.created_at if paid else None,
                "paid_month":paid.period if paid else None,
                "commission_on_first_payment_eur":20 if direct else 10,
                "payment_verified":bool(paid)})
        firm_activity.sort(key=lambda x:x["registered_at"],reverse=True)

        return {"agent_id":agent.id,"sponsored_ambassadors":recruits,
                "pending_eur":sum(x.amount_cents for x in rows if x.status=="pending")/100,
                "approved_eur":sum(x.amount_cents for x in rows if x.status=="approved")/100,
                "paid_eur":sum(x.amount_cents for x in rows if x.status=="paid")/100,
                "direct_paid_businesses":len({x.business_id for x in personal}),
                "wise_details_saved":bool(agent.payout_details),
                "firm_activity":firm_activity[:100],
                "month":datetime.now(timezone.utc).strftime("%Y-%m"),
                "recruits":[{"name":x.name,"joined_at":next(
                    (r.referred_at for r in team_links if r.ambassador_id==x.id),"")}
                    for x in recruits_people],
                "entries":[{"kind":x.kind,"eur":x.amount_cents/100,
                            "status":x.status,"month":x.period,
                            "created_at":x.created_at,
                            "business_id":receipt_index[x.invoice_id].business_id
                                if x.invoice_id in receipt_index else None,
                            "source":"my_business" if x.kind!="sponsor" else "direct_recruit",
                            "description":"Firmă adusă de un ambasador recrutat direct"
                                if x.kind=="sponsor" else
                                ("Primul abonament achitat" if x.kind=="activation"
                                 else "Reînnoire abonament achitat")}
                            for x in rows],
                "money_withdrawal_auto_enabled":False}

    @router.get("/simulate")
    def calculator(own_new:int=0,own_active:int=0,friend_ambassadors:int=0,
                   new_firms_per_friend:int=0):
        try:return simulate(own_new,own_active,
                            friend_ambassadors,new_firms_per_friend)
        except ValueError as e:raise HTTPException(status_code=422,detail=str(e))

    @router.post("/admin/wise/confirm")
    def confirm_wise_payment(req:WiseReceiptInput,
                             actor=Depends(admin),db:Session=Depends(session)):
        raise HTTPException(status_code=410,detail="Abonamentele se incaseaza exclusiv prin Stripe.")
        if not req.confirmed_in_wise:
            raise HTTPException(status_code=422,
                detail="Verifica incasarea reala din extrasul Wise Business")
        business=db.query(Business).filter(Business.id==req.business_id).first()
        if not business:
            raise HTTPException(status_code=404,detail="Firma inexistenta")
        try:
            result=apply_verified_wise_receipt(
                db,business,Agent,req.wise_reference,req.payment_month,
                req.paid_amount_eur_cents,req.evidence_note)
            business.plan="probusiness"
            business.max_customers=999999
            db.commit()
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=409,detail=str(exc))
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409,
                detail="Incasare Wise deja reconciliata")
        return {"status":"reconciled","verified_by":actor.email,**result}

    @router.get("/admin/wise/receipts")
    def wise_receipts(period:Optional[str]=None,actor=Depends(admin),
                      db:Session=Depends(session)):
        if period and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])",period):
            raise HTTPException(status_code=422,detail="Luna invalida")
        q=db.query(PaidMerchantInvoice).filter(
            PaidMerchantInvoice.provider_customer_id=="wise_business")
        if period:q=q.filter(PaidMerchantInvoice.period==period)
        rows=q.order_by(PaidMerchantInvoice.id.desc()).limit(500).all()
        return {"items":[{"business_id":r.business_id,
            "invoice_id":r.id,"month":r.period,
            "paid_eur":r.gross_paid_cents/100,
            "status":"refunded" if r.refunded else "confirmed",
            "verified_at":r.created_at} for r in rows]}

    @router.post("/admin/bind")
    def bind(req:MerchantLinkInput,actor=Depends(admin),db:Session=Depends(session)):
        customer=req.stripe_customer_id.strip()
        if not re.fullmatch(r"cus_[A-Za-z0-9]{5,125}",customer):
            raise HTTPException(status_code=422,detail="Stripe customer ID invalid")
        business=db.query(Business).filter(Business.id==req.business_id).first()
        if not business:raise HTTPException(status_code=404,detail="Firma inexistenta")
        existing=db.query(MerchantBilling).filter(
            (MerchantBilling.business_id==business.id) |
            (MerchantBilling.provider_customer_id==customer)).first()
        if existing:
            if existing.business_id==business.id and existing.provider_customer_id==customer:
                return {"status":"already_linked"}
            raise HTTPException(status_code=409,
                detail="Legatura Stripe existenta: schimbarea necesita reconciliere manuala")
        db.add(MerchantBilling(business_id=business.id,
            provider_customer_id=customer,linked_at=now_iso()))
        db.commit()
        return {"status":"linked","business_id":business.id,
                "verified_by_admin":actor.email,
                "notice":"Compara contul Stripe cu firma inainte de a primi plati."}

    @router.post("/stripe/webhook")
    async def webhook(request:Request,db:Session=Depends(session)):
        raise HTTPException(status_code=410,detail="Stripe retras: incasari numai Wise Business.")
        secret_key=os.getenv("LOIAL_STRIPE_WEBHOOK_SECRET","")
        if not secret_key:
            raise HTTPException(status_code=503,detail="Stripe webhook not configured")
        raw=await request.body()
        if len(raw)>1024*1024:
            raise HTTPException(status_code=413,detail="Payload prea mare")
        if not _signature_ok(raw,request.headers.get("Stripe-Signature",""),secret_key):
            raise HTTPException(status_code=400,detail="Stripe signature invalid")
        try:event=json.loads(raw)
        except (ValueError,TypeError):
            raise HTTPException(status_code=400,detail="Invalid JSON")
        if not isinstance(event,dict) or not isinstance(event.get("id"),str):
            raise HTTPException(status_code=400,detail="Event ID required")
        if event.get("livemode") is not True:
            return {"status":"test_event_not_credited"}
        eid=event["id"]
        if db.query(BillingEvent).filter(BillingEvent.event_id==eid).first():
            return {"status":"duplicate_ignored"}
        obj=(event.get("data") or {}).get("object") or {}
        if not isinstance(obj,dict):raise HTTPException(status_code=400,detail="Invalid data")
        event_type=str(event.get("type",""))[:70]
        outcome={"ignored":"unsupported_event"}
        if event_type=="invoice.paid":
            outcome=apply_verified_invoice(db,obj,Agent,Business)
        elif event_type in ("charge.refunded","charge.dispute.created",
                            "charge.dispute.closed","invoice.voided","credit_note.created"):
            reference=obj.get("invoice")
            payment=obj.get("payment_intent")
            if event_type.startswith("charge.dispute"):
                charge=obj.get("charge")
                if isinstance(charge,dict):
                    payment=charge.get("payment_intent")
            if payment:
                row=db.query(PaidMerchantInvoice).filter(
                    PaidMerchantInvoice.payment_intent_id==_payment_id(payment)).first()
            else:
                row=db.query(PaidMerchantInvoice).filter(
                    PaidMerchantInvoice.external_invoice_id==_payment_id(reference)).first()
            if row:
                is_full=(obj.get("refunded") is True or
                         obj.get("amount_refunded")==obj.get("amount") and
                         isinstance(obj.get("amount"),int) and obj.get("amount")>0)
                if event_type.startswith("charge.dispute") or event_type in (
                    "invoice.voided","credit_note.created"):
                    # Disputes and credit notes can be partial; hold for manual review.
                    paid_any=False
                    for c in db.query(AmbassadorCommission).filter(
                        AmbassadorCommission.invoice_id==row.id).all():
                        if c.status in ("pending","approved"):c.status="held"
                        if c.status=="paid":paid_any=True
                    row.review_reason="billing_dispute_or_credit_note_review"
                    outcome={"manual_review":True,"paid_commissions_require_recovery":paid_any}
                elif is_full:
                    outcome=reverse_invoice(db,row)
                else:
                    for c in db.query(AmbassadorCommission).filter(
                        AmbassadorCommission.invoice_id==row.id,
                        AmbassadorCommission.status=="pending").all():
                        c.status="held"
                    row.review_reason="partial_refund_review"
                    outcome={"manual_review":True}
            else:outcome={"ignored":"no_invoice_match"}
        db.add(BillingEvent(event_id=eid,event_type=event_type,created_at=now_iso()))
        try:db.commit()
        except IntegrityError:
            db.rollback()
            return {"status":"duplicate_ignored"}
        return {"status":"recorded","event_type":event_type,**outcome}

    @router.get("/admin/summary")
    def admin_summary(period:Optional[str]=None,actor=Depends(admin),
                      db:Session=Depends(session)):
        if period and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])",period):
            raise HTTPException(status_code=422,detail="Luna trebuie sa fie YYYY-MM")
        return summary(db,Agent,period)

    @router.get("/admin/export/{period}.xlsx")
    def export_commissions_xlsx(period:str,actor=Depends(admin),
                                db:Session=Depends(session)):
        """Excel export is read-only; approval and Wise payout stay separate."""
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])",period):
            raise HTTPException(status_code=422,detail="Luna invalida")
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from io import BytesIO
        from fastapi import Response
        book=Workbook()
        overview=book.active
        overview.title="De platit"
        overview.append(["ID ambasador","Ambasador","Comisioane in asteptare EUR",
                         "Aprobate EUR","Platite EUR","Reversate EUR",
                         "Activari EUR","Recurente EUR","Recrutare directa EUR",
                         "Furnizor plata comisioane","Destinatie Wise (date personale)"])
        monthly=summary(db,Agent,period)["ambassadors"]
        agents_by_id={a.id:a for a in db.query(Agent).all()}
        for row in monthly:
            agent=agents_by_id.get(row["agent_id"])
            overview.append([row["agent_id"],excel_literal(row["name"]),row["pending_eur"],
                             row["available_eur"],row["paid_eur"],
                             row["reversed_eur"],row["activation_eur"],
                             row["recurring_eur"],row["sponsor_eur"],
                             "Wise Business",excel_literal(agent.payout_details or "")
                             if agent else ""])
        detail=book.create_sheet("Registru comisioane")
        detail.append(["ID","ID ambasador","ID factura","Tip","Suma EUR",
                       "Luna","Status","Data","Referinta plata Wise"])
        entries=db.query(AmbassadorCommission).filter(
            AmbassadorCommission.period==period).order_by(
            AmbassadorCommission.id).all()
        for row in entries:
            detail.append([row.id,row.agent_id,row.invoice_id,row.kind,
                           row.amount_cents/100,row.period,row.status,
                           row.created_at,excel_literal(row.payout_reference or "")])
        receipts=book.create_sheet("Incasari verificate")
        receipts.append(["ID factura","ID firma","Ambasador direct","Luna",
                         "Incasare EUR","Procesator","Status"])
        invoices=db.query(PaidMerchantInvoice).filter(
            PaidMerchantInvoice.period==period,
            PaidMerchantInvoice.eligible==1).all()
        for row in invoices:
            receipts.append([row.id,row.business_id,row.agent_id,row.period,
                             row.gross_paid_cents/100,
                             "Wise" if row.provider_customer_id=="wise_business" else "Stripe",
                             "Rambursat" if row.refunded else "Verificat"])
        for sheet in book.worksheets:
            sheet.freeze_panes="A2"
            sheet.auto_filter.ref=sheet.dimensions
            for cell in sheet[1]:
                cell.font=Font(bold=True,color="FFFFFF")
                cell.fill=PatternFill("solid",fgColor="1B3A31")
            for column in sheet.columns:
                letter=column[0].column_letter
                width=min(45,max(14,max(len(str(c.value or "")) for c in column)+2))
                sheet.column_dimensions[letter].width=width
        buf=BytesIO();book.save(buf)
        return Response(buf.getvalue(),media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            headers={"Content-Disposition":
                     f'attachment; filename="loial-comisioane-{period}.xlsx"',
                     "Cache-Control":"no-store"})

    @router.post("/admin/approve/{period}")
    def approve_period(period:str,actor=Depends(admin),
                       db:Session=Depends(session)):
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])",period):
            raise HTTPException(status_code=422,detail="Perioada invalida")
        try:
            year,month=map(int,period.split("-"))
            first_next=datetime(year+1,1,1,tzinfo=timezone.utc) if month==12 else datetime(
                year,month+1,1,tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=422,detail="Perioada invalida")
        if datetime.now(timezone.utc)<first_next+timedelta(days=REWARD_RELEASE_DAYS):
            raise HTTPException(status_code=409,
                detail="Perioada de verificare a platilor si retururilor nu a expirat")
        pending=payable_commissions(db,period,"pending").all()
        for entry in pending:entry.status="approved"
        db.commit()
        return {"approved":len(pending),"period":period,
                "money_sent":False,"requires_financial_documents":True}

    @router.post("/admin/settle")
    def record_settlement(req:SettlementInput,actor=Depends(admin),
                          db:Session=Depends(session)):
        if not req.document_confirmed:
            raise HTTPException(status_code=422,
                detail="Confirmarea transferului bancar este obligatorie")
        ref=req.bank_reference.strip()
        if db.query(AmbassadorSettlement).filter(
            AmbassadorSettlement.paid_reference==ref).first():
            raise HTTPException(status_code=409,detail="Transfer deja inregistrat")
        entries=payable_commissions(db,req.period,"approved",req.agent_id).all()
        if not entries:raise HTTPException(status_code=404,detail="Nu exista comisioane aprobate")
        cents=sum(x.amount_cents for x in entries)
        db.add(AmbassadorSettlement(agent_id=req.agent_id,period=req.period,
            amount_cents=cents,paid_reference=ref,
            paid_at=now_iso(),approved_by=actor.email))
        for x in entries:
            x.status="paid";x.paid_at=now_iso();x.payout_reference=ref
        db.commit()
        return {"status":"recorded_external_transfer","amount_eur":cents/100,
                "bank_reference":ref,
                "note":"Doar transfer deja confirmat; aceasta ruta nu trimite bani."}

    app.include_router(router)
