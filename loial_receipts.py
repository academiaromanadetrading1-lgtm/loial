"""Receipt QR pilot: one verified transaction -> one Loial stamp + product history.

The fiscal QR on a statutory receipt is NOT assumed to contain products.
Merchants must import/submit line items from their sales software or manually
enter the receipt. A unique one-use Loial QR identifies the recorded transaction.
No access to SMS, WhatsApp, email, banking or fiscal systems.
"""
import base64
import hashlib
import io
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional
from urllib.parse import quote

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Text, UniqueConstraint, update
from sqlalchemy.orm import Session, declarative_base

from loial_inbox import WalletInboxAccess, access_hash, queue_service_event
from loial_analytics import money

ReceiptBase = declarative_base()

class Receipt(ReceiptBase):
    __tablename__="loial_transaction_receipts"
    id=Column(Integer,primary_key=True)
    business_id=Column(Integer,nullable=False,index=True)
    receipt_ref=Column(String(100),nullable=False)
    claim_hash=Column(String(64),nullable=False,unique=True,index=True)
    status=Column(String(20),nullable=False,default="issued")
    document_id=Column(Integer,nullable=False)
    total_minor=Column(Integer,nullable=False)
    currency=Column(String(3),default="RON")
    issued_at=Column(String(40),nullable=False)
    expires_at=Column(String(40),nullable=False)
    claimed_at=Column(String(40))
    claimed_wallet=Column(String(120))
    __table_args__=(UniqueConstraint("business_id","receipt_ref",name="uq_loial_receipt_per_merchant"),)

class ReceiptLine(BaseModel):
    product: str = Field(min_length=1,max_length=160)
    sku: str = Field(default="",max_length=60)
    quantity: float=Field(gt=0,le=10000)
    unit_price: float=Field(ge=0,le=10000000)
    unit_variable_cost: Optional[float]=Field(default=None,ge=0,le=10000000)

class IssueReceipt(BaseModel):
    receipt_ref: str=Field(min_length=2,max_length=100)
    lines: List[ReceiptLine]=Field(min_length=1,max_length=100)
    currency: str=Field(default="RON",min_length=3,max_length=3)
    expires_days: int=Field(default=30,ge=1,le=60)

class ReceiptClaim(BaseModel):
    receipt_token: str=Field(min_length=32,max_length=200)

class ReceiptRefund(BaseModel):
    receipt_ref: str=Field(min_length=2,max_length=100)
    reason: str=Field(min_length=4,max_length=240)

def utc_now():
    return datetime.now(timezone.utc)

