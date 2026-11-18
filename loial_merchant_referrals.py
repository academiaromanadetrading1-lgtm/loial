"""Merchant referrals, distinct from friend points and paid commissions."""
import os
import secrets
from datetime import datetime, timezone
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

def install_merchant_referrals(app, engine, factory):
    RecruitmentBase.metadata.create_all(bind=engine)
    api=APIRouter(prefix="/api/loial-merchant-referrals", tags=["Merchant recruitment"])
    def session():
        db=factory()
        try:
            yield db
        finally:
            db.close()
    @api.get("/me")
    def me(request: Request, db=Depends(session)):
        token=request.headers.get("X-Loial-Wallet-Token","").strip()
        if not 40<=len(token)<=180:
            raise HTTPException(401,"Portofel privat necesar")
        wallet=db.query(WalletInboxAccess).filter_by(token_hash=access_hash(token)).first()
        if not wallet:
            raise HTTPException(401,"Portofel neautorizat")
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
        return {"code":row.code,"share_url":origin+"/register.html?ref="+row.code,
                "registered_merchants":recruited,"status":"eligible_for_activation" if recruited else "customer",
                "commission_on_signup":False}
    app.include_router(api)
