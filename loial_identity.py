"""Loial: independent, additive identities for business, ambassador and customer.

A person may hold all three roles. A customer wallet is linked only by presenting
its private inbox token; public QR and manually entered email are never proof of
wallet ownership. Existing ambassador accounts need password verification once.
"""
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, UniqueConstraint
from sqlalchemy.orm import Session, declarative_base

IdentityBase = declarative_base()

class BusinessAmbassadorLink(IdentityBase):
    __tablename__ = "loial_business_ambassador_links"
    business_id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, nullable=False, index=True)
    linked_at = Column(String(40), nullable=False)

class BusinessWalletLink(IdentityBase):
    __tablename__ = "loial_business_wallet_links"
    business_id = Column(Integer, primary_key=True)
    wallet_uuid = Column(String(120), nullable=False)
    linked_at = Column(String(40), nullable=False)

class NewAmbassador(BaseModel):
    display_name: str = Field(default="", max_length=100)

class AmbassadorName(BaseModel):
    display_name: str = Field(min_length=2, max_length=100)

class AmbassadorProof(BaseModel):
    password: str = Field(min_length=1, max_length=200)

class LinkWallet(BaseModel):
    wallet_private_token: str = Field(min_length=40, max_length=180)

def install_loial_identity(app, engine, session_factory, BusinessAccount,
                           SalesAgent, Sale, pwd_context, secret, algorithm,
                           wallet_access_model, wallet_hash, tier_func):
    IdentityBase.metadata.create_all(bind=engine)
    router = APIRouter(prefix="/api/loial-identity", tags=["Independent Loial Roles"])

    def session():
        db=session_factory()
        try:
            yield db
        finally:
            db.close()

    def claims(request):
        token=(request.headers.get("Authorization") or "").strip()
        if not token.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Autentificare necesara")
        try:
            payload=jwt.decode(token[7:],secret,algorithms=[algorithm])
        except JWTError:
            raise HTTPException(status_code=401, detail="Sesiune invalida")
        if payload.get("role") not in ("business", "ambassador"):
            raise HTTPException(status_code=403, detail="Cont de firma sau ambasador necesar")
        return payload

    def business(request:Request,db:Session=Depends(session)):
        payload=claims(request)
        if payload.get("role")!="business":
            raise HTTPException(status_code=403, detail="Administratorul firmei trebuie autentificat")
        account=db.query(BusinessAccount).filter(
            BusinessAccount.email==payload.get("sub")).first()
        if not account or (payload.get("business_id") and payload["business_id"]!=account.id):
            raise HTTPException(status_code=403, detail="Firma nu este disponibila")
        return account

    def public_ambassador(agent, db):
        completed = db.query(Sale).filter(
            Sale.agent_id == agent.id, Sale.status == "completed").count()
        tier=tier_func(completed)
        return {"name":agent.name,"id":agent.id,"ref_code":agent.qr_code,
                "rank":tier["rank"],"active_businesses":completed,
                "monthly_rate":tier["monthly_rate"],
                "referral_url":"https://loial.space/register.html?ref="+agent.qr_code}

    @router.get("/me")
    def me(request:Request,db:Session=Depends(session)):
        payload=claims(request)
        if payload["role"]=="ambassador":
            agent=db.query(SalesAgent).filter(SalesAgent.email==payload.get("sub"),
                                               SalesAgent.active.is_(True)).first()
            if not agent:
                raise HTTPException(status_code=403, detail="Ambasador inactiv")
            return {"roles":["ambassador"],"ambassador":public_ambassador(agent,db),
                    "business":None,"customer_wallet_linked":False}
        account=db.query(BusinessAccount).filter(
            BusinessAccount.email==payload.get("sub")).first()
        if not account:
            raise HTTPException(status_code=403,detail="Firma inexistenta")
        link=db.query(BusinessAmbassadorLink).filter(
            BusinessAmbassadorLink.business_id==account.id).first()
        agent=db.query(SalesAgent).filter(
            SalesAgent.id==link.agent_id, SalesAgent.active.is_(True)).first() if link else None
        candidate=db.query(SalesAgent).filter(SalesAgent.email==account.email).first()
        wallet=db.query(BusinessWalletLink).filter(
            BusinessWalletLink.business_id==account.id).first()
        roles=["business"]
        if agent:
            roles.append("ambassador")
        if wallet:
            roles.append("customer")
        return {"roles":roles,
                "business":{"id":account.id,"name":account.name,"plan":account.plan},
                "ambassador":public_ambassador(agent,db) if agent else None,
                "ambassador_needs_verification":bool(candidate and not link),
                "customer_wallet_linked":bool(wallet)}

    @router.post("/ambassador/activate")
    def activate(req:NewAmbassador,biz=Depends(business),db:Session=Depends(session)):
        link=db.query(BusinessAmbassadorLink).filter(
            BusinessAmbassadorLink.business_id==biz.id).first()
        if link:
            agent=db.query(SalesAgent).filter(SalesAgent.id==link.agent_id).first()
            if agent:
                return {"status":"already_active","ambassador":public_ambassador(agent,db)}
        existing=db.query(SalesAgent).filter(SalesAgent.email==biz.email).first()
        if existing:
            raise HTTPException(status_code=409,detail="Exista deja cont de ambasador pe acest email. Confirma parola contului existent pentru asociere.")
        ref="LOIAL-"+secrets.token_hex(5).upper()
        random_password=secrets.token_urlsafe(48)
        agent=SalesAgent(name=(req.display_name.strip() or biz.name)[:100],email=biz.email,
                         password=pwd_context.hash(random_password),
                         phone="",role="ambassador",rank="Ambasador",qr_code=ref,
                         status="active",active=True,payout_method="wise",
                         payout_details=None,
                         created_at=datetime.now(timezone.utc).isoformat())
        db.add(agent)
        db.flush()
        db.add(BusinessAmbassadorLink(business_id=biz.id,agent_id=agent.id,
            linked_at=datetime.now(timezone.utc).isoformat()))
        db.commit()
        return {"status":"activated","ambassador":public_ambassador(agent,db)}

    @router.post("/ambassador/link")
    def link_existing(req:AmbassadorProof,biz=Depends(business),db:Session=Depends(session)):
        existing=db.query(SalesAgent).filter(SalesAgent.email==biz.email).first()
        if not existing or not pwd_context.verify(req.password,existing.password):
            raise HTTPException(status_code=401,detail="Parola contului de ambasador este incorecta")
        link=db.query(BusinessAmbassadorLink).filter(
            BusinessAmbassadorLink.business_id==biz.id).first()
        if link and link.agent_id!=existing.id:
            raise HTTPException(status_code=409,detail="Aceasta firma are deja un ambasador asociat")
        if not link:
            db.add(BusinessAmbassadorLink(business_id=biz.id,agent_id=existing.id,
                linked_at=datetime.now(timezone.utc).isoformat()))
        db.commit()
        return {"status":"linked","ambassador":public_ambassador(existing,db)}

    @router.put("/ambassador/name")
    def set_ambassador_name(req:AmbassadorName,biz=Depends(business),db:Session=Depends(session)):
        link=db.query(BusinessAmbassadorLink).filter(
            BusinessAmbassadorLink.business_id==biz.id).first()
        agent=db.query(SalesAgent).filter(SalesAgent.id==link.agent_id).first() if link else None
        if not agent:
            raise HTTPException(status_code=404,detail="Activeaza mai intai statutul de ambasador")
        agent.name=req.display_name.strip()
        db.commit()
        return {"status":"updated","ambassador":public_ambassador(agent,db)}

    @router.post("/customer/link")
    def link_customer(req:LinkWallet,biz=Depends(business),db:Session=Depends(session)):
        access=db.query(wallet_access_model).filter(
            wallet_access_model.token_hash==wallet_hash(req.wallet_private_token)).first()
        if not access:
            raise HTTPException(status_code=401,detail="Verificarea portofelului de client a esuat")
        linked=db.query(BusinessWalletLink).filter(
            BusinessWalletLink.business_id==biz.id).first()
        if not linked:
            db.add(BusinessWalletLink(business_id=biz.id,wallet_uuid=access.wallet_uuid,
                linked_at=datetime.now(timezone.utc).isoformat()))
        else:
            linked.wallet_uuid=access.wallet_uuid
            linked.linked_at=datetime.now(timezone.utc).isoformat()
        db.commit()
        return {"status":"linked","roles":["business","customer"],
                "notice":"Cardul de client este separat de panoul firmei si de rolul de ambasador."}

    app.include_router(router)
