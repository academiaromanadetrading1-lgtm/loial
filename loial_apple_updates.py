"""Apple PassKit V1 update web service.

This implements authenticated registration, unregister, updated serial discovery and
re-download of a newly signed pass. Push-token storage is encrypted at rest. APNs
sending must be separately enabled and validated with the issuer; registering here
does not imply that iOS will receive a push notification.
"""
import hashlib
import hmac
import os
import time
from datetime import datetime, timezone
from email.utils import formatdate
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, Column, Integer, String, UniqueConstraint
from sqlalchemy.orm import declarative_base

AppleBase=declarative_base()

class ApplePass(AppleBase):
    __tablename__="loial_apple_passes"
    serial=Column(String(64),primary_key=True)
    role=Column(String(18),nullable=False)
    business_id=Column(Integer,nullable=True,index=True)
    wallet_uuid=Column(String(120),nullable=True)
    agent_id=Column(Integer,nullable=True)
    modified_ns=Column(BigInteger,nullable=False)
    version=Column(Integer,default=1)

class AppleRegistration(AppleBase):
    __tablename__="loial_apple_registrations"
    id=Column(Integer,primary_key=True)
    device_hash=Column(String(64),nullable=False,index=True)
    serial=Column(String(64),nullable=False,index=True)
    encrypted_push_token=Column(String(1000),nullable=False)
    created_at=Column(String(45),nullable=False)
    __table_args__=(UniqueConstraint("device_hash","serial",name="uq_loial_apple_device_pass"),)

class RegistrationPayload(BaseModel):
    pushToken:str=Field(min_length=8,max_length=512)

def apple_updates_ready():
    url=os.getenv("LOIAL_APPLE_WEB_SERVICE_URL","").rstrip("/")
    secret=os.getenv("LOIAL_APPLE_PASS_AUTH_SECRET","")
    key=os.getenv("LOIAL_APPLE_PUSH_TOKEN_FERNET_KEY","")
    try:
        Fernet(key.encode())
    except (ValueError,TypeError):
        return False
    return (url.startswith("https://") and len(secret)>=32 and
            bool(os.getenv("LOIAL_APPLE_PASS_TYPE_ID","")))

def pass_serial(card):
    return hashlib.sha256(("loial:"+card["role"]+":"+card["id"]).encode()).hexdigest()[:32]

def pass_authentication_token(serial):
    secret=os.getenv("LOIAL_APPLE_PASS_AUTH_SECRET","")
    if len(secret)<32:
        raise ValueError("PassKit auth secret missing")
    pass_type=os.environ["LOIAL_APPLE_PASS_TYPE_ID"]
    return hmac.new(secret.encode(),(pass_type+":"+serial).encode(),hashlib.sha256).hexdigest()

def device_hash(device_library_identifier):
    if not (12<=len(device_library_identifier)<=150):
        raise HTTPException(status_code=400,detail="Device identifier invalid")
    return hashlib.sha256(device_library_identifier.encode()).hexdigest()

def encrypt_push_token(token):
    key=os.environ["LOIAL_APPLE_PUSH_TOKEN_FERNET_KEY"]
    return Fernet(key.encode()).encrypt(token.encode()).decode()

def updated_ns():
    return time.time_ns()

def register_issued_pass(db,card,business_id=None,wallet_uuid=None,agent_id=None):
    if not apple_updates_ready():
        return None
    serial=pass_serial(card)
    old=db.query(ApplePass).filter(ApplePass.serial==serial).first()
    if not old:
        db.add(ApplePass(serial=serial,role=card["role"],
                         business_id=business_id,wallet_uuid=wallet_uuid,
                         agent_id=agent_id,modified_ns=updated_ns(),version=1))
    return serial

def mark_customer_pass_changed(db,business_id,wallet_uuid):
    """Lightweight update marker; no APNs or external request on stamp path."""
    if not wallet_uuid:
        return False
    card_id="client:"+str(business_id)+":"+wallet_uuid
    serial=hashlib.sha256(("loial:customer:"+card_id).encode()).hexdigest()[:32]
    state=db.query(ApplePass).filter(ApplePass.serial==serial,
                                   ApplePass.business_id==business_id,
                                   ApplePass.wallet_uuid==wallet_uuid).first()
    if not state:
        return False
    state.version+=1
    state.modified_ns=max(updated_ns(),state.modified_ns+1)
    return True

