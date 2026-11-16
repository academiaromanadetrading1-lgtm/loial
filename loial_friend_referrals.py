"""Loial Friend Rewards: customer-to-customer referrals, separate from ambassadors.

Only newly enrolled wallets may be attributed. A referral becomes qualified
after the invited friend receives a verified loyalty stamp from a merchant.
Rewards are PILOT loyalty points with NO monetary value, no withdrawal,
no conversion to partner discounts until a separately approved program exists.
No contact lists, emails, SMS, cash payout, or paid provider is required.
"""
import secrets
from datetime import datetime, timezone
from hashlib import sha256
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, UniqueConstraint, func, update
from sqlalchemy.orm import declarative_base, Session

from loial_inbox import WalletInboxAccess, access_hash

ReferralBase=declarative_base()
POINTS_PER_PERSON=10
MAX_QUALIFIED_PER_REFERRER_MONTH=20

def utc():
    return datetime.now(timezone.utc).isoformat()

class FriendReferralCode(ReferralBase):
    __tablename__="loial_friend_referral_codes"
    wallet_uuid=Column(String(120),primary_key=True)
    code=Column(String(60),unique=True,nullable=False,index=True)
    created_at=Column(String(40),nullable=False)

class FriendInvitation(ReferralBase):
    __tablename__="loial_friend_invitations"
    id=Column(Integer,primary_key=True)
    invitee_wallet=Column(String(120),unique=True,nullable=False,index=True)
    referrer_wallet=Column(String(120),nullable=False,index=True)
    referral_code=Column(String(60),nullable=False)
    status=Column(String(16),nullable=False,default="pending")
    created_at=Column(String(40),nullable=False)
    qualified_at=Column(String(40))
    qualified_business_id=Column(Integer)
    qualified_operation=Column(String(140))

class FriendPoints(ReferralBase):
    __tablename__="loial_friend_points_ledger"
    id=Column(Integer,primary_key=True)
    wallet_uuid=Column(String(120),nullable=False,index=True)
    points=Column(Integer,nullable=False)
    event_key=Column(String(140),nullable=False,unique=True)
    reason=Column(String(50),nullable=False)
    created_at=Column(String(40),nullable=False)

def reward_balance(db, wallet_uuid):
    return int(db.query(func.coalesce(func.sum(FriendPoints.points),0)).filter(
        FriendPoints.wallet_uuid==wallet_uuid).scalar() or 0)

def create_code(db, wallet_uuid):
    existing=db.query(FriendReferralCode).filter(
        FriendReferralCode.wallet_uuid==wallet_uuid).first()
    if existing:return existing
    code="L-"+secrets.token_urlsafe(17).replace("-","").replace("_","")
    result=FriendReferralCode(wallet_uuid=wallet_uuid,code=code,
                               created_at=utc())
    db.add(result)
    db.flush()
    return result

def attribute_new_wallet(db, invitee_wallet, referral_code):
    """Call ONLY after new wallet issuance; never for an old/migrated identity."""
    code=(referral_code or "").strip()
    if not code:return "no_invitation"
    if len(code)>60:return "invalid"
    ref=db.query(FriendReferralCode).filter(
        FriendReferralCode.code==code).first()
    if not ref:return "invalid"
    if ref.wallet_uuid==invitee_wallet:return "self_referral"
    verified=db.query(WalletInboxAccess).filter(
        WalletInboxAccess.wallet_uuid==ref.wallet_uuid).first()
    if not verified:return "invalid"
    if db.query(FriendInvitation).filter(
        FriendInvitation.invitee_wallet==invitee_wallet).first():
        return "already_attributed"
    db.add(FriendInvitation(invitee_wallet=invitee_wallet,
            referrer_wallet=ref.wallet_uuid,referral_code=code,
            status="pending",created_at=utc()))
    db.flush()
    return "pending_first_verified_visit"