def sha256(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def monetary_total(lines):
    total=Decimal("0")
    for line in lines:
        quantity=money(line.quantity)
        price=money(line.unit_price)
        total+=quantity*price
    return total.quantize(Decimal(".01"))

def create_receipt_qr_png(url):
    output=io.BytesIO()
    img=qrcode.make(url,error_correction=qrcode.constants.ERROR_CORRECT_M)
    img.save(output,format="PNG")
    return base64.b64encode(output.getvalue()).decode()

def install_receipts(app,engine,factory,BusinessAccount,Customer,AIDocument,AISale,
                     jwt_secret,jwt_algorithm):
    ReceiptBase.metadata.create_all(bind=engine)
    router=APIRouter(prefix="/api/loial-receipts",tags=["Loial verified receipt QR"])

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
            payload=jwt.decode(auth[7:],jwt_secret,algorithms=[jwt_algorithm])
        except JWTError:
            raise HTTPException(status_code=401,detail="Sesiune invalida")
        if payload.get("role")!="business":
            raise HTTPException(status_code=403,detail="Doar administratorul firmei")
        biz=db.query(BusinessAccount).filter(
            BusinessAccount.email==payload.get("sub")).first()
        if not biz or (payload.get("business_id") and biz.id!=payload["business_id"]):
            raise HTTPException(status_code=403,detail="Firma nu este disponibila")
        return biz

    def wallet(request:Request,db:Session=Depends(database)):
        token=(request.headers.get("X-Loial-Wallet-Token") or "").strip()
        if not (40<=len(token)<=180):
            raise HTTPException(status_code=401,detail="Activeaza portofelul personal Loial")
        entry=db.query(WalletInboxAccess).filter(
            WalletInboxAccess.token_hash==access_hash(token)).first()
        if not entry:
            raise HTTPException(status_code=401,detail="Dispozitivul nu este verificat")
        return entry

    def receipt_for_token(db,token):
        r=db.query(Receipt).filter(Receipt.claim_hash==sha256(token)).first()
        if not r:
            raise HTTPException(status_code=404,detail="Bon Loial necunoscut")
        return r

    def receipt_info(db,record):
        biz=db.query(BusinessAccount).filter(BusinessAccount.id==record.business_id).first()
        doc=db.query(AIDocument).filter(AIDocument.id==record.document_id).first()
        data=json.loads(doc.data_json or "{}") if doc else {}
        return {"merchant":biz.name if biz else "Afacere Loial",
                "business_id":record.business_id,"receipt_ref":record.receipt_ref,
                "currency":record.currency,"total":round(record.total_minor/100,2),
                "products":[{"name":item["product"],"qty":item["quantity"],
                             "price":item["unit_price"]} for item in data.get("rows",[])],
                "status":record.status,"expires_at":record.expires_at}

    @router.post("/issue")
    def issue(request:IssueReceipt,biz=Depends(owner),db:Session=Depends(database)):
        ref=request.receipt_ref.strip()
        duplicate=db.query(Receipt).filter(Receipt.business_id==biz.id,
                                           Receipt.receipt_ref==ref).first()
        if duplicate:
            raise HTTPException(status_code=409,detail="Bonul a fost deja inregistrat in aceasta firma")
        total=monetary_total(request.lines)
        if total<=0 or total>Decimal("100000000"):
            raise HTTPException(status_code=422,detail="Totalul bonului trebuie sa fie pozitiv si rezonabil")
        if request.currency.upper() not in {"RON","EUR","USD","GBP"}:
            raise HTTPException(status_code=422,detail="Moneda nu este suportata")
        raw=secrets.token_urlsafe(32)
        timestamp=utc_now()
        deadline=timestamp+timedelta(days=request.expires_days)
        rows=[{"product":r.product.strip(),"sku":r.sku.strip(),
               "quantity":r.quantity,"unit_price":r.unit_price,
               "unit_variable_cost":r.unit_variable_cost} for r in request.lines]
        data={"kind":"receipt","rows":rows,"total":str(total),
              "currency":request.currency.upper(),"receipt_ref":ref,
              "notes":["Date introduse/importate de comerciant; nu sunt obtinute automat din QR-ul fiscal."]}
        doc=AIDocument(business_id=biz.id,filename="bon-"+ref[:80],
                       sha256=sha256(str(biz.id)+":"+ref),kind="receipt",
                       data_json=json.dumps(data,ensure_ascii=False),
                       confirmed=1,created_at=timestamp.isoformat())
        db.add(doc);db.flush()
        receipt=Receipt(business_id=biz.id,receipt_ref=ref,claim_hash=sha256(raw),
                        status="issued",document_id=doc.id,total_minor=int(total*100),
                        currency=request.currency.upper(),issued_at=timestamp.isoformat(),
                        expires_at=deadline.isoformat())
        db.add(receipt)
        for n,row in enumerate(rows):
            db.add(AISale(business_id=biz.id,document_id=doc.id,row_number=n,
                          sold_at=timestamp.date().isoformat(),transaction_id=ref,
                          product=row["product"],quantity=row["quantity"],
                          unit_price=row["unit_price"],unit_variable_cost=row["unit_variable_cost"],
                          customer_uuid=None))
        db.commit()
        url="https://loial.space/loial-receipt.html?token="+quote(raw,safe="")
        return {"receipt_id":receipt.id,"status":"issued","claim_url":url,
                "qr_png_base64":"data:image/png;base64,"+create_receipt_qr_png(url),
                "total":float(total),"currency":receipt.currency,
                "expires_at":receipt.expires_at,
                "notice":"QR Loial unic. Se poate imprima separat sau prin POS compatibil. Nu inlocuieste bonul fiscal."}

    @router.get("/preview")
    def preview(token:str,db:Session=Depends(database)):
        if not (32<=len(token)<=200):
            raise HTTPException(status_code=422,detail="Cod de bon invalid")
        record=receipt_for_token(db,token)
        return receipt_info(db,record)

    @router.post("/claim")
    def claim(req:ReceiptClaim,access=Depends(wallet),db:Session=Depends(database)):
        receipt=receipt_for_token(db,req.receipt_token)
        if receipt.status!="issued":
            raise HTTPException(status_code=409,detail="Bonul a fost deja folosit sau anulat")
        if datetime.fromisoformat(receipt.expires_at)<utc_now():
            raise HTTPException(status_code=410,detail="Termenul de revendicare al bonului a expirat")
        biz=db.query(BusinessAccount).filter(
            BusinessAccount.id==receipt.business_id).first()
        if not biz:
            raise HTTPException(status_code=404,detail="Firma nu mai exista")
        customer=db.query(Customer).filter(
            Customer.business_id==biz.id,
            (Customer.wallet_uuid==access.wallet_uuid) |
            (Customer.uuid==access.wallet_uuid)).first()
        if not customer:
            existing=db.query(Customer).filter(
                (Customer.wallet_uuid==access.wallet_uuid) |
                (Customer.uuid==access.wallet_uuid)).first()
            if not existing:
                raise HTTPException(status_code=409,detail="Activeaza un card Loial inainte sa revendici bonul")
            customer=Customer(uuid=str(uuid.uuid4()),wallet_uuid=access.wallet_uuid,
                              name=existing.name,email=existing.email,
                              phone=existing.phone,business_id=biz.id,stamps=0,
                              last_visit=utc_now().isoformat())
            db.add(customer);db.flush()
        target=getattr(biz,"stamps_required",None) or 6
        if (customer.stamps or 0)>=target:
            raise HTTPException(status_code=409,detail="Revendica mai intai recompensa existenta")
        claimed=utc_now()
        statement=(update(Receipt).where(Receipt.id==receipt.id,Receipt.status=="issued")
                   .values(status="claimed",claimed_wallet=access.wallet_uuid,
                           claimed_at=claimed.isoformat()))
        if db.execute(statement).rowcount!=1:
            db.rollback()
            raise HTTPException(status_code=409,detail="Bonul a fost deja revendicat")
        previous=customer.last_visit
        customer.stamps=(customer.stamps or 0)+1
        customer.last_visit=claimed.isoformat()
        matching=db.query(AISale).filter(
            AISale.business_id==biz.id,AISale.document_id==receipt.document_id).all()
        for line in matching:
            line.customer_uuid=access.wallet_uuid
        away=False
        if previous:
            try:
                away=(claimed-datetime.fromisoformat(previous.replace("Z","+00:00"))).days>=30
            except (ValueError,TypeError):
                pass
        queue_service_event(db,biz,customer,kind="stamp",returning=away,
                            event_key="receipt-"+str(receipt.id))
        from loial_wallet_sync import queue_google_refresh
        queue_google_refresh(db,biz.id,access.wallet_uuid)
        from loial_apple_updates import mark_customer_pass_changed
        mark_customer_pass_changed(db,biz.id,access.wallet_uuid)
        db.commit()
        return {"status":"claimed","stamps":customer.stamps,"target":target,
                "reward_unlocked":customer.stamps>=target,
                "linked_products":len(matching),"business":biz.name}

    @router.post("/refund")
    def refund(req:ReceiptRefund,biz=Depends(owner),db:Session=Depends(database)):
        r=db.query(Receipt).filter(Receipt.business_id==biz.id,
                                   Receipt.receipt_ref==req.receipt_ref.strip()).first()
        if not r:
            raise HTTPException(status_code=404,detail="Bonul nu exista in aceasta firma")
        if r.status=="refunded":
            return {"status":"already_refunded"}
        previously_claimed=r.status=="claimed"
        r.status="refunded"
        doc=db.query(AIDocument).filter(AIDocument.id==r.document_id,
                                        AIDocument.business_id==biz.id).first()
        if doc:
            doc.kind="receipt_refunded"
        db.commit()
        return {"status":"refunded","financial_data_excluded":True,
                "loyalty_review_required":previously_claimed,
                "notice":"Bonul a fost exclus din analiza vanzarilor. Daca a generat o stampila, administratorul trebuie sa revizuiasca recompensa."}

    @router.get("/recent")
    def recent(biz=Depends(owner),db:Session=Depends(database)):
        data=db.query(Receipt).filter(Receipt.business_id==biz.id).order_by(
            Receipt.id.desc()).limit(100).all()
        return [{"id":r.id,"receipt_ref":r.receipt_ref,
                 "status":r.status,"total":round(r.total_minor/100,2),
                 "currency":r.currency,"issued_at":r.issued_at,
                 "claimed":r.claimed_at is not None} for r in data]

    app.include_router(router)
