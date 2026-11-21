"""Merchant-approved, consent-gated wallet win-back campaigns and visit attribution.

Campaigns never send to WhatsApp/SMS. Explicit merchant approval is required.
Attribution counts verified scan visits, not incremental sales or receipt revenue.
"""
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from sqlalchemy import Column, Integer, String, UniqueConstraint, update
from sqlalchemy.orm import declarative_base
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from loial_winback import summarize_inactive, parse_visit_date, WinbackSettings

CampaignBase = declarative_base()

class WinbackCampaign(CampaignBase):
    __tablename__ = "loial_winback_campaigns"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, nullable=False, index=True)
    title = Column(String(120), nullable=False)
    message = Column(String(1000), nullable=False)
    status = Column(String(20), nullable=False, default="draft")
    created_at = Column(String(40), nullable=False)
    approved_at = Column(String(40))
    sent_count = Column(Integer, nullable=False, default=0)

class WinbackRecipient(CampaignBase):
    __tablename__ = "loial_winback_recipients"
    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, nullable=False, index=True)
    business_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, nullable=False)
    delivered_at = Column(String(40))
    __table_args__ = (UniqueConstraint("campaign_id", "customer_id",
                                       name="uq_winback_campaign_recipient"),)

class WinbackAttribution(CampaignBase):
    __tablename__ = "loial_winback_attributions"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, nullable=False, index=True)
    campaign_id = Column(Integer, nullable=False)
    customer_id = Column(Integer, nullable=False)
    operation_key = Column(String(120), nullable=False)
    confirmed_at = Column(String(40), nullable=False)
    __table_args__ = (UniqueConstraint("business_id", "operation_key",
                                       name="uq_winback_confirmed_operation"),)

class DraftInput(BaseModel):
    title: str = Field(default="Te așteptăm din nou", min_length=3, max_length=120)
    message: str = Field(default="Ne-ar face plăcere să revii! Verifică oferta în portofelul LOIAL.", min_length=10, max_length=1000)

def at_risk_ids(award_rows, customer_ids, threshold, as_of):
    """Reuse same observed-visit rule as Win-Back insights."""
    from collections import defaultdict
    from statistics import mean
    histories = defaultdict(set)
    customer_ids = set(customer_ids)
    for row in award_rows:
        if row.customer_id in customer_ids:
            day = parse_visit_date(row.created_at)
            if day is not None and day <= as_of:
                histories[row.customer_id].add(day)
    selected = set()
    for customer_id, dates in histories.items():
        ordered = sorted(dates)
        if len(ordered) >= 3:
            gaps = [(y-x).days for x,y in zip(ordered,ordered[1:])]
            cycle = max(3,min(365,round(mean(gaps)*1.3)))
        else:
            cycle = threshold
        if (as_of-ordered[-1]).days > cycle:
            selected.add(customer_id)
    return selected

def attribute_confirmed_visit(db, business_id, customer_id, operation_key, at=None):
    """Called in the same transaction as a confirmed stamp; never writes revenue."""
    at = at or datetime.now(timezone.utc)
    if not operation_key or len(operation_key) > 120:
        return False
    recent = (at-timedelta(days=14)).isoformat()
    match = (db.query(WinbackRecipient, WinbackCampaign)
             .join(WinbackCampaign, WinbackCampaign.id==WinbackRecipient.campaign_id)
             .filter(WinbackRecipient.business_id==business_id,
                     WinbackRecipient.customer_id==customer_id,
                     WinbackRecipient.delivered_at.isnot(None),
                     WinbackRecipient.delivered_at>=recent,
                     WinbackRecipient.delivered_at<=at.isoformat(),
                     WinbackCampaign.business_id==business_id,
                     WinbackCampaign.status=="sent")
             .order_by(WinbackRecipient.delivered_at.desc()).first())
    if not match:
        return False
    if db.query(WinbackAttribution).filter(
            WinbackAttribution.business_id==business_id,
            WinbackAttribution.operation_key==operation_key).first():
        return False
    recipient, campaign = match
    db.add(WinbackAttribution(business_id=business_id,campaign_id=campaign.id,
            customer_id=customer_id,operation_key=operation_key,
            confirmed_at=at.isoformat()))
    return True

