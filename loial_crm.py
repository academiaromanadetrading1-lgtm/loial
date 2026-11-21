"""Verified, tenant-scoped CRM and offer reactions. No external calls."""
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from jose import JWTError, jwt
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base
from sqlalchemy.exc import IntegrityError
from loial_receipts import Receipt
from loial_scans import StampAward
from loial_inbox import WalletInboxAccess, InboxDelivery, InboxEntry, access_hash, latest_offer_choice

CRMBase=declarative_base()
class OfferReaction(CRMBase):
    __tablename__="loial_offer_reactions"
    delivery_id=Column(Integer,primary_key=True)
    business_id=Column(Integer,nullable=False,index=True)
    customer_id=Column(Integer,nullable=False,index=True)
    choice=Column(String(24),nullable=False)
    updated_at=Column(String(40),nullable=False)

def timestamp(value):
    try:
        d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
    except (ValueError,TypeError):
        return None

def metrics(receipts,awards,products,now,currency="RON"):
    valid=[(r,d) for r in receipts if (d:=timestamp(getattr(r,"claimed_at",None) or r.issued_at)) is not None and d<=now]
    days=sorted({d.date() for r,d in valid})
    money=[r for r,d in valid if r.currency==currency]
    total=sum(r.total_minor for r in money)
    visits=[d for a in awards if a.source in ("manual","receipt") and (d:=timestamp(a.created_at)) is not None and d<=now]
    last=max([d for r,d in valid]+visits,default=None)
    return {"verified_receipts":len(valid),"verified_receipts_90d":sum(d>=now-timedelta(days=90) for r,d in valid),
            "purchase_days":len(days),"loyalty_events":len(visits),"last_activity":last.isoformat() if last else None,
            "days_since_activity":(now.date()-last.date()).days if last else None,
            "frequency_days":round((days[-1]-days[0]).days/(len(days)-1),1) if len(days)>1 else None,
            "currency":currency,"verified_spend_minor":total if money else None,
            "average_receipt_minor":int((Decimal(total)/len(money)).quantize(Decimal("1"),rounding=ROUND_HALF_UP)) if money else None,
            "products":[{"name":k,"quantity":float(v)} for k,v in products.most_common(20)]}

def select_crm(db,business_id,Customer,Consent,AISale,min_purchases=0,min_spend_minor=0,product="",currency="RON",max_inactive_days=36500,min_inactive_days=0):
    now=datetime.now(timezone.utc)
    receipts=db.query(Receipt).filter_by(business_id=business_id,status="claimed").all()
    by_wallet=defaultdict(list); awards=defaultdict(list); products=defaultdict(Counter)
    documents={}
    for rec in receipts:
        if not rec.claimed_wallet: continue
        by_wallet[rec.claimed_wallet].append(rec)
        documents[rec.document_id]=rec.claimed_wallet
    for a in db.query(StampAward).filter_by(business_id=business_id).all(): awards[a.customer_id].append(a)
    for sale in db.query(AISale).filter_by(business_id=business_id).all():
        w=documents.get(sale.document_id)
        if w and sale.customer_uuid==w:
            products[w][sale.product.strip().casefold()]+=Decimal(str(sale.quantity))
    output=[]
    for c in db.query(Customer).filter_by(business_id=business_id).order_by(Customer.id).all():
        w=c.wallet_uuid or c.uuid
        p=products[w]
        m=metrics(by_wallet[w],awards[c.id],p,now,currency)
        if m["verified_receipts_90d"]<min_purchases: continue
        if min_spend_minor and (m["verified_spend_minor"] is None or m["verified_spend_minor"]<min_spend_minor): continue
        if product.strip() and product.strip().casefold() not in p: continue
        if min_inactive_days and (m["days_since_activity"] is None or m["days_since_activity"]<min_inactive_days): continue
        if max_inactive_days<36500 and (m["days_since_activity"] is None or m["days_since_activity"]>max_inactive_days): continue
        output.append({"id":c.id,"name":c.name,"offers_enabled":latest_offer_choice(db,Consent,c.id),**m})
    return output

