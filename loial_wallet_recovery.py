"""Owner-assisted, one-card-at-a-time recovery of LEGACY Loial wallets.

Security: public QR/wallet_uuid never authorizes transfer. Owner must see the
customer in person (or verify using an equivalent documented procedure) and
issue a short-lived, single-use high-entropy recovery ticket. Tickets cannot
be used to take over an already privately authenticated wallet. Only this
merchant's card is transferred; other businesses remain untouched.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, Session

from loial_inbox import WalletInboxAccess, access_hash, now
from loial_google_issuer import loyalty_class_id_for_business

RecoveryBase=declarative_base()
TTL_MINUTES=15

class RecoveryTicket(RecoveryBase):
    __tablename__="loial_wallet_recovery_tickets"
    id=Column(Integer,primary_key=True)
    business_id=Column(Integer,nullable=False,index=True)
    customer_id=Column(Integer,nullable=False,index=True)
    ticket_hash=Column(String(64),nullable=False,unique=True,index=True)
    status=Column(String(20),nullable=False,default="pending")
    expires_at=Column(String(40),nullable=False)
    created_at=Column(String(40),nullable=False)
    used_at=Column(String(40))

class RecoveryRequest(BaseModel):
    customer_id:int=Field(gt=0)
    verification_note:str=Field(min_length=8,max_length=200)

class RecoveryClaim(BaseModel):
    code:str=Field(min_length=32,max_length=180)
    new_wallet_uuid:str=Field(min_length=20,max_length=120)
    new_private_token:str=Field(min_length=40,max_length=180)

def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def now_utc():
    return datetime.now(timezone.utc)

def verified_wallet(db, wallet_uuid):
    return db.query(WalletInboxAccess).filter(
        WalletInboxAccess.wallet_uuid==wallet_uuid).first()

def install_wallet_recovery(app,engine,factory,BusinessAccount,Customer,
                            AIDocument,AISale,secret,algorithm):
    RecoveryBase.metadata.create_all(bind=engine)
    router=APIRouter(prefix="/api/loial-wallet-recovery",
                     tags=["Loial legacy wallet migration"])

    def database():
        db=factory()
        try:
            yield db
        finally:
            db.close()

    def owner(request:Request,db:Session=Depends(database)):
        auth=request.headers.get("Authorization") or ""
        if not auth.startswith("Bearer "):
            raise HTTPException(status_code=401,detail="Autentificare Business necesara")
        try:
            claims=jwt.decode(auth[7:],secret,algorithms=[algorithm])
        except JWTError:
            raise HTTPException(status_code=401,detail="Sesiune invalida")
        if claims.get("role")!="business":
            raise HTTPException(status_code=403,detail="Doar administratorul firmei")
        biz=db.query(BusinessAccount).filter(
            BusinessAccount.email==claims.get("sub")).first()
        if not biz or (claims.get("business_id") and biz.id!=claims["business_id"]):
            raise HTTPException(status_code=403,detail="Firma nu este disponibila")
        return biz

    def ticket_by_code(db,code):
        result=db.query(RecoveryTicket).filter(
            RecoveryTicket.ticket_hash==sha(code)).first()
        if not result or result.status!="pending":
            raise HTTPException(status_code=404,detail="Cod de recuperare inexistent sau consumat")
        if datetime.fromisoformat(result.expires_at)<now_utc():
            raise HTTPException(status_code=410,detail="Codul de recuperare a expirat")
        return result

    @router.post("/request")
    def request_recovery(req:RecoveryRequest,biz=Depends(owner),
                         db:Session=Depends(database)):
        customer=db.query(Customer).filter(
            Customer.id==req.customer_id,Customer.business_id==biz.id).first()
        if not customer:
            raise HTTPException(status_code=404,detail="Clientul nu apartine acestei firme")
        old_wallet=customer.wallet_uuid or customer.uuid
        if not old_wallet:
            raise HTTPException(status_code=409,detail="Cardul vechi nu are identificator valid")
        if verified_wallet(db,old_wallet):
            raise HTTPException(status_code=409,detail=
                "Cardul are deja acces privat. Foloseste dispozitivul titularului sau asistenta verificata.")
        now_time=now_utc()
        pending=db.query(RecoveryTicket).filter(
            RecoveryTicket.business_id==biz.id,
            RecoveryTicket.customer_id==customer.id,
            RecoveryTicket.status=="pending").all()
        for item in pending:
            item.status="replaced"
        raw=secrets.token_urlsafe(32)
        ticket=RecoveryTicket(business_id=biz.id,customer_id=customer.id,
            ticket_hash=sha(raw),status="pending",
            expires_at=(now_time+timedelta(minutes=TTL_MINUTES)).isoformat(),
            created_at=now_time.isoformat())
        db.add(ticket)
        db.commit()
        return {"recovery_url":"https://loial.space/wallet-recovery.html?code="+raw,
                "expires_in_minutes":TTL_MINUTES,
                "business":biz.name,
                "customer":customer.name,
                "notice":"Verifica titularul in persoana. Codul transfera doar cardul acestei firme."}

    @router.get("/preview")
    def preview(code:str,db:Session=Depends(database)):
        if not (32<=len(code)<=180):
            raise HTTPException(status_code=422,detail="Cod invalid")
        ticket=ticket_by_code(db,code)
        biz=db.query(BusinessAccount).filter(
            BusinessAccount.id==ticket.business_id).first()
        if not biz:
            raise HTTPException(status_code=404,detail="Firma nu mai exista")
        return {"business":biz.name,"expires_at":ticket.expires_at,
                "card_scope":"single_business",
                "notice":"Transferul nu acorda acces la mesajele sau cardurile altor firme."}

    @router.post("/claim")
    def claim(req:RecoveryClaim,db:Session=Depends(database)):
        ticket=ticket_by_code(db,req.code)
        customer=db.query(Customer).filter(
            Customer.id==ticket.customer_id,
            Customer.business_id==ticket.business_id).first()
        if not customer:
            raise HTTPException(status_code=404,detail="Cardul nu mai exista")
        prior_wallet=customer.wallet_uuid or customer.uuid
        if verified_wallet(db,prior_wallet):
            raise HTTPException(status_code=409,detail=
                "Un dispozitiv privat este deja asociat; transferul nu este permis prin codul comerciantului.")
        if not req.new_wallet_uuid.startswith("W-"):
            raise HTTPException(status_code=422,detail="Identificatorul portofelului nou este invalid")
        if verified_wallet(db,req.new_wallet_uuid):
            # Never transfer the card based on an unverified existing UUID.
            raise HTTPException(status_code=409,detail="Portofelul destinatie exista deja")
        # Newly generated wallet UUID may not have an existing claim or card.
        if db.query(Customer).filter(
            (Customer.uuid==req.new_wallet_uuid) |
            (Customer.wallet_uuid==req.new_wallet_uuid)).first():
            raise HTTPException(status_code=409,detail="Identificatorul de destinatie este folosit")
        current=now_utc()
        old_wallet=prior_wallet
        # New independent card identity, so the old public QR cannot be scanned.
        customer.uuid="REC-"+uuid.uuid4().hex
        customer.wallet_uuid=req.new_wallet_uuid
        db.add(WalletInboxAccess(wallet_uuid=req.new_wallet_uuid,
                                 token_hash=access_hash(req.new_private_token),
                                 created_at=current.isoformat()))
        # Move only the merchant's own verified itemized purchase links.
        for row in db.query(AISale).filter(
            AISale.business_id==ticket.business_id,
            AISale.customer_uuid==old_wallet).all():
            row.customer_uuid=req.new_wallet_uuid
        ticket.status="used"
        ticket.used_at=current.isoformat()
        db.commit()
        return {"status":"recovered","wallet_uuid":req.new_wallet_uuid,
                "wallet_private_token":req.new_private_token,
                "business_id":ticket.business_id,
                "name":customer.name,
                "stamps":customer.stamps or 0,
                "scope":"single_business",
                "other_businesses_moved":False}

    app.include_router(router)
