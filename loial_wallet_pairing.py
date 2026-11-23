"""Pair an already authenticated LOIAL wallet with an installed PWA.
Never recover a private wallet from its public QR or a customer's name.
A high-entropy, 10-minute, single-use pairing code is issued only after
the original browser proves possession of the private wallet secret.
"""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, update
from sqlalchemy.orm import declarative_base, Session
from loial_inbox import WalletInboxAccess, access_hash

PairBase = declarative_base()

class WalletPairTicket(PairBase):
    __tablename__ = "loial_wallet_pair_tickets"
    id = Column(Integer, primary_key=True)
    wallet_uuid = Column(String(120), nullable=False, index=True)
    code_hash = Column(String(64), nullable=False, unique=True, index=True)
    private_token_encrypted = Column(String(500), nullable=False)
    expires_at = Column(String(40), nullable=False)
    consumed_at = Column(String(40))

class PairClaim(BaseModel):
    code: str = Field(min_length=40, max_length=160)

def utc_now():
    return datetime.now(timezone.utc)

def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def install_wallet_pairing(app, engine, session_factory, encrypt, decrypt, limiter=None):
    # The encrypted private token is retained for at most ten minutes and
    # discarded on claim. Expired records are purged at request time.
    PairBase.metadata.create_all(bind=engine)
    router = APIRouter(prefix="/api/loial-wallet-pair", tags=["Device pairing"])

    def database():
        db=session_factory()
        try:
            yield db
        finally:
            db.close()

    def purge(db):
        now=utc_now().isoformat()
        db.query(WalletPairTicket).filter(WalletPairTicket.expires_at < now).delete(synchronize_session=False)
        db.query(WalletPairTicket).filter(WalletPairTicket.consumed_at.isnot(None)).delete(synchronize_session=False)
        db.flush()

    @router.post("/issue")
    @((limiter.limit("5/minute")) if limiter else (lambda f:f))
    def issue(request: Request, db: Session=Depends(database)):
        wallet=(request.headers.get("X-Loial-Wallet-Id") or "").strip()
        token=(request.headers.get("X-Loial-Wallet-Token") or "").strip()
        if not re.fullmatch(r"W-[A-Za-z0-9_-]{17,117}",wallet) or not 40 <= len(token) <= 180:
            raise HTTPException(status_code=401, detail="Cardul original trebuie deschis pe dispozitivul autorizat")
        verified=db.query(WalletInboxAccess).filter(
            WalletInboxAccess.wallet_uuid==wallet,
            WalletInboxAccess.token_hash==access_hash(token)
        ).first()
        if not verified:
            raise HTTPException(status_code=403,detail="Accesul la card nu este verificat")
        purge(db)
        # Issue one usable code at a time for each wallet.
        db.query(WalletPairTicket).filter(WalletPairTicket.wallet_uuid==wallet).delete(synchronize_session=False)
        code=secrets.token_urlsafe(32)
        db.add(WalletPairTicket(
            wallet_uuid=wallet,
            code_hash=digest(code),
            private_token_encrypted=encrypt(token),
            expires_at=(utc_now()+timedelta(minutes=10)).isoformat()
        ))
        db.commit()
        return {"pairing_code":code,"expires_in_minutes":10}

    @router.post("/claim")
    @((limiter.limit("5/minute")) if limiter else (lambda f:f))
    def claim(request: Request, body: PairClaim, db: Session=Depends(database)):
        code=body.code.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{40,160}",code):
            raise HTTPException(status_code=422,detail="Cod de asociere invalid")
        # An atomic consume prevents simultaneous sessions from using the code.
        now=utc_now().isoformat()
        ticket=db.query(WalletPairTicket).filter(
            WalletPairTicket.code_hash==digest(code),
            WalletPairTicket.expires_at>now,
            WalletPairTicket.consumed_at.is_(None)
        ).first()
        if not ticket:
            raise HTTPException(status_code=404,detail="Cod inexistent, expirat sau deja utilizat")
        updated=db.execute(update(WalletPairTicket).where(
            WalletPairTicket.id==ticket.id,
            WalletPairTicket.consumed_at.is_(None),
            WalletPairTicket.expires_at>now
        ).values(consumed_at=now))
        if updated.rowcount!=1:
            db.rollback()
            raise HTTPException(status_code=409,detail="Codul a fost deja utilizat")
        try:
            token=decrypt(ticket.private_token_encrypted)
        except Exception:
            db.rollback()
            raise HTTPException(status_code=503,detail="Asocierea nu este disponibilă")
        verified=db.query(WalletInboxAccess).filter(
            WalletInboxAccess.wallet_uuid==ticket.wallet_uuid,
            WalletInboxAccess.token_hash==access_hash(token)
        ).first()
        if not verified:
            db.rollback()
            raise HTTPException(status_code=403,detail="Cardul original nu mai este autorizat")
        wallet=ticket.wallet_uuid
        db.delete(ticket)
        db.commit()
        return {"status":"paired","wallet_uuid":wallet,"private_token":token}

    app.include_router(router)