def install_apple_pass_updates(app,engine,factory,BusinessAccount,Customer,SalesAgent,
                               Sale,apple_pass_json,signed_apple_pkpass,
                               premium_card,tier_func):
    AppleBase.metadata.create_all(bind=engine)
    api=APIRouter(prefix="/api/passkit",tags=["Apple PassKit update service"])

    def db_session():
        db=factory()
        try:
            yield db
        finally:
            db.close()

    def authorize(request,serial):
        provided=request.headers.get("Authorization","")
        expected="ApplePass "+pass_authentication_token(serial)
        if not hmac.compare_digest(provided,expected):
            raise HTTPException(status_code=401,detail="Pass authorization denied")

    def state_for(db,pass_type,serial):
        if not apple_updates_ready() or pass_type!=os.getenv("LOIAL_APPLE_PASS_TYPE_ID"):
            raise HTTPException(status_code=404,detail="Pass type unavailable")
        record=db.query(ApplePass).filter(ApplePass.serial==serial).first()
        if not record:
            raise HTTPException(status_code=404,detail="Pass unknown")
        return record

    def card_for(db,state):
        if state.role=="customer":
            biz=db.query(BusinessAccount).filter(BusinessAccount.id==state.business_id).first()
            person=db.query(Customer).filter(
                Customer.business_id==state.business_id,
                ((Customer.wallet_uuid==state.wallet_uuid) |
                 (Customer.uuid==state.wallet_uuid))).first()
            if not biz or not person:
                raise HTTPException(status_code=404,detail="Card no longer exists")
            return premium_card(person.name,"customer",biz.name,
                "https://loial.space/scan.html?wallet_uuid="+state.wallet_uuid,
                "client:"+str(biz.id)+":"+state.wallet_uuid,
                stamps=person.stamps or 0,target=getattr(biz,"stamps_required",None) or 6)
        if state.role=="ambassador":
            agent=db.query(SalesAgent).filter(
                SalesAgent.id==state.agent_id,SalesAgent.active.is_(True)).first()
            if not agent:
                raise HTTPException(status_code=404,detail="Ambassador no longer active")
            count=db.query(Sale).filter(Sale.agent_id==agent.id,
                                        Sale.status=="completed").count()
            return premium_card(agent.name,"ambassador","RETEAUA LOIAL",
                "https://loial.space/register.html?ref="+agent.qr_code,
                "ambassador:"+str(agent.id),status=tier_func(count)["rank"].upper())
        raise HTTPException(status_code=404,detail="Unsupported pass")

    @api.post("/v1/devices/{device_id}/registrations/{pass_type}/{serial}")
    def register(device_id:str,pass_type:str,serial:str,payload:RegistrationPayload,
                 request:Request,db=Depends(db_session)):
        record=state_for(db,pass_type,serial)
        authorize(request,serial)
        did=device_hash(device_id)
        reg=db.query(AppleRegistration).filter(
            AppleRegistration.device_hash==did,AppleRegistration.serial==serial).first()
        if reg:
            reg.encrypted_push_token=encrypt_push_token(payload.pushToken)
            db.commit()
            return Response(status_code=200)
        db.add(AppleRegistration(device_hash=did,serial=serial,
                                 encrypted_push_token=encrypt_push_token(payload.pushToken),
                                 created_at=datetime.now(timezone.utc).isoformat()))
        db.commit()
        return Response(status_code=201)

    @api.delete("/v1/devices/{device_id}/registrations/{pass_type}/{serial}")
    def unregister(device_id:str,pass_type:str,serial:str,request:Request,
                   db=Depends(db_session)):
        state_for(db,pass_type,serial)
        authorize(request,serial)
        registration=db.query(AppleRegistration).filter(
            AppleRegistration.device_hash==device_hash(device_id),
            AppleRegistration.serial==serial).first()
        if registration:
            db.delete(registration)
            db.commit()
        return Response(status_code=200)

    @api.get("/v1/devices/{device_id}/registrations/{pass_type}")
    def updates(device_id:str,pass_type:str,passes_updated_since:Optional[str]=Query(None,alias="passesUpdatedSince"),
                db=Depends(db_session)):
        if not apple_updates_ready() or pass_type!=os.getenv("LOIAL_APPLE_PASS_TYPE_ID"):
            raise HTTPException(status_code=404,detail="Pass type unavailable")
        did=device_hash(device_id)
        registrations=db.query(AppleRegistration).filter(
            AppleRegistration.device_hash==did).all()
        if not registrations:
            return Response(status_code=204)
        try:
            since=int(passes_updated_since or "0")
            if since<0:
                raise ValueError()
        except ValueError:
            raise HTTPException(status_code=400,detail="Invalid update tag")
        serials=[r.serial for r in registrations]
        states=db.query(ApplePass).filter(
            ApplePass.serial.in_(serials),ApplePass.modified_ns>since
        ).order_by(ApplePass.modified_ns.asc()).all()
        if not states:
            return Response(status_code=204)
        return {"serialNumbers":[state.serial for state in states],
                "lastUpdated":str(max(state.modified_ns for state in states))}

    @api.get("/v1/passes/{pass_type}/{serial}")
    def download(pass_type:str,serial:str,request:Request,db=Depends(db_session)):
        record=state_for(db,pass_type,serial)
        authorize(request,serial)
        card=card_for(db,record)
        if pass_serial(card)!=record.serial:
            raise HTTPException(status_code=409,detail="Pass identity mismatch")
        try:
            content=signed_apple_pkpass(card)
        except ValueError as e:
            raise HTTPException(status_code=503,detail="Issuer signing unavailable")
        return Response(content=content,media_type="application/vnd.apple.pkpass",
            headers={"Cache-Control":"private, no-store",
                     "Last-Modified":formatdate(record.modified_ns//1_000_000_000,usegmt=True),
                     "X-Content-Type-Options":"nosniff"})

    @api.post("/v1/log")
    def apple_log():
        # Apple may transmit device diagnostic text; do not store secrets or log raw contents.
        return Response(status_code=200)

    app.include_router(api)
