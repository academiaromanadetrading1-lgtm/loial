"""Receipt QR pilot: one verified transaction -> one Loial stamp + product history.

The fiscal QR on a statutory receipt is NOT assumed to contain products.
Merchants must import/submit line items from their sales software or manually
enter the receipt. A unique one-use Loial QR identifies the recorded transaction.
No access to SMS, WhatsApp, email, banking or fiscal systems.
"""
import base64
import hashlib
import hmac
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
from sqlalchemy.exc import IntegrityError

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

class ReceiptIntegration(ReceiptBase):
    __tablename__="loial_receipt_integrations"
    business_id=Column(Integer,primary_key=True)
    key_hash=Column(String(64),nullable=False,unique=True,index=True)
    updated_at=Column(String(40),nullable=False)

class SmartReservation(ReceiptBase):
    __tablename__="loial_smart_reservations"
    receipt_id=Column(Integer,primary_key=True)
    business_id=Column(Integer,nullable=False,index=True)
    wallet_uuid=Column(String(120),nullable=False)
    approval_hash=Column(String(64),nullable=False,unique=True,index=True)
    approval_expires=Column(String(40),nullable=False)
    confirmed_at=Column(String(40))
    staff_id=Column(Integer)

class StaffApproval(BaseModel):
    business_id:int
    pin:str=Field(min_length=4,max_length=4)
    approval_token:str=Field(min_length=32,max_length=100)

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
    requires_payment_confirmation: bool=False

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
                     jwt_secret,jwt_algorithm,StaffMember=None,limiter=None,can_enroll=None):
    ReceiptBase.metadata.create_all(bind=engine)
    router=APIRouter(prefix="/api/loial-receipts",tags=["Loial verified receipt QR"])
    # Receipt QR URLs must never point to a malformed external origin or
    # accidentally leave a staging deployment for the production domain.
    from loial_preflight import validated_public_origin
    public_origin=validated_public_origin(
        os.getenv("LOIAL_PUBLIC_ORIGIN","https://loial.space"),
        os.getenv("RAILWAY_ENVIRONMENT_NAME",""))

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
        if not biz or type(payload.get("business_id")) is not int or biz.id!=payload["business_id"]:
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

    def integration_token(bid,ref):
        return hmac.new(jwt_secret.encode() if isinstance(jwt_secret,str) else jwt_secret,
                        ("loial-print-v1:"+str(bid)+":"+ref).encode(),hashlib.sha256).hexdigest()

    @router.get("/integration")
    def integration_status(biz=Depends(owner),db:Session=Depends(database)):
        row=db.get(ReceiptIntegration,biz.id)
        return {"active":bool(row),"updated_at":row.updated_at if row else None,
                "endpoint":public_origin+"/api/loial-receipts/integration/issue"}

    @router.post("/integration/rotate")
    def integration_rotate(biz=Depends(owner),db:Session=Depends(database)):
        raw=secrets.token_urlsafe(32)
        row=db.get(ReceiptIntegration,biz.id)
        if row:
            row.key_hash=sha256(raw);row.updated_at=utc_now().isoformat()
        else:
            db.add(ReceiptIntegration(business_id=biz.id,key_hash=sha256(raw),updated_at=utc_now().isoformat()))
        db.commit()
        return {"api_key":raw,"notice":"Salveaza cheia in aplicatia de emitere. Cheia veche nu mai este valida."}

    @router.post("/integration/revoke")
    def integration_revoke(biz=Depends(owner),db:Session=Depends(database)):
        row=db.get(ReceiptIntegration,biz.id)
        if row: db.delete(row);db.commit()
        return {"active":False}

    @router.post("/integration/issue")
    @((limiter.limit("120/minute")) if limiter else (lambda f:f))
    def integration_issue(request:Request,payload:IssueReceipt,db:Session=Depends(database)):
        key=request.headers.get("X-Loial-Receipt-Key","").strip()
        if not 40<=len(key)<=100: raise HTTPException(401,"Cheie de integrare invalida")
        row=db.query(ReceiptIntegration).filter_by(key_hash=sha256(key)).first()
        if not row: raise HTTPException(401,"Cheie de integrare invalida")
        biz=db.get(BusinessAccount,row.business_id)
        if not biz: raise HTTPException(401,"Firma indisponibila")
        payload=payload.model_copy(update={"requires_payment_confirmation":True})
        return issue_record(payload,biz,db,integrated=True)

    @router.post("/issue")
    @((limiter.limit("30/minute")) if limiter else (lambda f:f))
    def issue(request:Request,payload:IssueReceipt,biz=Depends(owner),db:Session=Depends(database)):
        return issue_record(payload,biz,db)

    def issue_record(request,biz,db,integrated=False):
        ref=request.receipt_ref.strip()
        if len(ref)<2 or any(not row.product.strip() for row in request.lines):
            raise HTTPException(422,"Referinta sau produs invalid")
        duplicate=db.query(Receipt).filter(Receipt.business_id==biz.id,
                                           Receipt.receipt_ref==ref).first()
        if duplicate:
            if integrated and duplicate.status in ("awaiting_payment","reserved"):
                doc=db.query(AIDocument).filter_by(id=duplicate.document_id,business_id=biz.id).first()
                data=json.loads(doc.data_json or "{}") if doc else {}
                signature=sha256(request.model_dump_json())
                raw=integration_token(biz.id,ref)
                if data.get("integration_signature")==signature and datetime.fromisoformat(duplicate.expires_at)>utc_now() and hmac.compare_digest(duplicate.claim_hash,sha256(raw)):
                    return issue_result(duplicate,raw)
            raise HTTPException(status_code=409,detail="Bonul a fost deja inregistrat in aceasta firma")
        total=monetary_total(request.lines)
        if total<=0 or total>Decimal("100000000"):
            raise HTTPException(status_code=422,detail="Totalul bonului trebuie sa fie pozitiv si rezonabil")
        if request.currency.upper() not in {"RON","EUR","USD","GBP"}:
            raise HTTPException(status_code=422,detail="Moneda nu este suportata")
        raw=integration_token(biz.id,ref) if integrated else secrets.token_urlsafe(32)
        timestamp=utc_now()
        deadline=timestamp+timedelta(days=request.expires_days)
        rows=[{"product":r.product.strip(),"sku":r.sku.strip(),
               "quantity":r.quantity,"unit_price":r.unit_price,
               "unit_variable_cost":r.unit_variable_cost} for r in request.lines]
        data={"kind":"receipt","rows":rows,"total":str(total),
              "currency":request.currency.upper(),"receipt_ref":ref,
              "notes":["Date introduse/importate de comerciant; nu sunt obtinute automat din QR-ul fiscal."]}
        if integrated: data["integration_signature"]=sha256(request.model_dump_json())
        pending=request.requires_payment_confirmation
        doc=AIDocument(business_id=biz.id,filename="bon-"+ref[:80],
                       sha256=sha256(str(biz.id)+":"+ref),kind="receipt_pending" if pending else "receipt",
                       data_json=json.dumps(data,ensure_ascii=False),
                       confirmed=0 if pending else 1,created_at=timestamp.isoformat())
        db.add(doc)
        try: db.flush()
        except IntegrityError:
            db.rollback();raise HTTPException(409,"Tichet deja inregistrat")
        receipt=Receipt(business_id=biz.id,receipt_ref=ref,claim_hash=sha256(raw),
                        status="awaiting_payment" if pending else "issued",document_id=doc.id,total_minor=int(total*100),
                        currency=request.currency.upper(),issued_at=timestamp.isoformat(),
                        expires_at=deadline.isoformat())
        db.add(receipt)
        for n,row in enumerate(rows if not pending else []):
            db.add(AISale(business_id=biz.id,document_id=doc.id,row_number=n,
                          sold_at=timestamp.date().isoformat(),transaction_id=ref,
                          product=row["product"],quantity=row["quantity"],
                          unit_price=row["unit_price"],unit_variable_cost=row["unit_variable_cost"],
                          customer_uuid=None))
        try:
            db.commit()
        except IntegrityError:
            db.rollback();raise HTTPException(409,"Tichet deja inregistrat")
        return issue_result(receipt,raw)

    def issue_result(receipt,raw):
        url=public_origin+"/loial-receipt.html?token="+quote(raw,safe="")
        return {"receipt_id":receipt.id,"status":receipt.status,"claim_url":url,
                "qr_png_base64":"data:image/png;base64,"+create_receipt_qr_png(url),
                "total":receipt.total_minor/100,"currency":receipt.currency,
                "expires_at":receipt.expires_at,
                "notice":"QR Loial unic. Se poate imprima separat sau prin POS compatibil. Nu inlocuieste bonul fiscal."}

    @router.get("/preview")
    @((limiter.limit("30/minute")) if limiter else (lambda f:f))
    def preview(request:Request,token:str,db:Session=Depends(database)):
        if not (32<=len(token)<=200):
            raise HTTPException(status_code=422,detail="Cod de bon invalid")
        record=receipt_for_token(db,token)
        if record.status in ('claimed','refunded'):
            return {'merchant':'Loial','business_id':record.business_id,'receipt_ref':'','currency':record.currency,'total':0,'products':[],'status':record.status,'expires_at':record.expires_at}
        return receipt_info(db,record)

    @router.post("/claim")
    @((limiter.limit("20/minute")) if limiter else (lambda f:f))
    def claim(request:Request,req:ReceiptClaim,access=Depends(wallet),db:Session=Depends(database)):
        receipt=receipt_for_token(db,req.receipt_token)
        if receipt.status in ("awaiting_payment","reserved"):
            raise HTTPException(409,"Nota necesita confirmarea incasarii de catre angajat")
        if receipt.status!="issued":
            raise HTTPException(status_code=409,detail="Bonul a fost deja folosit sau anulat")
        if datetime.fromisoformat(receipt.expires_at)<utc_now():
            raise HTTPException(status_code=410,detail="Termenul de revendicare al bonului a expirat")
        return finalize(receipt,access.wallet_uuid,db,'issued')

    def finalize(receipt,wallet_uuid,db,expected_status):
        biz=db.query(BusinessAccount).filter(
            BusinessAccount.id==receipt.business_id).first()
        if not biz:
            raise HTTPException(status_code=404,detail="Firma nu mai exista")
        customer=db.query(Customer).filter(
            Customer.business_id==biz.id,
            (Customer.wallet_uuid==wallet_uuid) |
            (Customer.uuid==wallet_uuid)).first()
        if not customer:
            existing=db.query(Customer).filter(
                (Customer.wallet_uuid==wallet_uuid) |
                (Customer.uuid==wallet_uuid)).first()
            if not existing:
                raise HTTPException(status_code=409,detail="Activeaza un card Loial inainte sa revendici bonul")
            if can_enroll and not can_enroll(db,biz.id):
                raise HTTPException(403,"LIMIT_REACHED")
            customer=Customer(uuid=str(uuid.uuid4()),wallet_uuid=wallet_uuid,
                              name=existing.name,email=existing.email,
                              phone=existing.phone,business_id=biz.id,stamps=0,
                              last_visit=utc_now().isoformat())
            db.add(customer);db.flush()
        target=getattr(biz,"stamps_required",None) or 6
        if expected_status!="reserved" and (customer.stamps or 0)>=target:
            raise HTTPException(status_code=409,detail="Revendica mai intai recompensa existenta")
        claimed=utc_now()
        # Expiry is checked as part of the same atomic claim transition, not
        # solely before it (the ticket may expire during receipt processing).
        statement=(update(Receipt).where(
                    Receipt.id==receipt.id,
                    Receipt.status==expected_status,
                    Receipt.expires_at>claimed.isoformat())
                   .values(status="claimed",claimed_wallet=wallet_uuid,
                           claimed_at=claimed.isoformat()))
        if db.execute(statement).rowcount!=1:
            db.rollback()
            raise HTTPException(status_code=409,detail="Bonul a fost deja revendicat")
        if expected_status=='reserved':
            doc=db.query(AIDocument).filter_by(id=receipt.document_id,business_id=biz.id).one()
            doc.kind='receipt';doc.confirmed=1
            for n,row in enumerate(json.loads(doc.data_json)['rows']):
                db.add(AISale(business_id=biz.id,document_id=doc.id,row_number=n,sold_at=claimed.date().isoformat(),transaction_id=receipt.receipt_ref,product=row['product'],quantity=row['quantity'],unit_price=row['unit_price'],unit_variable_cost=row.get('unit_variable_cost'),customer_uuid=wallet_uuid))
            db.flush()
        previous=customer.last_visit
        # A paid purchase must remain in CRM even when the reward is already available.
        from sqlalchemy import func
        stamp_granted=db.execute(update(Customer).where(Customer.id==customer.id,func.coalesce(Customer.stamps,0)<target).values(stamps=func.coalesce(Customer.stamps,0)+1)).rowcount==1
        db.refresh(customer)
        customer.last_visit=claimed.isoformat()
        matching=db.query(AISale).filter(
            AISale.business_id==biz.id,AISale.document_id==receipt.document_id).all()
        for line in matching:
            line.customer_uuid=wallet_uuid
        away=False
        if previous:
            try:
                away=(claimed-datetime.fromisoformat(previous.replace("Z","+00:00"))).days>=30
            except (ValueError,TypeError):
                pass
        if stamp_granted:
            queue_service_event(db,biz,customer,kind="stamp",returning=away,
                                event_key="receipt-"+str(receipt.id))
            from loial_scans import record_award
            record_award(db,biz.id,customer.id,"receipt:"+str(receipt.id),
                         "receipt",customer.stamps)
            from loial_friend_referrals import credit_after_valid_stamp
            credit_after_valid_stamp(db,wallet_uuid,biz.id,
                                     "receipt:"+str(receipt.id))
        # A redeemed, single-use receipt is a confirmed visit even when the
        # stamp target is already reached. Count it once, never infer revenue.
        from loial_winback_campaigns import attribute_confirmed_visit
        attribute_confirmed_visit(db,biz.id,customer.id,
                                  "receipt:"+str(receipt.id),at=claimed)
        from loial_wallet_sync import queue_google_refresh
        queue_google_refresh(db,biz.id,wallet_uuid)
        from loial_apple_updates import mark_customer_pass_changed
        mark_customer_pass_changed(db,biz.id,wallet_uuid)
        db.commit()
        return {"status":"claimed","stamp_granted":stamp_granted,"stamps":customer.stamps,"target":target,
                "reward_unlocked":customer.stamps>=target,
                "linked_products":len(matching),"business":biz.name}

    @router.post("/reserve")
    @((limiter.limit("20/minute")) if limiter else (lambda f:f))
    def reserve(request:Request,req:ReceiptClaim,access=Depends(wallet),db:Session=Depends(database)):
        rec=receipt_for_token(db,req.receipt_token)
        now=utc_now()
        if rec.status not in ("awaiting_payment","reserved"): raise HTTPException(409,"Tichet indisponibil")
        if datetime.fromisoformat(rec.expires_at)<now: raise HTTPException(410,"Tichet expirat")
        raw=secrets.token_urlsafe(32)
        deadline=min(now+timedelta(minutes=3),datetime.fromisoformat(rec.expires_at))
        if rec.status=="awaiting_payment":
            # The precheck alone is insufficient: expiry may change while
            # preparing the reservation. Only reserve an unexpired receipt.
            if db.execute(update(Receipt).where(
                Receipt.id==rec.id,
                Receipt.status=="awaiting_payment",
                Receipt.expires_at>now.isoformat()
            ).values(status="reserved")).rowcount!=1:
                db.rollback();raise HTTPException(409,"Tichet expirat sau deja rezervat")
            db.add(SmartReservation(receipt_id=rec.id,business_id=rec.business_id,wallet_uuid=access.wallet_uuid,approval_hash=sha256(raw),approval_expires=deadline.isoformat()))
        else:
            changed=db.execute(update(SmartReservation).where(SmartReservation.receipt_id==rec.id,SmartReservation.wallet_uuid==access.wallet_uuid,SmartReservation.confirmed_at.is_(None)).values(approval_hash=sha256(raw),approval_expires=deadline.isoformat())).rowcount
            if changed!=1: db.rollback();raise HTTPException(409,"Tichet rezervat altui portofel sau deja confirmat")
        db.commit()
        url=public_origin+"/scan.html?receipt_approval="+quote(raw,safe="")
        return {"status":"reserved","approval_qr":"data:image/png;base64,"+create_receipt_qr_png(url),"expires_at":deadline.isoformat()}

    @router.post("/confirm-payment")
    @((limiter.limit("20/minute")) if limiter else (lambda f:f))
    def confirm_payment(request:Request,req:StaffApproval,db:Session=Depends(database)):
        biz=db.query(BusinessAccount).filter_by(id=req.business_id).first()
        if not biz or req.pin=="1234": raise HTTPException(401,"Terminal neautorizat")
        staff=db.query(StaffMember).filter_by(business_id=biz.id,pin=req.pin,active=1).first() if StaffMember is not None else None
        if not staff and not (biz.staff_pin and biz.staff_pin==req.pin): raise HTTPException(401,"Terminal neautorizat")
        approval=db.query(SmartReservation).filter_by(business_id=biz.id,approval_hash=sha256(req.approval_token)).first()
        if not approval: raise HTTPException(404,"Cod de confirmare necunoscut")
        rec=db.query(Receipt).filter_by(id=approval.receipt_id,business_id=biz.id).first()
        if not rec or rec.status!="reserved" or approval.confirmed_at: raise HTTPException(409,"Tichet deja procesat sau anulat")
        now=utc_now()
        if any(datetime.fromisoformat(t)<now for t in (approval.approval_expires,rec.expires_at)):
            raise HTTPException(410,"Cod expirat; clientul poate regenera codul")
        # Validate expiry inside the same conditional UPDATE that consumes the
        # staff approval. A ticket can expire after the preliminary read.
        changed=db.execute(update(SmartReservation).where(
            SmartReservation.receipt_id==rec.id,
            SmartReservation.confirmed_at.is_(None),
            SmartReservation.approval_hash==sha256(req.approval_token),
            SmartReservation.approval_expires>now.isoformat()
        ).values(confirmed_at=now.isoformat(),
                 staff_id=staff.id if staff else None)).rowcount
        if changed!=1: db.rollback();raise HTTPException(409,"Confirmare deja procesata")
        if staff: staff.scans_count=(staff.scans_count or 0)+1
        return finalize(rec,approval.wallet_uuid,db,"reserved")

    @router.get("/payment-status")
    @((limiter.limit("60/minute")) if limiter else (lambda f:f))
    def payment_status(request:Request,token:str,access=Depends(wallet),db:Session=Depends(database)):
        rec=receipt_for_token(db,token)
        if rec.status not in ("reserved","claimed","refunded"): return {"status":rec.status}
        reservation=db.get(SmartReservation,rec.id)
        if not reservation or reservation.wallet_uuid!=access.wallet_uuid: raise HTTPException(404,"Tichet negasit")
        if rec.status=="claimed":
            customer=db.query(Customer).filter(Customer.business_id==rec.business_id,(Customer.wallet_uuid==access.wallet_uuid)|(Customer.uuid==access.wallet_uuid)).first()
            from loial_scans import StampAward
            award=db.query(StampAward).filter_by(business_id=rec.business_id,operation_key="receipt:"+str(rec.id),source="receipt").first()
            return {"status":"claimed","stamps":customer.stamps if customer else None,"stamp_granted":bool(award)}
        return {"status":rec.status}

    @router.post("/refund")
    @((limiter.limit("20/minute")) if limiter else (lambda f:f))
    def refund(request:Request,req:ReceiptRefund,biz=Depends(owner),db:Session=Depends(database)):
        r=db.query(Receipt).filter(Receipt.business_id==biz.id,
                                   Receipt.receipt_ref==req.receipt_ref.strip()).first()
        if not r:
            raise HTTPException(status_code=404,detail="Bonul nu exista in aceasta firma")
        if r.status=="refunded":
            return {"status":"already_refunded"}
        previous_status=r.status
        previously_claimed=previous_status=="claimed"
        if db.execute(update(Receipt).where(Receipt.id==r.id,Receipt.status==previous_status).values(status="refunded")).rowcount!=1:
            db.rollback();raise HTTPException(409,"Starea tichetului s-a modificat; actualizeaza")
        reversed_stamp=False
        if previously_claimed and r.claimed_wallet:
            from loial_scans import StampAward, record_award
            award=db.query(StampAward).filter(
                StampAward.business_id==biz.id,
                StampAward.operation_key=="receipt:"+str(r.id),
                StampAward.source=="receipt").first()
            if award:
                customer=db.query(Customer).filter(
                    Customer.id==award.customer_id,
                    Customer.business_id==biz.id).first()
                latest=db.query(StampAward).filter(
                    StampAward.business_id==biz.id,
                    StampAward.customer_id==award.customer_id
                ).order_by(StampAward.id.desc()).first()
                # Safe rollback only when the refunded receipt is the latest
                # loyalty event; never retract a reward already redeemed.
                if (customer and latest and latest.id==award.id and
                    (customer.stamps or 0)==award.stamps_after and
                    award.stamps_after>0):
                    # A concurrent scan or redemption may change this
                    # balance after the ORM read. Compare-and-swap prevents
                    # overwriting the new balance during refund processing.
                    changed=db.execute(update(Customer).where(
                        Customer.id==customer.id,
                        Customer.business_id==biz.id,
                        Customer.stamps==award.stamps_after
                    ).values(stamps=award.stamps_after-1)).rowcount
                    if changed==1:
                        db.refresh(customer)
                        record_award(db,biz.id,customer.id,
                                     "refund:"+str(r.id),"refund",customer.stamps)
                        queue_service_event(db,biz,customer,kind="reversal",
                                            event_key=str(r.id))
                        from loial_wallet_sync import queue_google_refresh
                        from loial_apple_updates import mark_customer_pass_changed
                        queue_google_refresh(db,biz.id,r.claimed_wallet)
                        mark_customer_pass_changed(db,biz.id,r.claimed_wallet)
                        reversed_stamp=True
        if previously_claimed and r.claimed_wallet:
            from loial_friend_referrals import reverse_referral_for_refunded_receipt
            reverse_referral_for_refunded_receipt(
                db,r.claimed_wallet,"receipt:"+str(r.id))
        r.status="refunded"
        doc=db.query(AIDocument).filter(AIDocument.id==r.document_id,
                                        AIDocument.business_id==biz.id).first()
        if doc:
            doc.kind="receipt_refunded"
            extracted=json.loads(doc.data_json or "{}")
            notes=extracted.setdefault("notes",[])
            notes.append("Bon returnat de comerciant. Motiv: "+req.reason.strip()[:200])
            doc.data_json=json.dumps(extracted,ensure_ascii=False)
        db.commit()
        manual_review=previously_claimed and not reversed_stamp
        return {"status":"refunded","financial_data_excluded":True,
                "stamp_reversed":reversed_stamp,
                "loyalty_review_required":manual_review,
                "notice":("Bonul si stampila aferenta au fost anulate."
                           if reversed_stamp else
                          "Bonul a fost exclus din vanzari; verifica manual recompensa daca a fost folosita.")}

    @router.get("/recent")
    def recent(biz=Depends(owner),db:Session=Depends(database)):
        data=db.query(Receipt).filter(Receipt.business_id==biz.id).order_by(
            Receipt.id.desc()).limit(100).all()
        return [{"id":r.id,"receipt_ref":r.receipt_ref,
                 "status":r.status,"total":round(r.total_minor/100,2),
                 "currency":r.currency,"issued_at":r.issued_at,
                 "claimed":r.claimed_at is not None} for r in data]

    app.include_router(router)
