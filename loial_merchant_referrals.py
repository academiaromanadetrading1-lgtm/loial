"""Merchant referrals, distinct from friend points and paid commissions."""
import os
import secrets
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from sqlalchemy import update
from loial_manual_admin import AmbassadorInvite
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base
from sqlalchemy.exc import IntegrityError
from loial_inbox import WalletInboxAccess, access_hash

RecruitmentBase = declarative_base()

class MerchantReferralCode(RecruitmentBase):
    __tablename__ = "loial_merchant_referral_codes"
    wallet_uuid = Column(String(120), primary_key=True)
    code = Column(String(60), unique=True, nullable=False)
    created_at = Column(String(40), nullable=False)

class MerchantAttribution(RecruitmentBase):
    __tablename__ = "loial_merchant_attributions"
    business_id = Column(Integer, primary_key=True)
    wallet_uuid = Column(String(120), nullable=False, index=True)
    created_at = Column(String(40), nullable=False)
    agent_id = Column(Integer, nullable=True)

def utc():
    return datetime.now(timezone.utc).isoformat()

def resolve_code(db, code):
    if not code or not code.startswith("LM-") or len(code)>60:
        return None
    row = db.query(MerchantReferralCode).filter_by(code=code).first()
    if not row or not db.query(WalletInboxAccess).filter_by(wallet_uuid=row.wallet_uuid).first():
        return None
    return row

def attribute_merchant(db, business_id, wallet_uuid):
    # Caller owns merchant registration transaction.
    row = MerchantAttribution(business_id=business_id,wallet_uuid=wallet_uuid,created_at=utc())
    db.add(row)
    db.flush()
    return row

class WalletAmbassadorLink(RecruitmentBase):
    __tablename__ = "loial_wallet_ambassador_links"
    wallet_uuid = Column(String(120), primary_key=True)
    agent_id = Column(Integer, unique=True, nullable=False)
    linked_at = Column(String(40), nullable=False)

class ActivateAmbassador(BaseModel):
    name: str = Field(min_length=2,max_length=100)
    email: str = Field(min_length=3,max_length=100,pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=10,max_length=72)
    accept_terms: bool = False

class LinkAmbassador(BaseModel):
    email: str = Field(min_length=3,max_length=100)
    password: str = Field(min_length=1,max_length=200)
    accept_terms: bool = False

def linked_agent(db, wallet_uuid, Agent):
    link=db.get(WalletAmbassadorLink,wallet_uuid)
    if not link:
        return None
    return db.query(Agent).filter_by(id=link.agent_id,active=True,role="ambassador").first()