def install_crm(app,engine,factory,BusinessAccount,Customer,Consent,AISale,jwt_key,algorithm):
    CRMBase.metadata.create_all(bind=engine)
    r=APIRouter(prefix="/api/loial-crm",tags=["Verified customer CRM"])
    def session():
        db=factory()
        try: yield db
        finally: db.close()
    def owner(request:Request,db=Depends(session)):
        raw=request.headers.get("Authorization","")
        if not raw.startswith("Bearer "): raise HTTPException(401,"Autentificare obligatorie")
        try: claims=jwt.decode(raw[7:],jwt_key,algorithms=[algorithm])
        except JWTError: raise HTTPException(401,"Sesiune invalida")
        if claims.get("role")!="business": raise HTTPException(403,"Acces rezervat firmei")
        biz=db.query(BusinessAccount).filter_by(email=claims.get("sub")).first()
        if not biz or type(claims.get("business_id")) is not int or claims["business_id"]!=biz.id: raise HTTPException(403,"Acces refuzat")
        return biz
    def wallet(request:Request,db=Depends(session)):
        token=request.headers.get("X-Loial-Wallet-Token","")
        if not 40<=len(token)<=180: raise HTTPException(401,"Portofel neautorizat")
        w=db.query(WalletInboxAccess).filter_by(token_hash=access_hash(token)).first()
        if not w: raise HTTPException(401,"Portofel neautorizat")
        return w
    @r.get("/customers")
    def customers(min_purchases:int=Query(0,ge=0),min_spend_minor:int=Query(0,ge=0),
                  product:str=Query("",max_length=160),currency:str=Query("RON",pattern="^(RON|EUR|USD|GBP)$"),
                  max_inactive_days:int=Query(36500,ge=0,le=36500),min_inactive_days:int=Query(0,ge=0,le=36500),offset:int=Query(0,ge=0),
                  limit:int=Query(100,ge=1,le=500),biz=Depends(owner),db=Depends(session)):
        if min_inactive_days>max_inactive_days: raise HTTPException(422,"Interval de inactivitate invalid")
        output=select_crm(db,biz.id,Customer,Consent,AISale,min_purchases,min_spend_minor,product,currency,max_inactive_days,min_inactive_days)
        return {"total":len(output),"items":output[offset:offset+limit],"source":"verified_receipts_and_loyalty_events"}
    @r.post("/reaction/{delivery_id}/{choice}")
    def react(delivery_id:int,choice:str,w=Depends(wallet),db=Depends(session)):
        if choice not in ("interested","not_interested"): raise HTTPException(422,"Raspuns necunoscut")
        d=db.get(InboxDelivery,delivery_id)
        if not d: raise HTTPException(404,"Mesaj negasit")
        c=db.query(Customer).filter(Customer.id==d.customer_id,Customer.business_id==d.business_id,
             (Customer.uuid==w.wallet_uuid)|(Customer.wallet_uuid==w.wallet_uuid)).first()
        e=db.query(InboxEntry).filter_by(id=d.entry_id,business_id=d.business_id,category="marketing").first()
        if not c or not e: raise HTTPException(404,"Mesaj negasit")
        if not latest_offer_choice(db,Consent,c.id): raise HTTPException(403,"Ofertele sunt dezactivate")
        stamp=datetime.now(timezone.utc).isoformat()
        old=db.get(OfferReaction,delivery_id)
        if old: old.choice,old.updated_at=choice,stamp
        else: db.add(OfferReaction(delivery_id=delivery_id,business_id=c.business_id,customer_id=c.id,choice=choice,updated_at=stamp))
        if not d.read_at: d.read_at=stamp
        try: db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409,"Reincearca raspunsul")
        return {"choice":choice,"read":True}
    @r.get("/campaigns")
    def campaigns(biz=Depends(owner),db=Depends(session)):
        result=[]
        for e in db.query(InboxEntry).filter_by(business_id=biz.id,category="marketing").order_by(InboxEntry.id.desc()).limit(80):
            ds=db.query(InboxDelivery).filter_by(business_id=biz.id,entry_id=e.id).all()
            ids=[d.id for d in ds]; counts=Counter()
            for i in range(0,len(ids),400):
                for a in db.query(OfferReaction).filter(OfferReaction.business_id==biz.id,OfferReaction.delivery_id.in_(ids[i:i+400])): counts[a.choice]+=1
            result.append({"id":e.id,"subject":e.title,"stored_in_inbox":len(ds),"read":sum(bool(d.read_at) for d in ds),
                           "interested":counts["interested"],"not_interested":counts["not_interested"]})
        return result
    app.include_router(r)
