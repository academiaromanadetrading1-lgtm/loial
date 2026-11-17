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
from sqlalchemy import Column, Integer, String, Text, UniqueConstraint, update
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
    verification_note=Column(String(200),nullable=False,default="")

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

    @router.get("/eligible")
    def eligible_clients(q:str="",limit:int=50,biz=Depends(owner),
                         db:Session=Depends(database)):
        # Scoped lookup of legacy cards only. No emails, phone numbers or QR secrets.
        result=db.query(Customer).filter(Customer.business_id==biz.id)
        term=q.strip()[:60]
        if term:
            result=result.filter(Customer.name.ilike("%"+term.replace("%","\\%").replace("_","\\_")+"%",
                                                   escape="\\"))
        cards=result.order_by(Customer.id.desc()).limit(min(max(limit,1),100)).all()
        items=[]
        for c in cards:
            old_uuid=c.wallet_uuid or c.uuid
            if not old_uuid or verified_wallet(db,old_uuid):
                continue
            items.append({"id":c.id,"name":c.name,"stamps":c.stamps or 0,
                          "last_visit":c.last_visit,
                          "recovery_available":True})
        return {"items":items,"business_id":biz.id}

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
            created_at=now_time.isoformat(),
            verification_note=req.verification_note.strip())
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
        ticket=db.query(RecoveryTicket).filter(
            RecoveryTicket.ticket_hash==sha(req.code)).first()
        if ticket and ticket.status=="used":
            customer=db.query(Customer).filter(
                Customer.id==ticket.customer_id,
                Customer.business_id==ticket.business_id).first()
            verified=verified_wallet(db,req.new_wallet_uuid)
            if (customer and customer.wallet_uuid==req.new_wallet_uuid and verified
                and verified.token_hash==access_hash(req.new_private_token)):
                return {"status":"recovered","wallet_uuid":req.new_wallet_uuid,
                        "wallet_private_token":req.new_private_token,
                        "business_id":ticket.business_id,"name":customer.name,
                        "stamps":customer.stamps or 0,"scope":"single_business",
                        "other_businesses_moved":False,"replayed":True}
            raise HTTPException(status_code=409,detail="Cod deja consumat de alt dispozitiv")
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
        destination=verified_wallet(db,req.new_wallet_uuid)
        if destination and destination.token_hash!=access_hash(req.new_private_token):
            raise HTTPException(status_code=409,detail="Portofelul destinatie nu este verificat")
        existing_card=db.query(Customer).filter(
            Customer.business_id==ticket.business_id,
            ((Customer.uuid==req.new_wallet_uuid) |
             (Customer.wallet_uuid==req.new_wallet_uuid))).first()
        if existing_card and existing_card.id!=customer.id:
            raise HTTPException(status_code=409,detail="Exista deja un card pentru aceasta firma pe portofelul ales")
        current=now_utc()
        # One-time atomic claim to prevent concurrent transfers to two devices.
        claimed=db.execute(
            update(RecoveryTicket).where(
                RecoveryTicket.id==ticket.id,
                RecoveryTicket.status=="pending").values(
                    status="used",used_at=current.isoformat())
        ).rowcount
        if claimed!=1:
            db.rollback()
            raise HTTPException(status_code=409,detail="Codul a fost deja folosit")
        old_wallet=prior_wallet
        # New independent card identity, so the old public QR cannot be scanned.
        old_card_uuid=customer.uuid
        customer.uuid="REC-"+uuid.uuid4().hex
        customer.wallet_uuid=req.new_wallet_uuid
        if not destination:
            db.add(WalletInboxAccess(wallet_uuid=req.new_wallet_uuid,
                                     token_hash=access_hash(req.new_private_token),
                                     created_at=current.isoformat()))
        # Preserve purchases only for this business, never for other merchants.
        from sqlalchemy import or_
        for row in db.query(AISale).filter(
            AISale.business_id==ticket.business_id,
            AISale.customer_uuid.in_([old_wallet,old_card_uuid])).all():
            row.customer_uuid=req.new_wallet_uuid
        db.commit()
        return {"status":"recovered","wallet_uuid":req.new_wallet_uuid,
                "wallet_private_token":req.new_private_token,
                "business_id":ticket.business_id,
                "name":customer.name,
                "stamps":customer.stamps or 0,
                "scope":"single_business",
                "other_businesses_moved":False}

    app.include_router(router)