def install_merchant_referrals(app, engine, factory, Agent, Business, pwd_context):
    RecruitmentBase.metadata.create_all(bind=engine)
    api=APIRouter(prefix="/api/loial-merchant-referrals", tags=["Merchant recruitment"])
    def session():
        db=factory()
        try:
            yield db
        finally:
            db.close()
    def authenticated_wallet(request,db):
        token=request.headers.get("X-Loial-Wallet-Token","").strip()
        if not 40<=len(token)<=180:
            raise HTTPException(401,"Portofel privat necesar")
        wallet=db.query(WalletInboxAccess).filter_by(token_hash=access_hash(token)).first()
        if not wallet:
            raise HTTPException(401,"Portofel neautorizat")
        return wallet
    @api.get("/me")
    def me(request: Request, db=Depends(session)):
        wallet=authenticated_wallet(request,db)
        row=db.get(MerchantReferralCode,wallet.wallet_uuid)
        if not row:
            row=MerchantReferralCode(wallet_uuid=wallet.wallet_uuid,code="LM-"+secrets.token_hex(16),created_at=utc())
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                row=db.get(MerchantReferralCode,wallet.wallet_uuid)
                if not row:
                    raise HTTPException(409,"Reincearca generarea codului")
        recruited=db.query(MerchantAttribution).filter_by(wallet_uuid=wallet.wallet_uuid).count()
        origin=os.getenv("LOIAL_PUBLIC_ORIGIN","https://loial.space").rstrip("/")
        agent=linked_agent(db,wallet.wallet_uuid,Agent)
        return {"code":row.code,"share_url":origin+"/register.html?ref="+row.code,
                "registered_merchants":recruited,"status":"ambassador" if agent else ("eligible_for_activation" if recruited else "customer"),
                "commission_on_signup":False}
    @api.post("/link")
    def link(req: LinkAmbassador, request: Request, db=Depends(session)):
        wallet=authenticated_wallet(request,db)
        if not req.accept_terms:
            raise HTTPException(422,"Accepta regulile programului de ambasador")
        if not db.query(MerchantAttribution).filter_by(wallet_uuid=wallet.wallet_uuid).first():
            raise HTTPException(409,"Recruteaza mai intai o firma")
        agent=db.query(Agent).filter_by(email=req.email.strip().lower(),active=True,role="ambassador").first()
        if not agent or not pwd_context.verify(req.password,agent.password):
            raise HTTPException(401,"Datele contului de ambasador sunt incorecte")
        return associate(db,wallet,agent)
    @api.post("/activate")
    def activate(req: ActivateAmbassador, request: Request, db=Depends(session)):
        wallet=authenticated_wallet(request,db)
        if not req.accept_terms:
            raise HTTPException(422,"Accepta regulile programului de ambasador")
        if not db.query(MerchantAttribution).filter_by(wallet_uuid=wallet.wallet_uuid).first():
            raise HTTPException(409,"Recruteaza mai intai o firma")
        if db.get(WalletAmbassadorLink,wallet.wallet_uuid):
            raise HTTPException(409,"Portofelul este deja asociat unui ambasador")
        email=req.email.strip().lower()
        if not req.name.strip() or len(req.password.encode("utf-8"))>72:
            raise HTTPException(422,"Verifica numele si parola")
        invite=db.get(AmbassadorInvite,email)
        if invite and not invite.used_at:
            raise HTTPException(409,"Exista deja o invitatie individuala pentru acest cont")
        if db.query(Agent).filter_by(email=email).first():
            raise HTTPException(409,"Cont existent. Foloseste asocierea prin parola.")
        agent=Agent(name=req.name.strip(),email=email,password=pwd_context.hash(req.password),
            phone="",role="ambassador",rank="Ambasador",qr_code="LOIAL-"+secrets.token_hex(8).upper(),
            status="active",active=True,payout_method="wise",payout_details=None,created_at=utc())
        db.add(agent)
        try:db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409,"Contul exista deja. Foloseste asocierea.")
        return associate(db,wallet,agent)
    def associate(db,wallet,agent):
        existing=db.get(WalletAmbassadorLink,wallet.wallet_uuid)
        if existing and existing.agent_id!=agent.id:
            raise HTTPException(409,"Portofel deja asociat")
        if db.query(WalletAmbassadorLink).filter(WalletAmbassadorLink.agent_id==agent.id,WalletAmbassadorLink.wallet_uuid!=wallet.wallet_uuid).first():
            raise HTTPException(409,"Cont deja asociat altui portofel")
        if not existing:
            db.add(WalletAmbassadorLink(wallet_uuid=wallet.wallet_uuid,agent_id=agent.id,linked_at=utc()))
            try:db.flush()
            except IntegrityError:
                db.rollback()
                raise HTTPException(409,"Asociere concurenta. Reincearca.")
        assigned=0
        for row in db.query(MerchantAttribution).filter_by(wallet_uuid=wallet.wallet_uuid,agent_id=None).all():
            biz=db.get(Business,row.business_id)
            if not biz or biz.agent_id is not None or (biz.email or "").lower()==agent.email.lower():
                continue
            # Do not change attribution on any merchant with a verified payment.
            from loial_revenue_commissions import PaidMerchantInvoice
            if db.query(PaidMerchantInvoice).filter_by(business_id=biz.id,eligible=1).first():
                continue
            changed=db.execute(update(Business).where(Business.id==biz.id,Business.agent_id.is_(None)).values(agent_id=agent.id))
            if changed.rowcount==1:
                row.agent_id=agent.id
                assigned+=1
        db.commit()
        return {"status":"ambassador","assigned_merchants":assigned,"commission_on_signup":False}
    app.include_router(api)