def install_winback_campaigns(app, engine, get_db, BusinessAccount, Customer,
                              StampAward, Consent, merchant_auth, security):
    CampaignBase.metadata.create_all(bind=engine)
    router=APIRouter(prefix="/api/loial-winback/campaigns",tags=["winback campaigns"])

    def owner(credentials=Depends(security), db=Depends(get_db)):
        return merchant_auth(credentials,db)

    def eligible(db, business_id):
        from loial_inbox import latest_offer_choice
        customers=db.query(Customer).filter(Customer.business_id==business_id).all()
        settings=db.get(WinbackSettings,business_id)
        threshold=settings.default_return_days if settings else 30
        ids=at_risk_ids(db.query(StampAward).filter(
            StampAward.business_id==business_id).all(),
            [c.id for c in customers],threshold,datetime.now(timezone.utc).date())
        return [c for c in customers if c.id in ids and
                latest_offer_choice(db,Consent,c.id)]

    @router.post("/draft")
    def draft(req:DraftInput,biz=Depends(owner),db=Depends(get_db)):
        candidates=eligible(db,biz.id)
        campaign=WinbackCampaign(business_id=biz.id,title=req.title.strip(),
           message=req.message.strip(),status="draft",
           created_at=datetime.now(timezone.utc).isoformat())
        db.add(campaign)
        db.flush()
        for customer in candidates:
            db.add(WinbackRecipient(campaign_id=campaign.id,
                business_id=biz.id,customer_id=customer.id))
        db.commit()
        return {"campaign_id":campaign.id,"status":"draft",
                "eligible_with_marketing_consent":len(candidates),
                "channel":"loial_wallet","sent":0,
                "needs_explicit_approval":True}

    @router.get("")
    def list_campaigns(biz=Depends(owner),db=Depends(get_db)):
        rows=db.query(WinbackCampaign).filter(WinbackCampaign.business_id==biz.id
            ).order_by(WinbackCampaign.id.desc()).limit(30).all()
        return [{"id":c.id,"title":c.title,"message":c.message,"status":c.status,
                 "sent_count":c.sent_count,"approved_at":c.approved_at} for c in rows]

    @router.post("/{campaign_id}/approve")
    def approve(campaign_id:int,biz=Depends(owner),db=Depends(get_db)):
        from loial_inbox import InboxEntry, InboxDelivery, latest_offer_choice
        from loial_stripe_billing import effective_entitlements
        access=effective_entitlements(db,biz.id)
        if not access["active"]:
            raise HTTPException(status_code=403,detail="Abonament Business inactiv")
        campaign=db.query(WinbackCampaign).filter(
            WinbackCampaign.id==campaign_id,WinbackCampaign.business_id==biz.id).first()
        if campaign is None:
            raise HTTPException(status_code=404,detail="Campanie negăsită")
        if campaign.status!="draft":
            raise HTTPException(status_code=409,detail="Campania a fost deja aprobată")
        # Atomic status transition prevents simultaneous approval requests
        # from generating two wallet deliveries for one campaign.
        claimed=db.execute(update(WinbackCampaign).where(
            WinbackCampaign.id==campaign_id,
            WinbackCampaign.business_id==biz.id,
            WinbackCampaign.status=="draft").values(status="dispatching")).rowcount
        if claimed!=1:
            db.rollback()
            raise HTTPException(status_code=409,detail="Campania este deja în curs de aprobare")
        # Recheck current consent and that each recipient still belongs to this firm.
        candidates=db.query(WinbackRecipient).filter(
            WinbackRecipient.campaign_id==campaign.id,
            WinbackRecipient.business_id==biz.id).all()
        # The customer may have returned since the draft was prepared.
        # Recheck current inactivity and consent at the moment of approval.
        current_eligible={customer.id for customer in eligible(db,biz.id)}
        allowed=[]
        for recipient in candidates:
            customer=db.query(Customer).filter(
                Customer.id==recipient.customer_id,Customer.business_id==biz.id).first()
            if customer and customer.id in current_eligible and latest_offer_choice(db,Consent,customer.id):
                allowed.append(recipient)
        stamp=datetime.now(timezone.utc).isoformat()
        event="winback:"+str(campaign.id)
        entry=InboxEntry(business_id=biz.id,title=campaign.title,
            body=campaign.message,category="marketing",
            source_event=event,created_at=stamp)
        db.add(entry)
        db.flush()
        for recipient in allowed:
            db.add(InboxDelivery(entry_id=entry.id,business_id=biz.id,
                customer_id=recipient.customer_id,created_at=stamp))
            recipient.delivered_at=stamp
        campaign.status="sent"
        campaign.approved_at=stamp
        campaign.sent_count=len(allowed)
        db.commit()
        return {"campaign_id":campaign.id,"status":"sent",
                "delivered_to_wallet_inbox":len(allowed),
                "external_messages":0,"channel":"loial_wallet"}

    @router.get("/attributions")
    def attribution_summary(biz=Depends(owner),db=Depends(get_db)):
        entries=db.query(WinbackAttribution).filter(
            WinbackAttribution.business_id==biz.id).all()
        return {"business_id":biz.id,"confirmed_post_campaign_visits":len(entries),
                "confirmed_post_campaign_customers":len({e.customer_id for e in entries}),
                "revenue_confirmed_minor":None,
                "incremental_revenue_proven":False,
                "note":"Vizite după mesaj în fereastra de 14 zile; nu sunt dovada unor venituri suplimentare."}

    app.include_router(router)