def credit_after_valid_stamp(db, invitee_wallet, business_id, operation):
    """Staff scan or one-use receipt is a verified qualification event.

    Atomic claim from 'pending' to 'qualified' before ledger credits.
    Idempotent even when identical scan is retried.
    """
    invitation=db.query(FriendInvitation).filter(
        FriendInvitation.invitee_wallet==invitee_wallet).first()
    if not invitation or invitation.status!="pending":return "not_pending"
    if invitation.referrer_wallet==invitee_wallet:return "self_referral"
    now=utc()
    month=now[:7]
    credited=db.query(FriendInvitation).filter(
        FriendInvitation.referrer_wallet==invitation.referrer_wallet,
        FriendInvitation.status=="qualified",
        FriendInvitation.qualified_at.startswith(month)).count()
    if credited>=MAX_QUALIFIED_PER_REFERRER_MONTH:
        invitation.status="review"
        return "monthly_limit_review"
    claimed=db.execute(update(FriendInvitation).where(
        FriendInvitation.id==invitation.id,FriendInvitation.status=="pending")
        .values(status="qualified",qualified_at=now,
                qualified_business_id=business_id,
                qualified_operation=str(operation)[:140]))
    if claimed.rowcount!=1:return "already_qualified"
    for owner,suffix in ((invitation.referrer_wallet,"inviter"),
                         (invitee_wallet,"friend")):
        db.add(FriendPoints(wallet_uuid=owner,points=POINTS_PER_PERSON,
            event_key=f"qualified:{invitation.id}:{suffix}",reason="friend_visit",
            created_at=now))
    db.flush()
    return "qualified"

def reverse_referral_for_refunded_receipt(db, invitee_wallet, operation):
    """Revoke reward only if the exact first qualifying receipt was refunded."""
    invitation=db.query(FriendInvitation).filter(
        FriendInvitation.invitee_wallet==invitee_wallet,
        FriendInvitation.status=="qualified",
        FriendInvitation.qualified_operation==operation).first()
    if not invitation:return False
    invitation.status="reversed"
    for owner,suffix in ((invitation.referrer_wallet,"inviter"),
                         (invitee_wallet,"friend")):
        db.add(FriendPoints(wallet_uuid=owner,points=-POINTS_PER_PERSON,
            event_key=f"reversed:{invitation.id}:{suffix}",
            reason="refunded_first_visit",created_at=utc()))
    db.flush()
    return True

def install_friend_referrals(app,engine,factory):
    ReferralBase.metadata.create_all(bind=engine)
    api=APIRouter(prefix="/api/loial-friends",tags=["Loial friends"])

    def session():
        db=factory()
        try:yield db
        finally:db.close()

    def wallet(request:Request,db:Session=Depends(session)):
        credential=(request.headers.get("X-Loial-Wallet-Token") or "").strip()
        if not 40<=len(credential)<=180:
            raise HTTPException(status_code=401,detail="Portofel privat necesar")
        record=db.query(WalletInboxAccess).filter(
            WalletInboxAccess.token_hash==access_hash(credential)).first()
        if not record:
            raise HTTPException(status_code=401,detail="Dispozitiv neautorizat")
        return record

    @api.get("/program")
    def program():
        return {"name":"Loial Recomanda","reward_kind":"pilot_non_cash_points",
            "points_for_inviter":POINTS_PER_PERSON,
            "points_for_friend":POINTS_PER_PERSON,
            "qualification":"Prima stampila reala verificata de comerciant.",
            "monthly_qualification_cap":MAX_QUALIFIED_PER_REFERRER_MONTH,
            "requires_ambassador_role":False,"monetary_value_eur":None,
            "cash_withdrawal":False,"merchant_redemption_enabled":False,
            "notice":"Punctele sunt pilot, fara valoare monetara sau reducere garantata. Beneficiile viitoare necesita acordul comerciantilor si reguli publicate."}

    @api.get("/validate")
    def validate(code:str):
        if len(code)>60 or len(code)<8:return {"valid":False}
        with factory() as db:
            found=db.query(FriendReferralCode).filter(
                FriendReferralCode.code==code).first()
            return {"valid":bool(found)}

    @api.get("/me")
    def me(record=Depends(wallet),db:Session=Depends(session)):
        identity=create_code(db,record.wallet_uuid)
        db.commit()
        entries=db.query(FriendInvitation).filter(
            FriendInvitation.referrer_wallet==record.wallet_uuid).all()
        own=db.query(FriendInvitation).filter(
            FriendInvitation.invitee_wallet==record.wallet_uuid).first()
        return {"code":identity.code,
                "share_url":"https://loial.space/wallet?invite="+identity.code,
                "points":reward_balance(db,record.wallet_uuid),
                "pending":sum(1 for r in entries if r.status=="pending"),
                "qualified":sum(1 for r in entries if r.status=="qualified"),
                "review":sum(1 for r in entries if r.status=="review"),
                "reversed":sum(1 for r in entries if r.status=="reversed"),
                "my_invitation_status":own.status if own else None,
                "is_ambassador":False,
                "rewards":"Puncte Loial de pilot, fara valoare monetara.",
                "cash_withdrawal":False,
                "merchant_redemption_enabled":False}

    app.include_router(api)
